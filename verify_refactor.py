import sys
import os
import logging

# Add project root to path
sys.path.append(os.getcwd())

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("Verification")

def verify_imports():
    try:
        logger.info("Verifying ConfigManager...")
        from config_manager import config_manager
        print(f"FFmpeg Path: {config_manager.get_ffmpeg_path()}")
        
        logger.info("Verifying UI Dialogs...")
        from ui.dialogs import ColorOptionsDialog, EncodingProgressDialog
        
        logger.info("Verifying Core Builder...")
        from core.ffmpeg_builder import FFmpegCommandBuilder
        
        logger.info("Verifying GUI Import...")
        from gui import FFmpegGui
        
        logger.info("All imports successful!")
        return True
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    if verify_imports():
        sys.exit(0)
    else:
        sys.exit(1)
