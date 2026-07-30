import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.core.ffmpeg_manager import FFmpegManager


class FFmpegManagerTests(unittest.TestCase):
    def setUp(self):
        FFmpegManager._instance = None
        self.temp_dir = tempfile.TemporaryDirectory()
        self.manager = FFmpegManager()
        self.manager.app_dir = self.temp_dir.name
        self.manager.ffmpeg_dir = os.path.join(self.temp_dir.name, "ffmpeg")
        self.manager.default_ffmpeg_path = os.path.join(self.manager.ffmpeg_dir, "ffmpeg.exe")
        self.manager.default_ffprobe_path = os.path.join(self.manager.ffmpeg_dir, "ffprobe.exe")
        self.manager.ffmpeg_path = None
        self.manager.ffprobe_path = None

    def tearDown(self):
        self.temp_dir.cleanup()
        FFmpegManager._instance = None

    def _write_pair(self, bin_dir: Path):
        bin_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg_path = bin_dir / "ffmpeg.exe"
        ffprobe_path = bin_dir / "ffprobe.exe"
        ffmpeg_path.write_text("fake ffmpeg", encoding="utf-8")
        ffprobe_path.write_text("fake ffprobe", encoding="utf-8")
        return str(ffmpeg_path)

    def test_parse_sha256_extracts_digest_from_checksum_file(self):
        digest = "A" * 64
        self.assertEqual(
            FFmpegManager.parse_sha256(f"{digest} *ffmpeg-release-essentials.zip"),
            digest.lower(),
        )
        self.assertEqual(FFmpegManager.parse_sha256("not-a-digest"), "")

    def test_ensure_ffmpeg_exists_prefers_saved_path_before_cache(self):
        saved_ffmpeg = self._write_pair(Path(self.temp_dir.name) / "saved" / "bin")
        self._write_pair(Path(self.manager.ffmpeg_dir) / "8.1.2" / "bin")

        resolved = self.manager.ensure_ffmpeg_exists(saved_path=saved_ffmpeg, allow_download=False)

        self.assertEqual(resolved, os.path.abspath(saved_ffmpeg))
        self.assertEqual(self.manager.get_ffprobe_path(), os.path.join(os.path.dirname(resolved), "ffprobe.exe"))
    def test_encoder_capabilities_backfills_missing_singleton_cache_fields(self):
        delattr(self.manager, "_encoder_capabilities_cache")
        delattr(self.manager, "_encoder_capabilities_path")

        capabilities = self.manager.get_encoder_capabilities()

        self.assertFalse(capabilities.nvenc_available)
        self.assertTrue(hasattr(self.manager, "_encoder_capabilities_cache"))
        self.assertTrue(hasattr(self.manager, "_encoder_capabilities_path"))

    def test_encoder_capabilities_rejects_advertised_but_unusable_nvenc(self):
        self.manager.ffmpeg_path = self._write_pair(
            Path(self.temp_dir.name) / "installed" / "bin"
        )
        encoder_list = b" V....D h264_nvenc NVIDIA NVENC H.264 encoder\n"
        driver_error = (
            b"Driver does not support the required nvenc API version.\n"
            b"The minimum required Nvidia driver for nvenc is 610.00 or newer.\n"
        )
        with patch(
            "app.core.ffmpeg_manager.subprocess.run",
            side_effect=[
                subprocess.CompletedProcess([], 0, stdout=encoder_list, stderr=b""),
                subprocess.CompletedProcess([], 1, stdout=b"", stderr=driver_error),
            ],
        ) as run_mock:
            capabilities = self.manager.get_encoder_capabilities(force_refresh=True)

        probe_command = run_mock.call_args_list[1].args[0]
        self.assertIn("color=c=black:s=256x256:r=1:d=1", probe_command)
        self.assertIn("h264_nvenc", capabilities.encoders)
        self.assertFalse(capabilities.nvenc_available)
        self.assertIn("610.00", capabilities.encoder_errors["h264_nvenc"])
        self.assertFalse(self.manager.supports_encoder("h264_nvenc"))

    def test_download_and_install_ffmpeg_verifies_sha_and_installs_versioned_cache(self):
        source_zip = Path(self.temp_dir.name) / "source.zip"
        with zipfile.ZipFile(source_zip, "w") as archive:
            archive.writestr("ffmpeg-8.1.2-essentials_build/bin/ffmpeg.exe", "fake ffmpeg")
            archive.writestr("ffmpeg-8.1.2-essentials_build/bin/ffprobe.exe", "fake ffprobe")

        expected_sha = hashlib.sha256(source_zip.read_bytes()).hexdigest()

        def fake_download(url, output_path, progress_callback=None):
            shutil.copy2(source_zip, output_path)
            return expected_sha

        self.manager._download_file = fake_download
        progress = []

        resolved = self.manager.download_and_install_ffmpeg(
            progress_callback=lambda value, message: progress.append((value, message)),
            metadata={
                "version": "8.1.2",
                "sha256": expected_sha,
                "download_url": "https://example.invalid/ffmpeg.zip",
            },
        )

        expected = os.path.join(self.manager.ffmpeg_dir, "8.1.2", "bin", "ffmpeg.exe")
        self.assertEqual(resolved, os.path.abspath(expected))
        self.assertTrue(os.path.exists(expected))
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(expected), "ffprobe.exe")))
        self.assertEqual(progress[-1], (100, "FFmpeg installed"))


if __name__ == "__main__":
    unittest.main()
