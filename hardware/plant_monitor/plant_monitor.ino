#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include "Adafruit_seesaw.h"
#include "secrets.h"

Adafruit_seesaw ss;

void setup() {
  Serial.begin(115200);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("WiFi connected");

  Wire.begin(21, 22); // SDA, SCL
  if (!ss.begin(0x36)) {
    Serial.println("Sensor not found");
    while (1) delay(10);
  }
}

void loop() {
  uint16_t moisture = ss.touchRead(0);
  float tempC = ss.getTemp();   // API wants Celsius

  // Show for debugging (but in Fahrenheit if you like)
  float tempF = (tempC * 9.0 / 5.0) + 32.0;
  Serial.print("Moisture: "); Serial.print(moisture);
  Serial.print("  Temp F: "); Serial.println(tempF, 2);

  if (WiFi.status() == WL_CONNECTED) {
    // Debug prints
    Serial.print("ESP32 IP: "); Serial.println(WiFi.localIP());
    Serial.print("Trying: ");  Serial.println(API_URL);

    HTTPClient http;
    // Hardcode host/port/path for now to avoid parsing issues
    http.begin("192.168.12.178", 5000, "/readings");  // <-- use your PC's current IP
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(8000);

    String body = String("{\"moisture\":") + moisture + ",\"temperature\":" + tempC + "}";
    int code = http.POST(body);

    Serial.print("POST result: ");
    Serial.println(code);
    if (code > 0) Serial.println(http.getString());
    http.end();
  }

  delay(60000); // every minute
}
