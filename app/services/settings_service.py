# app/services/settings_service.py
import logging


class _MemorySettings:
    """Small QSettings-compatible fallback for test environments without PySide6."""

    def __init__(self):
        self._values = {}

    def value(self, key, default=None, type=None):
        value = self._values.get(key, default)
        if type is not None and value is not None:
            try:
                if type is bool and isinstance(value, str):
                    return value.lower() in {"1", "true", "yes", "on"}
                return type(value)
            except (TypeError, ValueError):
                return default
        return value

    def setValue(self, key, value):
        self._values[key] = value

    def allKeys(self):
        return list(self._values.keys())

    def clear(self):
        self._values.clear()

    def sync(self):
        return None


class SettingsService:
    """Singleton wrapper around QSettings with a lightweight test fallback."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        try:
            from PySide6.QtCore import QSettings

            self.settings = QSettings("LHCinema", "ffmpegGUI")
        except ModuleNotFoundError:
            self.settings = _MemorySettings()

        self.logger = logging.getLogger(__name__)
        self.logger.debug("SettingsService initialized")

    def get(self, key, default=None, type=None):
        if type is None:
            return self.settings.value(key, default)
        return self.settings.value(key, default, type=type)

    def set(self, key, value):
        self.settings.setValue(key, value)
        self.logger.debug(f"Setting saved: {key}={value}")

    def sync(self):
        self.settings.sync()

    def get_ffmpeg_path(self):
        return self.get("ffmpeg_path", "", type=str)

    def set_ffmpeg_path(self, path):
        self.set("ffmpeg_path", path)

    def get_last_output_path(self):
        return self.get("last_output_path", "")

    def set_last_output_path(self, path):
        self.set("last_output_path", path)

    def get_debug_mode(self):
        return self.get("debug_mode", False, type=bool)

    def set_debug_mode(self, enabled):
        self.set("debug_mode", enabled)

    def get_rv_path(self):
        return self.get("rv_path", "")

    def set_rv_path(self, path):
        self.set("rv_path", path)

    def get_all_settings(self):
        return {key: self.settings.value(key) for key in self.settings.allKeys()}

    def get_all_keys(self):
        return self.settings.allKeys()

    def clear_settings(self):
        self.settings.clear()
        self.logger.info("All settings have been cleared.")

    def clear(self):
        self.clear_settings()
