# list_widget_item.py

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSpinBox
from PySide6.QtCore import Qt, QEvent
import os


class ListWidgetItem(QWidget):
    def __init__(self, file_path, start_frame=0, end_frame=0, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.is_selected = False
        self.is_hovered = False

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QLabel(os.path.basename(file_path))
        self.label.setToolTip(file_path)
        layout.addWidget(self.label)

        self.start_frame_spinbox = QSpinBox()
        self.start_frame_spinbox.setPrefix("시작: ")
        self.start_frame_spinbox.setRange(0, 9999999) # 최대 범위는 일단 넓게
        self.start_frame_spinbox.setValue(start_frame)
        self.start_frame_spinbox.setFixedWidth(100)
        layout.addWidget(self.start_frame_spinbox)

        self.end_frame_spinbox = QSpinBox()
        self.end_frame_spinbox.setPrefix("끝: ")
        self.end_frame_spinbox.setRange(0, 9999999) # 최대 범위는 일단 넓게
        self.end_frame_spinbox.setValue(end_frame)
        self.end_frame_spinbox.setFixedWidth(100)
        layout.addWidget(self.end_frame_spinbox)

        self.setLayout(layout)
        self.setMouseTracking(True)

        # 스핀박스 값 변경 시그널 연결 (유효성 검사)
        self.start_frame_spinbox.valueChanged.connect(self.validate_frame_range)
        self.end_frame_spinbox.valueChanged.connect(self.validate_frame_range)

        # 초기 유효성 설정
        self.validate_frame_range()

        # 더블 클릭 이벤트를 위한 설정
        self.setAttribute(Qt.WA_Hover)
        self.setMouseTracking(True)

    def get_frame_range(self):
        return self.start_frame_spinbox.value(), self.end_frame_spinbox.value()

    def validate_frame_range(self):
        start_frame = self.start_frame_spinbox.value()
        end_frame = self.end_frame_spinbox.value()

        # 시그널 무한 루프 방지
        self.start_frame_spinbox.blockSignals(True)
        self.end_frame_spinbox.blockSignals(True)

        # start_frame이 end_frame을 넘지 않도록
        if start_frame > end_frame:
            self.end_frame_spinbox.setValue(start_frame)
        
        # end_frame이 start_frame보다 작아지지 않도록
        if end_frame < start_frame:
            self.start_frame_spinbox.setValue(end_frame)
            
        self.end_frame_spinbox.setMinimum(self.start_frame_spinbox.value())
        self.start_frame_spinbox.setMaximum(self.end_frame_spinbox.value())

        self.start_frame_spinbox.blockSignals(False)
        self.end_frame_spinbox.blockSignals(False)


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
