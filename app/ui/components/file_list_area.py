import os
import logging
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QCheckBox,
    QLineEdit, QFileDialog, QMessageBox, QMenu, QToolButton
)
from PySide6.QtCore import Qt, QItemSelectionModel

from app.ui.widgets.droppable_line_edit import DroppableLineEdit
from app.ui.commands.commands import RemoveItemsCommand, ReorderItemsCommand, ClearListCommand, AddItemsCommand
from app.utils.utils import process_file
from app.services.logging_service import LoggingService
from app.core.commands import command_manager

# 로깅 서비스 설정
logger = LoggingService().get_logger(__name__)


def _list_item_states(list_widget):
    if hasattr(list_widget, "get_all_item_states"):
        return list_widget.get_all_item_states()
    return list_widget.get_all_file_paths()


def _state_path(state):
    return state.get("file_path", state) if isinstance(state, dict) else state


def _state_paths(states):
    return [_state_path(state) for state in states]

class FileListAreaComponent:
    """
    파일 목록 영역 관련 기능을 제공하는 컴포넌트 클래스
    """

    def __init__(self, parent):
        """
        :param parent: 부모 위젯 (FFmpegGui 인스턴스)
        """
        self.parent = parent
        self.sort_ascending = True
        self.left_layout = None

    def create_left_layout(self, content_layout, include_job_controls=True):
        """소스 큐와 관련 작업 컨트롤을 생성합니다."""
        self.left_layout = QVBoxLayout()

        self.parent.preview_mode_checkbox = QCheckBox("미리보기")
        self.parent.preview_mode_checkbox.setChecked(True)
        self.parent.preview_mode_checkbox.hide()

        self.parent.auto_output_path_checkbox = QCheckBox("출력 경로 자동")
        self.parent.auto_output_path_checkbox.setChecked(True)
        self.parent.auto_output_path_checkbox.stateChanged.connect(self._refresh_parent)

        self.parent.auto_naming_checkbox = QCheckBox("파일명 자동")
        self.parent.auto_naming_checkbox.setChecked(True)
        self.parent.auto_naming_checkbox.stateChanged.connect(self._refresh_parent)

        self.parent.auto_foldernaming_checkbox = QCheckBox("폴더명 기준")
        self.parent.auto_foldernaming_checkbox.setChecked(False)
        self.parent.auto_foldernaming_checkbox.stateChanged.connect(self._refresh_parent)
        self.left_layout.addWidget(self.parent.tab_list_widget)

        self.parent.list_widget = self.parent.tab_list_widget.get_current_list_widget()
        self.parent.tab_list_widget.tab_widget.currentChanged.connect(self.on_tab_changed)
        self.create_button_layout(self.left_layout)

        if include_job_controls:
            version_options_layout = QHBoxLayout()
            version_down_button = QPushButton("버전 다운")
            version_up_button = QPushButton("버전 업")
            version_down_button.clicked.connect(lambda: self.change_version(-1))
            version_up_button.clicked.connect(lambda: self.change_version(1))
            options_button = QPushButton("인코딩 옵션")
            options_button.clicked.connect(self.parent.show_encoding_options)
            version_options_layout.addWidget(version_down_button)
            version_options_layout.addWidget(version_up_button)
            version_options_layout.addWidget(options_button)
            self.left_layout.addLayout(version_options_layout)
            self.create_output_layout(self.left_layout)
            self.create_encode_button(self.left_layout)
            self.create_update_button(self.left_layout)
            self.create_undo_redo_buttons(self.left_layout)

        content_layout.addLayout(self.left_layout)

    def add_otio_controls(self, otio_controls):
        """OTIO 컨트롤을 왼쪽 레이아웃에 추가"""
        if self.left_layout:
            otio_controls.setup_otio_controls(self.left_layout)
        else:
            logger.warning("left_layout이 초기화되지 않았습니다.")  # left_layout이 없는 경우 경고 출력

    def create_button_layout(self, left_layout):
        """Create primary source actions and move low-frequency actions to a menu."""
        button_layout = QHBoxLayout()

        self.parent.add_button = QPushButton("미디어 추가")
        self.parent.add_button.setProperty("role", "primary")
        self.parent.add_button.clicked.connect(self.add_files)
        button_layout.addWidget(self.parent.add_button, 1)

        self.parent.remove_button = QPushButton("−")
        self.parent.remove_button.setToolTip("선택한 클립 삭제")
        self.parent.remove_button.setFixedWidth(34)
        self.parent.remove_button.clicked.connect(self.remove_selected_files)
        button_layout.addWidget(self.parent.remove_button)

        more_button = QToolButton()
        more_button.setText("•••")
        more_button.setToolTip("클립 및 목록 명령")
        more_button.setFixedWidth(38)
        more_button.setPopupMode(QToolButton.InstantPopup)
        more_menu = QMenu(more_button)

        self.parent.move_up_button = QAction("위로 이동", more_menu)
        self.parent.move_up_button.triggered.connect(self.move_item_up)
        more_menu.addAction(self.parent.move_up_button)
        self.parent.move_down_button = QAction("아래로 이동", more_menu)
        self.parent.move_down_button.triggered.connect(self.move_item_down)
        more_menu.addAction(self.parent.move_down_button)
        duplicate_action = QAction("클립 복제", more_menu)
        duplicate_action.triggered.connect(self.parent.duplicate_selected_clip)
        more_menu.addAction(duplicate_action)
        reset_ranges_action = QAction("모든 컷 구간 초기화", more_menu)
        reset_ranges_action.triggered.connect(self.parent.reset_all_clip_ranges)
        more_menu.addAction(reset_ranges_action)
        more_menu.addSeparator()
        undo_action = QAction("실행 취소", more_menu)
        undo_action.triggered.connect(self.parent.undo)
        more_menu.addAction(undo_action)
        redo_action = QAction("다시 실행", more_menu)
        redo_action.triggered.connect(self.parent.redo)
        more_menu.addAction(redo_action)
        more_menu.addSeparator()
        self.parent.sort_button = QAction("이름순 정렬", more_menu)
        self.parent.sort_button.triggered.connect(self.toggle_sort_list)
        more_menu.addAction(self.parent.sort_button)
        self.parent.reverse_button = QAction("순서 뒤집기", more_menu)
        self.parent.reverse_button.triggered.connect(self.reverse_list_order)
        more_menu.addAction(self.parent.reverse_button)
        more_menu.addSeparator()
        self.parent.clear_button = QAction("목록 비우기", more_menu)
        self.parent.clear_button.triggered.connect(self.clear_list)
        more_menu.addAction(self.parent.clear_button)

        more_button.setMenu(more_menu)
        button_layout.addWidget(more_button)

        left_layout.addLayout(button_layout)

    def create_output_layout(self, left_layout):
        """출력 레이아웃 생성"""
        self.parent.auto_output_path_checkbox.hide()
        self.parent.auto_naming_checkbox.hide()
        self.parent.auto_foldernaming_checkbox.hide()

        naming_button = QToolButton()
        naming_button.setText("이름 규칙")
        naming_button.setPopupMode(QToolButton.InstantPopup)
        naming_menu = QMenu(naming_button)
        for label, checkbox in (
            ("출력 경로 자동", self.parent.auto_output_path_checkbox),
            ("파일명 자동", self.parent.auto_naming_checkbox),
            ("폴더명 기준", self.parent.auto_foldernaming_checkbox),
        ):
            action = QAction(label, naming_menu)
            action.setCheckable(True)
            action.setChecked(checkbox.isChecked())
            action.toggled.connect(checkbox.setChecked)
            checkbox.toggled.connect(action.setChecked)
            naming_menu.addAction(action)
        naming_button.setMenu(naming_menu)
        left_layout.addWidget(naming_button, 0, Qt.AlignRight)

        self.parent.output_label = QLabel("저장 위치")
        left_layout.addWidget(self.parent.output_label)
        self.parent.output_edit = DroppableLineEdit(self.parent)
        self.parent.output_edit.setText(self.parent.settings_service.get("last_output_path", ""))
        left_layout.addWidget(self.parent.output_edit)

        output_actions = QHBoxLayout()
        self.parent.output_browse = QPushButton("위치 선택")
        self.parent.output_browse.clicked.connect(self.browse_output)

        self.parent.open_folder_button = QPushButton("폴더 열기")
        self.parent.open_folder_button.setToolTip("출력 폴더 열기")
        self.parent.open_folder_button.clicked.connect(lambda: self.parent.open_folder(self.parent.output_edit.text()))

        output_actions.addWidget(self.parent.output_browse)
        output_actions.addWidget(self.parent.open_folder_button)
        left_layout.addLayout(output_actions)

        ffmpeg_layout = QHBoxLayout()
        self.parent.ffmpeg_label = QLabel("FFmpeg 경로:")
        self.parent.ffmpeg_edit = QLineEdit()
        self.parent.ffmpeg_edit.setText(self.parent.settings_service.get("ffmpeg_path", self.parent.default_ffmpeg_path))
        self.parent.ffmpeg_edit.setAcceptDrops(False)
        self.parent.ffmpeg_browse = QPushButton("찾아보기")
        self.parent.ffmpeg_browse.clicked.connect(self.browse_ffmpeg)

        self.parent.open_ffmpeg_folder_button = QPushButton("📂")
        self.parent.open_ffmpeg_folder_button.setToolTip("FFmpeg 폴더 열기")
        # 람다를 사용하여 ffmpeg_edit의 경로 전달
        self.parent.open_ffmpeg_folder_button.clicked.connect(lambda: self.parent.open_folder(self.parent.ffmpeg_edit.text()))

        # The widgets remain as a compatibility bridge for existing setup code.
        # FFmpeg configuration is exposed through the app-level Settings dialog.
        self.parent.ffmpeg_label.hide()
        self.parent.ffmpeg_edit.hide()
        self.parent.open_ffmpeg_folder_button.hide()
        self.parent.ffmpeg_browse.hide()

    def create_encode_button(self, left_layout):
        """인코딩 버튼 생성"""
        self.parent.encode_button = QPushButton('🎬 인코딩 시작')
        self.parent.encode_button.clicked.connect(self.parent.start_encoding)
        left_layout.addWidget(self.parent.encode_button)

    def create_update_button(self, left_layout):
        """업데이트 버튼 생성"""
        update_layout = QHBoxLayout()
        self.parent.update_button = QPushButton('🔄 업데이트 확인')
        self.parent.update_button.clicked.connect(self.parent.update_checker.check_for_updates)
        update_layout.addWidget(self.parent.update_button)
        left_layout.addLayout(update_layout)

    def create_undo_redo_buttons(self, left_layout):
        """실행 취소/다시 실행 버튼 생성"""
        undo_redo_layout = QHBoxLayout()
        undo_redo_layout.setAlignment(Qt.AlignLeft)

        self.parent.undo_button = QPushButton('↩️ 실행취소')
        self.parent.undo_button.clicked.connect(self.parent.undo)
        self.parent.undo_button.setEnabled(False)
        self.parent.undo_button.setFixedWidth(100)
        undo_redo_layout.addWidget(self.parent.undo_button)

        self.parent.redo_button = QPushButton('↪️ 다시실행')
        self.parent.redo_button.clicked.connect(self.parent.redo)
        self.parent.redo_button.setEnabled(False)
        self.parent.redo_button.setFixedWidth(100)
        undo_redo_layout.addWidget(self.parent.redo_button)

        undo_redo_layout.addStretch()

        self.parent.debug_checkbox = QCheckBox("디버그 모드")
        self.parent.debug_checkbox.setChecked(False)
        self.parent.debug_checkbox.stateChanged.connect(self.parent.toggle_debug_mode)
        undo_redo_layout.addStretch(1)
        undo_redo_layout.addWidget(self.parent.debug_checkbox)

        self.parent.clear_settings_button = QPushButton("설정 초기화")
        self.parent.clear_settings_button.clicked.connect(self.parent.clear_settings)
        self.parent.clear_settings_button.hide()
        undo_redo_layout.addWidget(self.parent.clear_settings_button)
        left_layout.addLayout(undo_redo_layout)

    def toggle_sort_list(self):
        """목록 정렬 토글"""
        old_order = _list_item_states(self.parent.list_widget)

        if self.sort_ascending:
            new_order = sorted(old_order, key=lambda state: os.path.basename(_state_path(state)).lower())
            self.parent.sort_button.setText("이름 역순 정렬")
        else:
            new_order = sorted(old_order, key=lambda state: os.path.basename(_state_path(state)).lower(), reverse=True)
            self.parent.sort_button.setText("이름순 정렬")

        if _state_paths(old_order) != _state_paths(new_order):
            command = ReorderItemsCommand(self.parent.list_widget, old_order, new_order)
            command_manager.execute(command)

        self.sort_ascending = not self.sort_ascending

    def clear_list(self):
        """목록 비우기"""
        reply = QMessageBox.question(self.parent, '목록 비우기',
                                     "정말로 목록을 비우시겠습니까?",
                                     QMessageBox.Yes | QMessageBox.No,
                                     QMessageBox.No)
        if reply == QMessageBox.Yes:
            if self.parent.list_widget.count() > 0:
                command = ClearListCommand(self.parent.list_widget)
                command_manager.execute(command)
                self._refresh_parent()
                preview_area = getattr(self.parent, "preview_area", None)
                if preview_area:
                    if hasattr(preview_area, "stop_current_preview"):
                        preview_area.stop_current_preview()
                    if hasattr(preview_area, "clear_preview"):
                        preview_area.clear_preview()

    def add_files(self):
        """파일 추가"""
        files, _ = QFileDialog.getOpenFileNames(self.parent, '파일 선택', '', '모든 파일 (*.*)')
        if files:
            processed_files = list(map(process_file, files))
            self.parent.list_widget.handle_new_files(processed_files)
            self._refresh_parent()

    def reverse_list_order(self):
        """목록 순서 반대로"""
        old_order = _list_item_states(self.parent.list_widget)
        new_order = list(reversed(old_order))

        if _state_paths(old_order) != _state_paths(new_order):
            command = ReorderItemsCommand(self.parent.list_widget, old_order, new_order)
            command_manager.execute(command)
            self._refresh_parent()

    def move_item_up(self):
        """항목 위로 이동"""
        self.move_selected_items(-1)

    def move_item_down(self):
        """항목 아래로 이동"""
        self.move_selected_items(1)

    def move_selected_items(self, direction):
        """선택된 항목 이동"""
        selected_items = self.parent.list_widget.selectedItems()
        if not selected_items:
            return

        old_order = _list_item_states(self.parent.list_widget)
        selected_rows = {self.parent.list_widget.row(item) for item in selected_items}
        new_order = old_order.copy()

        if direction < 0:
            for row in sorted(selected_rows):
                if row > 0 and row - 1 not in selected_rows:
                    new_order[row - 1], new_order[row] = new_order[row], new_order[row - 1]
                    selected_rows.remove(row)
                    selected_rows.add(row - 1)
        else:
            for row in sorted(selected_rows, reverse=True):
                if row < len(new_order) - 1 and row + 1 not in selected_rows:
                    new_order[row + 1], new_order[row] = new_order[row], new_order[row + 1]
                    selected_rows.remove(row)
                    selected_rows.add(row + 1)

        if _state_paths(old_order) != _state_paths(new_order):
            command = ReorderItemsCommand(self.parent.list_widget, old_order, new_order)
            command_manager.execute(command)
            self.parent.list_widget.clearSelection()
            for row in selected_rows:
                item = self.parent.list_widget.item(row)
                if item:
                    item.setSelected(True)
            self._refresh_parent()

    def browse_output(self):
        """출력 파일 경로 선택"""
        last_path = self.parent.settings_service.get("last_output_path", "")
        extension = getattr(self.parent, "current_output_extension", ".mp4") or ".mp4"
        if not extension.startswith("."):
            extension = f".{extension}"
        label = extension.lstrip(".").upper()
        primary_filter = f"{label} 파일 (*{extension})"
        filters = f"{primary_filter};;MP4 파일 (*.mp4);;WebM 파일 (*.webm);;모든 파일 (*.*)"
        output_file, _ = QFileDialog.getSaveFileName(self.parent, '출력 파일 저장', last_path, filters)
        if output_file:
            if not os.path.splitext(output_file)[1]:
                output_file = f"{output_file}{extension}"
            self.parent.output_edit.setText(output_file)
            self.parent.settings_service.set("last_output_path", output_file)
            self._refresh_parent()

    def browse_ffmpeg(self):
        """FFmpeg 경로 선택"""
        ffmpeg_path, _ = QFileDialog.getOpenFileName(
            self.parent, 'FFmpeg 실행 파일 선택',
            self.parent.ffmpeg_edit.text(),
            'FFmpeg (ffmpeg.exe);;모든 파일 (*.*)'
        )
        if ffmpeg_path:
            if self.parent.ffmpeg_manager.initialize_ffmpeg(ffmpeg_path):
                self.parent.ffmpeg_edit.setText(ffmpeg_path)
                self.parent.settings_service.set("ffmpeg_path", ffmpeg_path)
                self.parent.current_ffmpeg_path = ffmpeg_path
                self._refresh_parent()
            else:
                QMessageBox.warning(self.parent, "경고", "FFmpeg 경로 설정에 실패했습니다. 경로를 확인해주세요.")

    def remove_selected_files(self):
        """선택된 파일 제거"""
        selected_items = self.parent.list_widget.selectedItems()
        if selected_items:
            command = RemoveItemsCommand(self.parent.list_widget, selected_items)
            command_manager.execute(command)
            self._refresh_parent()

    def on_tab_changed(self, index):
        """탭이 변경될 때 호출되는 메서드"""
        self.parent.list_widget = self.parent.tab_list_widget.get_current_list_widget()
        if self.parent.list_widget:
            # 현재 탭의 리스트 위젯으로 업데이트
            logger.info(f"탭 변경됨: 인덱스 {index}")

            # 미리보기 모드가 활성화되어 있다면 프리뷰 업데이트
            if hasattr(self.parent, 'preview_mode_checkbox') and self.parent.preview_mode_checkbox.isChecked():
                self.parent.preview_area.update_preview()
            self._refresh_parent()

    def on_item_selection_changed(self):
        """리스트 위젯의 아이템 선택이 변경될 때 호출되는 메서드"""
        if self.parent.preview_mode_checkbox.isChecked():
            self.parent._loading_selected_media_trim = True
            self.parent.preview_area.update_preview()
        elif hasattr(self.parent, "apply_selected_item_trim_to_timeline"):
            self.parent.apply_selected_item_trim_to_timeline()
        self._refresh_parent()

        # 선택된 아이템 유무에 따라 버튼 상태 업데이트
        has_selection = len(self.parent.list_widget.selectedItems()) > 0
        if hasattr(self.parent, 'remove_button'):
            self.parent.remove_button.setEnabled(has_selection)
        if hasattr(self.parent, 'move_up_button'):
            self.parent.move_up_button.setEnabled(has_selection)
        if hasattr(self.parent, 'move_down_button'):
            self.parent.move_down_button.setEnabled(has_selection)

    def _refresh_parent(self, *args):
        if hasattr(self.parent, "refresh_job_inspector"):
            self.parent.refresh_job_inspector()

    def change_version(self, delta):
        """
        리스트의 모든 아이템의 버전을 변경하는 메서드
        :param delta: 버전 변경값 (1: 업, -1: 다운)
        """
        import re

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
        for i in range(self.parent.list_widget.count()):
            item = self.parent.list_widget.item(i)
            file_path = item.data(Qt.UserRole)
            new_path = update_version_in_path(file_path, delta)

            # 경로가 변경된 경우에만 업데이트
            if new_path != file_path:
                item_widget = self.parent.list_widget.itemWidget(item)
                if item_widget:
                    item_widget.file_path = new_path
                    item_widget.update_labels()
                item.setData(Qt.UserRole, new_path)
        self._refresh_parent()
