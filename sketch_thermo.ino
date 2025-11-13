// Define the modem model BEFORE including TinyGSM
#define TINY_GSM_MODEM_SIM800

#include <TinyGsmClient.h>
#include <SPI.h>
#include <Adafruit_MAX31855.h>
#include <algorithm>

// Define UART pins for SIM800L (Hardware Serial2 on ESP32)
#define SIM_RX 16
#define SIM_TX 17

// Define CS pins for both MAX31855 modules
#define MAX31855_CS1  5  // MAX31855 #1
#define MAX31855_CS2  4  // MAX31855 #2

// Initialize the modem on Serial2
TinyGsm modem(Serial2);

// Replace with your SIM's APN
const char apn[] = "send.ee";

// Redis details
const char redis_host[] = ""; // REPLACE WITH ACTUAL HOST!
const int redis_port = 6379;
const char redis_key[] = "temps";
const char redis_pass[] = "";  // REPLACE WITH ACTUAL PASSWORD!

// Thermocouples
Adafruit_MAX31855 thermocouple1(MAX31855_CS1);
Adafruit_MAX31855 thermocouple2(MAX31855_CS2);

void setup() {
  Serial.begin(115200);
  delay(3000);
  Serial.println("Starting...");

  Serial2.begin(9600, SERIAL_8N1, SIM_RX, SIM_TX);
  delay(1000);

  if (!thermocouple1.begin()) {
    Serial.println("ERROR: MAX31855 #1 init failed!");
    while (1) delay(10);
  }
  if (!thermocouple2.begin()) {
    Serial.println("ERROR: MAX31855 #2 init failed!");
    while (1) delay(10);
  }
  Serial.println("Sensors initialized.");

  Serial.println("Restarting modem...");
  modem.restart();
  delay(5000);
  if (!modem.init()) {
    Serial.println("ERROR: Modem init failed!");
    while (1) delay(1000);
  }
  if (!modem.testAT()) {
    Serial.println("ERROR: No AT response!");
    while (1) delay(1000);
  }

  Serial.println("Waiting for network...");
  while (modem.getRegistrationStatus() != 1 && modem.getRegistrationStatus() != 5) {
    delay(5000);
  }
  Serial.println("Network registered!");

  Serial.print("Connecting GPRS (APN: ");
  Serial.print(apn);
  Serial.println(")...");
  if (!modem.gprsConnect(apn)) {
    Serial.println("ERROR: Initial GPRS failed!");
    while (1) delay(1000);
  }
  Serial.println("GPRS connected!");
}

void loop() {
  // Sample 100 points over 5 seconds
  float readings1[100];
  float readings2[100];
  int count1 = 0;
  int count2 = 0;
  for (int i = 0; i < 100; i++) {
    double t1 = thermocouple1.readCelsius();
    if (!isnan(t1)) readings1[count1++] = (float)t1;
    double t2 = thermocouple2.readCelsius();
    if (!isnan(t2)) readings2[count2++] = (float)t2;
    delay(50);
  }

  // Compute averages after removing outliers
  double avg1 = computeAverage(readings1, count1);
  double avg2 = computeAverage(readings2, count2);

  // Send if valid
  if (!isnan(avg1) && !isnan(avg2)) {
    sendToRedis(avg1, avg2);
  } else {
    Serial.println("Invalid averages, skipping send.");
  }
}

double computeAverage(float readings[], int count) {
  if (count == 0) return NAN;
  std::sort(readings, readings + count);
  float sum = 0;
  for (int i = count/2; i < count; i++) {
    sum += readings[i];
  }
  return sum / (count / 2);
}

void sendToRedis(double avg1, double avg2) {
  if (!modem.isGprsConnected()) {
    Serial.println("GPRS dropped, reconnecting...");
    if (!modem.gprsConnect(apn)) {
      Serial.println("GPRS reconnect FAILED - skipping send.");
      return;
    }
    Serial.println("GPRS reconnected.");
  }

  String payload = "{\"avg_temp1\":" + String(avg1, 2) + ",\"avg_temp2\":" + String(avg2, 2) + "}";
  TinyGsmClient client(modem);

  if (!client.connect(redis_host, redis_port)) {
    Serial.println("TCP Connect FAILED!");
    return;
  }

  // AUTH
  String auth_cmd = "*2\r\n$4\r\nAUTH\r\n$" + String(strlen(redis_pass)) + "\r\n" + redis_pass + "\r\n";
  client.print(auth_cmd);
  String auth_resp = readResponse(client, 3000);
  if (auth_resp.indexOf("+OK") < 0) {
    Serial.println("AUTH FAILED");
    client.stop();
    return;
  }

  // PUBLISH
  String pub_cmd = "*3\r\n$7\r\nPUBLISH\r\n$" + String(strlen(redis_key)) + "\r\n" + redis_key + "\r\n$" + String(payload.length()) + "\r\n" + payload + "\r\n";
  client.print(pub_cmd);
  String pub_resp = readResponse(client, 5000);
  client.stop();

  if (pub_resp.startsWith(":")) {
    Serial.println("PUBLISH SUCCESS!");
  } else {
    Serial.println("PUBLISH FAILED");
  }
}

String readResponse(TinyGsmClient &client, unsigned long timeout_ms) {
  String resp = "";
  unsigned long start = millis();
  while (millis() - start < timeout_ms) {
    while (client.available()) {
      resp += (char)client.read();
      if (resp.endsWith("\r\n")) return resp;
    }
    delay(5);
  }
  return resp;
}