"""Editor-facing encoding presets."""

from typing import Dict, Iterable

from app.core.models import EncodingPreset

CUSTOM_PRESET_ID = "custom"

_DEFAULT_COLOR_OPTIONS = {
    "pix_fmt": "yuv420p",
    "colorspace": "bt709",
    "color_primaries": "bt709",
    "color_trc": "bt709",
    "color_range": "limited",
}

_DEFAULT_MP4_OPTIONS = {
    **_DEFAULT_COLOR_OPTIONS,
    "c:a": "aac",
    "b:a": "192k",
    "movflags": "+faststart",
}

_PRESETS = [
    EncodingPreset(
        preset_id="h264_review",
        name="빠른 검토 (CPU H.264)",
        description="빠른 리뷰와 사내 공유용 균형 프리셋",
        ffmpeg_options={
            "c:v": "libx264",
            "preset": "medium",
            "crf": "18",
            **_DEFAULT_MP4_OPTIONS,
        },
        extension=".mp4",
        hardware="cpu",
        quality_tier="review",
    ),
    EncodingPreset(
        preset_id="h265_small",
        name="용량 절약 (CPU H.265)",
        description="용량을 줄인 납품/아카이브용 프리셋",
        ffmpeg_options={
            "c:v": "libx265",
            "preset": "slow",
            "crf": "24",
            "tag:v": "hvc1",
            **_DEFAULT_MP4_OPTIONS,
        },
        extension=".mp4",
        hardware="cpu",
        quality_tier="small",
    ),
    EncodingPreset(
        preset_id="vp9_web",
        name="웹용 (VP9)",
        description="웹 미리보기와 브라우저 재생용 프리셋",
        ffmpeg_options={
            "c:v": "libvpx-vp9",
            "b:v": "0",
            "crf": "32",
            **_DEFAULT_COLOR_OPTIONS,
        },
        extension=".webm",
        hardware="cpu",
        quality_tier="web",
    ),
    EncodingPreset(
        preset_id="gpu_h264_draft",
        name="초고속 초안 (GPU H.264)",
        description="NVENC 기반 빠른 초안 확인용 프리셋",
        ffmpeg_options={
            "c:v": "h264_nvenc",
            "preset": "p1",
            "rc": "vbr",
            "cq": "28",
            **_DEFAULT_MP4_OPTIONS,
        },
        extension=".mp4",
        hardware="nvenc",
        quality_tier="draft",
        requires_encoder="h264_nvenc",
    ),
    EncodingPreset(
        preset_id="gpu_h264_review",
        name="빠른 검토 (GPU H.264)",
        description="NVENC 기반 반복 리뷰용 균형 프리셋",
        ffmpeg_options={
            "c:v": "h264_nvenc",
            "preset": "p4",
            "rc": "vbr",
            "cq": "23",
            **_DEFAULT_MP4_OPTIONS,
        },
        extension=".mp4",
        hardware="nvenc",
        quality_tier="review",
        requires_encoder="h264_nvenc",
    ),
    EncodingPreset(
        preset_id="gpu_h264_delivery",
        name="고품질 납품 (GPU H.264)",
        description="NVENC 기반 고품질 납품용 H.264 프리셋",
        ffmpeg_options={
            "c:v": "h264_nvenc",
            "preset": "p6",
            "rc": "vbr",
            "cq": "19",
            **_DEFAULT_MP4_OPTIONS,
        },
        extension=".mp4",
        hardware="nvenc",
        quality_tier="delivery",
        requires_encoder="h264_nvenc",
    ),
    EncodingPreset(
        preset_id="gpu_h265_small",
        name="용량 절약 (GPU H.265)",
        description="NVENC 기반 용량 절감용 H.265 프리셋",
        ffmpeg_options={
            "c:v": "hevc_nvenc",
            "preset": "p5",
            "rc": "vbr",
            "cq": "25",
            "tag:v": "hvc1",
            **_DEFAULT_MP4_OPTIONS,
        },
        extension=".mp4",
        hardware="nvenc",
        quality_tier="small",
        requires_encoder="hevc_nvenc",
    ),
    EncodingPreset(
        preset_id="gpu_h265_quality",
        name="고품질 보관 (GPU H.265)",
        description="NVENC 기반 고품질 H.265 마스터 프리셋",
        ffmpeg_options={
            "c:v": "hevc_nvenc",
            "preset": "p6",
            "rc": "vbr",
            "cq": "20",
            "tag:v": "hvc1",
            **_DEFAULT_MP4_OPTIONS,
        },
        extension=".mp4",
        hardware="nvenc",
        quality_tier="quality",
        requires_encoder="hevc_nvenc",
    ),
    EncodingPreset(
        preset_id=CUSTOM_PRESET_ID,
        name="직접 설정",
        description="현재 고급 FFmpeg 옵션을 그대로 사용",
        ffmpeg_options={},
        extension=".mp4",
        is_custom=True,
        hardware="custom",
        quality_tier="custom",
    ),
]

_PRESET_BY_ID = {preset.preset_id: preset for preset in _PRESETS}
_PRESET_BY_NAME = {preset.name: preset for preset in _PRESETS}
_PRESET_BY_NAME.update({
    "H.264 Review": _PRESET_BY_ID["h264_review"],
    "H.265 Small": _PRESET_BY_ID["h265_small"],
    "VP9 Web": _PRESET_BY_ID["vp9_web"],
    "GPU H.264 Draft": _PRESET_BY_ID["gpu_h264_draft"],
    "GPU H.264 Review": _PRESET_BY_ID["gpu_h264_review"],
    "GPU H.264 Delivery": _PRESET_BY_ID["gpu_h264_delivery"],
    "GPU H.265 Small": _PRESET_BY_ID["gpu_h265_small"],
    "GPU H.265 Quality": _PRESET_BY_ID["gpu_h265_quality"],
    "Custom": _PRESET_BY_ID[CUSTOM_PRESET_ID],
})


def get_presets() -> Iterable[EncodingPreset]:
    return tuple(_PRESETS)


def get_preset(identifier: str) -> EncodingPreset:
    if identifier in _PRESET_BY_ID:
        return _PRESET_BY_ID[identifier]
    if identifier in _PRESET_BY_NAME:
        return _PRESET_BY_NAME[identifier]
    return _PRESET_BY_ID["h264_review"]


def get_preset_id_by_name(name: str) -> str:
    return get_preset(name).preset_id


def apply_preset_options(preset_id: str, current_options: Dict[str, str] | None = None) -> Dict[str, str]:
    preset = get_preset(preset_id)
    if preset.is_custom:
        return dict(current_options or {})
    return dict(preset.ffmpeg_options)
