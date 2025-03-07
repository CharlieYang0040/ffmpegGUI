# gui_refactor.py

import os
import sys
import subprocess
import logging
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QFileDialog, QGroupBox,
    QHBoxLayout, QLabel, QComboBox, QAbstractItemView, QCheckBox, QLineEdit,
    QMessageBox, QSlider, QDoubleSpinBox, QSpinBox,
    QProgressBar, QDialog, QPushButton, QListWidgetItem, QMainWindow, QTabWidget, QProgressDialog
)
from PySide6.QtCore import Qt, QSettings, QItemSelectionModel, Signal, QThread, QTimer, QTime, QObject
from PySide6.QtGui import QCursor, QPixmap, QIcon, QIntValidator, QShortcut, QKeySequence

# 새로운 구조의 임포트
from app.utils.ffmpeg_utils import FFmpegUtils
from app.core.ffmpeg_manager import FFmpegManager
from app.services.settings_service import SettingsService
from app.services.logging_service import LoggingService
from app.core.events import event_emitter, Events
from app.core.commands import command_manager, Command

# 기존 UI 관련 임포트
from app.services.update import UpdateChecker
from app.ui.commands.commands import RemoveItemsCommand, ReorderItemsCommand, ClearListCommand, AddItemsCommand
from app.ui.widgets.drag_drop_list_widget import DragDropListWidget
from app.ui.widgets.droppable_line_edit import DroppableLineEdit
from app.ui.widgets.list_widget_item import ListWidgetItem
from app.ui.widgets.tab_list_widget import TabListWidget
from app.core.video_thread import VideoThread
from app.utils.utils import (
    process_file,
    is_video_file,
    is_image_file,
    get_first_sequence_file,
    get_debug_mode,
    set_debug_mode,
    set_logger_level,
    process_image_file
)

# 분리된 컴포넌트 임포트
from app.ui.dialogs.progress_dialog import EncodingProgressDialog, ProgressSignals
from app.ui.dialogs.encoding_options_dialog import EncodingOptionsDialog
from app.ui.threads.encoding_thread import EncodingThread
from app.ui.components.preview_area import PreviewAreaComponent
from app.ui.components.control_area import ControlAreaComponent
from app.ui.components.file_list_area import FileListAreaComponent
from app.ui.components.otio_controls import OtioControlsComponent
from app.ui.styles import Styles

# 로깅 서비스 설정
logger = LoggingService().get_logger(__name__)

