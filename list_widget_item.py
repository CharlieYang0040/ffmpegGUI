# list_widget_item.py

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSpinBox
from PySide6.QtCore import Qt, QEvent
import os


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
        self.setMouseTracking(True)

        # 더블 클릭 이벤트를 위한 설정
        self.setAttribute(Qt.WA_Hover)
        self.setMouseTracking(True)

    def get_trim_values(self):
        return self.trim_start_spinbox.value(), self.trim_end_spinbox.value()

    def setSelected(self, selected):
        self.is_selected = selected
        self.update_style()

    def enterEvent(self, event: QEvent):
        self.is_hovered = True
        self.update_style()

    def leaveEvent(self, event: QEvent):
        self.is_hovered = False
        self.update_style()

    def update_style(self):
        if self.is_selected:
            self.setStyleSheet("background-color: #3a3a3a;")
        elif self.is_hovered:
            self.setStyleSheet("background-color: #2a2a2a;")
        else:
            self.setStyleSheet("")

    def mouseDoubleClickEvent(self, event):
        # 부모 위젯(DragDropListWidget)의 더블클릭 시그널 발생
        parent_list = self.parent().parent()
        if hasattr(parent_list, 'itemDoubleClicked'):
            parent_list.handle_double_click(self.file_path)
