// Room microphone module for the home-automation Pi.
//
// An ESP32 with an ICS-43434 I2S microphone, inside a wall switch board.
// It does five things:
//   1. Connects to WiFi (and restarts itself if WiFi stays down).
//   2. Accepts firmware updates over WiFi from Arduino IDE (ArduinoOTA).
//   3. Sends log lines over WiFi:  nc <ip address> 23
//   4. Puts every new firmware on trial. If it cannot join WiFi and stay up for
//      60 seconds within 3 starts, the ESP32 switches back to the previous firmware.
//   5. Calls the Pi and sends it the microphone sound without end (16 kHz,
//      16-bit, mono), together with its own health. If the call fails or
//      drops, it calls again every few seconds, for ever.
//
// The module calls the Pi; nothing calls the module for sound. So a module
// needs no fixed address on the router. How the sound is packed is written in
// src/home_automation/services/mic_protocol.py. That file, this sketch and
// tests/fake_mic_module.py must be changed together.
//
// The same sketch goes on every module, with no edits per module:
//   - Each module names itself from its own hardware address, e.g. esp32-mic-a1b2.
//     Those 4 characters are the last 4 of the MAC address shown in the router.
//   - It finds out by itself whether the board has one mic or two (2CH board).
//     With two mics it mixes both into one mono stream.
//
// Parts 1 to 4 are taken over unchanged from the trial firmware (mic_wifi.ino),
// because they are the parts proven by the rollback tests. Do not change them
// without a strong reason, and try any change on a desk board first.
//
// Building and uploading: see firmware/README.md.

#include <WiFi.h>
#include <ArduinoOTA.h>
#include <Preferences.h>
#include <Update.h>
#include <stdarg.h>
#include <errno.h>
#include <lwip/sockets.h>
#include <driver/i2s.h>
#include <driver/gpio.h>

// WIFI_SSID, WIFI_PASS and OTA_PASS. Copy secrets.example.h to secrets.h and
// fill it in. secrets.h is ignored by git and must never be committed.
#include "secrets.h"

// ---- change this text on every upload, so the log proves the new code is running ----
#define FW_VERSION "mic-module-1"

// ---- where the sound goes: the Pi. The Pi has these same two values in
//      src/home_automation/config/application.py. Change both together. ----
const IPAddress PI_ADDRESS(192, 168, 1, 31);
#define PI_PORT 3334
#define PI_CONNECT_TIMEOUT_MS 1000          // how long one call to the Pi may take
#define PI_RETRY_MS 5000                    // wait between two calls
#define PI_STALL_MS 5000                    // hang up if nothing got through for this long

// ---- safety check for new firmware ----
#define TRIAL_MAX_STARTS 3                  // a new firmware gets this many starts to prove itself
#define TRIAL_PASS_MS 60000                 // it passes after running this long with WiFi connected
#define TEST_FAULT 0                        // testing only: 0 = normal, 1 = wrong WiFi password, 2 = crash at startup

char HOSTNAME[24] = "esp32-mic";            // becomes esp32-mic-xxxx in setup(), different on every module
#define LOG_PORT 23
#define LED_PIN 2                           // blue LED on the DevKit V1
#define WIFI_DOWN_RESTART_MS 60000          // restart if WiFi is down this long

// ---- microphone ----
#define I2S_SCK 14
#define I2S_WS  15
#define I2S_SD  32
#define SAMPLE_RATE 16000
#define FRAME_SAMPLES 256                   // 256 samples = 16 ms of sound per frame

// ---- frames sent to the Pi (see mic_protocol.py) ----
#define FRAME_HELLO  1
#define FRAME_AUDIO  2
#define FRAME_STATUS 3
#define FRAME_HEADER_BYTES 5                // 0xA5 0x5A, kind, length (2 bytes, low byte first)
#define AUDIO_FRAME_BYTES (FRAME_HEADER_BYTES + 4 + FRAME_SAMPLES * 2)
#define TX_CAPACITY (AUDIO_FRAME_BYTES * 16) // room for about a quarter of a second of sound

