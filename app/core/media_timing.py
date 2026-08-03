from bisect import bisect_right
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FrameTimeMap:
    """Bidirectional mapping between one-based video frames and media time."""

    timestamps_ms: tuple[int, ...]

    def __post_init__(self):
        normalized = []
        previous = -1
        for value in self.timestamps_ms:
            timestamp = max(0, int(round(float(value))))
            if timestamp < previous:
                timestamp = previous
            normalized.append(timestamp)
            previous = timestamp
        object.__setattr__(self, "timestamps_ms", tuple(normalized))

    @classmethod
    def from_timestamps(
        cls,
        timestamps_ms: Iterable[float | int],
        *,
        frame_count: int = 0,
        fps: float = 0.0,
    ) -> "FrameTimeMap":
        timestamps = tuple(timestamps_ms or ())
        if timestamps:
            return cls(timestamps)
        return cls.from_fps(frame_count, fps)

    @classmethod
    def from_fps(cls, frame_count: int, fps: float) -> "FrameTimeMap":
        frame_count = max(0, int(frame_count or 0))
        fps = float(fps or 0.0)
        if frame_count <= 0 or fps <= 0:
            return cls(())
        return cls(tuple((index / fps) * 1000.0 for index in range(frame_count)))

    @property
    def frame_count(self) -> int:
        return len(self.timestamps_ms)

    def timestamp_for_frame(self, frame: int) -> int:
        if not self.timestamps_ms:
            return 0
        index = max(0, min(int(frame) - 1, len(self.timestamps_ms) - 1))
        return self.timestamps_ms[index]

    def frame_for_timestamp(self, timestamp_ms: int) -> int:
        if not self.timestamps_ms:
            return 1
        index = bisect_right(self.timestamps_ms, max(0, int(timestamp_ms))) - 1
        return max(1, min(index + 1, len(self.timestamps_ms)))
