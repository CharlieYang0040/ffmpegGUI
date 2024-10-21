# video_thread.py

import os
import subprocess
import sys
import json
import traceback
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap, QImage

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
        self.process = None
        self.is_sequence = '%' in file_path
        self.video_width = 0
        self.video_height = 0

    def run(self):
        self.get_video_info()
        self.start_ffmpeg()
        while self.is_playing:
            self.get_frame()
            self.msleep(int(1000 / (30 * self.speed)))  # Based on 30 FPS
        self.finished.emit()

    def get_video_info(self):
        try:
            command = [
                os.path.join(os.path.dirname(FFMPEG_PATH), 'ffprobe'),
                '-v', 'quiet',
                '-print_format', 'json',
                '-show_format',
                '-show_streams',
                self.file_path
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            output = result.stdout

            print(f"ffprobe command: {' '.join(command)}")
            print(f"ffprobe output: {output}")

            data = json.loads(output)
            video_stream = next((stream for stream in data['streams'] if stream['codec_type'] == 'video'), None)
            
            if video_stream:
                self.video_width = int(video_stream['width'])
                self.video_height = int(video_stream['height'])
                print(f"Video size: {self.video_width}x{self.video_height}")
                self.video_info_ready.emit(self.video_width, self.video_height)
            else:
                print("No video stream found.")
                self.video_info_ready.emit(0, 0)
        except Exception as e:
            print(f"Error getting video info: {str(e)}")
            print(f"Exception type: {type(e).__name__}")
            print(f"Stack trace: {traceback.format_exc()}")
            self.video_info_ready.emit(0, 0)

    def start_ffmpeg(self):
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
            print(f"Error starting FFmpeg: {str(e)}")

    def get_frame(self):
        if self.is_playing and self.process:
            frame_size = self.video_width * self.video_height * 3  # RGB24 format
            raw_image = self.process.stdout.read(frame_size)
            if len(raw_image) == frame_size:
                image = QImage(raw_image, self.video_width, self.video_height, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(image)
                self.frame_ready.emit(pixmap)
            else:
                self.stop()

    def stop(self):
        self.is_playing = False
        if self.process:
            self.process.terminate()
            self.process = None

    def set_speed(self, speed: float):
        self.speed = speed

    def get_video_frame(self, time_sec: float) -> QPixmap:
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
            print(f"FFmpeg error: {e}")
        except Exception as e:
            print(f"Error in get_video_frame: {str(e)}")
        return None
