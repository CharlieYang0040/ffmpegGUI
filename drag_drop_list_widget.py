# drag_drop_list_widget.py

from PySide6.QtWidgets import QListWidget, QAbstractItemView
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QDragEnterEvent, QDropEvent
import os

from utils import (
    is_media_file,
    process_image_sequences,
    process_file,
)

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
            self.addItems(links)
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
