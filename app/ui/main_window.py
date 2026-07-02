import os
import subprocess

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QCursor, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.commands import Command, command_manager
from app.core.encoding_presets import apply_preset_options, get_preset, get_presets
from app.core.events import Events, event_emitter
from app.core.ffmpeg_manager import FFmpegManager
from app.core.job_builder import validate_encoding_job
from app.core.models import CancellationToken, EncodingProgressStage, PreflightSeverity
from app.core.preflight import build_preflight
from app.services.logging_service import LoggingService
from app.services.settings_service import SettingsService
from app.services.update import UpdateChecker
from app.ui.components.control_area import ControlAreaComponent
from app.ui.components.file_list_area import FileListAreaComponent
from app.ui.components.otio_controls import OtioControlsComponent
from app.ui.components.preview_area import PreviewAreaComponent
from app.ui.dialogs.encoding_options_dialog import EncodingOptionsDialog
from app.ui.dialogs.progress_dialog import EncodingProgressDialog, ProgressSignals
from app.ui.encoding_job_adapter import collect_encoding_job
from app.ui.styles import Styles
from app.ui.threads.encoding_thread import EncodingThread
from app.ui.widgets.tab_list_widget import TabListWidget
from app.utils.ffmpeg_utils import FFmpegUtils
from app.utils.utils import get_debug_mode, get_resource_path, set_debug_mode, set_logger_level

logger = LoggingService().get_logger(__name__)


class FFmpegSetupThread(QThread):
    """Resolve or install FFmpeg without blocking the Qt UI thread."""

    progress_updated = Signal(int, str)
    setup_finished = Signal(str)
    setup_error = Signal(str)

    def __init__(self, ffmpeg_manager, saved_path="", parent=None):
        super().__init__(parent)
        self.ffmpeg_manager = ffmpeg_manager
        self.saved_path = saved_path

    def run(self):
        try:
            path = self.ffmpeg_manager.ensure_ffmpeg_exists(
                saved_path=self.saved_path,
                allow_download=True,
                progress_callback=lambda value, message: self.progress_updated.emit(value, message),
            )
            if path:
                self.setup_finished.emit(path)
            else:
                self.setup_error.emit("FFmpeg를 찾거나 설치하지 못했습니다. FFmpeg 경로를 직접 선택해주세요.")
        except Exception as e:
            self.setup_error.emit(str(e))


