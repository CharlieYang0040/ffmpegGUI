import os
import logging
from PySide6.QtWidgets import QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

from app.core.video_thread import VideoThread
from app.utils.utils import is_video_file, is_image_file, get_first_sequence_file
from app.services.logging_service import LoggingService

# 로깅 서비스 설정
logger = LoggingService().get_logger(__name__)

class PreviewAreaComponent:
    """
    미리보기 영역 관련 기능을 제공하는 컴포넌트 클래스
    """
    
    def __init__(self, parent):
        """
        :param parent: 부모 위젯 (FFmpegGui 인스턴스)
        """
        self.parent = parent
        self.video_thread = None
        self.current_video_width = 0
        self.current_video_height = 0
        
    def create_preview_area(self, top_layout):
        """미리보기 영역 생성"""
        self.parent.preview_label = QLabel(alignment=Qt.AlignCenter)
        self.parent.preview_label.setFixedSize(470, 270)
        self.parent.preview_label.setStyleSheet("background-color: #1a1a1a; border: 1px solid #3a3a3a;")
        top_layout.addWidget(self.parent.preview_label, 1)
    
    def update_preview(self):
        """현재 선택된 파일의 미리보기 업데이트"""
        try:
            file_path = self.parent.list_widget.get_selected_file_path()
            if not file_path:
                self.stop_current_preview()
                self.parent.preview_label.clear()
                return
            
            # 현재 재생 중인 비디오가 있고, 같은 파일이면 미리보기 업데이트 하지 않음
            if (hasattr(self, 'video_thread') and self.video_thread and 
                hasattr(self.video_thread, 'file_path') and 
                self.video_thread.file_path == file_path):
                return
            
            # 다른 파일이면 현재 재생 중인 비디오 정리
            self.stop_current_preview()
            logger.info(f"미리보기 업데이트: {file_path}")

            if is_video_file(file_path):
                self.show_video_preview(file_path)
            elif is_image_file(file_path):
                self.show_image_preview(file_path)
            else:
                logger.warning(f"지원하지 않는 파일 형식입니다: {file_path}")
        except Exception as e:
            logger.error(f"미리보기 업데이트 중 오류: {str(e)}")
    
    def stop_current_preview(self):
        """현재 재생 중인 미리보기를 정리하는 메서드"""
        if not hasattr(self, 'video_thread') or not self.video_thread:
            return
        
        logger.debug("현재 미리보기 정리 시작")
        if self.video_thread.is_playing:
            self.stop_video_playback()
        
        self.video_thread = None
        # 재생 버튼 상태 초기화
        if hasattr(self.parent, 'play_button'):
            self.parent.play_button.setText('▶️ 재생')
    
    def show_video_preview(self, file_path: str):
        """비디오 파일 미리보기 표시"""
        self.create_video_thread(file_path)
        if hasattr(self.parent, 'play_button'):
            self.parent.play_button.setEnabled(True)

        self.video_thread.get_video_info()
        self.video_thread.wait()
        first_frame = self.video_thread.get_video_frame(0)
        if first_frame and not first_frame.isNull():
            self.update_video_frame(first_frame)
        else:
            self.parent.preview_label.clear()
    
    def show_image_preview(self, file_path: str):
        """이미지 파일 미리보기 표시"""
        if '%' in file_path:
            file_path = get_first_sequence_file(file_path)
            if not file_path:
                logger.warning(f"시퀀스 파일을 찾을 수 없습니다: {file_path}")
                return

        if os.path.exists(file_path):
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                scaled_pixmap = self.resize_keeping_aspect_ratio(pixmap, self.parent.preview_label.width(), self.parent.preview_label.height())
                self.parent.preview_label.setPixmap(scaled_pixmap)
            else:
                logger.warning(f"이미지를 로드할 수 없습니다: {file_path}")
        else:
            logger.warning(f"파일이 존재하지 않습니다: {file_path}")
    
    def set_video_info(self, width: int, height: int):
        """비디오 정보 설정"""
        self.current_video_width = width
        self.current_video_height = height
    
    def toggle_play(self):
        """비디오 재생/정지 토글"""
        selected_item = self.parent.list_widget.currentItem()
        if not selected_item:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.parent, "경고", "재생할 파일을 선택해주세요.")
            return

        if not self.video_thread or not self.video_thread.is_playing:
            self.start_video_playback()
        else:
            self.stop_video_playback()
    
    def create_video_thread(self, file_path=None):
        """비디오 스레드 생성"""
        if file_path is None:
            file_path = self.parent.list_widget.get_selected_file_path()
            
        if file_path:
            if self.video_thread:
                self.stop_video_playback()
            self.video_thread = VideoThread(file_path)
            self.video_thread.frame_ready.connect(self.update_video_frame)
            self.video_thread.finished.connect(self.on_video_finished)
            self.video_thread.video_info_ready.connect(self.set_video_info)
    
    def start_video_playback(self):
        """비디오 재생 시작"""
        if self.video_thread and self.video_thread.isRunning():
            self.video_thread.reset()
            self.video_thread.terminate()
            self.video_thread.wait()

        if not self.video_thread:
            self.create_video_thread()

        self.video_thread.is_playing = True
        current_speed = self.parent.speed_slider.value() / 100
        self.video_thread.set_speed(current_speed * 1.5)
        self.video_thread.start()
        self.parent.play_button.setText('⏹️ 정지')
    
    def stop_video_playback(self):
        """비디오 재생 중지"""
        if not hasattr(self, 'video_thread') or not self.video_thread:
            return
        
        if not self.video_thread.is_playing:
            return
        
        logger.debug("비디오 재생 중지 시작")
        self.video_thread.stop()
        self.video_thread.wait()
        self.update_ui_after_stop()
    
    def on_video_finished(self):
        """비디오 재생 완료 처리"""
        if not hasattr(self, 'video_thread') or not self.video_thread:
            return
        
        if self.video_thread.is_playing:
            self.stop_video_playback()
            self.update_ui_after_stop()
            self.video_thread.reset()
    
    def update_ui_after_stop(self):
        """비디오 정지 후 UI 업데이트"""
        self.video_thread.is_playing = False
        self.parent.play_button.setText('▶️ 재생')
    
    def change_speed(self):
        """재생 속도 변경"""
        self.parent.speed = self.parent.speed_slider.value() / 100
        self.parent.speed_value_label.setText(f"{self.parent.speed:.1f}x")
        if self.video_thread:
            self.video_thread.set_speed(self.parent.speed * 1.5)
    
    def resize_keeping_aspect_ratio(self, pixmap: QPixmap, max_width: int, max_height: int, video_width: int = 0, video_height: int = 0) -> QPixmap:
        """종횡비를 유지하면서 이미지 크기 조정"""
        if video_width <= 0 or video_height <= 0:
            video_width = pixmap.width()
            video_height = pixmap.height()

        if video_width > 0 and video_height > 0:
            aspect_ratio = video_width / video_height

            if aspect_ratio > 1:
                new_width = min(video_width, max_width)
                new_height = int(new_width / aspect_ratio)
            else:
                new_height = min(video_height, max_height)
                new_width = int(new_height * aspect_ratio)

            new_width = min(new_width, max_width)
            new_height = min(new_height, max_height)

            return pixmap.scaled(new_width, new_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return pixmap
    
    def update_preview_label(self):
        """미리보기 레이블 업데이트"""
        if self.parent.preview_label.pixmap() and not self.parent.preview_label.pixmap().isNull():
            scaled_pixmap = self.resize_keeping_aspect_ratio(
                self.parent.preview_label.pixmap(),
                self.parent.preview_label.width(),
                self.parent.preview_label.height(),
                self.current_video_width,
                self.current_video_height
            )
            self.parent.preview_label.setPixmap(scaled_pixmap)
    
    def update_video_frame(self, pixmap: QPixmap):
        """비디오 프레임 업데이트"""
        if not pixmap.isNull():
            scaled_pixmap = self.resize_keeping_aspect_ratio(
                pixmap,
                self.parent.preview_label.width(),
                self.parent.preview_label.height(),
                self.current_video_width,
                self.current_video_height
            )
            self.parent.preview_label.setPixmap(scaled_pixmap) 