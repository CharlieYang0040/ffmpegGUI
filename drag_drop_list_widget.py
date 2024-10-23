# drag_drop_list_widget.py

from PySide6.QtWidgets import QListWidget, QAbstractItemView, QListWidgetItem, QWidget, QHBoxLayout, QLabel, QSpinBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QDragEnterEvent, QDropEvent, QEnterEvent
from PySide6.QtCore import QEvent
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
        self.is_selected = False
        self.is_hovered = False

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

        self.setMouseTracking(True)  # 마우스 추적 활성화

    def get_trim_values(self):
        return self.trim_start_spinbox.value(), self.trim_end_spinbox.value()

    def setSelected(self, selected):
        self.is_selected = selected
        self.update_style()

    def enterEvent(self, event: QEnterEvent):
        self.is_hovered = True
        self.update_style()

    def leaveEvent(self, event: QEvent):  # QLeaveEvent 대신 QEvent 사용
        self.is_hovered = False
        self.update_style()

    def update_style(self):
        if self.is_selected:
            self.setStyleSheet("background-color: #3a3a3a;")
        elif self.is_hovered:
            self.setStyleSheet("background-color: #2a2a2a;")
        else:
            self.setStyleSheet("")

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
            list_item.setData(Qt.UserRole, file_path)
            self.addItem(list_item)
            self.setItemWidget(list_item, item_widget)

    def update_items(self, new_file_paths):
        self.clear()
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
