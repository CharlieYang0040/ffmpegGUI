# video_thread.py

import ffmpeg
import numpy as np
from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition
from PySide6.QtGui import QPixmap, QImage
from concurrent.futures import ThreadPoolExecutor
import cv2
import subprocess
import os
import logging
import glob
from PIL import Image
import json
from typing import Dict, Optional, Tuple, Union, Any
import time
from app.utils.utils import get_debug_mode
import io
import re
import queue
from enum import Enum, auto

# 로깅 서비스 가져오기
from app.services.logging_service import LoggingService

# FFmpegManager 싱글톤 가져오기
from app.core.ffmpeg_manager import FFmpegManager

# 로깅 설정
logger = LoggingService().get_logger(__name__)

# FFmpeg 경로를 전역 변수로 설정
FFMPEG_PATH = None
FFPROBE_PATH = None

# 비디오 스레드 상태 열거형
class VideoThreadState(Enum):
    """비디오 스레드 상태 열거형"""
    STOPPED = auto()    # 정지 상태
    PLAYING = auto()    # 재생 중
    PAUSED = auto()     # 일시 정지
    SEEKING = auto()    # 탐색 중
    ERROR = auto()      # 오류 상태

def set_ffmpeg_path(path: str):
    global FFMPEG_PATH, FFPROBE_PATH
    if os.path.exists(path):
        FFMPEG_PATH = path
        FFPROBE_PATH = os.path.join(os.path.dirname(path), 'ffprobe.exe')
        logger.debug(f"FFmpeg 경로 설정: {FFMPEG_PATH}")
        logger.debug(f"FFprobe 경로 설정: {FFPROBE_PATH}")
    else:
        logger.error(f"FFmpeg 경로를 찾을 수 없음: {path}")


