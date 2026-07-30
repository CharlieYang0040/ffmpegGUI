# list_widget_item.py

import os
import re
import subprocess
import uuid

from PySide6.QtCore import QEvent, Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.core.job_builder import (
    clip_range_to_trim,
    detect_media_type,
    trim_to_clip_range,
)
from app.core.models import ClipRange, FrameTrim
from app.utils.utils import get_first_sequence_file, get_sequence_files


def load_media_metadata(file_path, debug_mode=False):
    """Load media properties, preserving image-sequence frame counts."""
    probe_path = file_path
    sequence_files = []
    if "%" in file_path:
        sequence_files = get_sequence_files(file_path)
        if sequence_files:
            probe_path = sequence_files[0]

    from app.core.ffmpeg_core import get_media_properties

    props = dict(get_media_properties(probe_path, debug_mode) or {})
    if sequence_files:
        props["nb_frames"] = len(sequence_files)
        fps = float(props.get("r", 30.0) or 30.0)
        props["duration"] = len(sequence_files) / fps if fps > 0 else 0.0
    return props


class MediaMetadataLoader(QThread):
    loaded = Signal(dict)

    def __init__(self, file_path, debug_mode=False):
        super().__init__()
        self.file_path = file_path
        self.debug_mode = debug_mode

    def run(self):
        try:
            props = load_media_metadata(self.file_path, self.debug_mode)
            self.loaded.emit(props)
        except Exception:
            self.loaded.emit({})


class ThumbnailLoader(QThread):
    loaded = Signal(QImage)

    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path

    def run(self):
        image = QImage()
        try:
            media_type = detect_media_type(self.file_path)
            source_path = self.file_path
            if media_type.value == "image_sequence":
                source_path = get_first_sequence_file(self.file_path) or ""
            if media_type.value in {"image", "image_sequence", "webp"}:
                image = QImage(source_path)
            elif media_type.value == "video":
                from app.core.ffmpeg_manager import FFmpegManager

                ffmpeg_path = FFmpegManager().get_ffmpeg_path()
                if ffmpeg_path:
                    creation_flags = (
                        subprocess.CREATE_NO_WINDOW
                        if os.name == "nt"
                        else 0
                    )
                    result = subprocess.run(
                        [
                            ffmpeg_path,
                            "-v",
                            "error",
                            "-ss",
                            "0",
                            "-i",
                            source_path,
                            "-frames:v",
                            "1",
                            "-vf",
                            "scale=160:-1",
                            "-f",
                            "image2pipe",
                            "-vcodec",
                            "png",
                            "pipe:1",
                        ],
                        capture_output=True,
                        timeout=10,
                        creationflags=creation_flags,
                        check=False,
                    )
                    if result.returncode == 0:
                        image.loadFromData(result.stdout, "PNG")
        except Exception:
            image = QImage()
        if not image.isNull():
            self.loaded.emit(image)


