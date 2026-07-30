"""Transitional adapter between legacy Qt widgets and WorkspaceState.

The modern UI will own WorkspaceState directly. Until each panel is replaced,
this module takes one consistent snapshot of every ready list item so job
building no longer needs a selected-item-only timeline exception.
"""

from typing import Optional

from app.core.job_builder import (
    clip_range_to_trim,
    detect_media_type,
    trim_to_clip_range,
)
from app.core.models import EditClip, EditSequence, FrameTrim, WorkspaceState


def collect_workspace_state(window) -> Optional[WorkspaceState]:
    """Return a complete workspace snapshot, or None while metadata is pending."""
    list_widget = getattr(window, "list_widget", None)
    if not list_widget or list_widget.count() == 0:
        return WorkspaceState(
            output_file=_output_file(window),
            preset_id=getattr(window, "current_preset_id", "h264_review"),
        )

    clips = []
    selected_clip_id = None
    current_row = list_widget.currentRow()
    for index in range(list_widget.count()):
        item = list_widget.item(index)
        item_widget = list_widget.itemWidget(item)
        if not item_widget:
            return None

        source_path = str(getattr(item_widget, "file_path", "") or "")
        source_frame_count = int(getattr(item_widget, "total_frames", 0) or 0)
        if not source_path or source_frame_count <= 0:
            return None

        source_range = (
            item_widget.get_clip_range()
            if hasattr(item_widget, "get_clip_range")
            else None
        )
        if source_range is None:
            head_frames, tail_frames = item_widget.get_trim_values()
            source_range = trim_to_clip_range(
                FrameTrim(head_frames, tail_frames),
                source_frame_count,
            )
        clip_id = str(getattr(item_widget, "clip_id", "") or f"legacy-{index}")
        clip = EditClip(
            clip_id=clip_id,
            source_path=source_path,
            source_range=source_range,
            source_frame_count=source_frame_count,
            media_type=detect_media_type(source_path),
            source_fps=float(getattr(item_widget, "fps", 0) or 0) or None,
        )
        clips.append(clip)
        if index == current_row:
            selected_clip_id = clip_id

    return WorkspaceState(
        edit_sequence=EditSequence(tuple(clips)),
        selected_clip_id=selected_clip_id,
        output_file=_output_file(window),
        preset_id=getattr(window, "current_preset_id", "h264_review"),
    )


def _output_file(window) -> str:
    output_edit = getattr(window, "output_edit", None)
    return output_edit.text() if output_edit and hasattr(output_edit, "text") else ""


def split_clip_item_state(
    state: dict,
    source_frame_count: int,
    split_boundary: int,
    left_clip_id: str,
    right_clip_id: str,
) -> tuple[dict, dict]:
    """Split one persisted list state at a zero-based half-open boundary."""
    source_range = trim_to_clip_range(
        FrameTrim(state.get("trim_start", 0), state.get("trim_end", 0)),
        source_frame_count,
    )
    left_range, right_range = source_range.split(split_boundary)
    left_trim = clip_range_to_trim(left_range, source_frame_count)
    right_trim = clip_range_to_trim(right_range, source_frame_count)

    left = dict(state)
    left.update(
        clip_id=left_clip_id,
        trim_start=left_trim.head_frames,
        trim_end=left_trim.tail_frames,
    )
    right = dict(state)
    right.update(
        clip_id=right_clip_id,
        trim_start=right_trim.head_frames,
        trim_end=right_trim.tail_frames,
    )
    return left, right