class VideoThread(QThread):
    """비디오 재생을 위한 스레드 클래스"""
    
    # 시그널 정의
    frame_ready = Signal(QPixmap)
    finished = Signal()
    video_info_ready = Signal(int, int)
    frame_changed = Signal(int)  # 현재 프레임 변경 시그널
    playback_completed = Signal()  # 재생 완료 시그널 추가
    state_changed = Signal(VideoThreadState)  # 상태 변경 시그널 추가
    
    def __init__(self, file_path: str, parent=None):
        """
        비디오 스레드 초기화
        
        Args:
            file_path: 비디오 파일 경로
            parent: 부모 객체
        """
        super().__init__(parent)
        
        # FFmpegManager 인스턴스 가져오기
        self.ffmpeg_manager = FFmpegManager()
        self.logger = LoggingService().get_logger(__name__)
        
        # 파일 정보
        self.file_path = file_path
        self.is_image_sequence = '%' in file_path
        self.is_single_image = not self.is_image_sequence and file_path.lower().endswith(
            ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
        )
        
        # 비디오 정보
        self.width = 0
        self.height = 0
        self.fps = 0
        self.frame_count = 0
        self.duration = 0
        
        # 재생 제어
        self._state = VideoThreadState.STOPPED
        self.running = False     # 스레드 실행 상태
        self.seek_requested = False
        self.seek_frame = 0
        self.current_frame = 1  # 1-based 인덱스
        self.speed = 1.0
        self.is_completed = False
        self.process = None
        
        # 동기화 객체
        self.mutex = QMutex()
        self.seek_mutex = QMutex()
        self.condition = QWaitCondition()
        
        # 이미지 시퀀스 캐싱 관련 변수
        self.image_cache = {}
        self.cache_size = 30  # 캐시할 최대 이미지 수
        self.preload_count = 10  # 미리 로드할 이미지 수
        self.image_queue = queue.Queue(maxsize=self.preload_count)
        self.thread_pool = None  # 초기화 시점에는 None으로 설정
        
        # 다운샘플링 관련 변수
        self.preview_mode = False  # 미리보기 모드 (저해상도)
        self.preview_scale = 0.5  # 미리보기 스케일 (50%)
        self.target_width = 0
        self.target_height = 0
        
        # 이미지 시퀀스 처리를 위한 설정
        self.preload_executor = ThreadPoolExecutor(max_workers=4)
        self.preload_futures = []
        
        # 비디오 정보 초기화
        self._initialize_video_info()
    
    @property
    def state(self) -> VideoThreadState:
        """현재 상태 반환"""
        return self._state
    
    @state.setter
    def state(self, new_state: VideoThreadState):
        """상태 설정 및 시그널 발생"""
        if self._state != new_state:
            old_state = self._state
            self._state = new_state
            
            # 상태 변경 로깅
            self.logger.debug(f"비디오 스레드 상태 변경: {old_state.name} -> {new_state.name}")
            
            # 상태 변경 시그널 발생
            self.state_changed.emit(new_state)
    
    def get_video_properties(self, input_file: str) -> Dict[str, str]:
        """
        비디오 파일의 속성을 가져옵니다.
        
        Args:
            input_file: 비디오 파일 경로
            
        Returns:
            비디오 속성 딕셔너리
        """
        try:
            # FFprobe 경로 확인
            ffprobe_path = self.ffmpeg_manager.get_ffprobe_path()
            if not ffprobe_path:
                self.logger.error("FFprobe 경로가 설정되지 않았습니다.")
                return {}
            
            self.logger.debug(f"비디오 속성 가져오기: {input_file}")
                
            # FFprobe 명령 실행
            cmd = [
                ffprobe_path,
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,r_frame_rate,duration,nb_frames',
                '-of', 'default=noprint_wrappers=1:nokey=0',
                input_file
            ]
            
            self.logger.debug(f"FFprobe 명령: {' '.join(cmd)}")
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.logger.error(f"FFprobe 실행 실패: {result.stderr}")
                return {}
                
            # 출력 파싱
            properties = {}
            for line in result.stdout.splitlines():
                if '=' in line:
                    key, value = line.split('=', 1)
                    properties[key.strip()] = value.strip()
            
            # 프레임레이트 계산 (분수 형태로 반환될 수 있음)
            if 'r_frame_rate' in properties:
                try:
                    num, den = map(int, properties['r_frame_rate'].split('/'))
                    properties['fps'] = num / den
                except (ValueError, ZeroDivisionError):
                    properties['fps'] = 30  # 기본값
            
            self.logger.debug(f"비디오 속성: {properties}")
            return properties
            
        except Exception as e:
            self.logger.exception(f"비디오 속성 가져오기 실패: {e}")
            return {}
    
    def get_fallback_properties(self) -> Dict[str, str]:
        """
        기본 속성을 반환합니다.
        
        Returns:
            기본 비디오 속성 딕셔너리
        """
        return {
            'width': 1920,
            'height': 1080,
            'fps': 30,
            'duration': 0,
            'nb_frames': 0
        }
    
    def process_image_sequence(self):
        """이미지 시퀀스 처리"""
        try:
            # 이미지 시퀀스 패턴에서 파일 목록 가져오기
            import glob
            pattern = re.sub(r'%\d*d', '*', self.file_path)
            image_files = sorted(glob.glob(pattern))
            
            if not image_files:
                self.logger.error(f"이미지 시퀀스를 찾을 수 없습니다: {pattern}")
                return
                
            # 첫 번째 이미지로 크기 설정
            first_image = Image.open(image_files[0])
            self.width, self.height = first_image.size
            self.fps = 30  # 기본 프레임레이트
            self.frame_count = len(image_files)
            self.duration = self.frame_count / self.fps
            
            # 비디오 정보 시그널 발생
            self.video_info_ready.emit(self.width, self.height)
            
            # 이미지 시퀀스 처리 함수 호출
            self.process_image_sequence_frames()
            
        except Exception as e:
            self.logger.exception(f"이미지 시퀀스 처리 실패: {e}")
    
    def process_fallback(self):
        """단일 이미지 파일 처리"""
        try:
            # 이미지 파일 로드
            image = Image.open(self.file_path)
            self.width, self.height = image.size
            self.fps = 1  # 단일 이미지는 1fps로 설정
            self.frame_count = 1
            self.duration = 1
            
            # 비디오 정보 시그널 발생
            self.video_info_ready.emit(self.width, self.height)
            
            # 이미지를 QPixmap으로 변환하여 시그널 발생
            img_bytes = io.BytesIO()
            image.save(img_bytes, format='PNG')
            img_data = img_bytes.getvalue()
            
            q_image = QImage.fromData(img_data)
            pixmap = QPixmap.fromImage(q_image)
            
            self.frame_ready.emit(pixmap)
            
        except Exception as e:
            self.logger.exception(f"이미지 처리 실패: {e}")
    
    def get_image_size(self, file_path):
        """PIL을 사용하여 이미지 크기 가져오기"""
        with Image.open(file_path) as img:
            return img.size
    
    def run(self):
        """스레드 실행"""
        try:
            self.running = True
            self.state = VideoThreadState.PLAYING
            self.is_completed = False  # 재생 시작 시 완료 상태 초기화
            
            self.logger.debug("===== 비디오 스레드 실행 시작 =====")
            
            try:
                if self.is_single_image:
                    # 단일 이미지 처리
                    self.logger.debug("단일 이미지 처리 시작")
                    self.process_fallback()
                elif self.is_image_sequence:
                    # 이미지 시퀀스 처리
                    self.logger.debug("이미지 시퀀스 처리 시작")
                    self.process_image_sequence()
                else:
                    # 비디오 파일 처리
                    self.logger.debug("비디오 파일 처리 시작")
                    # 비디오 속성 가져오기
                    properties = self.get_video_properties(self.file_path)
                    
                    if not properties:
                        self.logger.warning(f"비디오 속성을 가져올 수 없습니다: {self.file_path}")
                        properties = self.get_fallback_properties()
                    
                    # 비디오 정보 설정
                    self.width = int(properties.get('width', 1920))
                    self.height = int(properties.get('height', 1080))
                    self.fps = float(properties.get('fps', 30))
                    self.duration = float(properties.get('duration', 0))
                    
                    # nb_frames를 직접 사용하여 총 프레임 수 계산
                    if 'nb_frames' in properties and properties['nb_frames'] != 'N/A' and int(properties.get('nb_frames', 0)) > 0:
                        self.frame_count = int(properties['nb_frames'])
                        self.logger.debug(f"nb_frames 정보 사용: {self.frame_count}프레임")
                    else:
                        # nb_frames가 없는 경우에만 duration * fps 사용
                        if self.duration > 0 and self.fps > 0:
                            self.frame_count = int(self.duration * self.fps)
                            self.logger.warning(f"nb_frames 정보가 없어 duration * fps로 계산: {self.duration} * {self.fps} = {self.frame_count}")
                    
                    # 비디오 정보 시그널 발생
                    self.video_info_ready.emit(self.width, self.height)
                    
                    # 비디오 프레임 처리 함수 호출
                    self.process_video_frames()
            
            except Exception as e:
                self.logger.exception(f"비디오 처리 실패: {e}")
                self.state = VideoThreadState.ERROR
            
            self.logger.debug("===== 비디오 스레드 실행 종료 =====")
        except Exception as e:
            self.logger.error(f"비디오 스레드 run() 메서드에서 예외 발생: {str(e)}", exc_info=True)
        finally:
            try:
                self.running = False
                self.state = VideoThreadState.STOPPED
                self.finished.emit()
            except Exception as e:
                self.logger.error(f"비디오 스레드 종료 처리 중 오류: {str(e)}", exc_info=True)
    
    def process_image_sequence_frames(self):
        """이미지 시퀀스 프레임 처리 - 최적화 버전"""
        try:
            # 이미지 시퀀스 패턴에서 파일 목록 가져오기
            import glob
            pattern = re.sub(r'%\d*d', '*', self.file_path)
            image_files = sorted(glob.glob(pattern))
            
            if not image_files:
                self.logger.error(f"이미지 시퀀스를 찾을 수 없습니다: {pattern}")
                return
            
            # 스레드 풀 생성 (실행 시점에 생성)
            if self.thread_pool is None or self.thread_pool._shutdown:
                self.thread_pool = ThreadPoolExecutor(max_workers=4)
                self.logger.debug("새 스레드 풀 생성")
            
            # 이미지 로딩 스레드 시작
            self.start_preloading(image_files)
            
            # 각 이미지 파일 처리
            # 1-based에서 0-based로 변환 (current_frame은 1-based)
            i = max(0, self.current_frame - 1)
            
            while i < len(image_files) and self.running:
                # 프레임 탐색 요청 확인
                self.seek_mutex.lock()
                if self.seek_requested:
                    # 1-based에서 0-based로 변환
                    i = min(self.seek_frame - 1, len(image_files) - 1)
                    i = max(0, i)  # 음수 방지
                    self.current_frame = i + 1  # 0-based에서 1-based로 변환하여 저장
                    self.seek_requested = False
                    self.frame_changed.emit(self.current_frame)
                    
                    # 캐시 및 큐 초기화
                    with self.image_queue.mutex:
                        self.image_queue.queue.clear()
                    
                    # 새 위치에서 프리로딩 시작
                    self.start_preloading(image_files, start_idx=i)
                self.seek_mutex.unlock()
                
                # 일시 정지 처리
                self.mutex.lock()
                if self.state == VideoThreadState.PAUSED:
                    self.condition.wait(self.mutex)
                self.mutex.unlock()
                
                # 이미지 로드 및 처리
                try:
                    # 캐시에서 이미지 확인
                    pixmap = None
                    if i in self.image_cache:
                        pixmap = self.image_cache[i]
                        self.logger.debug(f"캐시에서 이미지 사용: {i}")
                    else:
                        # 큐에서 이미지 가져오기 시도
                        try:
                            frame_idx, pixmap = self.image_queue.get(block=False)
                            if frame_idx == i:
                                self.logger.debug(f"큐에서 이미지 사용: {i}")
                                # 캐시에 저장
                                self.update_cache(i, pixmap)
                            else:
                                # 큐에서 가져온 이미지가 현재 필요한 프레임이 아님
                                self.image_queue.put((frame_idx, pixmap))
                                pixmap = None
                        except queue.Empty:
                            pixmap = None
                    
                    # 캐시나 큐에 없으면 직접 로드
                    if pixmap is None:
                        self.logger.debug(f"이미지 직접 로드: {i}")
                        # 미리보기 모드 사용 (타겟 크기에 맞게 리사이징)
                        pixmap = self.load_image(image_files[i], True)
                        # 캐시에 저장
                        self.update_cache(i, pixmap)
                    
                    # 프레임 시그널 발생 (이미 리사이징된 이미지이므로 추가 리사이징 불필요)
                    if pixmap and not pixmap.isNull():
                        self.frame_ready.emit(pixmap)
                    
                    # 현재 프레임 업데이트 (0-based에서 1-based로 변환)
                    self.current_frame = i + 1
                    self.frame_changed.emit(self.current_frame)
                    
                    # 다음 프레임 미리 로드 요청 (더 많은 프레임을 미리 로드)
                    for offset in range(1, min(5, self.preload_count)):
                        next_preload_idx = i + offset
                        if next_preload_idx < len(image_files):
                            self.preload_image(image_files[next_preload_idx], next_preload_idx)
                    
                    # 재생 속도에 따른 대기
                    if self.speed > 0:
                        time.sleep(1 / (self.fps * self.speed))
                    
                    # 다음 프레임으로 이동
                    i += 1
                    
                    # 마지막 프레임 도달 확인
                    if i >= len(image_files):
                        self.logger.debug("이미지 시퀀스 마지막 프레임 도달")
                        self.is_completed = True
                        self.playback_completed.emit()
                        break
                    
                except Exception as e:
                    self.logger.warning(f"이미지 파일 처리 실패: {image_files[i]} - {e}")
                    i += 1
                    continue
        
        except Exception as e:
            self.logger.exception(f"이미지 시퀀스 프레임 처리 실패: {e}")
        
        finally:
            # 스레드 풀 종료 (여기서는 종료하지 않음)
            # 스레드 풀은 stop() 메서드에서만 종료
            pass
    
    def load_image(self, file_path, preview_mode=False):
        """이미지 파일 로드 및 QPixmap으로 변환"""
        try:
            image = Image.open(file_path)
            
            # 미리보기 모드인 경우 타겟 크기에 맞게 리사이징
            if preview_mode and hasattr(self, 'target_width') and hasattr(self, 'target_height'):
                # 원본 이미지 크기
                orig_width, orig_height = image.size
                
                # 종횡비 계산
                aspect_ratio = orig_width / orig_height
                
                # 타겟 종횡비 계산
                target_aspect_ratio = self.target_width / self.target_height
                
                # 종횡비에 따라 리사이즈 크기 결정
                if aspect_ratio > target_aspect_ratio:
                    # 너비에 맞춤
                    new_width = self.target_width
                    new_height = int(new_width / aspect_ratio)
                else:
                    # 높이에 맞춤
                    new_height = self.target_height
                    new_width = int(new_height * aspect_ratio)
                
                # 이미지 리사이즈 (LANCZOS는 고품질이지만 BILINEAR가 더 빠름)
                image = image.resize((new_width, new_height), Image.BILINEAR)
                self.logger.debug(f"이미지 리사이즈: {orig_width}x{orig_height} -> {new_width}x{new_height}")
            elif preview_mode:
                # 타겟 크기가 설정되지 않은 경우 기본 스케일 사용
                new_width = int(image.width * self.preview_scale)
                new_height = int(image.height * self.preview_scale)
                image = image.resize((new_width, new_height), Image.BILINEAR)
            
            # 알파 채널이 있는 경우 RGB로 변환 (알파 채널 제거)
            if image.mode == 'RGBA':
                # 배경색 설정 (검은색)
                background = Image.new('RGB', image.size, (0, 0, 0))
                # 알파 채널을 고려하여 합성
                background.paste(image, mask=image.split()[3])  # 3번 채널이 알파 채널
                image = background
                self.logger.debug("알파 채널 제거 후 RGB로 변환")
            
            # 이미지를 QPixmap으로 변환
            img_bytes = io.BytesIO()
            # JPEG 포맷으로 저장 (모든 이미지)
            image.save(img_bytes, format='JPEG', quality=90)
            img_data = img_bytes.getvalue()
            
            q_image = QImage.fromData(img_data)
            return QPixmap.fromImage(q_image)
            
        except Exception as e:
            self.logger.warning(f"이미지 로드 실패: {file_path} - {e}")
            return None
    
    def preload_image(self, file_path, frame_idx):
        """비동기적으로 이미지 미리 로드"""
        if frame_idx in self.image_cache:
            return  # 이미 캐시에 있으면 로드하지 않음
            
        # 이미 큐에 있는지 확인
        for idx, _ in list(self.image_queue.queue):
            if idx == frame_idx:
                return
                
        # 스레드 풀이 종료되었는지 확인
        if self.thread_pool is None or self.thread_pool._shutdown:
            self.thread_pool = ThreadPoolExecutor(max_workers=4)
            self.logger.debug("새 스레드 풀 생성 (preload_image)")
            
        # 비동기로 이미지 로드
        try:
            future = self.thread_pool.submit(self.load_image, file_path, self.preview_mode)
            future.add_done_callback(lambda f: self.on_image_loaded(f, frame_idx))
        except RuntimeError as e:
            # 스레드 풀 오류 처리
            self.logger.warning(f"스레드 풀 오류: {e}, 동기적으로 이미지 로드")
            # 동기적으로 이미지 로드 (대체 방법)
            pixmap = self.load_image(file_path, self.preview_mode)
            if pixmap and not pixmap.isNull():
                self.update_cache(frame_idx, pixmap)
    
    def on_image_loaded(self, future, frame_idx):
        """이미지 로드 완료 콜백"""
        try:
            pixmap = future.result()
            if pixmap and not pixmap.isNull():
                try:
                    # 큐가 가득 차 있으면 가장 오래된 항목 제거
                    if self.image_queue.full():
                        try:
                            self.image_queue.get_nowait()
                        except queue.Empty:
                            pass
                    
                    # 새 이미지 추가
                    self.image_queue.put((frame_idx, pixmap))
                except Exception as e:
                    self.logger.warning(f"이미지 큐 추가 실패: {e}")
        except Exception as e:
            self.logger.warning(f"이미지 로드 콜백 실패: {e}")
    
    def update_cache(self, frame_idx, pixmap):
        """이미지 캐시 업데이트"""
        # 캐시 크기 제한
        if len(self.image_cache) >= self.cache_size:
            # 가장 오래된 항목 제거 (가장 작은 인덱스)
            oldest_key = min(self.image_cache.keys())
            del self.image_cache[oldest_key]
        
        # 새 이미지 캐싱
        self.image_cache[frame_idx] = pixmap
    
    def start_preloading(self, image_files, start_idx=0):
        """이미지 프리로딩 시작"""
        # 캐시 초기화
        self.image_cache.clear()
        
        # 큐 초기화
        with self.image_queue.mutex:
            self.image_queue.queue.clear()
        
        # 스레드 풀이 종료되었는지 확인
        if self.thread_pool is None or self.thread_pool._shutdown:
            self.thread_pool = ThreadPoolExecutor(max_workers=4)
            self.logger.debug("새 스레드 풀 생성 (start_preloading)")
        
        # 미리 로드할 이미지 범위 계산
        end_idx = min(start_idx + self.preload_count, len(image_files))
        
        # 비동기로 이미지 로드
        for i in range(start_idx, end_idx):
            self.preload_image(image_files[i], i)
    
    def set_preview_mode(self, enabled, scale=0.5):
        """미리보기 모드 설정"""
        self.preview_mode = enabled
        self.preview_scale = scale
        
        # 캐시 초기화 (해상도가 변경되므로)
        self.image_cache.clear()
        
        # 큐 초기화
        with self.image_queue.mutex:
            self.image_queue.queue.clear()
    
    def set_target_size(self, width, height):
        """미리보기 타겟 크기 설정"""
        # 최소 크기 제한 (너무 작은 이미지는 성능 이점이 적음)
        self.target_width = max(width, 320)
        self.target_height = max(height, 240)
        self.logger.debug(f"미리보기 타겟 크기 설정: {self.target_width}x{self.target_height}")
        
        # 캐시 초기화 (해상도가 변경되므로)
        self.image_cache.clear()
        
        # 큐 초기화
        with self.image_queue.mutex:
            self.image_queue.queue.clear()
    
    def process_video_frames(self):
        """비디오 프레임 처리"""
        try:
            # FFmpeg 경로 확인
            ffmpeg_path = self.ffmpeg_manager.get_ffmpeg_path()
            if not ffmpeg_path:
                self.logger.error("FFmpeg 경로가 설정되지 않았습니다.")
                return
            
            # 현재 프레임부터 시작
            start_time = self.current_frame / self.fps if self.current_frame > 0 else 0
            
            # FFmpeg 명령 설정
            cmd = [
                ffmpeg_path,
                '-ss', str(start_time),
                '-i', self.file_path,
                '-f', 'image2pipe',
                '-pix_fmt', 'rgb24',
                '-vcodec', 'rawvideo',
                '-'
            ]
            
            # FFmpeg 프로세스 시작
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=10**8
            )
            
            # 프레임 크기 계산
            frame_size = self.width * self.height * 3  # RGB 3채널
            
            # 프레임 처리 루프
            frame_count = 0
            while self.running:
                # 프레임 탐색 요청 확인
                self.seek_mutex.lock()
                if self.seek_requested:
                    # 현재 프로세스 종료
                    if self.process:
                        self.process.terminate()
                    
                    # 새로운 시작 시간 계산
                    start_time = self.seek_frame / self.fps
                    
                    # 새 FFmpeg 프로세스 시작
                    cmd = [
                        ffmpeg_path,
                        '-ss', str(start_time),
                        '-i', self.file_path,
                        '-f', 'image2pipe',
                        '-pix_fmt', 'rgb24',
                        '-vcodec', 'rawvideo',
                        '-'
                    ]
                    
                    self.process = subprocess.Popen(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        bufsize=10**8
                    )
                    
                    # 현재 프레임 업데이트
                    self.current_frame = self.seek_frame
                    frame_count = 0
                    self.seek_requested = False
                    self.frame_changed.emit(self.current_frame)
                self.seek_mutex.unlock()
                
                # 일시 정지 처리
                self.mutex.lock()
                if self.state == VideoThreadState.PAUSED:
                    self.condition.wait(self.mutex)
                self.mutex.unlock()
                
                # 프레임 읽기
                in_bytes = self.process.stdout.read(frame_size)
                if not in_bytes:
                    # 재생 완료 상태 설정
                    self.is_completed = True
                    self.logger.debug("비디오 재생 완료됨")
                    # 재생 완료 시그널 발생
                    self.playback_completed.emit()
                    break
                
                # 프레임 처리
                self.process_frame(in_bytes)
                
                # 재생 속도에 따른 대기
                if self.speed > 0:
                    time.sleep(1 / (self.fps * self.speed))
                
                # 현재 프레임 업데이트
                frame_count += 1
                self.current_frame = self.current_frame + 1
                
                # 마지막 프레임인지 확인
                if self.frame_count > 0 and self.current_frame >= self.frame_count:
                    self.is_completed = True
                    self.logger.debug(f"마지막 프레임 도달: {self.current_frame}/{self.frame_count}")
                    # 재생 완료 시그널 발생
                    self.playback_completed.emit()
                
                self.frame_changed.emit(self.current_frame)
        
        except Exception as e:
            self.logger.exception(f"비디오 프레임 처리 실패: {e}")
        
        finally:
            # 프로세스 정리
            if self.process:
                self.process.terminate()
                self.process = None
    
    def process_frame(self, in_bytes):
        """프레임 데이터 처리"""
        try:
            # 바이트 데이터를 QImage로 변환
            image = QImage(
                in_bytes, self.width, self.height, 
                self.width * 3, QImage.Format_RGB888
            )
            
            # QImage를 QPixmap으로 변환
            pixmap = QPixmap.fromImage(image)
            
            # 프레임 시그널 발생
            self.frame_ready.emit(pixmap)
            
        except Exception as e:
            self.logger.warning(f"프레임 처리 실패: {e}")
    
    def stop(self):
        """비디오 재생 중지"""
        try:
            self.logger.debug("===== 비디오 스레드 중지 시작 =====")
            
            # 상태 확인
            self.logger.debug(f"현재 상태: {self.state.name}, 실행 중: {self.running}")
            
            # 이미 중지된 경우
            if not self.running and self.state == VideoThreadState.STOPPED:
                self.logger.debug("이미 중지된 상태입니다.")
                return
            
            # 상태 변경
            try:
                self.logger.debug("상태를 STOPPED로 변경")
                self.state = VideoThreadState.STOPPED
                self.running = False
            except Exception as e:
                self.logger.error(f"상태 변경 중 오류: {str(e)}")
            
            # 일시 정지 상태인 경우 해제
            try:
                self.logger.debug("뮤텍스 잠금 및 조건 변수 깨우기 시작")
                self.mutex.lock()
                self.condition.wakeAll()
                self.mutex.unlock()
                self.logger.debug("뮤텍스 잠금 및 조건 변수 깨우기 완료")
            except Exception as e:
                self.logger.error(f"뮤텍스/조건 변수 처리 중 오류: {str(e)}")
            
            # 프로세스 정리 - 핵심 수정 부분
            process_local = self.process  # 로컬 변수에 복사하여 안전하게 처리
            self.process = None  # 즉시 참조 제거
            
            if process_local:
                try:
                    self.logger.debug("FFmpeg 프로세스 종료 시작")
                    # 프로세스 상태 확인
                    poll_result = None
                    try:
                        poll_result = process_local.poll()
                        self.logger.debug(f"프로세스 상태: {poll_result}")
                    except Exception as e:
                        self.logger.error(f"프로세스 상태 확인 중 오류: {str(e)}")
                        poll_result = -1  # 오류 발생 시 이미 종료된 것으로 간주
                    
                    # None인 경우만 종료 시도 (아직 실행 중인 경우)
                    if poll_result is None:
                        try:
                            self.logger.debug("프로세스 terminate() 호출")
                            process_local.terminate()
                            
                            try:
                                self.logger.debug("프로세스 종료 대기 (최대 0.5초)")
                                # 대기 시간을 짧게 설정하여 블로킹 최소화
                                process_local.wait(timeout=0.5)
                                self.logger.debug("프로세스 정상 종료됨")
                            except subprocess.TimeoutExpired:
                                self.logger.warning("프로세스 종료 타임아웃")
                                # 강제 종료는 시도하지 않음 - 이 부분이 충돌의 원인일 수 있음
                        except Exception as e:
                            self.logger.error(f"프로세스 terminate() 실패: {str(e)}")
                    else:
                        self.logger.debug(f"프로세스가 이미 종료됨 (반환 코드: {poll_result})")
                    
                    self.logger.debug("FFmpeg 프로세스 참조 제거 완료")
                except Exception as e:
                    self.logger.error(f"프로세스 종료 중 오류: {str(e)}", exc_info=True)
            else:
                self.logger.debug("FFmpeg 프로세스가 없음")
            
            # 스레드 풀 정리
            thread_pool_local = None
            if hasattr(self, 'thread_pool') and self.thread_pool:
                thread_pool_local = self.thread_pool
                self.thread_pool = None  # 참조 즉시 제거
                
            if thread_pool_local:
                try:
                    if not thread_pool_local._shutdown:
                        self.logger.debug("스레드 풀 종료 시작")
                        thread_pool_local.shutdown(wait=False)
                        self.logger.debug("스레드 풀 종료 완료")
                    else:
                        self.logger.debug("스레드 풀이 이미 종료됨")
                except Exception as e:
                    self.logger.error(f"스레드 풀 종료 중 오류: {str(e)}")
            
            # 이미지 캐시 및 큐 정리
            try:
                self.logger.debug("이미지 캐시 및 큐 정리 시작")
                if hasattr(self, 'image_cache'):
                    cache_size = len(self.image_cache)
                    self.image_cache.clear()
                    self.logger.debug(f"이미지 캐시 정리됨 (항목 수: {cache_size})")
                
                if hasattr(self, 'image_queue') and hasattr(self.image_queue, 'mutex'):
                    queue_size = 0
                    try:
                        queue_size = self.image_queue.qsize()
                    except:
                        pass
                    
                    try:
                        with self.image_queue.mutex:
                            self.image_queue.queue.clear()
                    except Exception as e:
                        self.logger.error(f"이미지 큐 정리 중 오류: {str(e)}")
                    
                    self.logger.debug(f"이미지 큐 정리됨 (항목 수: {queue_size})")
                self.logger.debug("이미지 캐시 및 큐 정리 완료")
            except Exception as e:
                self.logger.error(f"캐시/큐 정리 중 오류: {str(e)}")
            
            self.logger.debug("===== 비디오 스레드 중지 완료 =====")
        except Exception as e:
            self.logger.error(f"비디오 스레드 중지 전체 과정에서 오류 발생: {str(e)}", exc_info=True)
    
    def reset(self):
        """스레드 리셋"""
        self.stop()
        self.current_frame = 0
        self.speed = 1.0
    
    def set_speed(self, speed: float):
        """재생 속도 설정"""
        if speed > 0:
            self.speed = speed
            self.logger.debug(f"재생 속도 설정: {speed}x")
    
    def get_video_info(self):
        """비디오 정보 반환"""
        # 비디오 정보가 아직 설정되지 않은 경우 가져오기
        if self.width == 0 or self.height == 0 or self.fps == 0:
            self.logger.debug("비디오 정보 초기화 필요")
            
            if self.is_single_image:
                # 단일 이미지 처리
                try:
                    image = Image.open(self.file_path)
                    self.width, self.height = image.size
                    self.fps = 1  # 단일 이미지는 1fps로 설정
                    self.frame_count = 1
                    self.duration = 1
                    self.logger.debug(f"단일 이미지 정보: {self.width}x{self.height}")
                except Exception as e:
                    self.logger.error(f"이미지 정보 가져오기 실패: {e}")
            
            elif self.is_image_sequence:
                # 이미지 시퀀스 처리
                try:
                    pattern = re.sub(r'%\d*d', '*', self.file_path)
                    image_files = sorted(glob.glob(pattern))
                    
                    if image_files:
                        first_image = Image.open(image_files[0])
                        self.width, self.height = first_image.size
                        self.fps = 30  # 기본 프레임레이트
                        self.frame_count = len(image_files)
                        self.duration = self.frame_count / self.fps
                        self.logger.debug(f"이미지 시퀀스 정보: {self.width}x{self.height}, {self.frame_count} 프레임")
                    else:
                        self.logger.error(f"이미지 시퀀스를 찾을 수 없습니다: {pattern}")
                except Exception as e:
                    self.logger.error(f"이미지 시퀀스 정보 가져오기 실패: {e}")
            
            else:
                # 비디오 파일 처리
                properties = self.get_video_properties(self.file_path)
                
                if properties:
                    self.width = int(properties.get('width', 1920))
                    self.height = int(properties.get('height', 1080))
                    self.fps = float(properties.get('fps', 30))
                    self.duration = float(properties.get('duration', 0))
                    
                    # nb_frames를 직접 사용하여 총 프레임 수 계산
                    if 'nb_frames' in properties and properties['nb_frames'] != 'N/A' and int(properties.get('nb_frames', 0)) > 0:
                        self.frame_count = int(properties['nb_frames'])
                        self.logger.debug(f"nb_frames 정보 사용: {self.frame_count}프레임")
                    else:
                        # nb_frames가 없는 경우에만 duration * fps 사용
                        if self.duration > 0 and self.fps > 0:
                            self.frame_count = int(self.duration * self.fps)
                            self.logger.warning(f"nb_frames 정보가 없어 duration * fps로 계산: {self.duration} * {self.fps} = {self.frame_count}")
                    
                    self.logger.debug(f"비디오 정보: {self.width}x{self.height}, {self.frame_count} 프레임, {self.fps} fps")
                else:
                    # 정보를 가져올 수 없는 경우 기본값 사용
                    fallback = self.get_fallback_properties()
                    self.width = int(fallback.get('width', 1920))
                    self.height = int(fallback.get('height', 1080))
                    self.fps = float(fallback.get('fps', 30))
                    self.duration = float(fallback.get('duration', 0))
                    self.frame_count = int(fallback.get('nb_frames', 0))
                    self.logger.warning(f"비디오 정보를 가져올 수 없어 기본값 사용: {self.width}x{self.height}")
        
        # 비디오 정보 반환
        info = {
            'width': self.width,
            'height': self.height,
            'fps': self.fps,
            'duration': self.duration,
            'frame_count': self.frame_count
        }
        
        self.logger.debug(f"비디오 정보 반환: {info}")
        return info
    
    def get_video_frame(self, frame_number):
        """특정 프레임 가져오기"""
        try:
            # 프레임 번호 유효성 검사
            if frame_number < 0:
                self.logger.warning(f"유효하지 않은 프레임 번호: {frame_number}, 0으로 설정")
                frame_number = 0
            
            if self.frame_count > 0 and frame_number >= self.frame_count:
                self.logger.warning(f"프레임 번호가 총 프레임 수를 초과합니다: {frame_number} >= {self.frame_count}, 마지막 프레임으로 설정")
                frame_number = self.frame_count - 1
            
            # FFmpeg 경로 확인
            ffmpeg_path = self.ffmpeg_manager.get_ffmpeg_path()
            if not ffmpeg_path:
                self.logger.error("FFmpeg 경로가 설정되지 않았습니다.")
                return None
            
            self.logger.debug(f"프레임 가져오기: {frame_number}")
            
            # 이미지 시퀀스인 경우
            if self.is_image_sequence:
                import glob
                pattern = re.sub(r'%\d*d', '*', self.file_path)
                image_files = sorted(glob.glob(pattern))
                
                if not image_files:
                    self.logger.warning(f"이미지 시퀀스를 찾을 수 없습니다: {pattern}")
                    return None
                
                # 프레임 번호 조정
                if frame_number >= len(image_files):
                    self.logger.warning(f"프레임 번호가 이미지 파일 수를 초과합니다: {frame_number} >= {len(image_files)}")
                    frame_number = len(image_files) - 1
                
                # 해당 프레임의 이미지 파일 로드
                self.logger.debug(f"이미지 시퀀스 프레임 로드: {image_files[frame_number]}")
                
                # 미리보기 모드 사용 (타겟 크기에 맞게 리사이징)
                return self.load_image(image_files[frame_number], True)
            
            # 단일 이미지인 경우
            elif self.is_single_image:
                self.logger.debug(f"단일 이미지 로드: {self.file_path}")
                return self.load_image(self.file_path, True)
            
            # 비디오 파일인 경우
            else:
                # 비디오 정보 확인
                if self.width <= 0 or self.height <= 0 or self.fps <= 0:
                    self.logger.warning("비디오 정보가 유효하지 않습니다. 정보를 다시 가져옵니다.")
                    video_info = self.get_video_info()
                
                # 프레임 시간 계산 (0-based 인덱스로 변환)
                if frame_number == 0:
                    frame_time = 0.0
                    self.logger.debug("첫 프레임 가져오기 (0초)")
                else:
                    # 1-based에서 0-based로 변환하여 시간 계산
                    frame_time = frame_number / self.fps
                    self.logger.debug(f"비디오 프레임 시간: {frame_time:.3f}초 (프레임 {frame_number})")
                
                # FFmpeg 명령 설정
                command = [
                    ffmpeg_path,
                    "-ss", f"{frame_time:.3f}",
                    "-i", self.file_path,
                    "-vframes", "1",
                    "-f", "image2pipe",
                    "-pix_fmt", "rgb24",
                    "-vcodec", "rawvideo",
                    "-v", "quiet",
                    "-"
                ]
                
                self.logger.debug(f"FFmpeg 명령: {' '.join(command)}")
                
                # FFmpeg 프로세스 실행
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=10**8
                )
                
                # 출력 데이터 읽기
                out, err = process.communicate()
                
                if process.returncode != 0:
                    self.logger.error(f"FFmpeg 오류: {err.decode()}")
                    return None
                
                if not out:
                    self.logger.error("FFmpeg에서 데이터를 받지 못했습니다.")
                    return None
                
                # 바이트 데이터를 이미지로 변환
                try:
                    # 이미지 크기 계산
                    img_size = self.width * self.height * 3  # RGB
                    
                    if len(out) < img_size:
                        self.logger.error(f"불완전한 이미지 데이터: {len(out)} < {img_size}")
                        return None
                    
                    # 바이트 데이터를 numpy 배열로 변환
                    img_array = np.frombuffer(out, dtype=np.uint8)
                    img_array = img_array[:img_size].reshape((self.height, self.width, 3))
                    
                    # OpenCV BGR에서 RGB로 변환
                    img_array = cv2.cvtColor(img_array, cv2.COLOR_BGR2RGB)
                    
                    # numpy 배열을 QImage로 변환
                    q_img = QImage(img_array.data, self.width, self.height, self.width * 3, QImage.Format_RGB888)
                    
                    # QImage를 QPixmap으로 변환
                    pixmap = QPixmap.fromImage(q_img)
                    
                    return pixmap
                except Exception as e:
                    self.logger.error(f"이미지 변환 중 오류: {str(e)}")
                    return None
        except Exception as e:
            self.logger.error(f"프레임 가져오기 중 오류: {str(e)}")
            return None
    
    def resize_image(self, img, target_width, target_height):
        """이미지의 종횡비 유지하면서 리사이즈"""
        width, height = img.size
        
        # 종횡비 계산
        aspect_ratio = width / height
        
        # 타겟 종횡비 계산
        target_aspect_ratio = target_width / target_height
        
        # 종횡비에 따라 리사이즈 크기 결정
        if aspect_ratio > target_aspect_ratio:
            # 너비에 맞춤
            new_width = target_width
            new_height = int(new_width / aspect_ratio)
        else:
            # 높이에 맞춤
            new_height = target_height
            new_width = int(new_height * aspect_ratio)
        
        # 이미지 리사이즈
        resized_img = img.resize((new_width, new_height), Image.LANCZOS)
        
        # 검은색 배경 생성
        background = Image.new('RGB', (target_width, target_height), (0, 0, 0))
        
        # 이미지를 중앙에 배치
        offset = ((target_width - new_width) // 2, (target_height - new_height) // 2)
        background.paste(resized_img, offset)
        
        return background
    
    def resize_frame(self, frame, target_width, target_height):
        """프레임의 종횡비 유지하면서 리사이즈"""
        # QPixmap을 QImage로 변환
        image = frame.toImage()
        
        # QImage를 PIL Image로 변환
        buffer = QImage.bits(image)
        buffer.setsize(image.byteCount())
        
        pil_image = Image.frombuffer(
            'RGB',
            (image.width(), image.height()),
            buffer,
            'raw',
            'BGRA' if image.format() == QImage.Format_ARGB32 else 'BGR',
            0, 1
        )
        
        # 이미지 리사이즈
        resized_image = self.resize_image(pil_image, target_width, target_height)
        
        # PIL Image를 QPixmap으로 변환
        img_bytes = io.BytesIO()
        resized_image.save(img_bytes, format='PNG')
        img_data = img_bytes.getvalue()
        
        q_image = QImage.fromData(img_data)
        return QPixmap.fromImage(q_image)

    def seek_to_frame(self, frame_number: int):
        """
        특정 프레임으로 이동
        
        Args:
            frame_number (int): 이동할 프레임 번호 (1-based, 타임라인과 일치)
        """
        # 유효성 검사 (1-based 인덱스 기준)
        if frame_number < 1 or (self.frame_count > 0 and frame_number > self.frame_count):
            self.logger.warning(f"유효하지 않은 프레임 번호: {frame_number}")
            return
        
        self.logger.debug(f"프레임 탐색 요청: {frame_number} (1-based)")
        
        # 내부적으로 0-based 인덱스 사용
        zero_based_frame = frame_number - 1
        
        self.seek_mutex.lock()
        self.seek_requested = True
        self.seek_frame = frame_number  # 1-based 인덱스 저장
        self.seek_mutex.unlock()
        
        # 재생 중이 아니면 직접 프레임 가져와서 표시
        if not self.is_playing or not self.isRunning():
            self.logger.debug(f"재생 중이 아님, 직접 프레임 가져오기: {frame_number} (1-based)")
            # 0-based 인덱스로 프레임 가져오기
            pixmap = self.get_video_frame(zero_based_frame)
            if pixmap and not pixmap.isNull():
                self.frame_ready.emit(pixmap)
                self.current_frame = frame_number  # 1-based 인덱스 저장
                self.frame_changed.emit(frame_number)  # 1-based 인덱스 전달
            else:
                self.logger.warning(f"프레임을 가져올 수 없음: {frame_number} (1-based)")
        
        # 일시 정지 상태인 경우 깨우기
        self.mutex.lock()
        if self.state == VideoThreadState.PAUSED:
            self.logger.debug("일시 정지 상태에서 깨우기")
            self.condition.wakeAll()
        self.mutex.unlock()
    
    def toggle_pause(self):
        """
        일시 정지/재생 토글
        
        Returns:
            bool: 재생 중이면 True, 일시 정지면 False 반환
        """
        self.mutex.lock()
        
        # 현재 상태에 따라 새 상태 결정
        if self.state == VideoThreadState.PLAYING:
            self.state = VideoThreadState.PAUSED
        elif self.state == VideoThreadState.PAUSED:
            self.state = VideoThreadState.PLAYING
            self.condition.wakeAll()  # 일시 정지 해제 시 스레드 깨우기
        
        self.mutex.unlock()
        
        # 재생 중이면 True, 일시 정지면 False 반환
        return self.state == VideoThreadState.PLAYING

    def _initialize_video_info(self):
        """비디오 정보 초기화"""
        if self.is_single_image:
            # 단일 이미지 처리
            try:
                image = Image.open(self.file_path)
                self.width, self.height = image.size
                self.fps = 1  # 단일 이미지는 1fps로 설정
                self.frame_count = 1
                self.duration = 1
                self.logger.debug(f"단일 이미지 정보: {self.width}x{self.height}")
            except Exception as e:
                self.logger.error(f"이미지 정보 가져오기 실패: {e}")
        
        elif self.is_image_sequence:
            # 이미지 시퀀스 처리
            try:
                pattern = re.sub(r'%\d*d', '*', self.file_path)
                image_files = sorted(glob.glob(pattern))
                
                if image_files:
                    first_image = Image.open(image_files[0])
                    self.width, self.height = first_image.size
                    self.fps = 30  # 기본 프레임레이트
                    self.frame_count = len(image_files)
                    self.duration = self.frame_count / self.fps
                    self.logger.debug(f"이미지 시퀀스 정보: {self.width}x{self.height}, {self.frame_count} 프레임")
                else:
                    self.logger.error(f"이미지 시퀀스를 찾을 수 없습니다: {pattern}")
            except Exception as e:
                self.logger.error(f"이미지 시퀀스 정보 가져오기 실패: {e}")
        
        else:
            # 비디오 파일 처리
            properties = self.get_video_properties(self.file_path)
            
            if properties:
                self.width = int(properties.get('width', 1920))
                self.height = int(properties.get('height', 1080))
                self.fps = float(properties.get('fps', 30))
                self.duration = float(properties.get('duration', 0))
                
                # nb_frames를 직접 사용하여 총 프레임 수 계산
                if 'nb_frames' in properties and properties['nb_frames'] != 'N/A' and int(properties.get('nb_frames', 0)) > 0:
                    self.frame_count = int(properties['nb_frames'])
                    self.logger.debug(f"nb_frames 정보 사용: {self.frame_count}프레임")
                else:
                    # nb_frames가 없는 경우에만 duration * fps 사용
                    if self.duration > 0 and self.fps > 0:
                        self.frame_count = int(self.duration * self.fps)
                        self.logger.warning(f"nb_frames 정보가 없어 duration * fps로 계산: {self.duration} * {self.fps} = {self.frame_count}")
                    
                self.logger.debug(f"비디오 정보: {self.width}x{self.height}, {self.frame_count} 프레임, {self.fps} fps")
            else:
                # 정보를 가져올 수 없는 경우 기본값 사용
                fallback = self.get_fallback_properties()
                self.width = int(fallback.get('width', 1920))
                self.height = int(fallback.get('height', 1080))
                self.fps = float(fallback.get('fps', 30))
                self.duration = float(fallback.get('duration', 0))
                self.frame_count = int(fallback.get('nb_frames', 0))
                self.logger.warning(f"비디오 정보를 가져올 수 없어 기본값 사용: {self.width}x{self.height}")


