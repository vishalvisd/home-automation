// Copy this file to secrets.h, in this same folder, and fill in the three
// values. secrets.h is ignored by git: it must never be committed, and the
// values must never be pasted into a chat.
//
// Every module uses the same three values.

#pragma once

const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASS = "YOUR_WIFI_PASSWORD";
const char* OTA_PASS  = "YOUR_UPDATE_PASSWORD";   // Arduino IDE asks for this on every WiFi upload
