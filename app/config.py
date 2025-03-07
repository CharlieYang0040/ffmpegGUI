# config.py
"""
FFmpegGUI 애플리케이션 전역 설정
"""
import os
import sys

# 애플리케이션 정보
APP_NAME = "ffmpegGUI"
APP_VERSION = "2.0.0"
APP_COMPANY = "LHCinema"

# 경로 설정
if getattr(sys, 'frozen', False):
    # 실행 파일로 패키징된 경우
    BASE_DIR = os.path.dirname(sys.executable)
    RESOURCES_DIR = os.path.join(sys._MEIPASS, "resources")
else:
    # 개발 환경인 경우
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    RESOURCES_DIR = os.path.join(BASE_DIR, "resources")

# 리소스 경로
ICONS_DIR = os.path.join(RESOURCES_DIR, "icons")
STYLES_DIR = os.path.join(RESOURCES_DIR, "styles")

# 성능 설정
PERFORMANCE_SETTINGS = {
    'max_threads': os.cpu_count(),
    'memory_limit_percentage': 80,  # 최대 메모리 사용률
    'chunk_size': 1024 * 1024,  # 파일 처리 청크 크기
    'buffer_size': 4096,  # FFmpeg 버퍼 크기
    'enable_gpu': True,  # GPU 가속 사용 여부
    'process_priority': 'above_normal'  # 프로세스 우선순위
}

# 기본 인코딩 옵션
DEFAULT_ENCODING_OPTIONS = {
    "c:v": "libx264",
    "pix_fmt": "yuv420p",
    "colorspace": "bt709",
    "color_primaries": "bt709",
    "color_trc": "bt709",
    "color_range": "limited"
}

# 지원하는 파일 형식
SUPPORTED_VIDEO_FORMATS = ['.mp4', '.avi', '.mov', '.mkv']
SUPPORTED_IMAGE_FORMATS = ['.jpg', '.jpeg', '.png', '.bmp', '.webp']
SUPPORTED_FORMATS = SUPPORTED_VIDEO_FORMATS + SUPPORTED_IMAGE_FORMATS