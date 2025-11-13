import redis
import json
import threading
import asyncio
from datetime import datetime
from typing import Callable
import logging
import os

logger = logging.getLogger(__name__)


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
            logger.info("✓ Connected to Redis")
            return True
        except Exception as e:
            logger.error(f"✗ Failed to connect to Redis: {e}")
            return False

    def set_message_callback(self, callback: Callable):
        """Set callback function to handle incoming messages"""
        self.on_message_callback = callback

    def start(self):
        """Start listening to Redis channel in background thread"""
        if self.running:
            logger.warning("Subscriber already running")
            return

        if not self.redis_client:
            if not self.connect():
                return

        self.running = True
        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()
        logger.info(f"✓ Subscribed to channel: {self.channel}")

    def _listen_loop(self):
        """Main listening loop (runs in background thread)"""
        try:
            self.pubsub = self.redis_client.pubsub()
            self.pubsub.subscribe(self.channel)

            for message in self.pubsub.listen():
                if not self.running:
                    break

                print(message)

                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        timestamp = datetime.now().isoformat()

                        logger.info(
                            f"[{timestamp}] Received: {data}"
                        )

                        if self.on_message_callback:
                            # Handle both sync and async callbacks
                            if asyncio.iscoroutinefunction(self.on_message_callback):
                                asyncio.run(self.on_message_callback(data))
                            else:
                                self.on_message_callback(data)
                    except json.JSONDecodeError:
                        logger.error(f"Invalid JSON: {message['data']}")
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
        except Exception as e:
            logger.error(f"Listening loop error: {e}")
        finally:
            if self.pubsub:
                self.pubsub.unsubscribe(self.channel)

    def stop(self):
        """Stop listening to Redis channel"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        if self.pubsub:
            self.pubsub.close()
        if self.redis_client:
            self.redis_client.close()
        logger.info("✓ Disconnected from Redis")
