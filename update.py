# update.py

import requests
import shutil
import tempfile
import threading
import os
import sys
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtCore import QCoreApplication, QObject, pyqtSignal

class UpdateChecker(QObject):
    update_error = pyqtSignal(str)
    update_available = pyqtSignal(str, str)
    no_update = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.updating = False
        self.update_button = None

    def check_for_updates(self):
        if self.updating:
            return

        self.updating = True
        if self.update_button:
            self.update_button.setEnabled(False)
        self.perform_update_check()

    def perform_update_check(self):
        try:
            latest_version, download_url = self.get_latest_version_info()
            from main import __version__

            if self.is_newer_version(latest_version, __version__):
                self.update_available.emit(latest_version, download_url)
            else:
                self.no_update.emit()
        except Exception as e:
            self.update_error.emit(str(e))
        finally:
            self.updating = False
            if self.update_button:
                self.update_button.setEnabled(True)

    def get_latest_version_info(self):
        repo_owner = 'CharlieYang0040'
        repo_name = 'ffmpegGUI'
        api_url = f'https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest'

        response = requests.get(api_url)
        response.raise_for_status()  # HTTP 오류 발생 시 예외 발생
        data = response.json()

        latest_version = data['tag_name']
        assets = data.get('assets', [])
        if not assets:
            raise Exception('릴리스 자산을 찾을 수 없습니다.')

        download_url = next((asset['browser_download_url'] for asset in assets if asset['name'].endswith('.exe')), None)
        if not download_url:
            raise Exception('실행 파일 다운로드 URL을 찾을 수 없습니다.')

        return latest_version, download_url

    def is_newer_version(self, latest_version, current_version):
        from packaging import version
        return version.parse(latest_version) > version.parse(current_version)

    def download_and_install_update(self, download_url):
        try:
            # 임시 디렉토리에 파일 다운로드
            temp_dir = tempfile.mkdtemp()
            temp_file_path = os.path.join(temp_dir, 'update.exe')

            response = requests.get(download_url, stream=True)
            with open(temp_file_path, 'wb') as f:
                shutil.copyfileobj(response.raw, f)

            # 업데이트 스크립트 실행
            threading.Thread(target=self.run_updater, args=(temp_file_path,)).start()
        except Exception as e:
            QMessageBox.critical(self, '업데이트 오류', f'업데이트 다운로드 중 오류가 발생했습니다:\n{e}')

    def run_updater(self, new_executable_path):
        # 현재 실행 파일 경로
        current_executable = sys.executable

        # 업데이트 스크립트 생성
        updater_script = f"""
import os
import sys
import time
import shutil

time.sleep(1)  # 기존 프로그램��� 종료될 때까지 대기

try:
    shutil.move(r"{new_executable_path}", r"{current_executable}")
    os.startfile(r"{current_executable}")
except Exception as e:
    print("업데이트 중 오류 발생:", e)
"""

        # 임시 스크립트 파일 생성
        temp_dir = tempfile.mkdtemp()
        updater_script_path = os.path.join(temp_dir, 'updater.pyw')
        with open(updater_script_path, 'w', encoding='utf-8') as f:
            f.write(updater_script)

        # 업데이트 스크립트 실행
        os.startfile(updater_script_path)

        # 애플리케이션 종료
        QCoreApplication.exit()