// Version text plus compile time. It changes on every build, so every new build
// goes on trial even if FW_VERSION was not changed.
const char* BUILD_ID = FW_VERSION " " __DATE__ " " __TIME__;

WiFiServer logServer(LOG_PORT);
WiFiClient logClient;
Preferences prefs;                          // small settings store that survives restarts and updates
bool onTrial = false;
String lastRollback;                        // build that was rejected last time, if any

WiFiClient piClient;
bool piConnected = false;
bool piTried = false;
bool piFailLogged = false;
unsigned long lastPiTryMs = 0;
unsigned long lastSendMs = 0;               // last time the Pi took some bytes
static uint8_t txBuf[TX_CAPACITY];          // frames waiting to go to the Pi
static size_t txLen = 0;
uint32_t audioSeq = 0;                      // counts every 16 ms block taken from the mic, sent or not
uint32_t droppedFrames = 0;                 // blocks that could not be sent since start

int micPeak = 0;                            // loudest sample since the last status line (max 32767)
bool twoMics = false;                       // becomes true when a second mic is seen (2CH board)
static int32_t i2sBuf[FRAME_SAMPLES * 2];   // 2 slots per frame, the mic is in the even one
static int16_t pcmBuf[FRAME_SAMPLES];

// Print one line to USB serial and, if someone is connected, to the WiFi log.
void logLine(const char* fmt, ...) {
  char buf[200];
  va_list args;
  va_start(args, fmt);
  vsnprintf(buf, sizeof(buf), fmt, args);
  va_end(args);
  Serial.println(buf);
  if (logClient && logClient.connected()) logClient.println(buf);
}

// Runs first thing at every start, before anything that could fail.
// Counts the starts of a firmware that has not proven itself yet,
// and switches back to the previous firmware after too many.
void checkTrialAtBoot() {
  prefs.begin("fwsafe", false);
  lastRollback = prefs.getString("rb", "");

  if (prefs.getString("good", "") == BUILD_ID) {
    onTrial = false;                        // this exact build already passed, never roll it back
    return;
  }

  onTrial = true;
  int starts = prefs.getInt("starts", 0);
  if (prefs.getString("trial", "") != BUILD_ID) {   // first start of a new build
    starts = 0;
    prefs.putString("trial", BUILD_ID);
  }
  starts++;
  prefs.putInt("starts", starts);
  Serial.printf("This firmware is on trial: start %d (allowed %d)\n", starts, TRIAL_MAX_STARTS);

  if (starts > TRIAL_MAX_STARTS) {
    if (Update.canRollBack()) {
      Serial.println("Trial failed. Switching back to the previous firmware.");
      prefs.putString("rb", BUILD_ID);
      prefs.putInt("starts", 0);
      prefs.remove("trial");
      Update.rollBack();
      delay(300);
      ESP.restart();
    } else {
      Serial.println("Trial failed, but there is no previous firmware to go back to. Staying on this one.");
    }
  }
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(HOSTNAME);
  WiFi.setSleep(false);                     // keeps WiFi responsive (matters for updates and sound)
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, TEST_FAULT == 1 ? "wrong-password-for-test" : WIFI_PASS);

  Serial.printf("Connecting to WiFi \"%s\"", WIFI_SSID);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    if (millis() - start > 30000) {
      Serial.println("\nNo WiFi after 30 s. Check the name and password. Restarting.");
      delay(1000);
      ESP.restart();
    }
  }
  Serial.println();
}

