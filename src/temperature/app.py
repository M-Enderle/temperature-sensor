import logging
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import json

from .database import init_db, get_latest_temperature, get_temperature_history, save_temperature, clear_database
from .redis_subscriber import RedisSubscriber
from .models import SettingsStore

# Berlin timezone
BERLIN_TZ = ZoneInfo("Europe/Berlin")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize components
settings_store = SettingsStore()
redis_subscriber = RedisSubscriber()

# Initialize database on startup
init_db()


async def on_message(data: dict):
    """Callback when Redis message is received"""
    try:
        avg_temp1 = data.get("avg_temp1")
        avg_temp2 = data.get("avg_temp2")

        if avg_temp1 is not None and avg_temp2 is not None:
            save_temperature(avg_temp1, avg_temp2)
            logger.info(f"Saved: temp1={avg_temp1}°C, temp2={avg_temp2}°C")
    except Exception as e:
        logger.error(f"Error saving temperature: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app startup and shutdown"""
    # Startup
    logger.info("Starting application...")
    redis_subscriber.set_message_callback(on_message)
    redis_subscriber.start()
    yield
    # Shutdown
    logger.info("Shutting down application...")
    redis_subscriber.stop()


# Create FastAPI app
app = FastAPI(title="Temperature Monitor", lifespan=lifespan)

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")


# ============== Response Models ==============
class TemperatureDataResponse(BaseModel):
    """Response for latest temperature"""
    timestamp: datetime
    avg_temp1: float
    avg_temp2: float

    class Config:
        from_attributes = True


class HistoryPoint(BaseModel):
    """Single point in history"""
    timestamp: datetime
    avg_temp1: float
    avg_temp2: float

    class Config:
        from_attributes = True


class SettingsResponse(BaseModel):
    """Temperature threshold settings"""
    temp_threshold: float


class UpdateSettingsRequest(BaseModel):
    """Request to update settings"""
    temp_threshold: float


# ============== API Endpoints ==============
@app.get("/api/current", response_model=TemperatureDataResponse)
async def get_current():
    """Get the most recent temperature reading"""
    record = get_latest_temperature()
    if not record:
        return {
            "timestamp": datetime.now(BERLIN_TZ),
            "avg_temp1": 0.0,
            "avg_temp2": 0.0,
        }
    return record


@app.get("/api/history", response_model=list[HistoryPoint])
async def get_history(hours: int = 6):
    """Get temperature history for the last N hours"""
    records = get_temperature_history(hours)
    return records


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings():
    """Get current settings"""
    return {"temp_threshold": settings_store.get_threshold()}


@app.post("/api/settings")
async def update_settings(request: UpdateSettingsRequest):
    """Update temperature threshold"""
    settings_store.set_threshold(request.temp_threshold)
    return {"temp_threshold": settings_store.get_threshold()}


@app.get("/")
async def get_index():
    """Serve the main HTML page"""
    html_file = static_path / "index.html"
    if html_file.exists():
        return FileResponse(html_file)
    return {"error": "index.html not found"}


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "redis_connected": redis_subscriber.redis_client is not None,
    }


@app.post("/api/clear")
async def clear_db():
    """Clear all temperature records from database"""
    count = clear_database()
    logger.info(f"Cleared {count} temperature records from database")
    return {"deleted_records": count, "message": "Database cleared successfully"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
