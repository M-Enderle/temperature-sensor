#define TINY_GSM_MODEM_SIM800

#include <TinyGsmClient.h>
#include <SPI.h>
#include <Adafruit_MAX31855.h>
#include <ArduinoJson.h>

// ===================== PIN CONFIG =====================
// SIM800 (ESP32 Serial2)
#define SIM_RX 16
#define SIM_TX 17

// MAX31855 chip selects
#define MAX31855_CS1  5
#define MAX31855_CS2  4

// OPTIONAL: Explicit SPI pins for ESP32 (uncomment if you wired SPI to non-default pins)
// Default ESP32 VSPI: SCK=18, MISO=19, MOSI=23 (MAX31855 doesn't use MOSI)
//#define SPI_SCK   18
//#define SPI_MISO  19
//#define SPI_MOSI  23

// ===================== CONFIG =====================
const char apn[] = "send.ee";
const char api_host[] = "temps.enderles.com";
const int  api_port   = 80;

const char redis_key[]  = "temps";
const char redis_pass[] = "nnwbQa2xDmJLPn4m7N9J5FK93";
const int  redis_port   = 6379;

// ===================== GLOBALS =====================
TinyGsm modem(Serial2);
TinyGsmClient client(modem);

Adafruit_MAX31855 tc1(MAX31855_CS1);
Adafruit_MAX31855 tc2(MAX31855_CS2);

String redis_ip = "";
String sms_number = "";
double temp_threshold = 30.0;
bool sms_sent = false;

// Error logging throttling
unsigned long last_error_log_t1 = 0;
unsigned long last_error_log_t2 = 0;
unsigned long last_error_log_both = 0;
const unsigned long ERROR_LOG_INTERVAL = 300000; // 5 minutes in milliseconds

// ===================== DEBUG HELPERS =====================
static bool DEBUG_VERBOSE_SAMPLES = true;
static uint32_t CYCLE_MS = 10000;

void debug(const String &msg) {
  Serial.print("[LOG] ");
  Serial.println(msg);
}

void debugKV(const String &k, const String &v) {
  Serial.print("[LOG] ");
  Serial.print(k);
  Serial.print(": ");
  Serial.println(v);
}

// Read a line with timeout
String readLineWithTimeout(uint32_t timeoutMs) {
  String line;
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    while (client.available()) {
      char c = (char)client.read();
      line += c;
      if (c == '\n') return line;
    }
    delay(5);
  }
  return line; // may be partial/empty
}

// Read all remaining with timeout
String readAllWithTimeout(uint32_t timeoutMs) {
  String out;
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    while (client.available()) out += (char)client.read();
    if (!client.connected() && !client.available()) break;
    delay(5);
  }
  return out;
}

// ===================== MAX31855 DEBUG =====================
// Adafruit_MAX31855::readError() returns bitmask:
// 0x01 = open circuit
// 0x02 = short to GND
// 0x04 = short to VCC
String maxErrToString(uint8_t e) {
  if (e == 0) return "OK";
  String s;
  if (e & 0x01) s += "OPEN ";
  if (e & 0x02) s += "SHORT_GND ";
  if (e & 0x04) s += "SHORT_VCC ";
  s.trim();
  return s;
}

void logThermo(const char* name, Adafruit_MAX31855 &tc) {
  double ext = tc.readCelsius();
  double internal = tc.readInternal();
  uint8_t err = tc.readError();

  String msg = String(name) +
               " ext=" + (isnan(ext) ? "NaN" : String(ext, 2)) + "C" +
               " internal=" + (isnan(internal) ? "NaN" : String(internal, 2)) + "C" +
               " err=" + maxErrToString(err);
  debug(msg);
}

// ===================== HTTP HELPER =====================
// Returns body only; logs status + parsing issues
String fetchApi(const String &path) {
  debug("HTTP GET: " + String(api_host) + path);

  client.stop(); // ensure clean socket
  if (!client.connect(api_host, api_port)) {
    debug("ERROR: HTTP connect failed");
    return "";
  }

  client.print(String("GET ") + path + " HTTP/1.1\r\n" +
               "Host: " + api_host + "\r\n" +
               "Connection: close\r\n\r\n");

  // Read status line
  String statusLine = readLineWithTimeout(5000);
  statusLine.trim();
  if (statusLine.length() == 0) {
    debug("ERROR: HTTP no status line (timeout?)");
    client.stop();
    return "";
  }
  debug("HTTP StatusLine: " + statusLine);

  // Read headers until blank line
  bool gotBlank = false;
  uint32_t headerStart = millis();
  while (millis() - headerStart < 8000) {
    String line = readLineWithTimeout(2000);
    if (line.length() == 0) continue;
    if (line == "\r\n" || line == "\n" || line == "\r") {
      gotBlank = true;
      break;
    }
  }
  if (!gotBlank) debug("WARN: HTTP headers may be incomplete");

  // Read body
  String body = readAllWithTimeout(8000);
  client.stop();
  body.trim();

  debug("HTTP Body (" + String(body.length()) + " bytes): " + body);
  return body;
}

