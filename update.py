# update.py

import requests
import shutil
import tempfile
import os
import logging
import sys
from PySide6.QtWidgets import QMessageBox, QProgressDialog
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import Qt

# 로깅 설정
logger = logging.getLogger(__name__)

class UpdateChecker(QObject):
    update_error = Signal(str)
    update_available = Signal(str, str)
    no_update = Signal()

    def __init__(self):
        super().__init__()
        self.updating = False
        self.update_button = None
        logger.debug("UpdateChecker 초기화됨")

    def check_for_updates(self):
        if self.updating:
            logger.debug("이미 업데이트 확인 중")
            return

        logger.info("업데이트 확인 시작")
        self.updating = True
        if self.update_button:
            self.update_button.setEnabled(False)
        self.perform_update_check()

    def perform_update_check(self):
        try:
            logger.debug("최신 버전 정보 가져오기 시작")
            latest_version, download_url = self.get_latest_version_info()
            from main import __version__
            logger.info(f"현재 버전: {__version__}, 최신 버전: {latest_version}")

            if self.is_newer_version(latest_version, __version__):
                logger.info("새로운 버전 발견")
                self.update_available.emit(latest_version, download_url)
            else:
                logger.info("최신 버전 사용 중")
                self.update_available.emit(latest_version, download_url)

        except Exception as e:
            logger.error(f"업데이트 확인 중 오류 발생: {str(e)}")
            self.update_error.emit(str(e))
        finally:
            self.updating = False
            if self.update_button:
                self.update_button.setEnabled(True)
            logger.debug("업데이트 확인 완료")

    def get_latest_version_info(self):
        repo_owner = 'CharlieYang0040'
        repo_name = 'ffmpegGUI'
        api_url = f'https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest'

        logger.debug(f"GitHub API 요청: {api_url}")
        response = requests.get(api_url)
        response.raise_for_status()
        data = response.json()

        latest_version = data['tag_name']
        assets = data.get('assets', [])
        if not assets:
            raise Exception('릴리스 자산을 찾을 수 없습니다.')

        download_url = next((asset['browser_download_url'] for asset in assets if asset['name'].endswith('.exe')), None)
        if not download_url:
            raise Exception('실행 파일 다운로드 URL을 찾을 수 없습니다.')

        logger.debug(f"최신 버전: {latest_version}, 다운로드 URL: {download_url}")
        return latest_version, download_url

    def is_newer_version(self, latest_version, current_version):
        from packaging import version
        is_newer = version.parse(latest_version) > version.parse(current_version)
        logger.debug(f"버전 비교: {latest_version} > {current_version} = {is_newer}")
        return is_newer

    def download_and_install_update(self, download_url):
        try:
            logger.info(f"업데이트 다운로드 시작: {download_url}")
            temp_dir = tempfile.mkdtemp()
            temp_file_path = os.path.join(temp_dir, 'update.exe')

            # 파일 다운로드
            response = requests.get(download_url, stream=True)
            total_size = int(response.headers.get('content-length', 0))
            
            progress_dialog = QProgressDialog("업데이트 다운로드 중...", "취소", 0, 100, None)
            progress_dialog.setWindowTitle("업데이트 다운로드")
            progress_dialog.setWindowModality(Qt.WindowModal)
            progress_dialog.setAutoClose(True)
            
            block_size = 1024  # 1KB
            downloaded_size = 0
            
            with open(temp_file_path, 'wb') as f:
                for data in response.iter_content(block_size):
                    if progress_dialog.wasCanceled():
                        logger.info("사용자가 다운로드를 취소했습니다.")
                        shutil.rmtree(temp_dir)
                        return
                        
                    downloaded_size += len(data)
                    f.write(data)
                    
                    if total_size:
                        progress = int((downloaded_size / total_size) * 100)
                        progress_dialog.setValue(progress)
                        progress_dialog.setLabelText(f"다운로드 중... {progress}% ({downloaded_size}/{total_size} bytes)")
            
            progress_dialog.close()
            logger.info(f"업데이트 파일 다운로드 완료: {temp_file_path}")

            # 현재 실행 파일의 디렉토리 가져오기
            if getattr(sys, 'frozen', False):
                current_dir = os.path.dirname(sys.executable)
            else:
                current_dir = os.path.dirname(os.path.abspath(__file__))

            # 대상 파일 경로 설정
            target_path = os.path.join(current_dir, 'update.exe')
            
            # 파일이 이미 존재하는 경우 _new 붙이기
            if os.path.exists(target_path):
                base_name = 'update'
                target_path = os.path.join(current_dir, f'{base_name}_new.exe')
                
            # 임시 파일을 대상 경로로 이동
            shutil.move(temp_file_path, target_path)
            logger.info(f"업데이트 파일 이동 완료: {target_path}")

            # 임시 디렉토리 정리
            shutil.rmtree(temp_dir)

        except Exception as e:
            logger.error(f"업데이트 다운로드 중 오류 발생: {e}")
            QMessageBox.critical(None, '업데이트 오류', f'업데이트 다운로드 중 오류가 발생했습니다:\n{e}')