# gui_refactor.py

import os
import sys
import subprocess
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QComboBox, QAbstractItemView, QCheckBox, QLineEdit,
    QMessageBox, QSlider, QDoubleSpinBox, QSpinBox,
    QProgressBar, QDialog, QPushButton, QListWidgetItem, QMainWindow, QTabWidget
)
from PySide6.QtCore import Qt, QSettings, QItemSelectionModel, Signal, QThread, QTimer, QTime
from PySide6.QtGui import QCursor, QPixmap, QIcon, QIntValidator, QShortcut, QKeySequence

from ffmpeg_utils import process_all_media
from ffmpeg_utils import set_ffmpeg_path as set_ffmpeg_utils_path
from update import UpdateChecker
from commands import RemoveItemsCommand, ReorderItemsCommand, ClearListCommand, AddItemsCommand, Command
from drag_drop_list_widget import DragDropListWidget
from droppable_line_edit import DroppableLineEdit
from video_thread import VideoThread
from video_thread import set_ffmpeg_path as set_video_thread_path
from utils import (
    process_file,
    is_video_file,
    is_image_file,
    get_first_sequence_file,
    ffmpeg_manager,
    get_debug_mode,
    set_debug_mode,
    set_logger_level,
    process_image_file
)
from list_widget_item import ListWidgetItem
from tab_list_widget import TabListWidget

# 로깅 설정
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

from PySide6.QtCore import QTimer, QTime

