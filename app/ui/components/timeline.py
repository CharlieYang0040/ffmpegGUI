from typing import Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from app.core.commands import (
    SeekFrameCommand,
    SetInPointCommand,
    SetOutPointCommand,
    command_manager,
)
from app.core.events import Events, event_emitter
from app.services.logging_service import LoggingService
from app.ui.widgets.cut_timeline_widget import CutTimelineWidget


logger = LoggingService().get_logger(__name__)


class TimelineComponent:
    """Playback controls and the single WorkspaceState-backed cut timeline."""

    def __init__(self, parent):
        self.parent = parent
        self.timeline_widget = None
        self.play_button = None
        self.speed_slider = None
        self.speed_value_label = None
        self.current_timecode_label = None
        self._shortcuts = ()

    def create_timeline_area(self, layout):
        timeline_frame = QFrame()
        timeline_frame.setObjectName("cut-timeline-panel")
        timeline_frame.setFixedHeight(146)

        timeline_layout = QVBoxLayout(timeline_frame)
        timeline_layout.setContentsMargins(10, 8, 10, 8)
        timeline_layout.setSpacing(6)

        self.timeline_widget = CutTimelineWidget()
        self.timeline_widget.frame_changed.connect(self._on_frame_changed)
        self.timeline_widget.in_point_changed.connect(self._on_in_point_changed)
        self.timeline_widget.out_point_changed.connect(self._on_out_point_changed)
        self.timeline_widget.playback_requested.connect(self._on_playback_requested)
        timeline_layout.addWidget(self.timeline_widget)
        layout.addWidget(timeline_frame)

    def create_playback_controls(self, layout):
        playback_layout = QHBoxLayout()

        self.play_button = QPushButton("▶")
        self.play_button.setObjectName("play-button")
        self.play_button.setToolTip("재생 / 일시정지 (Space)")
        self.play_button.setFixedSize(34, 30)
        self.play_button.clicked.connect(self._on_play_button_clicked)
        self.play_button.setEnabled(False)
        self.parent.play_button = self.play_button
        playback_layout.addWidget(self.play_button)

        self.speed_slider = QSlider(Qt.Horizontal)
        self.speed_slider.setRange(10, 400)
        self.speed_slider.setValue(100)
        self.speed_slider.valueChanged.connect(self._on_speed_changed)
        self.speed_slider.hide()
        self.parent.speed_slider = self.speed_slider

        self.speed_value_label = QPushButton("1.0x")
        self.speed_value_label.setToolTip("재생 속도")
        self.speed_value_label.setFixedHeight(20)
        self.speed_value_label.setMinimumWidth(40)
        self.parent.speed_value_label = self.speed_value_label
        speed_menu = QMenu(self.speed_value_label)
        for speed in (0.5, 1.0, 1.5, 2.0):
            action = QAction(f"{speed:.1f}x", speed_menu)
            action.triggered.connect(
                lambda checked=False, value=speed: self.speed_slider.setValue(
                    int(value * 100)
                )
            )
            speed_menu.addAction(action)
        self.speed_value_label.setMenu(speed_menu)

        self.current_timecode_label = QLabel("00:00:00:00")
        self.current_timecode_label.setObjectName("viewer-timecode")
        playback_layout.addStretch(1)
        playback_layout.addWidget(self.current_timecode_label)
        playback_layout.addStretch(1)
        playback_layout.addWidget(self.speed_value_label)
        playback_layout.addStretch(1)
        layout.addLayout(playback_layout)

    def set_video_info(
        self,
        frame_count: int,
        fps: float,
        duration: float,
        nb_frames: int = 0,
    ):
        if not self.timeline_widget:
            return
        if frame_count <= 0 and nb_frames <= 0:
            self.timeline_widget.set_video_info(1, 30.0, 0.0, 0)
            self.timeline_widget.set_current_frame(1, emit_signal=False)
            if self.play_button:
                self.play_button.setEnabled(False)
            return

        frame_count = int(nb_frames or frame_count)
        fps = float(fps or 30.0)
        duration = float(duration or (frame_count / fps))
        self.timeline_widget.set_video_info(frame_count, fps, duration, nb_frames)
        if self.play_button:
            self.play_button.setEnabled(True)

    def set_current_frame(self, frame: int, emit_signal: bool = True):
        if self.timeline_widget:
            self.timeline_widget.set_current_frame(frame, emit_signal)

    def get_current_frame(self) -> int:
        return self.timeline_widget.current_frame if self.timeline_widget else 1

    def get_in_point(self) -> int:
        return self.timeline_widget.in_point if self.timeline_widget else 0

    def get_out_point(self) -> int:
        return self.timeline_widget.out_point if self.timeline_widget else 0

    def get_in_out_points(self) -> Tuple[int, int]:
        return self.get_in_point(), self.get_out_point()

    def _on_frame_changed(self, frame: int):
        fps = max(
            1.0,
            float(getattr(self.timeline_widget, "fps", 30.0) or 30.0),
        )
        total_seconds = max(0.0, (frame - 1) / fps)
        hours = int(total_seconds // 3600)
        minutes = int(total_seconds % 3600 // 60)
        seconds = int(total_seconds % 60)
        frames = int((total_seconds - int(total_seconds)) * fps)
        if self.current_timecode_label:
            self.current_timecode_label.setText(
                f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"
            )

    def _on_in_point_changed(self, frame: int):
        del frame

    def _on_out_point_changed(self, frame: int):
        del frame

    def _on_playback_requested(self):
        if hasattr(self.parent, "preview_area"):
            self.parent.preview_area.toggle_play()

    def _on_play_button_clicked(self):
        if hasattr(self.parent, "preview_area"):
            self.parent.preview_area.toggle_play()

    def _on_speed_changed(self, value):
        speed = value / 100.0
        self.speed_value_label.setText(f"{speed:.1f}x")
        if hasattr(self.parent, "preview_area"):
            self.parent.preview_area.change_speed(speed)

    def setup_shortcuts(self):
        bindings = (
            ("i", self.set_current_as_in_point),
            ("o", self.set_current_as_out_point),
            ("Space", self._on_play_button_clicked),
            ("Left", self.seek_prev_frame),
            ("Right", self.seek_next_frame),
            ("Home", self.seek_to_start),
            ("End", self.seek_to_end),
        )
        shortcuts = []
        for sequence, callback in bindings:
            shortcut = QShortcut(QKeySequence(sequence), self.parent)
            shortcut.activated.connect(callback)
            shortcuts.append(shortcut)
        self._shortcuts = tuple(shortcuts)

    def set_current_as_in_point(self):
        timeline = self.timeline_widget
        if not timeline or timeline.current_frame > timeline.out_point:
            return
        command_manager.execute(
            SetInPointCommand(
                timeline,
                timeline.in_point,
                timeline.current_frame,
            )
        )
        event_emitter.emit(Events.TIMELINE_SET_IN_POINT, timeline.current_frame)

    def set_current_as_out_point(self):
        timeline = self.timeline_widget
        if not timeline or timeline.current_frame < timeline.in_point:
            return
        command_manager.execute(
            SetOutPointCommand(
                timeline,
                timeline.out_point,
                timeline.current_frame,
            )
        )
        event_emitter.emit(Events.TIMELINE_SET_OUT_POINT, timeline.current_frame)

    def seek_prev_frame(self):
        timeline = self.timeline_widget
        if timeline and timeline.current_frame > 1:
            timeline.set_current_frame(timeline.current_frame - 1)
            event_emitter.emit(
                Events.TIMELINE_SEEK_PREV_FRAME,
                timeline.current_frame,
            )

    def seek_next_frame(self):
        timeline = self.timeline_widget
        if timeline and timeline.current_frame < timeline.frame_count:
            timeline.set_current_frame(timeline.current_frame + 1)
            event_emitter.emit(
                Events.TIMELINE_SEEK_NEXT_FRAME,
                timeline.current_frame,
            )

    def seek_to_start(self):
        timeline = self.timeline_widget
        if not timeline:
            return
        command_manager.execute(
            SeekFrameCommand(timeline, timeline.current_frame, 1)
        )
        event_emitter.emit(Events.TIMELINE_SEEK_START, 1)

    def seek_to_end(self):
        timeline = self.timeline_widget
        if not timeline:
            return
        last_frame = max(1, timeline.frame_count)
        command_manager.execute(
            SeekFrameCommand(timeline, timeline.current_frame, last_frame)
        )
        event_emitter.emit(Events.TIMELINE_SEEK_END, last_frame)

    def reset_in_out_points(self):
        if not self.timeline_widget:
            return
        self.timeline_widget.set_in_point(1)
        self.timeline_widget.set_out_point(
            max(1, self.timeline_widget.frame_count)
        )
