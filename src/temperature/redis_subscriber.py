import redis
import json
import threading
import asyncio
from datetime import datetime
from typing import Callable
import os
from .logging_config import get_logger, log_redis_message

logger = get_logger(__name__, "redis")


class RedisSubscriber:
    """Subscribes to Redis channel and processes temperature messages"""

    def __init__(
        self,
        host: str = None,
        port: int = None,
        db: int = None,
        password: str = None,
        channel: str = "temps",
    ):
        # Use environment variables with fallbacks
        self.host = host or os.getenv("REDIS_HOST", "172.23.73.28")
        self.port = port or int(os.getenv("REDIS_PORT", 6379))
        self.db = db or int(os.getenv("REDIS_DB", 0))
        self.password = password or os.getenv("REDIS_PASSWORD", "nnwbQa2xDmJLPn4m7N9J5FK93")
        self.channel = channel
        self.redis_client = None
        self.pubsub = None
        self.running = False
        self.thread = None
        self.on_message_callback: Callable = None

    def connect(self) -> bool:
        """Establish connection to Redis"""
        try:
            self.redis_client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True,
                password=self.password,
            )
            # Test connection
            self.redis_client.ping()
            logger.info(
                "Connected to Redis successfully",
                extra={
                    "operation": "redis_connect",
                    "redis_host": self.host,
                    "redis_port": self.port,
                    "redis_db": self.db,
                    "success": True
                }
            )
            return True
        except Exception as e:
            logger.error(
                "Failed to connect to Redis",
                extra={
                    "operation": "redis_connect",
                    "redis_host": self.host,
                    "redis_port": self.port,
                    "redis_db": self.db,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "success": False
                }
            )
            return False

    def set_message_callback(self, callback: Callable):
        """Set callback function to handle incoming messages"""
        self.on_message_callback = callback

    def start(self):
        """Start listening to Redis channel in background thread"""
        if self.running:
            logger.warning(
                "Redis subscriber already running",
                extra={
                    "operation": "redis_start",
                    "already_running": True
                }
            )
            return

        if not self.redis_client:
            if not self.connect():
                return

        self.running = True
        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()
        logger.info(
            "Redis subscriber started",
            extra={
                "operation": "redis_start",
                "redis_channel": self.channel,
                "success": True
            }
        )

    def _listen_loop(self):
        """Main listening loop (runs in background thread)"""
        try:
            self.pubsub = self.redis_client.pubsub()
            self.pubsub.subscribe(self.channel)

            logger.info(
                "Redis listening loop started",
                extra={
                    "operation": "redis_listen_start",
                    "redis_channel": self.channel
                }
            )

            for message in self.pubsub.listen():
                if not self.running:
                    break

                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        
                        log_redis_message(self.channel, data, success=True)

                        if self.on_message_callback:
                            # Handle both sync and async callbacks
                            if asyncio.iscoroutinefunction(self.on_message_callback):
                                asyncio.run(self.on_message_callback(data))
                            else:
                                self.on_message_callback(data)
                    except json.JSONDecodeError as e:
                        logger.error(
                            "Invalid JSON received from Redis",
                            extra={
                                "operation": "redis_message_decode",
                                "redis_channel": self.channel,
                                "raw_data": message["data"],
                                "error": str(e),
                                "error_type": "JSONDecodeError"
                            }
                        )
                        log_redis_message(self.channel, {"raw": message["data"]}, success=False)
                    except Exception as e:
                        logger.error(
                            "Error processing Redis message",
                            extra={
                                "operation": "redis_message_process",
                                "redis_channel": self.channel,
                                "error": str(e),
                                "error_type": type(e).__name__
                            }
                        )
        except Exception as e:
            logger.error(
                "Redis listening loop error",
                extra={
                    "operation": "redis_listen_loop",
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "redis_channel": self.channel
                }
            )
        finally:
            if self.pubsub:
                self.pubsub.unsubscribe(self.channel)
                logger.info(
                    "Unsubscribed from Redis channel",
                    extra={
                        "operation": "redis_unsubscribe",
                        "redis_channel": self.channel
                    }
                )

    def stop(self):
        """Stop listening to Redis channel"""
        logger.info(
            "Stopping Redis subscriber",
            extra={
                "operation": "redis_stop",
                "redis_channel": self.channel
            }
        )
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        if self.pubsub:
            self.pubsub.close()
        if self.redis_client:
            self.redis_client.close()
        logger.info(
            "Redis subscriber stopped",
            extra={
                "operation": "redis_stop_complete",
                "redis_channel": self.channel
            }
        )
