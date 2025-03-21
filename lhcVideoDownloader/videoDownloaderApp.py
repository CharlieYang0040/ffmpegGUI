import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
                               QLineEdit, QPushButton, QFileDialog, QTextEdit, QProgressBar, QHBoxLayout)
from PySide6.QtCore import Signal, Slot, QThread
import yt_dlp
from youtube_auth import YouTubeAuthWindow
import tempfile
import json
import subprocess  # 파일 탐색기 실행용

class MyLogger:
    def __init__(self, log_signal):
        self.log_signal = log_signal
    def debug(self, msg):
        self.log_signal.emit(f"[DEBUG] {msg}")
    def warning(self, msg):
        self.log_signal.emit(f"[WARNING] {msg}")
    def error(self, msg):
        self.log_signal.emit(f"[ERROR] {msg}")

class ExtractWorker(QThread):
    progress_signal = Signal(str)
    result_signal = Signal(dict)

    def __init__(self, url):
        super().__init__()
        self.url = url
        self.cookies = None
        
    def set_cookies(self, cookies):
        self.cookies = cookies
        
    def run(self):
        try:
            self.progress_signal.emit(f"Attempting to connect to YouTube URL: {self.url}")
            ydl_opts = {
                'quiet': True,
                'no_warnings': True
            }
            
            if self.cookies:
                ydl_opts['cookiefile'] = self.cookies
                
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self.progress_signal.emit("Retrieving video information...")
                info = ydl.extract_info(self.url, download=False)
                if not info:
                    self.result_signal.emit({"title": "Unknown", "formats": [], "error": "Failed to retrieve video information"})
                    return

                title = info.get('title', f"video_{info.get('id', 'unknown')}")
                self.progress_signal.emit(f"Found title: {title}")

                seen_resolutions = set()
                formats = []
                
                for f in info['formats']:
                    if (f.get('height') and f.get('vcodec') != 'none'):
                        resolution = f'{f.get("height")}p'
                        if resolution not in seen_resolutions:
                            seen_resolutions.add(resolution)
                            formats.append({
                                'resolution': resolution,
                                'format_id': f['format_id'],
                                'ext': f.get('ext', ''),
                                'vcodec': f.get('vcodec', ''),
                                'acodec': f.get('acodec', '')
                            })
                            self.progress_signal.emit(f"Found format: {resolution} ({f.get('ext', 'unknown')})")

                if not formats:
                    self.result_signal.emit({"title": title, "formats": [], "error": "No compatible video formats found"})
                    return

                formats.sort(key=lambda x: int(x['resolution'].replace('p', '')), reverse=True)

                self.result_signal.emit({"title": title, "formats": formats, "error": None})
        except Exception as e:
            self.result_signal.emit({"title": "Unknown", "formats": [], "error": f"Error: {str(e)}"})


