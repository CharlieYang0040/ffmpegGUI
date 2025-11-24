import logging
import os
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QPixmap

from utils import is_image_file, get_first_sequence_file
from video_thread import load_image_preview_pixmap, load_video_preview_pixmap

logger = logging.getLogger(__name__)


class PreviewWorkerSignals(QObject):
    finished = Signal(int, str, object)


class PreviewWorker(QRunnable):
    def __init__(self, request_id: int, file_path: str, target_width: int, target_height: int):
        super().__init__()
        self.request_id = request_id
        self.file_path = file_path
        self.target_width = target_width
        self.target_height = target_height
        self.signals = PreviewWorkerSignals()

    def run(self):
        pixmap: Optional[QPixmap] = None
        try:
            actual_path = self._resolve_actual_path(self.file_path)
            if actual_path and os.path.exists(actual_path) and is_image_file(actual_path):
                pixmap = load_image_preview_pixmap(actual_path, self.target_width, self.target_height)
            else:
                pixmap = load_video_preview_pixmap(self.file_path, self.target_width, self.target_height)
        except Exception as exc:  # pragma: no cover - 방어적 로깅
            logger.warning("미리보기 로드 실패(%s): %s", self.file_path, exc)
            pixmap = None
        self.signals.finished.emit(self.request_id, self.file_path, pixmap)

    def _resolve_actual_path(self, path: str) -> str:
        if '%' in path:
            first_file = get_first_sequence_file(path)
            if first_file:
                return first_file
        return path

