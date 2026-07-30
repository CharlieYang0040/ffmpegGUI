from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ClipGeometry:
    clip_id: str
    start_frame: int
    frame_count: int
    source_in: int
    source_out: int
    x: float
    width: float

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.active_frame_count

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def active_frame_count(self) -> int:
        return self.source_out - self.source_in

    @property
    def pixels_per_source_frame(self) -> float:
        return self.width / max(1, self.frame_count)

    @property
    def active_left(self) -> float:
        return self.x + self.source_in * self.pixels_per_source_frame

    @property
    def active_right(self) -> float:
        return self.x + self.source_out * self.pixels_per_source_frame

    @property
    def active_width(self) -> float:
        return max(1.0, self.active_right - self.active_left)


class TimelineGeometry:
    """Shared frame/pixel mapping for drawing and hit testing."""

    def __init__(
        self,
        width: int,
        clip_lengths: Iterable[tuple],
        *,
        zoom: float = 1.0,
        offset: float = 0.0,
        padding: int = 12,
        minimum_clip_width: int = 36,
        reference_total_frames: int | None = None,
    ):
        self.width = max(1, int(width))
        self.padding = max(0, int(padding))
        self.zoom = max(1.0, min(float(zoom), 12.0))
        self.offset = max(0.0, float(offset))
        lengths = []
        for value in clip_lengths:
            if len(value) == 2:
                clip_id, source_frame_count = value
                source_in, source_out = 0, source_frame_count
            elif len(value) == 4:
                clip_id, source_frame_count, source_in, source_out = value
            else:
                raise ValueError("클립 길이는 (id, frames) 또는 (id, frames, in, out)이어야 합니다.")
            source_frame_count = max(1, int(source_frame_count))
            source_in = max(0, min(int(source_in), source_frame_count - 1))
            source_out = max(source_in + 1, min(int(source_out), source_frame_count))
            lengths.append(
                (str(clip_id), source_frame_count, source_in, source_out)
            )
        total_frames = sum(source_out - source_in for _, _, source_in, source_out in lengths)
        total_source_frames = sum(source_frame_count for _, source_frame_count, _, _ in lengths)
        reference_total_frames = max(
            total_source_frames,
            int(reference_total_frames or total_source_frames or 1),
        )
        available = max(1, self.width - self.padding * 2)
        self.pixels_per_frame = (available / reference_total_frames) * self.zoom

        geometries = []
        frame_cursor = 0
        x_cursor = float(self.padding) - self.offset
        for clip_id, frame_count, source_in, source_out in lengths:
            clip_width = max(float(minimum_clip_width), frame_count * self.pixels_per_frame)
            geometries.append(
                ClipGeometry(
                    clip_id=clip_id,
                    start_frame=frame_cursor,
                    frame_count=frame_count,
                    source_in=source_in,
                    source_out=source_out,
                    x=x_cursor,
                    width=clip_width,
                )
            )
            frame_cursor += source_out - source_in
            x_cursor += clip_width + 2
        self.clips = tuple(geometries)
        self.total_frames = total_frames
        self.reference_total_frames = reference_total_frames
        self.content_width = max(float(available), x_cursor + self.offset)

    def clip(self, clip_id: str) -> ClipGeometry | None:
        return next((clip for clip in self.clips if clip.clip_id == clip_id), None)

    def hit_test(self, x: float) -> ClipGeometry | None:
        return next((clip for clip in self.clips if clip.x <= x <= clip.right), None)

    def position_at(self, x: float) -> tuple[ClipGeometry, int] | None:
        """Map any viewport x position to the nearest clip and local frame."""
        if not self.clips:
            return None
        x = float(x)
        clip = self.hit_test(x)
        if clip is None:
            clip = min(
                self.clips,
                key=lambda candidate: min(
                    abs(x - candidate.x),
                    abs(x - candidate.right),
                ),
            )
        return clip, self.clip_frame_at(clip, x)

    def clip_frame_at(self, clip: ClipGeometry, x: float) -> int:
        source_frame = self.source_frame_at(clip, x)
        return max(
            0,
            min(clip.active_frame_count - 1, source_frame - clip.source_in),
        )

    def source_frame_at(self, clip: ClipGeometry, x: float) -> int:
        ratio = (float(x) - clip.x) / max(1.0, clip.width)
        return max(0, min(clip.frame_count - 1, int(ratio * clip.frame_count)))

    def active_source_frame_at(self, clip: ClipGeometry, x: float) -> int:
        return max(
            clip.source_in,
            min(clip.source_out - 1, self.source_frame_at(clip, x)),
        )

    def x_for_clip_frame(self, clip_id: str, local_frame: int) -> float:
        clip = self.clip(clip_id)
        if clip is None:
            return float(self.padding)
        local_frame = max(0, min(int(local_frame), clip.active_frame_count))
        return clip.active_left + local_frame * clip.pixels_per_source_frame

    def frame_delta_for_pixels(self, pixels: float, clip_id: str | None = None) -> int:
        clip = self.clip(clip_id) if clip_id else None
        scale = clip.pixels_per_source_frame if clip else self.pixels_per_frame
        return int(round(float(pixels) / max(0.001, scale)))

    def max_offset(self) -> float:
        return max(0.0, self.content_width - self.width + self.padding)