class DownloadWorker(QThread):
    progress_signal = Signal(int, int)  # 진행률 업데이트
    log_signal = Signal(str)
    finished_signal = Signal(bool)

    def __init__(self, url, format_data, output_file, ffmpeg_path, cookies=None):
        super().__init__()
        self.url = url
        self.format_data = format_data
        self.output_file = output_file
        self.ffmpeg_path = ffmpeg_path
        self.cookies = cookies
        self.ydl_opts = {}  # ydl_opts 초기화
        
    def progress_hook(self, d):
        if d['status'] == 'downloading':
            downloaded = d.get('downloaded_bytes', 0)
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            
            if total > 0:  # total이 유효한 값일 때만 진행률 계산
                progress = int((downloaded / total) * 100)
                self.progress_signal.emit(progress, 100)
                
                speed = d.get('speed', 0)
                eta = d.get('eta', 0)
                
                if speed and speed > 1024*1024:  # speed가 None이 아닐 때만 계산
                    speed_str = f"{speed/(1024*1024):.2f} MB/s"
                elif speed and speed > 1024:
                    speed_str = f"{speed/1024:.2f} KB/s"
                else:
                    speed_str = f"{speed:.2f} B/s" if speed else "Unknown speed"
                    
                eta_str = f"{eta}s" if eta else "Unknown"
                self.log_signal.emit(f"다운로드 진행률: {progress}% | 속도: {speed_str} | 남은 시간: {eta_str}")
        
        elif d['status'] == 'started':
            self.log_signal.emit("FFmpeg로 인코딩 중입니다. 잠시 기다려주세요...")
            self.progress_signal.emit(0, 0)
        
        elif d['status'] == 'processing':
            # FFmpeg 처리 상태 표시
            progress = d.get('percent', 0)
            if progress:
                self.progress_signal.emit(int(progress), 100)
                self.log_signal.emit(f"FFmpeg 인코딩 진행률: {int(progress)}%")
        
        elif d['status'] == 'finished':
            self.log_signal.emit("인코딩이 완료되었습니다!")
            self.progress_signal.emit(100, 100)
        
    def run(self):
        try:
            if not os.path.exists(self.ffmpeg_path):
                self.log_signal.emit(f"Warning: FFmpeg not found at {self.ffmpeg_path}")
                self.finished_signal.emit(False)
                return

            self.log_signal.emit(f"Using FFmpeg from: {self.ffmpeg_path}")
            self.log_signal.emit(f"Output file: {self.output_file}")
            self.log_signal.emit("Starting download, conversion, and thumbnail embedding...")

            logger = MyLogger(self.log_signal)
            ydl_opts = {
                'logger': logger,
                'verbose': True,
                'quiet': False,
                'no_warnings': False,
                'format': self.format_data['format_id'],
                'outtmpl': self.output_file,
                'progress_hooks': [self.progress_hook],
                'merge_output_format': 'mp4',
                'ffmpeg_location': self.ffmpeg_path,
                'force_overwrites': True,
                'writethumbnail': True,
                'concurrent_fragment_downloads': 8,
                'postprocessor_args': {
                    'ffmpeg': [
                        '-loglevel', 'info',
                        '-progress', 'pipe:1'
                    ],
                    'default': [
                        '-c:v', 'libx264',
                        '-preset', 'medium',
                        '-crf', '23',
                        '-c:a', 'aac',
                        '-b:a', '192k',
                        '-movflags', '+faststart'
                    ]
                },
                'postprocessors': [
                    {
                        'key': 'FFmpegVideoConvertor',
                        'preferedformat': 'mp4'
                    },
                    {
                        'key': 'FFmpegMetadata',
                        'add_metadata': True
                    }
                ]
            }

            if self.cookies:
                ydl_opts['cookiefile'] = self.cookies
                
            # 저장된 옵션 병합
            if self.ydl_opts:
                for key, value in self.ydl_opts.items():
                    if key != 'postprocessor_args':
                        ydl_opts[key] = value
                    else:
                        # postprocessor_args는 딕셔너리 병합이 필요함
                        for pp_key, pp_value in value.items():
                            if pp_key not in ydl_opts['postprocessor_args']:
                                ydl_opts['postprocessor_args'][pp_key] = pp_value

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])

            self.log_signal.emit("Download, conversion, metadata insertion, and thumbnail embedding completed successfully!")
            self.finished_signal.emit(True)
        except Exception as e:
            self.log_signal.emit(f"Download failed: {str(e)}")
            self.finished_signal.emit(False)


class ConfigManager:
    def __init__(self):
        # Windows의 경우 %APPDATA%/Local/LHCVideoDownloader 경로 사용
        if os.name == 'nt':
            self.config_file = os.path.join(os.getenv('LOCALAPPDATA'), 'LHCVideoDownloader', 'settings.json')
        else:
            self.config_file = os.path.expanduser('~/.config/lhcVideoDownloader.json')
        
        # 설정 파일 디렉토리 생성
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

    def load_cookies(self):
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                return f.read()
        return None

    def save_cookies(self, cookies):
        with open(self.config_file, 'w') as f:
            f.write(cookies)


