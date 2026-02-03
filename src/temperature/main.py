#!/usr/bin/env python
"""
Temperature Monitor - Main Entry Point
"""

import uvicorn
from src.temperature.logging_config import setup_logging, get_logger
from src.temperature.app import app

if __name__ == "__main__":
    # Setup Loki-compatible logging
    setup_logging()
    logger = get_logger(__name__, "main")
    
    logger.info(
        "Starting temperature sensor application",
        extra={
            "operation": "application_startup",
            "host": "0.0.0.0",
            "port": 8000
        }
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True,
        log_config=None  # Use our custom logging configuration
    )
