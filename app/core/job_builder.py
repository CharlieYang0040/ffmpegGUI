"""Helpers for building and validating encoding jobs."""

import os
from typing import Iterable, Tuple

from app.core.models import (
    EncodingJob,
    FrameTrim,
    MediaItem,
    MediaType,
    TimelineRange,
)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv"}


def detect_media_type(path: str) -> MediaType:
    """Detect the media type used by the encoding pipeline."""
    if not path:
        return MediaType.UNKNOWN

    if "%" in path or os.path.isdir(path):
        return MediaType.IMAGE_SEQUENCE

    _, ext = os.path.splitext(path)
    ext = ext.lower()
    if ext == ".webp":
        return MediaType.WEBP
    if ext in VIDEO_EXTENSIONS:
        return MediaType.VIDEO
    if ext in IMAGE_EXTENSIONS:
        return MediaType.IMAGE
    return MediaType.UNKNOWN


def normalize_trim(trim: FrameTrim) -> FrameTrim:
    """Return a non-negative, integer frame trim."""
    if trim is None:
        return FrameTrim()

    head_frames = int(trim.head_frames or 0)
    tail_frames = int(trim.tail_frames or 0)
    return FrameTrim(
        head_frames=max(0, head_frames),
        tail_frames=max(0, tail_frames),
    )


def timeline_range_to_trim(timeline_range: TimelineRange) -> FrameTrim:
    """Convert an inclusive timeline in/out range into head/tail trim."""
    if timeline_range is None:
        return FrameTrim()

    in_frame = int(timeline_range.in_frame or 1)
    out_frame = int(timeline_range.out_frame or 0)
    frame_count = int(timeline_range.frame_count or 0)
    return FrameTrim(
        head_frames=max(0, in_frame - 1),
        tail_frames=max(0, frame_count - out_frame),
    )


def media_items_to_legacy_tuples(media_items: Iterable[MediaItem]) -> list[Tuple[str, int, int]]:
    """Convert MediaItem objects to the existing BatchProcessor tuple input."""
    legacy_items = []
    for item in media_items:
        trim = normalize_trim(item.trim)
        legacy_items.append((item.source_path, trim.head_frames, trim.tail_frames))
    return legacy_items


def validate_encoding_job(job: EncodingJob) -> None:
    """Validate an EncodingJob without checking filesystem existence."""
    if job is None:
        raise ValueError("인코딩 작업 정보가 없습니다.")
    if not job.output_file:
        raise ValueError("출력 경로를 지정해야 합니다.")
    if not job.media_items:
        raise ValueError("인코딩할 소스를 하나 이상 추가해야 합니다.")

    for index, item in enumerate(job.media_items, start=1):
        if not item.source_path:
            raise ValueError(f"소스 {index}의 경로가 비어 있습니다.")

        trim = item.trim
        if trim is None:
            continue
        if trim.head_frames < 0 or trim.tail_frames < 0:
            raise ValueError(f"소스 {index}의 트림 값은 음수일 수 없습니다.")
        if int(trim.head_frames) != trim.head_frames or int(trim.tail_frames) != trim.tail_frames:
            raise ValueError(f"소스 {index}의 트림 값은 정수 프레임이어야 합니다.")

    global_trim = job.options.global_trim if job.options else FrameTrim()
    if global_trim and (global_trim.head_frames < 0 or global_trim.tail_frames < 0):
        raise ValueError("전체 트림 값은 음수일 수 없습니다.")
