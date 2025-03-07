import logging
from PySide6.QtCore import QThread, Signal

from app.utils.ffmpeg_utils import FFmpegUtils
from app.core.events import event_emitter, Events
from app.services.logging_service import LoggingService

# 로깅 서비스 설정
logger = LoggingService().get_logger(__name__)

class EncodingThread(QThread):
    """
    인코딩 작업을 별도의 스레드에서 실행하기 위한 클래스
    
    이벤트 기반 아키텍처를 사용하여 진행 상황을 업데이트합니다.
    """
    progress_updated = Signal(int)
    task_updated = Signal(str)
    encoding_finished = Signal()
    encoding_error = Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.ffmpeg_utils = FFmpegUtils()
        self.listeners_registered = False
        
        # 이벤트 리스너 등록
        self.register_event_listeners()
        
        # 스레드 종료 시 이벤트 리스너 제거
        self.finished.connect(self.unregister_event_listeners)
        
    def __del__(self):
        """소멸자: 객체가 삭제될 때 이벤트 리스너 제거"""
        self.unregister_event_listeners()
        
    def register_event_listeners(self):
        """이벤트 리스너 등록"""
        if not self.listeners_registered:
            # 기존 리스너 제거 (중복 방지)
            self.unregister_event_listeners()
            
            # 새 리스너 등록
            event_emitter.on(Events.PROCESS_PROGRESS, self.on_progress)
            event_emitter.on(Events.PROCESS_COMPLETED, self.on_complete)
            event_emitter.on(Events.PROCESS_ERROR, self.on_error)
            self.listeners_registered = True
            logger.debug("인코딩 스레드 이벤트 리스너 등록됨")
    
    def unregister_event_listeners(self):
        """이벤트 리스너 제거"""
        if self.listeners_registered:
            event_emitter.off(Events.PROCESS_PROGRESS, self.on_progress)
            event_emitter.off(Events.PROCESS_COMPLETED, self.on_complete)
            event_emitter.off(Events.PROCESS_ERROR, self.on_error)
            self.listeners_registered = False
            logger.debug("인코딩 스레드 이벤트 리스너 제거됨")
        
    def on_progress(self, progress):
        """진행 상황 업데이트 이벤트 핸들러"""
        self.progress_updated.emit(progress)
        
    def on_complete(self, output_file):
        """처리 완료 이벤트 핸들러"""
        self.progress_updated.emit(100)
        self.task_updated.emit(f"인코딩 완료: {output_file}")
        self.encoding_finished.emit()
        
    def on_error(self, error_message):
        """오류 이벤트 핸들러"""
        self.encoding_error.emit(error_message)

    def run(self):
        try:
            self.task_updated.emit("인코딩 준비 중...")
            
            # 진행 상황 업데이트를 위한 콜백 함수
            def progress_callback(progress):
                event_emitter.emit(Events.PROCESS_PROGRESS, progress)
                
            # 작업 상태 업데이트를 위한 콜백 함수
            def task_callback(task):
                self.task_updated.emit(task)
            
            # FFmpegUtils 인스턴스를 사용하여 미디어 처리
            media_files = self.kwargs.pop('media_files', self.args[0] if self.args else [])
            output_file = self.kwargs.pop('output_file', self.args[1] if len(self.args) > 1 else None)
            encoding_options = self.kwargs.pop('encoding_options', self.args[2] if len(self.args) > 2 else {})
            
            result = self.ffmpeg_utils.process_all_media(
                media_files=media_files,
                output_file=output_file,
                encoding_options=encoding_options,
                progress_callback=progress_callback,
                task_callback=task_callback,
                **self.kwargs
            )
            
            # 처리 완료 이벤트 발행
            event_emitter.emit(Events.PROCESS_COMPLETED, result)
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"인코딩 오류: {error_message}")
            event_emitter.emit(Events.PROCESS_ERROR, error_message)
            self.encoding_error.emit(error_message) 