import os
import logging
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QCheckBox, 
    QLineEdit, QFileDialog, QMessageBox 
)
from PySide6.QtCore import Qt, QItemSelectionModel

from app.ui.widgets.droppable_line_edit import DroppableLineEdit
from app.ui.commands.commands import RemoveItemsCommand, ReorderItemsCommand, ClearListCommand, AddItemsCommand
from app.utils.utils import process_file
from app.services.logging_service import LoggingService

# 로깅 서비스 설정
logger = LoggingService().get_logger(__name__)

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
        
    def create_left_layout(self, content_layout):
        """왼쪽 레이아웃 생성"""
        self.left_layout = QVBoxLayout()
        
        # 체크박스 레이아웃 먼저 생성
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setAlignment(Qt.AlignLeft)

        self.parent.preview_mode_checkbox = QCheckBox("미리보기")
        self.parent.preview_mode_checkbox.setChecked(True)
        checkbox_layout.addWidget(self.parent.preview_mode_checkbox)

        self.parent.auto_output_path_checkbox = QCheckBox("자동 경로")
        self.parent.auto_output_path_checkbox.setChecked(True)
        checkbox_layout.addWidget(self.parent.auto_output_path_checkbox)

        self.parent.auto_naming_checkbox = QCheckBox("자동 네이밍")
        self.parent.auto_naming_checkbox.setChecked(True)
        checkbox_layout.addWidget(self.parent.auto_naming_checkbox)

        self.parent.auto_foldernaming_checkbox = QCheckBox("자동 폴더네이밍")
        self.parent.auto_foldernaming_checkbox.setChecked(False)
        checkbox_layout.addWidget(self.parent.auto_foldernaming_checkbox)

        self.left_layout.addLayout(checkbox_layout)
        
        # TabListWidget 생성 및 추가
        self.parent.tab_list_widget = self.parent.tab_list_widget
        self.left_layout.addWidget(self.parent.tab_list_widget)
        
        # 현재 활성화된 list_widget 참조 설정
        self.parent.list_widget = self.parent.tab_list_widget.get_current_list_widget()
        self.parent.tab_list_widget.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        # 버튼 레이아웃 추가
        self.create_button_layout(self.left_layout)
        
        # 버전 및 인코딩 옵션 버튼 레이아웃
        version_options_layout = QHBoxLayout()
        
        # 버전 업/다운 버튼 추가
        version_down_button = QPushButton("⬇️ 버전다운")
        version_up_button = QPushButton("⬆️ 버전업")
        version_down_button.clicked.connect(lambda: self.change_version(-1))
        version_up_button.clicked.connect(lambda: self.change_version(1))
        
        # 인코딩 옵션 버튼
        options_button = QPushButton("⚙️ 인코딩 옵션")
        options_button.clicked.connect(self.parent.show_encoding_options)
        
        version_options_layout.addWidget(version_down_button)
        version_options_layout.addWidget(version_up_button)
        version_options_layout.addWidget(options_button)
        
        self.left_layout.addLayout(version_options_layout)
        
        # 나머지 UI 요소들 추가
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
        """버튼 레이아웃 생성"""
        button_layout = QHBoxLayout()

        self.parent.add_button = QPushButton('➕ 파일 추가')
        self.parent.add_button.clicked.connect(self.add_files)
        button_layout.addWidget(self.parent.add_button)

        self.parent.remove_button = QPushButton('➖ 파일 제거')
        self.parent.remove_button.clicked.connect(self.remove_selected_files)
        button_layout.addWidget(self.parent.remove_button)

        self.parent.clear_button = QPushButton('🗑️ 목록 비우기')
        self.parent.clear_button.clicked.connect(self.clear_list)
        button_layout.addWidget(self.parent.clear_button)

        self.parent.sort_button = QPushButton('🔠 이름 순 정렬')
        self.parent.sort_button.clicked.connect(self.toggle_sort_list)
        button_layout.addWidget(self.parent.sort_button)

        self.parent.reverse_button = QPushButton('🔃 순서 반대로')
        self.parent.reverse_button.clicked.connect(self.reverse_list_order)
        button_layout.addWidget(self.parent.reverse_button)

        self.parent.move_up_button = QPushButton('🔼 위로 이동')
        self.parent.move_up_button.clicked.connect(self.move_item_up)
        button_layout.addWidget(self.parent.move_up_button)

        self.parent.move_down_button = QPushButton('🔽 아래로 이동')
        self.parent.move_down_button.clicked.connect(self.move_item_down)
        button_layout.addWidget(self.parent.move_down_button)

        left_layout.addLayout(button_layout)
    
    def create_output_layout(self, left_layout):
        """출력 레이아웃 생성"""
        output_layout = QHBoxLayout()
        self.parent.output_label = QLabel("출력 경로:")
        self.parent.output_edit = DroppableLineEdit(self.parent)
        self.parent.output_edit.setText(self.parent.settings_service.get("last_output_path", ""))

        self.parent.output_browse = QPushButton("찾아보기")
        self.parent.output_browse.clicked.connect(self.browse_output)

        self.parent.open_folder_button = QPushButton("📂")
        self.parent.open_folder_button.setToolTip("출력 폴더 열기")
        # 람다를 사용하여 output_edit의 경로 전달
        self.parent.open_folder_button.clicked.connect(lambda: self.parent.open_folder(self.parent.output_edit.text()))

        output_layout.addWidget(self.parent.output_label)
        output_layout.addWidget(self.parent.output_edit)
        output_layout.addWidget(self.parent.open_folder_button)
        output_layout.addWidget(self.parent.output_browse)
        left_layout.addLayout(output_layout)

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

        ffmpeg_layout.addWidget(self.parent.ffmpeg_label)
        ffmpeg_layout.addWidget(self.parent.ffmpeg_edit)
        ffmpeg_layout.addWidget(self.parent.open_ffmpeg_folder_button)
        ffmpeg_layout.addWidget(self.parent.ffmpeg_browse)
        left_layout.addLayout(ffmpeg_layout)
    
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
        old_order = self.parent.list_widget.get_all_file_paths()

        if self.sort_ascending:
            new_order = sorted(old_order, key=lambda x: os.path.basename(x).lower())
            self.parent.sort_button.setText('🔠 이름 역순 정렬')
        else:
            new_order = sorted(old_order, key=lambda x: os.path.basename(x).lower(), reverse=True)
            self.parent.sort_button.setText('🔠 이름 순 정렬')

        if old_order != new_order:
            command = ReorderItemsCommand(self.parent.list_widget, old_order, new_order)
            self.parent.execute_command(command)

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
                self.parent.execute_command(command)
                self.parent.preview_label.clear()
    
    def add_files(self):
        """파일 추가"""
        files, _ = QFileDialog.getOpenFileNames(self.parent, '파일 선택', '', '모든 파일 (*.*)')
        if files:
            processed_files = list(map(process_file, files))
            self.parent.list_widget.handle_new_files(processed_files)
    
    def reverse_list_order(self):
        """목록 순서 반대로"""
        file_paths = self.parent.list_widget.get_all_file_paths()
        reversed_file_paths = list(reversed(file_paths))

        if file_paths != reversed_file_paths:
            command = ReorderItemsCommand(self.parent.list_widget, file_paths, reversed_file_paths)
            self.parent.execute_command(command)
    
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

        old_order = self.parent.list_widget.get_all_file_paths()

        items_to_move = selected_items if direction < 0 else reversed(selected_items)
        for item in items_to_move:
            current_row = self.parent.list_widget.row(item)
            new_row = current_row + direction
            if 0 <= new_row < self.parent.list_widget.count() and self.parent.list_widget.item(new_row) not in selected_items:
                taken_item = self.parent.list_widget.takeItem(current_row)
                self.parent.list_widget.insertItem(new_row, taken_item)
                self.parent.list_widget.setCurrentItem(taken_item, QItemSelectionModel.Select)

        new_order = self.parent.list_widget.get_all_file_paths()

        if old_order != new_order:
            command = ReorderItemsCommand(self.parent.list_widget, old_order, new_order)
            self.parent.execute_command(command)
    
    def browse_output(self):
        """출력 파일 경로 선택"""
        last_path = self.parent.settings_service.get("last_output_path", "")
        output_file, _ = QFileDialog.getSaveFileName(self.parent, '출력 파일 저장', last_path, 'MP4 파일 (*.mp4)')
        if output_file:
            self.parent.output_edit.setText(output_file)
            self.parent.settings_service.set("last_output_path", output_file)
    
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
            else:
                QMessageBox.warning(self.parent, "경고", "FFmpeg 경로 설정에 실패했습니다. 경로를 확인해주세요.")
    
    def remove_selected_files(self):
        """선택된 파일 제거"""
        selected_items = self.parent.list_widget.selectedItems()
        if selected_items:
            command = RemoveItemsCommand(self.parent.list_widget, selected_items)
            self.parent.execute_command(command)
    
    def on_tab_changed(self, index):
        """탭이 변경될 때 호출되는 메서드"""
        self.parent.list_widget = self.parent.tab_list_widget.get_current_list_widget()
        if self.parent.list_widget:
            # 현재 탭의 리스트 위젯으로 업데이트
            logger.info(f"탭 변경됨: 인덱스 {index}")
            
            # 미리보기 모드가 활성화되어 있다면 프리뷰 업데이트
            if hasattr(self.parent, 'preview_mode_checkbox') and self.parent.preview_mode_checkbox.isChecked():
                self.parent.preview_area.update_preview()
    
    def on_item_selection_changed(self):
        """리스트 위젯의 아이템 선택이 변경될 때 호출되는 메서드"""
        if self.parent.preview_mode_checkbox.isChecked():
            self.parent.preview_area.update_preview()
        
        # 선택된 아이템 유무에 따라 버튼 상태 업데이트
        has_selection = len(self.parent.list_widget.selectedItems()) > 0
        if hasattr(self.parent, 'remove_button'):
            self.parent.remove_button.setEnabled(has_selection)
        if hasattr(self.parent, 'move_up_button'):
            self.parent.move_up_button.setEnabled(has_selection)
        if hasattr(self.parent, 'move_down_button'):
            self.parent.move_down_button.setEnabled(has_selection)
    
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