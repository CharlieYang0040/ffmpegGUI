# update.py

import requests
import shutil
import tempfile
import os
import logging
import sys
import json
from PySide6.QtWidgets import QMessageBox, QProgressDialog
from PySide6.QtCore import QObject, Signal, QThread
from PySide6.QtGui import Qt
from app.services.logging_service import LoggingService
from app.core.events import event_emitter, Events

# 로깅 설정
logger = logging.getLogger(__name__)

class UpdateDownloader(QThread):
    """업데이트 다운로드를 위한 스레드 클래스"""
    def __init__(self, url, target_path):
        super().__init__()
        self.url = url
        self.target_path = target_path
        self.logger = LoggingService().get_logger(__name__)

    def run(self):
        try:
            event_emitter.emit(Events.UPDATE_DOWNLOAD_STARTED)
            response = requests.get(self.url, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            block_size = 1024
            downloaded = 0

            with open(self.target_path, 'wb') as f:
                for data in response.iter_content(block_size):
                    downloaded += len(data)
                    f.write(data)
                    if total_size:
                        progress = int((downloaded / total_size) * 100)
                        event_emitter.emit(Events.UPDATE_DOWNLOAD_PROGRESS, progress)

            event_emitter.emit(Events.UPDATE_DOWNLOAD_COMPLETED, self.target_path)

        except Exception as e:
            self.logger.error(f"업데이트 다운로드 중 오류: {str(e)}")
            event_emitter.emit(Events.UPDATE_DOWNLOAD_ERROR, str(e))

class UpdateChecker(QObject):
    """
    업데이트 확인 및 설치를 관리하는 클래스
    
    이벤트 기반 아키텍처를 사용하여 업데이트 상태를 전파합니다.
    """
    def __init__(self):
        super().__init__()
        self.logger = LoggingService().get_logger(__name__)
        self.current_version = "1.0.0"  # 현재 버전
        self.update_url = "https://api.github.com/repos/username/repo/releases/latest"  # 업데이트 확인 URL
        self.update_button = None

    def check_for_updates(self):
        """
        최신 버전을 확인하고 업데이트가 필요한 경우 이벤트를 발행합니다.
        """
        try:
            self.logger.info("업데이트 확인 시작")
            response = requests.get(self.update_url)
            response.raise_for_status()
            
            release_info = response.json()
            latest_version = release_info['tag_name'].lstrip('v')
            download_url = release_info['assets'][0]['browser_download_url']
            
            if self._is_newer_version(latest_version):
                self.logger.info(f"새로운 버전 발견: {latest_version}")
                event_emitter.emit(Events.UPDATE_AVAILABLE, latest_version, download_url)
            else:
                self.logger.info("최신 버전 사용 중")
                event_emitter.emit(Events.UPDATE_NOT_AVAILABLE)
                
        except Exception as e:
            self.logger.error(f"업데이트 확인 중 오류: {str(e)}")
            event_emitter.emit(Events.UPDATE_ERROR, str(e))

    def download_and_install_update(self, download_url):
        """
        업데이트를 다운로드하고 설치합니다.
        
        Args:
            download_url: 다운로드 URL
        """
        try:
            # 임시 파일 경로 생성
            temp_dir = os.path.join(os.path.dirname(sys.executable), 'temp')
            os.makedirs(temp_dir, exist_ok=True)
            temp_file = os.path.join(temp_dir, 'update.exe')
            
            # 다운로드 스레드 생성 및 시작
            self.downloader = UpdateDownloader(download_url, temp_file)
            self.downloader.finished.connect(lambda: self._install_update(temp_file))
            self.downloader.start()
            
        except Exception as e:
            self.logger.error(f"업데이트 다운로드 준비 중 오류: {str(e)}")
            event_emitter.emit(Events.UPDATE_ERROR, str(e))

    def _install_update(self, update_file):
        """
        다운로드된 업데이트를 설치합니다.
        
        Args:
            update_file: 업데이트 파일 경로
        """
        try:
            event_emitter.emit(Events.UPDATE_INSTALL_STARTED)
            
            # 여기에 실제 업데이트 설치 로직 구현
            # 예: os.system(f'start "" "{update_file}"')
            
            event_emitter.emit(Events.UPDATE_INSTALL_COMPLETED)
            
        except Exception as e:
            self.logger.error(f"업데이트 설치 중 오류: {str(e)}")
            event_emitter.emit(Events.UPDATE_INSTALL_ERROR, str(e))

    def _is_newer_version(self, latest_version):
        """
        최신 버전이 현재 버전보다 새로운지 확인합니다.
        
        Args:
            latest_version: 최신 버전 문자열
            
        Returns:
            bool: 최신 버전이 더 새로운 경우 True
        """
        current = [int(x) for x in self.current_version.split('.')]
        latest = [int(x) for x in latest_version.split('.')]
        
        for c, l in zip(current, latest):
            if l > c:
                return True
            elif l < c:
                return False
        return False  # 버전이 같은 경우