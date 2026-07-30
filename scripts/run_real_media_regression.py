"""Generate fixed media samples and exercise the real FFmpegGUI pipeline.

The generated media and reports are written below artifacts/, which is ignored
by Git. This script intentionally uses the application's FFmpegManager and
EncodingJob path instead of a mocked processor.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Any

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.encoding_presets import get_preset
from app.core.ffmpeg_manager import FFmpegManager
from app.core.models import (
    CancellationToken,
    ClipRange,
    EncodingJob,
    EncodingOptions,
    FrameTrim,
    MediaItem,
    MediaType,
)
from app.core.webp_processor import read_webp_frame_durations
from app.utils.ffmpeg_utils import FFmpegUtils


class RecordingCancellationToken(CancellationToken):
    """Cancellation token that records spawned FFmpeg process IDs."""

    def __init__(self) -> None:
        super().__init__()
        self.process_ids: list[int] = []
        self.process_started = threading.Event()

    def register_process(self, process) -> None:
        self.process_ids.append(process.pid)
        self.process_started.set()
        super().register_process(process)


def run_command(command: list[str], description: str) -> None:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        stderr_tail = "\n".join(result.stderr.splitlines()[-30:])
        raise RuntimeError(f"{description} failed ({result.returncode})\n{stderr_tail}")


def generate_samples(ffmpeg: str, sample_dir: Path) -> dict[str, Path]:
    sample_dir.mkdir(parents=True, exist_ok=True)
    sequence_dir = sample_dir / "png_sequence"
    sequence_dir.mkdir(parents=True, exist_ok=True)

    samples = {
        "cfr_audio": sample_dir / "cfr_30fps_audio.mp4",
        "vfr": sample_dir / "vfr_15_to_30fps.mp4",
        "sequence_pattern": sequence_dir / "frame.%04d.png",
        "webp": sample_dir / "animated_12fps.webp",
        "cancel_source": sample_dir / "cancel_source_720p.mp4",
    }

    run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30:duration=4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000:duration=4",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            "-y",
            str(samples["cfr_audio"]),
        ],
        "CFR sample generation",
    )
    run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30:duration=3",
            "-vf",
            "select=if(lt(t\\,1.5)\\,not(mod(n\\,2))\\,1)",
            "-fps_mode",
            "vfr",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(samples["vfr"]),
        ],
        "VFR sample generation",
    )
    run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=12:duration=2",
            "-frames:v",
            "24",
            "-y",
            str(samples["sequence_pattern"]),
        ],
        "PNG sequence generation",
    )
    sequence_frames = []
    for frame_path in sorted(sequence_dir.glob("frame.*.png")):
        with Image.open(frame_path) as frame:
            sequence_frames.append(frame.convert("RGB"))
    frame_durations = [83] * 16 + [84] * 8
    sequence_frames[0].save(
        samples["webp"],
        "WEBP",
        save_all=True,
        append_images=sequence_frames[1:],
        duration=frame_durations,
        loop=0,
        lossless=True,
    )
    run_command(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=30:duration=12",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(samples["cancel_source"]),
        ],
        "cancellation sample generation",
    )
    return samples


def fraction_value(value: str | None) -> float:
    if not value or value == "N/A":
        return 0.0
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        return float(numerator) / denominator_value if denominator_value else 0.0
    return float(value)


def probe_media(ffprobe: str, path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path}: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
    duration_text = video.get("duration") or data.get("format", {}).get("duration") or "0"
    frame_text = video.get("nb_read_frames") or video.get("nb_frames") or "0"
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "duration_seconds": float(duration_text),
        "frame_count": int(frame_text) if frame_text not in ("", "N/A") else 0,
        "r_frame_rate": video.get("r_frame_rate", ""),
        "avg_frame_rate": video.get("avg_frame_rate", ""),
        "nominal_fps": fraction_value(video.get("r_frame_rate")),
        "average_fps": fraction_value(video.get("avg_frame_rate")),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "video_codec": video.get("codec_name", ""),
        "has_audio": audio is not None,
        "audio_codec": audio.get("codec_name", "") if audio else "",
    }


def probe_webp(path: Path) -> dict[str, Any]:
    with Image.open(path) as image:
        frame_count = int(getattr(image, "n_frames", 1))
        durations = []
        for frame_index in range(frame_count):
            image.seek(frame_index)
            durations.append(int(image.info.get("duration", 0)))
        if sum(durations) <= 0:
            container_durations = read_webp_frame_durations(str(path))
            if len(container_durations) == frame_count:
                durations = container_durations
        duration_seconds = sum(durations) / 1000
        fps = frame_count / duration_seconds if duration_seconds > 0 else 0.0
        return {
            "path": str(path),
            "size_bytes": path.stat().st_size,
            "duration_seconds": duration_seconds,
            "frame_count": frame_count,
            "r_frame_rate": "",
            "avg_frame_rate": "",
            "nominal_fps": fps,
            "average_fps": fps,
            "width": image.width,
            "height": image.height,
            "video_codec": "webp",
            "has_audio": False,
            "audio_codec": "",
            "frame_durations_ms": durations,
        }


def run_encoding_case(
    ffmpeg_utils: FFmpegUtils,
    ffprobe: str,
    name: str,
    source: Path,
    media_type: MediaType,
    output: Path,
    trim: FrameTrim,
    fps: float | None = None,
    preset_id: str = "h264_review",
) -> dict[str, Any]:
    preset_options = dict(get_preset(preset_id).ffmpeg_options)
    if fps:
        preset_options["r"] = str(fps)
    progress: list[int] = []
    tasks: list[str] = []
    started_at = time.perf_counter()
    if media_type == MediaType.WEBP:
        source_probe = probe_webp(source)
        source_frame_count = source_probe["frame_count"]
    elif media_type == MediaType.IMAGE_SEQUENCE:
        probe_source = sorted(source.parent.glob("*.png"))[0]
        source_probe = probe_media(ffprobe, probe_source)
        source_frame_count = len(list(source.parent.glob("*.png")))
    else:
        source_probe = probe_media(ffprobe, source)
        source_frame_count = source_probe["frame_count"]
    source_range = ClipRange(
        trim.head_frames,
        source_frame_count - trim.tail_frames,
    )
    job = EncodingJob(
        media_items=[
            MediaItem(
                source_path=str(source),
                media_type=media_type,
                source_range=source_range,
                fps=fps,
                frame_count=source_frame_count,
            )
        ],
        output_file=str(output),
        options=EncodingOptions(
            ffmpeg_options=preset_options,
            use_frame_based_trim=True,
        ),
    )
    ffmpeg_utils.process_encoding_job(
        job,
        progress_callback=lambda value: progress.append(int(value)),
        task_callback=tasks.append,
    )
    output_probe = probe_media(ffprobe, output)
    expected_frames = None
    if media_type != MediaType.IMAGE_SEQUENCE:
        expected_frames = max(1, source_probe["frame_count"] - trim.head_frames - trim.tail_frames)
    else:
        expected_frames = max(1, len(list(source.parent.glob("*.png"))) - trim.head_frames - trim.tail_frames)
    errors = []
    if abs(output_probe["frame_count"] - expected_frames) > 1:
        errors.append(
            f"frame count mismatch: expected {expected_frames}, got {output_probe['frame_count']}"
        )
    if media_type == MediaType.VIDEO and source_probe["has_audio"] and not output_probe["has_audio"]:
        errors.append("audio stream was lost")
    if media_type in (MediaType.IMAGE_SEQUENCE, MediaType.WEBP) and fps:
        if abs(output_probe["average_fps"] - fps) > 0.1:
            errors.append(
                f"frame rate mismatch: expected {fps}, got {output_probe['average_fps']}"
            )
    if progress and (min(progress) < 0 or max(progress) > 100):
        errors.append("progress escaped 0..100")
    if progress and any(current < previous for previous, current in zip(progress, progress[1:])):
        errors.append("progress was not monotonic")
    return {
        "name": name,
        "preset_id": preset_id,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "trim": {
            "head_frames": trim.head_frames,
            "tail_frames": trim.tail_frames,
        },
        "expected_frames": expected_frames,
        "source": source_probe,
        "output": output_probe,
        "progress_samples": progress,
        "tasks": tasks,
    }


def run_cancellation_case(
    ffmpeg_utils: FFmpegUtils,
    source: Path,
    output: Path,
) -> dict[str, Any]:
    token = RecordingCancellationToken()
    exception: list[str] = []
    job = EncodingJob(
        media_items=[
            MediaItem(
                source_path=str(source),
                media_type=MediaType.VIDEO,
                trim=FrameTrim(),
            )
        ],
        output_file=str(output),
        options=EncodingOptions(
            ffmpeg_options={
                **get_preset("h264_review").ffmpeg_options,
                "preset": "veryslow",
            },
            use_frame_based_trim=True,
        ),
    )

    def worker() -> None:
        try:
            ffmpeg_utils.process_encoding_job(job, cancel_token=token)
        except Exception as exc:  # Expected for the cancellation path.
            exception.append(str(exc))

    thread = threading.Thread(target=worker, name="real-media-cancel-test")
    started_at = time.perf_counter()
    thread.start()
    process_seen = token.process_started.wait(timeout=15)
    if process_seen:
        token.cancel()
    thread.join(timeout=20)
    time.sleep(0.2)

    live_pids = []
    for pid in token.process_ids:
        try:
            os.kill(pid, 0)
        except OSError:
            continue
        live_pids.append(pid)
    errors = []
    if not process_seen:
        errors.append("no FFmpeg child process was observed")
    if thread.is_alive():
        errors.append("encoding worker did not stop after cancellation")
    if output.exists():
        errors.append("partial output file remained after cancellation")
    if live_pids:
        errors.append(f"FFmpeg child processes still alive: {live_pids}")
    if not token.is_cancelled:
        errors.append("cancellation token did not enter cancelled state")
    if not exception or "취소" not in exception[0]:
        errors.append(f"unexpected cancellation exception: {exception}")
    return {
        "name": "cancel_active_encode",
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        "process_ids": token.process_ids,
        "exception": exception,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "real_media_regression",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="Fail instead of downloading FFmpeg when it is not installed.",
    )
    args = parser.parse_args()

    output_dir = args.output_dir.resolve()
    artifacts_root = (PROJECT_ROOT / "artifacts").resolve()
    if artifacts_root not in output_dir.parents:
        raise ValueError(
            f"--output-dir must be a child of the project artifacts directory: "
            f"{artifacts_root}"
        )
    if output_dir.exists():
        shutil.rmtree(output_dir)
    sample_dir = output_dir / "samples"
    encoded_dir = output_dir / "encoded"
    encoded_dir.mkdir(parents=True, exist_ok=True)

    manager = FFmpegManager()
    ffmpeg = manager.ensure_ffmpeg_exists(allow_download=not args.no_download)
    ffprobe = manager.get_ffprobe_path()
    if not ffmpeg or not ffprobe:
        raise RuntimeError("FFmpeg/FFprobe is not available")
    capabilities = manager.get_encoder_capabilities(force_refresh=True)

    samples = generate_samples(ffmpeg, sample_dir)
    sample_probes = {
        "cfr_audio": probe_media(ffprobe, samples["cfr_audio"]),
        "vfr": probe_media(ffprobe, samples["vfr"]),
        "webp": probe_webp(samples["webp"]),
    }
    ffmpeg_utils = FFmpegUtils()
    cases = [
        run_encoding_case(
            ffmpeg_utils,
            ffprobe,
            "cfr_audio_trim",
            samples["cfr_audio"],
            MediaType.VIDEO,
            encoded_dir / "cfr_audio_trim.mp4",
            FrameTrim(15, 30),
        ),
        run_encoding_case(
            ffmpeg_utils,
            ffprobe,
            "vfr_trim",
            samples["vfr"],
            MediaType.VIDEO,
            encoded_dir / "vfr_trim.mp4",
            FrameTrim(5, 7),
        ),
        run_encoding_case(
            ffmpeg_utils,
            ffprobe,
            "png_sequence_trim",
            samples["sequence_pattern"],
            MediaType.IMAGE_SEQUENCE,
            encoded_dir / "png_sequence_trim.mp4",
            FrameTrim(3, 5),
            fps=12,
        ),
        run_encoding_case(
            ffmpeg_utils,
            ffprobe,
            "animated_webp_trim",
            samples["webp"],
            MediaType.WEBP,
            encoded_dir / "animated_webp_trim.mp4",
            FrameTrim(3, 5),
            fps=12,
        ),
        run_cancellation_case(
            ffmpeg_utils,
            samples["cancel_source"],
            encoded_dir / "cancelled.mp4",
        ),
        run_encoding_case(
            ffmpeg_utils,
            ffprobe,
            "retry_after_cancel",
            samples["cfr_audio"],
            MediaType.VIDEO,
            encoded_dir / "retry_after_cancel.mp4",
            FrameTrim(15, 30),
        ),
    ]
    if (
        "h264_nvenc" in capabilities.encoders
        and "h264_nvenc" not in capabilities.encoder_errors
    ):
        cases.append(
            run_encoding_case(
                ffmpeg_utils,
                ffprobe,
                "nvenc_h264_trim",
                samples["cfr_audio"],
                MediaType.VIDEO,
                encoded_dir / "nvenc_h264_trim.mp4",
                FrameTrim(15, 30),
                preset_id="gpu_h264_review",
            )
        )
    else:
        nvenc_reason = capabilities.encoder_errors.get(
            "h264_nvenc",
            "h264_nvenc is not advertised by the installed FFmpeg",
        )
        cases.append(
            {
                "name": "nvenc_h264_trim",
                "preset_id": "gpu_h264_review",
                "status": "skipped",
                "errors": [],
                "reason": nvenc_reason,
            }
        )
    report = {
        "schema_version": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ffmpeg": ffmpeg,
        "ffprobe": ffprobe,
        "encoder_capabilities": {
            "nvenc_available": capabilities.nvenc_available,
            "h264_nvenc": "h264_nvenc" in capabilities.encoders,
            "encoder_errors": capabilities.encoder_errors,
            "message": capabilities.message,
        },
        "output_dir": str(output_dir),
        "samples": sample_probes,
        "cases": cases,
        "summary": {
            "passed": sum(case["status"] == "passed" for case in cases),
            "failed": sum(case["status"] == "failed" for case in cases),
            "skipped": sum(case["status"] == "skipped" for case in cases),
        },
    }
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Report: {report_path}")
    for case in cases:
        print(f"[{case['status'].upper()}] {case['name']}")
        for error in case["errors"]:
            print(f"  - {error}")
    print(
        f"Summary: {report['summary']['passed']} passed, "
        f"{report['summary']['failed']} failed, "
        f"{report['summary']['skipped']} skipped"
    )
    return 1 if report["summary"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