class ListWidgetItem(QWidget):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.clip_id = uuid.uuid4().hex
        self.file_path = file_path
        self.is_selected = False
        self.is_hovered = False
        self.total_frames = 0
        self.fps = 30.0
        self.source_range = None
        self._pending_trim = FrameTrim()
        self.init_ui()
        file_exists = self.check_file_exists()
        self.set_file_status(file_exists)
        
        # 백그라운드 미디어 분석 실행
        self.loader = None
        self.thumbnail_loader = None
        if file_exists:
            from app.utils.utils import get_debug_mode
            self.loader = MediaMetadataLoader(self.file_path, get_debug_mode())
            self.loader.loaded.connect(self.on_metadata_loaded)
            self.loader.start()
            self.thumbnail_loader = ThumbnailLoader(self.file_path, self)
            self.thumbnail_loader.loaded.connect(self.on_thumbnail_loaded)
            self.thumbnail_loader.start()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(8)

        drag_handle = QLabel("⋮⋮")
        drag_handle.setProperty("role", "muted")
        drag_handle.setToolTip("끌어서 클립 순서 변경")
        layout.addWidget(drag_handle)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setObjectName("clip-thumbnail")
        self.thumbnail_label.setAlignment(Qt.AlignCenter)
        self.thumbnail_label.setFixedSize(64, 40)
        layout.addWidget(self.thumbnail_label)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)

        self.file_label = QLabel()
        self.file_label.setToolTip(self.file_path)
        self.meta_label = QLabel()
        self.meta_label.setStyleSheet("font-size: 11px;")
        text_layout.addWidget(self.file_label)
        text_layout.addWidget(self.meta_label)
        layout.addLayout(text_layout, 1)

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
        """Compatibility boundary for legacy processors and saved list commands."""
        if self.source_range is not None and self.total_frames > 0:
            trim = clip_range_to_trim(self.source_range, self.total_frames)
        else:
            trim = self._pending_trim
        return trim.head_frames, trim.tail_frames

    def get_clip_range(self):
        return self.source_range

    def set_trim_values(self, start_value, end_value, refresh=True):
        """Compatibility adapter from legacy head/tail values to ClipRange."""
        trim = FrameTrim(start_value, end_value)
        if self.total_frames > 0:
            self.source_range = trim_to_clip_range(trim, self.total_frames)
            self._pending_trim = FrameTrim()
        else:
            self._pending_trim = trim
        self.update_labels()
        if refresh:
            self._notify_clip_range_changed()
        return True

    def set_clip_range(self, source_range: ClipRange, refresh=True):
        if self.total_frames <= 0:
            raise ValueError("미디어 정보가 준비되기 전에는 클립 구간을 설정할 수 없습니다.")
        if source_range.source_out > self.total_frames:
            raise ValueError("클립 구간이 원본 프레임 범위를 벗어났습니다.")
        self.source_range = source_range
        self._pending_trim = FrameTrim()
        self.update_labels()
        if refresh:
            self._notify_clip_range_changed()
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
            
        if self.source_range is None:
            head = min(self._pending_trim.head_frames, self.total_frames - 1)
            tail = min(
                self._pending_trim.tail_frames,
                self.total_frames - head - 1,
            )
            self.source_range = trim_to_clip_range(
                FrameTrim(head, tail),
                self.total_frames,
            )
            self._pending_trim = FrameTrim()
        self.update_labels()
        self._refresh_parent_inspector()

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
        badge_labels = {
            "VIDEO": "영상",
            "IMAGE": "이미지",
            "IMAGE SEQUENCE": "시퀀스",
            "WEBP": "WebP",
            "UNKNOWN": "파일",
        }
        if not self.thumbnail_label.pixmap():
            self.thumbnail_label.setText(badge_labels.get(media_type, media_type))
        status = "정상" if self.check_file_exists() else "파일 없음"
        
        if self.total_frames > 0 and self.source_range is not None:
            in_frame = self.source_range.source_in + 1
            out_frame = self.source_range.source_out
            selected_frames = self.source_range.frame_count
            self.meta_label.setText(
                f"{status} · {in_frame}–{out_frame}f · "
                f"{selected_frames}/{self.total_frames}프레임"
            )
        else:
            self.meta_label.setText(f"{status} · 미디어 정보 확인 중")
        self.set_file_status(status == "정상")

    def on_thumbnail_loaded(self, image):
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            return
        self.thumbnail_label.setPixmap(
            pixmap.scaled(
                self.thumbnail_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )
        list_widget = self._parent_list_widget()
        main_window = getattr(list_widget, "main_window", None)
        if main_window and hasattr(main_window, "update_cut_timeline"):
            main_window.update_cut_timeline(
                getattr(main_window, "workspace_state", None)
            )

    def set_file_status(self, exists):
        if exists:
            self.file_label.setStyleSheet("")
            self.file_label.setToolTip(self.file_path)
        else:
            self.file_label.setStyleSheet("color: #FF6B6B;")
            self.file_label.setToolTip(f"파일을 찾을 수 없습니다\n{self.file_path}")

    def _notify_clip_range_changed(self):
        list_widget = self._parent_list_widget()
        main_window = getattr(list_widget, "main_window", None)
        if main_window and hasattr(main_window, "apply_selected_item_trim_to_timeline"):
            main_window.apply_selected_item_trim_to_timeline()
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
