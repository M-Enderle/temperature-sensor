"""
Loki configuration constants
"""
import os

LOKI_URL = os.getenv("LOKI_URL") or "http://loki:3100"
LOKI_PUSH_ENDPOINT = f"{LOKI_URL}/loki/api/v1/push"

SERVICE_NAME = os.getenv("SERVICE_NAME", "temperature-sensor")
SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.1.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
