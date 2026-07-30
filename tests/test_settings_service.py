import unittest

from unittest.mock import patch

from app.services.logging_service import LoggingService
from app.services.settings_service import SettingsService, _MemorySettings


class SettingsServiceTests(unittest.TestCase):
    def test_logging_service_initialization_does_not_write_to_stdout(self):
        original_instance = LoggingService._instance
        LoggingService._instance = None
        try:
            with patch("builtins.print") as mocked_print:
                LoggingService()
            mocked_print.assert_not_called()
        finally:
            LoggingService._instance = original_instance

    def setUp(self):
        SettingsService._instance = None
        self.service = SettingsService()
        self.service.settings = _MemorySettings()

    def tearDown(self):
        SettingsService._instance = None

    def test_clear_settings_and_sync_are_available(self):
        self.service.set("ffmpeg_path", "C:/tools/ffmpeg.exe")
        self.service.set("debug_mode", True)

        self.service.clear_settings()
        self.service.sync()

        self.assertEqual(self.service.get("ffmpeg_path", ""), "")
        self.assertFalse(self.service.get("debug_mode", False, type=bool))

    def test_clear_alias_uses_clear_settings(self):
        self.service.set("last_output_path", "C:/out.mp4")
        self.service.clear()

        self.assertEqual(self.service.get_all_keys(), [])


if __name__ == "__main__":
    unittest.main()
