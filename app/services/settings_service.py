# app/services/settings_service.py
import logging
import os

class SettingsService:
    """
    애플리케이션 설정을 관리하는 싱글톤 클래스
    
    이 클래스는 QSettings를 사용하여 애플리케이션 설정을 저장하고 로드합니다.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(SettingsService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """싱글톤 인스턴스 초기화"""
        from PySide6.QtCore import QSettings
        self.settings = QSettings('LHCinema', 'ffmpegGUI')
        self.logger = logging.getLogger(__name__)
        self.logger.debug("SettingsService 초기화됨")
    
    def get(self, key, default=None, type=None):
        """
        설정 값 가져오기
        
        Args:
            key (str): 설정 키
            default: 기본값
            type: 반환 타입
            
        Returns:
            설정 값
        """
        if type is None:
            return self.settings.value(key, default)
        return self.settings.value(key, default, type=type)
    
    def set(self, key, value):
        """
        설정 값 저장하기
        
        Args:
            key (str): 설정 키
            value: 설정 값
        """
        self.settings.setValue(key, value)
        self.logger.debug(f"설정 저장: {key}={value}")
    
    def get_ffmpeg_path(self):
        """FFmpeg 경로 가져오기"""
        return self.get("ffmpeg_path", "", type=str)
    
    def set_ffmpeg_path(self, path):
        """FFmpeg 경로 저장하기"""
        self.set("ffmpeg_path", path)
    
    def get_last_output_path(self):
        """마지막 출력 경로 가져오기"""
        return self.get("last_output_path", "")
    
    def set_last_output_path(self, path):
        """마지막 출력 경로 저장하기"""
        self.set("last_output_path", path)
    
    def get_debug_mode(self):
        """디버그 모드 상태 가져오기"""
        return self.get("debug_mode", False, type=bool)
    
    def set_debug_mode(self, enabled):
        """디버그 모드 상태 저장하기"""
        self.set("debug_mode", enabled)
    
    def get_rv_path(self):
        """RV 경로 가져오기"""
        return self.get("rv_path", "")
    
    def set_rv_path(self, path):
        """RV 경로 저장하기"""
        self.set("rv_path", path)
    
    def get_all_settings(self):
        """모든 설정 값 가져오기"""
        all_keys = self.settings.allKeys()
        result = {}
        for key in all_keys:
            result[key] = self.settings.value(key)
        return result
    
    def get_all_keys(self):
        """
        모든 설정 키 목록 반환
        
        Returns:
            list: 모든 설정 키 목록
        """
        return self.settings.allKeys()
    
    def clear_settings(self):
        """모든 설정 초기화"""
        self.settings.clear()
        self.logger.info("모든 설정이 초기화되었습니다.")