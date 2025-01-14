import os
import json
from pathlib import Path
from cryptography.fernet import Fernet
import base64

class ConfigManager:
    def __init__(self):
        # 애플리케이션 기본 디렉토리 설정
        self.app_name = "LHCVideoDownloader"
        self.app_dir = os.path.join(os.getenv('LOCALAPPDATA'), self.app_name)
        self.config_dir = os.path.join(self.app_dir, "config")
        self.cookies_dir = os.path.join(self.app_dir, "cookies")
        self.encryption_key_file = os.path.join(self.config_dir, "encryption.key")
        
        # 디렉토리 생성
        self.setup_directories()
        
        # 암호화 키 초기화
        self.encryption_key = self.load_or_create_encryption_key()
        self.fernet = Fernet(self.encryption_key)

    def setup_directories(self):
        """필요한 디렉토리 구조 생성"""
        os.makedirs(self.config_dir, exist_ok=True)
        os.makedirs(self.cookies_dir, exist_ok=True)

    def load_or_create_encryption_key(self):
        """암호화 키 로드 또는 생성"""
        if os.path.exists(self.encryption_key_file):
            with open(self.encryption_key_file, 'rb') as f:
                return f.read()
        else:
            key = Fernet.generate_key()
            with open(self.encryption_key_file, 'wb') as f:
                f.write(key)
            return key

    def save_cookies(self, cookies_data, filename="youtube_cookies.txt"):
        """쿠키 데이터를 암호화하여 저장"""
        cookie_path = os.path.join(self.cookies_dir, filename)
        encrypted_data = self.fernet.encrypt(cookies_data.encode())
        with open(cookie_path, 'wb') as f:
            f.write(encrypted_data)

    def load_cookies(self, filename="youtube_cookies.txt"):
        """저장된 쿠키 데이터 로드 및 복호화"""
        cookie_path = os.path.join(self.cookies_dir, filename)
        if not os.path.exists(cookie_path):
            return None
        
        try:
            with open(cookie_path, 'rb') as f:
                encrypted_data = f.read()
            decrypted_data = self.fernet.decrypt(encrypted_data)
            return decrypted_data.decode()
        except Exception as e:
            print(f"쿠키 로드 중 오류 발생: {e}")
            return None

    def delete_cookies(self, filename="youtube_cookies.txt"):
        """저장된 쿠키 삭제"""
        cookie_path = os.path.join(self.cookies_dir, filename)
        if os.path.exists(cookie_path):
            os.remove(cookie_path)
