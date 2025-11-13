import json
from pathlib import Path
from typing import Dict, Any
import threading

SETTINGS_FILE = Path("settings.json")


class SettingsStore:
    """Thread-safe settings storage"""

    def __init__(self, default_threshold: float = 200.0):
        self.lock = threading.Lock()
        self.default_threshold = default_threshold
        self._load_settings()

    def _load_settings(self):
        """Load settings from file"""
        with self.lock:
            if SETTINGS_FILE.exists():
                try:
                    with open(SETTINGS_FILE, "r") as f:
                        self.settings: Dict[str, Any] = json.load(f)
                except Exception as e:
                    print(f"Error loading settings: {e}")
                    self.settings = {"temp_threshold": self.default_threshold}
            else:
                self.settings = {"temp_threshold": self.default_threshold}

    def _save_settings(self):
        """Save settings to file"""
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")

    def get_threshold(self) -> float:
        """Get temperature threshold"""
        with self.lock:
            return self.settings.get("temp_threshold", self.default_threshold)

    def set_threshold(self, value: float) -> float:
        """Set temperature threshold"""
        with self.lock:
            self.settings["temp_threshold"] = value
            self._save_settings()
            return value
