# list_widget_item.py

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSpinBox
from PySide6.QtCore import Qt, QEvent
import os
from utils import debug_print


class ListWidgetItem(QWidget):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        debug_print(f"[ListWidgetItem] 생성됨: {file_path}")
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

    def get_trim_values(self):
        return self.trim_start_spinbox.value(), self.trim_end_spinbox.value()

    def setSelected(self, selected):
        debug_print(f"[ListWidgetItem] 선택 상태 변경: {self.file_path} -> {selected}")
        self.is_selected = selected
        self.update_style()

    def enterEvent(self, event: QEvent):
        debug_print(f"[ListWidgetItem] 마우스 진입: {self.file_path}")
        self.is_hovered = True
        self.update_style()

    def leaveEvent(self, event: QEvent):
        debug_print(f"[ListWidgetItem] 마우스 이탈: {self.file_path}")
        self.is_hovered = False
        self.update_style()

    def update_style(self):
        state = "선택됨" if self.is_selected else "호버" if self.is_hovered else "기본"
        debug_print(f"[ListWidgetItem] 스타일 업데이트: {self.file_path} -> {state}")
        if self.is_selected:
            self.setStyleSheet("background-color: #3a3a3a;")
        elif self.is_hovered:
            self.setStyleSheet("background-color: #2a2a2a;")
        else:
            self.setStyleSheet("")
