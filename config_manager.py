import os
import sys
import json
import logging
from typing import Dict, Any, Optional
from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)

class ConfigManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ConfigManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.settings = QSettings('LHCinema', 'ffmpegGUI')
        self._config_cache = {}
        self._load_defaults()
        self._initialized = True

    def _load_defaults(self):
        """기본 설정 로드"""
        # 기본 FFmpeg 경로 설정
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
            default_ffmpeg = os.path.join(base_path, "libs", "ffmpeg-7.1-full_build", "bin", "ffmpeg.exe")
        else:
            # 개발 환경 기본값 (사용자 환경에 맞게 수정 필요할 수 있음)
            default_ffmpeg = r"\\192.168.2.215\Share_151\art\ffmpeg-7.1\bin\ffmpeg.exe"

        self._defaults = {
            "ffmpeg_path": default_ffmpeg,
            "font_path": self._detect_system_font(),
            "color_mgmt": {
                "enabled": False,
                "config_path": "",
                "lut_size": 33
            },
            "overlay": {
                "enabled": True,
                "font_size": 48
            }
        }

    def _detect_system_font(self) -> Optional[str]:
        """시스템 폰트 자동 감지"""
        candidates = []
        if sys.platform.startswith("win"):
            windir = os.environ.get("WINDIR", r"C:\Windows")
            candidates.extend([
                os.path.join(windir, "Fonts", "malgun.ttf"),
                os.path.join(windir, "Fonts", "arial.ttf"),
            ])
        elif sys.platform == "darwin":
            candidates.extend([
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
            ])
        else:
            candidates.extend([
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ])

        for path in candidates:
            if path and os.path.exists(path):
                return path.replace("\\", "/")
        return None

    def get(self, key: str, default: Any = None) -> Any:
        """설정값 가져오기 (메모리 캐시 -> QSettings -> 기본값 순)"""
        if key in self._config_cache:
            return self._config_cache[key]

        # QSettings에서 값 가져오기
        val = self.settings.value(key)
        
        # 값이 없으면 기본값 확인
        if val is None:
            val = self._defaults.get(key, default)
            
        # 타입 변환 (필요한 경우)
        if isinstance(default, bool) and not isinstance(val, bool):
            val = str(val).lower() == 'true'
        elif isinstance(default, int) and not isinstance(val, int):
            try:
                val = int(val)
            except (ValueError, TypeError):
                val = default

        self._config_cache[key] = val
        return val

    def set(self, key: str, value: Any):
        """설정값 저장"""
        self._config_cache[key] = value
        self.settings.setValue(key, value)
        self.settings.sync()

    def get_ffmpeg_path(self) -> str:
        path = self.get("ffmpeg_path")
        if not path or not os.path.exists(path):
            # 경로가 유효하지 않으면 기본값으로 재설정 시도
            path = self._defaults["ffmpeg_path"]
            if os.path.exists(path):
                self.set("ffmpeg_path", path)
        return path

    def get_ffprobe_path(self) -> str:
        ffmpeg_path = self.get_ffmpeg_path()
        if ffmpeg_path:
            return os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe.exe')
        return ""

config_manager = ConfigManager()
