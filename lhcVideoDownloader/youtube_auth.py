from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QLabel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebEngineCore import QWebEngineCookieStore, QWebEngineProfile
from PySide6.QtCore import QUrl, Signal, Qt, QTimer
import os
import tempfile
from http.cookiejar import MozillaCookieJar
import time
from config_manager import ConfigManager

class YouTubeAuthWindow(QWidget):
    login_completed = Signal(str)

    def __init__(self):
        super().__init__()
        self.config_manager = ConfigManager()
        
        # 저장된 쿠키가 있는지 확인
        saved_cookies = self.config_manager.load_cookies()
        if saved_cookies:
            try:
                # 임시 파일에 저장된 쿠키 복사
                temp_cookie_file = tempfile.NamedTemporaryFile(
                    mode='w',
                    suffix='.txt',
                    delete=False
                )
                temp_cookie_file.write(saved_cookies)
                temp_cookie_file.close()
                
                # 로그인 완료 시그널 발생
                self.login_completed.emit(temp_cookie_file.name)
                return
            except Exception as e:
                print(f"저장된 쿠키 로드 중 오류 발생: {e}")
                # 오류 발생 시 새로 로그인 진행
        
        # UI 초기화
        self.setWindowTitle("YouTube 로그인")
        self.setGeometry(100, 100, 800, 600)
        
        layout = QVBoxLayout()
        
        self.label = QLabel("Google 계정으로 로그인해주세요")
        self.label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.label)

        self.webview = QWebEngineView()
        self.webview.setUrl(QUrl("https://accounts.google.com/signin/v2/identifier?service=youtube"))
        
        self.cookie_store = self.webview.page().profile().cookieStore()
        self.cookie_store.cookieAdded.connect(self.on_cookie_added)
        
        layout.addWidget(self.webview)
        self.setLayout(layout)

        self.cookies = []
        self.login_check_count = 0
        self.webview.loadFinished.connect(self.on_load_finished)
        self.redirect_attempted = False
        self.has_login_cookie = False
        
        # 윈도우 표시
        self.show()

    def on_cookie_added(self, cookie):
        """쿠키가 추가될 때마다 호출되는 메서드"""
        if any(domain in cookie.domain() for domain in ['.youtube.com', '.google.com']):
            name = cookie.name().data().decode()
            value = cookie.value().data().decode()
            domain = cookie.domain()
            
            # Netscape 형식에 저장된 쿠키 데이터 저장
            cookie_data = {
                'domain': domain,
                'flag': 'TRUE',
                'path': cookie.path(),
                'secure': 'TRUE' if cookie.isSecure() else 'FALSE',
                'expiration': int(cookie.expirationDate().toSecsSinceEpoch() if not cookie.isSessionCookie() else time.time() + 3600*24*365),
                'name': name,
                'value': value
            }
            
            # 중복 쿠키 제거
            self.cookies = [c for c in self.cookies if c['name'] != name or c['domain'] != domain]
            self.cookies.append(cookie_data)
            
            # 로그인 상태를 나타내는 주요 쿠키 확인
            if name in ['SAPISID', 'SID', '__Secure-1PSID']:
                self.has_login_cookie = True

    def save_cookies_to_file(self):
        """쿠키를 Netscape 형식으로 파일에 저장"""
        cookie_content = "# Netscape HTTP Cookie File\n"
        cookie_content += "# https://curl.haxx.se/rfc/cookie_spec.html\n"
        cookie_content += "# This is a generated file!  Do not edit.\n\n"
        
        for cookie in self.cookies:
            domain = cookie['domain']
            if not domain.startswith('.'):
                domain = '.' + domain.lstrip('.')
                
            cookie_content += f"{domain}\t"
            cookie_content += "TRUE\t"
            cookie_content += f"{cookie['path']}\t"
            cookie_content += f"{cookie['secure']}\t"
            cookie_content += f"{cookie['expiration']}\t"
            cookie_content += f"{cookie['name']}\t"
            cookie_content += f"{cookie['value']}\n"

        # 쿠키를 ConfigManager를 통해 저장
        self.config_manager.save_cookies(cookie_content)
        
        # 임시 파일 생성 및 반환
        temp_cookie_file = tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.txt',
            delete=False
        )
        temp_cookie_file.write(cookie_content)
        temp_cookie_file.close()
        return temp_cookie_file.name

    def on_load_finished(self, success):
        if not success:
            return

        current_url = self.webview.url().toString()
        
        if "myaccount.google.com" in current_url and self.has_login_cookie:
            if not self.redirect_attempted:
                self.redirect_attempted = True
                self.label.setText("로그인 확인 중... YouTube로 이동합니다.")
                QTimer.singleShot(2000, self.redirect_to_youtube)
                
        elif "youtube.com" in current_url and self.has_login_cookie:
            self.label.setText("로그인이 완료되었습니다. 잠시만 기다려주세요...")
            QTimer.singleShot(2000, self.complete_login)

    def redirect_to_youtube(self):
        self.webview.setUrl(QUrl("https://www.youtube.com"))

    def complete_login(self):
        if self.has_login_cookie and self.cookies:
            cookie_file = self.save_cookies_to_file()
            self.login_completed.emit(cookie_file)
            self.close()