void setupMic() {
  i2s_config_t cfg = {
    .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
    .sample_rate = SAMPLE_RATE,
    .bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT,
    .channel_format = I2S_CHANNEL_FMT_RIGHT_LEFT,   // same setting that worked over USB
    .communication_format = I2S_COMM_FORMAT_STAND_I2S,
    .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
    .dma_buf_count = 8,
    .dma_buf_len = FRAME_SAMPLES,
    .use_apll = false,
    .tx_desc_auto_clear = false,
    .fixed_mclk = 0
  };
  i2s_pin_config_t pins = {
    .bck_io_num = I2S_SCK,
    .ws_io_num = I2S_WS,
    .data_out_num = I2S_PIN_NO_CHANGE,
    .data_in_num = I2S_SD
  };
  esp_err_t e1 = i2s_driver_install(I2S_NUM_0, &cfg, 0, NULL);
  esp_err_t e2 = i2s_set_pin(I2S_NUM_0, &pins);
  gpio_pulldown_en((gpio_num_t)I2S_SD);
  logLine("Mic setup: install=%d set_pin=%d (0 means OK)", (int)e1, (int)e2);
}

// ---- talking to the Pi ----

// Put one frame in the queue for the Pi. Queues nothing and returns false
// if there is no room. A frame is never queued in part.
bool queueFrame(uint8_t kind, const uint8_t* payload, size_t len) {
  size_t total = FRAME_HEADER_BYTES + len;
  if (txLen + total > TX_CAPACITY) return false;
  uint8_t* p = txBuf + txLen;
  p[0] = 0xA5;
  p[1] = 0x5A;
  p[2] = kind;
  p[3] = (uint8_t)(len & 0xFF);
  p[4] = (uint8_t)((len >> 8) & 0xFF);
  memcpy(p + FRAME_HEADER_BYTES, payload, len);
  txLen += total;
  return true;
}

// A frame of text lines "key=value" (the hello and the health).
bool queueText(uint8_t kind, const char* fmt, ...) {
  char buf[240];
  va_list args;
  va_start(args, fmt);
  vsnprintf(buf, sizeof(buf), fmt, args);
  va_end(args);
  return queueFrame(kind, (const uint8_t*)buf, strlen(buf));
}

// The 16 ms of sound in pcmBuf, with its counter in front.
bool queueAudio(uint32_t seq) {
  static uint8_t payload[4 + sizeof(pcmBuf)];
  memcpy(payload, &seq, 4);                 // the ESP32 stores numbers low byte first, as the Pi expects
  memcpy(payload + 4, pcmBuf, sizeof(pcmBuf));
  return queueFrame(FRAME_AUDIO, payload, sizeof(payload));
}

void disconnectPi(const char* why) {
  if (!piConnected) return;
  piClient.stop();
  piConnected = false;
  txLen = 0;                                // never carry half a frame into the next call
  logLine("Pi: disconnected (%s)", why);
}

// Call the Pi if we are not connected. A call that gets no answer takes up to
// PI_CONNECT_TIMEOUT_MS, so it is tried only every PI_RETRY_MS.
void connectPi() {
  if (piConnected || WiFi.status() != WL_CONNECTED) return;
  if (piTried && millis() - lastPiTryMs < PI_RETRY_MS) return;
  piTried = true;
  lastPiTryMs = millis();

  if (!piClient.connect(PI_ADDRESS, PI_PORT, PI_CONNECT_TIMEOUT_MS)) {
    if (!piFailLogged) {
      logLine("Pi: no answer at %s:%d, trying again every %d s",
              PI_ADDRESS.toString().c_str(), PI_PORT, PI_RETRY_MS / 1000);
      piFailLogged = true;
    }
    return;
  }

  piClient.setNoDelay(true);
  txLen = 0;
  piConnected = true;
  piFailLogged = false;
  lastSendMs = millis();

  // The first frame says who this is.
  queueText(FRAME_HELLO, "name=%s\nversion=%s\nbuild=%s\nrate=%d\nmics=%d",
            HOSTNAME, FW_VERSION, BUILD_ID, SAMPLE_RATE, twoMics ? 2 : 1);
  logLine("Pi: connected to %s:%d, sending sound", PI_ADDRESS.toString().c_str(), PI_PORT);
}

