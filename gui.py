# gui_refactor.py

import os
import sys
import subprocess
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QComboBox, QAbstractItemView, QCheckBox, QLineEdit,
    QMessageBox, QSlider, QDoubleSpinBox, QSpinBox,
    QProgressBar, QDialog, QPushButton
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
    set_logger_level
)

# 로깅 설정
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

from PySide6.QtCore import QTimer, QTime

class ColorOptionsDialog(QDialog):
    """
    색상 옵션을 설정하는 다이얼로그
    """
    def __init__(self, current_options, parent=None):
        super().__init__(parent)
        self.setWindowTitle("색상 옵션")
        self.setMinimumWidth(300)
        self.options = current_options.copy()

        layout = QVBoxLayout(self)
        self.option_widgets = {}

        color_options = [
            ("colorspace", ["bt709", "bt2020nc", "none"]),
            ("color_primaries", ["bt709", "bt2020", "none"]),
            ("color_trc", ["bt709", "bt2020-10", "none"]),
            ("color_range", ["limited", "full", "none"])
        ]

        for option, values in color_options:
            hbox = QHBoxLayout()
            label = QLabel(option)
            combo = QComboBox()
            combo.addItems(values)
            
            # 현재 설정된 값으로 콤보박스 초기화
            current_value = self.options.get(option)
            if current_value in values:
                combo.setCurrentText(current_value)
            
            combo.currentTextChanged.connect(lambda value, opt=option: self.update_option(opt, value))
            
            hbox.addWidget(label)
            hbox.addWidget(combo)
            layout.addLayout(hbox)
            self.option_widgets[option] = combo

        # OK and Cancel buttons
        button_box = QHBoxLayout()
        ok_button = QPushButton("확인")
        ok_button.clicked.connect(self.accept)
        cancel_button = QPushButton("취소")
        cancel_button.clicked.connect(self.reject)
        button_box.addStretch()
        button_box.addWidget(ok_button)
        button_box.addWidget(cancel_button)
        layout.addLayout(button_box)

    def update_option(self, option, value):
        if value != "none":
            self.options[option] = value
        else:
            self.options.pop(option, None)

    def get_options(self):
        return self.options

