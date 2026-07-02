"""Core data models for encoding jobs.

These models intentionally avoid PySide types so encoding preparation can be
tested without starting the GUI.
"""

from dataclasses import dataclass, field
from enum import Enum
import subprocess
import threading
from typing import Dict, List, Optional


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


@dataclass(frozen=True)
class EncodingOptions:
    """Options that apply to an encoding job."""

    ffmpeg_options: Dict[str, str] = field(default_factory=dict)
    global_trim: FrameTrim = field(default_factory=FrameTrim)
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