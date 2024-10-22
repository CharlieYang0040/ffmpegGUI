# gui.py

import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QComboBox, QAbstractItemView, QCheckBox, QLineEdit,
    QMessageBox, QSlider, QDoubleSpinBox, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt, QSettings, QItemSelectionModel
from PySide6.QtGui import QCursor, QPixmap, QIcon, QIntValidator

from ffmpeg_utils import concat_videos
from update import UpdateChecker

from drag_drop_list_widget import DragDropListWidget
from video_thread import VideoThread
from utils import (
    process_file,
    is_video_file,
    is_image_file,
    get_sequence_start_number,
    get_first_sequence_file,
)
from config import FFMPEG_PATH

class FFmpegGui(QWidget):
    def __init__(self):
        super().__init__()
        self.update_checker = UpdateChecker()
        self.init_attributes()
        self.init_ui()
        self.position_window_near_mouse()
        self.setStyleSheet(self.get_unreal_style())
        self.set_icon()
        self.hide_console()  # Hide console window on startup
        self.sort_ascending = True  # Variable to store sort order

    def setup_update_checker(self):
        self.update_checker.update_error.connect(self.show_update_error)
        self.update_checker.update_available.connect(self.show_update_available)
        self.update_checker.no_update.connect(self.show_no_update)
        self.update_checker.update_button = self.update_button

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
        self.speed_slider.setRange(0, 400)
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
        self.width_edit.setFixedWidth(60)  # Adjust width
        self.width_edit.setEnabled(False)

        self.height_edit = QLineEdit()
        self.height_edit.setValidator(QIntValidator(1, 4320))
        self.height_edit.setText("1080")
        self.height_edit.setFixedWidth(60)  # Adjust width
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
        # Preview mode checkbox
        self.preview_mode_checkbox = QCheckBox("Preview 모드")
        self.preview_mode_checkbox.setChecked(True)  # Default is checked
        left_layout.addWidget(self.preview_mode_checkbox)

        self.list_widget = DragDropListWidget(self, process_file_func=process_file)
        self.list_widget.setMinimumHeight(200)
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.itemSelectionChanged.connect(self.on_item_selection_changed)
        left_layout.addWidget(self.list_widget)

    def on_item_selection_changed(self):
        if self.preview_mode_checkbox.isChecked():
            self.update_preview()

    def create_button_layout(self, left_layout):
        button_layout = QHBoxLayout()

        self.add_button = QPushButton('파일 추가')
        self.add_button.clicked.connect(self.add_files)
        button_layout.addWidget(self.add_button)

        self.remove_button = QPushButton('파일 제거')
        self.remove_button.clicked.connect(self.remove_selected_files)
        button_layout.addWidget(self.remove_button)

        self.clear_button = QPushButton('목록 비우기')
        self.clear_button.clicked.connect(self.clear_list)
        button_layout.addWidget(self.clear_button)

        self.sort_button = QPushButton('이름 순 정렬')
        self.sort_button.clicked.connect(self.toggle_sort_list)
        button_layout.addWidget(self.sort_button)

        self.reverse_button = QPushButton('순서 반대로')
        self.reverse_button.clicked.connect(self.reverse_list_order)
        button_layout.addWidget(self.reverse_button)

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

    # Update button
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

    def remove_selected_files(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    def toggle_sort_list(self):
        if self.sort_ascending:
            self.sort_list_by_name(reverse=False)
            self.sort_button.setText('이름 역순 정렬')
        else:
            self.sort_list_by_name(reverse=True)
            self.sort_button.setText('이름 순 정렬')
        self.sort_ascending = not self.sort_ascending

    def sort_list_by_name(self, reverse=False):
        print("sort_list_by_name 함수 시작")
        
        # 현재 모든 파일 경로 가져오기
        file_paths = self.list_widget.get_all_file_paths()
        print(f"현재 아이템 수: {len(file_paths)}")
        
        # 파일 경로 정렬
        sorted_file_paths = sorted(file_paths, key=lambda x: os.path.basename(x).lower(), reverse=reverse)
        print(f"정렬된 아이템 순서: {sorted_file_paths}")
        
        # 정렬된 파일 경로로 리스트 위젯 업데이트
        self.list_widget.update_items(sorted_file_paths)
        
        print("sort_list_by_name 함수 종료")

    def clear_list(self):
        reply = QMessageBox.question(self, '목록 비우기',
                                     "정말로 목록을 비우시겠습니까?",
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.list_widget.clear()
            self.preview_label.clear()  # Also clear the preview

    def set_icon(self):
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        icon_path = os.path.join(base_path, 'icon.png')
        self.setWindowIcon(QIcon(icon_path))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '파일 선택', '', '모든 파일 (*.*)')
        if files:
            self.list_widget.addItems(map(process_file, files))

    def reverse_list_order(self):
        print("reverse_list_order 함수 시작")
        
        # 현재 모든 파일 경로 가져오기
        file_paths = self.list_widget.get_all_file_paths()
        print(f"현재 아이템 수: {len(file_paths)}")
        
        # 파일 경로 순서 뒤집기
        reversed_file_paths = list(reversed(file_paths))
        print(f"뒤집힌 아이템 순서: {reversed_file_paths}")
        
        # 뒤집힌 파일 경로로 리스트 위젯 업데이트
        self.list_widget.update_items(reversed_file_paths)
        
        print("reverse_list_order 함수 종료")

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
        print(f"toggle_2f_offset called: state={state}, use_2f_offset={self.use_2f_offset}")

    def get_encoding_parameters(self):
        output_file = self.output_edit.text()
        if not output_file:
            QMessageBox.warning(self, "경고", "출력 경로를 지정해주세요.")
            return None

        if self.list_widget.count() == 0:
            QMessageBox.warning(self, "경고", "입력 파일을 추가해주세요.")
            return None

        input_files = []
        trim_values = []
        for i in range(self.list_widget.count()):
            list_item = self.list_widget.item(i)
            item_widget = self.list_widget.itemWidget(list_item)
            file_path = item_widget.file_path
            trim_start, trim_end = item_widget.get_trim_values()
            input_files.append(file_path)
            trim_values.append((trim_start, trim_end))

        return (output_file, self.encoding_options, self.debug_checkbox.isChecked(), input_files, trim_values)

    def browse_output(self):
        last_path = self.settings.value("last_output_path", "")
        output_file, _ = QFileDialog.getSaveFileName(self, '출력 파일 저장', last_path, 'MP4 파일 (*.mp4)')
        if output_file:
            self.output_edit.setText(output_file)
            self.settings.setValue("last_output_path", output_file)

    def start_encoding(self):
        params = self.get_encoding_parameters()
        if params:
            output_file, encoding_options, debug_mode, input_files, trim_values = params

            self.update_encoding_options(encoding_options)

            try:
                concat_videos(
                    input_files,
                    output_file,
                    encoding_options,
                    debug_mode=debug_mode,
                    trim_values=trim_values
                )
                QMessageBox.information(self, "완료", "인코딩이 완료되었습니다.")
            except Exception as e:
                QMessageBox.critical(self, "에러", f"인코딩 중 에러가 발생했습니다:\n{e}")

    def get_media_duration(self, file_path):
        # 미디어 파일의 길이를 가져오는 함수 구현
        try:
            import subprocess
            command = [
                os.path.join(os.path.dirname(FFMPEG_PATH), 'ffprobe'),
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                file_path
            ]
            result = subprocess.run(command, capture_output=True, text=True)
            duration_str = result.stdout.strip()
            return float(duration_str)
        except Exception as e:
            print(f"get_media_duration 오류: {e}")
            return None

    def update_encoding_options(self, encoding_options):
        if self.use_custom_framerate:
            encoding_options["-r"] = str(self.framerate)
        if self.use_custom_resolution:
            encoding_options["-s"] = f"{self.video_width}x{self.video_height}"

    def toggle_debug_mode(self, state):
        is_debug = state == Qt.CheckState.Checked.value
        self.clear_settings_button.setVisible(is_debug)
        print(f"toggle_debug_mode called: state={state}, is_debug={is_debug}")

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
            file_path = self.list_widget.get_selected_file_path()
            if file_path:
                self.stop_current_preview()

                if is_video_file(file_path):
                    self.show_video_preview(file_path)
                elif is_image_file(file_path):
                    self.show_image_preview(file_path)
                else:
                    print(f"Unsupported file format: {file_path}")
            else:
                self.preview_label.clear()
        except Exception as e:
            print(f"update_preview error: {str(e)}")

    def stop_current_preview(self):
        if self.video_thread:
            self.video_thread.stop()
            self.video_thread.wait()
            self.video_thread = None  # Reset the video thread

    def show_video_preview(self, file_path: str):
        self.create_video_thread()
        self.play_button.setEnabled(True)

        self.video_thread.get_video_info()
        self.video_thread.wait()
        first_frame = self.video_thread.get_video_frame(0)
        if first_frame and not first_frame.isNull():
            self.update_video_frame(first_frame)
        else:
            self.preview_label.clear()

    def show_image_preview(self, file_path: str):
        if '%' in file_path:
            file_path = get_first_sequence_file(file_path)
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

    def set_video_info(self, width: int, height: int):
        self.current_video_width = width
        self.current_video_height = height

    def toggle_play(self):
        print("toggle_play 호출됨")
        selected_item = self.list_widget.currentItem()
        if not selected_item:
            print("선택된 아이템이 없습니다.")
            QMessageBox.warning(self, "경고", "재생할 파일을 선택해주세요.")
            return

        if self.video_thread:
            print(f"비디오 스레드 상태: is_playing = {self.video_thread.is_playing}")
            if not self.video_thread.is_playing:
                print("재생 시작")
                self.start_video_playback()
            else:
                print("재생 정지")
                self.stop_video_playback()
        else:
            print("비디오 스레드 생성")
            self.create_video_thread()
            self.start_video_playback()

    def create_video_thread(self):
        file_path = self.list_widget.get_selected_file_path()
        if file_path:
            self.video_thread = VideoThread(file_path)
            self.video_thread.frame_ready.connect(self.update_video_frame)
            self.video_thread.finished.connect(self.on_video_finished)
            self.video_thread.video_info_ready.connect(self.set_video_info)

    def start_video_playback(self):
        print("start_video_playback 호출됨")
        if not self.video_thread:
            self.create_video_thread()
        
        self.video_thread.is_playing = True
        current_speed = self.speed_slider.value() / 100
        print(f"현재 재생 속도: {current_speed}")
        self.video_thread.set_speed(current_speed)
        self.video_thread.start()
        print("비디오 스레드 시작됨")
        self.play_button.setText('정지')
        print("재생 버튼 텍스트 변경: '정지'")

    def stop_video_playback(self):
        print("stop_video_playback 호출됨")
        if self.video_thread:
            self.video_thread.stop()
            self.play_button.setText('재생')

    def on_video_finished(self):
        print("on_video_finished 호출됨")
        if self.video_thread:
            self.video_thread.stop()
            self.play_button.setText('재생')

    def change_speed(self):
        print("change_speed 호출됨")
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

    def toggle_framerate(self, state):
        self.use_custom_framerate = state == Qt.CheckState.Checked.value
        self.framerate_spinbox.setEnabled(self.use_custom_framerate)
        if not self.use_custom_framerate:
            self.encoding_options.pop("-r", None)
        print(f"toggle_framerate called: state={state}, use_custom_framerate={self.use_custom_framerate}")

    def toggle_resolution(self, state):
        self.use_custom_resolution = state == Qt.CheckState.Checked.value
        self.width_edit.setEnabled(self.use_custom_resolution)
        self.height_edit.setEnabled(self.use_custom_resolution)
        if not self.use_custom_resolution:
            self.encoding_options.pop("-s", None)
        print(f"toggle_resolution called: state={state}, use_custom_resolution={self.use_custom_resolution}")

    def update_framerate(self, value):
        self.framerate = value
        if self.use_custom_framerate:
            self.encoding_options["-r"] = str(self.framerate)

    def update_resolution(self):
        self.video_width = self.width_edit.text()
        self.video_height = self.height_edit.text()
        if self.use_custom_resolution:
            self.encoding_options["-s"] = f"{self.video_width}x{self.video_height}"

    def closeEvent(self, event):
        # Save the current output path when the application closes
        self.settings.setValue("last_output_path", self.output_edit.text())
        super().closeEvent(event)