class VideoDownloaderApp(QMainWindow):
    update_progress = Signal(int, int)
    log_message = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Video Downloader")
        self.setGeometry(200, 200, 600, 400)
        
        # ConfigManager 초기화
        self.config_manager = ConfigManager()
        
        # UI 초기화
        self.main_widget = QWidget()
        self.layout = QVBoxLayout()

        self.url_label = QLabel("YouTube Video URL:")
        self.url_input = QLineEdit()

        self.url_layout = QHBoxLayout()
        self.url_layout.addWidget(self.url_input)
        
        self.paste_btn = QPushButton("붙여넣기")
        self.paste_btn.clicked.connect(self.paste_from_clipboard)
        self.url_layout.addWidget(self.paste_btn)

        self.download_btn = QPushButton("Extract and Download")
        self.download_btn.clicked.connect(self.start_extraction)

        self.save_label = QLabel("Save Directory:")
        self.save_path_btn = QPushButton("Choose Folder")
        self.save_path_btn.clicked.connect(self.choose_save_path)
        self.save_path_display = QLabel("Not selected")

        self.progress_bar = QProgressBar()
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)

        self.layout.addWidget(self.url_label)
        self.layout.addLayout(self.url_layout)
        self.layout.addWidget(self.save_label)
        self.layout.addWidget(self.save_path_btn)
        self.layout.addWidget(self.save_path_display)
        self.layout.addWidget(self.download_btn)
        self.layout.addWidget(QLabel("Download Progress:"))
        self.layout.addWidget(self.progress_bar)
        self.layout.addWidget(QLabel("Logs:"))
        self.layout.addWidget(self.log_output)
        
        self.main_widget.setLayout(self.layout)
        self.setCentralWidget(self.main_widget)

        self.save_path = os.getcwd()
        self.save_path_display.setText(self.save_path)
        self.video_info = None
        self.extract_thread = None
        self.download_thread = None

        self.update_progress.connect(self.update_progress_bar)
        self.log_message.connect(self.append_log)

        # 설정 버튼 레이아웃
        self.settings_layout = QHBoxLayout()
        
        # 로그인 버튼
        self.login_btn = QPushButton("YouTube 로그인")
        self.login_btn.clicked.connect(self.show_login_window)
        self.settings_layout.addWidget(self.login_btn)
        
        # Config 폴더 열기 버튼
        self.open_config_btn = QPushButton("설정 폴더 열기")
        self.open_config_btn.clicked.connect(self.open_config_folder)
        self.settings_layout.addWidget(self.open_config_btn)
        
        # 설정 레이아웃을 메인 레이아웃에 추가
        self.layout.insertLayout(1, self.settings_layout)  # URL 입력란 아래에 추가
        
        self.youtube_cookies = None  # 쿠키 저장용 변수
        
        # 저장된 쿠키 확인 및 로드
        self.load_saved_cookies()
    
    def load_saved_cookies(self):
        """저장된 쿠키 로드"""
        saved_cookies = self.config_manager.load_cookies()
        if saved_cookies:
            # 임시 파일에 쿠키 저장
            temp_cookie_file = tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.txt',
                delete=False
            )
            temp_cookie_file.write(saved_cookies)
            temp_cookie_file.close()
            
            self.youtube_cookies = temp_cookie_file.name
            self.append_log("저장된 로그인 정보를 불러왔습니다.")
            
            # 로그인 버튼 텍스트 변경
            self.login_btn.setText("다시 로그인")
    
    def choose_save_path(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Save Directory")
        if folder:
            self.save_path = folder
            self.save_path_display.setText(folder)

    @Slot()
    def start_extraction(self):
        video_url = self.url_input.text()
        if not video_url:
            self.append_log("Please enter a valid YouTube video URL.")
            return
        if not self.save_path:
            self.append_log("Please select a save directory.")
            return

        self.append_log("Extracting video information...")
        if self.extract_thread and self.extract_thread.isRunning():
            self.append_log("Extraction is already running.")
            return

        self.extract_thread = ExtractWorker(video_url)
        if self.youtube_cookies:  # 쿠키가 있다면 전달
            self.extract_thread.set_cookies(self.youtube_cookies)
        self.extract_thread.progress_signal.connect(self.append_log)
        self.extract_thread.result_signal.connect(self.handle_extract_result)
        self.extract_thread.start()

    @Slot(dict)
    def handle_extract_result(self, result):
        self.video_info = result
        if self.video_info["error"]:
            self.append_log(f"Error during extraction: {self.video_info['error']}")
            return

        self.append_log(f"Title: {self.video_info['title']}")
        if not self.video_info["formats"]:
            self.append_log("No available formats found.")
            return

        self.append_log("Available Resolutions:")
        for fmt in self.video_info["formats"]:
            self.append_log(f"- {fmt['resolution']}")

        self.append_log("Starting download for the first available format...")
        selected_format = self.video_info['formats'][0]

        safe_title = "".join([
            c if c.isalnum() or c in (' ', '-', '_', '.', '[', ']') else '_' 
            for c in self.video_info['title']
        ])

        output_file = os.path.join(self.save_path, f"{safe_title}.mp4")

        counter = 1
        base_name = os.path.splitext(output_file)[0]
        while os.path.exists(output_file):
            output_file = f"{base_name}_{counter}.mp4"
            counter += 1

        # 사용자 이름을 이용한 동적 ffmpeg 경로 설정
        user_name = os.getenv('USERNAME') or os.getenv('USER')
        ffmpeg_path = rf'C:\Users\{user_name}\AppData\Local\LHCinema\ffmpegGUI\ffmpeg\ffmpeg.exe'

        self.download_thread = DownloadWorker(
            self.url_input.text(), 
            selected_format, 
            output_file, 
            ffmpeg_path,
            self.youtube_cookies  # 쿠키 전달
        )
        
        # progress_hook은 이미 DownloadWorker 클래스 내에 있으므로 직접 설정할 필요 없음
        self.download_thread.progress_signal.connect(self.update_progress_bar)
        self.download_thread.log_signal.connect(self.append_log)
        self.download_thread.finished_signal.connect(self.download_finished)
        self.download_thread.start()

    @Slot(bool)
    def download_finished(self, success):
        if success:
            self.append_log("Download process finished successfully.")
        else:
            self.append_log("Download process ended with an error or was incomplete.")

    @Slot(int, int)
    def update_progress_bar(self, value, max_value):
        self.progress_bar.setMaximum(max_value)
        self.progress_bar.setValue(value)

    @Slot(str)
    def append_log(self, message):
        self.log_output.append(message)

    def paste_from_clipboard(self):
        """클립보드의 내용을 URL 입력창에 붙여넣습니다."""
        clipboard = QApplication.clipboard()
        self.url_input.setText(clipboard.text())

    def show_login_window(self):
        """YouTube 로그인 창을 표시"""
        if hasattr(self, 'auth_window'):
            self.auth_window.close()
        self.auth_window = YouTubeAuthWindow()
        self.auth_window.login_completed.connect(self.handle_login_completed)
    
    def handle_login_completed(self, cookie_file):
        """로그인이 완료되면 쿠키 파일 경로 저장"""
        self.youtube_cookies = cookie_file
        self.append_log("YouTube 로그인이 완료되었습니다.")
        self.login_btn.setText("다시 로그인")

    def open_config_folder(self):
        """설정 폴더를 파일 탐색기로 엽니다"""
        config_path = os.path.dirname(self.config_manager.config_file)
        try:
            # 설정 폴더가 없으면 생성
            os.makedirs(config_path, exist_ok=True)
            
            if os.name == 'nt':  # Windows
                os.startfile(config_path)
            elif os.name == 'posix':  # macOS, Linux
                subprocess.run(['xdg-open', config_path])
            self.append_log(f"설정 폴더를 열었습니다: {config_path}")
        except Exception as e:
            self.append_log(f"설정 폴더를 여는 중 오류가 발생했습니다: {e}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = VideoDownloaderApp()
    window.show()
    sys.exit(app.exec())