// Hand the queue to WiFi without ever waiting. What WiFi cannot take now
// stays in the queue for the next round.
void sendQueued() {
  if (!piConnected || txLen == 0) return;

  int sent = send(piClient.fd(), txBuf, txLen, MSG_DONTWAIT);
  if (sent > 0) {
    txLen -= (size_t)sent;
    if (txLen > 0) memmove(txBuf, txBuf + sent, txLen);
    lastSendMs = millis();
  } else if (sent < 0 && errno != EAGAIN && errno != EWOULDBLOCK) {
    disconnectPi("could not send");
    return;
  }

  if (millis() - lastSendMs > PI_STALL_MS) disconnectPi("nothing got through for 5 s");
}

// Reads 16 ms of sound from the mic and queues it for the Pi, if connected.
void handleAudio() {
  static float prevIn = 0, prevOut = 0;
  static bool first = true;

  if (piConnected && WiFi.status() != WL_CONNECTED) disconnectPi("WiFi lost");
  if (piConnected && !piClient.connected()) disconnectPi("the Pi closed the connection");

  // Always read the mic, so the level in the status line works without the Pi.
  // The 100 ms limit keeps updates over WiFi working even if the mic is dead.
  size_t bytesRead = 0;
  i2s_read(I2S_NUM_0, i2sBuf, sizeof(i2sBuf), &bytesRead, pdMS_TO_TICKS(100));
  if (bytesRead != sizeof(i2sBuf)) return;

  // Is there a second mic in the other slot? A real mic always shows some noise,
  // an empty slot reads a flat 0. Checked until found, then it stays on.
  if (!twoMics) {
    static int liveFrames = 0;
    int32_t minB = INT32_MAX, maxB = INT32_MIN;
    for (int i = 0; i < FRAME_SAMPLES; i++) {
      int32_t b = i2sBuf[i * 2 + 1] >> 8;
      if (b < minB) minB = b;
      if (b > maxB) maxB = b;
    }
    if (maxB - minB > 64) liveFrames++; else liveFrames = 0;
    if (liveFrames >= 20) {                        // about a third of a second in a row
      twoMics = true;
      logLine("Mic: second mic found, mixing both into one");
    }
  }

  for (int i = 0; i < FRAME_SAMPLES; i++) {
    int32_t s = i2sBuf[i * 2] >> 8;                // 24-bit value from the mic
    if (twoMics) s = (s + (i2sBuf[i * 2 + 1] >> 8)) / 2;   // average of both mics

    // Remove the constant offset (simple high-pass filter, about 13 Hz)
    if (first) { prevIn = (float)s; first = false; }
    float y = (float)s - prevIn + 0.995f * prevOut;
    prevIn = (float)s;
    prevOut = y;

    // 24-bit -> 16-bit, no extra gain here (loudness is added on the Pi side, when listening)
    int32_t v = (int32_t)(y / 256.0f);
    if (v > 32767) v = 32767;
    if (v < -32768) v = -32768;
    pcmBuf[i] = (int16_t)v;
    if (abs(v) > micPeak) micPeak = abs(v);
  }

  // Every block gets the next number, also one that cannot be sent. The jump
  // in the numbers tells the Pi exactly how much sound is missing.
  uint32_t seq = audioSeq++;
  if (piConnected) {
    if (!queueAudio(seq)) droppedFrames++;         // WiFi is behind: this block is lost
    sendQueued();
  }
}

