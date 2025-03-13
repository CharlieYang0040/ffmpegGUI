from typing import Callable, Dict, List, Any
import logging
from app.services.logging_service import LoggingService

class EventEmitter:
    """
    이벤트 기반 아키텍처를 위한 이벤트 발행-구독 시스템
    
    이 클래스는 애플리케이션 전체에서 이벤트를 발행하고 구독할 수 있는 메커니즘을 제공합니다.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EventEmitter, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """싱글톤 인스턴스 초기화"""
        self.listeners: Dict[str, List[Callable]] = {}
        self.logger = LoggingService().get_logger(__name__)
        self.logger.debug("EventEmitter 초기화됨")
    
    def on(self, event: str, callback: Callable) -> None:
        """
        이벤트에 콜백 함수를 등록합니다.
        
        Args:
            event: 이벤트 이름
            callback: 이벤트 발생 시 호출될 콜백 함수
        """
        if event not in self.listeners:
            self.listeners[event] = []
        self.listeners[event].append(callback)
        self.logger.debug(f"이벤트 '{event}'에 리스너 등록됨")
    
    def off(self, event: str, callback: Callable) -> None:
        """
        이벤트에서 콜백 함수를 제거합니다.
        
        Args:
            event: 이벤트 이름
            callback: 제거할 콜백 함수
        """
        if event in self.listeners and callback in self.listeners[event]:
            self.listeners[event].remove(callback)
            self.logger.debug(f"이벤트 '{event}'에서 리스너 제거됨")
    
    def emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        """
        이벤트를 발행하고 등록된 모든 콜백 함수를 호출합니다.
        
        Args:
            event: 발행할 이벤트 이름
            *args: 콜백 함수에 전달할 위치 인자
            **kwargs: 콜백 함수에 전달할 키워드 인자
        """
        if event in self.listeners:
            self.logger.debug(f"이벤트 '{event}' 발행됨")
            for callback in self.listeners[event]:
                try:
                    callback(*args, **kwargs)
                except Exception as e:
                    self.logger.error(f"이벤트 '{event}' 처리 중 오류 발생: {str(e)}")
        else:
            self.logger.debug(f"이벤트 '{event}'에 등록된 리스너 없음")
    
    def once(self, event: str, callback: Callable) -> None:
        """
        이벤트에 한 번만 실행되는 콜백 함수를 등록합니다.
        
        Args:
            event: 이벤트 이름
            callback: 이벤트 발생 시 한 번만 호출될 콜백 함수
        """
        def one_time_callback(*args: Any, **kwargs: Any) -> None:
            self.off(event, one_time_callback)
            callback(*args, **kwargs)
        
        self.on(event, one_time_callback)
        self.logger.debug(f"이벤트 '{event}'에 일회성 리스너 등록됨")
    
    def clear(self, event: str = None) -> None:
        """
        모든 이벤트 리스너를 제거하거나 특정 이벤트의 모든 리스너를 제거합니다.
        
        Args:
            event: 제거할 이벤트 이름 (None인 경우 모든 이벤트 제거)
        """
        if event:
            if event in self.listeners:
                self.listeners[event] = []
                self.logger.debug(f"이벤트 '{event}'의 모든 리스너 제거됨")
        else:
            self.listeners = {}
            self.logger.debug("모든 이벤트 리스너 제거됨")

# 전역 이벤트 이미터 인스턴스
event_emitter = EventEmitter()

# 이벤트 상수 정의
class Events:
    """이벤트 이름 상수"""
    # 프로세스 관련 이벤트
    PROCESS_STARTED = "process:started"
    PROCESS_PROGRESS = "process:progress"
    PROCESS_COMPLETED = "process:completed"
    PROCESS_ERROR = "process:error"
    
    # 파일 관련 이벤트
    FILE_LOADED = "file:loaded"
    FILE_SAVED = "file:saved"
    FILE_ERROR = "file:error"
    
    # FFmpeg 관련 이벤트
    FFMPEG_INITIALIZED = "ffmpeg:initialized"
    FFMPEG_ERROR = "ffmpeg:error"
    
    # UI 관련 이벤트
    UI_STATE_CHANGED = "ui:state_changed"
    UI_THEME_CHANGED = "ui:theme_changed"
    
    # 설정 관련 이벤트
    SETTINGS_CHANGED = "settings:changed"
    SETTINGS_RESET = "settings:reset"
    
    # 업데이트 관련 이벤트
    UPDATE_ERROR = "update:error"
    UPDATE_AVAILABLE = "update:available"
    UPDATE_NOT_AVAILABLE = "update:not_available"
    UPDATE_DOWNLOAD_STARTED = "update:download_started"
    UPDATE_DOWNLOAD_PROGRESS = "update:download_progress"
    UPDATE_DOWNLOAD_COMPLETED = "update:download_completed"
    UPDATE_DOWNLOAD_ERROR = "update:download_error"
    UPDATE_INSTALL_STARTED = "update:install_started"
    UPDATE_INSTALL_COMPLETED = "update:install_completed"
    UPDATE_INSTALL_ERROR = "update:install_error"
    
    # 타임라인 관련 이벤트
    TIMELINE_SET_IN_POINT = "timeline:set_in_point"
    TIMELINE_SET_OUT_POINT = "timeline:set_out_point"
    TIMELINE_PLAY_TOGGLE = "timeline:play_toggle"
    TIMELINE_SEEK_PREV_FRAME = "timeline:seek_prev_frame"
    TIMELINE_SEEK_NEXT_FRAME = "timeline:seek_next_frame"
    TIMELINE_SEEK_START = "timeline:seek_start"
    TIMELINE_SEEK_END = "timeline:seek_end" 