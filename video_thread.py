# video_thread.py

import os
import subprocess
from typing import Optional
from PySide6.QtCore import QThread, Signal, QByteArray
from PySide6.QtGui import QPixmap, QImage
import glob

from config import FFMPEG_PATH

class VideoThread(QThread):
    frame_ready = Signal(QPixmap)
    finished = Signal()
    video_info_ready = Signal(int, int)

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.is_playing = False
        self.speed = 1.0
        self.process: Optional[subprocess.Popen] = None
        self.is_sequence = '%' in file_path
        self.video_width = 0
        self.video_height = 0
        self.sequence_files = []
        self.current_frame = 0
        self.frame_buffer = QByteArray()
        self.frame_size = 0
        self.frame_skip = 0

    def run(self):
        print("VideoThread.run() 시작")
        self.get_video_info()
        print("비디오 파일 재생 시작")
        self.start_ffmpeg()
        frame_count = 0
        while self.is_playing and self.process:
            if frame_count % (self.frame_skip + 1) == 0:
                self.get_frame()
            else:
                self.skip_frame()
            frame_count += 1
            self.msleep(int(33.33 / self.speed))  # 약 30 FPS에 해당하는 지연 시간
        print("VideoThread.run() 종료")
        self.finished.emit()

    def get_video_info(self):
        print(f"get_video_info() 시작: is_sequence={self.is_sequence}")
        if self.is_sequence:
            self.get_sequence_info()
        else:
            try:
                command = [
                    FFMPEG_PATH,
                    '-i', self.file_path,
                    '-v', 'error',
                    '-select_streams', 'v:0',
                    '-count_packets', '-show_entries', 'stream=width,height',
                    '-of', 'csv=p=0'
                ]
                result = subprocess.run(command, capture_output=True, text=True)
                output = result.stdout.strip()
                if output:
                    self.video_width, self.video_height = map(int, output.split(','))
                    self.video_info_ready.emit(self.video_width, self.video_height)
                else:
                    self.get_video_info_ffprobe()
            except Exception as e:
                print(f"비디오 정보 가져오기 오류: {str(e)}")
                self.video_info_ready.emit(0, 0)

    def get_video_info_ffprobe(self):
        print("get_video_info_ffprobe() 시작")
        try:
            ffprobe_command = [
                os.path.join(os.path.dirname(FFMPEG_PATH), 'ffprobe'),
                '-v', 'error',
                '-select_streams', 'v:0',
                '-count_packets',
                '-show_entries', 'stream=width,height',
                '-of', 'csv=p=0',
                self.file_path
            ]
            ffprobe_result = subprocess.run(ffprobe_command, capture_output=True, text=True)
            ffprobe_output = ffprobe_result.stdout.strip()
            if ffprobe_output:
                self.video_width, self.video_height = map(int, ffprobe_output.split(','))
                self.video_info_ready.emit(self.video_width, self.video_height)
            else:
                print(f"비디오 정보를 가져올 수 없습니다: {self.file_path}")
                self.video_info_ready.emit(0, 0)
        except Exception as e:
            print(f"FFprobe를 사용한 비디오 정보 가져오기 오류: {str(e)}")
            self.video_info_ready.emit(0, 0)

    def get_sequence_info(self):
        print("get_sequence_info() 시작")
        self.get_sequence_files()
        if self.sequence_files:
            pixmap = QPixmap(self.sequence_files[0])
            if not pixmap.isNull():
                self.video_width = pixmap.width()
                self.video_height = pixmap.height()
                self.video_info_ready.emit(self.video_width, self.video_height)
            else:
                self.video_info_ready.emit(0, 0)
        else:
            self.video_info_ready.emit(0, 0)

    def get_sequence_files(self):
        pattern = self.file_path.replace('%04d', '*')
        self.sequence_files = sorted(glob.glob(pattern))

    def start_ffmpeg(self):
        print("start_ffmpeg() 시작")
        try:
            command = [
                FFMPEG_PATH,
                '-i', self.file_path,
                '-f', 'rawvideo',
                '-pix_fmt', 'rgb24',
                '-'
            ]
            if self.is_sequence:
                command[1:1] = ['-framerate', '30']

            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except Exception as e:
            print(f"FFmpeg 시작 중 오류: {str(e)}")
            print(f"FFmpeg 오류 출력: {self.process.stderr.read().decode('utf-8')}")

    def get_frame(self):
        if self.is_playing and self.process:
            if self.frame_size == 0:
                self.frame_size = self.video_width * self.video_height * 3  # RGB24 포맷

            try:
                while len(self.frame_buffer) < self.frame_size:
                    data = self.process.stdout.read(4096)  # 작은 청크로 읽기
                    if not data:
                        print("프레임 데이터를 더 이상 읽을 수 없습니다.")
                        self.stop()
                        return
                    self.frame_buffer.append(data)

                raw_image = self.frame_buffer[:self.frame_size]
                self.frame_buffer = self.frame_buffer[self.frame_size:]

                image = QImage(raw_image, self.video_width, self.video_height, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(image)
                self.frame_ready.emit(pixmap)
            except Exception as e:
                print(f"프레임 읽기 오류: {str(e)}")
                self.stop()

    def stop(self):
        print("stop() 호출됨")
        self.is_playing = False
        if self.process:
            self.process.terminate()
            self.process = None
        self.current_frame = 0
        self.frame_buffer.clear()

    def set_speed(self, speed: float):
        print(f"set_speed() 호출됨: {speed}")
        self.speed = speed
        if speed > 2.0:
            self.frame_skip = int(speed - 2)
        else:
            self.frame_skip = 0

    def get_video_frame(self, time_sec: float) -> Optional[QPixmap]:
        print(f"get_video_frame() 시작: time_sec={time_sec}")
        temp_filename = f'temp_frame_{time_sec}.png'
        command = [
            FFMPEG_PATH,
            '-ss', str(time_sec),
            '-i', self.file_path,
            '-vframes', '1',
            '-an',
            temp_filename
        ]
        try:
            subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            pixmap = QPixmap(temp_filename)
            os.remove(temp_filename)
            return pixmap
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg 에러: {e}")
        except Exception as e:
            print(f"get_video_frame 오류: {str(e)}")
        return None

    def skip_frame(self):
        if self.is_playing and self.process:
            skip_size = self.frame_size * (self.frame_skip)
            try:
                self.process.stdout.read(skip_size)
            except Exception as e:
                print(f"프레임 스킵 오류: {str(e)}")
                self.stop()
