import ffmpeg
import numpy as np
from PySide6.QtCore import QThread, Signal, QByteArray
from PySide6.QtGui import QPixmap, QImage
from concurrent.futures import ThreadPoolExecutor
import cv2
import subprocess
import os
import glob
from PIL import Image

class VideoThread(QThread):
    frame_ready = Signal(QPixmap)
    finished = Signal()
    video_info_ready = Signal(int, int)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.is_playing = False
        self.is_stopping = False
        self.speed = 1.0
        self.preview_width = 640
        self.preview_height = 0
        self.image_files = []
        self.process = None
        self.thread_pool = ThreadPoolExecutor(max_workers=4)
        
        try:
            if '%' in self.file_path:  # 이미지 시퀀스 처리
                self.process_image_sequence()
            else:
                probe = ffmpeg.probe(self.file_path)
                self.video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        except Exception as e:
            print(f"Error processing file: {e}")
            self.process_fallback()

        self.width = int(self.video_info['width'])
        self.height = int(self.video_info['height'])
        if self.preview_height == 0:
            self.preview_height = int(self.height * (self.preview_width / self.width))
        self.frame_rate = eval(self.video_info.get('r_frame_rate', '30/1'))
        duration = float(self.video_info.get('duration', '0'))
        self.total_frames = int(duration * self.frame_rate) if duration > 0 else len(self.image_files)
        self.current_frame = 0
        self.thread_pool = ThreadPoolExecutor(max_workers=4)

    def process_image_sequence(self):
        base_path = self.file_path.split('%')[0]
        pattern = os.path.basename(self.file_path).replace('%04d', '*')
        self.image_files = sorted(glob.glob(os.path.join(os.path.dirname(base_path), pattern)))
        
        if not self.image_files:
            raise ValueError("No image files found in the sequence")
        
        with Image.open(self.image_files[0]) as img:
            width, height = img.size
        
        self.video_info = {
            'width': str(width),
            'height': str(height),
            'r_frame_rate': '30/1',  # 기본 프레임 레이트
            'duration': str(len(self.image_files) / 30)  # 대략적인 지속 시간
        }

    def process_fallback(self):
        # 단일 이미지 파일 처리
        try:
            with Image.open(self.file_path) as img:
                width, height = img.size
            self.video_info = {
                'width': str(width),
                'height': str(height),
                'r_frame_rate': '1/1',
                'duration': '1'
            }
            self.image_files = [self.file_path]
        except Exception as e:
            print(f"Error processing image: {e}")
            # 기본값 설정
            self.video_info = {
                'width': '640',
                'height': '480',
                'r_frame_rate': '30/1',
                'duration': '0'
            }
            self.image_files = []

    def get_image_size(self, file_path):
        # PIL을 사용하여 이미지 크기 가져오기
        with Image.open(file_path) as img:
            return img.size

    def run(self):
        try:
            self.video_info_ready.emit(self.width, self.height)
            
            if '%' in self.file_path or len(self.image_files) > 0:
                self.process_image_sequence_frames()
            else:
                self.process_video_frames()
        finally:
            if not self.is_stopping:
                self.stop()
                self.is_playing = False
                self.finished.emit()

    def process_image_sequence_frames(self):
        if self.preview_height == 0:
            self.preview_height = int(self.height * (self.preview_width / self.width))

        for image_file in self.image_files:
            if not self.is_playing:
                break
            
            img = Image.open(image_file)
            img.thumbnail((self.preview_width, self.preview_height), Image.LANCZOS)
            
            # PIL 이미지를 numpy 배열로 변환
            np_img = np.array(img)
            
            # RGB에서 BGR로 변환 (만약 필요하다면)
            # np_img = np_img[:, :, ::-1].copy()
            
            height, width, channel = np_img.shape
            bytes_per_line = 3 * width
            
            q_image = QImage(np_img.data, width, height, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_image)
            
            self.frame_ready.emit(pixmap)
            self.current_frame += 1
            self.msleep(int(1000 / (self.frame_rate * self.speed)))

        self.finished.emit()

    def process_video_frames(self):
        try:
            self.process = (
                ffmpeg
                .input(self.file_path)
                .output('pipe:', format='rawvideo', pix_fmt='rgb24')
                .run_async(pipe_stdout=True, pipe_stdin=True)
            )

            while self.is_playing and self.current_frame < self.total_frames:
                in_bytes = self.process.stdout.read(self.width * self.height * 3)
                if not in_bytes:
                    break

                self.thread_pool.submit(self.process_frame, in_bytes)
                
                self.current_frame += 1
                self.msleep(int(1000 / (self.frame_rate * self.speed)))

                if self.current_frame >= self.total_frames - 1:
                    break  # 마지막 프레임에 도달하면 루프를 빠져나갑니다.

        except ffmpeg.Error as e:
            print(f"FFmpeg 에러: {e.stderr.decode()}")
        except Exception as e:
            print(f"예상치 못한 에러: {e}")
        finally:
            self.stop()

    def process_frame(self, in_bytes):
        np_array = np.frombuffer(in_bytes, np.uint8).reshape([self.height, self.width, 3])
        # BGR에서 RGB로의 변환을 제거합니다.
        frame = np_array  # cv2.cvtColor(np_array, cv2.COLOR_RGB2BGR) 대신 사용
        
        if self.preview_height == 0:
            self.preview_height = int(self.height * (self.preview_width / self.width))
        
        resized_frame = cv2.resize(frame, (self.preview_width, self.preview_height))
        
        height, width, channel = resized_frame.shape
        bytes_per_line = 3 * width
        q_image = QImage(resized_frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(q_image)
        
        self.frame_ready.emit(pixmap)

    def stop(self):
        if self.is_stopping:
            return
        self.is_stopping = True
        self.is_playing = False
        print("VideoThread stop 호출됨")
        if self.process:
            try:
                # 프로세스 종료 요청
                self.process.terminate()
                # 최대 5초 동안 프로세스가 종료되기를 기다림
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # 5초 후에도 종료되지 않으면 강제 종료
                self.process.kill()
            except Exception as e:
                print(f"프로세스 종료 중 오류 발생: {e}")
            finally:
                self.process = None
        self.is_stopping = False
        print("VideoThread stop 완료")

    def reset(self):
        self.is_playing = False
        self.is_stopping = False
        self.current_frame = 0
        if self.process:
            self.process.kill()
            self.process = None

    def set_speed(self, speed: float):
        self.speed = speed

    def get_video_info(self):
        return {
            'width': self.width,
            'height': self.height,
            'frame_rate': self.frame_rate,
            'total_frames': self.total_frames
        }
    def get_video_frame(self, frame_number):
        if '%' in self.file_path or self.image_files:  # 이미지 시퀀스인 경우
            if 0 <= frame_number < len(self.image_files):
                img = Image.open(self.image_files[frame_number])
                img = self.resize_image(img, self.preview_width, self.preview_height)
                
                np_img = np.array(img)
                height, width, channel = np_img.shape
                bytes_per_line = 3 * width
                
                q_image = QImage(np_img.data, width, height, bytes_per_line, QImage.Format_RGB888)
                return QPixmap.fromImage(q_image)
            return None
        
        # 비디오 파일 처리
        try:
            out, _ = (
                ffmpeg
                .input(self.file_path)
                .filter('select', f'gte(n,{frame_number})')
                .output('pipe:', format='rawvideo', pix_fmt='rgb24', vframes=1)
                .run(capture_stdout=True)
            )

            frame = np.frombuffer(out, np.uint8).reshape([self.height, self.width, 3])
            
            resized_frame = self.resize_frame(frame, self.preview_width, self.preview_height)
            
            height, width, channel = resized_frame.shape
            bytes_per_line = 3 * width
            q_image = QImage(resized_frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_image)
            
            return pixmap
        except Exception as e:
            print(f"프레임 가져오기 오류: {e}")
            return None
    def resize_image(self, img, target_width, target_height):
        # 이미지의 종횡비 유지하면서 리사이즈
        img_width, img_height = img.size
        aspect_ratio = img_width / img_height
        target_ratio = target_width / target_height

        if aspect_ratio > target_ratio:
            # 이미지가 더 넓은 경우
            new_width = target_width
            new_height = int(target_width / aspect_ratio)
        else:
            # 이미지가 더 높은 경우
            new_height = target_height
            new_width = int(target_height * aspect_ratio)

        img = img.resize((new_width, new_height), Image.LANCZOS)
        
        # 빈 이미지 생성 (검은색 배경)
        background = Image.new('RGB', (target_width, target_height), (0, 0, 0))
        
        # 리사이즈된 이미지를 중앙에 붙이기
        offset = ((target_width - new_width) // 2, (target_height - new_height) // 2)
        background.paste(img, offset)
        
        return background

    def resize_frame(self, frame, target_width, target_height):
        # 프레임의 종횡비 유지하면서 리사이즈
        img_height, img_width = frame.shape[:2]
        aspect_ratio = img_width / img_height
        target_ratio = target_width / target_height

        if aspect_ratio > target_ratio:
            # 이미지가 더 넓은 경우
            new_width = target_width
            new_height = int(target_width / aspect_ratio)
        else:
            # 이미지가 더 높은 경우
            new_height = target_height
            new_width = int(target_height * aspect_ratio)

        resized_frame = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LANCZOS4)
        
        # 빈 프레임 생성 (검은색 배경)
        background = np.zeros((target_height, target_width, 3), dtype=np.uint8)
        
        # 리사이즈된 프레임을 중앙에 붙이기
        y_offset = (target_height - new_height) // 2
        x_offset = (target_width - new_width) // 2
        background[y_offset:y_offset+new_height, x_offset:x_offset+new_width] = resized_frame
        
        return background