class FFmpegGui(QMainWindow):
    """FFmpegGUI editor workstation."""

    def __init__(self):
        super().__init__()

        self.settings_service = SettingsService()
        self.ffmpeg_utils = FFmpegUtils()
        self.ffmpeg_manager = FFmpegManager()
        self.progress_dialog = None
        self.encoding_thread = None
        self.ffmpeg_setup_thread = None
        self.cancel_token = None
        self._encoding_failed = False
        self._is_encoding = False
        self._ffmpeg_setup_in_progress = False
        self._syncing_timeline_trim = False

        saved_ffmpeg_path = self.settings_service.get("ffmpeg_path", "")
        self.default_ffmpeg_path = self.ffmpeg_manager.find_existing_ffmpeg(saved_ffmpeg_path)
        self.current_ffmpeg_path = self.default_ffmpeg_path

        self.init_basic_attributes()
        self.init_components()
        self.init_tab_list_widget()
        self.init_shortcuts()
        self.init_ui()
        self.setStyleSheet(Styles.get_unreal_style())
        self.set_icon()

        self.progress_signals = ProgressSignals()
        self.progress_signals.progress.connect(self.update_progress)
        self.progress_signals.task.connect(self.update_task)
        self.progress_signals.error.connect(self.show_error)
        self.progress_signals.completed.connect(self.encoding_completed)

        self.ensure_ffmpeg_ready_async()
        self.refresh_job_inspector()

    def init_basic_attributes(self):
        self.current_preset_id = self.settings_service.get("last_encoding_preset", "h264_review")
        self.encoding_options = apply_preset_options(self.current_preset_id, {
            "c:v": "libx264",
            "pix_fmt": "yuv420p",
            "colorspace": "bt709",
            "color_primaries": "bt709",
            "color_trc": "bt709",
            "color_range": "limited",
        })
        self.current_output_extension = get_preset(self.current_preset_id).extension
        self.speed = 1.0
        self.update_checker = UpdateChecker()

    def init_components(self):
        self.preview_area = PreviewAreaComponent(self)
        self.control_area = ControlAreaComponent(self)
        self.file_list_area = FileListAreaComponent(self)
        self.otio_controls = OtioControlsComponent(self)

    def init_tab_list_widget(self):
        self.tab_list_widget = TabListWidget(self)
        self.list_widget = self.tab_list_widget.get_current_list_widget()

    def init_shortcuts(self):
        undo_shortcut = QShortcut(QKeySequence.Undo, self)
        undo_shortcut.activated.connect(self.undo)
        redo_shortcut = QShortcut(QKeySequence.Redo, self)
        redo_shortcut.activated.connect(self.redo)

    def init_ui(self):
        self.setWindowTitle("ffmpegGUI by LHCinema")
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        workspace = QSplitter(Qt.Horizontal)
        workspace.setChildrenCollapsible(False)
        main_layout.addWidget(workspace, 1)

        source_panel = self.create_panel("source-panel")
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(10, 10, 10, 10)
        self.file_list_area.create_left_layout(source_layout, include_job_controls=False)
        workspace.addWidget(source_panel)

        preview_panel = self.create_panel("preview-panel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        self.preview_area.create_preview_area(preview_layout)
        workspace.addWidget(preview_panel)

        inspector_scroll = QScrollArea()
        inspector_scroll.setWidgetResizable(True)
        inspector_scroll.setFrameShape(QFrame.NoFrame)
        inspector_widget = self.create_panel("inspector-panel")
        inspector_layout = QVBoxLayout(inspector_widget)
        inspector_layout.setContentsMargins(10, 10, 10, 10)
        self.create_job_inspector(inspector_layout)
        inspector_scroll.setWidget(inspector_widget)
        workspace.addWidget(inspector_scroll)
        workspace.setSizes([330, 620, 360])

        self.create_bottom_progress_area(main_layout)
        self.setup_timeline_sync()
        self.setup_update_checker()

        self.setGeometry(100, 100, 1280, 760)
        self.setMinimumSize(1120, 680)
        self.statusBar().showMessage("준비됨")

        self.debug_checkbox.setChecked(get_debug_mode())
        set_logger_level(self.debug_checkbox.isChecked())
        logger.info("UI initialized")
        self.print_settings_info()

    def create_panel(self, object_name):
        panel = QFrame()
        panel.setObjectName(object_name)
        panel.setFrameShape(QFrame.StyledPanel)
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return panel

    def create_job_inspector(self, layout):
        title = QLabel("Job Inspector")
        title.setStyleSheet("font-weight: bold; font-size: 15px;")
        layout.addWidget(title)

        preset_group = QGroupBox("인코딩 프리셋")
        preset_layout = QVBoxLayout(preset_group)
        self.preset_combo = QComboBox()
        for preset in get_presets():
            self.preset_combo.addItem(preset.name, preset.preset_id)
        preset_index = self.preset_combo.findData(self.current_preset_id)
        self.preset_combo.setCurrentIndex(max(0, preset_index))
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        self.preset_description_label = QLabel(get_preset(self.current_preset_id).description)
        self.preset_description_label.setWordWrap(True)
        self.preset_description_label.setStyleSheet("color: #b0b8c0;")
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addWidget(self.preset_description_label)
        layout.addWidget(preset_group)

        self.file_list_area.create_output_layout(layout)
        self.output_edit.textChanged.connect(self.refresh_job_inspector)
        self.ffmpeg_edit.textChanged.connect(self.refresh_job_inspector)

        self.control_area.create_control_area(layout)

        preflight_group = QGroupBox("Preflight")
        preflight_layout = QVBoxLayout(preflight_group)
        self.preflight_summary_label = QLabel("소스와 출력 경로를 준비하세요.")
        self.preflight_summary_label.setWordWrap(True)
        self.preflight_issues_label = QLabel("입력 대기 중")
        self.preflight_issues_label.setWordWrap(True)
        self.preflight_issues_label.setStyleSheet("color: #b0b8c0;")
        preflight_layout.addWidget(self.preflight_summary_label)
        preflight_layout.addWidget(self.preflight_issues_label)
        layout.addWidget(preflight_group)

        action_layout = QHBoxLayout()
        self.encode_button = QPushButton("인코딩 시작")
        self.encode_button.clicked.connect(self.start_encoding)
        self.cancel_button = QPushButton("취소")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_encoding)
        action_layout.addWidget(self.encode_button, 1)
        action_layout.addWidget(self.cancel_button)
        layout.addLayout(action_layout)

        self.create_advanced_tools(layout)
        layout.addStretch(1)

    def create_advanced_tools(self, layout):
        tools_group = QGroupBox("Tools / Advanced")
        tools_layout = QVBoxLayout(tools_group)

        version_options_layout = QHBoxLayout()
        version_down_button = QPushButton("버전다운")
        version_up_button = QPushButton("버전업")
        version_down_button.clicked.connect(lambda: self.file_list_area.change_version(-1))
        version_up_button.clicked.connect(lambda: self.file_list_area.change_version(1))
        options_button = QPushButton("고급 옵션")
        options_button.clicked.connect(self.show_encoding_options)
        version_options_layout.addWidget(version_down_button)
        version_options_layout.addWidget(version_up_button)
        version_options_layout.addWidget(options_button)
        tools_layout.addLayout(version_options_layout)

        self.otio_controls.setup_otio_controls(tools_layout)
        self.file_list_area.create_update_button(tools_layout)
        self.file_list_area.create_undo_redo_buttons(tools_layout)
        layout.addWidget(tools_group)

    def create_bottom_progress_area(self, main_layout):
        bottom_group = QGroupBox("진행 상태")
        bottom_layout = QVBoxLayout(bottom_group)
        header_layout = QHBoxLayout()
        self.progress_stage_label = QLabel("대기")
        self.progress_task_label = QLabel("인코딩 작업이 아직 시작되지 않았습니다.")
        self.progress_task_label.setStyleSheet("color: #b0b8c0;")
        header_layout.addWidget(self.progress_stage_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.progress_task_label)
        self.bottom_progress_bar = QProgressBar()
        self.bottom_progress_bar.setRange(0, 100)
        self.bottom_progress_bar.setValue(0)
        self.job_log_view = QTextEdit()
        self.job_log_view.setReadOnly(True)
        self.job_log_view.setFixedHeight(70)
        self.job_log_view.setPlaceholderText("인코딩 단계와 경고가 여기에 표시됩니다.")
        bottom_layout.addLayout(header_layout)
        bottom_layout.addWidget(self.bottom_progress_bar)
        bottom_layout.addWidget(self.job_log_view)
        main_layout.addWidget(bottom_group)

    def setup_timeline_sync(self):
        timeline_component = getattr(self.preview_area, "timeline", None)
        timeline_widget = getattr(timeline_component, "timeline_widget", None)
        if not timeline_widget:
            return
        timeline_widget.in_point_changed.connect(self.sync_current_item_trim_from_timeline)
        timeline_widget.out_point_changed.connect(self.sync_current_item_trim_from_timeline)
        timeline_component.setup_shortcuts()
        logger.debug("Timeline shortcuts initialized")

    def refresh_job_inspector(self, *args):
        if not hasattr(self, "preflight_summary_label") or self._is_encoding:
            return
        try:
            job = collect_encoding_job(self)
            preset = get_preset(self.current_preset_id)
            summary = build_preflight(job, self.settings_service, preset)
            parts = [f"소스 {summary.input_count}개", f"프리셋 {summary.preset_name}"]
            if summary.codec:
                parts.append(f"코덱 {summary.codec}")
            if summary.resolution:
                parts.append(f"해상도 {summary.resolution}")
            if summary.framerate:
                parts.append(f"FPS {summary.framerate}")
            if summary.total_head_trim or summary.total_tail_trim:
                parts.append(f"트림 앞 {summary.total_head_trim}f / 뒤 {summary.total_tail_trim}f")
            self.preflight_summary_label.setText(" | ".join(parts))

            if summary.issues:
                lines = []
                has_error = False
                for issue in summary.issues:
                    prefix = "차단" if issue.severity == PreflightSeverity.ERROR else "경고" if issue.severity == PreflightSeverity.WARNING else "정보"
                    if issue.severity == PreflightSeverity.ERROR:
                        has_error = True
                    target = f" ({issue.target})" if issue.target else ""
                    lines.append(f"[{prefix}] {issue.message}{target}")
                self.preflight_issues_label.setText("\n".join(lines))
                self.preflight_issues_label.setStyleSheet("color: #ff8a80;" if has_error else "color: #ffd166;")
            else:
                self.preflight_issues_label.setText("문제 없음. 바로 인코딩할 수 있습니다.")
                self.preflight_issues_label.setStyleSheet("color: #8bd17c;")
            self.encode_button.setEnabled(summary.can_start and not self._ffmpeg_setup_in_progress)
        except Exception as exc:
            self.preflight_summary_label.setText("Preflight를 계산할 수 없습니다.")
            self.preflight_issues_label.setText(str(exc))
            self.preflight_issues_label.setStyleSheet("color: #ff8a80;")
            self.encode_button.setEnabled(False)

    def on_preset_changed(self, index):
        preset_id = self.preset_combo.itemData(index)
        preset = get_preset(preset_id)
        self.current_preset_id = preset.preset_id
        self.current_output_extension = preset.extension
        self.preset_description_label.setText(preset.description)
        if not preset.is_custom:
            self.encoding_options = apply_preset_options(preset.preset_id, self.encoding_options)
            self.update_output_extension_for_preset(preset.extension)
        self.settings_service.set("last_encoding_preset", preset.preset_id)
        self.settings_service.sync()
        self.refresh_job_inspector()

    def update_output_extension_for_preset(self, extension):
        if not extension or not hasattr(self, "output_edit"):
            return
        if not extension.startswith("."):
            extension = f".{extension}"

        current_path = self.output_edit.text().strip()
        if not current_path:
            return

        root, current_extension = os.path.splitext(current_path)
        if not root:
            return

        known_extensions = {
            preset.extension.lower()
            for preset in get_presets()
            if getattr(preset, "extension", "")
        }
        auto_naming = (
            hasattr(self, "auto_naming_checkbox")
            and self.auto_naming_checkbox.isChecked()
        )
        should_update = (
            not current_extension
            or current_extension.lower() in known_extensions
            or auto_naming
        )
        if not should_update or current_extension.lower() == extension.lower():
            return

        self.output_edit.setText(f"{root}{extension}")

    def apply_selected_item_trim_to_timeline(self):
        timeline = getattr(getattr(self.preview_area, "timeline", None), "timeline_widget", None)
        if not timeline or not getattr(self, "list_widget", None) or not self.list_widget.currentItem():
            return
        item_widget = self.list_widget.itemWidget(self.list_widget.currentItem())
        if not item_widget or not hasattr(item_widget, "get_trim_values"):
            return
        frame_count = getattr(timeline, "frame_count", 0)
        if frame_count <= 0:
            return
        start_trim, end_trim = item_widget.get_trim_values()
        in_frame = max(1, min(frame_count, int(start_trim) + 1))
        out_frame = max(in_frame, min(frame_count, frame_count - int(end_trim)))
        self._syncing_timeline_trim = True
        try:
            if in_frame > getattr(timeline, "out_point", 0):
                timeline.set_out_point(out_frame)
                timeline.set_in_point(in_frame)
            else:
                timeline.set_in_point(in_frame)
                timeline.set_out_point(out_frame)
        finally:
            self._syncing_timeline_trim = False

    def sync_current_item_trim_from_timeline(self, *args):
        if self._syncing_timeline_trim:
            return
        timeline = getattr(getattr(self.preview_area, "timeline", None), "timeline_widget", None)
        if not timeline or not getattr(self, "list_widget", None) or not self.list_widget.currentItem():
            return
        frame_count = getattr(timeline, "frame_count", 0)
        if frame_count <= 0:
            return
        item_widget = self.list_widget.itemWidget(self.list_widget.currentItem())
        if not item_widget or not hasattr(item_widget, "set_trim_values"):
            return
        start_trim = max(0, timeline.in_point - 1)
        end_trim = max(0, frame_count - timeline.out_point)
        item_widget.set_trim_values(start_trim, end_trim)
        self.refresh_job_inspector()

    def print_settings_info(self):
        logger.info("Current settings:")
        for key in self.settings_service.get_all_keys():
            logger.info(f"{key}: {self.settings_service.get(key)}")

    def set_icon(self):
        icon_path = get_resource_path("icon.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

    def setup_update_checker(self):
        self.update_checker = UpdateChecker()
        self.update_checker.update_button = self.update_button
        event_emitter.on(Events.UPDATE_ERROR, self.show_update_error)
        event_emitter.on(Events.UPDATE_AVAILABLE, self.show_update_available)
        event_emitter.on(Events.UPDATE_NOT_AVAILABLE, self.show_no_update)
        event_emitter.on(Events.UPDATE_DOWNLOAD_STARTED, self.on_download_started)
        event_emitter.on(Events.UPDATE_DOWNLOAD_PROGRESS, self.on_download_progress)
        event_emitter.on(Events.UPDATE_DOWNLOAD_COMPLETED, self.on_download_completed)
        event_emitter.on(Events.UPDATE_DOWNLOAD_ERROR, self.show_update_error)
        event_emitter.on(Events.UPDATE_INSTALL_STARTED, self.on_install_started)
        event_emitter.on(Events.UPDATE_INSTALL_COMPLETED, self.on_install_completed)
        event_emitter.on(Events.UPDATE_INSTALL_ERROR, self.show_update_error)

    def ensure_ffmpeg_ready_async(self):
        saved_path = self.settings_service.get("ffmpeg_path", "")
        ffmpeg_path = self.ffmpeg_manager.find_existing_ffmpeg(saved_path)
        if ffmpeg_path:
            self.on_ffmpeg_setup_finished(ffmpeg_path)
            return
        if self._ffmpeg_setup_in_progress:
            return

        self._ffmpeg_setup_in_progress = True
        self.set_encoding_active(False)
        self.progress_dialog = EncodingProgressDialog(self)
        self.progress_dialog.setWindowTitle("FFmpeg 설치")
        self.progress_dialog.status_label.setText("FFmpeg 준비 중...")
        self.progress_dialog.show()
        self.progress_dialog.start_timer()

        self.ffmpeg_setup_thread = FFmpegSetupThread(self.ffmpeg_manager, saved_path, self)
        self.ffmpeg_setup_thread.progress_updated.connect(self.on_ffmpeg_setup_progress)
        self.ffmpeg_setup_thread.setup_finished.connect(self.on_ffmpeg_setup_finished)
        self.ffmpeg_setup_thread.setup_error.connect(self.on_ffmpeg_setup_error)
        self.ffmpeg_setup_thread.finished.connect(self.on_ffmpeg_setup_thread_finished)
        self.ffmpeg_setup_thread.start()

    def on_ffmpeg_setup_progress(self, progress, message):
        self.update_progress(progress)
        self.update_task(message)

    def on_ffmpeg_setup_finished(self, ffmpeg_path):
        self.current_ffmpeg_path = ffmpeg_path
        self.default_ffmpeg_path = ffmpeg_path
        self.settings_service.set_ffmpeg_path(ffmpeg_path)
        self.settings_service.sync()
        if hasattr(self, "ffmpeg_edit"):
            self.ffmpeg_edit.setText(ffmpeg_path)
        self.set_encoding_active(True)
        dialog = getattr(self, "progress_dialog", None)
        if dialog and dialog.isVisible() and self._ffmpeg_setup_in_progress:
            dialog.update_progress(100)
            dialog.update_task("FFmpeg 준비 완료")
            dialog.stop_timer()
            QTimer.singleShot(300, dialog.accept)
        self.refresh_job_inspector()

    def on_ffmpeg_setup_error(self, message):
        self.set_encoding_active(True)
        dialog = getattr(self, "progress_dialog", None)
        if dialog and dialog.isVisible():
            dialog.show_error(message)
        QMessageBox.warning(self, "FFmpeg 설정", message)
        self.refresh_job_inspector()

    def on_ffmpeg_setup_thread_finished(self):
        self._ffmpeg_setup_in_progress = False
        self.ffmpeg_setup_thread = None

    def set_encoding_active(self, enabled):
        self._is_encoding = not enabled
        if hasattr(self, "encode_button"):
            self.encode_button.setEnabled(enabled)
        if hasattr(self, "cancel_button"):
            self.cancel_button.setEnabled(not enabled)
        if enabled:
            self.refresh_job_inspector()

    def update_progress(self, value):
        if hasattr(self, "bottom_progress_bar"):
            self.bottom_progress_bar.setValue(value)
        dialog = getattr(self, "progress_dialog", None)
        if dialog and dialog.isVisible():
            dialog.update_progress(value)

    def update_task(self, message):
        if hasattr(self, "progress_task_label"):
            self.progress_task_label.setText(message)
        if hasattr(self, "job_log_view") and message:
            self.job_log_view.append(message)
        dialog = getattr(self, "progress_dialog", None)
        if dialog and dialog.isVisible():
            dialog.update_task(message)

    def update_progress_state(self, state):
        stage_names = {
            EncodingProgressStage.IDLE: "대기",
            EncodingProgressStage.FFMPEG_SETUP: "FFmpeg 준비",
            EncodingProgressStage.PREPARING: "준비",
            EncodingProgressStage.PROCESSING: "파일 처리",
            EncodingProgressStage.MERGING: "병합",
            EncodingProgressStage.COMPLETED: "완료",
            EncodingProgressStage.FAILED: "실패",
            EncodingProgressStage.CANCELLED: "취소됨",
        }
        if hasattr(self, "progress_stage_label"):
            self.progress_stage_label.setText(stage_names.get(state.stage, state.stage.value))
        self.update_progress(state.progress)
        if state.message:
            self.update_task(state.message)

    def show_error(self, message):
        dialog = getattr(self, "progress_dialog", None)
        if dialog and dialog.isVisible():
            dialog.show_error(message)
        QMessageBox.critical(self, "오류", message)

    def encoding_failed(self, message):
        if self._encoding_failed:
            return
        self._encoding_failed = True
        self.set_encoding_active(True)
        if self.encoding_thread and self.encoding_thread.isRunning():
            self.encoding_thread.wait()
        self.encoding_thread = None
        if "취소" in message:
            self.update_task("인코딩이 취소되었습니다.")
            self.statusBar().showMessage("인코딩 취소됨")
        else:
            self.show_error(message)
        self.cancel_token = None

    def encoding_completed(self):
        if self._encoding_failed:
            return
        dialog = getattr(self, "progress_dialog", None)
        if dialog and dialog.isVisible():
            dialog.update_progress(100)
            dialog.update_task("인코딩 완료")
            dialog.stop_timer()
            QTimer.singleShot(500, dialog.accept)
        if self.encoding_thread and self.encoding_thread.isRunning():
            self.encoding_thread.wait()
        self.encoding_thread = None
        self.cancel_token = None
        self.set_encoding_active(True)
        self.update_progress(100)
        self.update_task("인코딩 완료")
        self.statusBar().showMessage("인코딩 완료")
        QMessageBox.information(self, "완료", "인코딩이 완료되었습니다.")

    def show_update_error(self, error_message):
        QMessageBox.critical(self, "업데이트 오류", f"업데이트 중 오류가 발생했습니다:\n{error_message}")
        self.update_button.setEnabled(True)

    def show_update_available(self, version, download_url):
        reply = QMessageBox.question(
            self,
            "업데이트 가능",
            f"새로운 버전 {version}이(가) 있습니다. 지금 업데이트하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.update_checker.download_and_install_update(download_url)

    def show_no_update(self):
        QMessageBox.information(self, "업데이트 확인", "현재 최신 버전을 사용 중입니다.")
        self.update_button.setEnabled(True)

    def on_download_started(self):
        self.progress_dialog = EncodingProgressDialog(self)
        self.progress_dialog.setWindowTitle("업데이트 다운로드")
        self.progress_dialog.status_label.setText("업데이트 다운로드 중...")
        self.progress_dialog.show()
        self.progress_dialog.start_timer()

    def on_download_progress(self, progress):
        self.update_progress(progress)
        self.update_task(f"다운로드 중... {progress}%")

    def on_download_completed(self, file_path):
        dialog = getattr(self, "progress_dialog", None)
        if dialog and dialog.isVisible():
            dialog.stop_timer()
            dialog.close()

    def on_install_started(self):
        QMessageBox.information(self, "업데이트 설치", "업데이트 설치를 시작합니다. 프로그램이 자동으로 재시작됩니다.")

    def on_install_completed(self):
        QMessageBox.information(self, "업데이트 완료", "업데이트가 설치되었습니다. 프로그램을 재시작합니다.")
        self.close()

    def position_window_near_mouse(self):
        cursor_pos = QCursor.pos()
        screen_geometry = self.screen().availableGeometry()
        x = max(screen_geometry.left(), min(cursor_pos.x() - self.width() // 2, screen_geometry.right() - self.width()))
        y = max(screen_geometry.top(), min(cursor_pos.y() - self.height() // 2, screen_geometry.bottom() - self.height()))
        self.move(x, y)

    def toggle_debug_mode(self, state):
        is_checked = state == Qt.CheckState.Checked.value
        set_debug_mode(is_checked)
        self.clear_settings_button.setVisible(is_checked)
        logger.info("Debug mode %s", "enabled" if is_checked else "disabled")
        set_logger_level(is_checked)

    def clear_settings(self):
        reply = QMessageBox.question(
            self,
            "설정 초기화",
            "모든 설정을 초기화하시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.settings_service.clear_settings()
            self.settings_service.sync()
            QMessageBox.information(self, "설정 초기화", "모든 설정이 초기화되었습니다.")
            self.output_edit.clear()
            self.ffmpeg_edit.setText(self.default_ffmpeg_path or "")
            self.refresh_job_inspector()

    def open_folder(self, path):
        if not path:
            return
        folder_path = os.path.dirname(path).replace("/", "\\")
        if os.path.exists(folder_path):
            try:
                subprocess.Popen(["explorer", folder_path])
            except Exception as e:
                logger.error("Failed to open folder: %s", e)
                QMessageBox.warning(self, "오류", f"폴더를 열 수 없습니다: {e}")
        else:
            QMessageBox.warning(self, "경고", "폴더가 존재하지 않습니다.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "preview_area"):
            self.preview_area.update_preview_label()

    def closeEvent(self, event):
        self.settings_service.set("last_output_path", self.output_edit.text())
        self.settings_service.set("ffmpeg_path", self.ffmpeg_edit.text())
        self.settings_service.set("last_encoding_preset", self.current_preset_id)
        self.settings_service.sync()
        if hasattr(self, "preview_area"):
            self.preview_area.stop_current_preview()
        if self.cancel_token:
            self.cancel_token.cancel()
        super().closeEvent(event)

    def execute_command(self, command: Command):
        command_manager.execute(command)
        self.update_undo_redo_buttons()
        self.refresh_job_inspector()

    def undo(self):
        command_manager.undo()
        self.update_undo_redo_buttons()
        self.refresh_job_inspector()

    def redo(self):
        command_manager.redo()
        self.update_undo_redo_buttons()
        self.refresh_job_inspector()

    def update_undo_redo_buttons(self):
        self.undo_button.setEnabled(command_manager.can_undo())
        self.redo_button.setEnabled(command_manager.can_redo())

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Delete):
            self.file_list_area.remove_selected_files()
        else:
            super().keyPressEvent(event)

    def show_encoding_options(self):
        dialog = EncodingOptionsDialog(self, self.encoding_options)
        if dialog.exec_() == QDialog.Accepted:
            self.encoding_options = dialog.get_options()
            self.current_preset_id = "custom"
            custom_index = self.preset_combo.findData("custom")
            if custom_index >= 0:
                self.preset_combo.setCurrentIndex(custom_index)
            self.refresh_job_inspector()

    def start_encoding(self):
        try:
            if not self.ffmpeg_manager.get_ffmpeg_path():
                self.ensure_ffmpeg_ready_async()
                QMessageBox.warning(self, "FFmpeg 설정", "FFmpeg 준비가 끝난 뒤 다시 인코딩을 시작해주세요.")
                return

            job = collect_encoding_job(self)
            summary = build_preflight(job, self.settings_service, get_preset(self.current_preset_id))
            if not summary.can_start:
                blocking = "\n".join(issue.message for issue in summary.issues if issue.severity == PreflightSeverity.ERROR)
                QMessageBox.warning(self, "Preflight", blocking or "인코딩 전 확인이 필요합니다.")
                self.refresh_job_inspector()
                return
            validate_encoding_job(job)

            logger.info("Encoding options: %s", job.options.ffmpeg_options)
            logger.info("Output file: %s", job.output_file)
            for index, item in enumerate(job.media_items, start=1):
                logger.info(
                    "Encoding file %s: %s, head trim: %sf, tail trim: %sf",
                    index,
                    item.source_path,
                    item.trim.head_frames,
                    item.trim.tail_frames,
                )

            self._encoding_failed = False
            self.cancel_token = CancellationToken()
            self.set_encoding_active(False)
            self.bottom_progress_bar.setValue(0)
            self.job_log_view.clear()
            self.progress_dialog = EncodingProgressDialog(self)
            self.progress_dialog.show()
            self.progress_dialog.start_timer()

            self.encoding_thread = EncodingThread(job=job, cancel_token=self.cancel_token)
            self.encoding_thread.progress_updated.connect(self.update_progress)
            self.encoding_thread.task_updated.connect(self.update_task)
            if hasattr(self.encoding_thread, "progress_state_updated"):
                self.encoding_thread.progress_state_updated.connect(self.update_progress_state)
            self.encoding_thread.encoding_finished.connect(self.encoding_completed)
            self.encoding_thread.encoding_error.connect(self.encoding_failed)
            self.encoding_thread.start()
        except ValueError as e:
            logger.warning("Encoding job validation failed: %s", e)
            QMessageBox.warning(self, "경고", str(e))
            self.set_encoding_active(True)
        except Exception as e:
            logger.error("Encoding error: %s", e)
            self.encoding_failed(str(e))

    def cancel_encoding(self):
        if self.cancel_token:
            self.cancel_token.cancel()
        if self.encoding_thread and hasattr(self.encoding_thread, "cancel"):
            self.encoding_thread.cancel()
        self.update_task("인코딩 취소 요청 중...")
        self.statusBar().showMessage("취소 요청됨")

    def update_encoding_options(self):
        if self.control_area.use_custom_framerate:
            self.encoding_options["r"] = str(self.control_area.framerate)
        else:
            self.encoding_options.pop("r", None)

        if self.control_area.use_custom_resolution:
            self.encoding_options["s"] = f"{self.control_area.video_width}x{self.control_area.video_height}"
        else:
            self.encoding_options.pop("s", None)
        self.refresh_job_inspector()
