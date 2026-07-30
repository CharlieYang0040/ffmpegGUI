"""Helpers for building and validating encoding jobs."""

import os
from typing import Iterable, Tuple

from app.core.models import (
    ClipRange,
    EditClip,
    EditSequence,
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


def timeline_range_to_clip_range(timeline_range: TimelineRange) -> ClipRange:
    """Convert a 1-based inclusive UI range into the canonical clip range."""
    if timeline_range is None:
        raise ValueError("타임라인 구간 정보가 없습니다.")
    in_frame = int(timeline_range.in_frame)
    out_frame = int(timeline_range.out_frame)
    frame_count = int(timeline_range.frame_count)
    if frame_count <= 0:
        raise ValueError("전체 프레임 수는 1 이상이어야 합니다.")
    if not 1 <= in_frame <= out_frame <= frame_count:
        raise ValueError("타임라인 구간이 원본 프레임 범위를 벗어났습니다.")
    return ClipRange(source_in=in_frame - 1, source_out=out_frame)


def clip_range_to_trim(clip_range: ClipRange, source_frame_count: int) -> FrameTrim:
    """Adapt a canonical clip range to the legacy head/tail trim contract."""
    source_frame_count = int(source_frame_count)
    if source_frame_count <= 0:
        raise ValueError("전체 프레임 수는 1 이상이어야 합니다.")
    if clip_range.source_out > source_frame_count:
        raise ValueError("클립 구간이 원본 프레임 범위를 벗어났습니다.")
    return FrameTrim(
        head_frames=clip_range.source_in,
        tail_frames=source_frame_count - clip_range.source_out,
    )


def trim_to_clip_range(trim: FrameTrim, source_frame_count: int) -> ClipRange:
    """Adapt a legacy head/tail trim into the canonical clip range."""
    source_frame_count = int(source_frame_count)
    if source_frame_count <= 0:
        raise ValueError("전체 프레임 수는 1 이상이어야 합니다.")
    trim = normalize_trim(trim)
    source_out = source_frame_count - trim.tail_frames
    if trim.head_frames >= source_out:
        raise ValueError("트림 결과에 사용할 프레임이 남아 있지 않습니다.")
    return ClipRange(trim.head_frames, source_out)


def edit_sequence_to_media_items(edit_sequence: EditSequence) -> list[MediaItem]:
    """Build legacy-compatible MediaItems from ordered edit clips."""
    return [
        MediaItem(
            source_path=clip.source_path,
            media_type=clip.media_type,
            trim=FrameTrim(),
            fps=clip.source_fps,
            frame_count=clip.source_frame_count,
            source_range=clip.source_range,
        )
        for clip in edit_sequence.clips
    ]


def media_items_to_legacy_tuples(media_items: Iterable[MediaItem]) -> list[Tuple[str, int, int]]:
    """Convert MediaItem objects to the existing BatchProcessor tuple input."""
    legacy_items = []
    for item in media_items:
        if item.source_range is not None:
            trim = clip_range_to_trim(item.source_range, item.frame_count)
        else:
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
        if item.source_range is not None:
            if item.frame_count is None or int(item.frame_count) <= 0:
                raise ValueError(f"소스 {index}의 전체 프레임 수가 필요합니다.")
            if item.source_range.source_out > int(item.frame_count):
                raise ValueError(f"소스 {index}의 클립 구간이 원본 범위를 벗어났습니다.")
            continue
        if trim is None:
            continue
        if trim.head_frames < 0 or trim.tail_frames < 0:
            raise ValueError(f"소스 {index}의 트림 값은 음수일 수 없습니다.")
        if int(trim.head_frames) != trim.head_frames or int(trim.tail_frames) != trim.tail_frames:
            raise ValueError(f"소스 {index}의 트림 값은 정수 프레임이어야 합니다.")
