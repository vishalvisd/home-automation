# Module firmware

Firmware for the devices that talk to the Pi. Each folder is one Arduino
sketch. Nothing here runs on the Pi.

| Folder | Device |
|---|---|
| `mic_module/` | Room microphone module: ESP32 + ICS-43434 I2S microphone |

## Room microphone module (`mic_module/`)

What it does, how the module is wired and which modules exist:
`docs/hardware-and-network.md`, "Room microphone modules". How it talks
to the Pi: `src/home_automation/services/mic_protocol.py`.

The same firmware goes on every module, with no edit per module. A
module names itself from its own MAC (`esp32-mic-2f20`) and calls the Pi
at `192.168.1.31` port `3334`. Both values are at the top of
`mic_module.ino`.

### Once per computer

1. Arduino IDE 2, with the board package **esp32 by Espressif**. The
   firmware is built and proven with version **2.0.6**; a newer major
   version (3.x) changes the I2S driver and is not tried.
2. In `firmware/mic_module/`, copy `secrets.example.h` to `secrets.h`
   and fill in the Wi-Fi name, the Wi-Fi password and the update
   password. `secrets.h` is ignored by git. Never commit it and never
   paste its values into a chat. Every module uses the same three
   values; the update password must be the one already on the modules,
   or they refuse an update over Wi-Fi.

### Settings in Arduino IDE

| Setting | Value |
|---|---|
| File > Open | `firmware/mic_module/mic_module.ino` |
| Tools > Board | ESP32 Dev Module |
| Tools > Partition Scheme | Default 4MB with spiffs (it has the two slots an update over Wi-Fi needs; "No OTA" and "Huge APP" break updates) |
| Serial monitor | 115200 baud |

Before every upload, change `FW_VERSION` at the top of the sketch, so
the log and the page prove the new code is running.

### A new board (first upload, by USB)

1. Plug the board straight into the computer, not through a hub (a hub
   starves it and it resets).
2. Tools > Port: the USB port. Upload.
3. If the upload stops at "Connecting....." with "Wrong boot mode
   detected", hold the BOOT button on the board while it connects.
4. Open the serial monitor. It prints the module's name, joins the
   Wi-Fi and, within a few seconds, "Pi: connected". The module then
   appears in the page by itself. Give it its room name there.

Never power the board from USB and from the mains supply at the same
time.

### A module already in a wall (update over Wi-Fi)

1. Tools > Port: under "network ports" pick the module by its name
   (`esp32-mic-2f20 at 192.168.1.x`). Upload, and type the update
   password when asked.
2. The module restarts into the new firmware **on trial**. Watch it:

   ```bash
   nc <module address> 23
   ```

   `nc` does not notice the restart; press Ctrl+C and connect again.
   After 60 seconds with Wi-Fi the log says "Trial passed". Do not cut
   the module's power while the status line says `trial=yes`.
3. The page shows the new firmware version for that module.

An upload that breaks half way is harmless: the old firmware keeps
running. A new firmware that cannot join the Wi-Fi, or crashes at
start, is thrown out by the module itself after 3 starts and the
previous one comes back. What this does **not** catch: a fault that
only shows after the first minute, or a firmware where Wi-Fi works but
the update code itself is broken. So the Wi-Fi, update and trial code
at the top of the sketch is not to be changed without a strong reason,
and any change to it goes on a desk board first.

Update one module, watch it for a while, then the next.

### The status line

Every 5 seconds on the log (USB serial and `nc <address> 23`):

```
name=esp32-mic-2f20 version=mic-module-1 trial=no uptime=70s wifi_signal=-74dBm free_memory=215352 pi=connected dropped=0 mics=2 mic_peak=370
```

- `pi=no`: the Pi does not answer on port 3334 (backend stopped, Pi
  off, or the main switch of the microphones is off in the page).
- `dropped`: blocks of 16 ms that could not be sent since the module
  started, because the Wi-Fi was behind. The Pi stores silence for them.
- `mic_peak=0`: the microphone sends nothing. Suspect a loose wire.
- `wifi_signal=0dBm`: Wi-Fi is not connected. Aim for -70 or better.

### Building without the IDE

Arduino IDE ships its own command-line tool. This compiles the sketch
(it needs `secrets.h` to exist) without uploading:

```bash
"/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli" compile --fqbn esp32:esp32:esp32 --build-path /tmp/mic_module_build firmware/mic_module
```

The build folder holds the passwords inside the compiled file. Delete
it afterwards.
