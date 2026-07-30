"""Core data models for encoding jobs.

These models intentionally avoid PySide types so encoding preparation can be
tested without starting the GUI.
"""

from dataclasses import dataclass, field, replace
from enum import Enum
import subprocess
import threading
from typing import Dict, List, Optional, Tuple


class MediaType(str, Enum):
    """Supported media categories."""

    VIDEO = "video"
    IMAGE = "image"
    IMAGE_SEQUENCE = "image_sequence"
    WEBP = "webp"
    UNKNOWN = "unknown"


class PreflightSeverity(str, Enum):
    """Severity levels for issues found before encoding starts."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EncodingProgressStage(str, Enum):
    """High-level stages shown in the encoding progress UI."""

    IDLE = "idle"
    FFMPEG_SETUP = "ffmpeg_setup"
    PREPARING = "preparing"
    PROCESSING = "processing"
    MERGING = "merging"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class FrameTrim:
    """Trim amount in frames from the head and tail of a media item."""

    head_frames: int = 0
    tail_frames: int = 0

    def __post_init__(self):
        object.__setattr__(self, "head_frames", max(0, int(self.head_frames or 0)))
        object.__setattr__(self, "tail_frames", max(0, int(self.tail_frames or 0)))


@dataclass(frozen=True)
class TimelineRange:
    """Inclusive in/out range selected in the preview timeline."""

    in_frame: int
    out_frame: int
    frame_count: int


@dataclass(frozen=True)
class ClipRange:
    """Zero-based, half-open source frame range used by one edit clip."""

    source_in: int
    source_out: int

    def __post_init__(self):
        if int(self.source_in) != self.source_in or int(self.source_out) != self.source_out:
            raise ValueError("클립 구간은 정수 프레임이어야 합니다.")
        source_in = int(self.source_in)
        source_out = int(self.source_out)
        if source_in < 0:
            raise ValueError("클립 시작 프레임은 0보다 작을 수 없습니다.")
        if source_out <= source_in:
            raise ValueError("클립 종료 프레임은 시작 프레임보다 커야 합니다.")
        object.__setattr__(self, "source_in", source_in)
        object.__setattr__(self, "source_out", source_out)

    @property
    def frame_count(self) -> int:
        return self.source_out - self.source_in

    def split(self, frame: int) -> Tuple["ClipRange", "ClipRange"]:
        """Split at a zero-based boundary inside this range."""
        frame = int(frame)
        if not self.source_in < frame < self.source_out:
            raise ValueError("분할 위치는 클립 구간 내부여야 합니다.")
        return (
            ClipRange(self.source_in, frame),
            ClipRange(frame, self.source_out),
        )


@dataclass(frozen=True)
class EditClip:
    """One ordered use of a source file in a simple cut edit."""

    clip_id: str
    source_path: str
    source_range: ClipRange
    source_frame_count: int
    media_type: MediaType = MediaType.UNKNOWN
    source_fps: Optional[float] = None

    def __post_init__(self):
        clip_id = str(self.clip_id or "").strip()
        source_path = str(self.source_path or "").strip()
        if int(self.source_frame_count) != self.source_frame_count:
            raise ValueError("원본 프레임 수는 정수여야 합니다.")
        source_frame_count = int(self.source_frame_count)
        if not clip_id:
            raise ValueError("클립 ID가 비어 있습니다.")
        if not source_path:
            raise ValueError("클립 원본 경로가 비어 있습니다.")
        if source_frame_count <= 0:
            raise ValueError("원본 프레임 수는 1 이상이어야 합니다.")
        if self.source_range.source_out > source_frame_count:
            raise ValueError("클립 구간이 원본 프레임 범위를 벗어났습니다.")
        if self.source_fps is not None and float(self.source_fps) <= 0:
            raise ValueError("클립 FPS는 0보다 커야 합니다.")
        object.__setattr__(self, "clip_id", clip_id)
        object.__setattr__(self, "source_path", source_path)
        object.__setattr__(self, "source_frame_count", source_frame_count)
        if self.source_fps is not None:
            object.__setattr__(self, "source_fps", float(self.source_fps))

    def with_range(self, source_range: ClipRange) -> "EditClip":
        return EditClip(
            clip_id=self.clip_id,
            source_path=self.source_path,
            source_range=source_range,
            source_frame_count=self.source_frame_count,
            media_type=self.media_type,
            source_fps=self.source_fps,
        )

    def copy_as(self, clip_id: str, source_range: Optional[ClipRange] = None) -> "EditClip":
        return EditClip(
            clip_id=clip_id,
            source_path=self.source_path,
            source_range=source_range or self.source_range,
            source_frame_count=self.source_frame_count,
            media_type=self.media_type,
            source_fps=self.source_fps,
        )


@dataclass(frozen=True)
class EditSequence:
    """Immutable ordered clips for single-track cut editing."""

    clips: Tuple[EditClip, ...] = field(default_factory=tuple)

    def __post_init__(self):
        clips = tuple(self.clips or ())
        clip_ids = [clip.clip_id for clip in clips]
        if len(clip_ids) != len(set(clip_ids)):
            raise ValueError("클립 ID는 작업 안에서 중복될 수 없습니다.")
        object.__setattr__(self, "clips", clips)

    @property
    def frame_count(self) -> int:
        return sum(clip.source_range.frame_count for clip in self.clips)

    def _index_of(self, clip_id: str) -> int:
        for index, clip in enumerate(self.clips):
            if clip.clip_id == clip_id:
                return index
        raise ValueError(f"클립을 찾을 수 없습니다: {clip_id}")

    def replace_range(self, clip_id: str, source_range: ClipRange) -> "EditSequence":
        index = self._index_of(clip_id)
        clips = list(self.clips)
        clips[index] = clips[index].with_range(source_range)
        return EditSequence(tuple(clips))

    def split(
        self,
        clip_id: str,
        frame: int,
        left_clip_id: str,
        right_clip_id: str,
    ) -> "EditSequence":
        index = self._index_of(clip_id)
        clip = self.clips[index]
        left_range, right_range = clip.source_range.split(frame)
        replacement = (
            clip.copy_as(left_clip_id, left_range),
            clip.copy_as(right_clip_id, right_range),
        )
        return EditSequence(self.clips[:index] + replacement + self.clips[index + 1 :])

    def delete(self, clip_id: str) -> "EditSequence":
        index = self._index_of(clip_id)
        return EditSequence(self.clips[:index] + self.clips[index + 1 :])

    def duplicate(self, clip_id: str, new_clip_id: str) -> "EditSequence":
        index = self._index_of(clip_id)
        duplicate = self.clips[index].copy_as(new_clip_id)
        return EditSequence(self.clips[: index + 1] + (duplicate,) + self.clips[index + 1 :])

    def move(self, clip_id: str, new_index: int) -> "EditSequence":
        old_index = self._index_of(clip_id)
        if not 0 <= int(new_index) < len(self.clips):
            raise ValueError("이동할 위치가 클립 목록 범위를 벗어났습니다.")
        clips = list(self.clips)
        clip = clips.pop(old_index)
        clips.insert(int(new_index), clip)
        return EditSequence(tuple(clips))


@dataclass(frozen=True)
class WorkspaceState:
    """Single source of truth for the modernized editing workspace."""

    edit_sequence: EditSequence = field(default_factory=EditSequence)
    selected_clip_id: Optional[str] = None
    output_file: str = ""
    preset_id: str = "h264_review"

    def __post_init__(self):
        clip_ids = {clip.clip_id for clip in self.edit_sequence.clips}
        if self.selected_clip_id is not None and self.selected_clip_id not in clip_ids:
            raise ValueError("선택한 클립이 현재 작업에 없습니다.")

    @property
    def selected_clip(self) -> Optional[EditClip]:
        if self.selected_clip_id is None:
            return None
        return next(
            clip
            for clip in self.edit_sequence.clips
            if clip.clip_id == self.selected_clip_id
        )

    def select(self, clip_id: Optional[str]) -> "WorkspaceState":
        if clip_id is not None:
            self.edit_sequence._index_of(clip_id)
        return replace(self, selected_clip_id=clip_id)

    def set_clip_range(self, clip_id: str, source_range: ClipRange) -> "WorkspaceState":
        return replace(
            self,
            edit_sequence=self.edit_sequence.replace_range(clip_id, source_range),
        )

    def split_clip(
        self,
        clip_id: str,
        frame: int,
        left_clip_id: str,
        right_clip_id: str,
    ) -> "WorkspaceState":
        sequence = self.edit_sequence.split(
            clip_id,
            frame,
            left_clip_id,
            right_clip_id,
        )
        return replace(
            self,
            edit_sequence=sequence,
            selected_clip_id=right_clip_id,
        )

    def delete_clip(self, clip_id: str) -> "WorkspaceState":
        index = self.edit_sequence._index_of(clip_id)
        sequence = self.edit_sequence.delete(clip_id)
        selected_clip_id = self.selected_clip_id
        if selected_clip_id == clip_id:
            if sequence.clips:
                selected_clip_id = sequence.clips[min(index, len(sequence.clips) - 1)].clip_id
            else:
                selected_clip_id = None
        return replace(
            self,
            edit_sequence=sequence,
            selected_clip_id=selected_clip_id,
        )

    def duplicate_clip(self, clip_id: str, new_clip_id: str) -> "WorkspaceState":
        return replace(
            self,
            edit_sequence=self.edit_sequence.duplicate(clip_id, new_clip_id),
            selected_clip_id=new_clip_id,
        )

    def move_clip(self, clip_id: str, new_index: int) -> "WorkspaceState":
        return replace(
            self,
            edit_sequence=self.edit_sequence.move(clip_id, new_index),
        )

    def with_output(self, output_file: str, preset_id: Optional[str] = None) -> "WorkspaceState":
        changes = {"output_file": str(output_file or "")}
        if preset_id is not None:
            changes["preset_id"] = str(preset_id)
        return replace(self, **changes)


@dataclass(frozen=True)
class EncodingPreset:
    """Named FFmpeg option bundle exposed to editors as a practical preset."""

    preset_id: str
    name: str
    description: str
    ffmpeg_options: Dict[str, str] = field(default_factory=dict)
    extension: str = ".mp4"
    is_custom: bool = False
    hardware: str = "cpu"
    quality_tier: str = "review"
    requires_encoder: str = ""


@dataclass(frozen=True)
class FFmpegEncoderCapabilities:
    """Available FFmpeg encoders discovered from the configured binary."""

    encoders: set[str] = field(default_factory=set)
    nvenc_available: bool = False
    encoder_errors: Dict[str, str] = field(default_factory=dict)
    checked_at: float = 0.0
    message: str = ""


@dataclass(frozen=True)
class PreflightIssue:
    """One validation or guidance item shown before encoding."""

    severity: PreflightSeverity
    code: str
    message: str
    target: str = ""


@dataclass(frozen=True)
class MediaItem:
    """One source item in an encoding job."""

    source_path: str
    media_type: MediaType
    trim: FrameTrim = field(default_factory=FrameTrim)
    fps: Optional[float] = None
    frame_count: Optional[int] = None
    source_range: Optional[ClipRange] = None

    def __post_init__(self):
        if self.source_range is not None:
            if self.frame_count is None or int(self.frame_count) <= 0:
                raise ValueError("클립 구간을 사용하는 소스에는 전체 프레임 수가 필요합니다.")
            if self.source_range.source_out > int(self.frame_count):
                raise ValueError("클립 구간이 소스의 전체 프레임 수를 벗어났습니다.")


@dataclass(frozen=True)
class EncodingOptions:
    """Options that apply to an encoding job."""

    ffmpeg_options: Dict[str, str] = field(default_factory=dict)
    debug_mode: bool = False
    use_frame_based_trim: bool = True


@dataclass(frozen=True)
class EncodingJob:
    """Complete request to encode a list of media items into an output file."""

    media_items: List[MediaItem]
    output_file: str
    options: EncodingOptions = field(default_factory=EncodingOptions)


@dataclass(frozen=True)
class EncodingJobSummary:
    """Human-readable summary and validation result for an EncodingJob."""

    input_count: int
    output_file: str
    preset_name: str
    codec: str = ""
    resolution: str = ""
    framerate: str = ""
    total_head_trim: int = 0
    total_tail_trim: int = 0
    output_exists: bool = False
    issues: List[PreflightIssue] = field(default_factory=list)

    @property
    def can_start(self) -> bool:
        """Return True when no blocking preflight errors are present."""
        return not any(issue.severity == PreflightSeverity.ERROR for issue in self.issues)


@dataclass(frozen=True)
class EncodingProgressState:
    """Structured progress state for long-running encoding work."""

    stage: EncodingProgressStage
    progress: int = 0
    message: str = ""
    current_index: int = 0
    total_count: int = 0
    file_path: str = ""

    def __post_init__(self):
        object.__setattr__(self, "progress", max(0, min(100, int(self.progress or 0))))


@dataclass(frozen=True)
class EncodingResult:
    """Result reported by an encoding operation."""

    output_file: str
    success: bool
    message: str = ""


class CancellationToken:
    """Cooperative cancellation helper that can also terminate active processes."""

    def __init__(self):
        self._cancelled = False
        self._processes = []
        self._lock = threading.RLock()

    @property
    def is_cancelled(self) -> bool:
        with self._lock:
            return self._cancelled

    def cancel(self):
        with self._lock:
            self._cancelled = True
            processes = list(self._processes)

        for process in processes:
            self._terminate_process(process)

    def register_process(self, process):
        if process is None:
            return
        with self._lock:
            self._processes.append(process)
            should_cancel = self._cancelled
        if should_cancel:
            self._terminate_process(process)

    def unregister_process(self, process):
        with self._lock:
            if process in self._processes:
                self._processes.remove(process)

    def throw_if_cancelled(self):
        if self.is_cancelled:
            raise RuntimeError("작업이 취소되었습니다.")

    def _terminate_process(self, process):
        try:
            if process.poll() is None:
                process.terminate()
        except (AttributeError, subprocess.SubprocessError, OSError):
            try:
                process.kill()
            except (AttributeError, subprocess.SubprocessError, OSError):
                pass
