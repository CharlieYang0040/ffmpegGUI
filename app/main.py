# app/main.py
"""
FFmpegGUI 애플리케이션 진입점
"""
import sys
import traceback
from PySide6.QtWidgets import QApplication

# 서비스 초기화
from app.services.logging_service import LoggingService
from app.services.settings_service import SettingsService
from app.core.ffmpeg_manager import FFmpegManager

# 메인 윈도우 가져오기
from app.ui.main_window import FFmpegGui

# 버전 정보
from app.utils.ffmpeg_utils import __version__

def setup_services():
    """서비스 초기화"""
    # 로깅 서비스 초기화
    logging_service = LoggingService()
    logger = logging_service.get_logger(__name__)
    
    # 설정 서비스 초기화
    settings_service = SettingsService()
    
    # 디버그 모드 설정
    debug_mode = settings_service.get_debug_mode()
    logging_service.set_debug_mode(debug_mode)
    
    # FFmpeg 매니저 초기화
    ffmpeg_manager = FFmpegManager()
    ffmpeg_path = settings_service.get_ffmpeg_path()
    
    if ffmpeg_path:
        if not ffmpeg_manager.set_ffmpeg_path(ffmpeg_path):
            logger.warning(f"저장된 FFmpeg 경로를 사용할 수 없습니다: {ffmpeg_path}")
            ffmpeg_path = ffmpeg_manager.ensure_ffmpeg_exists()
            if ffmpeg_path:
                settings_service.set_ffmpeg_path(ffmpeg_path)
    else:
        ffmpeg_path = ffmpeg_manager.ensure_ffmpeg_exists()
        if ffmpeg_path:
            settings_service.set_ffmpeg_path(ffmpeg_path)
    
    if not ffmpeg_path:
        logger.error("FFmpeg를 찾을 수 없습니다.")
        return False
    
    logger.info(f"FFmpegGUI 버전 {__version__} 시작")
    return True

def main():
    """애플리케이션 메인 함수"""
    try:
        # 서비스 초기화
        if not setup_services():
            print("FFmpeg를 찾을 수 없습니다. 프로그램을 종료합니다.")
            return 1
        
        # Qt 애플리케이션 생성
        app = QApplication(sys.argv)
        app.setApplicationName("ffmpegGUI")
        app.setOrganizationName("LHCinema")
        
        # 메인 윈도우 생성 및 표시
        window = FFmpegGui()
        window.show()
        
        # 애플리케이션 실행
        return app.exec()
        
    except Exception as e:
        error_message = f"오류가 발생했습니다:\n{str(e)}\n\n트레이스백:\n{traceback.format_exc()}"
        print(error_message)
        
        # 로그 파일에 오류 기록
        try:
            logging_service = LoggingService()
            logger = logging_service.get_logger(__name__)
            logger.critical(f"치명적 오류: {str(e)}", exc_info=True)
        except:
            pass
            
        return 1

if __name__ == "__main__":
    sys.exit(main())