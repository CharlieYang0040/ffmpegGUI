from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

from app.services.logging_service import LoggingService
from app.ui.components.timeline import TimelineComponent

logger = LoggingService().get_logger(__name__)


class ControlAreaComponent:
    """Encoding and trim controls shown in the Job Inspector."""

    def __init__(self, parent):
        self.parent = parent
        self.framerate = 30
        self.video_width = 1920
        self.video_height = 1080
        self.use_custom_framerate = False
        self.use_custom_resolution = False
        self.timeline_component = None

    def create_control_area(self, parent_layout):
        control_layout = QVBoxLayout()
        self.create_offset_group(control_layout)
        if hasattr(self.parent, "preview_area") and self.parent.preview_area.timeline:
            self.timeline_component = self.parent.preview_area.timeline
        else:
            self.timeline_component = TimelineComponent(self.parent)
        parent_layout.addLayout(control_layout)

    def create_offset_group(self, control_layout):
        options_group = QGroupBox("추가 설정")
        options_layout = QVBoxLayout(options_group)
        self.create_framerate_control(options_layout)
        self.create_resolution_control(options_layout)
        control_layout.addWidget(options_group)

    def create_framerate_control(self, layout):
        row = QHBoxLayout()
        self.parent.framerate_checkbox = QCheckBox("FPS 고정")
        self.parent.framerate_checkbox.setChecked(False)
        self.parent.framerate_checkbox.stateChanged.connect(self.toggle_framerate)
        self.parent.framerate_spinbox = QDoubleSpinBox()
        self.parent.framerate_spinbox.setRange(1, 120)
        self.parent.framerate_spinbox.setValue(30)
        self.parent.framerate_spinbox.setDecimals(2)
        self.parent.framerate_spinbox.setEnabled(False)
        self.parent.framerate_spinbox.valueChanged.connect(self.update_framerate)
        row.addWidget(self.parent.framerate_checkbox)
        row.addWidget(self.parent.framerate_spinbox)
        layout.addLayout(row)

    def create_resolution_control(self, layout):
        row = QHBoxLayout()
        self.parent.resolution_checkbox = QCheckBox("해상도 고정")
        self.parent.resolution_checkbox.setChecked(False)
        self.parent.resolution_checkbox.stateChanged.connect(self.toggle_resolution)
        self.parent.width_edit = QLineEdit()
        self.parent.width_edit.setValidator(QIntValidator(320, 9999))
        self.parent.width_edit.setText("1920")
        self.parent.width_edit.setFixedWidth(64)
        self.parent.width_edit.setEnabled(False)
        self.parent.height_edit = QLineEdit()
        self.parent.height_edit.setValidator(QIntValidator(240, 9999))
        self.parent.height_edit.setText("1080")
        self.parent.height_edit.setFixedWidth(64)
        self.parent.height_edit.setEnabled(False)
        self.parent.width_edit.textChanged.connect(self.update_resolution)
        self.parent.height_edit.textChanged.connect(self.update_resolution)
        row.addWidget(self.parent.resolution_checkbox)
        row.addWidget(self.parent.width_edit)
        row.addWidget(QLabel("x"))
        row.addWidget(self.parent.height_edit)
        layout.addLayout(row)

    def toggle_framerate(self, state):
        self.use_custom_framerate = state == Qt.CheckState.Checked.value
        self.parent.framerate_spinbox.setEnabled(self.use_custom_framerate)
        self._notify_options_changed()

    def toggle_resolution(self, state):
        self.use_custom_resolution = state == Qt.CheckState.Checked.value
        self.parent.width_edit.setEnabled(self.use_custom_resolution)
        self.parent.height_edit.setEnabled(self.use_custom_resolution)
        self.update_resolution()

    def update_resolution(self):
        if self.use_custom_resolution:
            width = self.parent.width_edit.text()
            height = self.parent.height_edit.text()
            if width and height:
                self.video_width = int(width)
                self.video_height = int(height)
                self.parent.encoding_options["s"] = f"{width}x{height}"
        self._notify_options_changed()

    def update_framerate(self, value):
        self.framerate = value
        if self.use_custom_framerate:
            self.parent.encoding_options["r"] = str(self.framerate)
        self._notify_options_changed()

    def _notify_options_changed(self):
        if hasattr(self.parent, "refresh_job_inspector"):
            self.parent.refresh_job_inspector()
