"""Adapter that collects GUI state into an EncodingJob."""

from typing import Optional, Tuple

from app.core.job_builder import (
    detect_media_type,
    edit_sequence_to_media_items,
    normalize_trim,
    timeline_range_to_trim,
)
from app.core.models import (
    EncodingJob,
    EncodingOptions,
    FrameTrim,
    MediaItem,
    TimelineRange,
)


def _get_debug_mode():
    try:
        from app.utils.utils import get_debug_mode

        return get_debug_mode()
    except ModuleNotFoundError:
        return False


def _get_trim_from_item_widget(item_widget) -> FrameTrim:
    if item_widget and hasattr(item_widget, "get_trim_values"):
        trim_start, trim_end = item_widget.get_trim_values()
        return normalize_trim(FrameTrim(trim_start, trim_end))
    return FrameTrim()


def _get_timeline_in_out(timeline) -> Optional[Tuple[int, int]]:
    if not timeline:
        return None
    if hasattr(timeline, "get_in_out_points"):
        try:
            in_point, out_point = timeline.get_in_out_points()
            return int(in_point), int(out_point)
        except (TypeError, ValueError, AttributeError):
            return None
    if hasattr(timeline, "get_in_point") and hasattr(timeline, "get_out_point"):
        try:
            return int(timeline.get_in_point()), int(timeline.get_out_point())
        except (TypeError, ValueError, AttributeError):
            return None
    timeline_widget = getattr(timeline, "timeline_widget", None)
    if timeline_widget:
        try:
            return int(timeline_widget.in_point), int(timeline_widget.out_point)
        except (TypeError, ValueError, AttributeError):
            return None
    return None


def _get_current_timeline_trim(window, file_path: str) -> Optional[Tuple[FrameTrim, Optional[float], Optional[int]]]:
    preview_area = getattr(window, "preview_area", None)
    timeline = getattr(preview_area, "timeline", None)
    if not preview_area or not timeline:
        return None

    if getattr(preview_area, "current_media_path", None) != file_path:
        return None
    if getattr(preview_area, "current_media_fps", 0) <= 0:
        return None

    in_out = _get_timeline_in_out(timeline)
    if not in_out:
        return None

    in_point, out_point = in_out
    frame_count = getattr(preview_area, "current_media_frame_count", 0) or 0
    if frame_count <= 0:
        return None

    timeline_range = TimelineRange(
        in_frame=in_point,
        out_frame=out_point,
        frame_count=frame_count,
    )
    return (
        timeline_range_to_trim(timeline_range),
        getattr(preview_area, "current_media_fps", None),
        frame_count,
    )


def _collect_encoding_options(window) -> EncodingOptions:
    ffmpeg_options = dict(getattr(window, "encoding_options", {}) or {})
    control_area = getattr(window, "control_area", None)

    if control_area and getattr(control_area, "use_custom_framerate", False):
        ffmpeg_options["r"] = str(getattr(control_area, "framerate", 30))
    else:
        ffmpeg_options.pop("r", None)

    if control_area and getattr(control_area, "use_custom_resolution", False):
        width = getattr(control_area, "video_width", 0)
        height = getattr(control_area, "video_height", 0)
        if width and height:
            ffmpeg_options["s"] = f"{width}x{height}"
    else:
        ffmpeg_options.pop("s", None)

    return EncodingOptions(
        ffmpeg_options=ffmpeg_options,
        debug_mode=_get_debug_mode(),
        use_frame_based_trim=True,
    )


def collect_encoding_job(window) -> EncodingJob:
    """Collect current GUI state into an EncodingJob."""
    output_file = window.output_edit.text() if hasattr(window, "output_edit") else ""
    workspace_state = getattr(window, "workspace_state", None)
    if workspace_state and workspace_state.edit_sequence.clips:
        return EncodingJob(
            media_items=edit_sequence_to_media_items(workspace_state.edit_sequence),
            output_file=output_file,
            options=_collect_encoding_options(window),
        )

    media_items = []
    list_widget = getattr(window, "list_widget", None)
    current_row = list_widget.currentRow() if list_widget else -1

    if list_widget:
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            item_widget = list_widget.itemWidget(item)
            file_path = getattr(item_widget, "file_path", "")
            trim = _get_trim_from_item_widget(item_widget)
            fps = None
            frame_count = None

            if index == current_row:
                timeline_trim = _get_current_timeline_trim(window, file_path)
                if timeline_trim:
                    trim, fps, frame_count = timeline_trim

            media_items.append(
                MediaItem(
                    source_path=file_path,
                    media_type=detect_media_type(file_path),
                    trim=trim,
                    fps=fps,
                    frame_count=frame_count,
                )
            )

    return EncodingJob(
        media_items=media_items,
        output_file=output_file,
        options=_collect_encoding_options(window),
    )