class FFmpegGui(QWidget):
    """
    FFmpeg GUI 메인 클래스
    """
    def __init__(self):
        super().__init__()
        
        # 서비스 초기화
        self.settings_service = SettingsService()
        self.ffmpeg_utils = FFmpegUtils()
        self.ffmpeg_manager = FFmpegManager()
        
        # FFmpeg 경로 초기화
        self.default_ffmpeg_path = self.ffmpeg_manager.ensure_ffmpeg_exists()
        if not self.default_ffmpeg_path:
            QMessageBox.critical(self, "오류", "FFmpeg를 찾을 수 없습니다.")
            sys.exit(1)
            
        # 저장된 FFmpeg 경로 또는 기본 경로 사용
        saved_ffmpeg_path = self.settings_service.get("ffmpeg_path", "")
        self.current_ffmpeg_path = saved_ffmpeg_path if os.path.exists(saved_ffmpeg_path) else self.default_ffmpeg_path
        
        # FFmpeg 경로 설정
        if not self.ffmpeg_manager.initialize_ffmpeg(self.current_ffmpeg_path):
            QMessageBox.warning(self, "경고", "FFmpeg 경로 설정에 실패했습니다. 경로를 확인해주세요.")

        # 초기화 순서 변경: 기본 속성 초기화
        self.init_basic_attributes()
        
        # 컴포넌트 초기화
        self.init_components()
        
        # TabListWidget 초기화 (컴포넌트 초기화 후에 수행)
        self.init_tab_list_widget()
        
        self.init_shortcuts()
        self.init_ui()
        self.position_window_near_mouse()
        self.setStyleSheet(Styles.get_unreal_style())
        self.set_icon()
        
        # 진행률 시그널 초기화
        self.progress_signals = ProgressSignals()
        self.progress_signals.progress.connect(self.update_progress)
        self.progress_signals.task.connect(self.update_task)
        self.progress_signals.error.connect(self.show_error)
        self.progress_signals.completed.connect(self.encoding_completed)
    
    def update_progress(self, value):
        """진행률 업데이트 (메인 스레드에서 실행)"""
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.update_progress(value)
    
    def update_task(self, message):
        """작업 상태 업데이트 (메인 스레드에서 실행)"""
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.update_task(message)
    
    def show_error(self, message):
        """에러 메시지 표시 (메인 스레드에서 실행)"""
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.show_error(message)
        QMessageBox.critical(self, "오류", message)
    
    def encoding_completed(self):
        """인코딩 완료 처리 (메인 스레드에서 실행)"""
        if self.progress_dialog and self.progress_dialog.isVisible():
            # 마지막으로 진행률을 100%로 업데이트
            self.progress_dialog.update_progress(100)
            self.progress_dialog.update_task("인코딩 완료")
            self.progress_dialog.stop_timer()
            # 잠시 후 대화 상자 닫기
            QTimer.singleShot(500, self.progress_dialog.accept)
        
        # 인코딩 스레드 정리
        if hasattr(self, 'encoding_thread') and self.encoding_thread:
            if self.encoding_thread.isRunning():
                self.encoding_thread.wait()
            self.encoding_thread = None
            
        QMessageBox.information(self, "완료", "인코딩이 완료되었습니다.")

    def init_basic_attributes(self):
        """기본 속성 초기화"""
        self.encoding_options = {
            "c:v": "libx264",
            "pix_fmt": "yuv420p",
            "colorspace": "bt709",
            "color_primaries": "bt709",
            "color_trc": "bt709",
            "color_range": "limited"
        }
        self.speed = 1.0
        self.undo_stack = []
        self.redo_stack = []
        self.update_checker = UpdateChecker()
    
    def init_tab_list_widget(self):
        """TabListWidget 초기화"""
        # TabListWidget 생성 (컴포넌트 초기화 후에 수행)
        self.tab_list_widget = TabListWidget(self)
        # 현재 활성화된 list_widget 참조 설정
        self.list_widget = self.tab_list_widget.get_current_list_widget()
    
    def init_components(self):
        """컴포넌트 초기화"""
        self.preview_area = PreviewAreaComponent(self)
        self.control_area = ControlAreaComponent(self)
        self.file_list_area = FileListAreaComponent(self)
        self.otio_controls = OtioControlsComponent(self)

    def init_shortcuts(self):
        """단축키 초기화"""
        undo_shortcut = QShortcut(QKeySequence.Undo, self)
        undo_shortcut.activated.connect(self.undo)

        redo_shortcut = QShortcut(QKeySequence.Redo, self)
        redo_shortcut.activated.connect(self.redo)

    def init_ui(self):
        """UI 초기화"""
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
        all_keys = self.settings_service.get_all_keys()
        logger.info("현재 설정 값 목록:")
        for key in all_keys:
            value = self.settings_service.get(key)
            logger.info(f"{key}: {value}")

    def create_top_layout(self, main_layout):
        """상단 레이아웃 생성"""
        top_layout = QHBoxLayout()
        self.preview_area.create_preview_area(top_layout)
        self.control_area.create_control_area(top_layout)
        main_layout.addLayout(top_layout)

    def create_content_layout(self, main_layout):
        """콘텐츠 레이아웃 생성"""
        content_layout = QHBoxLayout()
        self.file_list_area.create_left_layout(content_layout)
        self.file_list_area.add_otio_controls(self.otio_controls)
        main_layout.addLayout(content_layout)

    def setup_update_checker(self):
        """업데이트 체커를 설정하고 이벤트 리스너를 등록합니다."""
        self.update_checker = UpdateChecker()
        self.update_checker.update_button = self.update_button

        # 업데이트 관련 이벤트 리스너 등록
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

    def show_update_error(self, error_message):
        """업데이트 오류를 표시합니다."""
        QMessageBox.critical(self, "업데이트 오류", f"업데이트 중 오류가 발생했습니다:\n{error_message}")
        self.update_button.setEnabled(True)

    def show_update_available(self, version, download_url):
        """새로운 업데이트가 있음을 표시하고 다운로드를 제안합니다."""
        reply = QMessageBox.question(
            self,
            "업데이트 가능",
            f"새로운 버전 {version}이(가) 있습니다. 지금 업데이트하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.update_checker.download_and_install_update(download_url)

    def show_no_update(self):
        """최신 버전을 사용 중임을 표시합니다."""
        QMessageBox.information(self, "업데이트 확인", "현재 최신 버전을 사용 중입니다.")
        self.update_button.setEnabled(True)

    def on_download_started(self):
        """업데이트 다운로드 시작 시 진행 상황 대화 상자를 표시합니다."""
        self.progress_dialog = EncodingProgressDialog(self)
        self.progress_dialog.setWindowTitle("업데이트 다운로드")
        self.progress_dialog.status_label.setText("업데이트 다운로드 중...")
        self.progress_dialog.show()
        self.progress_dialog.start_timer()

    def on_download_progress(self, progress):
        """다운로드 진행 상황을 업데이트합니다."""
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.update_progress(progress)
            self.progress_dialog.update_task(f"다운로드 중... {progress}%")

    def on_download_completed(self, file_path):
        """다운로드 완료 시 진행 상황 대화 상자를 닫습니다."""
        if self.progress_dialog and self.progress_dialog.isVisible():
            self.progress_dialog.stop_timer()
            self.progress_dialog.close()

    def on_install_started(self):
        """업데이트 설치 시작을 알립니다."""
        QMessageBox.information(
            self,
            "업데이트 설치",
            "업데이트 설치를 시작합니다. 프로그램이 자동으로 재시작됩니다."
        )

    def on_install_completed(self):
        """업데이트 설치 완료를 알리고 프로그램을 종료합니다."""
        QMessageBox.information(
            self,
            "업데이트 완료",
            "업데이트가 설치되었습니다. 프로그램을 재시작합니다."
        )
        self.close()  # 프로그램 종료

    def set_icon(self):
        """애플리케이션 아이콘 설정"""
        if getattr(sys, 'frozen', False):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        icon_path = os.path.join(base_path, 'icon.png')
        self.setWindowIcon(QIcon(icon_path))

    def position_window_near_mouse(self):
        """마우스 위치 근처에 창 위치 지정"""
        cursor_pos = QCursor.pos()
        screen = self.screen()
        screen_geometry = screen.availableGeometry()

        window_width = self.width()
        window_height = self.height()

        x = max(screen_geometry.left(), min(cursor_pos.x() - window_width // 2, screen_geometry.right() - window_width))
        y = max(screen_geometry.top(), min(cursor_pos.y() - window_height // 2, screen_geometry.bottom() - window_height))

        self.move(x, y)

    def toggle_debug_mode(self, state):
        """디버그 모드 토글"""
        is_checked = state == Qt.CheckState.Checked.value
        set_debug_mode(is_checked)
        self.clear_settings_button.setVisible(is_checked)
        logger.info(f"디버그 모드 {'활성화' if is_checked else '비활성화'}")
        set_logger_level(is_checked)

    def clear_settings(self):
        """설정 초기화"""
        reply = QMessageBox.question(
            self, '설정 초기화',
            "모든 설정을 초기화하시겠습니까?\n이 작업은 되돌릴 수 없습니다.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.settings_service.clear()
            self.settings_service.sync()
            QMessageBox.information(self, '설정 초기화', '모든 설정이 초기화되었습니다.')
            self.output_edit.clear()
            self.ffmpeg_edit.clear()
            self.ffmpeg_edit.setText(self.settings_service.get("ffmpeg_path", self.default_ffmpeg_path))

    def open_folder(self, path):
        """폴더 열기"""
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

    def resizeEvent(self, event):
        """창 크기 변경 이벤트 처리"""
        super().resizeEvent(event)
        if hasattr(self, 'preview_area'):
            self.preview_area.update_preview_label()

    def closeEvent(self, event):
        """창 닫기 이벤트 처리"""
        self.settings_service.set("last_output_path", self.output_edit.text())
        self.settings_service.set("ffmpeg_path", self.ffmpeg_edit.text())
        if hasattr(self, 'preview_area'):
            self.preview_area.stop_current_preview()
        super().closeEvent(event)

    def execute_command(self, command: Command):
        """명령 실행"""
        command.execute()
        self.undo_stack.append(command)
        self.redo_stack.clear()
        self.update_undo_redo_buttons()

    def undo(self):
        """실행 취소"""
        if self.undo_stack:
            command = self.undo_stack.pop()
            command.undo()
            self.redo_stack.append(command)
            self.update_undo_redo_buttons()

    def redo(self):
        """다시 실행"""
        if self.redo_stack:
            command = self.redo_stack.pop()
            command.execute()
            self.undo_stack.append(command)
            self.update_undo_redo_buttons()

    def update_undo_redo_buttons(self):
        """실행 취소/다시 실행 버튼 상태 업데이트"""
        self.undo_button.setEnabled(bool(self.undo_stack))
        self.redo_button.setEnabled(bool(self.redo_stack))

    def keyPressEvent(self, event):
        """키 입력 이벤트 처리"""
        if event.matches(QKeySequence.Delete):
            self.file_list_area.remove_selected_files()
        else:
            super().keyPressEvent(event)

    def show_encoding_options(self):
        """인코딩 옵션 대화 상자 표시"""
        dialog = EncodingOptionsDialog(self, self.encoding_options)
        if dialog.exec_() == QDialog.Accepted:
            self.encoding_options = dialog.get_options()

    def start_encoding(self):
        """인코딩 작업을 시작합니다."""
        try:
            # 인코딩 파라미터 가져오기
            output_file = self.output_edit.text()
            if not output_file:
                QMessageBox.warning(self, "경고", "출력 경로를 지정해주세요.")
                return

            if self.list_widget.count() == 0:
                QMessageBox.warning(self, "경고", "입력 파일을 추가해주세요.")
                return

            logger.info(f"인코딩 옵션: {self.encoding_options}")
            logger.info(f"출력 파일: {output_file}")

            # 인코딩 옵션 업데이트
            self.update_encoding_options()

            # 입력 파일 정보 구성
            ordered_input = []
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                item_widget = self.list_widget.itemWidget(item)
                file_path = item_widget.file_path
                trim_start, trim_end = item_widget.get_trim_values()
                ordered_input.append((file_path, trim_start, trim_end))

            # 진행 상황 다이얼로그 표시
            self.progress_dialog = EncodingProgressDialog(self)
            self.progress_dialog.show()
            self.progress_dialog.start_timer()

            # 인코딩 스레드 시작
            self.encoding_thread = EncodingThread(
                ordered_input, output_file, self.encoding_options
            )
            self.encoding_thread.progress_updated.connect(self.update_progress)
            self.encoding_thread.task_updated.connect(self.update_task)
            self.encoding_thread.encoding_finished.connect(self.encoding_completed)
            self.encoding_thread.encoding_error.connect(self.show_error)
            self.encoding_thread.start()

        except Exception as e:
            logger.error(f"인코딩 오류: {str(e)}")
            self.progress_signals.error.emit(str(e))

    def update_encoding_options(self):
        """인코딩 옵션 업데이트"""
        if self.control_area.use_custom_framerate:
            self.encoding_options["r"] = str(self.control_area.framerate)
        else:
            self.encoding_options.pop("r", None)
            
        if self.control_area.use_custom_resolution:
            self.encoding_options["s"] = f"{self.control_area.video_width}x{self.control_area.video_height}"
        else:
            self.encoding_options.pop("s", None)