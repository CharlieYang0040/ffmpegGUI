# gui.py

import os
import sys
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QComboBox, QAbstractItemView, QCheckBox, QLineEdit,
    QMessageBox, QSlider, QDoubleSpinBox, QListWidget, QListWidgetItem, QSpinBox,
    QProgressBar, QDialog, QVBoxLayout
)
from PySide6.QtCore import Qt, QSettings, QItemSelectionModel, Signal, QThread
from PySide6.QtGui import QCursor, QPixmap, QIcon, QIntValidator, QShortcut, QKeySequence

import ffmpeg
from ffmpeg_utils import concat_videos
from update import UpdateChecker
from commands import *
from drag_drop_list_widget import DragDropListWidget
from video_thread import VideoThread
from utils import (
    process_file,
    is_video_file,
    is_image_file,
    get_sequence_start_number,
    get_first_sequence_file,
    format_drag_to_output,
    DEBUG_MODE,
    get_debug_mode,
    set_debug_mode
)

class EncodingProgressDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("인코딩 진행 상황")
        self.setFixedSize(300, 100)

        layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.setLayout(layout)

    def update_progress(self, value):
        self.progress_bar.setValue(value)

class EncodingThread(QThread):
    progress_updated = Signal(int)
    encoding_finished = Signal()

    def __init__(self, concat_videos_func, *args, **kwargs):
        super().__init__()
        self.concat_videos_func = concat_videos_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        self.concat_videos_func(*self.args, **self.kwargs, progress_callback=self.progress_updated.emit)
        self.encoding_finished.emit()

