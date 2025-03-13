# list_widget_item.py

from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QSpinBox
from PySide6.QtCore import Qt, QEvent
import os
import re
from app.utils.utils import get_first_sequence_file


class ListWidgetItem(QWidget):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.is_selected = False
        self.is_hovered = False
        self.init_ui()
        self.set_file_status(self.check_file_exists())

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)

        # 파일명과 버전을 함께 표시할 레이블
        self.file_label = QLabel()
        self.file_label.setToolTip(self.file_path)
        layout.addWidget(self.file_label)

        # 트림 스핀박스 추가 (프레임 단위로 변경)
        self.trim_start_spinbox = QSpinBox()
        self.trim_start_spinbox.setPrefix("앞: ")
        self.trim_start_spinbox.setSuffix("f")
        self.trim_start_spinbox.setRange(0, 10000)
        self.trim_start_spinbox.setFixedWidth(100)
        self.trim_start_spinbox.setToolTip("앞에서부터 몇 프레임을 트림할지 설정합니다.")
        layout.addWidget(self.trim_start_spinbox)

        self.trim_end_spinbox = QSpinBox()
        self.trim_end_spinbox.setPrefix("뒤: ")
        self.trim_end_spinbox.setSuffix("f")
        self.trim_end_spinbox.setRange(0, 10000)
        self.trim_end_spinbox.setFixedWidth(100)
        self.trim_end_spinbox.setToolTip("뒤에서부터 몇 프레임을 트림할지 설정합니다.")
        layout.addWidget(self.trim_end_spinbox)

        self.setLayout(layout)
        self.setMouseTracking(True)

        # 더블 클릭 이벤트를 위한 설정
        self.setAttribute(Qt.WA_Hover)
        self.setMouseTracking(True)

        # 초기 레이블 업데이트
        self.update_labels()

    def extract_version(self, path):
        """파일 경로에서 버전 정보 추출"""
        version_pattern = r'v(\d+)'
        match = re.search(version_pattern, path)
        if match:
            return f"v{match.group(1)}"
        return ""

    def check_file_exists(self):
        """파일 존재 여부 확인 (시퀀스 파일 고려)"""
        if '%' in self.file_path:  # 시퀀스 파일인 경우
            first_file = get_first_sequence_file(self.file_path)
            return bool(first_file)  # None이 아니면 True
        return os.path.exists(self.file_path)  # 일반 파일인 경우

    def get_trim_values(self):
        return self.trim_start_spinbox.value(), self.trim_end_spinbox.value()

    def set_trim_values(self, start_value, end_value):
        """트림 값 설정"""
        self.trim_start_spinbox.setValue(int(start_value))
        self.trim_end_spinbox.setValue(int(end_value))
        return True

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

    def update_labels(self):
        """라벨 텍스트 업데이트 및 파일 상태 확인"""
        basename = os.path.basename(self.file_path)
        version = self.extract_version(self.file_path)
        
        # 버전 정보가 있으면 파일명과 버전을 함께 표시
        if version:
            display_text = f"{basename} ({version})"
        else:
            display_text = basename
            
        self.file_label.setText(display_text)
        self.file_label.setToolTip(self.file_path)
        self.set_file_status(self.check_file_exists())

    def set_file_status(self, exists):
        """파일 존재 여부에 따라 시각적 상태 업데이트"""
        if exists:
            self.file_label.setStyleSheet("")
            self.file_label.setToolTip(self.file_path)
        else:
            self.file_label.setStyleSheet("color: #FF6B6B;")  # 빨간색으로 표시
            self.file_label.setToolTip(f"파일을 찾을 수 없습니다\n{self.file_path}")
