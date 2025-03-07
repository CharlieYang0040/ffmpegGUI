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
from typing import Dict, Optional, Tuple
import time
from app.utils.utils import get_debug_mode
import io
import re

# 로깅 서비스 가져오기
from app.services.logging_service import LoggingService

# FFmpegManager 싱글톤 가져오기
from app.core.ffmpeg_manager import FFmpegManager

# 로깅 설정
logger = LoggingService().get_logger(__name__)

# FFmpeg 경로를 전역 변수로 설정
FFMPEG_PATH = None
FFPROBE_PATH = None

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
        
        self.file_path = file_path
        self.running = False
        self.paused = False
        self.mutex = QMutex()
        self.condition = QWaitCondition()
        self.speed = 1.0
        self.process = None
        self.width = 0
        self.height = 0
        self.fps = 0
        self.duration = 0
        self.frame_count = 0
        self.current_frame = 0
        self.is_image_sequence = '%' in file_path
        self.is_single_image = not self.is_image_sequence and file_path.lower().endswith(
            ('.jpg', '.jpeg', '.png', '.bmp', '.webp')
        )
    
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
                
            # FFprobe 명령 실행
            cmd = [
                ffprobe_path,
                '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,r_frame_rate,duration,nb_frames',
                '-of', 'default=noprint_wrappers=1:nokey=0',
                input_file
            ]
            
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
        self.running = True
        
        try:
            if self.is_single_image:
                # 단일 이미지 처리
                self.process_fallback()
            elif self.is_image_sequence:
                # 이미지 시퀀스 처리
                self.process_image_sequence()
            else:
                # 비디오 파일 처리
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
                self.frame_count = int(properties.get('nb_frames', 0))
                
                if self.frame_count <= 0 and self.duration > 0 and self.fps > 0:
                    self.frame_count = int(self.duration * self.fps)
                
                # 비디오 정보 시그널 발생
                self.video_info_ready.emit(self.width, self.height)
                
                # 비디오 프레임 처리 함수 호출
                self.process_video_frames()
        
        except Exception as e:
            self.logger.exception(f"비디오 처리 실패: {e}")
        
        finally:
            self.running = False
            self.finished.emit()
    
    def process_image_sequence_frames(self):
        """이미지 시퀀스 프레임 처리"""
        try:
            # 이미지 시퀀스 패턴에서 파일 목록 가져오기
            import glob
            pattern = re.sub(r'%\d*d', '*', self.file_path)
            image_files = sorted(glob.glob(pattern))
            
            if not image_files:
                self.logger.error(f"이미지 시퀀스를 찾을 수 없습니다: {pattern}")
                return
            
            # 각 이미지 파일 처리
            for i, image_file in enumerate(image_files):
                if not self.running:
                    break
                
                # 일시 정지 처리
                self.mutex.lock()
                if self.paused:
                    self.condition.wait(self.mutex)
                self.mutex.unlock()
                
                # 이미지 로드 및 처리
                try:
                    image = Image.open(image_file)
                    
                    # 이미지를 QPixmap으로 변환
                    img_bytes = io.BytesIO()
                    image.save(img_bytes, format='PNG')
                    img_data = img_bytes.getvalue()
                    
                    q_image = QImage.fromData(img_data)
                    pixmap = QPixmap.fromImage(q_image)
                    
                    # 프레임 시그널 발생
                    self.frame_ready.emit(pixmap)
                    
                    # 현재 프레임 업데이트
                    self.current_frame = i
                    
                    # 재생 속도에 따른 대기
                    if self.speed > 0:
                        time.sleep(1 / (self.fps * self.speed))
                    
                except Exception as e:
                    self.logger.warning(f"이미지 파일 처리 실패: {image_file} - {e}")
                    continue
        
        except Exception as e:
            self.logger.exception(f"이미지 시퀀스 프레임 처리 실패: {e}")
    
    def process_video_frames(self):
        """비디오 프레임 처리"""
        try:
            # FFmpeg 경로 확인
            ffmpeg_path = self.ffmpeg_manager.get_ffmpeg_path()
            if not ffmpeg_path:
                self.logger.error("FFmpeg 경로가 설정되지 않았습니다.")
                return
            
            # FFmpeg 명령 설정
            cmd = [
                ffmpeg_path,
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
            while self.running:
                # 일시 정지 처리
                self.mutex.lock()
                if self.paused:
                    self.condition.wait(self.mutex)
                self.mutex.unlock()
                
                # 프레임 읽기
                in_bytes = self.process.stdout.read(frame_size)
                if not in_bytes:
                    break
                
                # 프레임 처리
                self.process_frame(in_bytes)
                
                # 재생 속도에 따른 대기
                if self.speed > 0:
                    time.sleep(1 / (self.fps * self.speed))
                
                # 현재 프레임 업데이트
                self.current_frame += 1
        
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
        """스레드 중지"""
        self.running = False
        
        # 일시 정지 상태인 경우 해제
        self.mutex.lock()
        self.paused = False
        self.condition.wakeAll()
        self.mutex.unlock()
        
        # 프로세스 정리
        if self.process:
            try:
                self.process.terminate()
                self.process = None
            except Exception as e:
                self.logger.warning(f"프로세스 종료 실패: {e}")
        
        # 스레드가 종료될 때까지 대기
        if self.isRunning():
            self.wait(1000)  # 최대 1초 대기
            
            # 여전히 실행 중이면 강제 종료
            if self.isRunning():
                self.terminate()
                self.logger.warning("비디오 스레드 강제 종료")
    
    def reset(self):
        """스레드 리셋"""
        self.stop()
        self.current_frame = 0
        self.paused = False
        self.speed = 1.0
    
    def set_speed(self, speed: float):
        """재생 속도 설정"""
        if speed > 0:
            self.speed = speed
            self.logger.debug(f"재생 속도 설정: {speed}x")
    
    def get_video_info(self):
        """비디오 정보 반환"""
        return {
            'width': self.width,
            'height': self.height,
            'fps': self.fps,
            'duration': self.duration,
            'frame_count': self.frame_count
        }
    
    def get_video_frame(self, frame_number):
        """특정 프레임 가져오기"""
        try:
            # FFmpeg 경로 확인
            ffmpeg_path = self.ffmpeg_manager.get_ffmpeg_path()
            if not ffmpeg_path:
                self.logger.error("FFmpeg 경로가 설정되지 않았습니다.")
                return None
            
            # 이미지 시퀀스인 경우
            if self.is_image_sequence:
                import glob
                pattern = re.sub(r'%\d*d', '*', self.file_path)
                image_files = sorted(glob.glob(pattern))
                
                if not image_files or frame_number >= len(image_files):
                    self.logger.warning(f"프레임 번호가 유효하지 않습니다: {frame_number}")
                    return None
                
                # 해당 프레임의 이미지 파일 로드
                image = Image.open(image_files[frame_number])
                
                # 이미지를 QPixmap으로 변환
                img_bytes = io.BytesIO()
                image.save(img_bytes, format='PNG')
                img_data = img_bytes.getvalue()
                
                q_image = QImage.fromData(img_data)
                return QPixmap.fromImage(q_image)
            
            # 단일 이미지인 경우
            elif self.is_single_image:
                image = Image.open(self.file_path)
                
                # 이미지를 QPixmap으로 변환
                img_bytes = io.BytesIO()
                image.save(img_bytes, format='PNG')
                img_data = img_bytes.getvalue()
                
                q_image = QImage.fromData(img_data)
                return QPixmap.fromImage(q_image)
            
            # 비디오 파일인 경우
            else:
                # 프레임 시간 계산
                frame_time = frame_number / self.fps
                
                # FFmpeg 명령 설정
                cmd = [
                    ffmpeg_path,
                    '-ss', str(frame_time),
                    '-i', self.file_path,
                    '-vframes', '1',
                    '-f', 'image2pipe',
                    '-pix_fmt', 'rgb24',
                    '-vcodec', 'rawvideo',
                    '-'
                ]
                
                # FFmpeg 프로세스 실행
                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=10**8
                )
                
                # 프레임 크기 계산
                frame_size = self.width * self.height * 3  # RGB 3채널
                
                # 프레임 읽기
                in_bytes = process.stdout.read(frame_size)
                
                # 프로세스 종료
                process.terminate()
                
                if not in_bytes:
                    self.logger.warning(f"프레임을 가져올 수 없습니다: {frame_number}")
                    return None
                
                # 바이트 데이터를 QImage로 변환
                image = QImage(
                    in_bytes, self.width, self.height, 
                    self.width * 3, QImage.Format_RGB888
                )
                
                # QImage를 QPixmap으로 변환
                return QPixmap.fromImage(image)
        
        except Exception as e:
            self.logger.exception(f"프레임 가져오기 실패: {e}")
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


