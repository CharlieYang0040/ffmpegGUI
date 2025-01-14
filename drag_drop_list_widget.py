# drag_drop_list_widget.py

from PySide6.QtWidgets import QListWidget, QAbstractItemView, QListWidgetItem, QApplication
from PySide6.QtCore import Qt, QMimeData
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QPainter, QColor, QDrag
import os
import logging
from commands import ChangeOutputPathCommand, ReorderItemsCommand, AddItemsCommand
from list_widget_item import ListWidgetItem
from utils import (
    is_media_file,
    process_image_sequences,
    process_file,
    format_drag_to_output
)

# 로깅 설정
logger = logging.getLogger(__name__)

class DragDropListWidget(QListWidget):
    def __init__(self, parent=None, process_file_func=None):
        super().__init__(parent)
        logger.debug("[DragDropListWidget] 초기화됨")
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.process_file_func = process_file_func or process_file
        self.old_order = []  # 드래그 시작 전 순서 저장
        self.drag_start_position = None  # 드래그 시작 위치 저장 변수 추가
        
        self.setViewportMargins(0, 0, 0, 0)
        self.placeholder_text = "파일 또는 폴더를 드래그 하여 추가하세요."
        self.placeholder_subtext = "이미지 시퀀스 파일은 한 장만 드래그 하세요."
        self.placeholder_visible = True
        
        # 더블 클릭 이벤트 연결
        self.itemDoubleClicked.connect(self.on_item_double_clicked)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def startDrag(self, supportedActions):
        self.old_order = self.get_all_file_paths()
        logger.debug(f"[startDrag] 드래그 시작. 이전 순서: {self.old_order}")
        
        drag = QDrag(self)
        mime_data = QMimeData()
        
        current_item = self.currentItem()
        if current_item:
            file_path = current_item.data(Qt.UserRole)
            logger.info(f"[startDrag] 드래그 중인 파일: {file_path}")
            file_name = os.path.basename(format_drag_to_output(file_path))
            mime_data.setText(file_name)
            mime_data.setData("application/x-qabstractitemmodeldatalist", b'')
        
        drag.setMimeData(mime_data)
        result = drag.exec_(Qt.MoveAction)
        logger.info(f"[startDrag] 드래그 작업 완료")

    def handle_new_files(self, links):
        """드래그 드롭과 파일 추가시 공통으로 사용할 파일 처리 메서드"""
        if links and hasattr(self.parent(), 'execute_command'):
            command = AddItemsCommand(self, links)
            self.parent().execute_command(command)
            logger.info(f"[handle_new_files] {len(links)}개 파일 추가됨")
            
            # 자동 출력 경로 설정
            if hasattr(self.parent(), 'auto_output_path_checkbox') and self.parent().auto_output_path_checkbox.isChecked():
                output_dir = os.path.dirname(links[0])
            else:
                output_dir = os.path.dirname(self.parent().output_edit.text())
                if not output_dir:
                    output_dir = os.path.expanduser("~")
            
            # 자동 네이밍이 활성화되어 있는지 확인
            if hasattr(self.parent(), 'auto_naming_checkbox') and self.parent().auto_naming_checkbox.isChecked():
                output_name = format_drag_to_output(links[0])
            else:
                existing_name = os.path.splitext(os.path.basename(self.parent().output_edit.text()))[0]
                output_name = existing_name if existing_name else "output"

            # 자동 폴더네이밍이 활성화되어 있는지 확인
            if hasattr(self.parent(), 'auto_foldernaming_checkbox') and self.parent().auto_foldernaming_checkbox.isChecked():
                output_name = os.path.basename(os.path.dirname(links[0]))

            # 새로운 출력 경로 생성
            new_output_path = os.path.join(output_dir, f"{output_name}.mp4")
            
            # 출력 경로 변경을 위한 Command 생성 및 실행
            command = ChangeOutputPathCommand(
                self.parent().output_edit,  # 출력 경로 QLineEdit
                self.parent().output_edit.text(),  # 이전 경로
                new_output_path  # 새로운 경로
            )
            self.parent().execute_command(command)

    def dropEvent(self, event: QDropEvent):
        logger.debug("[dropEvent] 드롭 이벤트 시작")
        if event.mimeData().hasUrls():
            logger.info("[dropEvent] 외부 파일 드롭 처리 시작")
            event.setDropAction(Qt.CopyAction)
            event.accept()
            links = []
            for url in event.mimeData().urls():
                if url.isLocalFile():
                    file_path = str(url.toLocalFile())
                    if os.path.isdir(file_path):
                        links.extend(self.parse_folder(file_path))
                    else:
                        processed_path = self.process_file_func(file_path)
                        if processed_path:
                            links.append(processed_path)
            
            self.handle_new_files(links)
        else:
            logger.info("[dropEvent] 내부 아이템 재정렬")
            event.setDropAction(Qt.MoveAction)
            super().dropEvent(event)
            new_order = self.get_all_file_paths()
            
            if self.old_order != new_order and hasattr(self.parent(), 'execute_command'):
                logger.info("[dropEvent] 아이템 순서 변경 실행")
                command = ReorderItemsCommand(self, self.old_order, new_order)
                self.parent().execute_command(command)
                logger.info("[dropEvent] 아이템 목록 업데이트 완료")
                self.update_items(new_order)

    def parse_folder(self, folder_path):
        files = []
        for root, _, filenames in os.walk(folder_path):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                if is_media_file(file_path):
                    files.append(file_path)
        
        return process_image_sequences(files)

    def add_items(self, file_paths):
        for file_path in file_paths:
            item_widget = ListWidgetItem(file_path)
            list_item = QListWidgetItem(self)
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, file_path)
            self.addItem(list_item)
            self.setItemWidget(list_item, item_widget)
        self.placeholder_visible = self.count() == 0

    def update_items(self, new_file_paths):
        logger.debug("[update_items] 아이템 목록 업데이트 시작")
        self.clear()
        for file_path in new_file_paths:
            logger.debug(f"[update_items] 아이템 추가: {file_path}")
            item_widget = ListWidgetItem(file_path)
            list_item = QListWidgetItem(self)
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, file_path)
            self.addItem(list_item)
            self.setItemWidget(list_item, item_widget)
        self.placeholder_visible = self.count() == 0
        logger.info(f"[update_items] {len(new_file_paths)}개 아이템 업데이트 완료")

    def get_all_file_paths(self):
        file_paths = []
        for index in range(self.count()):
            item = self.item(index)
            file_path = item.data(Qt.UserRole)
            file_paths.append(file_path)
        return file_paths
    
    def get_selected_file_path(self):
        selected_items = self.selectedItems()
        if selected_items:
            return selected_items[0].data(Qt.UserRole)
        return None

    def selectionChanged(self, selected, deselected):
        super().selectionChanged(selected, deselected)
        for index in deselected.indexes():
            item = self.item(index.row())
            widget = self.itemWidget(item)
            if widget:
                widget.setSelected(False)
        for index in selected.indexes():
            item = self.item(index.row())
            widget = self.itemWidget(item)
            if widget:
                widget.setSelected(True)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.placeholder_visible and self.count() == 0:
            painter = QPainter(self.viewport())
            painter.save()
            
            # 더 어두운 색상 설정
            col = self.palette().placeholderText().color()
            darker_col = QColor(col.red() // 3, col.green() // 3, col.blue() // 3)
            painter.setPen(darker_col)
            
            # 메인 텍스트 그리기
            main_font = QApplication.font()
            main_font.setPointSize(14)
            main_font.setBold(True)
            painter.setFont(main_font)
            
            fm = painter.fontMetrics()
            main_text_rect = fm.boundingRect(self.viewport().rect(), Qt.AlignCenter, self.placeholder_text)
            
            painter.drawText(main_text_rect, Qt.AlignCenter, self.placeholder_text)
            
            # 서브 텍스트 그리기
            sub_font = QApplication.font()
            sub_font.setPointSize(10)
            painter.setFont(sub_font)
            
            fm = painter.fontMetrics()
            sub_text_rect = fm.boundingRect(self.viewport().rect(), Qt.AlignCenter, self.placeholder_subtext)
            sub_text_rect.moveTop(main_text_rect.bottom() + 1)  # 메인 텍스트 아래에 위치
            
            painter.drawText(sub_text_rect, Qt.AlignCenter, self.placeholder_subtext)
            
            painter.restore()

    def clear(self):
        super().clear()
        self.placeholder_visible = True
        self.viewport().update()  # 뷰포트를 다시 그리도록 요청

    def update(self):
        super().update()
        # 추가적인 업데이트 로직이 있다면 여기에 작성

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_start_position = event.pos()
            logger.debug(f"[mousePressEvent] 마우스 누름 위치: {event.pos()}")
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.LeftButton):
            return
        if not self.drag_start_position:
            return
        
        distance = (event.pos() - self.drag_start_position).manhattanLength()
        
        if distance < QApplication.startDragDistance():
            return

        current_item = self.currentItem()
        if not current_item:
            logger.debug("[mouseMoveEvent] 선택된 아이템 없음")
            return

        logger.info("[mouseMoveEvent] 드래그 시작")
        self.startDrag(Qt.MoveAction)

    def handle_double_click(self, file_path):
        """ListWidgetItem으로부터 더블클릭 이벤트를 받아 처리"""
        if hasattr(self.parent(), 'open_folder'):
            self.parent().open_folder(file_path)

    def on_item_double_clicked(self, item):
        """QListWidget의 기본 더블클릭 이벤트 처리"""
        file_path = item.data(Qt.UserRole)
        if file_path and hasattr(self.parent(), 'open_folder'):
            self.parent().open_folder(file_path)
