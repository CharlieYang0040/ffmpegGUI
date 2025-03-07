from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QSlider, 
    QDoubleSpinBox, QGroupBox, QCheckBox, QLineEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator

from app.services.logging_service import LoggingService

# 로깅 서비스 설정
logger = LoggingService().get_logger(__name__)

class ControlAreaComponent:
    """
    컨트롤 영역 관련 기능을 제공하는 컴포넌트 클래스
    """
    
    def __init__(self, parent):
        """
        :param parent: 부모 위젯 (FFmpegGui 인스턴스)
        """
        self.parent = parent
        self.framerate = 30
        self.video_width = 1920
        self.video_height = 1080
        self.use_custom_framerate = False
        self.use_custom_resolution = False
        self.global_trim_start = 0
        self.global_trim_end = 0
        self.use_global_trim = False
        
    def create_control_area(self, top_layout):
        """컨트롤 영역 생성"""
        control_layout = QVBoxLayout()

        self.create_play_button(control_layout)
        self.create_speed_control(control_layout)
        self.create_offset_group(control_layout)

        control_layout.addStretch(1)
        top_layout.addLayout(control_layout)
    
    def create_play_button(self, control_layout):
        """재생 버튼 생성"""
        self.parent.play_button = QPushButton('▶️ 재생')
        self.parent.play_button.clicked.connect(self.parent.preview_area.toggle_play)
        control_layout.addWidget(self.parent.play_button)
    
    def create_speed_control(self, control_layout):
        """재생 속도 컨트롤 생성"""
        speed_layout = QVBoxLayout()
        speed_label = QLabel("재생 속도:")
        self.parent.speed_slider = QSlider(Qt.Horizontal)
        self.parent.speed_slider.setRange(20, 800)
        self.parent.speed_slider.setValue(100)
        self.parent.speed_slider.setTickPosition(QSlider.TicksBelow)
        self.parent.speed_slider.setTickInterval(50)
        self.parent.speed_slider.valueChanged.connect(self.parent.preview_area.change_speed)
        self.parent.speed_value_label = QLabel("1.0x")

        speed_layout.addWidget(speed_label)
        speed_layout.addWidget(self.parent.speed_slider)
        speed_layout.addWidget(self.parent.speed_value_label)

        control_layout.addLayout(speed_layout)
    
    def create_offset_group(self, control_layout):
        """편집 옵션 그룹 생성"""
        self.parent.offset_group = QGroupBox("편집 옵션")
        offset_layout = QVBoxLayout()

        self.create_framerate_control(offset_layout)
        self.create_resolution_control(offset_layout)
        self.create_global_trim_control(offset_layout)

        self.parent.offset_group.setLayout(offset_layout)
        control_layout.addWidget(self.parent.offset_group)
    
    def create_framerate_control(self, offset_layout):
        """프레임레이트 컨트롤 생성"""
        framerate_layout = QHBoxLayout()
        self.parent.framerate_checkbox = QCheckBox("프레임레이트 설정:")
        self.parent.framerate_checkbox.setChecked(False)
        self.parent.framerate_checkbox.stateChanged.connect(self.toggle_framerate)
        self.parent.framerate_spinbox = QDoubleSpinBox()
        self.parent.framerate_spinbox.setRange(1, 120)
        self.parent.framerate_spinbox.setValue(30)
        self.parent.framerate_spinbox.setEnabled(False)
        self.parent.framerate_spinbox.valueChanged.connect(self.update_framerate)
        framerate_layout.addWidget(self.parent.framerate_checkbox)
        framerate_layout.addWidget(self.parent.framerate_spinbox)
        offset_layout.addLayout(framerate_layout)
    
    def create_resolution_control(self, offset_layout):
        """해상도 컨트롤 생성"""
        resolution_layout = QHBoxLayout()
        self.parent.resolution_checkbox = QCheckBox("해상도 설정:")
        self.parent.resolution_checkbox.setChecked(False)
        self.parent.resolution_checkbox.stateChanged.connect(self.toggle_resolution)

        self.parent.width_edit = QLineEdit()
        self.parent.width_edit.setValidator(QIntValidator(320, 9999))
        self.parent.width_edit.setText("1920")
        self.parent.width_edit.setFixedWidth(60)
        self.parent.width_edit.setEnabled(False)

        self.parent.height_edit = QLineEdit()
        self.parent.height_edit.setValidator(QIntValidator(240, 9999))
        self.parent.height_edit.setText("1080")
        self.parent.height_edit.setFixedWidth(60)
        self.parent.height_edit.setEnabled(False)

        resolution_layout.addWidget(self.parent.resolution_checkbox)
        resolution_layout.addWidget(self.parent.width_edit)
        resolution_layout.addWidget(QLabel("x"))
        resolution_layout.addWidget(self.parent.height_edit)

        self.parent.width_edit.textChanged.connect(self.update_resolution)
        self.parent.height_edit.textChanged.connect(self.update_resolution)

        offset_layout.addLayout(resolution_layout)
    
    def create_global_trim_control(self, offset_layout):
        """전역 트림 컨트롤 생성"""
        trim_group = QGroupBox("전역 트림")
        trim_layout = QVBoxLayout()
        
        # 전역 트림 활성화 체크박스
        self.parent.global_trim_checkbox = QCheckBox("전역 트림 사용")
        self.parent.global_trim_checkbox.setChecked(False)
        self.parent.global_trim_checkbox.stateChanged.connect(self.toggle_global_trim)
        trim_layout.addWidget(self.parent.global_trim_checkbox)
        
        # 시작 트림 슬라이더
        start_layout = QHBoxLayout()
        start_layout.addWidget(QLabel("시작 트림:"))
        self.parent.global_trim_start_slider = QSlider(Qt.Horizontal)
        self.parent.global_trim_start_slider.setRange(0, 300)
        self.parent.global_trim_start_slider.setValue(0)
        self.parent.global_trim_start_slider.setEnabled(False)
        self.parent.global_trim_start_slider.valueChanged.connect(self.update_global_trim_start)
        start_layout.addWidget(self.parent.global_trim_start_slider)
        self.parent.global_trim_start_label = QLabel("0")
        start_layout.addWidget(self.parent.global_trim_start_label)
        trim_layout.addLayout(start_layout)
        
        # 끝 트림 슬라이더
        end_layout = QHBoxLayout()
        end_layout.addWidget(QLabel("끝 트림:"))
        self.parent.global_trim_end_slider = QSlider(Qt.Horizontal)
        self.parent.global_trim_end_slider.setRange(0, 300)
        self.parent.global_trim_end_slider.setValue(0)
        self.parent.global_trim_end_slider.setEnabled(False)
        self.parent.global_trim_end_slider.valueChanged.connect(self.update_global_trim_end)
        end_layout.addWidget(self.parent.global_trim_end_slider)
        self.parent.global_trim_end_label = QLabel("0")
        end_layout.addWidget(self.parent.global_trim_end_label)
        trim_layout.addLayout(end_layout)
        
        # 프레임 단위 트림 체크박스 추가
        self.parent.frame_based_trim_checkbox = QCheckBox("프레임 단위 트림 사용")
        self.parent.frame_based_trim_checkbox.setChecked(False)
        self.parent.frame_based_trim_checkbox.setToolTip("초 단위 변환 없이 프레임 번호로 직접 트림합니다.\n더 정확하지만 처리 속도가 느릴 수 있습니다.")
        trim_layout.addWidget(self.parent.frame_based_trim_checkbox)
        
        trim_group.setLayout(trim_layout)
        offset_layout.addWidget(trim_group)
    
    def toggle_framerate(self, state):
        """프레임레이트 설정 토글"""
        self.use_custom_framerate = state == Qt.CheckState.Checked.value
        self.parent.framerate_spinbox.setEnabled(self.use_custom_framerate)
        if not self.use_custom_framerate:
            # self.parent.encoding_options.pop("r", None)
            pass
    
    def toggle_resolution(self, state):
        """해상도 설정 토글"""
        self.use_custom_resolution = state == Qt.CheckState.Checked.value
        self.parent.width_edit.setEnabled(self.use_custom_resolution)
        self.parent.height_edit.setEnabled(self.use_custom_resolution)
        self.update_resolution()
    
    def update_resolution(self):
        """해상도 업데이트"""
        if self.use_custom_resolution:
            width = self.parent.width_edit.text()
            height = self.parent.height_edit.text()
            if width and height:
                self.video_width = int(width)
                self.video_height = int(height)
                self.parent.encoding_options["s"] = f"{width}x{height}"
        else:
            # self.parent.encoding_options.pop("s", None)
            pass
    
    def update_framerate(self, value):
        """프레임레이트 업데이트"""
        self.framerate = value
        if self.use_custom_framerate:
            self.parent.encoding_options["r"] = str(self.framerate)
    
    def toggle_global_trim(self, state):
        """전역 트림 토글"""
        self.use_global_trim = state == Qt.CheckState.Checked.value
        self.parent.global_trim_start_slider.setEnabled(self.use_global_trim)
        self.parent.global_trim_end_slider.setEnabled(self.use_global_trim)
    
    def update_global_trim_start(self, value):
        """전역 트림 시작 값 업데이트"""
        self.global_trim_start = value
        self.parent.global_trim_start_label.setText(str(value))
    
    def update_global_trim_end(self, value):
        """전역 트림 끝 값 업데이트"""
        self.global_trim_end = value
        self.parent.global_trim_end_label.setText(str(value)) 