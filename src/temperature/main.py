#!/usr/bin/env python
"""
Temperature Monitor - Main Entry Point
"""

import uvicorn
from src.temperature.app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        access_log=True
    )
