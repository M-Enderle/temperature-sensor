# Temperature Monitor 🌡️

Dual-sensor temperature monitoring via ESP32 + SIM800L GPRS modem, with real-time data streaming to Redis and web-based visualization with 6-hour historical charts.

## Overview

- **Hardware**: ESP32 + 2× MAX31855 thermocouples + SIM800L modem
- **Connectivity**: GPRS → Redis Server → Python Backend → Web UI
- **Sampling**: 100 readings/cycle → median averaging → 5-second intervals
- **Display**: Real-time temps, 6-hour charts, configurable alerts (threshold: 200°C default)

## System Architecture

```
┌──────────────────────────────────────────┐
│    Physical Sensors (On-Site)            │
│  ┌────────────────┐  ┌────────────────┐ │
│  │ Thermocouple 1 │  │ Thermocouple 2 │ │
│  └────────┬───────┘  └────────┬───────┘ │
│           │                   │         │
│  ┌────────▼────────────────────▼───────┐│
│  │        MAX31855 Amplifiers (×2)     ││
│  │    SPI Protocol, CS on GPIO 4 & 5   ││
│  └──────────────┬──────────────────────┘│
│                 │                       │
│          ┌──────▼──────┐                │
│          │    ESP32    │                │
│          │   Microcontroller           │
│          └──────┬──────┘                │
│                 │                       │
│          ┌──────▼────────┐              │
│          │  SIM800L      │              │
│          │  GSM/GPRS     │              │
│          │  Modem        │              │
│          └──────┬────────┘              │
└─────────────────┼──────────────────────┘
                  │
              (GPRS)
                  │
    ┌─────────────▼──────────────┐
    │   Internet / Cellular      │
    │   (EE APN: send.ee)       │
    └─────────────┬──────────────┘
                  │
┌─────────────────▼──────────────────────┐
│      Redis Server (Cloud/VPS)          │
│  Host: 77.47.82.206:6379               │
│  Channel: "temps"                      │
│  Auth: Password-protected              │
└─────────────────┬──────────────────────┘
                  │
        ┌─────────▼────────────┐
        │ Redis Pub/Sub        │
        │ (Subscribes to       │
        │  "temps" channel)    │
        └─────────┬────────────┘
                  │
        ┌─────────▼────────────────────┐
        │    Python Backend             │
        │    (FastAPI)                  │
        │  • Receives Redis messages    │
        │  • Stores to SQLite           │
        │  • Manages settings           │
        │  • Serves API endpoints       │
        └─────────┬────────────────────┘
                  │
     ┌────────────┼────────────┐
     │            │            │
     ▼            ▼            ▼
  ┌───────┐  ┌────────┐  ┌──────────┐
  │SQLite │  │Settings│  │FastAPI   │
  │  DB   │  │ JSON   │  │/docs     │
  └───────┘  └────────┘  └──────────┘
                  │
        ┌─────────▼─────────────┐
        │   Web UI              │
        │   (HTML/CSS/JS)       │
        │ • Live display        │
        │ • Chart.js graphs     │
        │ • Settings panel      │
        │ • Real-time updates   │
        └───────────────────────┘
```

## Setup

### Hardware (sketch_thermo.ino)
1. Wire MAX31855 #1 to CS1 (GPIO 5), #2 to CS2 (GPIO 4)
2. Connect SIM800L to Serial2 (RX=GPIO16, TX=GPIO17)
3. Update APN & Redis credentials in sketch:
```cpp
const char apn[] = "send.ee";
const char redis_host[] = "77.47.82.206";
const char redis_pass[] = "your-password-here";
```
4. Upload via Arduino IDE

### Backend
```bash
pip install -r requirements.txt  # or: poetry install
python main.py
```
Access at `http://localhost:8000`

Update Redis password in `src/temperature/redis_subscriber.py` if needed.

## Usage

**Web UI** (`http://localhost:8000`):
- Live temperature readings (both sensors)
- 6-hour historical chart
- Adjustable threshold (default: 200°C)

**API Endpoints**:
- `GET /api/current` - Latest readings
- `GET /api/history?hours=6` - Historical data
- `GET /api/settings` - Current threshold
- `POST /api/settings` - Update threshold
- `GET /health` - Health check

## Configuration

**Hardware** (`sketch_thermo.ino`):
- CS pins: GPIO 5 (sensor 1), GPIO 4 (sensor 2)
- Serial2: RX=GPIO16, TX=GPIO17 (SIM800L)
- Sampling: 100 readings @ 50ms intervals → median average
- Transmission: Every ~5 seconds

**Backend** (`src/temperature/redis_subscriber.py`):
- Redis host, port, password, channel
- SQLite database auto-created
- Settings stored in `settings.json`

## Files

```
├── sketch_thermo.ino          # ESP32 firmware
├── src/temperature/
│   ├── app.py                 # FastAPI routes
│   ├── database.py            # SQLAlchemy models
│   ├── redis_subscriber.py    # Redis listener
│   └── static/index.html      # Web UI
├── main.py                    # Entry point
├── pyproject.toml             # Dependencies
└── temperature.db             # SQLite (auto-created)
```

## Troubleshooting

**Hardware**:
- MAX31855 not detected: Check SPI connections (GPIO 4/5), reboot ESP32
- SIM800L not responding: Verify Serial2 pins (GPIO 16/17), check baud rate (9600)
- No network: Wait 30-60s for registration, check signal strength, verify APN

**Backend**:
- No data: Check Arduino Serial Monitor for "PUBLISH SUCCESS!", verify Redis is running
- Chart not loading: Check browser console (F12), verify Chart.js CDN accessible
- Settings not saving: Check `settings.json` write permissions