class FFmpegGui(QWidget):
    def __init__(self):
        super().__init__()
        self.update_checker = UpdateChecker()
        self.init_attributes()
        # FFmpeg 경로 초기화 및 동기화
        self.init_shortcuts()
        self.init_ffmpeg_path()
        self.init_ui()
        self.position_window_near_mouse()
        self.setStyleSheet(self.get_unreal_style())
        self.set_icon()
        # self.hide_console()  # Hide console window on startup
        self.sort_ascending = True  # Variable to store sort order
        self.global_trim_start = 0
        self.global_trim_end = 0

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
            "c:v": "libx264",
            "pix_fmt": "yuv420p",
            "colorspace": "bt709",
            "color_primaries": "bt709",
            "color_trc": "bt709",
            "color_range": "limited"
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
        self.undo_stack = []
        self.redo_stack = []

    def init_ffmpeg_path(self):
        try:
            # PyInstaller 번들 환경인지 확인
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
                self.default_ffmpeg_path = os.path.join(base_path, "libs", "ffmpeg-7.1-full_build", "bin", "ffmpeg.exe")
            else:
                # 개발 환경일 때의 기본 경로
                self.default_ffmpeg_path = r"\\192.168.2.215\Share_151\art\ffmpeg-7.1\bin\ffmpeg.exe"
            
            ffmpeg_path = self.settings.value("ffmpeg_path", self.default_ffmpeg_path)
            
            # 경로가 존재하는지 확인
            if not os.path.exists(ffmpeg_path):
                print(f"FFmpeg 경로를 찾을 수 없습니다: {ffmpeg_path}")
                # 번들링된 경로로 폴백
                if getattr(sys, 'frozen', False):
                    ffmpeg_path = self.default_ffmpeg_path
            
            # 모든 모듈에 FFmpeg 경로 동기화
            from video_thread import set_ffmpeg_path as set_video_thread_path
            from ffmpeg_utils import set_ffmpeg_path as set_ffmpeg_utils_path
            set_video_thread_path(ffmpeg_path)
            set_ffmpeg_utils_path(ffmpeg_path)
            
        except Exception as e:
            print(f"FFmpeg 경로 초기화 중 오류 발생: {e}")

    def init_shortcuts(self):
        # Ctrl+Z for undo
        undo_shortcut = QShortcut(QKeySequence.Undo, self)  # Ctrl+Z
        undo_shortcut.activated.connect(self.undo)
        
        # Ctrl+Shift+Z for redo
        redo_shortcut = QShortcut(QKeySequence.Redo, self)  # Ctrl+Shift+Z
        redo_shortcut.activated.connect(self.redo)

    def init_ui(self):
        self.setWindowTitle('ffmpegGUI by LHCinema')
        main_layout = QVBoxLayout(self)

        self.create_top_layout(main_layout)
        self.create_content_layout(main_layout)

        self.setGeometry(100, 100, 750, 600)
        self.setMinimumWidth(750)

        self.debug_checkbox.setChecked(get_debug_mode())

    def create_top_layout(self, main_layout):
        top_layout = QHBoxLayout()

        self.create_preview_area(top_layout)
        self.create_control_area(top_layout)

        main_layout.addLayout(top_layout)

    def create_preview_area(self, top_layout):
        self.preview_label = QLabel(alignment=Qt.AlignCenter)
        self.preview_label.setFixedSize(470, 270)
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
        self.play_button = QPushButton('▶️ 재생')
        self.play_button.clicked.connect(self.toggle_play)
        control_layout.addWidget(self.play_button)

    def create_speed_control(self, control_layout):
        speed_layout = QVBoxLayout()
        speed_label = QLabel("재생 속도:")
        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(20, 800)
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
        self.create_global_trim_control(offset_layout)  # 새로운 함수 추가

        self.offset_group.setLayout(offset_layout)
        control_layout.addWidget(self.offset_group)

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
        self.width_edit.setValidator(QIntValidator(320, 9999))
        self.width_edit.setText("1920")
        self.width_edit.setFixedWidth(60)  # Adjust width
        self.width_edit.setEnabled(False)

        self.height_edit = QLineEdit()
        self.height_edit.setValidator(QIntValidator(240, 9999))
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

    def create_global_trim_control(self, offset_layout):
        global_trim_layout = QVBoxLayout()  # QHBoxLayout에서 QVBoxLayout으로 변경
        self.global_trim_checkbox = QCheckBox("전체 앞뒤 트림:")
        self.global_trim_checkbox.setChecked(False)
        self.global_trim_checkbox.stateChanged.connect(self.toggle_global_trim)

        self.global_trim_start_spinbox = QSpinBox()
        self.global_trim_start_spinbox.setRange(0, 9999)
        self.global_trim_start_spinbox.setValue(0)
        self.global_trim_start_spinbox.setEnabled(False)
        self.global_trim_start_spinbox.valueChanged.connect(self.update_global_trim_start)

        self.global_trim_end_spinbox = QSpinBox()
        self.global_trim_end_spinbox.setRange(0, 9999)
        self.global_trim_end_spinbox.setValue(0)
        self.global_trim_end_spinbox.setEnabled(False)
        self.global_trim_end_spinbox.valueChanged.connect(self.update_global_trim_end)

        global_trim_layout.addWidget(self.global_trim_checkbox)
        
        spinbox_layout = QHBoxLayout()
        
        start_layout = QVBoxLayout()
        start_layout.addWidget(QLabel("시작:"))
        start_layout.addWidget(self.global_trim_start_spinbox)
        
        end_layout = QVBoxLayout()
        end_layout.addWidget(QLabel("끝:"))
        end_layout.addWidget(self.global_trim_end_spinbox)
        
        spinbox_layout.addLayout(start_layout)
        spinbox_layout.addLayout(end_layout)
        
        global_trim_layout.addLayout(spinbox_layout)

        offset_layout.addLayout(global_trim_layout)

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
        self.create_undo_redo_buttons(left_layout)
        content_layout.addLayout(left_layout)

    def create_list_widget(self, left_layout):
        # Checkbox layout
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setAlignment(Qt.AlignLeft)
        
        # Preview mode checkbox
        self.preview_mode_checkbox = QCheckBox("미리보기")
        self.preview_mode_checkbox.setChecked(True)  # Default is checked
        checkbox_layout.addWidget(self.preview_mode_checkbox)
        
        # Auto naming checkbox
        self.auto_naming_checkbox = QCheckBox("자동 네이밍") 
        self.auto_naming_checkbox.setChecked(False)  # Default is unchecked
        checkbox_layout.addWidget(self.auto_naming_checkbox)
        
        left_layout.addLayout(checkbox_layout)

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

        self.add_button = QPushButton('➕ 파일 추가')
        self.add_button.clicked.connect(self.add_files)
        button_layout.addWidget(self.add_button)

        self.remove_button = QPushButton('➖ 파일 제거')
        self.remove_button.clicked.connect(self.remove_selected_files)
        button_layout.addWidget(self.remove_button)

        self.clear_button = QPushButton('🗑️ 목록 비우기')
        self.clear_button.clicked.connect(self.clear_list)
        button_layout.addWidget(self.clear_button)

        self.sort_button = QPushButton('🔠 이름 순 정렬')
        self.sort_button.clicked.connect(self.toggle_sort_list)
        button_layout.addWidget(self.sort_button)

        self.reverse_button = QPushButton('🔃 순서 반대로')
        self.reverse_button.clicked.connect(self.reverse_list_order)
        button_layout.addWidget(self.reverse_button)

        self.move_up_button = QPushButton('🔼 위로 이동')
        self.move_up_button.clicked.connect(self.move_item_up)
        button_layout.addWidget(self.move_up_button)

        self.move_down_button = QPushButton('🔽 아래로 이동')
        self.move_down_button.clicked.connect(self.move_item_down)
        button_layout.addWidget(self.move_down_button)

        left_layout.addLayout(button_layout)

    def create_options_group(self, left_layout):
        self.options_group = QGroupBox("인코딩 옵션")
        options_layout = QVBoxLayout()

        encoding_options = [
            ("c:v", ["libx264", "libx265", "none"]),
            ("pix_fmt", ["yuv420p", "yuv422p", "yuv444p", "none"]),
            ("colorspace", ["bt709", "bt2020nc", "none"]),
            ("color_primaries", ["bt709", "bt2020", "none"]),
            ("color_trc", ["bt709", "bt2020-10", "none"]),
            ("color_range", ["limited", "full", "none"])
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
        self.output_edit.setAcceptDrops(True)  # 드롭 허용
        
        # QLineEdit을 상속받아 드롭 이벤트와 텍스트 변경 처리
        class DroppableLineEdit(QLineEdit):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.old_text = ""  # 이전 텍스트 저장용

            def focusInEvent(self, event):
                # 포커스를 얻을 때 현재 텍스트 저장
                self.old_text = self.text()
                super().focusInEvent(event)

            def dragEnterEvent(self, event):
                if event.mimeData().hasText():
                    event.acceptProposedAction()

            def dropEvent(self, event):
                file_name = event.mimeData().text()
                current_dir = os.path.dirname(self.text()) if self.text() else ""
                if not current_dir:
                    current_dir = os.path.expanduser("~")
                new_path = os.path.join(current_dir, f"{file_name}.mp4")
                
                # Command 생성 및 실행
                if hasattr(self.parent(), 'execute_command'):
                    command = ChangeOutputPathCommand(self, self.text(), new_path)
                    self.parent().execute_command(command)
                else:
                    self.setText(new_path)
                
                event.acceptProposedAction()

            def focusOutEvent(self, event):
                current_text = self.text()
                if current_text and not current_text.lower().endswith('.mp4'):
                    new_text = current_text + '.mp4'
                    
                    # 텍스트가 실제로 변경되었을 때만 Command 실행
                    if new_text != self.old_text and hasattr(self.parent(), 'execute_command'):
                        command = ChangeOutputPathCommand(self, self.old_text, new_text)
                        self.parent().execute_command(command)
                    else:
                        self.setText(new_text)
                
                super().focusOutEvent(event)

        # 기존 QLineEdit을 DroppableLineEdit으로 교체
        self.output_edit = DroppableLineEdit()
        self.output_edit.setText(self.settings.value("last_output_path", ""))
        
        self.output_browse = QPushButton("찾아보기")
        self.output_browse.clicked.connect(self.browse_output)
        output_layout.addWidget(self.output_label)
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(self.output_browse)
        left_layout.addLayout(output_layout)

        # FFmpeg 경로 입력 레이아웃 추가
        ffmpeg_layout = QHBoxLayout()
        self.ffmpeg_label = QLabel("FFmpeg 경로:")
        self.ffmpeg_edit = QLineEdit()
        self.ffmpeg_edit.setText(self.settings.value("ffmpeg_path", self.default_ffmpeg_path))
        self.ffmpeg_edit.setAcceptDrops(False)
        self.ffmpeg_browse = QPushButton("찾아보기")
        self.ffmpeg_browse.clicked.connect(self.browse_ffmpeg)
        ffmpeg_layout.addWidget(self.ffmpeg_label)
        ffmpeg_layout.addWidget(self.ffmpeg_edit)
        ffmpeg_layout.addWidget(self.ffmpeg_browse)
        left_layout.addLayout(ffmpeg_layout)

    def browse_ffmpeg(self):
        ffmpeg_path, _ = QFileDialog.getOpenFileName(
            self, 'FFmpeg 실행 파일 선택', 
            self.ffmpeg_edit.text(), 
            'FFmpeg (ffmpeg.exe);;모든 파일 (*.*)'
        )
        if ffmpeg_path:
            self.ffmpeg_edit.setText(ffmpeg_path)
            self.settings.setValue("ffmpeg_path", ffmpeg_path)
            # video_thread.py와 ffmpeg_utils.py 모두에 경로 설정
            from video_thread import set_ffmpeg_path as set_video_thread_path
            from ffmpeg_utils import set_ffmpeg_path as set_ffmpeg_utils_path
            set_video_thread_path(ffmpeg_path)
            set_ffmpeg_utils_path(ffmpeg_path)

    def create_encode_button(self, left_layout):
        self.encode_button = QPushButton('🎬 인코딩 시작')
        self.encode_button.clicked.connect(self.start_encoding)
        left_layout.addWidget(self.encode_button)

    # Update button
    def create_update_button(self, left_layout):
        update_layout = QHBoxLayout()
        self.update_button = QPushButton('🔄 업데이트 확인')
        self.update_button.clicked.connect(self.update_checker.check_for_updates)
        update_layout.addWidget(self.update_button)
        left_layout.addLayout(update_layout)

    def create_undo_redo_buttons(self, left_layout):
        # Add undo/redo buttons
        undo_redo_layout = QHBoxLayout()
        undo_redo_layout.setAlignment(Qt.AlignLeft)
        
        self.undo_button = QPushButton('↩️ 실행취소')
        self.undo_button.clicked.connect(self.undo)
        self.undo_button.setEnabled(False)
        self.undo_button.setFixedWidth(100)
        undo_redo_layout.addWidget(self.undo_button)

        self.redo_button = QPushButton('↪️ 다시실행')
        self.redo_button.clicked.connect(self.redo)
        self.redo_button.setEnabled(False)
        self.redo_button.setFixedWidth(100)
        undo_redo_layout.addWidget(self.redo_button)
        
        undo_redo_layout.addStretch()

        self.debug_checkbox = QCheckBox("디버그 모드")
        self.debug_checkbox.setChecked(False)
        self.debug_checkbox.stateChanged.connect(self.toggle_debug_mode)
        undo_redo_layout.addStretch(1)
        undo_redo_layout.addWidget(self.debug_checkbox)

        self.clear_settings_button = QPushButton("설정 초기화")
        self.clear_settings_button.clicked.connect(self.clear_settings)
        self.clear_settings_button.hide()
        undo_redo_layout.addWidget(self.clear_settings_button)
        left_layout.addLayout(undo_redo_layout)

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

    def toggle_sort_list(self):
        print("[toggle_sort_list] 시작")
        old_order = self.list_widget.get_all_file_paths()
        
        if self.sort_ascending:
            new_order = sorted(old_order, key=lambda x: os.path.basename(x).lower())
            self.sort_button.setText('🔠 이름 역순 정렬')
        else:
            new_order = sorted(old_order, key=lambda x: os.path.basename(x).lower(), reverse=True)
            self.sort_button.setText('🔠 이름 순 정렬')
        
        if old_order != new_order:
            command = ReorderItemsCommand(self.list_widget, old_order, new_order)
            self.execute_command(command)
        
        self.sort_ascending = not self.sort_ascending
        print("[toggle_sort_list] 종료")

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
        
        # ReorderItemsCommand 생성 및 실행
        if file_paths != reversed_file_paths:
            print("순서 변경 명령 실행")
            command = ReorderItemsCommand(self.list_widget, file_paths, reversed_file_paths)
            self.execute_command(command)
            
            # 뒤집힌 파일 경로로 리스트 위젯 업데이트
            self.list_widget.update_items(reversed_file_paths)
        
        print("reverse_list_order 함수 종료")

    def move_item_up(self):
        self.move_selected_items(-1)

    def move_item_down(self):
        self.move_selected_items(1)

    def move_selected_items(self, direction):
        print("[move_selected_items] 시작")
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            print("[move_selected_items] 선택된 아이템 없음")
            return

        # 이동 전 순서 저장
        old_order = self.list_widget.get_all_file_paths()
        print(f"[move_selected_items] 이동 전 순서: {old_order}")

        # 아이템 이동
        items_to_move = selected_items if direction < 0 else reversed(selected_items)
        for item in items_to_move:
            current_row = self.list_widget.row(item)
            new_row = current_row + direction
            if 0 <= new_row < self.list_widget.count() and self.list_widget.item(new_row) not in selected_items:
                taken_item = self.list_widget.takeItem(current_row)
                self.list_widget.insertItem(new_row, taken_item)
                self.list_widget.setCurrentItem(taken_item, QItemSelectionModel.Select)

        # 이동 후 새로운 순서 가져오기
        new_order = self.list_widget.get_all_file_paths()
        print(f"[move_selected_items] 이동 후 순서: {new_order}")

        # 순서가 변경된 경우에만 command 실행 및 업데이트
        if old_order != new_order:
            print("[move_selected_items] 순서 변경 명령 실행")
            command = ReorderItemsCommand(self.list_widget, old_order, new_order)
            self.execute_command(command)
            
            # 전체 리스트 업데이트
            print("[move_selected_items] 아이템 목록 업데이트")
            self.list_widget.update_items(new_order)

        print("[move_selected_items] 종료")

    def update_option(self, option: str, value: str):
        if value != "none":
            self.encoding_options[option] = value
        else:
            self.encoding_options.pop(option, None)

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
        # FFmpeg 경로 설정
        from video_thread import set_ffmpeg_path as set_video_thread_path
        from ffmpeg_utils import set_ffmpeg_path as set_ffmpeg_utils_path
        ffmpeg_path = self.ffmpeg_edit.text()
        set_video_thread_path(ffmpeg_path)
        set_ffmpeg_utils_path(ffmpeg_path)
        
        params = self.get_encoding_parameters()
        if params:
            output_file, encoding_options, debug_mode, input_files, trim_values = params

            self.update_encoding_options(encoding_options)

            try:
                # ordered input 로직 추가
                ordered_input = []
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    item_widget = self.list_widget.itemWidget(item)
                    file_path = item_widget.file_path
                    trim_start, trim_end = item_widget.get_trim_values()
                    ordered_input.append((file_path, trim_start, trim_end))

                self.progress_dialog = EncodingProgressDialog(self)
                self.progress_dialog.show()

                self.encoding_thread = EncodingThread(
                    concat_videos,
                    [item[0] for item in ordered_input],  # input_files
                    output_file,
                    encoding_options,
                    debug_mode=debug_mode,
                    trim_values=[(item[1], item[2]) for item in ordered_input],  # trim_values
                    global_trim_start=self.global_trim_start,
                    global_trim_end=self.global_trim_end
                )
                self.encoding_thread.progress_updated.connect(self.progress_dialog.update_progress)
                self.encoding_thread.encoding_finished.connect(self.on_encoding_finished)
                self.encoding_thread.start()

            except Exception as e:
                QMessageBox.critical(self, "에러", f"인코딩 중 에러가 발생했습니다:\n{e}")

    def on_encoding_finished(self):
        self.progress_dialog.close()
        QMessageBox.information(self, "완료", "인코딩이 완료되었습니다.")

    def get_media_duration(self, file_path):
        try:
            probe = ffmpeg.probe(file_path)
            duration = float(probe['streams'][0]['duration'])
            return duration
        except Exception as e:
            print(f"get_media_duration 오류: {e}")
            return None

    def update_encoding_options(self, encoding_options):
        if self.use_custom_framerate:
            encoding_options["-r"] = str(self.framerate)
        if self.use_custom_resolution:
            encoding_options["-s"] = f"{self.video_width}x{self.video_height}"

    def toggle_debug_mode(self, state):
        """디버그 모드 토글 함수"""
        is_checked = state == Qt.CheckState.Checked.value
        current_debug_mode = set_debug_mode(is_checked)  # 설정된 값 받기
        self.clear_settings_button.setVisible(current_debug_mode)
        print(f"[toggle_debug_mode] 디버그 모드 변경: {is_checked}")
        print(f"[toggle_debug_mode] 현재 DEBUG_MODE: {get_debug_mode()}")

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
            self.ffmpeg_edit.clear()

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
        debug_print("toggle_play 호출됨")
        selected_item = self.list_widget.currentItem()
        if not selected_item:
            print("선택된 아이템이 없습니다.")
            QMessageBox.warning(self, "경고", "재생할 파일을 선택해주세요.")
            return

        if not self.video_thread or not self.video_thread.is_playing:
            self.start_video_playback()
        else:
            self.stop_video_playback()

    def create_video_thread(self):
        file_path = self.list_widget.get_selected_file_path()
        if file_path:
            if self.video_thread:
                self.stop_video_playback()
            self.video_thread = VideoThread(file_path)
            self.video_thread.frame_ready.connect(self.update_video_frame)
            self.video_thread.finished.connect(self.on_video_finished)
            self.video_thread.video_info_ready.connect(self.set_video_info)

    def start_video_playback(self):
        if self.video_thread and self.video_thread.isRunning():
            self.video_thread.reset()
            self.video_thread.terminate()
            self.video_thread.wait()
        debug_print("start_video_playback 호출됨")
        if not self.video_thread:
            self.create_video_thread()
        
        self.video_thread.is_playing = True
        current_speed = self.speed_slider.value() / 100
        print(f"현재 재생 속도: {current_speed}")
        self.video_thread.set_speed(current_speed*1.5)
        self.video_thread.start()
        print("비디오 스레드 시작됨")
        self.play_button.setText('⏹️ 정지')
        debug_print("재생 버튼 텍스트 변경: '정지'")

    def stop_video_playback(self):
        if not self.video_thread or not self.video_thread.is_playing:
            return
        self.video_thread.stop()
        self.video_thread.wait()  # 스레드가 완전히 종료될 때까지 대기
        self.update_ui_after_stop()
        print("재생 정지")

    def on_video_finished(self):
        if self.video_thread.is_playing:
            return
        debug_print("on_video_finished 호출됨")
        self.stop_video_playback()
        self.update_ui_after_stop()
        self.video_thread.reset()  # 스레드 상태 초기화

    def update_ui_after_stop(self):
        debug_print("update_ui_after_stop 호출됨")
        self.video_thread.is_playing = False
        self.play_button.setText('▶️ 재생')
        # UI 업데이트 로직

    def change_speed(self):
        self.speed = self.speed_slider.value() / 100
        self.speed_value_label.setText(f"{self.speed:.1f}x")
        if self.video_thread:
            self.video_thread.set_speed(self.speed*1.5)

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

    def toggle_global_trim(self, state):
        is_enabled = state == Qt.CheckState.Checked.value
        self.global_trim_start_spinbox.setEnabled(is_enabled)
        self.global_trim_end_spinbox.setEnabled(is_enabled)
        print(f"toggle_global_trim called: state={state}, is_enabled={is_enabled}")

    def update_global_trim_start(self, value):
        self.global_trim_start = value
        print(f"Global trim start updated: {self.global_trim_start}")

    def update_global_trim_end(self, value):
        self.global_trim_end = value
        print(f"Global trim end updated: {self.global_trim_end}")

    def closeEvent(self, event):
        # Save the current output path when the application closes
        self.settings.setValue("last_output_path", self.output_edit.text())
        self.stop_video_playback()
        super().closeEvent(event)

    def execute_command(self, command: Command):
        print("[execute_command] 명령 실행")
        command.execute()
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self.update_undo_redo_buttons()
        print("[execute_command] 완료")

    def undo(self):
        print("[undo] 실행 취소 시작")
        if self.undo_stack:
            command = self.undo_stack.pop()
            command.undo()
            self.redo_stack.append(command)
            self.update_undo_redo_buttons()
        print("[undo] 실행 취소 완료")

    def redo(self):
        print("[redo] 다시 실행 시작")
        if self.redo_stack:
            command = self.redo_stack.pop()
            command.execute()
            self.undo_stack.append(command)
            self.update_undo_redo_buttons()
        print("[redo] 다시 실행 완료")

    def update_undo_redo_buttons(self):
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.redo_button.setEnabled(bool(self.redo_stack))

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, '파일 선택', '', '모든 파일 (*.*)')
        if files:
            processed_files = list(map(process_file, files))
            command = AddItemsCommand(self.list_widget, processed_files)
            self.execute_command(command)
            
            # 자동 네이밍이 켜져있고, 파일이 추가되었을 때
            if self.auto_naming_checkbox.isChecked() and processed_files:
                # 첫 번째 파일의 이름으로 출력 경로 설정
                first_file = processed_files[0]
                output_name = format_drag_to_output(first_file)
                
                # 현재 출력 경로의 디렉토리 유지
                current_dir = os.path.dirname(self.output_edit.text())
                if not current_dir:  # 디렉토리가 비어있으면 기본값 사용
                    current_dir = os.path.expanduser("~")
                
                # 새로운 출력 경로 설정
                new_output_path = os.path.join(current_dir, f"{output_name}.mp4")
                self.output_edit.setText(new_output_path)

    def remove_selected_files(self):
        print("[remove_selected_files] 시작")
        selected_items = self.list_widget.selectedItems()
        if selected_items:
            command = RemoveItemsCommand(self.list_widget, selected_items)
            self.execute_command(command)
        print("[remove_selected_files] 종료")

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Delete):
            self.remove_selected_files()
        else:
            super().keyPressEvent(event)

    def clear_list(self):
        print("[clear_list] 시작")
        reply = QMessageBox.question(
            self, '목록 비우기',
            "정말로 목록을 비우시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            if self.list_widget.count() > 0:
                command = ClearListCommand(self.list_widget)
                self.execute_command(command)
                self.preview_label.clear()
        print("[clear_list] 종료")