class EncodingProgressDialog(QDialog):
    """
    인코딩 진행 상황을 표시하는 다이얼로그
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("인코딩 진행 상황")
        self.setFixedSize(300, 150)  # 높이를 늘려서 경과 시간 표시

        layout = QVBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        layout.addWidget(self.progress_bar)

        self.elapsed_time_label = QLabel("경과 시간: 00:00:00")
        layout.addWidget(self.elapsed_time_label)

        self.setLayout(layout)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_elapsed_time)
        self.start_time = QTime()

    def start_timer(self):
        self.start_time = QTime.currentTime()
        self.timer.start(1000)  # 1초마다 업데이트

    def stop_timer(self):
        self.timer.stop()

    def update_elapsed_time(self):
        elapsed = self.start_time.secsTo(QTime.currentTime())
        elapsed_time_str = QTime(0, 0).addSecs(elapsed).toString("hh:mm:ss")
        self.elapsed_time_label.setText(f"경과 시간: {elapsed_time_str}")

    def update_progress(self, value):
        self.progress_bar.setValue(value)


class EncodingThread(QThread):
    """
    인코딩 작업을 별도의 스레드에서 실행하기 위한 클래스
    """
    progress_updated = Signal(int)
    encoding_finished = Signal(bool)

    def __init__(self, process_all_media_func, *args, **kwargs):
        super().__init__()
        self.process_all_media_func = process_all_media_func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.process_all_media_func(*self.args, **self.kwargs, progress_callback=self.progress_updated.emit)
            self.encoding_finished.emit(True)
        except Exception:
            self.encoding_finished.emit(False)


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
            "c:v": "h264_nvenc",
            "preset": "slow",
            "cq": "21",
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
        global_trim_layout = QVBoxLayout()
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
        self.setup_otio_controls(left_layout)
        content_layout.addLayout(left_layout)

    def create_list_widget(self, left_layout):
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

        self.option_widgets = {}

        # Codec
        self.create_option_widget(options_layout, "c:v", ["h264_nvenc", "hevc_nvenc", "libx264", "libx265", "none"])
        self.option_widgets["c:v"].setToolTip(
            "비디오 인코딩 코덱을 선택합니다.\n"
            "- h264_nvenc / hevc_nvenc: NVIDIA GPU를 사용해 빠르게 인코딩합니다.\n"
            "- libx264 / libx265: CPU를 사용해 인코딩하며, 호환성이 높습니다."
        )

        # Preset
        self.create_option_widget(options_layout, "preset", [])
        self.option_widgets["preset"].setToolTip(
            "인코딩 속도와 품질의 균형을 설정합니다.\n"
            "느린 프리셋일수록 품질과 압축률이 좋아집니다."
        )

        # Quality
        quality_layout = QHBoxLayout()
        self.quality_label = QLabel("Quality (CQ/CRF):")
        self.quality_label.setToolTip(
            "비디오의 품질을 설정합니다. (CQ/CRF)\n"
            "낮은 값일수록 고품질이며, 파일 크기가 커집니다.\n"
            "NVENC(CQ): 18-24 추천, libx264/265(CRF): 18-28 추천."
        )
        self.quality_spinbox = QSpinBox()
        self.quality_spinbox.setRange(0, 51)
        self.quality_spinbox.valueChanged.connect(self.update_quality_option)
        self.quality_spinbox.setToolTip(self.quality_label.toolTip()) # 라벨과 동일한 툴팁 설정
        quality_layout.addWidget(self.quality_label)
        quality_layout.addWidget(self.quality_spinbox)
        options_layout.addLayout(quality_layout)
        self.option_widgets["quality_spinbox"] = self.quality_spinbox

        # Other options (Pixel Format)
        self.create_option_widget(options_layout, "pix_fmt", ["yuv420p", "yuv422p", "yuv444p", "none"])
        self.option_widgets["pix_fmt"].setToolTip("픽셀 포맷을 설정합니다. 대부분의 경우 yuv420p로 충분합니다.")

        # Color Options Button
        self.color_options_button = QPushButton("색상 옵션 설정...")
        self.color_options_button.clicked.connect(self.open_color_options_dialog)
        options_layout.addWidget(self.color_options_button)


        self.options_group.setLayout(options_layout)
        left_layout.addWidget(self.options_group)

        # 초기 코덱 설정에 맞게 UI 업데이트
        self.update_codec_options(self.encoding_options.get("c:v"))

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

    def open_color_options_dialog(self):
        dialog = ColorOptionsDialog(self.encoding_options, self)
        if dialog.exec():
            self.encoding_options.update(dialog.get_options())
            logger.info(f"색상 옵션 업데이트됨: {self.encoding_options}")


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
        if option == "c:v":
            self.update_codec_options(value)

        if value != "none":
            self.encoding_options[option] = value
        else:
            self.encoding_options.pop(option, None)

    def update_codec_options(self, codec: str):
        self.encoding_options.pop("crf", None)
        self.encoding_options.pop("cq", None)

        preset_combo = self.option_widgets.get("preset")
        quality_spinbox = self.option_widgets.get("quality_spinbox")

        if codec in ["h264_nvenc", "hevc_nvenc"]:
            # NVENC presets
            presets = ["p1", "p2", "p3", "p4", "p5", "p6", "p7", "slow", "medium", "fast"]
            quality_label = "CQ"
            quality_value = 21
            self.encoding_options["cq"] = str(quality_value)
        elif codec in ["libx264", "libx265"]:
            # x264/x265 presets
            presets = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow", "placebo"]
            quality_label = "CRF"
            quality_value = 23
            self.encoding_options["crf"] = str(quality_value)
        else:
            presets = []
            quality_label = "Quality"
            quality_value = 0
            preset_combo.setEnabled(False)
            quality_spinbox.setEnabled(False)

        if presets:
            preset_combo.setEnabled(True)
            quality_spinbox.setEnabled(True)
            preset_combo.clear()
            preset_combo.addItems(presets)
            preset_combo.setCurrentText(self.encoding_options.get("preset", "medium"))
            self.quality_label.setText(f"{quality_label}:")
            quality_spinbox.setValue(quality_value)
            
    def update_quality_option(self, value: int):
        codec = self.encoding_options.get("c:v")
        if codec in ["h264_nvenc", "hevc_nvenc"]:
            self.encoding_options["cq"] = str(value)
            self.encoding_options.pop("crf", None)
        elif codec in ["libx264", "libx265"]:
            self.encoding_options["crf"] = str(value)
            self.encoding_options.pop("cq", None)

    def get_encoding_parameters(self):
        output_file = self.output_edit.text()
        if not output_file:
            QMessageBox.warning(self, "경고", "출력 경로를 지정해주세요.")
            return None

        if self.list_widget.count() == 0:
            QMessageBox.warning(self, "경고", "입력 파일을 추가해주세요.")
            return None

        input_files = []
        frame_ranges = []
        for i in range(self.list_widget.count()):
            list_item = self.list_widget.item(i)
            item_widget = self.list_widget.itemWidget(list_item)
            file_path = item_widget.file_path
            start_frame, end_frame = item_widget.get_frame_range()
            input_files.append(file_path)
            frame_ranges.append((start_frame, end_frame))

        return (output_file, self.encoding_options, get_debug_mode(), input_files, frame_ranges)

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
            output_file, encoding_options, debug_mode, input_files, frame_ranges = params
            logger.info(f"인코딩 옵션: {encoding_options}")
            logger.info(f"출력 파일: {output_file}")

            self.update_encoding_options(encoding_options)

            try:
                ordered_input = []
                for i in range(self.list_widget.count()):
                    item = self.list_widget.item(i)
                    item_widget = self.list_widget.itemWidget(item)
                    file_path = item_widget.file_path
                    start_frame, end_frame = item_widget.get_frame_range()
                    ordered_input.append((file_path, start_frame, end_frame))

                self.progress_dialog = EncodingProgressDialog(self)
                self.progress_dialog.show()
                self.progress_dialog.start_timer()  # 타이머 시작

                self.encoding_thread = EncodingThread(
                    process_all_media,  # 업데이트된 함수 사용
                    ordered_input,  # 전체 튜플을 그대로 전달
                    output_file,
                    encoding_options,
                    debug_mode=debug_mode,
                    global_trim_start=self.global_trim_start,
                    global_trim_end=self.global_trim_end
                )
                self.encoding_thread.progress_updated.connect(self.progress_dialog.update_progress)
                self.encoding_thread.encoding_finished.connect(self.on_encoding_finished)
                self.encoding_thread.start()

            except RuntimeError as e:
                QMessageBox.critical(self, "NVENC 오류", str(e))
                self.on_encoding_finished(False) # 오류 발생 시 프로그레스 다이얼로그 닫기
            except Exception as e:
                QMessageBox.critical(self, "에러", f"인코딩 중 에러가 발생했습니다:\n{e}")
                self.on_encoding_finished(False)

    def on_encoding_finished(self, success: bool):
        if self.progress_dialog:
            self.progress_dialog.stop_timer()
            self.progress_dialog.close()
            self.progress_dialog = None
        if success:
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
            if file_path:
                self.stop_current_preview()
                logger.info(f"미리보기 업데이트: {file_path}")

                if is_video_file(file_path):
                    self.show_video_preview(file_path)
                elif is_image_file(file_path):
                    self.show_image_preview(file_path)
                else:
                    logger.warning(f"지원하지 않는 파일 형식입니다: {file_path}")
            else:
                self.preview_label.clear()
        except Exception as e:
            logger.error(f"미리보기 업데이트 중 오류: {str(e)}")

    def stop_current_preview(self):
        if self.video_thread:
            self.video_thread.stop()
            self.video_thread.wait()
            self.video_thread = None

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
        if not self.video_thread or not self.video_thread.is_playing:
            return
        self.video_thread.stop()
        self.video_thread.wait()
        self.update_ui_after_stop()

    def on_video_finished(self):
        if self.video_thread.is_playing:
            return
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
        self.global_trim_start_spinbox.setEnabled(is_enabled)
        self.global_trim_end_spinbox.setEnabled(is_enabled)

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
        
        otio_layout.addWidget(self.rv_path_edit)
        otio_layout.addWidget(self.rv_browse_button)
        otio_layout.addWidget(self.create_otio_button)
        
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
            start_frame, end_frame = item_widget.get_frame_range()
            clips.append((file_path, start_frame, end_frame))
        
        try:
            from otio_utils import generate_and_open_otio
            # 임시 파일로 바로 생성하고 열기
            generate_and_open_otio(clips, None, self.rv_path_edit.text())
        except Exception as e:
            logger.error(f"OTIO 생성 중 오류 발생: {e}")
            QMessageBox.warning(self, "오류", f"OTIO 생성 중 오류가 발생했습니다: {str(e)}")