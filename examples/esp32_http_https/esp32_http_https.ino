// Arduino-ESP32 example. Requires a local secrets.h based on secrets.example.h.
// Replace the simulated temperature with a real sensor reading before integration.
#include <WiFi.h>
#include <WiFiClient.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <math.h>
#include <time.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include "secrets.h"

constexpr int IR_PIN = 27;  // Change to your board wiring; example sensor is active LOW.
constexpr unsigned long SAMPLE_PERIOD_MS = 1000;
unsigned long lastSampleMs = 0;
struct SensorReading { float temperature; int infrared; };
QueueHandle_t latestReading = nullptr;

float readTemperatureC() {
  // TECHNICAL DEMO ONLY: replace with your DHT/DS18B20/etc. library call.
  // Return NAN on sensor failure so the invalid sample is not sent.
  return 29.2f;
}

void localSafetyTick(float temperature, int infrared) {
  // Connect your project's independent local alarm logic here.
  // The example only logs the signal; it does not implement a physical safety controller.
  if (infrared == 1) Serial.println("Local IR signal; check local alarm logic");
}

void sendSample(float temperature, int infrared) {
  if (WiFi.status() != WL_CONNECTED || !isfinite(temperature) || temperature < -40 || temperature > 125) {
    Serial.println("Sample not sent: network unavailable or invalid temperature");
    return;
  }
  String url = String(API_BASE_URL) + "/api/v1/sensor-data";
  WiFiClient plain;
  WiFiClientSecure secure;
  WiFiClient* transport = &plain;
  if (url.startsWith("https://")) {
    if (time(nullptr) < 1700000000 || strlen(API_ROOT_CA) == 0) {
      Serial.println("HTTPS needs a synchronized clock and a trusted root CA");
      return;
    }
    secure.setCACert(API_ROOT_CA);  // Verify TLS; do not replace with setInsecure().
    transport = &secure;
  } else if (!url.startsWith("http://")) {
    Serial.println("API_BASE_URL must start with http:// or https://");
    return;
  }
  HTTPClient http;
  if (!http.begin(*transport, url)) {
    Serial.println("Cannot initialize HTTP client");
    return;
  }
  http.setConnectTimeout(5000);
  http.setTimeout(5000);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-API-Key", API_KEY);
  String payload = String("{\"device_id\":\"") + DEVICE_ID + "\",\"temperature\":" +
                   String(temperature, 2) + ",\"infrared\":" + String(infrared) + "}";
  int code = http.POST(payload);
  if (code == 200) {
    Serial.println(http.getString());
  } else {
    Serial.printf("POST failed: %d (401=key, 422=input, 503=model; negative=transport)\n", code);
  }
  http.end();
  // No automatic POST replay: a timeout may occur after the server accepted the sample.
}

void sensorTask(void*) {
  // Network calls run separately so a slow HTTPS request does not block localSafetyTick().
  SensorReading sample;
  for (;;) {
    if (xQueueReceive(latestReading, &sample, portMAX_DELAY) == pdTRUE) {
      sendSample(sample.temperature, sample.infrared);
    }
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(IR_PIN, INPUT);
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  latestReading = xQueueCreate(1, sizeof(SensorReading));
  if (latestReading == nullptr || xTaskCreate(sensorTask, "sensor_http", 12288, nullptr, 1, nullptr) != pdPASS) {
    Serial.println("Cannot start network task; local loop remains active");
  }
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleMs >= SAMPLE_PERIOD_MS) {
    lastSampleMs = now;
    SensorReading sample = { readTemperatureC(), digitalRead(IR_PIN) == LOW ? 1 : 0 };
    localSafetyTick(sample.temperature, sample.infrared);
    // Keep the newest sample if HTTPS is slow; do not replay a backlog after reconnect.
    if (latestReading != nullptr) xQueueOverwrite(latestReading, &sample);
  }
  delay(5);
}
