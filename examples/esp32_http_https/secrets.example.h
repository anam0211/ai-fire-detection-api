#pragma once
// Copy to secrets.h locally. Never commit secrets.h.
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* DEVICE_ID = "esp32_01";  // 1..64 ASCII letters, digits, _ or -.
// No trailing slash. For local HTTP, use the server's LAN IP (not 127.0.0.1).
const char* API_BASE_URL = "https://YOUR-SERVICE.onrender.com";
const char* API_KEY = "REPLACE_WITH_THE_API_KEY_FROM_RENDER";
// Insert the PEM root CA that validates your deployed hostname's certificate chain.
// Obtain it from the certificate issuer's official repository; verify the fingerprint.
// An empty CA intentionally prevents HTTPS requests.
const char* API_ROOT_CA = "";
