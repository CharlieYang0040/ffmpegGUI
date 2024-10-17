# gui.py

import os
import re
import glob
import subprocess
import sys
from typing import List, Dict, Optional
import traceback

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QFileDialog, QListWidget, QGroupBox,
    QHBoxLayout, QLabel, QComboBox, QAbstractItemView, QCheckBox, QLineEdit,
    QMessageBox, QSlider, QDoubleSpinBox
)
from PySide6.QtCore import Qt, QSettings, QThread, Signal, QItemSelectionModel
from PySide6.QtGui import QKeySequence, QDragEnterEvent, QDropEvent, QCursor, QPixmap, QImage, QIcon, QIntValidator

from ffmpeg_utils import concat_videos
from update import UpdateChecker

FFMPEG_PATH = os.path.join('libs', 'ffmpeg-7.1-full_build', 'bin', 'ffmpeg.exe')

class DragDropListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.accept()
            links = []
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    file_path = str(url.toLocalFile())
                    processed_path = self.parent().process_file(file_path)
                    if processed_path:
                        links.append(processed_path)
            self.addItems(links)
        else:
            super().dropEvent(event)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Delete):
            self.remove_selected_items()
        else:
            super().keyPressEvent(event)

    def remove_selected_items(self):
        for item in self.selectedItems():
            self.takeItem(self.row(item))

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

    def run(self):
        self.get_video_info()
        self.start_ffmpeg()
        while self.is_playing:
            self.get_frame()
            self.msleep(int(1000 / (30 * self.speed)))  # 30 FPS 기준
        self.finished.emit()

    def get_video_info(self):
        try:
            command = [
                FFMPEG_PATH,
                '-i', self.file_path
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            output = result.stderr  # FFmpeg는 정보를 stderr로 출력합니다

            print(f"FFmpeg 명령어: {' '.join(command)}")
            print(f"FFmpeg 출력: {output}")

            # 정규 표현식을 사용하여 비디오 크기 정보 추출
            import re
            match = re.search(r'Stream.*Video.*\s(\d+)x(\d+)', output)
            if match:
                self.video_width, self.video_height = map(int, match.groups())
                print(f"비디오 크기: {self.video_width}x{self.video_height}")
                self.video_info_ready.emit(self.video_width, self.video_height)
            else:
                print("비디오 크기 정보를 찾을 수 없습니다.")
                self.video_info_ready.emit(0, 0)
        except Exception as e:
            print(f"비디오 정보 가져오기 오류: {str(e)}")
            print(f"예외 타입: {type(e).__name__}")
            print(f"스택 트레이스: {traceback.format_exc()}")
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
            print(f"FFmpeg 시작 중 오류: {str(e)}")

    def get_frame(self):
        if self.is_playing and self.process:
            frame_size = self.video_width * self.video_height * 3  # RGB24 포맷
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

    def get_video_frame(self, time_sec: float) -> Optional[QPixmap]:
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

class FFmpegGui(QWidget):
    def __init__(self):
        super().__init__()
        self.update_checker = UpdateChecker()
        self.init_attributes()
        self.init_ui()
        self.position_window_near_mouse()
        self.setStyleSheet(self.get_unreal_style())
        self.set_icon()
        # self.show_console()  # 콘솔 창을 표시하기 위해 호출
        self.hide_console()  # 실행 시 콘솔 창 숨기기

    def setup_update_checker(self):
        self.update_checker.update_error.connect(self.show_update_error)
        self.update_checker.update_available.connect(self.show_update_available)
        self.update_checker.no_update.connect(self.show_no_update)
        self.update_checker.update_button = self.update_button

    def show_console(self):
        if sys.platform.startswith('win'):
            import ctypes
            ctypes.windll.kernel32.AllocConsole()
            sys.stdout = open('CONOUT$', 'w')
            sys.stderr = open('CONOUT$', 'w')

    def hide_console(self):
        if sys.platform.startswith('win'):
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

    def init_attributes(self):
        self.encoding_options = {
            "-c:v": "libx264",
            "-pix_fmt": "yuv420p",
            "-colorspace": "bt709",
            "-color_primaries": "bt709",
            "-color_trc": "bt709",
            "-color_range": "limited"
        }
        self.settings = QSettings("LHCinema", "FFmpegGUI")
        self.use_2f_offset = False
        self.video_thread = None
        self.speed = 1.0
        self.current_video_width = 0
        self.current_video_height = 0
        self.framerate = 30
        self.video_width = 1920
        self.video_height = 1080
        self.use_custom_framerate = False
        self.use_custom_resolution = False

    def init_ui(self):
        self.setWindowTitle('ffmpegGUI by LHCinema')
        main_layout = QVBoxLayout(self)

        self.create_top_layout(main_layout)
        self.create_content_layout(main_layout)

        self.setGeometry(100, 100, 650, 600)
        self.setMinimumWidth(650)

    def create_top_layout(self, main_layout):
        top_layout = QHBoxLayout()

        self.create_preview_area(top_layout)
        self.create_control_area(top_layout)

        main_layout.addLayout(top_layout)

    def create_preview_area(self, top_layout):
        self.preview_label = QLabel(alignment=Qt.AlignCenter)
        self.preview_label.setFixedSize(360, 240)
        self.preview_label.setStyleSheet("background-color: #1a1a1a; border: 1px solid #3a3a3a;")
        top_layout.addWidget(self.preview_label, 1)

    def create_control_area(self, top_layout):
        control_layout = QVBoxLayout()

        self.create_play_button(control_layout)
        self.create_speed_control(control_layout)
        self.create_offset_group(control_layout)

        control_layout.addStretch(1)
        top_layout.addLayout(control_layout)

    def create_play_button(self, control_layout):
        self.play_button = QPushButton('재생')
        self.play_button.clicked.connect(self.toggle_play)
        control_layout.addWidget(self.play_button)

    def create_speed_control(self, control_layout):
        speed_layout = QVBoxLayout()
        speed_label = QLabel("재생 속도:")
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(25, 400)
        self.speed_slider.setValue(100)
        self.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.speed_slider.setTickInterval(50)
        self.speed_slider.valueChanged.connect(self.change_speed)
        self.speed_value_label = QLabel("1.0x")

        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(self.speed_slider)
        speed_layout.addWidget(self.speed_value_label)

        control_layout.addLayout(speed_layout)

    def create_offset_group(self, control_layout):
        self.offset_group = QGroupBox("편집 옵션")
        offset_layout = QVBoxLayout()
        
        self.create_2f_offset_checkbox(offset_layout)
        self.create_framerate_control(offset_layout)
        self.create_resolution_control(offset_layout)

        self.offset_group.setLayout(offset_layout)
        control_layout.addWidget(self.offset_group)

    def create_2f_offset_checkbox(self, offset_layout):
        self.offset_checkbox = QCheckBox("2f offset 사용")
        self.offset_checkbox.setChecked(False)
        self.offset_checkbox.stateChanged.connect(self.toggle_2f_offset)
        offset_layout.addWidget(self.offset_checkbox)

    def create_framerate_control(self, offset_layout):
        framerate_layout = QHBoxLayout()
        self.framerate_checkbox = QCheckBox("프레임레이트 설정:")
        self.framerate_checkbox.setChecked(False)
        self.framerate_checkbox.stateChanged.connect(self.toggle_framerate)
        self.framerate_spinbox = QDoubleSpinBox()
        self.framerate_spinbox.setRange(1, 120)
        self.framerate_spinbox.setValue(30)
        self.framerate_spinbox.setEnabled(False)
        self.framerate_spinbox.valueChanged.connect(self.update_framerate)
        framerate_layout.addWidget(self.framerate_checkbox)
        framerate_layout.addWidget(self.framerate_spinbox)
        offset_layout.addLayout(framerate_layout)

    def create_resolution_control(self, offset_layout):
        resolution_layout = QHBoxLayout()
        self.resolution_checkbox = QCheckBox("해상도 설정:")
        self.resolution_checkbox.setChecked(False)
        self.resolution_checkbox.stateChanged.connect(self.toggle_resolution)
        
        self.width_edit = QLineEdit()
        self.width_edit.setValidator(QIntValidator(1, 7680))
        self.width_edit.setText("1920")
        self.width_edit.setFixedWidth(60)  # 너비 조정
        self.width_edit.setEnabled(False)
        
        self.height_edit = QLineEdit()
        self.height_edit.setValidator(QIntValidator(1, 4320))
        self.height_edit.setText("1080")
        self.height_edit.setFixedWidth(60)  # 너비 조정
        self.height_edit.setEnabled(False)
        
        resolution_layout.addWidget(self.resolution_checkbox)
        resolution_layout.addWidget(self.width_edit)
        resolution_layout.addWidget(QLabel("x"))
        resolution_layout.addWidget(self.height_edit)
        
        self.width_edit.textChanged.connect(self.update_resolution)
        self.height_edit.textChanged.connect(self.update_resolution)
        
        offset_layout.addLayout(resolution_layout)

    def create_content_layout(self, main_layout):
        content_layout = QHBoxLayout()
        self.create_left_layout(content_layout)
        main_layout.addLayout(content_layout)

    def create_left_layout(self, content_layout):
        left_layout = QVBoxLayout()
        self.create_list_widget(left_layout)
        self.create_button_layout(left_layout)
        self.create_options_group(left_layout)
        self.create_output_layout(left_layout)
        self.create_encode_button(left_layout)
        self.create_update_button(left_layout)
        self.create_debug_layout(left_layout)
        content_layout.addLayout(left_layout)

    def create_list_widget(self, left_layout):
        self.list_widget = DragDropListWidget(self)
        self.list_widget.setMinimumHeight(200)
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self.update_preview)
        left_layout.addWidget(self.list_widget)

    def create_button_layout(self, left_layout):
        button_layout = QHBoxLayout()
        self.add_button = QPushButton('파일 추가')
        self.add_button.clicked.connect(self.add_files)
        button_layout.addWidget(self.add_button)

        self.move_up_button = QPushButton('위로 이동')
        self.move_up_button.clicked.connect(self.move_item_up)
        button_layout.addWidget(self.move_up_button)

        self.move_down_button = QPushButton('아래로 이동')
        self.move_down_button.clicked.connect(self.move_item_down)
        button_layout.addWidget(self.move_down_button)

        left_layout.addLayout(button_layout)

    def create_options_group(self, left_layout):
        self.options_group = QGroupBox("인코딩 옵션")
        options_layout = QVBoxLayout()

        encoding_options = [
            ("-c:v", ["libx264", "libx265", "none"]),
            ("-pix_fmt", ["yuv420p", "yuv422p", "yuv444p", "none"]),
            ("-colorspace", ["bt709", "bt2020nc", "none"]),
            ("-color_primaries", ["bt709", "bt2020", "none"]),
            ("-color_trc", ["bt709", "bt2020-10", "none"]),
            ("-color_range", ["limited", "full", "none"])
        ]

        self.option_widgets = {}

        for option, values in encoding_options:
            self.create_option_widget(options_layout, option, values)

        self.options_group.setLayout(options_layout)
        left_layout.addWidget(self.options_group)

    def create_option_widget(self, options_layout, option, values):
        hbox = QHBoxLayout()
        label = QLabel(option)
        combo = QComboBox()
        combo.addItems(values)
        combo.setCurrentIndex(0)
        combo.currentTextChanged.connect(lambda value, opt=option: self.update_option(opt, value))
        hbox.addWidget(label)
        hbox.addWidget(combo)
        options_layout.addLayout(hbox)
        self.option_widgets[option] = combo

    def create_output_layout(self, left_layout):
        output_layout = QHBoxLayout()
        self.output_label = QLabel("출력 경로:")
        self.output_edit = QLineEdit()
        self.output_edit.setText(self.settings.value("last_output_path", ""))
        self.output_browse = QPushButton("찾아보기")
        self.output_browse.clicked.connect(self.browse_output)
        output_layout.addWidget(self.output_label)
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(self.output_browse)
        left_layout.addLayout(output_layout)

    def create_encode_button(self, left_layout):
        self.encode_button = QPushButton('인코딩 시작')
        self.encode_button.clicked.connect(self.start_encoding)
        left_layout.addWidget(self.encode_button)

    def create_debug_layout(self, left_layout):
        debug_layout = QHBoxLayout()
        self.debug_checkbox = QCheckBox("디버그 모드")
        self.debug_checkbox.setChecked(False)
        self.debug_checkbox.stateChanged.connect(self.toggle_debug_mode)
        debug_layout.addStretch(1)
        debug_layout.addWidget(self.debug_checkbox)

        self.clear_settings_button = QPushButton("설정 초기화")
        self.clear_settings_button.clicked.connect(self.clear_settings)
        self.clear_settings_button.hide()
        debug_layout.addWidget(self.clear_settings_button)

        left_layout.addLayout(debug_layout)

    # 업데이트 버튼 추가
    def create_update_button(self, left_layout):
        update_layout = QHBoxLayout()
        self.update_button = QPushButton('업데이트 확인')
        self.update_button.clicked.connect(self.update_checker.check_for_updates)
        update_layout.addWidget(self.update_button)
        left_layout.addLayout(update_layout)

    def show_update_error(self, error_message):
        QMessageBox.critical(self, '업데이트 오류', f'업데이트 확인 중 오류가 발생했습니다:\n{error_message}')

    def show_update_available(self, latest_version, download_url):
        reply = QMessageBox.question(
            self, '업데이트 확인',
            f'새로운 버전이 있습니다: {latest_version}\n업데이트를 진행하시겠습니까?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
        )
        if reply == QMessageBox.Yes:
            self.update_checker.download_and_install_update(download_url)

    def show_no_update(self):
        QMessageBox.information(self, '업데이트 확인', '현재 최신 버전입니다.')

    def check_for_updates(self):
        self.update_checker.check_for_updates()

    def get_unreal_style(self) -> str:
        return """
        QWidget {
            background-color: #1a1a1a;
            color: #ffffff;
            font-family: 'Segoe UI', Arial, sans-serif;
        }
        QPushButton {
            background-color: #2a2a2a;
            border: 1px solid #3a3a3a;
            padding: 5px 10px;
            border-radius: 3px;
        }
        QPushButton:hover {
            background-color: #3a3a3a;
        }
        QPushButton:pressed {
            background-color: #4a4a4a;
        }
        QListWidget, QLineEdit, QComboBox {
            background-color: #2a2a2a;
            border: 1px solid #3a3a3a;
            border-radius: 3px;
        }
        QGroupBox {
            border: 1px solid #3a3a3a;
            border-radius: 5px;
            margin-top: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 3px 0 3px;
        }
        QCheckBox::indicator {
            width: 13px;
            height: 13px;
        }
        QCheckBox::indicator:unchecked {
            border: 1px solid #3a3a3a;
            background-color: #2a2a2a;
        }
        QCheckBox::indicator:checked {
            border: 1px solid #3a3a3a;
            background-color: #4a90e2;
        }
        QSlider::groove:horizontal {
            border: 1px solid #3a3a3a;
            height: 8px;
            background: #2a2a2a;
            margin: 2px 0;
        }
        QSlider::handle:horizontal {
            background: #4a90e2;
            border: 1px solid #3a3a3a;
            width: 18px;
            margin: -2px 0;
            border-radius: 3px;
        }
        """

    def set_icon(self):
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))
        
        icon_path = os.path.join(base_path, 'icon.png')
        self.setWindowIcon(QIcon(icon_path))

    def hide_console(self):
        if sys.platform.startswith('win'):
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

    def process_file(self, file_path: str) -> str:
        _, ext = os.path.splitext(file_path)
        return self.process_image_file(file_path) if ext.lower() in ['.jpg', '.jpeg', '.png'] else file_path

    def process_image_file(self, file_path: str) -> str:
        dir_path, file_name = os.path.split(file_path)
        base_name, ext = os.path.splitext(file_name)

        match = re.search(r'(\d+)$', base_name)
        if match:
            number_part = match.group(1)
            prefix = base_name[:-len(number_part)]
            pattern = f"{prefix}[0-9]*{ext}"
            matching_files = [f for f in os.listdir(dir_path) if re.match(pattern, f)]

            if len(matching_files) > 1:
                return os.path.join(dir_path, f"{prefix}%0{len(number_part)}d{ext}")

        return file_path

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '파일 선택', '', '모든 파일 (*.*)')
        if files:
            self.list_widget.addItems(map(self.process_file, files))

    def move_item_up(self):
        self.move_selected_items(-1)

    def move_item_down(self):
        self.move_selected_items(1)

    def move_selected_items(self, direction):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return
        
        items_to_move = selected_items if direction < 0 else reversed(selected_items)
        for item in items_to_move:
            current_row = self.list_widget.row(item)
            new_row = current_row + direction
            if 0 <= new_row < self.list_widget.count() and self.list_widget.item(new_row) not in selected_items:
                taken_item = self.list_widget.takeItem(current_row)
                self.list_widget.insertItem(new_row, taken_item)
                self.list_widget.setCurrentItem(taken_item, QItemSelectionModel.Select)

    def update_option(self, option: str, value: str):
        if value != "none":
            self.encoding_options[option] = value
        else:
            self.encoding_options.pop(option, None)

    def toggle_2f_offset(self, state):
        self.use_2f_offset = state == Qt.CheckState.Checked.value
        print(f"toggle_2f_offset 호출됨: state={state}, use_2f_offset={self.use_2f_offset}")


    def get_encoding_parameters(self):
        output_file = self.output_edit.text()
        if not output_file:
            QMessageBox.warning(self, "경고", "출력 경로를 지정해주세요.")
            return None

        if self.list_widget.count() == 0:
            QMessageBox.warning(self, "경고", "입력 파일을 추가해주세요.")
            return None

        input_files = [self.list_widget.item(i).text() for i in range(self.list_widget.count())]
        return (output_file, self.encoding_options, self.use_2f_offset,
                self.debug_checkbox.isChecked(), input_files)

    def browse_output(self):
        last_path = self.settings.value("last_output_path", "")
        output_file, _ = QFileDialog.getSaveFileName(self, '출력 파일 저장', last_path, 'MP4 파일 (*.mp4)')
        if output_file:
            self.output_edit.setText(output_file)
            self.settings.setValue("last_output_path", output_file)

    def start_encoding(self):
        params = self.get_encoding_parameters()
        if params:
            output_file, encoding_options, use_2f_offset, debug_mode, input_files = params
            
            self.update_encoding_options(encoding_options)
            
            try:
                concat_videos(
                    input_files,
                    output_file,
                    encoding_options,
                    use_2f_offset=use_2f_offset,
                    debug_mode=debug_mode
                )
                QMessageBox.information(self, "완료", "인코딩이 완료되었습니다.")
            except Exception as e:
                QMessageBox.critical(self, "에러", f"인코딩 중 에러가 발생했습니다:\n{e}")

    def update_encoding_options(self, encoding_options):
        if self.use_custom_framerate:
            encoding_options["-r"] = str(self.framerate)
        if self.use_custom_resolution:
            encoding_options["-s"] = f"{self.video_width}x{self.video_height}"

    def toggle_debug_mode(self, state):
        is_debug = state == Qt.CheckState.Checked.value
        self.clear_settings_button.setVisible(is_debug)
        print(f"toggle_debug_mode 호출됨: state={state}, is_debug={is_debug}")

    def position_window_near_mouse(self):
        cursor_pos = QCursor.pos()
        screen = self.screen()
        screen_geometry = screen.availableGeometry()

        window_width = self.width()
        window_height = self.height()

        x = max(screen_geometry.left(), min(cursor_pos.x() - window_width // 2, screen_geometry.right() - window_width))
        y = max(screen_geometry.top(), min(cursor_pos.y() - window_height // 2, screen_geometry.bottom() - window_height))

        self.move(x, y)

    def clear_settings(self):
        reply = QMessageBox.question(
            self, '설정 초기화',
            "모든 설정을 초기화하시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.settings.clear()
            self.settings.sync()
            QMessageBox.information(self, '설정 초기화', '모든 설정이 초기화되었습니다.')
            self.output_edit.clear()

    def update_preview(self):
        try:
            selected_items = self.list_widget.selectedItems()
            if selected_items:
                file_path = selected_items[0].text()
                self.stop_current_preview()
                
                if self.is_video_file(file_path):
                    self.show_video_preview(file_path)
                elif self.is_image_file(file_path):
                    self.show_image_preview(file_path)
                else:
                    print(f"지원되지 않는 파일 형식: {file_path}")
            else:
                self.preview_label.clear()
        except Exception as e:
            print(f"update_preview 오류: {str(e)}")

    def stop_current_preview(self):
        if self.video_thread:
            self.video_thread.stop()
            self.video_thread.wait()

    def is_video_file(self, file_path):
        return file_path.lower().endswith(('.mp4', '.avi', '.mov', '.mkv')) or '%' in file_path

    def is_image_file(self, file_path):
        return file_path.lower().endswith(('.jpg', '.jpeg', '.png', '.bmp'))

    def show_video_preview(self, file_path: str):
        self.video_thread = VideoThread(file_path)
        self.video_thread.frame_ready.connect(self.update_video_frame)
        self.video_thread.finished.connect(self.on_video_finished)
        self.video_thread.video_info_ready.connect(self.set_video_info)
        self.play_button.setEnabled(True)

        self.video_thread.get_video_info()
        self.video_thread.wait()
        first_frame = self.video_thread.get_video_frame(0)
        if first_frame and not first_frame.isNull():
            self.update_video_frame(first_frame)
        else:
            self.preview_label.clear()

    def set_video_info(self, width: int, height: int):
        self.current_video_width = width
        self.current_video_height = height

    def toggle_play(self):
        if self.video_thread:
            if not self.video_thread.is_playing:
                self.start_video_playback()
            else:
                self.stop_video_playback()

    def start_video_playback(self):
        self.video_thread.is_playing = True
        current_speed = self.speed_slider.value() / 100
        self.video_thread.set_speed(current_speed)
        self.video_thread.start()
        self.play_button.setText('정지')

    def stop_video_playback(self):
        self.video_thread.stop()
        self.play_button.setText('재생')

    def on_video_finished(self):
        self.play_button.setText('재생')

    def change_speed(self):
        self.speed = self.speed_slider.value() / 100
        self.speed_value_label.setText(f"{self.speed:.1f}x")
        if self.video_thread:
            self.video_thread.set_speed(self.speed)

    def resize_keeping_aspect_ratio(self, pixmap: QPixmap, max_width: int, max_height: int, video_width: int = 0, video_height: int = 0) -> QPixmap:
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

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_preview_label()

    def update_preview_label(self):
        if self.preview_label.pixmap() and not self.preview_label.pixmap().isNull():
            scaled_pixmap = self.resize_keeping_aspect_ratio(
                self.preview_label.pixmap(),
                self.preview_label.width(),
                self.preview_label.height(),
                self.current_video_width,
                self.current_video_height
            )
            self.preview_label.setPixmap(scaled_pixmap)

    def update_video_frame(self, pixmap: QPixmap):
        if not pixmap.isNull():
            scaled_pixmap = self.resize_keeping_aspect_ratio(
                pixmap,
                self.preview_label.width(),
                self.preview_label.height(),
                self.current_video_width,
                self.current_video_height
            )
            self.preview_label.setPixmap(scaled_pixmap)

    def show_image_preview(self, file_path: str):
        # 시퀀스 파일 처리
        if '%' in file_path:
            file_path = self.get_first_sequence_file(file_path)
            if not file_path:
                print(f"시퀀스 파일을 찾을 수 없습니다: {file_path}")
                return

        if os.path.exists(file_path):
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                scaled_pixmap = self.resize_keeping_aspect_ratio(pixmap, self.preview_label.width(), self.preview_label.height())
                self.preview_label.setPixmap(scaled_pixmap)
            else:
                print(f"이미지를 로드할 수 없습니다: {file_path}")
        else:
            print(f"파일이 존재하지 않습니다: {file_path}")

    def get_first_sequence_file(self, file_path: str) -> str:
        pattern = file_path.replace('%04d', '*')
        files = sorted(glob.glob(pattern))
        return files[0] if files else ""

    def hide_console(self):
        if sys.platform.startswith('win'):
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)

    def toggle_framerate(self, state):
        self.use_custom_framerate = state == Qt.CheckState.Checked.value
        self.framerate_spinbox.setEnabled(self.use_custom_framerate)
        if not self.use_custom_framerate:
            self.encoding_options.pop("-r", None)  # 프레임레이트 옵션 제거
        print(f"toggle_framerate 호출됨: state={state}, use_custom_framerate={self.use_custom_framerate}")

    def toggle_resolution(self, state):
        self.use_custom_resolution = state == Qt.CheckState.Checked.value
        self.width_edit.setEnabled(self.use_custom_resolution)
        self.height_edit.setEnabled(self.use_custom_resolution)
        if not self.use_custom_resolution:
            self.encoding_options.pop("-s", None)  # 해상도 옵션 제거
        print(f"toggle_resolution 호출됨: state={state}, use_custom_resolution={self.use_custom_resolution}")

    def update_framerate(self, value):
        self.framerate = value
        if self.use_custom_framerate:
            self.encoding_options["-r"] = str(self.framerate)

    def update_resolution(self):
        self.video_width = self.width_edit.text()
        self.video_height = self.height_edit.text()
        if self.use_custom_resolution:
            self.encoding_options["-s"] = f"{self.video_width}x{self.video_height}"