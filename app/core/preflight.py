"""Preflight validation and summary helpers for encoding jobs."""

import os
from typing import Optional

from app.core.job_builder import validate_encoding_job
from app.core.models import (
    EncodingJob,
    EncodingJobSummary,
    EncodingPreset,
    FFmpegEncoderCapabilities,
    MediaType,
    PreflightIssue,
    PreflightSeverity,
)
from app.core.encoding_presets import get_preset
from app.utils.utils import get_first_sequence_file


def _settings_value(settings, key: str, default=""):
    if settings is None:
        return default
    getter_name = f"get_{key}"
    if hasattr(settings, getter_name):
        return getattr(settings, getter_name)()
    if hasattr(settings, "get"):
        return settings.get(key, default)
    return default


def _source_exists(path: str, media_type: MediaType) -> bool:
    if not path:
        return False
    if media_type == MediaType.IMAGE_SEQUENCE or "%" in path:
        return bool(get_first_sequence_file(path))
    return os.path.exists(path)


def _option_value(job: EncodingJob, key: str) -> str:
    if not job.options:
        return ""
    return str(job.options.ffmpeg_options.get(key, ""))


def _encoder_capabilities(settings) -> FFmpegEncoderCapabilities:
    if settings is not None and hasattr(settings, "get_encoder_capabilities"):
        return settings.get_encoder_capabilities()

    from app.core.ffmpeg_manager import FFmpegManager

    manager = FFmpegManager()
    saved_path = _settings_value(settings, "ffmpeg_path", "")
    if not manager.get_ffmpeg_path():
        manager.find_existing_ffmpeg(saved_path)
    return manager.get_encoder_capabilities()


def _add_required_encoder_issues(
    issues: list[PreflightIssue],
    preset: EncodingPreset,
    settings,
) -> None:
    required_encoder = getattr(preset, "requires_encoder", "") or ""
    if not required_encoder:
        return

    capabilities = _encoder_capabilities(settings)
    if required_encoder not in capabilities.encoders:
        detail = capabilities.message or "현재 FFmpeg에서 사용할 수 있는 encoder 목록을 확인하지 못했습니다."
        issues.append(
            PreflightIssue(
                severity=PreflightSeverity.ERROR,
                code="missing_required_encoder",
                message=(
                    f"선택한 GPU 프리셋에는 {required_encoder} 인코더가 필요하지만 "
                    f"현재 FFmpeg에서 확인되지 않았습니다. {detail}"
                ),
                target=required_encoder,
            )
        )
        return
    encoder_error = capabilities.encoder_errors.get(required_encoder, "")
    if encoder_error:
        issues.append(
            PreflightIssue(
                severity=PreflightSeverity.ERROR,
                code="encoder_runtime_unavailable",
                message=(
                    f"{required_encoder}가 FFmpeg 목록에는 있지만 실제로 초기화되지 "
                    f"않았습니다. GPU 드라이버와 FFmpeg 호환성을 확인하세요. "
                    f"{encoder_error}"
                ),
                target=required_encoder,
            )
        )
        return

    issues.append(
        PreflightIssue(
            severity=PreflightSeverity.INFO,
            code="required_encoder_available",
            message=f"GPU 인코더 확인됨: {required_encoder}",
            target=required_encoder,
        )
    )


def build_preflight(
    job: EncodingJob,
    settings=None,
    preset: Optional[EncodingPreset] = None,
) -> EncodingJobSummary:
    """Build an editor-readable summary and issue list for an encoding job."""
    issues: list[PreflightIssue] = []
    preset = preset or get_preset("h264_review")

    try:
        validate_encoding_job(job)
    except ValueError as exc:
        issues.append(
            PreflightIssue(
                severity=PreflightSeverity.ERROR,
                code="invalid_job",
                message=str(exc),
            )
        )

    output_file = getattr(job, "output_file", "") or ""
    output_exists = bool(output_file and os.path.exists(output_file))
    output_dir = os.path.dirname(output_file)
    if output_file and output_dir and not os.path.isdir(output_dir):
        issues.append(
            PreflightIssue(
                severity=PreflightSeverity.ERROR,
                code="missing_output_dir",
                message="출력 폴더가 존재하지 않습니다.",
                target=output_dir,
            )
        )
    if output_exists:
        issues.append(
            PreflightIssue(
                severity=PreflightSeverity.WARNING,
                code="output_exists",
                message="같은 이름의 출력 파일이 이미 있습니다. 인코딩 시 덮어쓸 수 있습니다.",
                target=output_file,
            )
        )

    expected_extension = (getattr(preset, "extension", "") or "").lower()
    actual_extension = os.path.splitext(output_file)[1].lower() if output_file else ""
    if output_file and expected_extension and actual_extension and actual_extension != expected_extension:
        issues.append(
            PreflightIssue(
                severity=PreflightSeverity.WARNING,
                code="output_extension_mismatch",
                message=f"선택한 프리셋은 {expected_extension} 출력에 맞춰져 있습니다.",
                target=output_file,
            )
        )

    ffmpeg_path = _settings_value(settings, "ffmpeg_path", "")
    if not ffmpeg_path:
        issues.append(
            PreflightIssue(
                severity=PreflightSeverity.WARNING,
                code="ffmpeg_pending",
                message="FFmpeg 경로가 아직 확정되지 않았습니다. 시작 시 자동 준비를 시도합니다.",
            )
        )

    _add_required_encoder_issues(issues, preset, settings)

    total_head_trim = 0
    total_tail_trim = 0
    media_types = set()
    for index, item in enumerate(getattr(job, "media_items", []) or [], start=1):
        media_types.add(item.media_type)
        if item.source_range is not None and item.frame_count:
            total_head_trim += item.source_range.source_in
            total_tail_trim += int(item.frame_count) - item.source_range.source_out
        elif item.trim:
            trim = item.trim
            total_head_trim += trim.head_frames
            total_tail_trim += trim.tail_frames
        if item.media_type == MediaType.UNKNOWN:
            issues.append(
                PreflightIssue(
                    severity=PreflightSeverity.WARNING,
                    code="unknown_media_type",
                    message=f"{index}번 소스의 미디어 형식을 확인할 수 없습니다.",
                    target=item.source_path,
                )
            )
        if not _source_exists(item.source_path, item.media_type):
            issues.append(
                PreflightIssue(
                    severity=PreflightSeverity.ERROR,
                    code="missing_input",
                    message=f"{index}번 소스 파일을 찾을 수 없습니다.",
                    target=item.source_path,
                )
            )

    if len(media_types - {MediaType.UNKNOWN}) > 1:
        issues.append(
            PreflightIssue(
                severity=PreflightSeverity.INFO,
                code="mixed_media_types",
                message="서로 다른 미디어 타입이 섞여 있습니다. 첫 소스 기준으로 출력 속성을 맞춥니다.",
            )
        )

    codec = _option_value(job, "c:v") or preset.ffmpeg_options.get("c:v", "")
    resolution = _option_value(job, "s")
    framerate = _option_value(job, "r")

    return EncodingJobSummary(
        input_count=len(getattr(job, "media_items", []) or []),
        output_file=output_file,
        preset_name=preset.name,
        codec=codec,
        resolution=resolution,
        framerate=framerate,
        total_head_trim=total_head_trim,
        total_tail_trim=total_tail_trim,
        output_exists=output_exists,
        issues=issues,
    )
