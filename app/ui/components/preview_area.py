import os
import logging
import subprocess
import queue # Added for frame buffer
import re    # Added for image sequence path parsing
import glob  # Added for image sequence file finding
from typing import Dict, Optional, Tuple, Union, Any # Added for type hinting

from PySide6.QtWidgets import QLabel, QVBoxLayout, QHBoxLayout, QFrame, QSizePolicy, QMessageBox, QWidget
from PySide6.QtCore import Qt, QUrl, Slot, QTimer, QRunnable, QThreadPool, QObject, QThread, Signal # Added QRunnable, QThreadPool, QObject, Signal
from PySide6.QtGui import QPixmap, QIcon, QImage # Added QImage for robust loading
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget

# Removed: from app.core.video_thread import VideoThread as MediaInfoLoaderThread 
from app.core.image_sequence_loader import ImageSequenceLoaderThread # Keep image loader
from app.utils.utils import is_video_file, is_image_file, get_resource_path
from app.services.logging_service import LoggingService
from app.ui.components.timeline import TimelineComponent
from app.core.events import event_emitter, Events
from app.core.ffmpeg_manager import FFmpegManager
from PIL import Image # Added for image size reading

# 로깅 서비스 설정
logger = LoggingService().get_logger(__name__)

# --- Aspect Ratio Widget ---
class AspectRatioWidget(QWidget):
    """지정된 종횡비를 유지하는 위젯 컨테이너"""
    def __init__(self, aspect_ratio: float = 16.0/9.0, parent=None):
        super().__init__(parent)
        self._aspect_ratio = aspect_ratio
        # 수평으로는 확장, 수직으로는 Preferred 설정
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def heightForWidth(self, width: int) -> int:
        """너비에 따른 높이 계산"""
        return int(width / self._aspect_ratio)

    def hasHeightForWidth(self) -> bool:
        """너비에 따라 높이가 결정됨을 알림"""
        return True

    def resizeEvent(self, event):
        """크기 변경 시 높이를 너비에 맞춰 업데이트"""
        # 너비는 레이아웃에 의해 결정되므로, 높이만 조정
        w = event.size().width()
        h = self.heightForWidth(w)
        # 직접 크기 설정 대신, sizePolicy와 heightForWidth를 통해 Qt 레이아웃 시스템이 처리하도록 유도
        # self.setFixedHeight(h) # 직접 설정하면 레이아웃 충돌 가능성
        super().resizeEvent(event)
# --- End Aspect Ratio Widget ---

# --- Media Info Fetcher (QRunnable) --- 
class MediaInfoFetcherSignals(QObject):
    """Holds signals for MediaInfoFetcher runnable."""
    result_ready = Signal(int, str, dict) # request_id, file_path, media_info
    error = Signal(int, str, str)         # request_id, file_path, error_message

class MediaInfoFetcher(QRunnable):
    """Runnable task to fetch media information in the background."""
    def __init__(self, request_id: int, file_path: str, ffmpeg_manager: FFmpegManager):
        super().__init__()
        self.request_id = request_id
        self.file_path = file_path
        self.ffmpeg_manager = ffmpeg_manager
        self.signals = MediaInfoFetcherSignals()
        self.logger = LoggingService().get_logger(f"{__name__}.MediaInfoFetcher")

    def run(self):
        """Fetches media info (video, image sequence, or single image)."""
        # 경로 정규화 (백슬래시 -> 슬래시)
        self.file_path = self.file_path.replace("\\", "/")
        logger.debug(f"백그라운드 미디어 정보 로딩 시작 (ID: {self.request_id}, 정규화된 경로): {os.path.basename(self.file_path)}")
        media_info = {
            'width': 0, 'height': 0, 'fps': 0,
            'duration': 0, 'frame_count': 0,
            'is_image_sequence': False,
            'is_single_image': False,
            'file_path': self.file_path # Include file_path for verification
        }
        error_msg = None
        is_image_sequence = '%' in self.file_path
        is_single_image = not is_image_sequence and self.file_path.lower().endswith(
            ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
        )
        media_info['is_image_sequence'] = is_image_sequence
        media_info['is_single_image'] = is_single_image

        try:
            if is_single_image:
                img_size = self._get_image_size(self.file_path)
                if img_size != (0, 0):
                    media_info['width'], media_info['height'] = img_size
                    media_info['fps'] = 1.0
                    media_info['frame_count'] = 1
                    media_info['duration'] = 1.0
                else:
                    error_msg = f"단일 이미지 크기 로드 실패: {os.path.basename(self.file_path)}"
            
            elif is_image_sequence:
                # re.sub에서 치환 문자열을 '*'로 수정 ('*.' -> '*')
                pattern = re.sub(r'%(\d*)d', '*', self.file_path)
                search_pattern = os.path.join(os.path.dirname(self.file_path), os.path.basename(pattern))
                
                # 로그 추가: 생성된 검색 패턴 확인
                self.logger.debug(f"이미지 시퀀스 검색 패턴: {search_pattern}")
                
                image_files = sorted(glob.glob(search_pattern))
                
                # 로그 추가: 찾은 파일 목록 확인 (최대 10개)
                if image_files:
                    self.logger.debug(f"찾은 이미지 파일 (최대 10개): {image_files[:10]}")
                else:
                    self.logger.warning(f"glob으로 이미지 파일을 찾지 못했습니다: {search_pattern}")

                if image_files:
                    try:
                        # 첫 파일 이름에서 프레임 번호 추출 (예: file.0178.png -> 178)
                        first_file_name = os.path.basename(image_files[0])
                        # 수정: 정규식 변경 가능성 고려 (파일 이름 마지막 숫자 그룹 추출)
                        match = re.search(r'(\d+)(?!.*\d)', first_file_name)
                        start_frame_number = 0 # 기본값 0
                        if match:
                            try:
                                detected_frame = int(match.group(1))
                                if detected_frame >= 0: # 0 이상이면 유효
                                    start_frame_number = detected_frame
                                    self.logger.debug(f"감지된 시작 프레임 번호 (0-based): {start_frame_number}")
                                else:
                                    self.logger.warning(f"감지된 시작 프레임 번호({detected_frame})가 음수. 기본값 0 사용.")
                            except ValueError:
                                 self.logger.warning(f"프레임 번호 '{match.group(1)}' 변환 실패. 기본값 0 사용.")
                        else:
                            self.logger.warning(f"시작 프레임 번호 감지 못함: {first_file_name}. 기본값 0 사용.")
                        # media_info에는 0-based 시작 인덱스 저장
                        media_info['start_frame'] = start_frame_number
                    except Exception as e:
                        self.logger.error(f"시작 프레임 번호 파싱 중 오류: {e}", exc_info=True)
                        media_info['start_frame'] = 0 # 오류 시 기본값 0

                    first_image_path = image_files[0]
                    img_size = self._get_image_size(first_image_path)
                    if img_size != (0, 0):
                        media_info['width'], media_info['height'] = img_size
                        media_info['fps'] = 30.0 # Default FPS
                        media_info['frame_count'] = len(image_files)
                        media_info['duration'] = media_info['frame_count'] / media_info['fps'] if media_info['fps'] > 0 else 0
                    else:
                        error_msg = f"이미지 시퀀스 첫 프레임 크기 로드 실패: {os.path.basename(first_image_path)}"
                else:
                    error_msg = f"이미지 시퀀스 파일 없음: {search_pattern}"
            
            else: # Video file
                properties = self._get_video_properties(self.file_path)
                if properties:
                    media_info['width'] = int(properties.get('width', 0))
                    media_info['height'] = int(properties.get('height', 0))
                    media_info['fps'] = float(properties.get('fps', 0))
                    media_info['duration'] = float(properties.get('duration', 0))
                    
                    # Frame count calculation
                    frame_count_raw = properties.get('nb_frames', 'N/A')
                    if frame_count_raw != 'N/A':
                        try:
                            media_info['frame_count'] = int(frame_count_raw)
                            if media_info['frame_count'] <= 0: raise ValueError("nb_frames <= 0")
                        except (ValueError, TypeError):
                            self.logger.warning(f"잘못된 nb_frames 값 '{frame_count_raw}', duration으로 계산 시도")
                            media_info['frame_count'] = int(media_info['duration'] * media_info['fps']) if media_info['duration'] > 0 and media_info['fps'] > 0 else 0
                    elif media_info['duration'] > 0 and media_info['fps'] > 0:
                        media_info['frame_count'] = int(media_info['duration'] * media_info['fps'])
                    else:
                        media_info['frame_count'] = 0

                    if media_info['width'] <= 0 or media_info['height'] <= 0 or media_info['fps'] <= 0:
                        error_msg = f"필수 비디오 정보 누락/0: W={media_info['width']}, H={media_info['height']}, FPS={media_info['fps']:.2f}"
                else:
                    error_msg = f"ffprobe로 비디오 속성 가져오기 실패: {os.path.basename(self.file_path)}"

            # Emit result or error - 시그널 발생 시 request_id 전달
            if error_msg:
                 self.logger.error(f"미디어 정보 로드 실패 ({os.path.basename(self.file_path)}): {error_msg}")
                 self.signals.error.emit(self.request_id, self.file_path, error_msg) # request_id 전달
            else:
                 self.logger.info(f"미디어 정보 로드 완료 ({os.path.basename(self.file_path)})")
                 self.signals.result_ready.emit(self.request_id, self.file_path, media_info) # request_id 전달
        
        except Exception as e:
            error_msg = f"미디어 정보 로드 중 예외 발생 ({os.path.basename(self.file_path)}): {e}"
            self.logger.exception(error_msg)
            self.signals.error.emit(self.request_id, self.file_path, error_msg) # request_id 전달
        finally:
             self.logger.debug(f"백그라운드 미디어 정보 로딩 종료: {os.path.basename(self.file_path)}")
             # Note: No finished signal needed as result/error covers completion

    def _get_video_properties(self, input_file: str) -> Dict[str, Any]:
        """Uses ffprobe via FFmpegManager to get video properties."""
        try:
            ffprobe_path = self.ffmpeg_manager.get_ffprobe_path()
            if not ffprobe_path:
                self.logger.error("FFprobe 경로가 설정되지 않았습니다.")
                return {}
            
            self.logger.debug(f"미디어 속성 가져오기 (ffprobe): {input_file}")
            cmd = [
                ffprobe_path,
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,r_frame_rate,duration,nb_frames',
                '-of', 'default=noprint_wrappers=1:nokey=0',
                input_file
            ]
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags)
            
            if result.returncode != 0:
                self.logger.error(f"FFprobe 실행 실패: {result.stderr}")
                return {}
                
            properties = {}
            for line in result.stdout.splitlines():
                if '=' in line:
                    key, value = line.split('=', 1)
                    properties[key.strip()] = value.strip()
            
            # Calculate FPS safely
            if 'r_frame_rate' in properties:
                try:
                    num, den = map(int, properties['r_frame_rate'].split('/'))
                    if den == 0: raise ZeroDivisionError("Denominator is zero")
                    properties['fps'] = num / den
                except (ValueError, ZeroDivisionError) as e:
                    self.logger.warning(f"FPS 파싱 오류 '{properties['r_frame_rate']}': {e}. 기본값 30 사용.")
                    properties['fps'] = 30.0
            else:
                 properties['fps'] = 30.0 # Default FPS
            
            self.logger.debug(f"가져온 비디오 속성 (raw): {properties}")
            return properties
            
        except Exception as e:
            self.logger.exception(f"_get_video_properties 실패: {e}")
            return {}

    def _get_image_size(self, file_path: str) -> Tuple[int, int]:
        """Uses PIL to get image size."""
        try:
            with Image.open(file_path) as img:
                return img.size
        except FileNotFoundError:
            self.logger.error(f"이미지 파일 없음: {file_path}")
            return (0, 0)
        except Exception as e:
            self.logger.error(f"_get_image_size 실패 '{os.path.basename(file_path)}': {e}")
            return (0, 0)

