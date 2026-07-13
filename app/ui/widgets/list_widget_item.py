# list_widget_item.py

import os
import re

from PySide6.QtCore import QEvent, Qt, QThread, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QVBoxLayout, QWidget

from app.core.job_builder import detect_media_type
from app.utils.utils import get_first_sequence_file


class MediaMetadataLoader(QThread):
    loaded = Signal(dict)

    def __init__(self, file_path, debug_mode=False):
        super().__init__()
        self.file_path = file_path
        self.debug_mode = debug_mode

    def run(self):
        try:
            probe_path = self.file_path
            if "%" in self.file_path:
                first_file = get_first_sequence_file(self.file_path)
                if first_file:
                    probe_path = first_file
            
            from app.core.ffmpeg_core import get_media_properties
            props = get_media_properties(probe_path, self.debug_mode)
            self.loaded.emit(props)
        except Exception:
            self.loaded.emit({})


class ListWidgetItem(QWidget):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.is_selected = False
        self.is_hovered = False
        self.total_frames = 0
        self.fps = 30.0
        self._pending_trim_end = None
        self.init_ui()
        self.set_file_status(self.check_file_exists())
        
        # 백그라운드 미디어 분석 실행
        from app.utils.utils import get_debug_mode
        self.loader = MediaMetadataLoader(self.file_path, get_debug_mode())
        self.loader.loaded.connect(self.on_metadata_loaded)
        self.loader.start()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.file_label = QLabel()
        self.file_label.setToolTip(self.file_path)
        self.meta_label = QLabel()
        self.meta_label.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        text_layout.addWidget(self.file_label)
        text_layout.addWidget(self.meta_label)
        layout.addLayout(text_layout, 1)

        self.trim_start_spinbox = QSpinBox()
        self.trim_start_spinbox.setPrefix("시작 ")
        self.trim_start_spinbox.setSuffix("f")
        self.trim_start_spinbox.setRange(1, 1000000)
        self.trim_start_spinbox.setValue(1)
        self.trim_start_spinbox.setFixedWidth(86)
        self.trim_start_spinbox.setToolTip("트림 시작 프레임 번호 (1-indexed)")
        self.trim_start_spinbox.valueChanged.connect(self.on_trim_changed)
        layout.addWidget(self.trim_start_spinbox)

        self.trim_end_spinbox = QSpinBox()
        self.trim_end_spinbox.setPrefix("끝 ")
        self.trim_end_spinbox.setSuffix("f")
        self.trim_end_spinbox.setRange(1, 1000000)
        self.trim_end_spinbox.setValue(1)
        self.trim_end_spinbox.setFixedWidth(86)
        self.trim_end_spinbox.setToolTip("트림 종료 프레임 번호 (1-indexed)")
        self.trim_end_spinbox.valueChanged.connect(self.on_trim_changed)
        layout.addWidget(self.trim_end_spinbox)

        self.setLayout(layout)
        self.setAttribute(Qt.WA_Hover)
        self.setMouseTracking(True)
        self.update_labels()

    def extract_version(self, path):
        match = re.search(r"v(\d+)", path)
        if match:
            return f"v{match.group(1)}"
        return ""

    def check_file_exists(self):
        if "%" in self.file_path:
            return bool(get_first_sequence_file(self.file_path))
        return os.path.exists(self.file_path)

    def get_trim_values(self):
        in_frame = self.trim_start_spinbox.value()
        out_frame = self.trim_end_spinbox.value()
        
        trim_start = max(0, in_frame - 1)
        if self.total_frames > 0:
            trim_end = max(0, self.total_frames - out_frame)
        else:
            trim_end = 0
        return trim_start, trim_end

    def set_trim_values(self, start_value, end_value, refresh=True):
        self.trim_start_spinbox.blockSignals(True)
        self.trim_end_spinbox.blockSignals(True)
        
        in_frame = int(start_value) + 1
        self.trim_start_spinbox.setValue(in_frame)
        
        if self.total_frames > 0:
            out_frame = max(in_frame, self.total_frames - int(end_value))
            self.trim_end_spinbox.setValue(out_frame)
        else:
            self._pending_trim_end = int(end_value)
            self.trim_end_spinbox.setValue(10000 - int(end_value))
            
        self.trim_start_spinbox.blockSignals(False)
        self.trim_end_spinbox.blockSignals(False)
        self.update_labels()
        if refresh:
            self._refresh_parent_inspector()
        return True

    def on_metadata_loaded(self, props):
        if not props:
            return
        
        self.fps = float(props.get('r', 30.0))
        
        if 'nb_frames' in props and int(props['nb_frames']) > 0:
            self.total_frames = int(props['nb_frames'])
        else:
            duration = float(props.get('duration', 0.0))
            self.total_frames = int(duration * self.fps)
            
        if self.total_frames <= 0:
            self.total_frames = 300
            
        self.trim_start_spinbox.blockSignals(True)
        self.trim_end_spinbox.blockSignals(True)
        
        self.trim_start_spinbox.setRange(1, self.total_frames)
        self.trim_end_spinbox.setRange(1, self.total_frames)
        
        if self._pending_trim_end is not None:
            out_frame = max(self.trim_start_spinbox.value(), self.total_frames - self._pending_trim_end)
            self.trim_end_spinbox.setValue(out_frame)
            self._pending_trim_end = None
        else:
            self.trim_end_spinbox.setValue(self.total_frames)
            
        self.trim_start_spinbox.blockSignals(False)
        self.trim_end_spinbox.blockSignals(False)
        self.update_labels()

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
            self.setStyleSheet("background-color: #343a40;")
        elif self.is_hovered:
            self.setStyleSheet("background-color: #252a2f;")
        else:
            self.setStyleSheet("")

    def mouseDoubleClickEvent(self, event):
        list_widget = self._parent_list_widget()
        if list_widget and hasattr(list_widget, "handle_double_click"):
            list_widget.handle_double_click(self.file_path)

    def update_labels(self):
        basename = os.path.basename(self.file_path)
        version = self.extract_version(self.file_path)
        display_text = f"{basename} ({version})" if version else basename
        self.file_label.setText(display_text)
        self.file_label.setToolTip(self.file_path)

        media_type = detect_media_type(self.file_path).value.replace("_", " ").upper()
        in_frame = self.trim_start_spinbox.value()
        out_frame = self.trim_end_spinbox.value()
        status = "OK" if self.check_file_exists() else "MISSING"
        
        if self.total_frames > 0:
            self.meta_label.setText(f"{media_type} | {status} | range {in_frame}f - {out_frame}f (total: {self.total_frames}f)")
        else:
            self.meta_label.setText(f"{media_type} | {status} | range {in_frame}f - {out_frame}f")
        self.set_file_status(status == "OK")

    def set_file_status(self, exists):
        if exists:
            self.file_label.setStyleSheet("")
            self.file_label.setToolTip(self.file_path)
        else:
            self.file_label.setStyleSheet("color: #FF6B6B;")
            self.file_label.setToolTip(f"파일을 찾을 수 없습니다\n{self.file_path}")

    def on_trim_changed(self):
        self.update_labels()
        self._refresh_parent_inspector()

    def _parent_list_widget(self):
        parent = self.parent()
        if parent and hasattr(parent, "parent"):
            parent = parent.parent()
        return parent

    def _refresh_parent_inspector(self):
        list_widget = self._parent_list_widget()
        main_window = getattr(list_widget, "main_window", None)
        if main_window and hasattr(main_window, "refresh_job_inspector"):
            main_window.refresh_job_inspector()
