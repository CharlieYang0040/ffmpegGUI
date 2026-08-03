import json
import os
import subprocess
from typing import Any, Sequence

from app.core.ffmpeg_process import decode_process_output


def hidden_process_kwargs() -> dict[str, Any]:
    """Return subprocess options that prevent console windows on Windows."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {
        "creationflags": subprocess.CREATE_NO_WINDOW,
        "startupinfo": startupinfo,
    }


def run_hidden(command: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    options = hidden_process_kwargs()
    options.update(kwargs)
    return subprocess.run(list(command), **options)


def popen_hidden(command: Sequence[str], **kwargs) -> subprocess.Popen:
    options = hidden_process_kwargs()
    options.update(kwargs)
    return subprocess.Popen(list(command), **options)


def probe_media_json(ffprobe_path: str, input_file: str) -> dict:
    """Run ffprobe without opening a console and return its JSON document."""
    if not ffprobe_path:
        raise ValueError("FFprobe 경로가 설정되지 않았습니다.")
    result = run_hidden(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            input_file,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = decode_process_output(result.stderr).strip()
        raise RuntimeError(message or f"FFprobe 실행 실패 (코드 {result.returncode})")
    return json.loads(decode_process_output(result.stdout))


def probe_video_frame_timestamps(ffprobe_path: str, input_file: str) -> list[float]:
    """Return video-frame presentation timestamps in milliseconds."""
    if not ffprobe_path:
        raise ValueError("FFprobe 경로가 설정되지 않았습니다.")
    result = run_hidden(
        [
            ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time",
            "-of",
            "json",
            input_file,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        message = decode_process_output(result.stderr).strip()
        raise RuntimeError(message or f"FFprobe 프레임 분석 실패 (코드 {result.returncode})")
    document = json.loads(decode_process_output(result.stdout))
    timestamps = []
    for frame in document.get("frames", []):
        value = frame.get("best_effort_timestamp_time")
        try:
            timestamps.append(float(value) * 1000.0)
        except (TypeError, ValueError):
            continue
    return timestamps