// POST error log to API
void logErrorToApi(const String &errorMsg) {
  debug("Logging error to API: " + errorMsg);

  client.stop();
  if (!client.connect(api_host, api_port)) {
    debug("ERROR: HTTP connect failed for error logging");
    return;
  }

  // Prepare JSON payload
  StaticJsonDocument<256> doc;
  doc["message"] = errorMsg;
  String payload;
  serializeJson(doc, payload);

  // Send POST request
  client.print(String("POST /api/error HTTP/1.1\r\n") +
               "Host: " + api_host + "\r\n" +
               "Content-Type: application/json\r\n" +
               "Content-Length: " + payload.length() + "\r\n" +
               "Connection: close\r\n\r\n" +
               payload);

  // Read response
  String statusLine = readLineWithTimeout(5000);
  debug("Error log response: " + statusLine);

  client.stop();
}

// ===================== REDIS HELPERS =====================
String redisReadReply(uint32_t timeoutMs) {
  String reply = readLineWithTimeout(timeoutMs);
  reply.trim();
  return reply;
}

bool redisSendCommand(const String &cmd, const char *expectPrefix, uint32_t timeoutMs) {
  client.print(cmd);
  String reply = redisReadReply(timeoutMs);
  debug("Redis Reply: " + reply);
  if (reply.length() == 0) return false;
  if (expectPrefix == nullptr) return true;
  return reply.startsWith(expectPrefix);
}

void publishToRedis(double t1, double t2) {
  if (redis_ip.length() == 0) {
    debug("SKIP: No Redis IP loaded");
    return;
  }

  client.stop();
  debug("Connecting to Redis: " + redis_ip + ":" + String(redis_port));
  if (!client.connect(redis_ip.c_str(), redis_port)) {
    debug("ERROR: Redis connect failed");
    return;
  }

  // AUTH
  String auth =
    String("*2\r\n$4\r\nAUTH\r\n$") +
    String(strlen(redis_pass)) + "\r\n" + redis_pass + "\r\n";

  debug("Redis -> AUTH ...");
  if (!redisSendCommand(auth, "+OK", 3000)) {
    debug("ERROR: Redis AUTH failed (no +OK). Closing.");
    client.stop();
    return;
  }

  // Prepare JSON Payload
  String payload = "{\"avg_temp1\":" + String(t1, 2) + ",\"avg_temp2\":" + String(t2, 2) + "}";

  // PUBLISH
  String pub =
    String("*3\r\n$7\r\nPUBLISH\r\n$") + String(strlen(redis_key)) + "\r\n" + redis_key +
    "\r\n$" + String(payload.length()) + "\r\n" + payload + "\r\n";

  debug("Redis -> PUBLISH " + String(redis_key) + " payload=" + payload);
  // PUBLISH returns :<int>
  if (!redisSendCommand(pub, ":", 3000)) {
    debug("ERROR: Redis PUBLISH failed (no integer reply).");
  } else {
    debug("Redis Publish OK");
  }

  client.stop();
}

