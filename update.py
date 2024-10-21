# update.py

import requests
import shutil
import tempfile
import threading
import os
import sys
from PySide6.QtWidgets import QMessageBox
from PySide6.QtCore import QCoreApplication, QObject, Signal

class UpdateChecker(QObject):
    update_error = Signal(str)
    update_available = Signal(str, str)
    no_update = Signal()

    def __init__(self):
        super().__init__()
        self.updating = False
        self.update_button = None
        print("UpdateChecker 초기화됨")

    def check_for_updates(self):
        if self.updating:
            print("이미 업데이트 확인 중")
            return

        print("업데이트 확인 시작")
        self.updating = True
        if self.update_button:
            self.update_button.setEnabled(False)
        self.perform_update_check()

    def perform_update_check(self):
        try:
            print("최신 버전 정보 가져오기 시작")
            latest_version, download_url = self.get_latest_version_info()
            from main import __version__
            print(f"현재 버전: {__version__}, 최신 버전: {latest_version}")

            if self.is_newer_version(latest_version, __version__):
                print("새로운 버전 발견")
                self.update_available.emit(latest_version, download_url)
            else:
                print("최신 버전 사용 중")
                self.no_update.emit()
        except Exception as e:
            print(f"업데이트 확인 중 오류 발생: {str(e)}")
            self.update_error.emit(str(e))
        finally:
            self.updating = False
            if self.update_button:
                self.update_button.setEnabled(True)
            print("업데이트 확인 완료")

    def get_latest_version_info(self):
        repo_owner = 'CharlieYang0040'
        repo_name = 'ffmpegGUI'
        api_url = f'https://api.github.com/repos/{repo_owner}/{repo_name}/releases/latest'

        print(f"GitHub API 요청: {api_url}")
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

        print(f"최신 버전: {latest_version}, 다운로드 URL: {download_url}")
        return latest_version, download_url

    def is_newer_version(self, latest_version, current_version):
        from packaging import version
        is_newer = version.parse(latest_version) > version.parse(current_version)
        print(f"버전 비교: {latest_version} > {current_version} = {is_newer}")
        return is_newer

    def download_and_install_update(self, download_url):
        try:
            print(f"업데이트 다운로드 시작: {download_url}")
            temp_dir = tempfile.mkdtemp()
            temp_file_path = os.path.join(temp_dir, 'update.exe')

            response = requests.get(download_url, stream=True)
            with open(temp_file_path, 'wb') as f:
                shutil.copyfileobj(response.raw, f)
            print(f"업데이트 파일 다운로드 완료: {temp_file_path}")

            print("업데이트 스크립트 실행 시작")
            threading.Thread(target=self.run_updater, args=(temp_file_path,)).start()
        except Exception as e:
            print(f"업데이트 다운로드 중 오류 발생: {e}")
            QMessageBox.critical(self, '업데이트 오류', f'업데이트 다운로드 중 오류가 발생했습니다:\n{e}')

    def run_updater(self, new_executable_path):
        print("업데이터 실행 시작")
        current_executable = sys.executable
        print(f"현재 실행 파일: {current_executable}")
        print(f"새 실행 파일: {new_executable_path}")

        updater_script = f"""
import os
import sys
import time
import shutil

print("업데이트 스크립트 시작")
time.sleep(1)  # 기존 프로그램이 종료될 때까지 대기

try:
    print(f"파일 이동: {new_executable_path} -> {current_executable}")
    shutil.move(r"{new_executable_path}", r"{current_executable}")
    print(f"새 프로그램 실행: {current_executable}")
    os.startfile(r"{current_executable}")
except Exception as e:
    print(f"업데이트 중 오류 발생: e")
"""

        temp_dir = tempfile.mkdtemp()
        updater_script_path = os.path.join(temp_dir, 'updater.pyw')
        print(f"업데이터 스크립트 생성: {updater_script_path}")
        with open(updater_script_path, 'w', encoding='utf-8') as f:
            f.write(updater_script)

        print("업데이터 스크립트 실행")
        os.startfile(updater_script_path)

        print("애플리케이션 종료")
        QCoreApplication.exit()
