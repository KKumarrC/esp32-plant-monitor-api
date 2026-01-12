#include <WiFi.h>
#include <WiFiClientSecure.h>
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
  Serial.println("\nWiFi connected");
  Serial.print("ESP32 IP: ");
  Serial.println(WiFi.localIP());

  Wire.begin(21, 22); // SDA, SCL
  if (!ss.begin(0x36)) {
    Serial.println("Sensor not found");
    while (1) delay(10);
  }
}

void loop() {
  uint16_t moisture = ss.touchRead(0);
  float tempC = ss.getTemp();   // API wants Celsius

  // Optional: debug print in Fahrenheit
  float tempF = (tempC * 9.0 / 5.0) + 32.0;
  Serial.print("Moisture: "); Serial.print(moisture);
  Serial.print("  Temp F: "); Serial.println(tempF, 2);

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Posting to: ");
    Serial.println(API_URL);

    WiFiClientSecure client;
    client.setInsecure(); // skip SSL cert validation (OK for this project)

    HTTPClient https;
    https.begin(client, API_URL); // API_URL should be full https://.../readings
    https.addHeader("Content-Type", "application/json");
    https.setTimeout(8000);

    String body =
      String("{\"device_id\":\"esp32-1\",\"moisture\":") + moisture +
      String(",\"temperature\":") + String(tempC, 2) +
      String("}");

    int code = https.POST(body);

    Serial.print("POST result: ");
    Serial.println(code);
    if (code > 0) {
      Serial.println(https.getString());
    } else {
      Serial.println("POST failed (check WiFi / HTTPS / URL)");
    }

    https.end();
  } else {
    Serial.println("WiFi not connected");
  }

  delay(60000); // every minute
}
