from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ClipGeometry:
    clip_id: str
    start_frame: int
    frame_count: int
    x: float
    width: float

    @property
    def end_frame(self) -> int:
        return self.start_frame + self.frame_count

    @property
    def right(self) -> float:
        return self.x + self.width


class TimelineGeometry:
    """Shared frame/pixel mapping for drawing and hit testing."""

    def __init__(
        self,
        width: int,
        clip_lengths: Iterable[tuple[str, int]],
        *,
        zoom: float = 1.0,
        offset: float = 0.0,
        padding: int = 12,
        minimum_clip_width: int = 36,
    ):
        self.width = max(1, int(width))
        self.padding = max(0, int(padding))
        self.zoom = max(1.0, min(float(zoom), 12.0))
        self.offset = max(0.0, float(offset))
        lengths = [(str(clip_id), max(1, int(length))) for clip_id, length in clip_lengths]
        total_frames = sum(length for _, length in lengths)
        available = max(1, self.width - self.padding * 2)
        self.pixels_per_frame = (available / max(1, total_frames)) * self.zoom

        geometries = []
        frame_cursor = 0
        x_cursor = float(self.padding) - self.offset
        for clip_id, frame_count in lengths:
            clip_width = max(float(minimum_clip_width), frame_count * self.pixels_per_frame)
            geometries.append(
                ClipGeometry(
                    clip_id=clip_id,
                    start_frame=frame_cursor,
                    frame_count=frame_count,
                    x=x_cursor,
                    width=clip_width,
                )
            )
            frame_cursor += frame_count
            x_cursor += clip_width + 2
        self.clips = tuple(geometries)
        self.total_frames = total_frames
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
        ratio = (float(x) - clip.x) / max(1.0, clip.width)
        return max(0, min(clip.frame_count - 1, int(ratio * clip.frame_count)))

    def x_for_clip_frame(self, clip_id: str, local_frame: int) -> float:
        clip = self.clip(clip_id)
        if clip is None:
            return float(self.padding)
        ratio = max(0.0, min(1.0, float(local_frame) / max(1, clip.frame_count)))
        return clip.x + ratio * clip.width

    def frame_delta_for_pixels(self, pixels: float) -> int:
        return int(round(float(pixels) / max(0.001, self.pixels_per_frame)))

    def max_offset(self) -> float:
        return max(0.0, self.content_width - self.width + self.padding)
