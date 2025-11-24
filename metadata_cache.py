import glob
import os
import re
import threading
from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, Optional, Tuple, List

import ffmpeg
import logging


logger = logging.getLogger(__name__)

FFPROBE_PATH: Optional[str] = None


def set_ffprobe_path(path: str):
    """
    외부에서 FFprobe 경로를 설정할 수 있도록 하는 헬퍼.
    """
    global FFPROBE_PATH
    if path:
        FFPROBE_PATH = path
    else:
        FFPROBE_PATH = None
    logger.debug("metadata_cache FFPROBE_PATH=%s", FFPROBE_PATH)


@dataclass
class MediaMetadata:
    width: int = 0
    height: int = 0
    fps: float = 0.0
    duration: float = 0.0
    total_frames: int = 0
    sequence_start: int = 0
    sequence_end: int = 0
    is_sequence: bool = False


class MetadataCache:
    """
    FFprobe/파일 시스템 메타데이터를 재사용하기 위한 간단한 캐시.
    파일의 크기/수정시간 혹은 시퀀스의 길이/경계가 바뀌면 자동 무효화된다.
    """

    _SEQ_PATTERN = re.compile(r'%\d*d', re.IGNORECASE)
    _FRAME_NUMBER_PATTERN = re.compile(r'(\d+)(?=\.[^.]+$)')

    def __init__(self):
        self._cache: Dict[str, Tuple[Tuple, MediaMetadata]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def get(self, path: str) -> MediaMetadata:
        """
        주어진 경로(비디오 파일 또는 시퀀스 패턴)의 메타데이터를 반환.
        캐시에 없거나 무효화된 경우 새로 계산한다.
        """
        normalized = os.path.abspath(path)
        signature = self._build_signature(normalized)

        with self._lock:
            cached = self._cache.get(normalized)
            if cached and cached[0] == signature:
                return cached[1]

        metadata = self._probe_metadata(normalized)

        with self._lock:
            self._cache[normalized] = (signature, metadata)

        return metadata

    def invalidate(self, path: Optional[str] = None):
        with self._lock:
            if path:
                normalized = os.path.abspath(path)
                self._cache.pop(normalized, None)
            else:
                self._cache.clear()

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _is_sequence(self, path: str) -> bool:
        return '%' in path or bool(self._SEQ_PATTERN.search(path))

    def _expand_sequence(self, path: str) -> List[str]:
        pattern = path.replace('\\', '/')
        glob_pattern = self._SEQ_PATTERN.sub('*', pattern)
        files = sorted(glob.glob(glob_pattern))
        return files

    def _build_signature(self, path: str) -> Tuple:
        if self._is_sequence(path):
            files = self._expand_sequence(path)
            if not files:
                return (path, 0, 0, 0)
            count = len(files)
            first = files[0]
            last = files[-1]
            first_stat = os.stat(first)
            last_stat = os.stat(last)
            return (
                path,
                count,
                int(first_stat.st_mtime),
                int(last_stat.st_mtime),
                int(last_stat.st_size),
            )

        try:
            stat_result = os.stat(path)
            return (
                int(stat_result.st_mtime),
                int(stat_result.st_size),
            )
        except FileNotFoundError:
            return (path, 0, 0)

    def _probe_metadata(self, path: str) -> MediaMetadata:
        if self._is_sequence(path):
            return self._probe_sequence_metadata(path)
        return self._probe_video_metadata(path)

    # ------------------------------------------------------------------ #
    # Sequence probing
    # ------------------------------------------------------------------ #
    def _probe_sequence_metadata(self, path: str) -> MediaMetadata:
        files = self._expand_sequence(path)
        if not files:
            return MediaMetadata(is_sequence=True)

        total_frames = len(files)
        first_file = files[0]
        last_file = files[-1]

        width, height = self._probe_image_resolution(first_file)
        start_frame = self._extract_frame_number(first_file)
        end_frame = self._extract_frame_number(last_file)

        if start_frame is None:
            start_frame = 0
        if end_frame is None:
            end_frame = total_frames if start_frame == 0 else start_frame + total_frames - 1

        fps = 30.0  # GUI 기본 프레임레이트 정책과 일치
        duration = total_frames / fps if fps > 0 else 0.0

        return MediaMetadata(
            width=width,
            height=height,
            fps=fps,
            duration=duration,
            total_frames=total_frames,
            sequence_start=start_frame,
            sequence_end=end_frame,
            is_sequence=True,
        )

    def _probe_image_resolution(self, path: str) -> Tuple[int, int]:
        try:
            probe = ffmpeg.probe(path, cmd=FFPROBE_PATH)
            stream = next(
                (s for s in probe.get('streams', []) if s.get('codec_type') == 'video'),
                None,
            )
            if stream:
                return int(stream.get('width', 0)), int(stream.get('height', 0))
        except Exception as exc:  # pragma: no cover - 보호적 로깅
            logger.debug("이미지 해상도 프로브 실패 (%s): %s", path, exc)
        return 0, 0

    def _extract_frame_number(self, file_path: str) -> Optional[int]:
        match = self._FRAME_NUMBER_PATTERN.search(os.path.basename(file_path))
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
        return None

    # ------------------------------------------------------------------ #
    # Video probing
    # ------------------------------------------------------------------ #
    def _probe_video_metadata(self, path: str) -> MediaMetadata:
        try:
            probe = ffmpeg.probe(path, cmd=FFPROBE_PATH)
        except ffmpeg.Error as exc:
            logger.warning("FFprobe 실패 (%s): %s", path, exc.stderr.decode(errors='ignore') if exc.stderr else exc)
            return MediaMetadata()
        except FileNotFoundError:
            logger.warning("FFprobe 대상 파일을 찾을 수 없습니다: %s", path)
            return MediaMetadata()

        video_stream = next(
            (s for s in probe.get('streams', []) if s.get('codec_type') == 'video'),
            None,
        )
        if not video_stream:
            logger.warning("비디오 스트림을 찾지 못했습니다: %s", path)
            return MediaMetadata()

        width = int(video_stream.get('width') or 0)
        height = int(video_stream.get('height') or 0)
        fps = self._parse_fps(video_stream.get('r_frame_rate'))

        nb_frames = video_stream.get('nb_frames')
        duration = float(video_stream.get('duration') or probe.get('format', {}).get('duration') or 0.0)
        if nb_frames:
            try:
                total_frames = int(nb_frames)
            except ValueError:
                total_frames = int(float(nb_frames))
        elif duration and fps:
            total_frames = int(duration * fps)
        else:
            total_frames = 0

        return MediaMetadata(
            width=width,
            height=height,
            fps=fps,
            duration=duration,
            total_frames=total_frames,
            sequence_start=0,
            sequence_end=total_frames,
            is_sequence=False,
        )

    def _parse_fps(self, fps_value: Optional[str]) -> float:
        if not fps_value:
            return 0.0
        try:
            if '/' in fps_value:
                return float(Fraction(fps_value))
            return float(fps_value)
        except Exception:
            try:
                return float(eval(fps_value))  # pragma: no cover - 기존 문자열 호환
            except Exception:
                return 0.0


metadata_cache = MetadataCache()


