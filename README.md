# Temperature Monitor 🌡️

A real-time temperature monitoring application that subscribes to Redis, stores data in SQLite, and provides a beautiful web UI with live updates and historical charts.

## Features

✨ **Real-time Updates**: Live temperature readings updated every second  
📊 **Historical Charts**: View temperature trends over the last 6 hours  
🔔 **Temperature Alerts**: Visual warnings when temperatures exceed threshold  
⚙️ **Adjustable Settings**: Configure temperature thresholds via the web UI  
🎨 **Modern UI**: Clean, responsive design with Playfair Display typography  
📱 **Mobile Responsive**: Works on desktop, tablet, and mobile devices  

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Redis Server                            │
│           (Publishing temp data to "temps" topic)            │
└────────────────────────────┬────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  Redis Subscriber
                    │   (Background)
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        │                    │                    │
        ▼                    ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  FastAPI     │     │   SQLite     │     │   Settings   │
│  Server      │────▶│   Database   │     │   Storage    │
│  (Port 8000) │     └──────────────┘     └──────────────┘
└──────────────┘
        │
        │ /api/current
        │ /api/history
        │ /api/settings
        │
        ▼
   ┌─────────────────────────────────────────┐
   │      Web UI (HTML/CSS/JavaScript)       │
   │  • Current temperature display          │
   │  • Chart.js temperature history graph   │
   │  • Settings panel for thresholds        │
   │  • Live status indicator                │
   └─────────────────────────────────────────┘
```

## Installation

### Prerequisites
- Python 3.10+
- Redis server running locally (with credentials)
- pip or poetry for dependency management

### Setup Steps

1. **Install dependencies**:
```bash
pip install -r requirements.txt
# or with poetry:
poetry install
```

2. **Update Redis credentials** (if needed):
Edit `src/temperature/redis_subscriber.py` and update the password:
```python
redis_subscriber = RedisSubscriber(
    password='your-redis-password-here'
)
```

3. **Run the application**:
```bash
python main.py
```

The application will start on `http://localhost:8000`

## Usage

### Web Interface
1. Open your browser and navigate to `http://localhost:8000`
2. You'll see:
   - **Current Values**: Latest temperature readings from both sensors
   - **Chart**: 6-hour historical trend visualization
   - **Settings**: Adjust temperature threshold (default: 200°C)

### API Endpoints

#### Get Current Temperature
```bash
GET /api/current
```
Response:
```json
{
  "timestamp": "2025-11-13T09:21:06.397007",
  "avg_temp1": 21.83,
  "avg_temp2": 21.57
}
```

#### Get Temperature History
```bash
GET /api/history?hours=6
```
Response:
```json
[
  {
    "timestamp": "2025-11-13T03:21:06",
    "avg_temp1": 20.5,
    "avg_temp2": 20.3
  },
  ...
]
```

#### Get Settings
```bash
GET /api/settings
```
Response:
```json
{
  "temp_threshold": 200.0
}
```

#### Update Settings
```bash
POST /api/settings
Content-Type: application/json

{
  "temp_threshold": 250.0
}
```

#### Health Check
```bash
GET /health
```

## Configuration

### Redis Connection
Update the connection parameters in `src/temperature/redis_subscriber.py`:
```python
RedisSubscriber(
    host='localhost',      # Redis host
    port=6379,            # Redis port
    db=0,                 # Database number
    password='...',       # Redis password
    channel='temps'       # Topic/Channel name
)
```

### Temperature Threshold
- Default: 200°C
- Configurable via web UI
- Stored in `settings.json`
- Values above threshold trigger visual warnings

### Database
- Uses SQLite for local storage
- File: `temperature.db` (created automatically)
- Schema auto-created on startup
- Records include timestamp, avg_temp1, avg_temp2

## File Structure

```
temperature/
├── main.py                          # Entry point
├── pyproject.toml                   # Dependencies
├── requirements.txt                 # Alternative: pip requirements
├── settings.json                    # Settings storage (auto-created)
├── temperature.db                   # SQLite database (auto-created)
└── src/
    └── temperature/
        ├── __init__.py
        ├── app.py                   # FastAPI application & routes
        ├── database.py              # SQLAlchemy models & helpers
        ├── models.py                # Settings model
        ├── redis_subscriber.py      # Redis subscription logic
        └── static/
            └── index.html           # Web UI
```

## Performance Notes

- **Update Interval**: Current values refresh every 1 second
- **Chart Updates**: Every 5 seconds
- **Database Queries**: Optimized with indexing on timestamp
- **Memory Usage**: Minimal - background threading with proper cleanup
- **Connection Management**: Automatic reconnection handling

## Troubleshooting

### Redis Connection Failed
- Check Redis server is running: `redis-cli ping`
- Verify host, port, and password in `redis_subscriber.py`
- Check firewall settings

### No Data Appearing
- Ensure Redis is publishing to the `temps` channel
- Check browser console for JavaScript errors (F12)
- Verify database file has write permissions

### Chart Not Loading
- Ensure Chart.js CDN is accessible
- Check browser compatibility (modern browsers only)
- Look for CORS issues in browser console

### Settings Not Saving
- Check `settings.json` file has write permissions
- Verify JSON syntax in settings file

## Development

### Adding New Sensors
1. Update Redis message format to include new sensor data
2. Update `TemperatureRecord` model in `database.py`
3. Update UI in `index.html` to display new sensor

### Customizing UI
- Edit `src/temperature/static/index.html`
- CSS variables at top for easy theming
- Chart.js configuration in the script section

### Extending API
- Add new endpoints in `src/temperature/app.py`
- Update database models in `database.py`
- Test with FastAPI's built-in `/docs` endpoint

## License

Created for personal use.

## Support

For issues or questions, check:
1. Browser console for JavaScript errors (F12)
2. Terminal logs for backend errors
3. Redis connection status in `/health` endpoint
