import unittest

from app.services.settings_service import SettingsService, _MemorySettings


class SettingsServiceTests(unittest.TestCase):
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
