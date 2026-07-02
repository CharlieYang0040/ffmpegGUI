from PySide6.QtCore import QThread, Signal

from app.core.events import event_emitter, Events
from app.core.job_builder import detect_media_type, validate_encoding_job
from app.core.models import (
    CancellationToken,
    EncodingJob,
    EncodingOptions,
    EncodingProgressStage,
    EncodingProgressState,
    FrameTrim,
    MediaItem,
)
from app.services.logging_service import LoggingService
from app.utils.ffmpeg_utils import FFmpegUtils

logger = LoggingService().get_logger(__name__)


class EncodingThread(QThread):
    """Run an encoding job on a worker thread."""

    progress_updated = Signal(int)
    task_updated = Signal(str)
    progress_state_updated = Signal(object)
    encoding_finished = Signal()
    encoding_error = Signal(str)

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.args = args
        self.kwargs = kwargs
        self.job = self.kwargs.pop("job", None)
        self.cancel_token = self.kwargs.pop("cancel_token", None) or CancellationToken()
        self.ffmpeg_utils = FFmpegUtils()
        self.listeners_registered = False
        self._last_progress = 0
        self._last_stage = EncodingProgressStage.IDLE
        self.register_event_listeners()
        self.finished.connect(self.unregister_event_listeners)

    def __del__(self):
        self.unregister_event_listeners()

    def cancel(self):
        self.cancel_token.cancel()

    def register_event_listeners(self):
        if not self.listeners_registered:
            self.unregister_event_listeners()
            event_emitter.on(Events.PROCESS_PROGRESS, self.on_progress)
            event_emitter.on(Events.PROCESS_COMPLETED, self.on_complete)
            event_emitter.on(Events.PROCESS_ERROR, self.on_error)
            self.listeners_registered = True
            logger.debug("인코딩 스레드 이벤트 리스너 등록됨")

    def unregister_event_listeners(self):
        if self.listeners_registered:
            event_emitter.off(Events.PROCESS_PROGRESS, self.on_progress)
            event_emitter.off(Events.PROCESS_COMPLETED, self.on_complete)
            event_emitter.off(Events.PROCESS_ERROR, self.on_error)
            self.listeners_registered = False
            logger.debug("인코딩 스레드 이벤트 리스너 제거됨")

    def on_progress(self, progress):
        self._last_progress = progress
        self.progress_updated.emit(progress)
        self._emit_state(self._last_stage, progress, "")

    def on_complete(self, output_file):
        self.progress_updated.emit(100)
        self.task_updated.emit(f"인코딩 완료: {output_file}")
        self._emit_state(EncodingProgressStage.COMPLETED, 100, f"인코딩 완료: {output_file}")
        self.encoding_finished.emit()

    def on_error(self, error_message):
        stage = EncodingProgressStage.CANCELLED if "취소" in error_message else EncodingProgressStage.FAILED
        self._emit_state(stage, self._last_progress, error_message)
        self.encoding_error.emit(error_message)

    def _coerce_frame_value(self, value) -> int:
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    def _build_legacy_job(self) -> EncodingJob:
        media_files = self.kwargs.pop("media_files", self.args[0] if self.args else [])
        output_file = self.kwargs.pop("output_file", self.args[1] if len(self.args) > 1 else "")
        encoding_options = dict(self.kwargs.pop("encoding_options", self.args[2] if len(self.args) > 2 else {}) or {})
        use_frame_based_trim = self.kwargs.pop("use_frame_based_trim", False)
        debug_mode = self.kwargs.pop("debug_mode", False)
        global_trim_start = self.kwargs.pop("global_trim_start", 0)
        global_trim_end = self.kwargs.pop("global_trim_end", 0)

        if self.kwargs.pop("use_custom_framerate", False):
            encoding_options["r"] = str(self.kwargs.pop("custom_framerate", 30.0))
        if self.kwargs.pop("use_custom_resolution", False):
            custom_width = self.kwargs.pop("custom_width", 0)
            custom_height = self.kwargs.pop("custom_height", 0)
            if custom_width and custom_height:
                encoding_options["s"] = f"{custom_width}x{custom_height}"

        media_items = []
        for file_path, trim_start, trim_end in media_files:
            media_items.append(
                MediaItem(
                    source_path=file_path,
                    media_type=detect_media_type(file_path),
                    trim=FrameTrim(self._coerce_frame_value(trim_start), self._coerce_frame_value(trim_end)),
                )
            )

        return EncodingJob(
            media_items=media_items,
            output_file=output_file,
            options=EncodingOptions(
                ffmpeg_options=encoding_options,
                global_trim=FrameTrim(global_trim_start, global_trim_end),
                debug_mode=debug_mode,
                use_frame_based_trim=use_frame_based_trim,
            ),
        )

    def _get_job(self) -> EncodingJob:
        if self.job is not None:
            return self.job
        if self.args and isinstance(self.args[0], EncodingJob):
            return self.args[0]
        return self._build_legacy_job()

    def _stage_for_task(self, task: str) -> EncodingProgressStage:
        if "병합" in task:
            return EncodingProgressStage.MERGING
        if "처리" in task or "WebP" in task or "파일" in task:
            return EncodingProgressStage.PROCESSING
        return EncodingProgressStage.PREPARING

    def _emit_state(self, stage, progress, message):
        self._last_stage = stage
        self.progress_state_updated.emit(EncodingProgressState(stage=stage, progress=progress, message=message))

    def run(self):
        try:
            self.cancel_token.throw_if_cancelled()
            self.task_updated.emit("인코딩 준비 중...")
            self._emit_state(EncodingProgressStage.PREPARING, 0, "인코딩 준비 중...")

            def progress_callback(progress):
                self.cancel_token.throw_if_cancelled()
                event_emitter.emit(Events.PROCESS_PROGRESS, progress)

            def task_callback(task):
                self.cancel_token.throw_if_cancelled()
                self.task_updated.emit(task)
                self._emit_state(self._stage_for_task(task), self._last_progress, task)

            job = self._get_job()
            validate_encoding_job(job)
            result = self.ffmpeg_utils.process_encoding_job(
                job,
                progress_callback=progress_callback,
                task_callback=task_callback,
                cancel_token=self.cancel_token,
            )
            event_emitter.emit(Events.PROCESS_COMPLETED, result)
        except Exception as e:
            error_message = "작업이 취소되었습니다." if self.cancel_token.is_cancelled else str(e)
            logger.error("인코딩 오류: %s", error_message)
            event_emitter.emit(Events.PROCESS_ERROR, error_message)
