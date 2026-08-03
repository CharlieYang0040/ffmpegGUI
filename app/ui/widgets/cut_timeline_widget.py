import math
import os

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QKeyEvent, QMouseEvent, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.core.models import ClipRange, WorkspaceState
from app.ui.timeline_geometry import TimelineGeometry


class CutTimelineWidget(QWidget):
    """Single-track cut timeline backed by WorkspaceState."""

    frame_changed = Signal(int)
    in_point_changed = Signal(int)
    out_point_changed = Signal(int)
    playback_requested = Signal()
    clip_selected = Signal(str)
    clip_range_committed = Signal(str, int, int)
    clip_move_committed = Signal(str, int)
    split_requested = Signal()

    RULER_HEIGHT = 24
    TRACK_TOP = 32
    TRACK_HEIGHT = 64
    HANDLE_WIDTH = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.workspace_state = WorkspaceState()
        self.selected_clip_id = None
        self.thumbnails = {}
        self.frame_count = 0
        self.current_frame = 1
        self.in_point = 1
        self.out_point = 1
        self.fps = 30.0
        self.duration = 0.0
        self.zoom = 1.0
        self.scroll_offset = 0.0
        self._drag_mode = None
        self._drag_clip_id = None
        self._drag_origin = QPoint()
        self._drag_original_range = None
        self._preview_range = None
        self._move_target_index = None
        self._fit_signature = ()
        self._fit_reference_frames = 1
        self._scaled_thumbnail_cache = {}
        self._geometry = TimelineGeometry(1, ())
        self.setMinimumHeight(118)
        self.setFixedHeight(118)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setToolTip("클립을 선택하고 가장자리를 끌어 사용할 구간을 조정하세요")

    def set_workspace_state(self, state: WorkspaceState | None, thumbnails=None):
        self.workspace_state = state or WorkspaceState()
        clips = self.workspace_state.edit_sequence.clips
        signature = tuple(clip.clip_id for clip in clips)
        current_total = sum(clip.source_frame_count for clip in clips)
        if signature != self._fit_signature:
            self._fit_signature = signature
            self._fit_reference_frames = max(1, current_total)
        else:
            self._fit_reference_frames = max(self._fit_reference_frames, current_total, 1)
        self.selected_clip_id = self.workspace_state.selected_clip_id
        self.thumbnails = dict(thumbnails or {})
        self._scaled_thumbnail_cache.clear()
        selected = self.workspace_state.selected_clip
        if selected is not None:
            self.frame_count = selected.source_frame_count
            self.fps = selected.source_fps or self.fps or 30.0
            self.in_point = selected.source_range.source_in + 1
            self.out_point = selected.source_range.source_out
            self.current_frame = max(self.in_point, min(self.current_frame, self.out_point))
        self._rebuild_geometry()
        self.update()

    def set_video_info(self, frame_count: int, fps: float, duration: float, nb_frames: int = 0):
        self.frame_count = max(1, int(nb_frames or frame_count or 1))
        self.fps = max(0.001, float(fps or 30.0))
        self.duration = max(0.0, float(duration or 0.0))
        if self.selected_clip_id is None:
            self.in_point = 1
            self.out_point = self.frame_count
        self.current_frame = max(1, min(self.current_frame, self.frame_count))
        self.update()

    def set_current_frame(self, frame: int, emit_signal: bool = True):
        frame = max(1, min(int(frame), max(1, self.frame_count)))
        changed = frame != self.current_frame
        self.current_frame = frame
        self.update()
        if changed and emit_signal:
            self.frame_changed.emit(frame)

    def set_in_point(self, frame: int):
        frame = max(1, min(int(frame), self.out_point))
        self.in_point = frame
        self.update()
        self.in_point_changed.emit(frame)

    def set_out_point(self, frame: int):
        frame = max(self.in_point, min(int(frame), max(1, self.frame_count)))
        self.out_point = frame
        self.update()
        self.out_point_changed.emit(frame)

    def commit_in_point(self, frame: int):
        clip = self.workspace_state.selected_clip
        if clip is None:
            return
        source_in = max(
            0,
            min(int(frame) - 1, clip.source_range.source_out - 1),
        )
        if source_in != clip.source_range.source_in:
            self.clip_range_committed.emit(
                clip.clip_id,
                source_in,
                clip.source_range.source_out,
            )

    def commit_out_point(self, frame: int):
        clip = self.workspace_state.selected_clip
        if clip is None:
            return
        source_out = max(
            clip.source_range.source_in + 1,
            min(int(frame), clip.source_frame_count),
        )
        if source_out != clip.source_range.source_out:
            self.clip_range_committed.emit(
                clip.clip_id,
                clip.source_range.source_in,
                source_out,
            )

    def toggle_in_out_markers(self, show: bool):
        self.update()

    def _clips(self):
        return self.workspace_state.edit_sequence.clips

    def _range_for(self, clip):
        if clip.clip_id == self._drag_clip_id and self._preview_range is not None:
            return self._preview_range
        return clip.source_range

    def _rebuild_geometry(self):
        lengths = [
            (
                clip.clip_id,
                clip.source_frame_count,
                self._range_for(clip).source_in,
                self._range_for(clip).source_out,
            )
            for clip in self._clips()
        ]
        self._geometry = TimelineGeometry(
            self.width(),
            lengths,
            zoom=self.zoom,
            offset=self.scroll_offset,
            reference_total_frames=self._fit_reference_frames,
        )
        self.scroll_offset = min(self.scroll_offset, self._geometry.max_offset())

    def _clip_by_id(self, clip_id):
        return next((clip for clip in self._clips() if clip.clip_id == clip_id), None)

    def _move_target_index_at(self, x: float) -> int:
        remaining = [
            clip for clip in self._clips() if clip.clip_id != self._drag_clip_id
        ]
        for index, clip in enumerate(remaining):
            geometry = self._geometry.clip(clip.clip_id)
            if geometry is None:
                continue
            midpoint = (geometry.active_left + geometry.active_right) / 2.0
            if float(x) < midpoint:
                return index
        return len(remaining)

    def _move_indicator_x(self) -> float | None:
        if self._drag_mode != "move" or self._move_target_index is None:
            return None
        remaining = [
            clip for clip in self._clips() if clip.clip_id != self._drag_clip_id
        ]
        if not remaining:
            geometry = self._geometry.clip(self._drag_clip_id or "")
            return geometry.active_left if geometry else None
        target_index = max(0, min(self._move_target_index, len(remaining)))
        if target_index == len(remaining):
            geometry = self._geometry.clip(remaining[-1].clip_id)
            return geometry.active_right + 2 if geometry else None
        geometry = self._geometry.clip(remaining[target_index].clip_id)
        return geometry.active_left - 2 if geometry else None

    def _activate_clip(self, clip, emit_signal: bool = True):
        changed = clip.clip_id != self.selected_clip_id
        self.selected_clip_id = clip.clip_id
        self.frame_count = clip.source_frame_count
        self.fps = clip.source_fps or self.fps or 30.0
        self.in_point = clip.source_range.source_in + 1
        self.out_point = clip.source_range.source_out
        self.current_frame = max(
            self.in_point,
            min(self.current_frame, self.out_point),
        )
        if changed and emit_signal:
            self.clip_selected.emit(clip.clip_id)

    def _timecode(self, frame: int, fps: float | None = None) -> str:
        fps = max(1.0, float(fps or self.fps or 30.0))
        total_seconds = max(0.0, frame / fps)
        hours = int(total_seconds // 3600)
        minutes = int(total_seconds % 3600 // 60)
        seconds = int(total_seconds % 60)
        frames = int(round((total_seconds - int(total_seconds)) * fps))
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"

    def _seek_at_x(self, x: float):
        position = self._geometry.position_at(x)
        if position is None:
            return
        geometry, local_frame = position
        clip = self._clip_by_id(geometry.clip_id)
        if clip is None:
            return
        self._activate_clip(clip)
        self.set_current_frame(clip.source_range.source_in + local_frame + 1)

    def _thumbnail_tile(self, clip_id, thumbnail):
        cache_key = (clip_id, self.TRACK_HEIGHT, thumbnail.cacheKey())
        cached = self._scaled_thumbnail_cache.get(cache_key)
        if cached is None:
            cached = thumbnail.scaledToHeight(
                self.TRACK_HEIGHT,
                Qt.SmoothTransformation,
            )
            self._scaled_thumbnail_cache[cache_key] = cached
            if len(self._scaled_thumbnail_cache) > 128:
                oldest_key = next(iter(self._scaled_thumbnail_cache))
                self._scaled_thumbnail_cache.pop(oldest_key, None)
        return cached

    def paintEvent(self, event):
        self._rebuild_geometry()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#11151a"))

        if not self._clips():
            painter.setPen(QColor("#d7dde5"))
            painter.drawText(self.rect(), Qt.AlignCenter, "미디어를 추가하면 컷 타임라인이 표시됩니다")
            return

        painter.setFont(QFont("Segoe UI", 8))
        painter.setPen(QColor("#75808d"))
        ruler_y = self.RULER_HEIGHT - 6
        painter.drawLine(12, ruler_y, self.width() - 12, ruler_y)
        tick_count = 8
        for index in range(tick_count + 1):
            x = 12 + (self.width() - 24) * index / tick_count
            position = self._geometry.position_at(x)
            sequence_frame = (
                position[0].start_frame + position[1]
                if position is not None
                else 0
            )
            painter.drawLine(int(x), ruler_y - 4, int(x), ruler_y + 2)
            painter.drawText(QRectF(x - 30, 1, 60, 14), Qt.AlignCenter, self._timecode(sequence_frame))

        for index, geometry in enumerate(self._geometry.clips):
            clip = self._clip_by_id(geometry.clip_id)
            if clip is None or geometry.right < 0 or geometry.x > self.width():
                continue
            selected = clip.clip_id == self.selected_clip_id
            envelope_rect = QRectF(
                geometry.x,
                self.TRACK_TOP,
                geometry.width,
                self.TRACK_HEIGHT,
            )
            rect = QRectF(
                geometry.active_left,
                self.TRACK_TOP,
                geometry.active_width,
                self.TRACK_HEIGHT,
            )
            envelope_path = QPainterPath()
            envelope_path.addRoundedRect(envelope_rect, 5, 5)
            painter.fillPath(envelope_path, QColor("#171d24"))
            painter.setPen(QPen(QColor("#303945"), 1))
            painter.drawPath(envelope_path)
            path = QPainterPath()
            path.addRoundedRect(rect, 5, 5)
            painter.fillPath(path, QColor("#29456f" if selected else "#252d36"))

            thumbnail = self.thumbnails.get(clip.clip_id)
            if thumbnail is not None and not thumbnail.isNull():
                thumbnail = self._thumbnail_tile(clip.clip_id, thumbnail)
                painter.save()
                painter.setClipPath(path)
                tile_width = max(54, int(self.TRACK_HEIGHT * thumbnail.width() / max(1, thumbnail.height())))
                first_tile = max(
                    0,
                    math.floor((max(0.0, rect.left()) - rect.left()) / tile_width),
                )
                x = int(rect.left() + first_tile * tile_width)
                visible_right = min(float(self.width()), rect.right())
                while x < visible_right:
                    target = QRectF(x, rect.y(), tile_width, rect.height())
                    painter.setOpacity(0.34 if selected else 0.18)
                    painter.drawPixmap(target, thumbnail, QRectF(thumbnail.rect()))
                    x += tile_width
                painter.restore()

            painter.setOpacity(1.0)
            painter.setPen(QPen(QColor("#6fa0ff" if selected else "#3b4652"), 2 if selected else 1))
            painter.drawPath(path)
            basename = os.path.basename(clip.source_path)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(QFont("Segoe UI", 9, QFont.DemiBold if selected else QFont.Normal))
            painter.drawText(
                rect.adjusted(10, 7, -10, -26),
                Qt.AlignLeft | Qt.AlignTop,
                basename,
            )
            source_range = self._range_for(clip)
            painter.setFont(QFont("Consolas", 8))
            painter.setPen(QColor("#d7dde5"))
            painter.drawText(
                rect.adjusted(10, 30, -10, -7),
                Qt.AlignLeft | Qt.AlignBottom,
                f"{source_range.source_in + 1}–{source_range.source_out}f",
            )

            if selected:
                painter.fillRect(
                    QRectF(rect.left(), rect.top(), self.HANDLE_WIDTH, rect.height()),
                    QColor("#6fa0ff"),
                )
                painter.fillRect(
                    QRectF(
                        rect.right() - self.HANDLE_WIDTH,
                        rect.top(),
                        self.HANDLE_WIDTH,
                        rect.height(),
                    ),
                    QColor("#6fa0ff"),
                )
                painter.setPen(QPen(QColor("#ffffff"), 1, Qt.DashLine))
                painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 3, 3)

            if clip.clip_id == self._drag_clip_id and self._preview_range is not None:
                preview_frames = self._preview_range.frame_count
                preview_seconds = preview_frames / max(0.001, clip.source_fps or self.fps)
                label = (
                    f"{self._preview_range.source_in + 1}–"
                    f"{self._preview_range.source_out}f  ·  {preview_seconds:.2f}초"
                )
                label_rect = QRectF(
                    max(8.0, min(rect.left(), self.width() - 230.0)),
                    self.height() - 20.0,
                    220.0,
                    17.0,
                )
                painter.fillRect(label_rect, QColor("#05070a"))
                painter.setPen(QColor("#ffffff"))
                painter.setFont(QFont("Consolas", 8, QFont.DemiBold))
                painter.drawText(label_rect, Qt.AlignCenter, label)

        move_indicator_x = self._move_indicator_x()
        if move_indicator_x is not None:
            painter.setPen(QPen(QColor("#70a7ff"), 3))
            painter.drawLine(
                int(move_indicator_x),
                self.TRACK_TOP - 4,
                int(move_indicator_x),
                self.TRACK_TOP + self.TRACK_HEIGHT + 4,
            )

        selected_clip = self.workspace_state.selected_clip
        selected_geometry = self._geometry.clip(self.selected_clip_id or "")
        if selected_clip is not None and selected_geometry is not None:
            local_frame = max(
                0,
                min(
                    selected_clip.source_range.frame_count,
                    self.current_frame - selected_clip.source_range.source_in - 1,
                ),
            )
            playhead_x = self._geometry.x_for_clip_frame(selected_clip.clip_id, local_frame)
            painter.setPen(QPen(QColor("#f4f7fb"), 1))
            painter.drawLine(int(playhead_x), self.RULER_HEIGHT, int(playhead_x), self.height() - 8)
            painter.setBrush(QColor("#f4f7fb"))
            painter.setPen(Qt.NoPen)
            painter.drawPolygon(
                [
                    QPoint(int(playhead_x) - 5, self.RULER_HEIGHT),
                    QPoint(int(playhead_x) + 5, self.RULER_HEIGHT),
                    QPoint(int(playhead_x), self.RULER_HEIGHT + 7),
                ]
            )
        if self.hasFocus():
            painter.setPen(QPen(QColor("#9bbcff"), 1, Qt.DashLine))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -2, -2), 5, 5)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton:
            return
        self.setFocus()
        self._rebuild_geometry()
        if event.position().y() < self.TRACK_TOP:
            self._seek_at_x(event.position().x())
            return
        geometry = self._geometry.hit_test(event.position().x())
        if geometry is None:
            self._seek_at_x(event.position().x())
            return
        clip = self._clip_by_id(geometry.clip_id)
        if clip is None:
            return
        self._activate_clip(clip)
        self._drag_clip_id = clip.clip_id
        self._drag_origin = event.position().toPoint()
        self._drag_original_range = clip.source_range
        self._preview_range = clip.source_range
        distance_left = abs(event.position().x() - geometry.active_left)
        distance_right = abs(event.position().x() - geometry.active_right)
        if distance_left <= self.HANDLE_WIDTH + 3:
            self._drag_mode = "trim_left"
        elif distance_right <= self.HANDLE_WIDTH + 3:
            self._drag_mode = "trim_right"
        else:
            self._drag_mode = "pending_move"
            source_frame = self._geometry.active_source_frame_at(
                geometry,
                event.position().x(),
            )
            self.set_current_frame(source_frame + 1)
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not (event.buttons() & Qt.LeftButton) or not self._drag_mode:
            geometry = self._geometry.hit_test(event.position().x())
            if geometry is None:
                self.unsetCursor()
                return
            near_edge = (
                geometry.clip_id == self.selected_clip_id
                and (
                    abs(event.position().x() - geometry.active_left) <= self.HANDLE_WIDTH + 3
                    or abs(event.position().x() - geometry.active_right) <= self.HANDLE_WIDTH + 3
                )
            )
            self.setCursor(Qt.SizeHorCursor if near_edge else Qt.PointingHandCursor)
            return
        clip = self._clip_by_id(self._drag_clip_id)
        if clip is None or self._drag_original_range is None:
            return
        delta_pixels = event.position().x() - self._drag_origin.x()
        if self._drag_mode == "pending_move" and abs(delta_pixels) > 10:
            self._drag_mode = "move"
            self._move_target_index = self._move_target_index_at(event.position().x())
        elif self._drag_mode == "move":
            self._move_target_index = self._move_target_index_at(event.position().x())
        if self._drag_mode == "trim_left":
            delta = self._geometry.frame_delta_for_pixels(
                delta_pixels,
                clip.clip_id,
            )
            source_in = max(0, min(self._drag_original_range.source_out - 1, self._drag_original_range.source_in + delta))
            self._preview_range = ClipRange(source_in, self._drag_original_range.source_out)
        elif self._drag_mode == "trim_right":
            delta = self._geometry.frame_delta_for_pixels(
                delta_pixels,
                clip.clip_id,
            )
            source_out = max(
                self._drag_original_range.source_in + 1,
                min(clip.source_frame_count, self._drag_original_range.source_out + delta),
            )
            self._preview_range = ClipRange(self._drag_original_range.source_in, source_out)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() != Qt.LeftButton or not self._drag_mode:
            return
        clip_id = self._drag_clip_id
        mode = self._drag_mode
        if mode in {"trim_left", "trim_right"} and self._preview_range != self._drag_original_range:
            self.clip_range_committed.emit(
                clip_id,
                self._preview_range.source_in,
                self._preview_range.source_out,
            )
        elif mode == "move":
            target_index = (
                self._move_target_index
                if self._move_target_index is not None
                else self._move_target_index_at(event.position().x())
            )
            self.clip_move_committed.emit(clip_id, target_index)
        self._drag_mode = None
        self._drag_clip_id = None
        self._drag_original_range = None
        self._preview_range = None
        self._move_target_index = None
        self.unsetCursor()
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.playback_requested.emit()

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            self.zoom = max(1.0, min(12.0, self.zoom * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15)))
        else:
            self.scroll_offset = max(0.0, self.scroll_offset - event.angleDelta().y() * 0.8)
        self._rebuild_geometry()
        self.scroll_offset = min(self.scroll_offset, self._geometry.max_offset())
        self.update()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_K and event.modifiers() & Qt.ControlModifier:
            self.split_requested.emit()
            event.accept()
            return
        if event.key() in {Qt.Key_Left, Qt.Key_Right}:
            delta = -1 if event.key() == Qt.Key_Left else 1
            self.set_current_frame(
                max(self.in_point, min(self.out_point, self.current_frame + delta))
            )
            event.accept()
            return
        if event.key() == Qt.Key_Home:
            first = self._clips()[0] if self._clips() else None
            if first is not None:
                self._activate_clip(first)
                self.set_current_frame(first.source_range.source_in + 1)
            event.accept()
            return
        if event.key() == Qt.Key_End:
            last = self._clips()[-1] if self._clips() else None
            if last is not None:
                self._activate_clip(last)
                self.set_current_frame(last.source_range.source_out)
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_geometry()
