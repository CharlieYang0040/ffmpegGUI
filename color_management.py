import json
import logging
import os
import tempfile
import hashlib
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import PyOpenColorIO as ocio  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    ocio = None


DEFAULT_LUT_SIZE = 33
_MANAGER_CACHE: Dict[str, "ColorPipelineManager"] = {}


class ColorPipelineError(RuntimeError):
    """Raised when color management setup fails."""


class ColorPipelineManager:
    """Utility class responsible for OCIO-based color transformations."""

    FALLBACK_INPUTS = [
        "Scene Linear (Rec709)",
        "sRGB Texture",
    ]

    FALLBACK_OUTPUTS = [
        "Rec.709 SDR",
        "sRGB",
    ]

    FALLBACK_METADATA = {
        "Rec.709 SDR": {
            "color_primaries": "bt709",
            "color_trc": "bt709",
            "colorspace": "bt709",
            "color_range": "limited",
        },
        "sRGB": {
            "color_primaries": "bt709",
            "color_trc": "iec61966-2-1",
            "colorspace": "bt709",
            "color_range": "full",
        },
    }

    FALLBACK_FILTERS = {
        ("Scene Linear (Rec709)", "Rec.709 SDR"): {
            "filters": [
                ("zscale", {
                    "matrix": "bt709",
                    "matrixin": "gbr",
                    "primaries": "bt709",
                    "primariesin": "bt709",
                    "transfer": "bt709",
                    "transferin": "linear",
                    "range": "limited",
                    "rangein": "full",
                })
            ],
            "metadata": FALLBACK_METADATA["Rec.709 SDR"],
        },
        ("Scene Linear (Rec709)", "sRGB"): {
            "filters": [
                ("zscale", {
                    "matrix": "bt709",
                    "matrixin": "gbr",
                    "primaries": "bt709",
                    "primariesin": "bt709",
                    "transfer": "iec61966-2-1",
                    "transferin": "linear",
                    "range": "full",
                    "rangein": "full",
                })
            ],
            "metadata": FALLBACK_METADATA["sRGB"],
        },
        ("sRGB Texture", "Rec.709 SDR"): {
            "filters": [
                ("zscale", {
                    "matrix": "bt709",
                    "matrixin": "gbr",
                    "primaries": "bt709",
                    "primariesin": "bt709",
                    "transfer": "bt709",
                    "transferin": "iec61966-2-1",
                    "range": "limited",
                    "rangein": "full",
                })
            ],
            "metadata": FALLBACK_METADATA["Rec.709 SDR"],
        },
        ("sRGB Texture", "sRGB"): {
            "filters": [],  # 이미 sRGB → sRGB
            "metadata": FALLBACK_METADATA["sRGB"],
        },
    }

    def __init__(self, config_path: Optional[str] = None):
        self._explicit_config_path = config_path.strip() if config_path else ""
        self._config: Optional["ocio.Config"] = None
        self._lut_cache_dir = os.path.join(tempfile.gettempdir(), "ffmpeg_gui_luts")
        os.makedirs(self._lut_cache_dir, exist_ok=True)
        self._load_config()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def config_path(self) -> Optional[str]:
        if self._config is None:
            return None
        if self._explicit_config_path:
            return self._explicit_config_path
        try:
            return self._config.getCacheID().split("|")[0]
        except Exception:  # pragma: no cover - best effort
            return None

    @property
    def is_available(self) -> bool:
        return self._config is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_input_spaces(self) -> List[str]:
        if not self.is_available:
            return list(self.FALLBACK_INPUTS)
        return sorted(self._config.getColorSpaceNames())

    def list_displays(self) -> List[str]:
        if not self.is_available:
            return ["Rec.709", "sRGB"]
        return list(self._config.getDisplays())

    def list_views(self, display: str) -> List[str]:
        if not self.is_available:
            if display == "Rec.709":
                return ["Film", "Video"]
            return ["Standard"]
        try:
            return list(self._config.getViews(display))
        except Exception:  # pragma: no cover
            logger.warning("OCIO display '%s'에 대한 뷰를 가져오지 못했습니다.", display)
            return []

    def get_default_io(self) -> Tuple[str, str, str]:
        inputs = self.list_input_spaces()
        displays = self.list_displays()
        display = displays[0] if displays else "Rec.709"
        views = self.list_views(display)
        view = views[0] if views else "Standard"
        input_space = inputs[0] if inputs else "Scene Linear (Rec709)"
        return input_space, display, view

    def build_filter_chain(
        self,
        input_space: str,
        display: str,
        view: str,
        lut_size: int = DEFAULT_LUT_SIZE,
    ) -> Tuple[List[Tuple[str, Dict[str, str]]], Dict[str, str]]:
        if self.is_available:
            try:
                lut_path = self._bake_lut(input_space, display, view, lut_size)
                metadata = self._metadata_from_view(display, view)
                return [("lut3d", {"file": lut_path})], metadata
            except Exception as exc:
                logger.warning("OCIO LUT 생성 실패 (%s). Fallback으로 전환합니다.", exc)

        candidates = [
            (input_space, view),
            (input_space, display),
            (input_space, "Rec.709 SDR"),
            (input_space, "sRGB"),
        ]
        for fallback_key in candidates:
            if fallback_key in self.FALLBACK_FILTERS:
                spec = self.FALLBACK_FILTERS[fallback_key]
                filters = list(spec["filters"])  # shallow copy
                metadata = dict(spec["metadata"])
                return filters, metadata

        raise ColorPipelineError(
            f"지원되지 않는 색상 변환 조합입니다: input={input_space}, display={display}, view={view}"
        )

    # ------------------------------------------------------------------
    # LUT / Metadata helpers
    # ------------------------------------------------------------------
    def _load_config(self):
        if ocio is None:
            logger.warning("PyOpenColorIO가 설치되어 있지 않아 고급 컬러 매니지먼트를 사용할 수 없습니다.")
            self._config = None
            return

        try:
            if self._explicit_config_path:
                if not os.path.exists(self._explicit_config_path):
                    raise FileNotFoundError(self._explicit_config_path)
                self._config = ocio.Config.CreateFromFile(self._explicit_config_path)
            else:
                self._config = ocio.GetCurrentConfig()
        except Exception as exc:
            logger.error("OCIO Config 로드 실패: %s", exc)
            self._config = None

    def _bake_lut(self, input_space: str, display: str, view: str, lut_size: int) -> str:
        if not self.is_available:
            raise ColorPipelineError("OCIO 설정을 사용할 수 없습니다.")

        key = json.dumps(
            {
                "config": self.config_path,
                "input": input_space,
                "display": display,
                "view": view,
                "lut_size": lut_size,
            },
            sort_keys=True,
        ).encode("utf-8")
        digest = hashlib.sha1(key).hexdigest()
        lut_path = os.path.join(self._lut_cache_dir, f"ocio_{digest}.cube")

        if os.path.exists(lut_path):
            return lut_path

        baker = ocio.Baker()
        baker.setConfig(self._config)
        baker.setFormat("Cube")
        baker.setInputSpace(input_space)
        if display and view:
            baker.setDisplay(display)
            baker.setView(view)
        else:
            baker.setTargetSpace(view or display or input_space)
        try:  # pragma: no cover - optional features
            baker.setCubeSize(lut_size)
        except Exception:
            pass

        try:
            lut_text = baker.bake()
        except Exception as exc:
            raise ColorPipelineError(f"OCIO LUT bake 실패: {exc}") from exc

        with open(lut_path, "w", encoding="utf-8") as handle:
            handle.write(lut_text)

        return lut_path

    def _metadata_from_view(self, display: str, view: str) -> Dict[str, str]:
        # 간단한 맵핑: 주요 뷰 이름에 따라 tag 결정
        name = f"{display}:{view}".lower()
        if "709" in name:
            return dict(self.FALLBACK_METADATA["Rec.709 SDR"])
        if "srgb" in name:
            return dict(self.FALLBACK_METADATA["sRGB"])
        return {}


def get_cached_manager(config_path: Optional[str]) -> ColorPipelineManager:
    key = (config_path or "__env__").strip()
    manager = _MANAGER_CACHE.get(key)
    if manager is None:
        manager = ColorPipelineManager(config_path)
        _MANAGER_CACHE[key] = manager
    return manager


def build_filters_for_options(options: Dict[str, str]) -> Tuple[List[Tuple[str, Dict[str, str]]], Dict[str, str]]:
    if not options or not options.get("enabled"):
        return [], {}

    manager = get_cached_manager(options.get("config_path"))
    input_space = options.get("input_space") or manager.get_default_io()[0]
    if input_space.lower() == "auto":
        input_space = "Scene Linear (Rec709)"
    display = options.get("output_display") or manager.get_default_io()[1]
    view = options.get("output_view") or manager.get_default_io()[2]
    lut_size = int(options.get("lut_size", DEFAULT_LUT_SIZE))

    filters, metadata = manager.build_filter_chain(input_space, display, view, lut_size)

    # 사용자 정의 메타데이터 override
    metadata_override = options.get("metadata")
    if isinstance(metadata_override, dict):
        metadata.update(metadata_override)

    return filters, metadata