void setupOta() {
  ArduinoOTA.setHostname(HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASS);
  ArduinoOTA.onStart([]() { disconnectPi("update starting"); logLine("OTA: update starting"); });
  ArduinoOTA.onEnd([]()   { logLine("OTA: update received, restarting"); });
  ArduinoOTA.onError([](ota_error_t error) { logLine("OTA: error %u, keeping the old firmware", (unsigned)error); });
  ArduinoOTA.begin();
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(LED_PIN, OUTPUT);

  // Name this module from its own hardware address, so every module gets a different name
  uint64_t mac = ESP.getEfuseMac();
  snprintf(HOSTNAME, sizeof(HOSTNAME), "esp32-mic-%02x%02x",
           (unsigned)((mac >> 32) & 0xFF), (unsigned)((mac >> 40) & 0xFF));

  Serial.printf("\nBooting, firmware %s\n", BUILD_ID);
  checkTrialAtBoot();
  if (TEST_FAULT == 2) {
    Serial.println("TEST: crashing on purpose");
    delay(200);
    abort();
  }

  connectWifi();
  setupOta();
  logServer.begin();
  digitalWrite(LED_PIN, HIGH);              // LED on = WiFi connected

  logLine("Ready. name=%s build=%s ip=%s", HOSTNAME, BUILD_ID, WiFi.localIP().toString().c_str());
  logLine("Log over WiFi: nc %s %d", WiFi.localIP().toString().c_str(), LOG_PORT);
  setupMic();
}

void loop() {
  ArduinoOTA.handle();
  connectPi();
  handleAudio();                            // takes about 16 ms, this paces the loop

  // Accept a new log viewer (the newest one replaces the old one)
  WiFiClient incoming = logServer.available();
  if (incoming) {
    if (logClient) logClient.stop();
    logClient = incoming;
    logLine("Log viewer connected. name=%s build=%s", HOSTNAME, BUILD_ID);
    logLine("Trial: %s. Last rejected firmware: %s",
            onTrial ? "ON TRIAL" : "passed",
            lastRollback.length() ? lastRollback.c_str() : "none");
  }

  // Restart if WiFi has been down too long (nobody can press a button inside a wall)
  static unsigned long wifiDownSince = 0;
  if (WiFi.status() == WL_CONNECTED) {
    wifiDownSince = 0;
    digitalWrite(LED_PIN, HIGH);
  } else {
    digitalWrite(LED_PIN, LOW);
    if (wifiDownSince == 0) wifiDownSince = millis();
    if (millis() - wifiDownSince > WIFI_DOWN_RESTART_MS) {
      Serial.println("WiFi down too long. Restarting.");
      delay(200);
      ESP.restart();
    }
  }

  // A new firmware passes its trial after running long enough with WiFi connected
  if (onTrial && WiFi.status() == WL_CONNECTED && millis() > TRIAL_PASS_MS) {
    prefs.putString("good", BUILD_ID);
    prefs.putInt("starts", 0);
    prefs.remove("trial");
    onTrial = false;
    logLine("Trial passed. This firmware is now saved as the last good one.");
  }

  // Every 5 seconds: one status line for the log, and the health for the Pi
  static unsigned long lastBeat = 0;
  if (millis() - lastBeat >= 5000) {
    lastBeat = millis();
    logLine("name=%s version=%s trial=%s uptime=%lus wifi_signal=%ddBm free_memory=%u pi=%s dropped=%u mics=%d mic_peak=%d",
            HOSTNAME, FW_VERSION, onTrial ? "yes" : "no", millis() / 1000, (int)WiFi.RSSI(), (unsigned)ESP.getFreeHeap(),
            piConnected ? "connected" : "no", (unsigned)droppedFrames, twoMics ? 2 : 1, micPeak);
    if (piConnected) {
      queueText(FRAME_STATUS, "uptime=%lu\nwifi_signal=%d\nfree_memory=%u\nmic_peak=%d\nmics=%d\ntrial=%s\ndropped=%u",
                millis() / 1000, (int)WiFi.RSSI(), (unsigned)ESP.getFreeHeap(),
                micPeak, twoMics ? 2 : 1, onTrial ? "yes" : "no", (unsigned)droppedFrames);
    }
    micPeak = 0;
  }
}
