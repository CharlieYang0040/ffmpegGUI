"""FFmpegGUI application entry point."""

import sys
import traceback

from PySide6.QtWidgets import QApplication

from app.core.ffmpeg_manager import FFmpegManager
from app.services.logging_service import LoggingService
from app.services.settings_service import SettingsService
from app.ui.main_window import FFmpegGui
from app.utils.ffmpeg_utils import __version__


def setup_services():
    """Initialize non-UI services. FFmpeg download is handled by the GUI worker."""
    logging_service = LoggingService()

    try:
        logging_service.setup_file_logging()
    except Exception as e:
        print(f"로그 파일 설정 중 오류 발생: {e}")

    logger = logging_service.get_logger(__name__)
    settings_service = SettingsService()

    debug_mode = settings_service.get_debug_mode()
    logging_service.set_debug_mode(debug_mode)

    ffmpeg_manager = FFmpegManager()
    ffmpeg_path = ffmpeg_manager.find_existing_ffmpeg(settings_service.get_ffmpeg_path())
    if ffmpeg_path:
        settings_service.set_ffmpeg_path(ffmpeg_path)
        settings_service.sync()
    else:
        logger.warning("FFmpeg를 아직 찾지 못했습니다. GUI에서 자동 다운로드를 시도합니다.")

    logger.info(f"FFmpegGUI 버전 {__version__} 시작")
    return True


def main():
    try:
        if not setup_services():
            print("서비스 초기화에 실패했습니다. 프로그램을 종료합니다.")
            return 1

        app = QApplication(sys.argv)
        app.setApplicationName("ffmpegGUI")
        app.setOrganizationName("LHCinema")

        window = FFmpegGui()
        window.show()

        logging_service = LoggingService()
        logging_service.setup_crash_handler()

        return app.exec()
    except Exception as e:
        error_message = f"오류가 발생했습니다:\n{str(e)}\n\n트레이스백:\n{traceback.format_exc()}"
        print(error_message)

        try:
            logging_service = LoggingService()
            logger = logging_service.get_logger(__name__)
            logger.critical(f"치명적 오류: {str(e)}", exc_info=True)
        except Exception:
            pass

        return 1


if __name__ == "__main__":
    sys.exit(main())
