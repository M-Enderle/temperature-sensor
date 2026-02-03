from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
from pydantic import BaseModel
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import asyncio
import urllib.request
import time

from .database import init_db, get_latest_temperature, get_temperature_history, save_temperature, clear_database, save_error_log, get_error_logs, clear_error_logs
from .redis_subscriber import RedisSubscriber
from .models import SettingsStore
from .logging_config import setup_logging, get_logger, log_api_request, log_temperature_reading, log_performance

# Berlin timezone
BERLIN_TZ = ZoneInfo("Europe/Berlin")

# Setup logging
setup_logging()
logger = get_logger(__name__, "api")

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
            # Get the previous record to check if outlier filtering occurred
            prev_record = get_latest_temperature()

            record = save_temperature(avg_temp1, avg_temp2, apply_outlier_filter=True)

            # Log temperature save success
            logger.info(
                "Temperature data saved successfully",
                extra={
                    "operation": "temperature_save",
                    "temperature_sensor1": record.avg_temp1,
                    "temperature_sensor2": record.avg_temp2,
                    "original_temp1": avg_temp1,
                    "original_temp2": avg_temp2,
                    "outlier_filtered": (record.avg_temp1 != avg_temp1 or record.avg_temp2 != avg_temp2)
                }
            )
    except Exception as e:
        logger.error(
            "Error processing Redis message",
            extra={
                "operation": "redis_message_processing",
                "error": str(e),
                "error_type": type(e).__name__,
                "data": data
            }
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle app startup and shutdown"""
    # Startup
    logger.info(
        "Application starting up",
        extra={
            "operation": "application_startup",
            "app_title": "Temperature Monitor",
            "components": ["redis_subscriber", "database", "static_files"]
        }
    )
    redis_subscriber.set_message_callback(on_message)
    redis_subscriber.start()
    logger.info(
        "Application startup completed",
        extra={
            "operation": "application_startup_complete",
            "redis_connected": redis_subscriber.redis_client is not None
        }
    )
    yield
    # Shutdown
    logger.info(
        "Application shutting down",
        extra={
            "operation": "application_shutdown"
        }
    )
    redis_subscriber.stop()
    logger.info(
        "Application shutdown completed",
        extra={
            "operation": "application_shutdown_complete"
        }
    )


# Create FastAPI app
app = FastAPI(title="Temperature Monitor", lifespan=lifespan)

# Add logging middleware
@app.middleware("http")
async def logging_middleware(request: Request, call_next):
    """Log all HTTP requests with structured logging"""
    start_time = time.time()
    
    # Log request start
    logger.info(
        f"Request started: {request.method} {request.url.path}",
        extra={
            "operation": "http_request_start",
            "http_method": request.method,
            "http_path": request.url.path,
            "http_query_params": str(request.query_params),
            "user_agent": request.headers.get("user-agent", "unknown")
        }
    )
    
    # Process request
    try:
        response = await call_next(request)
        duration = (time.time() - start_time) * 1000
        
        # Log successful response
        log_api_request(
            request.method,
            request.url.path,
            response.status_code,
            duration,
            request.headers.get("user-agent")
        )
        
        return response
    except Exception as e:
        duration = (time.time() - start_time) * 1000
        
        # Log error response
        logger.error(
            f"Request failed: {request.method} {request.url.path}",
            extra={
                "operation": "http_request_error",
                "http_method": request.method,
                "http_path": request.url.path,
                "duration_ms": duration,
                "error": str(e),
                "error_type": type(e).__name__
            }
        )
        raise

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


class ErrorLogResponse(BaseModel):
    """Error log entry"""
    id: int
    timestamp: datetime
    message: str

    class Config:
        from_attributes = True


class LogErrorRequest(BaseModel):
    """Request to log an error message"""
    message: str


# ============== API Endpoints ==============
@app.get("/api/current", response_model=TemperatureDataResponse)
@log_performance
async def get_current():
    """Get the most recent temperature reading"""
    record = get_latest_temperature()
    if not record:
        logger.warning(
            "No temperature records found",
            extra={
                "operation": "get_current_temperature",
                "records_found": 0
            }
        )
        return {
            "timestamp": datetime.now(BERLIN_TZ),
            "avg_temp1": 0.0,
            "avg_temp2": 0.0,
        }
    
    logger.info(
        "Current temperature retrieved",
        extra={
            "operation": "get_current_temperature",
            "temperature_sensor1": record.avg_temp1,
            "temperature_sensor2": record.avg_temp2,
            "timestamp": record.timestamp.isoformat()
        }
    )
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


@app.get("/api/ip")
async def get_public_ip():
    """Return the current public IP address (queried from a public service)."""
    try:
        def fetch():
            with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=5) as resp:
                return resp.read()

        body = await asyncio.to_thread(fetch)
        data = json.loads(body)
        ip = data.get("ip")
        if not ip:
            return {"error": "could not determine public IP"}
        return {"ip": ip}
    except Exception as e:
        logger.error(f"Error fetching public IP: {e}")
        return {"error": "failed to fetch public IP"}


@app.get("/api/phonenumber")
async def get_phonenumber():
    """Return a fixed phone number."""
    return {"phonenumber": "+4915124149139"}


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


@app.post("/api/error")
async def log_error(request: LogErrorRequest):
    """Log an error message"""
    error_log = save_error_log(request.message)
    logger.warning(f"Error logged: {request.message}")
    return {"id": error_log.id, "timestamp": error_log.timestamp, "message": error_log.message}


@app.get("/api/errors", response_model=list[ErrorLogResponse])
async def get_errors(hours: int = 24):
    """Get error logs from the last N hours"""
    errors = get_error_logs(hours)
    return errors


@app.post("/api/errors/clear")
async def clear_errors():
    """Clear all error logs from database"""
    count = clear_error_logs()
    logger.info(f"Cleared {count} error logs from database")
    return {"deleted_records": count, "message": "Error logs cleared successfully"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