class EncodingProgressDialog(QDialog):
    """
    인코딩 진행 상황을 표시하는 다이얼로그
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("인코딩 진행 상황")
        self.setFixedSize(350, 180)  # 높이를 늘려서 에러 메시지 표시 공간 확보

        layout = QVBoxLayout()
        
        # 상태 레이블 추가
        self.status_label = QLabel("처리 중...")
        layout.addWidget(self.status_label)
        
        # 진행 바
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        # 현재 작업 표시 레이블
        self.current_task_label = QLabel("준비 중...")
        layout.addWidget(self.current_task_label)

        # 경과 시간 레이블
        self.elapsed_time_label = QLabel("경과 시간: 00:00:00")
        layout.addWidget(self.elapsed_time_label)

        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_elapsed_time)
        self.start_time = QTime()
        self.is_error = False

    def start_timer(self):
        self.start_time = QTime.currentTime()
        self.timer.start(1000)  # 1초마다 업데이트

    def stop_timer(self):
        self.timer.stop()

    def update_elapsed_time(self):
        if not self.is_error:
            elapsed = self.start_time.secsTo(QTime.currentTime())
            elapsed_time_str = QTime(0, 0).addSecs(elapsed).toString("hh:mm:ss")
            self.elapsed_time_label.setText(f"경과 시간: {elapsed_time_str}")

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def update_task(self, task_description):
        self.current_task_label.setText(task_description)

    def show_error(self, error_message):
        self.is_error = True
        self.stop_timer()
        self.status_label.setText("에러 발생!")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.current_task_label.setText(error_message)
        self.current_task_label.setStyleSheet("color: red;")


class EncodingThread(QThread):
    """
    인코딩 작업을 별도의 스레드에서 실행하기 위한 클래스
    """
    progress_updated = Signal(int)
    task_updated = Signal(str)
    encoding_finished = Signal()
    encoding_error = Signal(str)

    def __init__(self, process_all_media_func, *args, **kwargs):
        super().__init__()
        self.process_all_media_func = process_all_media_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.task_updated.emit("인코딩 준비 중...")
            self.process_all_media_func(
                *self.args, 
                **self.kwargs, 
                progress_callback=self.progress_updated.emit,
                task_callback=self.task_updated.emit
            )
            self.encoding_finished.emit()
        except Exception as e:
            error_message = str(e)
            logger.exception("인코딩 중 오류 발생")
            self.encoding_error.emit(error_message)


class EncodingOptionsDialog(QDialog):
    def __init__(self, parent=None, encoding_options=None):
        super().__init__(parent)
        self.setWindowTitle("인코딩 옵션")
        self.encoding_options = encoding_options or {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # 인코딩 옵션 그룹
        options_group = QGroupBox("인코딩 옵션")
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

        options_group.setLayout(options_layout)
        layout.addWidget(options_group)

        # 확인/취소 버튼
        button_box = QHBoxLayout()
        ok_button = QPushButton("확인")
        cancel_button = QPushButton("취소")
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_box.addWidget(ok_button)
        button_box.addWidget(cancel_button)
        layout.addLayout(button_box)

    def create_option_widget(self, layout, option, values):
        hbox = QHBoxLayout()
        label = QLabel(option)
        combo = QComboBox()
        combo.addItems(values)
        current_value = self.encoding_options.get(option, values[0])
        combo.setCurrentText(current_value)
        hbox.addWidget(label)
        hbox.addWidget(combo)
        layout.addLayout(hbox)
        self.option_widgets[option] = combo

    def get_options(self):
        options = {}
        for option, combo in self.option_widgets.items():
            if combo.currentText() != "none":
                options[option] = combo.currentText()
        return options


class FFmpegGui(QWidget):
    """
    FFmpeg GUI 메인 클래스
    """
    def __init__(self):
        super().__init__()
        self.settings = QSettings('LHCinema', 'ffmpegGUI')
        
        # FFmpeg 경로 초기화
        self.default_ffmpeg_path = ffmpeg_manager.ensure_ffmpeg_exists()
        if not self.default_ffmpeg_path:
            QMessageBox.critical(self, "오류", "FFmpeg를 찾을 수 없습니다.")
            sys.exit(1)
            
        # 저장된 FFmpeg 경로 또는 기본 경로 사용
        saved_ffmpeg_path = self.settings.value("ffmpeg_path", "")
        self.current_ffmpeg_path = saved_ffmpeg_path if os.path.exists(saved_ffmpeg_path) else self.default_ffmpeg_path
        
        # FFmpeg 경로 설정
        set_video_thread_path(self.current_ffmpeg_path)
        set_ffmpeg_utils_path(self.current_ffmpeg_path)

        self.init_attributes()
        self.init_shortcuts()
        self.init_ui()
        self.position_window_near_mouse()
        self.setStyleSheet(self.get_unreal_style())
        self.set_icon()
        self.sort_ascending = True
        self.global_trim_start = 0
        self.global_trim_end = 0

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
        self.update_checker = UpdateChecker()

    def setup_update_checker(self):
        self.update_checker.update_error.connect(self.show_update_error)
        self.update_checker.update_available.connect(self.show_update_available)
        self.update_checker.no_update.connect(self.show_no_update)
        self.update_checker.update_button = self.update_button

    def init_ffmpeg_path(self):
        try:
            if getattr(sys, 'frozen', False):
                base_path = sys._MEIPASS
                self.default_ffmpeg_path = os.path.join(base_path, "libs", "ffmpeg-7.1-full_build", "bin", "ffmpeg.exe")
            else:
                self.default_ffmpeg_path = r"\\192.168.2.215\Share_151\art\ffmpeg-7.1\bin\ffmpeg.exe"

            ffmpeg_path = self.settings.value("ffmpeg_path", self.default_ffmpeg_path)
            
            # ffmpeg_path가 비어있거나 None인 경우 기본값으로 초기화
            if not ffmpeg_path or ffmpeg_path.strip() == "":
                logger.info("FFmpeg 경로가 비어있어 기본값으로 초기화합니다.")
                ffmpeg_path = self.default_ffmpeg_path
                self.settings.setValue("ffmpeg_path", ffmpeg_path)

            if not os.path.exists(ffmpeg_path):
                logger.info(f"FFmpeg 경로를 찾을 수 없습니다: {ffmpeg_path}")
                if getattr(sys, 'frozen', False):
                    ffmpeg_path = self.default_ffmpeg_path

            # 모든 모듈에 FFmpeg 경로 동기화
            set_video_thread_path(ffmpeg_path)
            set_ffmpeg_utils_path(ffmpeg_path)
            logger.info(f"FFmpeg 경로가 설정되었습니다: {ffmpeg_path}")

        except Exception as e:
            logger.error(f"FFmpeg 경로 초기화 중 오류 발생: {e}")

    def init_shortcuts(self):
        undo_shortcut = QShortcut(QKeySequence.Undo, self)
        undo_shortcut.activated.connect(self.undo)

        redo_shortcut = QShortcut(QKeySequence.Redo, self)
        redo_shortcut.activated.connect(self.redo)

    def init_ui(self):
        windowTitle = 'ffmpegGUI by LHCinema'
        self.setWindowTitle(windowTitle)
        main_layout = QVBoxLayout(self)

        self.create_top_layout(main_layout)
        self.create_content_layout(main_layout)
        self.setup_update_checker()
        self.setGeometry(100, 100, 750, 600)
        self.setMinimumWidth(750)

        self.debug_checkbox.setChecked(get_debug_mode())
        set_logger_level(self.debug_checkbox.isChecked())
        print(windowTitle)
        logger.info(f"UI 초기화 완료")
        self.print_settings_info()

    def print_settings_info(self):
        """설정 값들의 정보를 로깅"""
        all_keys = self.settings.allKeys()
        logger.info("현재 설정 값 목록:")
        for key in all_keys:
            value = self.settings.value(key)
            logger.info(f"{key}: {value}")

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
        self.create_global_trim_control(offset_layout)

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
        self.width_edit.setFixedWidth(60)
        self.width_edit.setEnabled(False)

        self.height_edit = QLineEdit()
        self.height_edit.setValidator(QIntValidator(240, 9999))
        self.height_edit.setText("1080")
        self.height_edit.setFixedWidth(60)
        self.height_edit.setEnabled(False)

        resolution_layout.addWidget(self.resolution_checkbox)
        resolution_layout.addWidget(self.width_edit)
        resolution_layout.addWidget(QLabel("x"))
        resolution_layout.addWidget(self.height_edit)

        self.width_edit.textChanged.connect(self.update_resolution)
        self.height_edit.textChanged.connect(self.update_resolution)

        offset_layout.addLayout(resolution_layout)

    def create_global_trim_control(self, offset_layout):
        """전역 트림 컨트롤 생성"""
        trim_group = QGroupBox("전역 트림")
        trim_layout = QVBoxLayout()
        
        # 전역 트림 활성화 체크박스
        self.global_trim_checkbox = QCheckBox("전역 트림 사용")
        self.global_trim_checkbox.setChecked(False)
        self.global_trim_checkbox.stateChanged.connect(self.toggle_global_trim)
        trim_layout.addWidget(self.global_trim_checkbox)
        
        # 시작 트림 슬라이더
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("시작 트림:"))
        self.global_trim_start_slider = QSlider(Qt.Horizontal)
        self.global_trim_start_slider.setRange(0, 300)
        self.global_trim_start_slider.setValue(0)
        self.global_trim_start_slider.setEnabled(False)
        self.global_trim_start_slider.valueChanged.connect(self.update_global_trim_start)
        start_layout.addWidget(self.global_trim_start_slider)
        self.global_trim_start_label = QLabel("0")
        start_layout.addWidget(self.global_trim_start_label)
        trim_layout.addLayout(start_layout)
        
        # 끝 트림 슬라이더
        end_layout = QHBoxLayout()
        end_layout.addWidget(QLabel("끝 트림:"))
        self.global_trim_end_slider = QSlider(Qt.Horizontal)
        self.global_trim_end_slider.setRange(0, 300)
        self.global_trim_end_slider.setValue(0)
        self.global_trim_end_slider.setEnabled(False)
        self.global_trim_end_slider.valueChanged.connect(self.update_global_trim_end)
        end_layout.addWidget(self.global_trim_end_slider)
        self.global_trim_end_label = QLabel("0")
        end_layout.addWidget(self.global_trim_end_label)
        trim_layout.addLayout(end_layout)
        
        # 프레임 단위 트림 체크박스 추가
        self.frame_based_trim_checkbox = QCheckBox("프레임 단위 트림 사용")
        self.frame_based_trim_checkbox.setChecked(False)
        self.frame_based_trim_checkbox.setToolTip("초 단위 변환 없이 프레임 번호로 직접 트림합니다.\n더 정확하지만 처리 속도가 느릴 수 있습니다.")
        trim_layout.addWidget(self.frame_based_trim_checkbox)
        
        trim_group.setLayout(trim_layout)
        offset_layout.addWidget(trim_group)
        
        # 초기값 설정
        self.global_trim_start = 0
        self.global_trim_end = 0

    def create_content_layout(self, main_layout):
        content_layout = QHBoxLayout()
        self.create_left_layout(content_layout)
        main_layout.addLayout(content_layout)

    def create_left_layout(self, content_layout):
        left_layout = QVBoxLayout()
        
        # 체크박스 레이아웃 먼저 생성
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setAlignment(Qt.AlignLeft)

        self.preview_mode_checkbox = QCheckBox("미리보기")
        self.preview_mode_checkbox.setChecked(True)
        checkbox_layout.addWidget(self.preview_mode_checkbox)

        self.auto_output_path_checkbox = QCheckBox("자동 경로")
        self.auto_output_path_checkbox.setChecked(True)
        checkbox_layout.addWidget(self.auto_output_path_checkbox)

        self.auto_naming_checkbox = QCheckBox("자동 네이밍")
        self.auto_naming_checkbox.setChecked(True)
        checkbox_layout.addWidget(self.auto_naming_checkbox)

        self.auto_foldernaming_checkbox = QCheckBox("자동 폴더네이밍")
        self.auto_foldernaming_checkbox.setChecked(False)
        checkbox_layout.addWidget(self.auto_foldernaming_checkbox)

        left_layout.addLayout(checkbox_layout)
        
        # TabListWidget 생성 및 추가
        self.tab_list_widget = TabListWidget(self)
        left_layout.addWidget(self.tab_list_widget)
        
        # 현재 활성화된 list_widget 참조 설정
        self.list_widget = self.tab_list_widget.get_current_list_widget()
        self.tab_list_widget.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        # 버튼 레이아웃 추가
        self.create_button_layout(left_layout)
        
        # 버전 및 인코딩 옵션 버튼 레이아웃
        version_options_layout = QHBoxLayout()
        
        # 버전 업/다운 버튼 추가
        version_down_button = QPushButton("⬇️ 버전다운")
        version_up_button = QPushButton("⬆️ 버전업")
        version_down_button.clicked.connect(lambda: self.change_version(-1))
        version_up_button.clicked.connect(lambda: self.change_version(1))
        
        # 인코딩 옵션 버튼
        options_button = QPushButton("⚙️ 인코딩 옵션")
        options_button.clicked.connect(self.show_encoding_options)
        
        version_options_layout.addWidget(version_down_button)
        version_options_layout.addWidget(version_up_button)
        version_options_layout.addWidget(options_button)
        
        left_layout.addLayout(version_options_layout)
        
        # 나머지 UI 요소들 추가
        self.create_output_layout(left_layout)
        self.create_encode_button(left_layout)
        self.create_update_button(left_layout)
        self.create_undo_redo_buttons(left_layout)
        self.setup_otio_controls(left_layout)
        
        content_layout.addLayout(left_layout)

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

    def create_output_layout(self, left_layout):
        output_layout = QHBoxLayout()
        self.output_label = QLabel("출력 경로:")
        self.output_edit = DroppableLineEdit(self)
        self.output_edit.setText(self.settings.value("last_output_path", ""))

        self.output_browse = QPushButton("찾아보기")
        self.output_browse.clicked.connect(self.browse_output)

        self.open_folder_button = QPushButton("📂")
        self.open_folder_button.setToolTip("출력 폴더 열기")
        # 람다를 사용하여 output_edit의 경로 전달
        self.open_folder_button.clicked.connect(lambda: self.open_folder(self.output_edit.text()))

        output_layout.addWidget(self.output_label)
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(self.open_folder_button)
        output_layout.addWidget(self.output_browse)
        left_layout.addLayout(output_layout)

        ffmpeg_layout = QHBoxLayout()
        self.ffmpeg_label = QLabel("FFmpeg 경로:")
        self.ffmpeg_edit = QLineEdit()
        self.ffmpeg_edit.setText(self.settings.value("ffmpeg_path", self.default_ffmpeg_path))
        self.ffmpeg_edit.setAcceptDrops(False)
        self.ffmpeg_browse = QPushButton("찾아보기")
        self.ffmpeg_browse.clicked.connect(self.browse_ffmpeg)

        self.open_ffmpeg_folder_button = QPushButton("📂")
        self.open_ffmpeg_folder_button.setToolTip("FFmpeg 폴더 열기")
        # 람다를 사용하여 ffmpeg_edit의 경로 전달
        self.open_ffmpeg_folder_button.clicked.connect(lambda: self.open_folder(self.ffmpeg_edit.text()))

        ffmpeg_layout.addWidget(self.ffmpeg_label)
        ffmpeg_layout.addWidget(self.ffmpeg_edit)
        ffmpeg_layout.addWidget(self.open_ffmpeg_folder_button)
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
            set_video_thread_path(ffmpeg_path)
            set_ffmpeg_utils_path(ffmpeg_path)

    def create_encode_button(self, left_layout):
        self.encode_button = QPushButton('🎬 인코딩 시작')
        self.encode_button.clicked.connect(self.start_encoding)
        left_layout.addWidget(self.encode_button)

    def create_update_button(self, left_layout):
        update_layout = QHBoxLayout()
        self.update_button = QPushButton('🔄 업데이트 확인')
        self.update_button.clicked.connect(self.update_checker.check_for_updates)
        update_layout.addWidget(self.update_button)
        left_layout.addLayout(update_layout)

    def create_undo_redo_buttons(self, left_layout):
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

    def clear_list(self):
        reply = QMessageBox.question(self, '목록 비우기',
                                     "정말로 목록을 비우시겠습니까?",
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.list_widget.count() > 0:
                command = ClearListCommand(self.list_widget)
                self.execute_command(command)
                self.preview_label.clear()

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
            processed_files = list(map(process_file, files))
            self.list_widget.handle_new_files(processed_files)

    def reverse_list_order(self):
        file_paths = self.list_widget.get_all_file_paths()
        reversed_file_paths = list(reversed(file_paths))

        if file_paths != reversed_file_paths:
            command = ReorderItemsCommand(self.list_widget, file_paths, reversed_file_paths)
            self.execute_command(command)

    def move_item_up(self):
        self.move_selected_items(-1)

    def move_item_down(self):
        self.move_selected_items(1)

    def move_selected_items(self, direction):
        selected_items = self.list_widget.selectedItems()
        if not selected_items:
            return

        old_order = self.list_widget.get_all_file_paths()

        items_to_move = selected_items if direction < 0 else reversed(selected_items)
        for item in items_to_move:
            current_row = self.list_widget.row(item)
            new_row = current_row + direction
            if 0 <= new_row < self.list_widget.count() and self.list_widget.item(new_row) not in selected_items:
                taken_item = self.list_widget.takeItem(current_row)
                self.list_widget.insertItem(new_row, taken_item)
                self.list_widget.setCurrentItem(taken_item, QItemSelectionModel.Select)

        new_order = self.list_widget.get_all_file_paths()

        if old_order != new_order:
            command = ReorderItemsCommand(self.list_widget, old_order, new_order)
            self.execute_command(command)

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

        return (output_file, self.encoding_options, get_debug_mode(), input_files, trim_values)

    def browse_output(self):
        last_path = self.settings.value("last_output_path", "")
        output_file, _ = QFileDialog.getSaveFileName(self, '출력 파일 저장', last_path, 'MP4 파일 (*.mp4)')
        if output_file:
            self.output_edit.setText(output_file)
            self.settings.setValue("last_output_path", output_file)

    def start_encoding(self):
        ffmpeg_path = self.ffmpeg_edit.text()
        set_video_thread_path(ffmpeg_path)
        set_ffmpeg_utils_path(ffmpeg_path)
        logger.info(f"인코딩 시작: FFmpeg 경로 = {ffmpeg_path}")

        params = self.get_encoding_parameters()
        if params:
            output_file, encoding_options, debug_mode, input_files, trim_values = params
            logger.info(f"인코딩 옵션: {encoding_options}")
            logger.info(f"출력 파일: {output_file}")

            self.update_encoding_options(encoding_options)

            try:
                ordered_input = []
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    item_widget = self.list_widget.itemWidget(item)
                    file_path = item_widget.file_path
                    trim_start, trim_end = item_widget.get_trim_values()
                    ordered_input.append((file_path, trim_start, trim_end))

                self.progress_dialog = EncodingProgressDialog(self)
                self.progress_dialog.show()
                self.progress_dialog.start_timer()  # 타이머 시작

                # 편집 옵션 설정 가져오기
                use_custom_framerate = self.framerate_checkbox.isChecked()
                custom_framerate = self.framerate_spinbox.value()
                use_custom_resolution = self.resolution_checkbox.isChecked()
                custom_width = int(self.width_edit.text()) if self.width_edit.text() else 0
                custom_height = int(self.height_edit.text()) if self.height_edit.text() else 0
                use_frame_based_trim = self.frame_based_trim_checkbox.isChecked()

                self.encoding_thread = EncodingThread(
                    process_all_media,
                    ordered_input,
                    output_file,
                    encoding_options,
                    debug_mode=debug_mode,
                    global_trim_start=self.global_trim_start,
                    global_trim_end=self.global_trim_end,
                    use_custom_framerate=use_custom_framerate,
                    custom_framerate=custom_framerate,
                    use_custom_resolution=use_custom_resolution,
                    custom_width=custom_width,
                    custom_height=custom_height,
                    use_frame_based_trim=use_frame_based_trim
                )
                self.encoding_thread.progress_updated.connect(self.progress_dialog.update_progress)
                self.encoding_thread.task_updated.connect(self.progress_dialog.update_task)
                self.encoding_thread.encoding_finished.connect(self.on_encoding_finished)
                self.encoding_thread.encoding_error.connect(self.on_encoding_error)
                self.encoding_thread.start()

            except Exception as e:
                QMessageBox.critical(self, "에러", f"인코딩 중 에러가 발생했습니다:\n{e}")

    def on_encoding_finished(self):
        self.progress_dialog.stop_timer()  # 타이머 중지
        self.progress_dialog.close()
        QMessageBox.information(self, "완료", "인코딩이 완료되었습니다.")

    def update_encoding_options(self, encoding_options):
        if self.use_custom_framerate:
            encoding_options["r"] = str(self.framerate)
        else:
            # encoding_options.pop("r", None)
            pass
        if self.use_custom_resolution:
            encoding_options["s"] = f"{self.video_width}x{self.video_height}"
        else:
            # encoding_options.pop("s", None)
            pass

    def toggle_debug_mode(self, state):
        is_checked = state == Qt.CheckState.Checked.value
        set_debug_mode(is_checked)
        self.clear_settings_button.setVisible(is_checked)
        logger.info(f"디버그 모드 {'활성화' if is_checked else '비활성화'}")
        set_logger_level(is_checked)

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
            self.ffmpeg_edit.setText(self.settings.value("ffmpeg_path", self.default_ffmpeg_path))

    def update_preview(self):
        try:
            file_path = self.list_widget.get_selected_file_path()
            if not file_path:
                self.stop_current_preview()
                self.preview_label.clear()
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
        if hasattr(self, 'play_button'):
            self.play_button.setText('▶️ 재생')

    def show_video_preview(self, file_path: str):
        self.create_video_thread()
        if hasattr(self, 'play_button'):
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
                logger.warning(f"시퀀스 파일을 찾을 수 없습니다: {file_path}")
                return

        if os.path.exists(file_path):
            pixmap = QPixmap(file_path)
            if not pixmap.isNull():
                scaled_pixmap = self.resize_keeping_aspect_ratio(pixmap, self.preview_label.width(), self.preview_label.height())
                self.preview_label.setPixmap(scaled_pixmap)
            else:
                logger.warning(f"이미지를 로드할 수 없습니다: {file_path}")
        else:
            logger.warning(f"파일이 존재하지 않습니다: {file_path}")

    def set_video_info(self, width: int, height: int):
        self.current_video_width = width
        self.current_video_height = height

    def toggle_play(self):
        selected_item = self.list_widget.currentItem()
        if not selected_item:
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

        if not self.video_thread:
            self.create_video_thread()

        self.video_thread.is_playing = True
        current_speed = self.speed_slider.value() / 100
        self.video_thread.set_speed(current_speed * 1.5)
        self.video_thread.start()
        self.play_button.setText('⏹️ 정지')

    def stop_video_playback(self):
        if not hasattr(self, 'video_thread') or not self.video_thread:
            return
        
        if not self.video_thread.is_playing:
            return
        
        logger.debug("비디오 재생 중지 시작")
        self.video_thread.stop()
        self.video_thread.wait()
        self.update_ui_after_stop()

    def on_video_finished(self):
        if not hasattr(self, 'video_thread') or not self.video_thread:
            return
        
        if self.video_thread.is_playing:
            self.stop_video_playback()
            self.update_ui_after_stop()
            self.video_thread.reset()

    def update_ui_after_stop(self):
        self.video_thread.is_playing = False
        self.play_button.setText('▶️ 재생')

    def change_speed(self):
        self.speed = self.speed_slider.value() / 100
        self.speed_value_label.setText(f"{self.speed:.1f}x")
        if self.video_thread:
            self.video_thread.set_speed(self.speed * 1.5)

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
            # self.encoding_options.pop("r", None)
            pass

    def toggle_resolution(self, state):
        self.use_custom_resolution = state == Qt.CheckState.Checked.value
        self.width_edit.setEnabled(self.use_custom_resolution)
        self.height_edit.setEnabled(self.use_custom_resolution)
        self.update_resolution()

    def update_resolution(self):
        if self.use_custom_resolution:
            width = self.width_edit.text()
            height = self.height_edit.text()
            if width and height:
                self.video_width = int(width)
                self.video_height = int(height)
                self.encoding_options["s"] = f"{width}x{height}"
        else:
            # self.encoding_options.pop("s", None)
            pass

    def update_framerate(self, value):
        self.framerate = value
        if self.use_custom_framerate:
            self.encoding_options["r"] = str(self.framerate)

    def toggle_global_trim(self, state):
        is_enabled = state == Qt.CheckState.Checked.value
        self.global_trim_start_slider.setEnabled(is_enabled)
        self.global_trim_end_slider.setEnabled(is_enabled)

    def update_global_trim_start(self, value):
        self.global_trim_start = value

    def update_global_trim_end(self, value):
        self.global_trim_end = value

    def closeEvent(self, event):
        self.settings.setValue("last_output_path", self.output_edit.text())
        self.settings.setValue("ffmpeg_path", self.ffmpeg_edit.text())
        self.stop_video_playback()
        super().closeEvent(event)

    def execute_command(self, command: Command):
        command.execute()
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self.update_undo_redo_buttons()

    def undo(self):
        if self.undo_stack:
            command = self.undo_stack.pop()
            command.undo()
            self.redo_stack.append(command)
            self.update_undo_redo_buttons()

    def redo(self):
        if self.redo_stack:
            command = self.redo_stack.pop()
            command.execute()
            self.undo_stack.append(command)
            self.update_undo_redo_buttons()

    def update_undo_redo_buttons(self):
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.redo_button.setEnabled(bool(self.redo_stack))

    def remove_selected_files(self):
        selected_items = self.list_widget.selectedItems()
        if selected_items:
            command = RemoveItemsCommand(self.list_widget, selected_items)
            self.execute_command(command)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Delete):
            self.remove_selected_files()
        else:
            super().keyPressEvent(event)

    def open_folder(self, path):
        if path:
            folder_path = os.path.dirname(path)
            folder_path = folder_path.replace('/', '\\')
            
            if os.path.exists(folder_path):
                try:
                    subprocess.Popen(['explorer', folder_path])
                except Exception as e:
                    logger.error(f"폴더 열기 실패: {str(e)}")
                    QMessageBox.warning(self, "오류", f"폴더를 열 수 없습니다: {str(e)}")
            else:
                QMessageBox.warning(self, "경고", "폴더가 존재하지 않습니다.")

    def setup_otio_controls(self, left_layout):
        otio_layout = QHBoxLayout()
        
        self.rv_path_edit = QLineEdit()
        self.rv_path_edit.setPlaceholderText("OpenRV 경로")
        self.rv_path_edit.setText(self.settings.value("rv_path", ""))
        
        self.rv_browse_button = QPushButton("RV 찾기")
        self.rv_browse_button.clicked.connect(self.browse_rv_path)
        
        self.create_otio_button = QPushButton("🎬 OTIO 생성 및 열기")
        self.create_otio_button.clicked.connect(self.create_and_open_otio)
        
        self.load_otio_button = QPushButton("📂 OTIO 불러오기")
        self.load_otio_button.clicked.connect(self.load_otio_file)
        
        otio_layout.addWidget(self.rv_path_edit)
        otio_layout.addWidget(self.rv_browse_button)
        otio_layout.addWidget(self.create_otio_button)
        otio_layout.addWidget(self.load_otio_button)
        
        left_layout.addLayout(otio_layout)

    def browse_rv_path(self):
        rv_path, _ = QFileDialog.getOpenFileName(
            self, 'OpenRV 실행 파일 선택',
            self.rv_path_edit.text(),
            'OpenRV (rv.exe);;모든 파일 (*.*)'
        )
        if rv_path:
            self.rv_path_edit.setText(rv_path)
            self.settings.setValue("rv_path", rv_path)

    def create_and_open_otio(self):
        if self.list_widget.count() == 0:
            QMessageBox.warning(self, "경고", "파일 목록이 비어있습니다.")
            return
        
        clips = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item_widget = self.list_widget.itemWidget(item)
            file_path = item_widget.file_path
            trim_start, trim_end = item_widget.get_trim_values()
            clips.append((file_path, trim_start, trim_end))
        
        try:
            from otio_utils import generate_and_open_otio
            # 임시 파일로 바로 생성하고 열기
            generate_and_open_otio(clips, None, self.rv_path_edit.text())
        except Exception as e:
            logger.error(f"OTIO 생성 중 오류 발생: {e}")
            QMessageBox.warning(self, "오류", f"OTIO 생성 중 오류가 발생했습니다: {str(e)}")

    def load_otio_file(self):
        """OTIO 파일을 선택하고 파싱하여 리스트에 추가합니다."""
        otio_path, _ = QFileDialog.getOpenFileName(
            self, 'OTIO 파일 선택',
            '',
            'OTIO 파일 (*.otio);;모든 파일 (*.*)'
        )
        
        if not otio_path:
            return
        
        try:
            logger.debug(f"OTIO 파일 파싱 시작: {otio_path}")
            from otio_utils import parse_otio_file
            clips = parse_otio_file(otio_path)
            logger.debug(f"파싱된 클립 정보: {clips}")
            
            if clips:
                # 기존 리스트 초기화 여부 확인
                if self.list_widget.count() > 0:
                    reply = QMessageBox.question(
                        self,
                        'OTIO 불러오기',
                        '기존 목록을 비우고 OTIO 파일을 불러오시겠습니까?',
                        QMessageBox.Yes | QMessageBox.No,
                        QMessageBox.No
                    )
                    
                    if reply == QMessageBox.Yes:
                        self.list_widget.clear()
                
                # 클립 추가
                file_paths = []
                trim_values = {}  # 파일 경로를 키로 하고 (trim_start, trim_end)를 값으로 하는 딕셔너리
                
                for file_path, trim_start, trim_end in clips:
                    logger.debug(f"처리할 파일 정보: 경로={file_path}, 시작={trim_start}, 끝={trim_end}")
                    # 파일 경로 처리
                    file_path = file_path.replace('\\', '/')  # 경로 정규화
                    
                    # 이미지 파일인 경우 시퀀스 처리
                    if is_image_file(file_path):
                        processed_path = process_image_file(file_path)
                        logger.debug(f"이미지 시퀀스 처리 결과: {processed_path}")
                        if processed_path and '%' in processed_path:  # 시퀀스 패턴이 있는 경우
                            file_path = processed_path
                    
                    if os.path.exists(file_path) or '%' in file_path:  # 시퀀스 패턴이 있는 경우도 허용
                        file_paths.append(file_path)
                        trim_values[file_path] = (trim_start, trim_end)
                        logger.debug(f"파일 추가됨: {file_path}")
                    else:
                        logger.warning(f"파일을 찾을 수 없습니다: {file_path}")
                
                if file_paths:
                    # 먼저 파일들을 추가
                    command = AddItemsCommand(self.list_widget, file_paths)
                    self.execute_command(command)
                    
                    # 그 다음 trim 값을 설정
                    for i in range(self.list_widget.count()):
                        item = self.list_widget.item(i)
                        file_path = item.data(Qt.UserRole)
                        if file_path in trim_values:
                            trim_start, trim_end = trim_values[file_path]
                            item_widget = self.list_widget.itemWidget(item)
                            if item_widget:
                                item_widget.trim_start_spinbox.setValue(trim_start)
                                item_widget.trim_end_spinbox.setValue(trim_end)
                else:
                    QMessageBox.warning(self, "경고", "처리할 수 있는 파일이 없습니다.")
                
        except Exception as e:
            logger.error(f"OTIO 파일 불러오기 실패: {str(e)}", exc_info=True)
            QMessageBox.warning(self, "오류", f"OTIO 파일을 불러오는 중 오류가 발생했습니다: {str(e)}")

    def on_tab_changed(self, index):
        """탭이 변경될 때 호출되는 메서드"""
        self.list_widget = self.tab_list_widget.get_current_list_widget()
        if self.list_widget:
            # 현재 탭의 리스트 위젯으로 업데이트
            logger.info(f"탭 변경됨: 인덱스 {index}")
            
            # 미리보기 모드가 활성화되어 있다면 프리뷰 업데이트
            if hasattr(self, 'preview_mode_checkbox') and self.preview_mode_checkbox.isChecked():
                self.update_preview()

    def on_item_selection_changed(self):
        """리스트 위젯의 아이템 선택이 변경될 때 호출되는 메서드"""
        if self.preview_mode_checkbox.isChecked():
            self.update_preview()
        
        # 선택된 아이템 유무에 따라 버튼 상태 업데이트
        has_selection = len(self.list_widget.selectedItems()) > 0
        if hasattr(self, 'remove_button'):
            self.remove_button.setEnabled(has_selection)
        if hasattr(self, 'move_up_button'):
            self.move_up_button.setEnabled(has_selection)
        if hasattr(self, 'move_down_button'):
            self.move_down_button.setEnabled(has_selection)

    def show_encoding_options(self):
        dialog = EncodingOptionsDialog(self, self.encoding_options)
        if dialog.exec_() == QDialog.Accepted:
            self.encoding_options = dialog.get_options()

    def change_version(self, delta):
        """
        리스트의 모든 아이템의 버전을 변경하는 메서드
        :param delta: 버전 변경값 (1: 업, -1: 다운)
        """
        import re
        import os
        
        def update_version_in_path(file_path, delta):
            # 경로를 디렉토리와 파일명으로 분리
            directory, filename = os.path.split(file_path)
            parent_dir = os.path.dirname(directory)
            
            # 버전 패턴 찾기 (v + 숫자)
            version_pattern = r'v(\d+)'
            
            # 디렉토리명과 파일명에서 버전 찾기
            dir_name = os.path.basename(directory)
            dir_match = re.search(version_pattern, dir_name)
            file_match = re.search(version_pattern, filename)
            
            # 버전 번호 업데이트
            current_version = int(dir_match.group(1)) if dir_match else 0
            new_version = max(0, current_version + delta)  # 버전이 음수가 되지 않도록
            new_version_str = str(new_version).zfill(len(dir_match.group(1)) if dir_match else 3)
            
            # 디렉토리명과 파일명 업데이트
            if dir_match:
                new_dir_name = dir_name.replace(f'v{dir_match.group(1)}', f'v{new_version_str}')
            else:
                new_dir_name = dir_name
            
            if file_match:
                new_filename = filename.replace(f'v{file_match.group(1)}', f'v{new_version_str}')
            else:
                new_filename = filename
            
            # 새로운 경로 생성
            new_path = os.path.join(parent_dir, new_dir_name, new_filename)
            return new_path
        
        # 현재 리스트의 모든 아이템 업데이트
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            file_path = item.data(Qt.UserRole)
            new_path = update_version_in_path(file_path, delta)
            
            # 경로가 변경된 경우에만 업데이트
            if new_path != file_path:
                item_widget = self.list_widget.itemWidget(item)
                if item_widget:
                    item_widget.file_path = new_path
                    item_widget.update_labels()
                item.setData(Qt.UserRole, new_path)

    def on_encoding_error(self, error_message):
        """인코딩 에러 발생 시 호출되는 메서드"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.show_error(f"에러: {error_message}")
        
        QMessageBox.critical(self, "인코딩 에러", f"인코딩 중 에러가 발생했습니다:\n{error_message}")