import json
import os
import subprocess
import unittest
from unittest.mock import patch

from app.core.process_utils import probe_media_json, run_hidden


class ProcessUtilsTests(unittest.TestCase):
    @patch("app.core.process_utils.subprocess.run")
    def test_run_hidden_applies_windows_no_console_flags(self, run_mock):
        run_hidden(["tool.exe", "-version"])

        kwargs = run_mock.call_args.kwargs
        if os.name == "nt":
            self.assertTrue(kwargs["creationflags"] & subprocess.CREATE_NO_WINDOW)
            self.assertEqual(kwargs["startupinfo"].wShowWindow, subprocess.SW_HIDE)
        else:
            self.assertNotIn("creationflags", kwargs)

    @patch("app.core.process_utils.run_hidden")
    def test_probe_media_json_uses_json_ffprobe_contract(self, run_mock):
        run_mock.return_value.returncode = 0
        run_mock.return_value.stdout = json.dumps(
            {"streams": [{"codec_type": "video"}]}
        ).encode("utf-8")
        run_mock.return_value.stderr = b""

        result = probe_media_json("ffprobe.exe", "input.mkv")

        self.assertEqual(result["streams"][0]["codec_type"], "video")
        command = run_mock.call_args.args[0]
        self.assertIn("-show_streams", command)
        self.assertEqual(command[-1], "input.mkv")


if __name__ == "__main__":
    unittest.main()
