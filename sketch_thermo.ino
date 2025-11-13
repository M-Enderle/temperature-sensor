// Define the modem model BEFORE including TinyGSM
#define TINY_GSM_MODEM_SIM800

#include <TinyGsmClient.h>
#include <SPI.h>
#include <Adafruit_MAX31855.h>
#include <algorithm>
#include <ArduinoJson.h>

// UART pins for SIM800L
#define SIM_RX 16
#define SIM_TX 17

// MAX31855 CS pins
#define MAX31855_CS1  5
#define MAX31855_CS2  4

TinyGsm modem(Serial2);

// --- CONFIGURATION (CHANGE THESE!) ---
const char apn[]          = "send.ee";

const char redis_host[]   = ""; // ← CHANGE
const int  redis_port     = 6379;
const char redis_key[]    = "temps";
const char redis_pass[]   = ""; // ← CHANGE

const char api_host[]     = "";   // ← CHANGE
const int  api_port       = 443;                      // or 443 for HTTPS
const char api_path[]     = "/api/settings";

const char sms_number[]   = "+...";          // ← CHANGE

// --- THRESHOLD & ONE-TIME SMS FLAG ---
double temp_threshold = 30.0;      // fallback = 30 °C
bool   sms_already_sent = false;   // ← this is the key

Adafruit_MAX31855 thermocouple1(MAX31855_CS1);
Adafruit_MAX31855 thermocouple2(MAX31855_CS2);

TinyGsmClient httpClient(modem);

void setup() {
  Serial.begin(115200);
  delay(3000);
  Serial.println("\n=== Starting Temperature Logger ===");

  SPI.begin();
  SPI.setFrequency(4000000);

  Serial2.begin(9600, SERIAL_8N1, SIM_RX, SIM_TX);
  delay(1000);

  // Sensors
  if (!thermocouple1.begin() || !thermocouple2.begin()) {
    Serial.println("MAX31855 init failed!");
    while (1) delay(10);
  }
  Serial.println("Sensors OK");

  // Modem
  modem.restart();
  delay(5000);
  modem.init();

  while (modem.getRegistrationStatus() != 1 && modem.getRegistrationStatus() != 5) {
    Serial.print(".");
    delay(2000);
  }
  Serial.println("\nNetwork registered");

  if (!modem.gprsConnect(apn)) {
    Serial.println("GPRS connect failed!");
    while (1) delay(1000);
  }
  Serial.println("GPRS connected");

  // Try to load threshold from API (optional – fallback is 30.0)
  if (fetchThresholdFromAPI()) {
    Serial.printf("Threshold loaded from API: %.2f °C\n", temp_threshold);
  } else {
    Serial.printf("Using fallback threshold: %.2f °C\n", temp_threshold);
  }
}

void loop() {
  float r1[100], r2[100];
  int c1 = 0, c2 = 0;

  Serial.println("Sampling 100 points...");

  for (int i = 0; i < 100; i++) {
    uint8_t f1 = thermocouple1.readError();
    double t1 = thermocouple1.readCelsius();
    if (f1 == 0 && !isnan(t1)) r1[c1++] = t1;
    else printFault("TC1", f1, isnan(t1));

    uint8_t f2 = thermocouple2.readError();
    double t2 = thermocouple2.readCelsius();
    if (f2 == 0 && !isnan(t2)) r2[c2++] = t2;
    else printFault("TC2", f2, isnan(t2));

    delay(50);
  }

  double avg1 = computeAverage(r1, c1);
  double avg2 = computeAverage(r2, c2);

  Serial.printf("Valid: TC1=%d  TC2=%d  →  Avg=%.2f °C / %.2f °C\n", c1, c2, avg1, avg2);

  if (!isnan(avg1) && !isnan(avg2)) {
    sendToRedis(avg1, avg2);                     // ← ALWAYS SEND

    // ONE-TIME SMS when BOTH sensors ≥ threshold
    if (!sms_already_sent && avg1 >= temp_threshold && avg2 >= temp_threshold) {
      String msg = String(temp_threshold, 1) + " Grad Erreicht";
      if (modem.sendSMS(sms_number, msg.c_str())) {
        Serial.println("SMS SENT (will not send again until reboot): " + msg);
      } else {
        Serial.println("SMS FAILED");
      }
      sms_already_sent = true;   // ← blocks any further SMS until power cycle
    }
  } else {
    Serial.println("Invalid averages – skipping this cycle");
  }

  delay(10000);   // next measurement in 10 seconds
}