// ===================== SETUP =====================
void setup() {
  Serial.begin(115200);
  delay(1500);
  debug("=== SYSTEM START ===");

  // SPI init
  // If using explicit pins, uncomment SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI);
  SPI.begin();
  //SPI.begin(SPI_SCK, SPI_MISO, SPI_MOSI);

  // Init sensors
  bool ok1 = tc1.begin();
  bool ok2 = tc2.begin();
  debug(String("Sensors begin -> tc1=") + (ok1 ? "OK" : "FAIL") + " tc2=" + (ok2 ? "OK" : "FAIL"));

  // First immediate readout (super useful)
  debug("Initial thermocouple diagnostic:");
  logThermo("TC1", tc1);
  logThermo("TC2", tc2);

  // Init modem
  Serial2.begin(9600, SERIAL_8N1, SIM_RX, SIM_TX);
  debug("Modem restarting...");
  debug("Initializing modem (without full restart)...");
  if (!modem.init()) {
    debug("ERROR: Modem init failed");
    // Optional: fallback to restart or loop/retry
  } else {
    debug("Modem init OK");
  }

  debug("Waiting for network...");
  if (!modem.waitForNetwork(120000L)) {
    debug("ERROR: Network failed (timeout 120s)");
  } else {
    debug("Network OK");
    debug("Operator: " + modem.getOperator());
    debug("Signal quality (CSQ): " + String(modem.getSignalQuality()));
  }

  debug("Network OK");
  delay(3000);  // Give the modem time to stabilize

  debug("Connecting GPRS...");
  if (modem.isGprsConnected()) {
    debug("Already connected");
  } else if (!modem.gprsConnect(apn, "", "")) {  // explicit empty user/pass
    debug("ERROR: GPRS connect failed");
  } else {
    debug("GPRS Connected. IP: " + modem.localIP());
  }

  // Fetch config
  if (modem.isGprsConnected()) {
    StaticJsonDocument<256> doc;

    // Redis IP
    String json = fetchApi("/api/ip");
    DeserializationError e = deserializeJson(doc, json);
    if (e) {
      debug(String("ERROR: JSON /api/ip parse: ") + e.c_str());
    } else if (doc["ip"]) {
      redis_ip = doc["ip"].as<String>();
    } else {
      debug("WARN: /api/ip JSON missing 'ip'");
    }

    // Threshold
    doc.clear();
    json = fetchApi("/api/settings");
    e = deserializeJson(doc, json);
    if (e) {
      debug(String("ERROR: JSON /api/settings parse: ") + e.c_str());
    } else if (doc["temp_threshold"]) {
      temp_threshold = doc["temp_threshold"].as<double>();
    } else {
      debug("WARN: /api/settings JSON missing 'temp_threshold'");
    }

    // Phone number
    doc.clear();
    json = fetchApi("/api/phonenumber");
    e = deserializeJson(doc, json);
    if (e) {
      debug(String("ERROR: JSON /api/phonenumber parse: ") + e.c_str());
    } else if (doc["phonenumber"]) {
      sms_number = doc["phonenumber"].as<String>();
    } else {
      debug("WARN: /api/phonenumber JSON missing 'phonenumber'");
    }

    debug("CONFIG LOADED -> IP: " + redis_ip +
          " | LIMIT: " + String(temp_threshold, 2) +
          " | SMS: " + sms_number);
  }
}

