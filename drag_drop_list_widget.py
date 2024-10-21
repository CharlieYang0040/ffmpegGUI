# drag_drop_list_widget.py

from PySide6.QtWidgets import QListWidget, QAbstractItemView, QListWidgetItem, QWidget, QHBoxLayout, QLabel, QSpinBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QDragEnterEvent, QDropEvent
import os

from utils import (
    is_media_file,
    process_image_sequences,
    process_file,
)

class ListWidgetItem(QWidget):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(os.path.basename(file_path))
        self.label.setToolTip(file_path)
        layout.addWidget(self.label)

        self.trim_start_spinbox = QSpinBox()
        self.trim_start_spinbox.setPrefix("앞: ")
        self.trim_start_spinbox.setRange(0, 100000)
        self.trim_start_spinbox.setFixedWidth(100)
        layout.addWidget(self.trim_start_spinbox)

        self.trim_end_spinbox = QSpinBox()
        self.trim_end_spinbox.setPrefix("뒤: ")
        self.trim_end_spinbox.setRange(0, 100000)
        self.trim_end_spinbox.setFixedWidth(100)
        layout.addWidget(self.trim_end_spinbox)

        self.setLayout(layout)

    def get_trim_values(self):
        return self.trim_start_spinbox.value(), self.trim_end_spinbox.value()

class DragDropListWidget(QListWidget):
    def __init__(self, parent=None, process_file_func=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.process_file_func = process_file_func or process_file

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
                    if os.path.isdir(file_path):
                        links.extend(self.parse_folder(file_path))
                    else:
                        processed_path = self.process_file_func(file_path)
                        if processed_path:
                            links.append(processed_path)
            self.add_items(links)
        else:
            super().dropEvent(event)

    def parse_folder(self, folder_path):
        files = []
        for root, _, filenames in os.walk(folder_path):
            for filename in filenames:
                file_path = os.path.join(root, filename)
                if is_media_file(file_path):
                    files.append(file_path)
        
        return process_image_sequences(files)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Delete):
            self.remove_selected_items()
        else:
            super().keyPressEvent(event)

    def remove_selected_items(self):
        for item in self.selectedItems():
            self.takeItem(self.row(item))

    def add_items(self, file_paths):
        for file_path in file_paths:
            item_widget = ListWidgetItem(file_path)
            list_item = QListWidgetItem(self)
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.UserRole, file_path)  # 파일 경로를 아이템 데이터로 저장
            self.addItem(list_item)
            self.setItemWidget(list_item, item_widget)

    def update_items(self, new_file_paths):
        # 기존 아이템 모두 제거
        self.clear()
        
        # 새로운 파일 경로로 아이템 추가
        self.add_items(new_file_paths)

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
