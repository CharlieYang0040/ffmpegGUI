"""Import-safe examples for the supported ffmpegGUI 2.x contracts."""

from app.config import APP_VERSION
from app.core.ffmpeg_manager import FFmpegManager
from app.core.models import ClipRange, EditClip, EditSequence, WorkspaceState
from app.services.settings_service import SettingsService
from app.utils.ffmpeg_utils import FFmpegUtils


def build_workspace(source_path: str, frame_count: int = 120) -> WorkspaceState:
    clip = EditClip(
        clip_id="example-clip",
        source_path=source_path,
        source_range=ClipRange(0, frame_count),
        source_frame_count=frame_count,
        source_fps=30.0,
    )
    return WorkspaceState(
        edit_sequence=EditSequence((clip,)),
        selected_clip_id=clip.clip_id,
    )


def current_services():
    """Return supported service objects without touching user settings."""
    return {
        "version": APP_VERSION,
        "settings": SettingsService(),
        "ffmpeg_manager": FFmpegManager(),
        "ffmpeg_facade": FFmpegUtils(),
    }


if __name__ == "__main__":
    workspace = build_workspace("input.mp4")
    services = current_services()
    print(
        f"ffmpegGUI {services['version']}: "
        f"{workspace.edit_sequence.frame_count} frame example"
    )