// ————————————————————————
// Helper functions (unchanged, just cleaned up)
// ————————————————————————

double computeAverage(float arr[], int cnt) {
  if (cnt == 0) return NAN;
  std::sort(arr, arr + cnt);
  if (cnt <= 4) return arr[cnt / 2];

  int q1i = cnt / 4;
  int q3i = 3 * cnt / 4;
  float q1 = arr[q1i];
  float q3 = arr[q3i];
  float iqr = q3 - q1;
  float lo = q1 - 1.5f * iqr;
  float hi = q3 + 1.5f * iqr;

  float sum = 0;
  int valid = 0;
  for (int i = 0; i < cnt; i++) {
    if (arr[i] >= lo && arr[i] <= hi) {
      sum += arr[i];
      valid++;
    }
  }
  return valid ? sum / valid : NAN;
}

void printFault(const char* name, uint8_t fault, bool nan) {
  Serial.print(name); Serial.print(" Fault: ");
  if (fault & MAX31855_FAULT_OPEN)       Serial.print("OPEN ");
  if (fault & MAX31855_FAULT_SHORT_GND)  Serial.print("SHORT_GND ");
  if (fault & MAX31855_FAULT_SHORT_VCC)  Serial.print("SHORT_VCC ");
  if (nan) Serial.print("NaN ");
  Serial.println();
}

void sendToRedis(double a1, double a2) {
  if (!modem.isGprsConnected()) {
    Serial.println("GPRS lost – reconnecting...");
    modem.gprsConnect(apn);
  }

  TinyGsmClient client(modem);
  if (!client.connect(redis_host, redis_port)) {
    Serial.println("Redis connect failed");
    return;
  }

  // AUTH
  client.print(String("*2\r\n$4\r\nAUTH\r\n$") + strlen(redis_pass) + "\r\n" + redis_pass + "\r\n");
  readLine(client, 3000);

  // PUBLISH
  String payload = "{\"avg_temp1\":" + String(a1, 2) + ",\"avg_temp2\":" + String(a2, 2) + "}";
  client.print(String("*3\r\n$7\r\nPUBLISH\r\n$") + strlen(redis_key) + "\r\n" + redis_key + "\r\n$" +
               payload.length() + "\r\n" + payload + "\r\n");

  String resp = readLine(client, 5000);
  client.stop();

  Serial.println(resp.startsWith(":") ? "Redis OK" : "Redis FAILED: " + resp);
}

bool fetchThresholdFromAPI() {
  if (!httpClient.connect(api_host, api_port)) return false;

  httpClient.print(String("GET ") + api_path + " HTTP/1.1\r\nHost: " + api_host + "\r\nConnection: close\r\n\r\n");

  String response = "";
  unsigned long t = millis();
  while (millis() - t < 10000 && httpClient.connected()) {
    while (httpClient.available()) response += (char)httpClient.read();
  }
  httpClient.stop();

  int bodyPos = response.indexOf("\r\n\r\n");
  if (bodyPos == -1) return false;
  String json = response.substring(bodyPos + 4);

  DynamicJsonDocument doc(256);
  if (deserializeJson(doc, json) != DeserializationError::Ok) return false;

  if (doc.containsKey("temp_threshold")) {
    temp_threshold = doc["temp_threshold"].as<double>();
    return true;
  }
  return false;
}

String readLine(TinyGsmClient& client, unsigned long timeout) {
  String s = "";
  unsigned long start = millis();
  while (millis() - start < timeout) {
    while (client.available()) {
      char c = client.read();
      s += c;
      if (s.endsWith("\r\n")) return s;
    }
    delay(5);
  }
  return s;
}