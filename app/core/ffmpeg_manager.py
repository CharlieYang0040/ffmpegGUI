# app/core/ffmpeg_manager.py
import hashlib
import logging
import os
import shutil
import subprocess
import sys
import time
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable, Iterable, Optional

from app.core.ffmpeg_process import decode_process_output, iter_decoded_lines
from app.core.models import FFmpegEncoderCapabilities

try:
    import appdirs
except ModuleNotFoundError:  # pragma: no cover - exercised when dev env is incomplete
    class _AppDirsFallback:
        @staticmethod
        def user_data_dir(appname, appauthor):
            base_dir = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
            return os.path.join(base_dir, appauthor, appname)

    appdirs = _AppDirsFallback()


ProgressCallback = Optional[Callable[[int, str], None]]


class FFmpegManager:
    """Manage ffmpeg/ffprobe discovery, validation, download, and execution."""

    _instance = None

    GYAN_BASE_URL = "https://www.gyan.dev/ffmpeg/builds"
    RELEASE_ZIP_URL = f"{GYAN_BASE_URL}/ffmpeg-release-essentials.zip"
    RELEASE_VERSION_URL = f"{GYAN_BASE_URL}/ffmpeg-release-essentials.zip.ver"
    RELEASE_SHA256_URL = f"{GYAN_BASE_URL}/ffmpeg-release-essentials.zip.sha256"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FFmpegManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        self.logger = logging.getLogger(__name__)
        self.ffmpeg_path = None
        self.ffprobe_path = None
        self._encoder_capabilities_cache = None
        self._encoder_capabilities_path = None

        self.app_name = "ffmpegGUI"
        self.company = "LHCinema"
        appdata_dir = os.environ.get("APPDATA")
        if appdata_dir:
            self.app_dir = os.path.join(appdata_dir, self.company, self.app_name)
        else:
            self.app_dir = appdirs.user_data_dir(self.app_name, self.company)
        self.ffmpeg_dir = os.path.join(self.app_dir, "ffmpeg")

        # Kept for backward compatibility with older installs.
        self.default_ffmpeg_path = os.path.join(self.ffmpeg_dir, "ffmpeg.exe")
        self.default_ffprobe_path = os.path.join(self.ffmpeg_dir, "ffprobe.exe")

        self.logger.debug("FFmpegManager initialized")

    def _ensure_encoder_capability_cache(self) -> None:
        """Backfill encoder capability cache fields for existing singleton instances."""
        if not hasattr(self, "_encoder_capabilities_cache"):
            self._encoder_capabilities_cache = None
        if not hasattr(self, "_encoder_capabilities_path"):
            self._encoder_capabilities_path = None

    def _emit_progress(self, callback: ProgressCallback, value: int, message: str) -> None:
        if callback:
            callback(max(0, min(100, int(value))), message)

    def _is_valid_pair(self, ffmpeg_path: str) -> bool:
        if not ffmpeg_path or not os.path.exists(ffmpeg_path):
            return False
        ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), "ffprobe.exe")
        return os.path.exists(ffprobe_path)

    def _versioned_cache_candidates(self) -> Iterable[str]:
        root = Path(self.ffmpeg_dir)
        if not root.exists():
            return []

        candidates = []
        for bin_dir in root.glob("*/bin"):
            ffmpeg_path = bin_dir / "ffmpeg.exe"
            if ffmpeg_path.exists():
                candidates.append(str(ffmpeg_path))
        return sorted(candidates, reverse=True)

    def find_existing_ffmpeg(self, saved_path: Optional[str] = None) -> str:
        """Find an existing ffmpeg installation without downloading anything."""
        candidates = []

        if self.ffmpeg_path:
            candidates.append(self.ffmpeg_path)
        if saved_path:
            candidates.append(saved_path)

        candidates.extend([
            self.default_ffmpeg_path,
            *self._versioned_cache_candidates(),
        ])

        path_ffmpeg = shutil.which("ffmpeg.exe") or shutil.which("ffmpeg")
        if path_ffmpeg:
            candidates.append(path_ffmpeg)

        seen = set()
        for candidate in candidates:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            if self._is_valid_pair(candidate) and self.set_ffmpeg_path(candidate):
                return self.ffmpeg_path

        return ""

    def set_ffmpeg_path(self, path):
        """Set and validate ffmpeg/ffprobe paths."""
        self.logger.debug(f"Trying FFmpeg path: {path}")

        if not self._is_valid_pair(path):
            self.logger.warning(f"Invalid FFmpeg pair: {path}")
            return False

        old_path = getattr(self, "ffmpeg_path", None)
        self.ffmpeg_path = os.path.abspath(path)
        self.ffprobe_path = os.path.join(os.path.dirname(self.ffmpeg_path), "ffprobe.exe")
        self._ensure_encoder_capability_cache()
        if old_path != self.ffmpeg_path:
            self._encoder_capabilities_cache = None
            self._encoder_capabilities_path = None
        self.logger.info(f"FFmpeg path set: {self.ffmpeg_path}")
        return True

    def get_ffmpeg_path(self):
        return self.ffmpeg_path

    def get_ffprobe_path(self):
        return self.ffprobe_path

    def ensure_ffmpeg_exists(
        self,
        saved_path: Optional[str] = None,
        allow_download: bool = True,
        progress_callback: ProgressCallback = None,
    ) -> str:
        """Resolve ffmpeg, optionally downloading the current gyan.dev essentials build."""
        existing_path = self.find_existing_ffmpeg(saved_path)
        if existing_path:
            self._emit_progress(progress_callback, 100, "FFmpeg found")
            return existing_path

        if not allow_download:
            self.logger.error("FFmpeg was not found and automatic download is disabled")
            return ""

        self.logger.info("FFmpeg not found; starting automatic download")
        return self.download_and_install_ffmpeg(progress_callback=progress_callback)

    def _read_text_url(self, url: str, timeout: int = 30) -> str:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8", errors="replace").strip()

    def fetch_release_metadata(self) -> dict:
        """Fetch release version and sha256 metadata from gyan.dev."""
        version = self._read_text_url(self.RELEASE_VERSION_URL)
        sha256 = self.parse_sha256(self._read_text_url(self.RELEASE_SHA256_URL))
        if not version:
            raise ValueError("FFmpeg release version is empty")
        if not sha256:
            raise ValueError("FFmpeg release sha256 is empty")
        return {
            "version": version,
            "sha256": sha256,
            "download_url": self.RELEASE_ZIP_URL,
        }

    @staticmethod
    def parse_sha256(text: str) -> str:
        """Extract a sha256 digest from a checksum file body."""
        if not text:
            return ""
        for token in text.replace("*", " ").split():
            if len(token) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in token):
                return token.lower()
        return ""

    @staticmethod
    def parse_encoder_names(text: str) -> set[str]:
        """Parse encoder names from `ffmpeg -encoders` output."""
        encoders = set()
        for line in (text or "").splitlines():
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            flags, name = parts[0], parts[1]
            if len(flags) >= 6 and ("V" in flags or "A" in flags or "S" in flags):
                encoders.add(name)
        return encoders

    def get_encoder_capabilities(self, force_refresh: bool = False) -> FFmpegEncoderCapabilities:
        """Return encoder capabilities for the configured FFmpeg binary."""
        self._ensure_encoder_capability_cache()
        ffmpeg_path = self.get_ffmpeg_path()
        if not ffmpeg_path or not os.path.exists(ffmpeg_path):
            return FFmpegEncoderCapabilities(
                encoders=set(),
                nvenc_available=False,
                checked_at=time.time(),
                message="FFmpeg 경로가 설정되지 않았습니다.",
            )

        if (
            not force_refresh
            and self._encoder_capabilities_cache is not None
            and self._encoder_capabilities_path == ffmpeg_path
        ):
            return self._encoder_capabilities_cache

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            result = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                creationflags=creationflags,
            )
            output = decode_process_output(result.stdout) + decode_process_output(result.stderr)
            if result.returncode != 0:
                capabilities = FFmpegEncoderCapabilities(
                    encoders=set(),
                    nvenc_available=False,
                    checked_at=time.time(),
                    message=f"FFmpeg encoder 목록을 확인할 수 없습니다. 코드: {result.returncode}",
                )
            else:
                encoders = self.parse_encoder_names(output)
                capabilities = FFmpegEncoderCapabilities(
                    encoders=encoders,
                    nvenc_available=bool({"h264_nvenc", "hevc_nvenc"} & encoders),
                    checked_at=time.time(),
                    message=f"{len(encoders)}개 encoder 확인됨",
                )
        except Exception as exc:
            capabilities = FFmpegEncoderCapabilities(
                encoders=set(),
                nvenc_available=False,
                checked_at=time.time(),
                message=f"FFmpeg encoder 확인 실패: {exc}",
            )

        self._encoder_capabilities_cache = capabilities
        self._encoder_capabilities_path = ffmpeg_path
        return capabilities

    def supports_encoder(self, encoder_name: str) -> bool:
        return encoder_name in self.get_encoder_capabilities().encoders

    def _download_file(self, url: str, output_path: str, progress_callback: ProgressCallback = None) -> str:
        with urllib.request.urlopen(url, timeout=60) as response:
            total = int(response.headers.get("Content-Length", "0") or 0)
            downloaded = 0
            digest = hashlib.sha256()

            with open(output_path, "wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if total:
                        percent = 10 + int((downloaded / total) * 60)
                        self._emit_progress(progress_callback, percent, "Downloading FFmpeg")

        return digest.hexdigest()

    def _find_extracted_binary(self, extract_dir: str, binary_name: str) -> str:
        for root, _, files in os.walk(extract_dir):
            if binary_name in files:
                return os.path.join(root, binary_name)
        return ""

    def download_and_install_ffmpeg(
        self,
        progress_callback: ProgressCallback = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """Download, verify, extract, and cache ffmpeg/ffprobe."""
        self._emit_progress(progress_callback, 2, "Reading FFmpeg release metadata")
        metadata = metadata or self.fetch_release_metadata()
        version = str(metadata["version"]).strip()
        expected_sha256 = str(metadata["sha256"]).strip().lower()
        download_url = str(metadata["download_url"]).strip()

        install_bin_dir = os.path.join(self.ffmpeg_dir, version, "bin")
        cached_ffmpeg = os.path.join(install_bin_dir, "ffmpeg.exe")
        if os.path.exists(cached_ffmpeg) and self.set_ffmpeg_path(cached_ffmpeg):
            self._emit_progress(progress_callback, 100, "Cached FFmpeg found")
            return self.ffmpeg_path

        os.makedirs(self.ffmpeg_dir, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix="ffmpeggui_ffmpeg_") as temp_dir:
            zip_path = os.path.join(temp_dir, "ffmpeg-release-essentials.zip")
            self._emit_progress(progress_callback, 10, "Downloading FFmpeg")
            actual_sha256 = self._download_file(download_url, zip_path, progress_callback)

            if actual_sha256.lower() != expected_sha256:
                raise ValueError(
                    "FFmpeg download checksum mismatch: "
                    f"expected {expected_sha256}, got {actual_sha256}"
                )

            self._emit_progress(progress_callback, 72, "Extracting FFmpeg")
            extract_dir = os.path.join(temp_dir, "extract")
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)

            ffmpeg_source = self._find_extracted_binary(extract_dir, "ffmpeg.exe")
            ffprobe_source = self._find_extracted_binary(extract_dir, "ffprobe.exe")
            if not ffmpeg_source or not ffprobe_source:
                raise FileNotFoundError("Downloaded archive does not contain ffmpeg.exe and ffprobe.exe")

            self._emit_progress(progress_callback, 88, "Installing FFmpeg")
            os.makedirs(install_bin_dir, exist_ok=True)
            shutil.copy2(ffmpeg_source, os.path.join(install_bin_dir, "ffmpeg.exe"))
            shutil.copy2(ffprobe_source, os.path.join(install_bin_dir, "ffprobe.exe"))

        if not self.set_ffmpeg_path(cached_ffmpeg):
            raise RuntimeError("Installed FFmpeg could not be validated")

        self._emit_progress(progress_callback, 100, "FFmpeg installed")
        return self.ffmpeg_path

    def get_version_info(self):
        info = {
            "ffmpeg_path": self.ffmpeg_path or "Not configured",
            "ffprobe_path": self.ffprobe_path or "Not configured",
        }

        try:
            if self.ffmpeg_path and os.path.exists(self.ffmpeg_path):
                result = subprocess.run(
                    [self.ffmpeg_path, "-version"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )
                stdout = decode_process_output(result.stdout)
                info["ffmpeg_version"] = (
                    stdout.splitlines()[0]
                    if result.returncode == 0 and stdout
                    else "FFmpeg version check failed"
                )
            else:
                info["ffmpeg_version"] = "FFmpeg path is not configured"
        except Exception as e:
            info["ffmpeg_version"] = f"Error: {e}"

        return info

    def run_ffmpeg_command(self, args, progress_callback=None):
        if not self.ffmpeg_path:
            return False, "FFmpeg path is not configured."

        process = None
        try:
            cmd = [self.ffmpeg_path] + args
            self.logger.debug(f"Running FFmpeg command: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            stderr_lines = []
            if progress_callback:
                import re
                for line in iter_decoded_lines(process.stderr):
                    stderr_lines.append(line)
                    self.logger.debug(line.strip())
                    if "time=" in line:
                        try:
                            time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                            if time_match:
                                h, m, s = map(float, time_match.group(1).split(":"))
                                progress_callback(h * 3600 + m * 60 + s)
                        except Exception as e:
                            self.logger.warning(f"Progress parse error: {e}")

            stdout, stderr = process.communicate()
            stderr_text = "\n".join(stderr_lines) or decode_process_output(stderr)
            stdout_text = decode_process_output(stdout)
            if process.returncode != 0:
                self.logger.error(f"FFmpeg command failed ({process.returncode}): {stderr_text}")
                return False, stderr_text

            return True, stdout_text
        except Exception as e:
            self.logger.exception(f"Error while running FFmpeg command: {e}")
            return False, str(e)
        finally:
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    pass

    def initialize_ffmpeg(self, ffmpeg_path: str) -> bool:
        self.logger.info(f"Initializing FFmpeg: {ffmpeg_path}")
        return self.set_ffmpeg_path(ffmpeg_path)
