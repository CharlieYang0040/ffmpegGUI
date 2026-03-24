import os
import sys
import json
import logging
from typing import Dict, Any, Optional
from PySide6.QtCore import QSettings

from utils import ffmpeg_manager

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
        # FFmpegManager를 통해 AppData 경로의 바이너리 보장 및 가져오기
        default_ffmpeg = ffmpeg_manager.ensure_ffmpeg_exists()
        
        # 만약 바이너리를 찾을 수 없다면 빈 문자열 처리
        if not default_ffmpeg:
            logger.warning("FFmpeg 바이너리를 찾지 못했습니다. 설정 기본값이 비어있게 됩니다.")
            default_ffmpeg = ""

        self._defaults = {
            "ffmpeg_path": default_ffmpeg,
            "font_path": self._detect_system_font(),
            "color_mgmt": {
                "enabled": False,
                "config_path": "",
                "lut_size": 33
            },
            "overlay": {
                "enabled": False,
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
        default_path = self._defaults.get("ffmpeg_path", "")
        
        # 예전에 캐시 목적으로 자동 저장되었던 AppData 경로들을 내장 경로로 강제 업데이트
        # (사용자가 수동으로 선택한 커스텀 경로가 아닌 AppData 캐시나 _MEI 임시 경로인 경우)
        if path and (("LHCinema" in path and "ffmpegGUI" in path) or "_MEI" in path):
            if default_path and os.path.exists(default_path) and os.path.normpath(default_path) != os.path.normpath(path):
                logger.info("과거 임시/캐시 FFmpeg 파일 경로를 내장된 바이너리 경로로 리셋합니다.")
                path = None

        if not path or not os.path.exists(path):
            # 경로가 유효하지 않거나 구버전 캐시인 경우 기본값으로 재설정
            path = default_path
            if os.path.exists(path) or path == "":
                self.set("ffmpeg_path", path)
        return path

    def get_ffprobe_path(self) -> str:
        ffmpeg_path = self.get_ffmpeg_path()
        if ffmpeg_path:
            return os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe.exe')
        return ""

config_manager = ConfigManager()