# --- End Media Info Fetcher --- 

# 재생 상태 Enum (UI 관리용)
class PlaybackState:
    STOPPED = 0
    PLAYING = 1
    PAUSED = 2

class PreviewAreaComponent:
    """
    미리보기 영역 관련 기능을 제공하는 컴포넌트 클래스
    """
    
    def __init__(self, parent):
        """
        :param parent: 부모 위젯 (FFmpegGui 인스턴스)
        """
        self.parent = parent
        # Removed: self.media_info_loader_thread = None
        self.image_loader_thread = None # For loading image sequences
        self.thread_pool = QThreadPool.globalInstance() # Use global thread pool
        self.last_request_id = 0 # 요청 ID 카운터 추가
        # self.current_fetcher_task = None # Optional: Keep track of the running task
        self.current_fetcher_task = None # ★ 현재 실행 중인 fetcher 참조

        self.media_player = None
        self.audio_output = None
        self.video_widget = None
        self.image_preview_label = None
        self.media_container = None # 16:9 비율 컨테이너 추가

        # Media Info
        self.current_media_path = None
        self.current_media_width = 0
        self.current_media_height = 0
        self.current_media_fps = 0
        self.current_media_duration_ms = 0
        self.current_media_frame_count = 0
        self.is_video_mode = False # Determined after info fetch
        self.current_media_start_frame_index = 0 # 이미지 시퀀스 시작 프레임 인덱스 (0-based)

        # Image Sequence Playback specific
        self.frame_buffer = queue.Queue(maxsize=60) # Frame buffer (index, QPixmap)
        self.frame_timer = QTimer(self.parent) # Timer for displaying frames
        self.image_sequence_playback_state = PlaybackState.STOPPED
        self.expected_sequence_frame_index = 0 # 0-based index for next frame

        self.timeline = None
        self.ffmpeg_manager = FFmpegManager()
        
        # Connect timer
        self.frame_timer.timeout.connect(self._update_sequence_frame)

        # 이벤트 리스너 등록
        event_emitter.on(Events.TIMELINE_SEEK_PREV_FRAME, self.on_timeline_seek_frame)
        event_emitter.on(Events.TIMELINE_SEEK_NEXT_FRAME, self.on_timeline_seek_frame)
        event_emitter.on(Events.TIMELINE_SEEK_START, self.on_timeline_seek_frame)
        event_emitter.on(Events.TIMELINE_SEEK_END, self.on_timeline_seek_frame)

    def create_preview_area(self, top_layout):
        """미리보기 영역 생성"""
        preview_frame = QFrame()
        preview_frame.setFrameShape(QFrame.StyledPanel)
        preview_frame.setStyleSheet("background-color: #1a1a1a; border: 1px solid #3a3a3a;")
        
        preview_layout = QVBoxLayout(preview_frame)
        preview_layout.setContentsMargins(5, 5, 5, 5)

        # --- 16:9 비율 컨테이너 생성 ---
        self.media_container = AspectRatioWidget(aspect_ratio=16.0/9.0)
        self.media_container.setMinimumHeight(250) # 최소 높이 설정
        media_container_layout = QVBoxLayout(self.media_container) # 컨테이너 내부 레이아웃
        media_container_layout.setContentsMargins(0, 0, 0, 0) # 여백 없음

        # --- Preview Widgets (컨테이너 내부에 배치) --- 
        self.image_preview_label = QLabel(alignment=Qt.AlignCenter)
        # 라벨의 수직 크기 정책을 Ignored로 변경하여 컨테이너 크기에 영향 주지 않도록 함
        self.image_preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.image_preview_label.setStyleSheet("background-color: #2a2a2a;")
        self.image_preview_label.setScaledContents(False) # 직접 스케일링하므로 False
        self.image_preview_label.hide()

        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding) # 컨테이너 채우도록
        self.video_widget.setStyleSheet("background-color: #1a1a1a;")
        self.video_widget.hide()
        
        # 컨테이너 레이아웃에 미디어 위젯 추가
        media_container_layout.addWidget(self.video_widget)
        media_container_layout.addWidget(self.image_preview_label)
        
        # 메인 미리보기 레이아웃에 16:9 컨테이너 추가
        preview_layout.addWidget(self.media_container)
        # preview_layout.addWidget(self.video_widget, 1) # 제거
        # preview_layout.addWidget(self.image_preview_label, 1) # 제거
        # --- End Preview Widgets --- 

        # --- Media Player Setup --- 
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        self.media_player.setVideoOutput(self.video_widget)

        # Connect signals
        self.media_player.durationChanged.connect(self.on_duration_changed)
        self.media_player.positionChanged.connect(self.on_position_changed)
        self.media_player.playbackStateChanged.connect(self.on_playback_state_changed)
        self.media_player.mediaStatusChanged.connect(self.on_media_status_changed)
        self.media_player.errorOccurred.connect(self.on_media_error)
        # --- End Media Player Setup --- 

        # 타임라인 컴포넌트 생성
        self.timeline = TimelineComponent(self.parent)
        self.timeline.create_timeline_area(preview_layout)
        
        # TimelineWidget의 frame_changed 시그널을 on_timeline_seek_frame 슬롯에 연결
        if self.timeline and self.timeline.timeline_widget:
            self.timeline.timeline_widget.frame_changed.connect(self.on_timeline_seek_frame)
            logger.debug("TimelineWidget.frame_changed 시그널 연결됨")
        else:
            logger.error("TimelineWidget 또는 TimelineComponent가 제대로 생성되지 않아 시그널 연결 실패")

        top_layout.addWidget(preview_frame, 1)
    
    def update_preview(self):
        """현재 선택된 파일의 미리보기 업데이트"""
        try:
            file_path_raw = self.parent.list_widget.get_selected_file_path()
            if not file_path_raw:
                self.stop_current_preview()
                return
            
            # 경로 정규화 (백슬래시 -> 슬래시)
            file_path = file_path_raw.replace("\\", "/")
            
            if self.current_media_path == file_path:
                logger.debug(f"선택된 파일 동일 ({os.path.basename(file_path)}), 미리보기 업데이트 건너뜀")
                return
            
            # 다른 파일 선택 시 현재 재생/로딩 중인 것 모두 중지
            self.stop_current_preview() 
            self.current_media_path = file_path # ★ 정규화된 경로 저장
            logger.info(f"미리보기 업데이트 시작: {file_path}")
            
            # 위젯 초기화 (로딩 중 표시?) 
            self._clear_preview_widgets() 
            self.image_preview_label.setText("미디어 정보 로딩 중...") # Placeholder text
            self.image_preview_label.show()

            # 요청 ID 증가
            self.last_request_id += 1
            current_request_id = self.last_request_id
            logger.debug(f"새 미디어 정보 요청 생성 (ID: {current_request_id}): {os.path.basename(file_path)}")

            # 이전 fetcher 참조 제거 (선택적이지만 명확성을 위해)
            self.current_fetcher_task = None

            # 백그라운드에서 미디어 정보 가져오기 시작 (request_id 전달)
            fetcher = MediaInfoFetcher(current_request_id, file_path, self.ffmpeg_manager) # ID 전달
            fetcher.signals.result_ready.connect(self.on_media_info_ready)
            fetcher.signals.error.connect(self.on_media_info_error)
            self.current_fetcher_task = fetcher # ★ Keep a reference to the current fetcher
            self.thread_pool.start(fetcher)
            # logger.debug(f"미디어 정보 로딩 작업 시작됨: {os.path.basename(file_path)}") # 로그 변경됨

        except Exception as e:
            logger.error(f"미리보기 업데이트 준비 중 오류: {str(e)}", exc_info=True)
            self._clear_preview_widgets()
            QMessageBox.critical(self.parent, "오류", f"미리보기 업데이트 준비 중 오류 발생:\n{str(e)}")
            self.current_media_path = None
            self.current_fetcher_task = None # ★ Clear reference on error too

    @Slot(int, str, dict)
    def on_media_info_ready(self, request_id: int, fetched_file_path: str, media_info: dict):
        """백그라운드 미디어 정보 로딩 완료 시 호출되는 슬롯"""
        logger.debug(f"미디어 정보 수신 시도 (ID: {request_id}): {os.path.basename(fetched_file_path)}")

        try: # 슬롯 전체에 대한 예외 처리 추가
            # 요청 ID 확인
            if request_id != self.last_request_id:
                logger.warning(f"오래된 미디어 정보 수신됨 (ID: {request_id}, 최신 ID: {self.last_request_id}), 무시.")
                return

            # 현재 선택된 경로와도 한 번 더 확인 (추가 방어 로직)
            if fetched_file_path != self.current_media_path:
                logger.warning(f"수신된 경로({os.path.basename(fetched_file_path)})가 현재 경로({os.path.basename(self.current_media_path or '')})와 다름, 무시.")
                return
            
            logger.info(f"미디어 정보 수신 완료 (ID: {request_id}): {os.path.basename(fetched_file_path)}")
            
            # 정보 저장
            self.current_media_width = media_info['width']
            self.current_media_height = media_info['height']
            self.current_media_fps = media_info['fps']
            self.current_media_duration_ms = int(media_info['duration'] * 1000)
            self.current_media_frame_count = media_info['frame_count']
            self.is_video_mode = not media_info['is_image_sequence'] and not media_info['is_single_image']
            is_image_sequence = media_info['is_image_sequence']
            is_single_image = media_info['is_single_image']
            # 이미지 시퀀스 시작 프레임 정보 가져오기 (0-based)
            # self.current_media_start_frame = media_info.get('start_frame', 1)
            self.current_media_start_frame_index = media_info.get('start_frame', 0) # 0-based 인덱스 저장, 기본값 0

            # 로딩 중 텍스트 제거
            self.image_preview_label.clear()

            # 필수 정보 유효성 검사
            if self.current_media_width <= 0 or self.current_media_height <= 0 or self.current_media_fps <= 0:
                 error_msg = f"수신된 미디어 정보가 유효하지 않음: {media_info}"
                 logger.error(error_msg)
                 QMessageBox.critical(self.parent, "오류", f"미디어 정보를 올바르게 읽을 수 없습니다.\n{error_msg}")
                 self._clear_preview_widgets() # 위젯 초기화
                 self.current_media_path = None # 경로 초기화
                 return

            # 타임라인 설정
            if self.timeline:
                self.timeline.set_video_info(
                    self.current_media_frame_count,
                    self.current_media_fps,
                    self.current_media_duration_ms / 1000.0
                )
                self.timeline.reset_in_out_points() # 새 파일 로드 시 In/Out 초기화
            
            # 파일 타입에 따라 미리보기 설정 분기
            file_path = self.current_media_path # 현재 경로 사용
            if self.is_video_mode:
                logger.debug("비디오 파일 미리보기 설정 (QMediaPlayer)")
                self.image_preview_label.hide()
                self.video_widget.show()
                try:
                    # 오디오 출력 설정 확인 (선택적)
                    # if self.audio_output.isMuted(): self.audio_output.setMuted(False)
                    # self.audio_output.setVolume(1.0)
                    
                    self.media_player.setSource(QUrl.fromLocalFile(file_path))
                    logger.debug(f"QMediaPlayer 소스 설정 완료: {file_path}")
                    # 재생 버튼 활성화는 mediaStatusChanged 에서 처리
                except Exception as e:
                     logger.error(f"QMediaPlayer 소스 설정 실패: {e}")
                     QMessageBox.critical(self.parent, "오류", f"비디오 파일을 열 수 없습니다:\n{os.path.basename(file_path)}\\n\\n오류: {e}")
                     self._clear_preview_widgets()
                     self.current_media_path = None

            elif is_image_sequence:
                logger.debug("이미지 시퀀스 미리보기 설정 시작")
                self.video_widget.hide()
                self.image_preview_label.show() # 이미지 표시 레이블 보이기
                # 첫 프레임 표시 (로더 시작 전) - 시작 프레임 인덱스 사용 (0-based)
                # start_frame은 1 이상이 보장됨
                # start_frame_index = self.current_media_start_frame - 1 # 0-based 계산
                start_frame_index = self.current_media_start_frame_index # 이미 0-based
                # 유효성 검사 추가
                if start_frame_index < 0:
                    logger.warning(f"잘못된 시작 프레임 인덱스({start_frame_index}), 0으로 조정.")
                    start_frame_index = 0
                self._display_sequence_frame(start_frame_index)
                # 재생 버튼 활성화
                if hasattr(self.parent, 'play_button'): self.parent.play_button.setEnabled(True)
                # 로더 스레드 시작 - 시작 프레임 인덱스 전달
                # self._start_image_sequence_loading(file_path, self.current_media_start_frame)
                self._start_image_sequence_loading(file_path, self.current_media_start_frame_index)

            elif is_single_image:
                logger.debug("단일 이미지 미리보기 설정")
                self.video_widget.hide()
                self.image_preview_label.show()
                self.show_single_image_preview(file_path) # pixmap 로드 및 표시
                # 재생 버튼 비활성화는 show_single_image_preview 내부에서 처리
            
            else:
                 # 이 경우는 media_info 유효성 검사에서 걸러졌어야 함
                 logger.error(f"알 수 없는 미디어 타입입니다: {file_path}")
                 self._clear_preview_widgets()
                 self.current_media_path = None
        
        except Exception as e:
             # 슬롯 실행 중 발생한 예외 로깅
             logger.exception(f"on_media_info_ready 슬롯 실행 중 예외 발생 (ID: {request_id}): {e}")
             # 오류 발생 시 UI 정리 시도
             try:
                 QMessageBox.critical(self.parent, "오류", f"미디어 정보 처리 중 예상치 못한 오류가 발생했습니다:\n{e}")
                 self._clear_preview_widgets()
                 self.current_media_path = None
             except Exception as inner_e:
                 logger.error(f"on_media_info_ready 오류 처리 중 추가 예외 발생: {inner_e}")

    @Slot(int, str, str)
    def on_media_info_error(self, request_id: int, error_file_path: str, error_msg: str):
        """미디어 정보 로딩 중 오류 발생 시 호출되는 슬롯"""
        logger.debug(f"미디어 정보 오류 수신 시도 (ID: {request_id}): {os.path.basename(error_file_path)}")

        try: # 슬롯 전체에 대한 예외 처리 추가
            # 요청 ID 확인
            if request_id != self.last_request_id:
                logger.warning(f"오래된 미디어 정보 오류 수신됨 (ID: {request_id}, 최신 ID: {self.last_request_id}), 무시.")
                return

            # 현재 선택된 경로와도 한 번 더 확인 (추가 방어 로직)
            if error_file_path != self.current_media_path:
                 logger.warning(f"오류 발생 경로({os.path.basename(error_file_path)})가 현재 경로({os.path.basename(self.current_media_path or '')})와 다름, 무시.")
                 return

            logger.error(f"미디어 정보 로딩 오류 (ID: {request_id}, 파일: {os.path.basename(error_file_path)}): {error_msg}")
            QMessageBox.critical(self.parent, "오류", f"미디어 정보를 가져오는 중 오류 발생:\n{error_msg}")
            self._clear_preview_widgets() # 위젯 초기화
            self.current_media_path = None # 경로 초기화
        
        except Exception as e:
            # 슬롯 실행 중 발생한 예외 로깅
            logger.exception(f"on_media_info_error 슬롯 실행 중 예외 발생 (ID: {request_id}): {e}")
            # 오류 발생 시 UI 정리 시도 (중복될 수 있으나 방어적으로)
            try:
                 self._clear_preview_widgets()
                 self.current_media_path = None
            except Exception as inner_e:
                 logger.error(f"on_media_info_error 오류 처리 중 추가 예외 발생: {inner_e}")

    def _clear_preview_widgets(self):
        """미리보기 위젯 숨기고 초기화"""
        if self.image_preview_label:
            self.image_preview_label.clear()
            self.image_preview_label.hide()
        if self.video_widget:
            self.video_widget.hide()
        if self.timeline:
            self.timeline.set_video_info(0, 0, 0) # 비디오 정보 초기화
            self.timeline.set_current_frame(1)    # 현재 프레임 1로 설정
            self.timeline.reset_in_out_points() # In/Out 지점 초기화
        if hasattr(self.parent, 'play_button'):
            self.parent.play_button.setEnabled(False)
            self.parent.play_button.setText('▶️ 재생')

    def stop_current_preview(self):
        """현재 재생/표시 중인 미디어를 정리하는 메서드"""
        logger.debug("현재 미리보기 정리 시작")
        
        # QMediaPlayer 정리
        if self.media_player and self.media_player.playbackState() != QMediaPlayer.StoppedState:
                 logger.debug("QMediaPlayer 중지")
                 self.media_player.stop()

        # 이미지 시퀀스 로더 및 타이머 정리
        self._stop_image_sequence_playback() # 내부에서 스레드/타이머 중지

        # 이미지 로더 스레드 종료 요청 (wait 제거)
        if self.image_loader_thread and self.image_loader_thread.isRunning():
             logger.debug("ImageSequenceLoaderThread 종료 요청")
             self.image_loader_thread.requestInterruption()
             # self.image_loader_thread.wait(1000) 제거 및 관련 블록 제거
             # 스레드 참조 제거 및 시그널 해제는 _cleanup_image_loader_thread 슬롯에서 처리

        # 프레임 버퍼 비우기
        self._clear_frame_buffer()

        self._clear_preview_widgets() # 위젯 숨기기 및 초기화
        self.current_media_path = None # 현재 경로 초기화 (★ 중요: 다음 fetcher 결과 처리를 위해)
        self.is_video_mode = False
        self.image_sequence_playback_state = PlaybackState.STOPPED
        self.current_fetcher_task = None # ★ Clear fetcher reference
        logger.debug("현재 미리보기 정리 완료 (wait 제거됨)")

    def update_preview_label(self):
        """Handles resizing of the preview label, rescaling the displayed image/frame."""
        if self.is_video_mode or not self.image_preview_label or not self.image_preview_label.isVisible():
            # 비디오 모드이거나 라벨이 없거나 보이지 않으면 아무것도 안 함
            return

        # 현재 표시해야 할 프레임 인덱스 가져오기 (expected_sequence_frame_index 사용)
        current_frame_index = self.expected_sequence_frame_index # 0-based 절대 인덱스 사용

        # 현재 재생 중인 상태가 아니라면 (정지 또는 일시정지)
        # _display_sequence_frame을 호출하여 현재 프레임을 새 크기에 맞게 다시 표시
        if self.image_sequence_playback_state != PlaybackState.PLAYING and self.current_media_path:
            logger.debug(f"Resizing: Re-displaying frame {current_frame_index}")
            self._display_sequence_frame(current_frame_index)
        # 참고: 재생 중일 때는 다음 프레임이 업데이트될 때 자동으로 새 크기가 반영될 것임
        # ( _update_sequence_frame 내부의 resize_keeping_aspect_ratio 호출 )

    def _display_sequence_frame(self, frame_index: int):
         """지정된 인덱스의 이미지 시퀀스 프레임을 표시 (첫 프레임 표시에 주로 사용)"""
         if self.is_video_mode or not self.image_preview_label: return
         
         # 경로 정규화 (백슬래시 -> 슬래시)
         if not self.current_media_path:
             logger.warning("_display_sequence_frame 호출 시 current_media_path가 없습니다.")
             return
         normalized_path = self.current_media_path.replace("\\", "/")
         
         logger.debug(f"시퀀스 프레임 {frame_index} 표시 시도 (직접 로드, 경로: {normalized_path})")
         pixmap = None
         
         if '%' in normalized_path:
              try:
                   # 파일 경로 생성 (0-based index -> N-padded string)
                   match = re.search(r'%(\d*)d', normalized_path)
                   if match:
                       padding = match.group(1)
                       format_spec = f"{{:0{padding}d}}" if padding else "{}"
                       frame_str = format_spec.format(frame_index + 1) # 1-based frame number
                       target_file_path = re.sub(r'%(\d*)d', frame_str, normalized_path)
                       
                       if os.path.exists(target_file_path):
                            # logger.debug(f"프레임 파일 로드: {target_file_path}")
                            pixmap = QPixmap(target_file_path) 
                            if pixmap.isNull():
                                 # QImage로 재시도
                                 image = QImage(target_file_path)
                                 if not image.isNull(): pixmap = QPixmap.fromImage(image)
                                 else: logger.warning(f"프레임 {frame_index} 로드 실패 (QPixmap & QImage): {os.path.basename(target_file_path)}")
                       else:
                            logger.warning(f"프레임 파일 없음: {target_file_path}")
                   else:
                        logger.error("이미지 시퀀스 경로 포맷 오류")
              except Exception as e:
                   logger.error(f"프레임 {frame_index} 직접 로드 중 오류: {e}")
         
         if pixmap and not pixmap.isNull():
             # 스케일링 기준을 media_container 크기로 변경
             container_width = self.media_container.width()
             container_height = self.media_container.height()
             
             # 컨테이너 크기가 유효할 때만 스케일링 수행
             if container_width > 0 and container_height > 0:
                 scaled_pixmap = self.resize_keeping_aspect_ratio(
                     pixmap,
                     container_width, 
                     container_height,
                     self.current_media_width, # 원본 너비
                     self.current_media_height # 원본 높이
                 )
                 self.image_preview_label.setPixmap(scaled_pixmap)
                 # logger.debug(f"프레임 {frame_index} 표시 완료 (직접 로드)")
             else:
                  # 컨테이너 크기가 아직 유효하지 않으면 원본 표시 또는 임시 처리
                  logger.warning(f"컨테이너 크기 미확정 ({container_width}x{container_height}), 스케일링 건너뜀")
                  # self.image_preview_label.setPixmap(pixmap) # 또는 원본 표시
         else:
              self.image_preview_label.clear() # 프레임 없으면 클리어
              self.image_preview_label.setText(f"(프레임 {frame_index + 1} 로드 실패)") # 사용자에게 실패 프레임 번호 알림
              logger.warning(f"프레임 {frame_index} 표시 실패 (직접 로드)")

    def resize_keeping_aspect_ratio(self, pixmap: QPixmap, target_width: int, target_height: int, original_width: int, original_height: int) -> QPixmap:
        """Resizes a QPixmap while keeping its aspect ratio, fitting within target dimensions."""
        if not pixmap or pixmap.isNull() or target_width <= 0 or target_height <= 0 or original_width <= 0 or original_height <= 0:
            return pixmap # Return original if invalid input

        scaled_pixmap = pixmap.scaled(target_width, target_height, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        return scaled_pixmap

    def _update_sequence_frame(self):
        """타이머에 의해 호출되어 이미지 시퀀스의 다음 프레임을 표시합니다."""
        if self.image_sequence_playback_state != PlaybackState.PLAYING or self.is_video_mode:
            return # 재생 중이 아니거나 비디오 모드면 중지

        try:
            # 프레임 버퍼에서 다음 프레임 가져오기 (non-blocking)
            frame_index, pixmap = self.frame_buffer.get_nowait()
            
            if frame_index != self.expected_sequence_frame_index:
                 logger.warning(f"예상 프레임({self.expected_sequence_frame_index})과 버퍼 프레임({frame_index}) 불일치, 건너뜀")
                 # 버퍼를 따라잡기 위해 예상 인덱스 업데이트 시도?
                 # self.expected_sequence_frame_index = frame_index # 주의: 프레임 드롭 발생 가능
                 # 일단은 건너뛰고 다음 타이머 호출 기다림
                 return

            if pixmap and not pixmap.isNull():
                # 스케일링 기준을 media_container 크기로 변경
                container_width = self.media_container.width()
                container_height = self.media_container.height()
                
                # 컨테이너 크기가 유효할 때만 스케일링 수행
                if container_width > 0 and container_height > 0:
                    scaled_pixmap = self.resize_keeping_aspect_ratio(
                        pixmap,
                        container_width,
                        container_height,
                        self.current_media_width,
                        self.current_media_height
                    )
                    self.image_preview_label.setPixmap(scaled_pixmap)
                    # logger.debug(f"프레임 {frame_index} 표시 완료 (버퍼)")
                else:
                    logger.warning(f"컨테이너 크기 미확정 ({container_width}x{container_height}), 스케일링 건너뜀")

                # 타임라인 업데이트
                if self.timeline:
                    # 프레임 인덱스는 0부터 시작하므로 +1 해서 1-based로 변환
                    # 절대 인덱스 대신 상대적인 프레임 번호로 업데이트
                    start_frame_index = self.current_media_start_frame_index
                    relative_frame = (frame_index - start_frame_index) + 1
                    # self.timeline.set_current_frame(frame_index + 1, emit_signal=False)
                    self.timeline.set_current_frame(relative_frame, emit_signal=False)
                
                # 다음 예상 프레임 인덱스 증가
                self.expected_sequence_frame_index += 1

                # 시퀀스 끝 확인 (종료 조건 수정)
                last_frame_index = self.current_media_start_frame_index + self.current_media_frame_count - 1
                if self.expected_sequence_frame_index > last_frame_index:
                    logger.info(f"이미지 시퀀스 재생 완료 (끝 도달: 예상={self.expected_sequence_frame_index}, 마지막={last_frame_index})")
                    self._stop_image_sequence_playback(reset_frame=True)
            else:
                logger.warning(f"버퍼에서 가져온 프레임 {frame_index}가 유효하지 않음")
                # 유효하지 않은 프레임이면 일단 건너뛰기

        except queue.Empty:
            # 버퍼가 비어있음 - 로더가 따라잡지 못하는 경우
            logger.warning("프레임 버퍼 비어 있음 (언더런 발생)")
            # 로더 스레드가 여전히 실행 중이고 시퀀스가 끝나지 않았는지 확인
            if self.image_loader_thread and self.image_loader_thread.isRunning() and \
               self.expected_sequence_frame_index < self.current_media_frame_count:
                 # 로더가 따라잡을 때까지 잠시 기다리는 것을 고려할 수 있으나,
                 # 일단은 타이머가 계속 돌도록 둠 (다음 프레임이 곧 들어올 수 있음)
                 pass
            else:
                 # 로더가 멈췄거나 시퀀스가 끝났는데 버퍼가 빈 경우 -> 재생 중지
                 logger.info("로더가 멈췄거나 시퀀스 끝, 재생 중지")
                 self._stop_image_sequence_playback(reset_frame=True)
        
        except Exception as e:
            logger.error(f"시퀀스 프레임 업데이트 중 오류: {e}", exc_info=True)
            self._stop_image_sequence_playback(reset_frame=False)

    # --- 이미지 시퀀스 로딩 및 재생 관련 도우미 메소드 --- 
    # (아래 메소드들은 예시이며, 실제 구현은 필요에 따라 달라질 수 있음)

    def _start_image_sequence_loading(self, file_path: str, start_frame_index: int): # 파라미터명 변경 (0-based)
        """이미지 시퀀스 로더 스레드를 시작합니다."""
        if self.image_loader_thread and self.image_loader_thread.isRunning():
            logger.warning("이미지 로더 스레드가 이미 실행 중입니다.")
            return

        # 기존 스레드 정리 (만약을 위해)
        self._stop_image_sequence_playback() 
        self._clear_frame_buffer()

        # expected_sequence_frame_index 를 실제 시작 프레임의 0-based 인덱스로 설정
        self.expected_sequence_frame_index = start_frame_index # 이미 0-based
        
        # ImageSequenceLoaderThread 생성자에 start_frame 전달 (1-based 프레임 번호)
        start_frame_number = start_frame_index + 1 # 1-based로 변환
        self.image_loader_thread = ImageSequenceLoaderThread(file_path, self.frame_buffer, start_frame=start_frame_number)
        # 필요한 시그널 연결 (주석 해제)
        self.image_loader_thread.error.connect(self.on_image_loader_error)
        self.image_loader_thread.finished.connect(self._cleanup_image_loader_thread)
        
        logger.info(f"이미지 시퀀스 로더 스레드 시작: {os.path.basename(file_path)}")
        # QThreadPool 대신 QThread.start() 사용
        # self.thread_pool.start(self.image_loader_thread)
        self.image_loader_thread.start()

    def _stop_image_sequence_playback(self, reset_frame: bool = True):
        """이미지 시퀀스 재생 및 로딩을 중지합니다."""
        # 타이머 중지
        if self.frame_timer.isActive():
            self.frame_timer.stop()
            logger.debug("프레임 타이머 중지")

        # 재생 상태 변경
        self.image_sequence_playback_state = PlaybackState.STOPPED
        
        # 로더 스레드 중지 요청
        if self.image_loader_thread and self.image_loader_thread.isRunning():
            logger.debug("이미지 로더 스레드 중지 요청")
            self.image_loader_thread.requestInterruption() # 스레드에 종료 요청
            # 스레드가 완전히 종료될 때까지 기다리는 대신,
            # 일단 UI 상태는 즉시 업데이트
            # self.image_loader_thread.wait(500) # 필요하다면 짧게 대기
        
        # 프레임 리셋 및 UI 업데이트
        if reset_frame:
             # expected_sequence_frame_index를 시작 프레임의 0-based 인덱스로 초기화
             self.expected_sequence_frame_index = self.current_media_start_frame_index
             if not self.is_video_mode:
                 # 0번 프레임 대신 시작 프레임 인덱스 사용
                 # _display_sequence_frame(self.current_media_start_frame - 1)
                 self._display_sequence_frame(self.current_media_start_frame_index)
             # 타임라인도 시작 프레임으로 설정 (1-based)
             # if self.timeline: self.timeline.set_current_frame(self.current_media_start_frame)
             if self.timeline: self.timeline.set_current_frame(self.current_media_start_frame_index + 1)
        
        # 재생 버튼 상태 업데이트 (STOPPED 상태 전달)
        self.update_play_button_state(PlaybackState.STOPPED)

    def _clear_frame_buffer(self):
        """프레임 버퍼를 비웁니다."""
        while not self.frame_buffer.empty():
            try:
                self.frame_buffer.get_nowait()
            except queue.Empty:
                break
        logger.debug("프레임 버퍼 비움")

    @Slot(str)
    def on_image_loader_error(self, error_msg: str):
        """ImageSequenceLoaderThread에서 오류 발생 시 호출되는 슬롯"""
        logger.error(f"이미지 로더 스레드 오류: {error_msg}")
        # 필요시 사용자에게 알림 표시
        # QMessageBox.warning(self.parent, "오류", f"이미지 로딩 중 오류:\n{error_msg}")
        # 오류 발생 시 재생 중지 및 UI 정리
        self._stop_image_sequence_playback(reset_frame=False)

    @Slot() # finished 시그널은 인자를 보내지 않음
    def _cleanup_image_loader_thread(self):
        """ImageSequenceLoaderThread 종료 시 호출되어 리소스를 정리하는 슬롯"""
        # sender_thread = self.sender() # 시그널을 보낸 스레드 객체 가져오기 -> AttributeError 발생
        # # if not thread_object:
        # if not sender_thread or not isinstance(sender_thread, QThread):
        #     logger.warning("_cleanup_image_loader_thread: 유효하지 않은 스레드 객체 수신")
        #     return

        # 현재 저장된 스레드 참조를 사용
        thread_to_cleanup = self.image_loader_thread 
        if not thread_to_cleanup:
             logger.warning("_cleanup_image_loader_thread: 정리할 스레드 참조가 없습니다 (이미 정리되었거나 없음).")
             return

        # finished 시그널을 보낸 스레드가 현재 참조와 같은지 확인하는 로직은 불필요.
        # finished 시그널은 해당 스레드가 종료될 때만 발생하므로, 
        # 이 슬롯이 호출되었다면 self.image_loader_thread가 종료된 것이 맞음.
        
        thread_id = thread_to_cleanup.objectName() if thread_to_cleanup.objectName() else id(thread_to_cleanup)
        logger.debug(f"이미지 로더 스레드({thread_id}) finished 시그널 수신, 정리 시작")
        try:
            # 시그널 연결 해제
            # sender_thread.error.disconnect(self.on_image_loader_error)
            thread_to_cleanup.error.disconnect(self.on_image_loader_error)
        except TypeError:
            logger.debug(f"({thread_id}) error 시그널 연결 해제 실패")
        except Exception as e:
            logger.warning(f"({thread_id}) error 시그널 연결 해제 중 예외 발생: {e}")
        try:
            # finished 시그널에 연결된 모든 슬롯 해제 시도
            # sender_thread.finished.disconnect()
            thread_to_cleanup.finished.disconnect() # 자기 자신과의 연결도 해제
            logger.debug(f"({thread_id}) finished 시그널 연결 해제 시도 완료")
        except TypeError:
            logger.debug(f"({thread_id}) finished 시그널 연결 해제 실패 (연결된 슬롯 없음?)")
        except Exception as e:
            logger.warning(f"({thread_id}) finished 시그널 연결 해제 중 예외 발생: {e}")

        # 스레드 참조 제거
        self.image_loader_thread = None
        logger.debug(f"이미지 로더 스레드({thread_id}) 참조 제거 완료")
        
        # 오래된 스레드 finished 시그널 처리 로직 제거 (불필요)
        # else:
        #     current_thread_id = id(self.image_loader_thread) if self.image_loader_thread else "None"
        #     received_thread_id = sender_thread.objectName() if sender_thread.objectName() else id(sender_thread)
        #     logger.warning(f"오래된/다른 이미지 로더 스레드({received_thread_id})의 finished 시그널 수신, 현재 스레드({current_thread_id}), 무시.")
        # else 블록 삭제 (린터 오류 수정)

    @Slot(int) # qint64 -> int 또는 @Slot() 사용
    def on_duration_changed(self, duration_ms: int):
        """QMediaPlayer의 duration 변경 시 호출됨"""
        if not self.is_video_mode: return
        # 미디어가 현재 로드된 미디어인지 확인
        if not self.media_player or self.media_player.source().toLocalFile() != self.current_media_path:
             return
        logger.debug(f"QMediaPlayer durationChanged: {duration_ms} ms")
        
        # ... (rest of the logic is likely fine)
        old_duration_ms = self.current_media_duration_ms
        self.current_media_duration_ms = duration_ms
        if self.current_media_fps > 0:
            new_frame_count = int((duration_ms / 1000.0) * self.current_media_fps)
            if new_frame_count != self.current_media_frame_count:
                logger.info(f"Duration 변경으로 frame_count 업데이트: {self.current_media_frame_count} -> {new_frame_count}")
                self.current_media_frame_count = new_frame_count
                if self.timeline:
                    self.timeline.set_video_info(
                        self.current_media_frame_count,
                        self.current_media_fps,
                        self.current_media_duration_ms / 1000.0
                    )
        else:
            logger.warning("FPS 정보가 없어 frame_count를 재계산할 수 없습니다.")

    @Slot(int)
    def on_position_changed(self, position_ms: int):
        """QMediaPlayer의 재생 위치 변경 시 호출됨"""
        if not self.is_video_mode: return
        if not self.media_player or self.media_player.source().toLocalFile() != self.current_media_path:
             return
        # logger.debug(f"QMediaPlayer positionChanged: {position_ms} ms") # 너무 빈번하게 로깅됨
        if self.timeline and self.current_media_fps > 0:
            current_frame = self._ms_to_frame(position_ms)
            self.timeline.set_current_frame(current_frame, emit_signal=False) # 내부 변경이므로 시그널 발생 방지

    @Slot(QMediaPlayer.PlaybackState)
    def on_playback_state_changed(self, state: QMediaPlayer.PlaybackState):
        """QMediaPlayer의 재생 상태 변경 시 호출됨"""
        if not self.is_video_mode: return
        if not self.media_player or self.media_player.source().toLocalFile() != self.current_media_path:
             # logger.debug("오래된 QMediaPlayer 상태 변경 무시")
             return
        logger.debug(f"QMediaPlayer playbackStateChanged: {state}")
        self.update_play_button_state(state)

    @Slot(QMediaPlayer.MediaStatus)
    def on_media_status_changed(self, status: QMediaPlayer.MediaStatus):
        """QMediaPlayer의 미디어 상태 변경 시 호출됨"""
        if not self.is_video_mode: return
        # 상태 변경이 현재 미디어에 대한 것인지 확인
        # source()가 null일 수 있으므로 주의
        current_source_file = self.media_player.source().toLocalFile() if self.media_player and self.media_player.source().isValid() else None
        if current_source_file != self.current_media_path:
             # logger.debug(f"오래된 QMediaPlayer 상태 변경 무시 (Status: {status}, Current: {self.current_media_path}, Source: {current_source_file})")
             return
        logger.debug(f"QMediaPlayer mediaStatusChanged: {status}")

        play_button_enabled = False
        if status == QMediaPlayer.LoadedMedia:
            logger.info("미디어 로드 완료, 재생 가능 상태")
            play_button_enabled = True
        elif status == QMediaPlayer.EndOfMedia:
            logger.info("미디어 재생 완료 (EndOfMedia)")
            self.reset_to_first_frame() # 첫 프레임 이동 및 UI 업데이트
            play_button_enabled = True # 완료 후 다시 재생 가능
        elif status == QMediaPlayer.InvalidMedia:
            logger.error("잘못된 미디어 파일 (InvalidMedia)")
            self.on_media_error(self.media_player.error(), self.media_player.errorString() or "Invalid Media")
            play_button_enabled = False
        elif status == QMediaPlayer.LoadingMedia:
            logger.debug("미디어 로딩 중...")
            play_button_enabled = False # 로딩 중 비활성화
        elif status == QMediaPlayer.BufferingMedia or status == QMediaPlayer.BufferedMedia:
            logger.debug(f"버퍼링 상태: {status}")
            play_button_enabled = True # 버퍼링 중에도 재생/일시정지 가능
        elif status == QMediaPlayer.NoMedia:
            logger.debug("미디어 없음 (NoMedia)")
            play_button_enabled = False
        elif status == QMediaPlayer.StalledMedia:
             logger.warning("미디어 Stalled 상태")
             play_button_enabled = True # 재생 시도 가능할 수 있음
        elif status == QMediaPlayer.UnknownMediaStatus:
            logger.warning("알 수 없는 미디어 상태")
            play_button_enabled = False

        if hasattr(self.parent, 'play_button'):
            self.parent.play_button.setEnabled(play_button_enabled)
            if not play_button_enabled:
                 self.update_play_button_state(QMediaPlayer.StoppedState) # 아이콘/텍스트 업데이트

    @Slot(QMediaPlayer.Error, str)
    def on_media_error(self, error: QMediaPlayer.Error, error_string: str):
        """QMediaPlayer 오류 발생 시 호출됨"""
        # 오류가 현재 미디어에 대한 것인지 확인
        current_source_file = self.media_player.source().toLocalFile() if self.media_player and self.media_player.source().isValid() else None
        if current_source_file != self.current_media_path:
             logger.warning(f"오래된 QMediaPlayer 오류 무시 (Error: {error_string}, Current: {self.current_media_path}, Source: {current_source_file})")
             return

        logger.error(f"QMediaPlayer 오류 발생: Code={error}, Message='{error_string}'")
        if error != QMediaPlayer.NoError:
            QMessageBox.critical(self.parent, "미디어 오류", f"미디어 재생 중 오류가 발생했습니다:\n{error_string}\n(파일: {os.path.basename(self.current_media_path or '')})")
            self.stop_current_preview() # 오류 발생 시 미리보기 정리

    def update_play_button_state(self, state):
        """재생 상태에 따라 재생 버튼 UI 업데이트 (통합)"""
        # logger.debug(f"Update play button state: {state}")
        if hasattr(self.parent, 'play_button'):
            button = self.parent.play_button
            is_playing = False
            is_paused = False
            is_stopped = True # Default to stopped
            can_play = False  # Default to disabled

            if self.is_video_mode:
                # QMediaPlayer 상태
                qt_state = state
                is_playing = (qt_state == QMediaPlayer.PlayingState)
                is_paused = (qt_state == QMediaPlayer.PausedState)
                is_stopped = (qt_state == QMediaPlayer.StoppedState)
                # 미디어가 로드되었고 오류가 없는 경우 재생 가능
                media_status = self.media_player.mediaStatus()
                can_play = self.media_player is not None and \
                           (media_status == QMediaPlayer.LoadedMedia or \
                            media_status == QMediaPlayer.BufferingMedia or \
                            media_status == QMediaPlayer.BufferedMedia or \
                            media_status == QMediaPlayer.EndOfMedia) and \
                           self.media_player.error() == QMediaPlayer.NoError
            else: # 이미지 시퀀스 모드
                # 내부 PlaybackState 사용
                internal_state = state 
                is_playing = (internal_state == PlaybackState.PLAYING)
                is_paused = (internal_state == PlaybackState.PAUSED)
                is_stopped = (internal_state == PlaybackState.STOPPED)
                # 현재 미디어 경로가 있고, 비디오 모드가 아니면 재생 가능
                can_play = (self.current_media_path is not None and not self.is_video_mode)

            # 버튼 텍스트 및 상태 설정
            if is_playing:
                 button.setText("⏸️ 일시정지")
                 button.setEnabled(True) # 재생 중에는 항상 활성화
            elif is_paused:
                 button.setText("▶️ 재생")
                 button.setEnabled(True) # 일시정지 중에는 항상 활성화
            elif is_stopped:
                button.setText("▶️ 재생")
                button.setEnabled(can_play) # 중지 상태에서는 재생 가능 여부에 따라 활성화
            else: # 알 수 없음 상태 or Fallback
                button.setText("▶️ 재생")
                button.setEnabled(False)

    def toggle_play(self):
        """재생/일시정지 상태를 토글합니다."""
        if not self.current_media_path:
            logger.warning("재생할 미디어가 없습니다.")
            return

        if self.is_video_mode:
            # 비디오 모드 (QMediaPlayer)
            if self.media_player:
                state = self.media_player.playbackState()
                if state == QMediaPlayer.PlayingState:
                    logger.info("QMediaPlayer 일시정지")
                    self.media_player.pause()
                elif state == QMediaPlayer.PausedState or state == QMediaPlayer.StoppedState:
                    logger.info("QMediaPlayer 재생")
                    self.media_player.play()
                else:
                    logger.warning(f"알 수 없는 QMediaPlayer 상태 ({state})에서는 재생/일시정지 불가")
            else:
                logger.error("미디어 플레이어가 초기화되지 않았습니다.")
        else:
            # 이미지 시퀀스 모드
            if self.image_sequence_playback_state == PlaybackState.PLAYING:
                # 재생 중 -> 일시정지
                logger.info("이미지 시퀀스 일시정지")
                self.image_sequence_playback_state = PlaybackState.PAUSED
                if self.frame_timer.isActive(): self.frame_timer.stop()
                self.update_play_button_state(PlaybackState.PAUSED) # 버튼 상태 업데이트
            elif self.image_sequence_playback_state == PlaybackState.PAUSED:
                 # 일시정지 -> 재생 (재개)
                 logger.info("이미지 시퀀스 재생 (재개)")
                 self.image_sequence_playback_state = PlaybackState.PLAYING
                 interval = int(1000 / self.current_media_fps) if self.current_media_fps > 0 else 33
                 self.frame_timer.start(interval)
                 self.update_play_button_state(PlaybackState.PLAYING)
            elif self.image_sequence_playback_state == PlaybackState.STOPPED:
                 # 중지 -> 재생 (로더 재시작 필요)
                 logger.info("이미지 시퀀스 재생 (처음부터/재시작)")
                 # 로더 재시작 및 예상 인덱스 초기화
                 self._start_image_sequence_loading(self.current_media_path, self.current_media_start_frame_index)
                 # 상태 변경 및 타이머 시작
                 self.image_sequence_playback_state = PlaybackState.PLAYING
                 interval = int(1000 / self.current_media_fps) if self.current_media_fps > 0 else 33
                 self.frame_timer.start(interval)
                 self.update_play_button_state(PlaybackState.PLAYING) # 버튼 상태 업데이트
            else:
                 logger.warning(f"알 수 없는 이미지 시퀀스 상태({self.image_sequence_playback_state})에서는 재생/일시정지 불가")

    def reset_to_first_frame(self):
        """미디어를 첫 프레임으로 초기화 (UI 및 상태)"""
        logger.debug("첫 프레임으로 리셋 시작")
        if self.is_video_mode:
            if self.media_player:
                # QMediaPlayer는 stop() 호출 시 자동으로 0으로 이동됨
                if self.media_player.position() != 0:
                    self.media_player.setPosition(0) # 명시적으로 0으로 설정 시도
                if self.media_player.playbackState() != QMediaPlayer.StoppedState:
                    self.media_player.stop() # 중지 상태가 아니면 중지
            # 타임라인 및 버튼 업데이트는 on_media_status_changed(EndOfMedia) 에서 처리됨
            # 또는 여기서 직접 호출 필요 시:
            # if self.timeline: self.timeline.set_current_frame(1)
            # self.update_play_button_state(QMediaPlayer.StoppedState)
        else:
            # 이미지 시퀀스
            self._stop_image_sequence_playback(reset_frame=True) # 내부에서 상태, 타이머, UI 업데이트
        
        logger.debug("첫 프레임으로 리셋 완료")

    def _ms_to_frame(self, ms: int) -> int:
        """밀리초를 프레임 번호로 변환 (1-based)"""
        if self.current_media_fps > 0:
            # + 0.5 는 반올림 효과, int()는 버림
            # frame = int((ms / 1000.0) * self.current_media_fps + 0.5) + 1 
            # QMediaPlayer position은 프레임 시작 시점 기준이므로 단순 계산
            frame = int((ms / 1000.0) * self.current_media_fps) + 1
            # 프레임 범위 제한
            return max(1, min(frame, self.current_media_frame_count if self.current_media_frame_count > 0 else 1))
        return 1 # FPS 모르면 첫 프레임 반환

    def _frame_to_ms(self, frame: int) -> int:
        """프레임 번호(1-based)를 밀리초로 변환"""
        if self.current_media_fps > 0:
            # 프레임 번호가 1부터 시작하므로 (frame - 1) 사용
            ms = int(((frame - 1) / self.current_media_fps) * 1000)
            # 시간 범위 제한 (음수 방지, 최대 duration 이내)
            return max(0, min(ms, self.current_media_duration_ms if self.current_media_duration_ms > 0 else 0))
        return 0 # FPS 모르면 0 반환

    def on_timeline_seek_frame(self, frame: int):
        """타임라인 프레임 이동 이벤트 처리"""
        logger.debug(f"타임라인 프레임 이동 이벤트 수신: {frame}")
        if self.is_video_mode:
            if self.media_player and self.current_media_fps > 0:
                position_ms = self._frame_to_ms(frame)
                logger.debug(f"QMediaPlayer 위치 설정 요청: frame {frame} -> {position_ms} ms")
                self.media_player.setPosition(position_ms)
            elif not self.media_player:
                logger.warning("미디어 플레이어가 없어 탐색할 수 없습니다.")
            else: # fps <= 0
                logger.warning("FPS 정보가 없어 프레임 위치로 탐색할 수 없습니다.")
        else:
            # 이미지 시퀀스 탐색 구현
            if not self.current_media_path or self.current_media_frame_count <= 0:
                logger.warning("이미지 시퀀스 정보가 없어 탐색할 수 없습니다.")
                return

            # 1. 재생/로딩 중지 (프레임 리셋 없이) 및 상태 업데이트
            logger.debug(f"이미지 시퀀스 탐색 시작: 프레임 {frame}")
            self._stop_image_sequence_playback(reset_frame=False)

            # 2. 프레임 버퍼 비우기
            self._clear_frame_buffer()

            # 3. 유효한 프레임 번호인지 확인 (1-based, 상대적)
            requested_relative_frame = max(1, min(frame, self.current_media_frame_count))
            logger.debug(f"요청된 상대 프레임 (범위 조정됨): {requested_relative_frame}")
            
            # 4. 표시할 절대 프레임 인덱스 계산 (0-based)
            # 시작 프레임 번호 (1-based)를 고려
            target_absolute_index = (requested_relative_frame - 1) + self.current_media_start_frame_index
            
            # 프레임 인덱스 범위 재확인 (절대 인덱스 기준)
            first_frame_index = self.current_media_start_frame_index
            last_frame_index = first_frame_index + self.current_media_frame_count - 1
            target_absolute_index = max(first_frame_index, min(target_absolute_index, last_frame_index))
            logger.debug(f"계산된 절대 프레임 인덱스 (0-based): {target_absolute_index}")
            
            # 5. 다음 예상 프레임 인덱스 업데이트
            self.expected_sequence_frame_index = target_absolute_index

            # 6. 요청된 프레임 직접 표시
            self._display_sequence_frame(target_absolute_index)
            
            # 7. 타임라인 UI 업데이트 (이미 슬라이더 이동 시 업데이트되었을 것이므로, 현재 프레임만 다시 설정)
            if self.timeline:
                 # set_current_frame에는 1-based 상대 프레임 전달
                 self.timeline.set_current_frame(requested_relative_frame, emit_signal=False) 

            # 8. 재생 상태는 STOPPED로 유지 ( _stop_image_sequence_playback 에서 처리됨)
            logger.debug(f"이미지 시퀀스 프레임 탐색 완료: {requested_relative_frame} (절대 인덱스 {target_absolute_index})")

    def change_speed(self, speed: float):
        """재생 속도를 변경합니다."""
        logger.debug(f"재생 속도 변경 요청: {speed:.1f}x")
        if self.is_video_mode:
            if self.media_player:
                self.media_player.setPlaybackRate(speed)
                logger.info(f"QMediaPlayer 재생 속도 변경: {speed:.1f}x")
        else:
            # 이미지 시퀀스 타이머 간격 조절
            if self.current_media_fps > 0 and speed > 0:
                interval = int(1000 / (self.current_media_fps * speed))
                if self.frame_timer.isActive():
                    self.frame_timer.setInterval(interval)
                    logger.info(f"이미지 시퀀스 타이머 간격 변경: {interval}ms ({speed:.1f}x)")
                else:
                     # 타이머가 비활성 상태면 간격만 저장하고 나중에 start 시 적용?
                     # 현재 구현에서는 재생 시작 시 항상 새로 계산하므로 별도 저장 불필요
                     pass
            else:
                logger.warning("FPS 또는 속도 정보가 유효하지 않아 타이머 간격 변경 불가")

    def __del__(self):
        """소멸자: 리소스 정리"""
        try:
            logger.debug("PreviewAreaComponent 소멸자 호출")
            # 비디오 스레드 정리 (이미지 시퀀스용)
            if hasattr(self, 'video_thread') and self.video_thread:
                if self.video_thread.isRunning():
                    self.video_thread.stop()
                    # 짧게 대기 (블로킹 방지)
                    if not self.video_thread.wait(500):
                        logger.warning("소멸자에서 스레드 종료 대기 시간 초과")
                
                # 시그널 연결 해제
                try:
                    self._disconnect_all_signals()
                except Exception as e:
                    logger.warning(f"소멸자에서 시그널 연결 해제 실패: {str(e)}")
                
                self.video_thread = None
                logger.debug("소멸자에서 비디오 스레드 정리 완료")
            else:
                logger.debug("기존 비디오 스레드 없음")
            
            # QMediaPlayer 정리
            if hasattr(self, 'media_player') and self.media_player:
                logger.debug("소멸자: QMediaPlayer 정리 시작")
                # 시그널 연결 해제 (선택적, 객체 삭제 시 자동 해제될 수 있음)
                try: self.media_player.durationChanged.disconnect(self.on_duration_changed) 
                except: pass
                try: self.media_player.positionChanged.disconnect(self.on_position_changed) 
                except: pass
                try: self.media_player.playbackStateChanged.disconnect(self.on_playback_state_changed) 
                except: pass
                try: self.media_player.mediaStatusChanged.disconnect(self.on_media_status_changed) 
                except: pass
                try: self.media_player.errorOccurred.disconnect(self.on_media_error) 
                except: pass

                self.media_player.setVideoOutput(None) # 출력 연결 해제
                self.media_player.setAudioOutput(None)
                self.media_player.stop() # 재생 중지
                # self.media_player.deleteLater() # Qt 객체 삭제는 부모가 관리하거나 deleteLater 권장
                self.media_player = None # 참조 제거
                self.audio_output = None
                logger.debug("소멸자: QMediaPlayer 정리 완료")

            # 이벤트 리스너 해제
            try:
                event_emitter.off(Events.TIMELINE_SEEK_PREV_FRAME, self.on_timeline_seek_frame)
                event_emitter.off(Events.TIMELINE_SEEK_NEXT_FRAME, self.on_timeline_seek_frame)
                event_emitter.off(Events.TIMELINE_SEEK_START, self.on_timeline_seek_frame)
                event_emitter.off(Events.TIMELINE_SEEK_END, self.on_timeline_seek_frame)
                logger.debug("소멸자: 이벤트 리스너 해제 완료")
            except Exception as e:
                logger.error(f"소멸자: 이벤트 리스너 해제 중 오류: {str(e)}")
        except Exception as e:
            logger.error(f"PreviewAreaComponent 소멸자에서 오류 발생: {str(e)}")

    def _disconnect_all_signals(self):
        """모든 시그널 연결 해제"""
        if not hasattr(self, 'video_thread') or not self.video_thread:
            return
        
        # 모든 시그널 연결 해제
        try:
            self.video_thread.frame_ready.disconnect()
            self.video_thread.finished.disconnect()
            self.video_thread.playback_completed.disconnect()
            self.video_thread.video_info_ready.disconnect()
            self.video_thread.frame_changed.disconnect()
            self.video_thread.state_changed.disconnect()
            logger.debug("모든 시그널 연결 해제 완료")
        except Exception as e:
            logger.warning(f"모든 시그널 연결 해제 중 오류: {str(e)}") 