// ===================== LOOP =====================
void loop() {
  debug("\n--- NEW CYCLE ---");

  // Connection check (unchanged)
  if (!modem.isNetworkConnected()) {
    debug("WARN: Network disconnected, waiting...");
    if (!modem.waitForNetwork(30000L)) {
      logErrorToApi("Network disconnected - failed to reconnect");
    }
  }
  if (!modem.isGprsConnected()) {
    debug("GPRS disconnected. Reconnecting...");
    if (!modem.gprsConnect(apn)) {
      debug("Reconnect failed. Sleeping 5s...");
      logErrorToApi("GPRS connection failed");
      delay(5000);
      return;
    }
    debug("GPRS reconnected. IP: " + modem.localIP());
  }

  // ───────────────────────────────────────────────────────────────
  // Read sensors – collect independently
  // ───────────────────────────────────────────────────────────────
  double t1 = NAN;
  double t2 = NAN;
  uint8_t e1 = 0xFF;  // invalid/error by default
  uint8_t e2 = 0xFF;

  int validCount = 0;

  for (int i = 0; i < 10; i++) {
    double sample1 = tc1.readCelsius();
    double sample2 = tc2.readCelsius();
    e1 = tc1.readError();
    e2 = tc2.readError();

    if (DEBUG_VERBOSE_SAMPLES) {
      debug(String("Sample ") + i +
            " | T1=" + (isnan(sample1) ? "NaN" : String(sample1, 2)) +
            " (" + maxErrToString(e1) + ")" +
            " | T2=" + (isnan(sample2) ? "NaN" : String(sample2, 2)) +
            " (" + maxErrToString(e2) + ")");
    }

    // Count this sample as valid for a sensor if no error & valid reading
    if (!isnan(sample1) && e1 == 0) {
      t1 = sample1;           // last good value (or keep averaging if you prefer)
      validCount++;
    }
    if (!isnan(sample2) && e2 == 0) {
      t2 = sample2;
      validCount++;
    }

    delay(150);
  }

  // ───────────────────────────────────────────────────────────────
  // Decide what to publish
  // ───────────────────────────────────────────────────────────────
  bool hasValidData = (validCount > 0);

  // Use -999.0 as "failed/no reading" marker
  double publish_t1 = isnan(t1) ? -999.0 : t1;
  double publish_t2 = isnan(t2) ? -999.0 : t2;

  if (hasValidData) {
    debug("Publishing data (at least one valid sensor)");
    debugKV("T1", isnan(t1) ? "FAILED" : String(t1, 2) + " °C");
    debugKV("T2", isnan(t2) ? "FAILED" : String(t2, 2) + " °C");

    // Log individual sensor failures (throttled to once per 5 minutes)
    unsigned long now = millis();
    if (isnan(t1) && (now - last_error_log_t1 > ERROR_LOG_INTERVAL)) {
      String errorMsg = "Sensor 1 failed: " + maxErrToString(e1);
      debug("ERROR: " + errorMsg);
      logErrorToApi(errorMsg);
      last_error_log_t1 = now;
    }
    if (isnan(t2) && (now - last_error_log_t2 > ERROR_LOG_INTERVAL)) {
      String errorMsg = "Sensor 2 failed: " + maxErrToString(e2);
      debug("ERROR: " + errorMsg);
      logErrorToApi(errorMsg);
      last_error_log_t2 = now;
    }

    publishToRedis(publish_t1, publish_t2);
  } else {
    // Both sensors failed - log only once per 5 minutes
    unsigned long now = millis();
    if (now - last_error_log_both > ERROR_LOG_INTERVAL) {
      String errorMsg = "CRITICAL: BOTH sensors failed - TC1: " + maxErrToString(e1) + ", TC2: " + maxErrToString(e2);
      debug(errorMsg);
      logThermo("TC1", tc1);
      logThermo("TC2", tc2);
      logErrorToApi(errorMsg);
      last_error_log_both = now;
    } else {
      debug("CRITICAL: BOTH sensors failed (suppressing API log - already sent recently)");
    }
  }

  // ───────────────────────────────────────────────────────────────
  // SMS logic – trigger only when BOTH sensors exceed threshold
  // Exception: if one sensor has completely failed, the other alone can trigger
  // ───────────────────────────────────────────────────────────────
  if (!sms_sent && sms_number.length() > 0) {
    bool t1_valid = !isnan(t1);
    bool t2_valid = !isnan(t2);
    bool t1_alarm = t1_valid && t1 > temp_threshold;
    bool t2_alarm = t2_valid && t2 > temp_threshold;
    
    bool should_alarm = false;
    String msg = "Temperatur Limit erreicht! ";
    
    if (t1_valid && t2_valid) {
      // Both sensors working: BOTH must exceed threshold
      if (t1_alarm && t2_alarm) {
        should_alarm = true;
        msg += "(beide Sensoren: S1=" + String(t1, 1) + "C, S2=" + String(t2, 1) + "C)";
      }
    } else if (t1_valid && !t2_valid) {
      // Only sensor 1 working (sensor 2 failed): sensor 1 alone can trigger
      if (t1_alarm) {
        should_alarm = true;
        msg += "(Sensor 1: " + String(t1, 1) + "C, Sensor 2 ausgefallen)";
      }
    } else if (!t1_valid && t2_valid) {
      // Only sensor 2 working (sensor 1 failed): sensor 2 alone can trigger
      if (t2_alarm) {
        should_alarm = true;
        msg += "(Sensor 2: " + String(t2, 1) + "C, Sensor 1 ausgefallen)";
      }
    }
    // If both sensors failed, no alarm (can't measure anything)
    
    if (should_alarm) {
      debug("SENDING ALARM SMS to " + sms_number);
      bool sent = modem.sendSMS(sms_number.c_str(), msg.c_str());
      debug(sent ? "SMS SUCCESS" : "SMS FAILED");
      if (sent) sms_sent = true;
    }
  }

  debug("Cycle Done. Sleeping " + String(CYCLE_MS / 1000) + "s...");
  delay(CYCLE_MS);
}