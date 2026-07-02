# update.py

import logging
import os
import sys

import requests
from packaging.version import parse as parse_version
from PySide6.QtCore import QObject, QThread

from app.config import APP_VERSION
from app.core.events import Events, event_emitter
from app.services.logging_service import LoggingService

logger = logging.getLogger(__name__)


class UpdateDownloader(QThread):
    """Download an application update in the background."""

    def __init__(self, url, target_path):
        super().__init__()
        self.url = url
        self.target_path = target_path
        self.logger = LoggingService().get_logger(__name__)

    def run(self):
        try:
            event_emitter.emit(Events.UPDATE_DOWNLOAD_STARTED)
            response = requests.get(self.url, stream=True, timeout=30)
            response.raise_for_status()

            total_size = int(response.headers.get("content-length", 0) or 0)
            block_size = 1024 * 256
            downloaded = 0

            with open(self.target_path, "wb") as f:
                for data in response.iter_content(block_size):
                    if not data:
                        continue
                    downloaded += len(data)
                    f.write(data)
                    if total_size:
                        progress = int((downloaded / total_size) * 100)
                        event_emitter.emit(Events.UPDATE_DOWNLOAD_PROGRESS, progress)

            event_emitter.emit(Events.UPDATE_DOWNLOAD_COMPLETED, self.target_path)
        except Exception as e:
            self.logger.error(f"업데이트 다운로드 중 오류: {e}")
            event_emitter.emit(Events.UPDATE_DOWNLOAD_ERROR, str(e))


class UpdateChecker(QObject):
    """Check GitHub releases and coordinate update download events."""

    def __init__(self):
        super().__init__()
        self.logger = LoggingService().get_logger(__name__)
        self.current_version = APP_VERSION
        self.update_url = "https://api.github.com/repos/CharlieYang0040/ffmpegGUI/releases/latest"
        self.update_button = None
        self.downloader = None

    def check_for_updates(self):
        try:
            self.logger.info("업데이트 확인 시작")
            response = requests.get(self.update_url, timeout=15)
            response.raise_for_status()

            release_info = response.json()
            latest_version = release_info["tag_name"].lstrip("v")
            assets = release_info.get("assets", [])
            download_url = assets[0]["browser_download_url"] if assets else release_info.get("html_url", "")

            if self._is_newer_version(latest_version):
                self.logger.info(f"새로운 버전 발견: {latest_version}")
                event_emitter.emit(Events.UPDATE_AVAILABLE, latest_version, download_url)
            else:
                self.logger.info("최신 버전 사용 중")
                event_emitter.emit(Events.UPDATE_NOT_AVAILABLE)
        except Exception as e:
            self.logger.error(f"업데이트 확인 중 오류: {e}")
            event_emitter.emit(Events.UPDATE_ERROR, str(e))

    def download_and_install_update(self, download_url):
        try:
            temp_dir = os.path.join(os.path.dirname(sys.executable), "temp")
            os.makedirs(temp_dir, exist_ok=True)
            temp_file = os.path.join(temp_dir, "update.exe")

            self.downloader = UpdateDownloader(download_url, temp_file)
            self.downloader.finished.connect(lambda: self._install_update(temp_file))
            self.downloader.start()
        except Exception as e:
            self.logger.error(f"업데이트 다운로드 준비 중 오류: {e}")
            event_emitter.emit(Events.UPDATE_ERROR, str(e))

    def _install_update(self, update_file):
        try:
            event_emitter.emit(Events.UPDATE_INSTALL_STARTED)
            # Real installer launch is intentionally left to release packaging.
            event_emitter.emit(Events.UPDATE_INSTALL_COMPLETED)
        except Exception as e:
            self.logger.error(f"업데이트 설치 중 오류: {e}")
            event_emitter.emit(Events.UPDATE_INSTALL_ERROR, str(e))

    def _is_newer_version(self, latest_version):
        try:
            return parse_version(latest_version) > parse_version(self.current_version)
        except Exception:
            current = [int(x) for x in self.current_version.split(".") if x.isdigit()]
            latest = [int(x) for x in latest_version.split(".") if x.isdigit()]
            return latest > current
