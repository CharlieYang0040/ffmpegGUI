import os
import logging
from PySide6.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QIcon

from app.core.video_thread import VideoThread, VideoThreadState
from app.utils.utils import is_video_file, is_image_file, get_first_sequence_file, get_resource_path
from app.services.logging_service import LoggingService
from app.ui.components.timeline import TimelineComponent
from app.core.events import event_emitter, Events

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
        self.timeline = None
        
        # 이벤트 리스너 등록
        event_emitter.on(Events.TIMELINE_SEEK_PREV_FRAME, self.on_timeline_seek_frame)
        event_emitter.on(Events.TIMELINE_SEEK_NEXT_FRAME, self.on_timeline_seek_frame)
        event_emitter.on(Events.TIMELINE_SEEK_START, self.on_timeline_seek_frame)
        event_emitter.on(Events.TIMELINE_SEEK_END, self.on_timeline_seek_frame)
        
    def create_preview_area(self, top_layout):
        """미리보기 영역 생성"""
        # 미리보기 컨테이너 프레임
        preview_frame = QFrame()
        preview_frame.setFrameShape(QFrame.StyledPanel)
        preview_frame.setStyleSheet("background-color: #1a1a1a; border: 1px solid #3a3a3a;")
        
        # 미리보기 레이아웃
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(5, 5, 5, 5)
        
        # 미리보기 레이블 - 동적 크기로 설정
        self.parent.preview_label = QLabel(alignment=Qt.AlignCenter)
        # 최소 크기만 설정하고 최대 크기는 제한하지 않음
        self.parent.preview_label.setMinimumSize(500, 250)
        # 크기 정책을 Expanding으로 설정하여 사용 가능한 공간을 채우도록 함
        self.parent.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.parent.preview_label.setStyleSheet("background-color: #1a1a1a; border: 1px solid #3a3a3a;")
        self.parent.preview_label.setScaledContents(False)
        
        # 미리보기 레이아웃에 위젯 추가 - stretch 인자 추가
        preview_layout.addWidget(self.parent.preview_label, 1)  # stretch 인자 1 추가
        
        # 타임라인 컴포넌트 생성
        self.timeline = TimelineComponent(self.parent)
        self.timeline.create_timeline_area(preview_layout)
        
        # 메인 레이아웃에 미리보기 프레임 추가 - stretch 인자 추가
        top_layout.addWidget(preview_frame, 1)
    
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
            self.parent.play_button.setEnabled(False)
    
    def show_video_preview(self, file_path: str):
        """비디오 파일 미리보기 표시"""
        logger.debug(f"비디오 미리보기 시작: {file_path}")
        
        # 비디오 스레드 생성
        self.create_video_thread(file_path)
        
        if not self.video_thread:
            logger.error("비디오 스레드 생성 실패")
            return
            
        # 이미지 시퀀스인 경우 프록시 모드 활성화
        if '%' in file_path:
            # 미리보기 레이블 크기 기반으로 프록시 모드 설정
            preview_width = self.parent.preview_label.width()
            preview_height = self.parent.preview_label.height()
            logger.debug(f"이미지 시퀀스 프록시 모드 활성화: {preview_width}x{preview_height}")
            self.video_thread.set_preview_mode(True)
            self.video_thread.set_target_size(preview_width, preview_height)
        
        # 재생 버튼 활성화
        if hasattr(self.parent, 'play_button'):
            self.parent.play_button.setEnabled(True)

        # 비디오 정보 가져오기
        video_info = self.video_thread.get_video_info()
        logger.debug(f"비디오 정보: {video_info}")
        
        # 비디오 정보 확인
        if video_info['width'] <= 0 or video_info['height'] <= 0 or video_info['frame_count'] <= 0:
            logger.warning("유효하지 않은 비디오 정보")
            
            # 기본값 설정
            video_info = {
                'width': 1920,
                'height': 1080,
                'fps': 30,
                'duration': 10,
                'frame_count': 300
            }
        
        # 비디오 정보 설정
        self.current_video_width = video_info['width']
        self.current_video_height = video_info['height']
        
        # 타임라인에 비디오 정보 설정
        if self.timeline:
            # 비디오 속성에서 nb_frames 값 가져오기
            nb_frames = 0
            if self.video_thread and hasattr(self.video_thread, 'get_video_properties'):
                try:
                    video_properties = self.video_thread.get_video_properties(self.video_thread.file_path)
                    if 'nb_frames' in video_properties and video_properties['nb_frames'] != 'N/A':
                        nb_frames = int(video_properties['nb_frames'])
                        logger.debug(f"비디오 속성에서 nb_frames 정보 가져옴: {nb_frames}")
                except Exception as e:
                    logger.warning(f"nb_frames 정보 가져오기 실패: {e}")
            
            logger.debug(f"타임라인에 비디오 정보 설정: {video_info['frame_count']} 프레임, {video_info['fps']} fps, {video_info['duration']} 초, nb_frames: {nb_frames}")
            self.timeline.set_video_info(
                video_info['frame_count'], 
                video_info['fps'], 
                video_info['duration'],
                nb_frames
            )
        
        # 첫 프레임 표시
        first_frame = self.video_thread.get_video_frame(0)
        if first_frame and not first_frame.isNull():
            logger.debug("첫 프레임 표시 성공")
            self.update_video_frame(first_frame)
        else:
            logger.warning("첫 프레임 표시 실패")
            self.parent.preview_label.clear()
    
    def show_image_preview(self, file_path: str):
        """이미지 파일 미리보기 표시"""
        if '%' in file_path:
            # 이미지 시퀀스인 경우 비디오처럼 처리
            self.show_video_preview(file_path)
            return
            
        if os.path.exists(file_path):
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                scaled_pixmap = self.resize_keeping_aspect_ratio(pixmap, self.parent.preview_label.width(), self.parent.preview_label.height())
                self.parent.preview_label.setPixmap(scaled_pixmap)
                
                # 단일 이미지인 경우 타임라인 비활성화
                if self.timeline:
                    self.timeline.set_video_info(1, 1, 1, 1)
                
                # 재생 버튼 비활성화
                if hasattr(self.parent, 'play_button'):
                    self.parent.play_button.setEnabled(False)
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
        # 선택된 파일 확인
        selected_item = self.parent.list_widget.currentItem()
        if not selected_item:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.parent, "경고", "재생할 파일을 선택해주세요.")
            return

        # 비디오 스레드가 없거나 정지 상태인 경우 재생 시작
        if not self.video_thread or (hasattr(self.video_thread, 'state') and 
                                     self.video_thread.state == VideoThreadState.STOPPED):
            self.start_video_playback()
        # 재생 중인 경우 정지
        elif hasattr(self.video_thread, 'state') and self.video_thread.state == VideoThreadState.PLAYING:
            # 사용자가 직접 정지 버튼을 누른 경우, 첫 프레임으로 돌아가지 않음
            self.stop_video_playback(reset_to_first_frame=False)
        # 일시 정지 상태인 경우 재생 재개
        elif hasattr(self.video_thread, 'state') and self.video_thread.state == VideoThreadState.PAUSED:
            # 일시 정지 상태에서 재생 재개
            is_playing = self.video_thread.toggle_pause()
            self.parent.play_button.setText('⏹️ 정지' if is_playing else '▶️ 재생')
            logger.debug(f"비디오 일시정지 해제: {is_playing}")
        # 이전 버전과의 호환성을 위한 코드
        else:
            if not self.video_thread.is_playing:
                self.start_video_playback()
            else:
                self.stop_video_playback(reset_to_first_frame=False)
    
    def create_video_thread(self, file_path=None):
        """비디오 스레드 생성"""
        try:
            if file_path is None:
                file_path = self.parent.list_widget.get_selected_file_path()
                
            if not file_path:
                logger.warning("선택된 파일이 없습니다.")
                return
                
            if self.video_thread:
                self.stop_video_playback()
                
            self.video_thread = VideoThread(file_path)
            self.video_thread.frame_ready.connect(self.update_video_frame)
            self.video_thread.finished.connect(self.on_video_finished)
            self.video_thread.playback_completed.connect(self.on_playback_completed)
            self.video_thread.video_info_ready.connect(self.set_video_info)
            self.video_thread.frame_changed.connect(self.on_frame_changed)
            
            # 상태 변경 이벤트 연결
            if hasattr(self.video_thread, 'state_changed'):
                self.video_thread.state_changed.connect(self.on_video_state_changed)
            
            # 비디오 스레드 생성 로깅
            logger.debug(f"비디오 스레드 생성: {file_path}")
        except Exception as e:
            logger.error(f"비디오 스레드 생성 중 오류: {str(e)}")
            self.video_thread = None
    
    def start_video_playback(self):
        """비디오 재생 시작"""
        # 아이템이 선택되어 있는지 확인
        selected_item = self.parent.list_widget.currentItem()
        if not selected_item:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self.parent, "경고", "재생할 파일을 선택해주세요.")
            return
            
        # 비디오 스레드가 이미 실행 중인 경우
        if self.video_thread and self.video_thread.isRunning():
            # 일시 정지 상태인 경우 재생 재개
            if hasattr(self.video_thread, 'state') and self.video_thread.state == VideoThreadState.PAUSED:
                is_playing = self.video_thread.toggle_pause()
                self.parent.play_button.setText('⏹️ 정지' if is_playing else '▶️ 재생')
                logger.debug(f"비디오 일시정지 토글: {is_playing}")
                return
            # 이전 버전과의 호환성을 위한 코드
            elif hasattr(self.video_thread, 'paused'):
                is_playing = self.video_thread.toggle_pause()
                self.parent.play_button.setText('⏹️ 정지' if is_playing else '▶️ 재생')
                logger.debug(f"비디오 일시정지 토글(레거시): {is_playing}")
                return
            
        # 비디오 스레드가 없는 경우 생성
        if not self.video_thread:
            self.create_video_thread()
            
        # video_thread가 여전히 None인지 확인 (create_video_thread가 실패했을 수 있음)
        if not self.video_thread:
            logger.error("비디오 스레드를 생성할 수 없습니다.")
            return

        # 현재 타임라인 위치에서 시작
        try:
            if self.timeline and self.timeline.timeline_widget:
                current_frame = self.timeline.timeline_widget.current_frame
                self.video_thread.current_frame = current_frame
                logger.debug(f"타임라인 위치에서 시작: {current_frame}")
        except AttributeError as e:
            logger.error(f"타임라인 위치를 설정할 수 없습니다: {str(e)}")
            # 기본값으로 첫 프레임 설정
            self.video_thread.current_frame = 1

        # 상태 설정 및 재생 시작
        if hasattr(self.video_thread, 'state'):
            self.video_thread.state = VideoThreadState.PLAYING
        else:
            # 이전 버전과의 호환성을 위한 코드
            self.video_thread.is_playing = True
            self.video_thread.paused = False
            
        # 재생 속도 설정
        current_speed = self.parent.speed_slider.value() / 100
        self.video_thread.set_speed(current_speed * 1.5)
        
        # 스레드 시작
        if not self.video_thread.isRunning():
            self.video_thread.start()
            
        # UI 업데이트
        self.parent.play_button.setText('⏹️ 정지')
        logger.debug("비디오 재생 시작")
    
    def stop_video_playback(self, reset_to_first_frame=False):
        """비디오 재생 중지
        
        Args:
            reset_to_first_frame (bool): 첫 프레임으로 되돌릴지 여부. 기본값은 False.
        """
        if not hasattr(self, 'video_thread') or not self.video_thread:
            return
        
        # 이미 정지 상태인 경우 아무 작업도 하지 않음
        if hasattr(self.video_thread, 'state') and self.video_thread.state == VideoThreadState.STOPPED:
            return
        # 이전 버전과의 호환성을 위한 코드
        elif not hasattr(self.video_thread, 'state') and not self.video_thread.is_playing:
            return
        
        logger.debug(f"비디오 재생 중지 시작 (첫 프레임 리셋: {reset_to_first_frame})")
        
        # 비디오 스레드 중지
        self.video_thread.stop()
        self.video_thread.wait()
        
        # UI 업데이트
        self.update_ui_after_stop()
        
        # 첫 프레임으로 되돌리기 옵션이 활성화된 경우에만 실행
        if reset_to_first_frame:
            self.reset_to_first_frame()
    
    def on_playback_completed(self):
        """비디오 재생 완료 처리 (playback_completed 시그널에 의해 호출)"""
        logger.debug("비디오 재생 완료 시그널 수신")
        
        # 비디오 재생이 완료된 경우에는 첫 프레임으로 되돌리기
        self.reset_to_first_frame()
        
        # 재생 버튼 상태 업데이트
        if hasattr(self.parent, 'play_button'):
            self.parent.play_button.setIcon(QIcon(os.path.join(get_resource_path(), 'icons', 'play.png')))
            self.parent.play_button.setToolTip("재생")
            
        # 상태 업데이트
        if hasattr(self.video_thread, 'state'):
            self.video_thread.state = VideoThreadState.STOPPED
    
    def reset_to_first_frame(self):
        """비디오를 첫 프레임으로 초기화"""
        logger.debug("비디오를 첫 프레임으로 초기화 시작")
        
        if not self.timeline:
            logger.warning("타임라인이 설정되지 않았습니다.")
            return
            
        # 타임라인의 현재 프레임을 1로 설정
        self.timeline.set_current_frame(1)
        logger.debug("타임라인 현재 프레임을 1로 설정")
        
        # 비디오 스레드가 있는 경우 첫 프레임 표시
        if self.video_thread:
            try:
                # 0-based 인덱스로 변환하여 첫 프레임 가져오기
                first_frame = self.video_thread.get_video_frame(0)
                if first_frame and not first_frame.isNull():
                    self.update_video_frame(first_frame)
                    logger.debug("첫 프레임 표시 성공")
                else:
                    logger.warning("첫 프레임을 가져올 수 없습니다.")
            except Exception as e:
                logger.error(f"첫 프레임 표시 중 오류: {str(e)}")
        
        # UI 업데이트
        self.update_ui_after_stop()
        logger.debug("비디오를 첫 프레임으로 초기화 완료")
    
    def on_video_finished(self):
        """비디오 재생 완료 처리 (finished 시그널에 의해 호출)"""
        if not hasattr(self, 'video_thread') or not self.video_thread:
            return
        
        logger.debug("비디오 재생 finished 시그널 수신")
        
        # 비디오가 완료 상태인 경우에만 첫 프레임으로 초기화
        if hasattr(self.video_thread, 'is_completed') and self.video_thread.is_completed:
            logger.debug("비디오가 완료 상태로 확인됨, 첫 프레임으로 초기화")
            self.reset_to_first_frame()
            
            # 재생 버튼 상태 업데이트
            if hasattr(self.parent, 'play_button'):
                self.parent.play_button.setIcon(QIcon(os.path.join(get_resource_path(), 'icons', 'play.png')))
                self.parent.play_button.setToolTip("재생")
                
            # 상태 업데이트
            if hasattr(self.video_thread, 'state'):
                self.video_thread.state = VideoThreadState.STOPPED
        else:
            # 일반 정지인 경우 현재 프레임 유지
            logger.debug("비디오가 완료 상태가 아님, 현재 프레임 유지")
            self.stop_video_playback(reset_to_first_frame=False)
    
    def on_frame_changed(self, frame: int):
        """프레임 변경 이벤트 처리"""
        try:
            if self.timeline:
                self.timeline.set_current_frame(frame)
                logger.debug(f"비디오 스레드에서 프레임 변경 알림: {frame}")
        except AttributeError as e:
            logger.error(f"프레임 변경 처리 중 오류: {str(e)}")
    
    def update_ui_after_stop(self):
        """비디오 정지 후 UI 업데이트"""
        if self.video_thread:
            # 새로운 상태 관리 시스템 사용
            if hasattr(self.video_thread, 'state'):
                self.video_thread.state = VideoThreadState.STOPPED
            else:
                # 이전 버전과의 호환성을 위한 코드
                self.video_thread.is_playing = False
        
        # 재생 버튼 텍스트 변경
        if hasattr(self.parent, 'play_button'):
            self.parent.play_button.setText('▶️ 재생')
            logger.debug("재생 버튼 상태 업데이트: 재생")
    
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
        """미리보기 레이블 크기 업데이트 (UI 크기 변경 시에만 호출)"""
        if hasattr(self.parent, 'preview_label'):
            # 현재 비디오 프레임이 있으면 크기에 맞게 다시 표시
            if hasattr(self, 'video_thread') and self.video_thread and self.parent.preview_label.pixmap() and not self.parent.preview_label.pixmap().isNull():
                # 현재 레이블 크기에 맞게 영상 크기만 조정
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
            # 레이블 크기에 맞게 영상 크기 조정 (레이블 크기는 변경하지 않음)
            scaled_pixmap = self.resize_keeping_aspect_ratio(
                pixmap,
                self.parent.preview_label.width(),
                self.parent.preview_label.height(),
                self.current_video_width,
                self.current_video_height
            )
            self.parent.preview_label.setPixmap(scaled_pixmap)
    
    def get_trim_points(self) -> tuple:
        """트림 지점 가져오기"""
        if self.timeline:
            in_point = self.timeline.get_in_point()
            out_point = self.timeline.get_out_point()
            return (in_point, out_point)
        return (0, 0)

    def on_timeline_seek_frame(self, frame):
        """타임라인 프레임 이동 이벤트 처리"""
        logger.debug(f"타임라인 프레임 이동 이벤트: {frame}")
        if self.video_thread:
            # 이미지 시퀀스와 비디오 파일 모두 동일하게 처리
            # seek_to_frame 메서드 내부에서 1-based에서 0-based로 변환
            self.video_thread.seek_to_frame(frame)
            logger.debug(f"프레임 탐색 요청: {frame}") 

    def on_video_state_changed(self, state):
        """비디오 상태 변경 이벤트 처리"""
        logger.debug(f"비디오 상태 변경: {state.name}")
        
        # 재생 버튼 상태 업데이트
        if hasattr(self.parent, 'play_button'):
            if state == VideoThreadState.PLAYING:
                self.parent.play_button.setText('⏹️ 정지')
            elif state == VideoThreadState.PAUSED:
                self.parent.play_button.setText('▶️ 재생')
            elif state == VideoThreadState.STOPPED:
                self.parent.play_button.setText('▶️ 재생') 