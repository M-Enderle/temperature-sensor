"""
Loki logging configuration using python-logging-loki
"""
import os
import logging
import logging.config
from typing import Dict, Any, Optional
from multiprocessing import Queue
import logging_loki

# Environment variables for configuration
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SERVICE_NAME = os.getenv("SERVICE_NAME", "temperature-sensor")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.1.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
LOKI_URL = os.getenv("LOKI_URL") or "http://loki:3100"

# Loki handler instance (initialized in setup_logging)
_loki_handler = None


def setup_logging():
    """Setup application logging with Loki handler"""
    global _loki_handler

    # Create Loki handler with queue for async sending
    _loki_handler = logging_loki.LokiQueueHandler(
        Queue(-1),
        url=f"{LOKI_URL}/loki/api/v1/push",
        tags={
            "application": SERVICE_NAME,
            "environment": ENVIRONMENT,
            "version": SERVICE_VERSION,
        },
        version="1",
    )
    _loki_handler.setLevel(LOG_LEVEL)

    # Also add a console handler for local debugging
    console_handler = logging.StreamHandler()
    console_handler.setLevel(LOG_LEVEL)
    console_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler.setFormatter(console_formatter)

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(LOG_LEVEL)
    root_logger.addHandler(_loki_handler)
    root_logger.addHandler(console_handler)

    # Configure specific loggers
    for logger_name in ["temperature", "uvicorn", "uvicorn.access", "fastapi", "redis"]:
        logger = logging.getLogger(logger_name)
        logger.setLevel(LOG_LEVEL)
        logger.propagate = True

    # SQLAlchemy at WARNING level
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)

    # Log startup
    logger = logging.getLogger("temperature.startup")
    logger.info(
        "Logging system initialized with Loki handler",
        extra={"tags": {
            "component": "logging",
            "operation": "initialization",
        }}
    )

    return logger


def get_logger(name: str, component: Optional[str] = None) -> logging.Logger:
    """Get a logger with optional component context"""
    logger = logging.getLogger(name)

    if component:
        class ComponentAdapter(logging.LoggerAdapter):
            def process(self, msg, kwargs):
                kwargs.setdefault('extra', {})
                kwargs['extra'].setdefault('tags', {})
                kwargs['extra']['tags']['component'] = component
                return msg, kwargs

        return ComponentAdapter(logger, {})

    return logger


def log_performance(func):
    """Decorator to log function performance"""
    import time
    import asyncio
    from functools import wraps

    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        logger = get_logger(func.__module__, func.__qualname__)
        start_time = time.time()
        try:
            result = await func(*args, **kwargs)
            duration = (time.time() - start_time) * 1000
            logger.info(
                f"Function {func.__name__} completed successfully",
                extra={"tags": {
                    "operation": func.__name__,
                    "duration_ms": str(round(duration, 2)),
                    "success": "true"
                }}
            )
            return result
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            logger.error(
                f"Function {func.__name__} failed: {str(e)}",
                extra={"tags": {
                    "operation": func.__name__,
                    "duration_ms": str(round(duration, 2)),
                    "success": "false",
                    "error_type": type(e).__name__
                }}
            )
            raise

    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        logger = get_logger(func.__module__, func.__qualname__)
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = (time.time() - start_time) * 1000
            logger.info(
                f"Function {func.__name__} completed successfully",
                extra={"tags": {
                    "operation": func.__name__,
                    "duration_ms": str(round(duration, 2)),
                    "success": "true"
                }}
            )
            return result
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            logger.error(
                f"Function {func.__name__} failed: {str(e)}",
                extra={"tags": {
                    "operation": func.__name__,
                    "duration_ms": str(round(duration, 2)),
                    "success": "false",
                    "error_type": type(e).__name__
                }}
            )
            raise

    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper


def log_temperature_reading(temp1: float, temp2: float, filtered: bool = False):
    """Log temperature readings with structured data"""
    logger = get_logger("temperature.readings", "sensor")
    logger.info(
        "Temperature reading recorded",
        extra={"tags": {
            "operation": "temperature_reading",
            "sensor1": str(temp1),
            "sensor2": str(temp2),
            "outlier_filtered": str(filtered).lower(),
        }}
    )


def log_redis_message(channel: str, data: Dict[str, Any], success: bool = True):
    """Log Redis message processing"""
    logger = get_logger("temperature.redis", "redis")

    if success:
        logger.info(
            f"Redis message processed from channel {channel}",
            extra={"tags": {
                "operation": "redis_message",
                "redis_channel": channel,
                "success": "true",
            }}
        )
    else:
        logger.error(
            f"Failed to process Redis message from channel {channel}",
            extra={"tags": {
                "operation": "redis_message",
                "redis_channel": channel,
                "success": "false",
            }}
        )


def log_database_operation(operation: str, success: bool = True, record_count: int = None, error: str = None):
    """Log database operations"""
    logger = get_logger("temperature.database", "database")

    tags = {
        "operation": "database",
        "db_operation": operation,
        "success": str(success).lower()
    }

    if record_count is not None:
        tags["record_count"] = str(record_count)

    if success:
        logger.info(f"Database {operation} completed successfully", extra={"tags": tags})
    else:
        tags["error_type"] = "DatabaseError"
        logger.error(f"Database {operation} failed: {error}", extra={"tags": tags})


def log_api_request(method: str, path: str, status_code: int, duration_ms: float, user_agent: str = None):
    """Log API requests"""
    logger = get_logger("temperature.api", "api")

    tags = {
        "operation": "api_request",
        "http_method": method,
        "http_path": path,
        "http_status": str(status_code),
        "duration_ms": str(round(duration_ms, 2)),
        "success": str(200 <= status_code < 400).lower()
    }

    logger.info(f"{method} {path} - {status_code}", extra={"tags": tags})


# Initialize logging on module import
if __name__ != "__main__":
    setup_logging()
