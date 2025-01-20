# main.py

import sys
import traceback
import logging
from PySide6.QtWidgets import QApplication
from gui import FFmpegGui

# 로깅 설정
logger = logging.getLogger(__name__)

__version__ = '1.1.2'

if __name__ == '__main__':
    try:
        app = QApplication(sys.argv)
        window = FFmpegGui()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        error_message = f"오류가 발생했습니다:\n{str(e)}\n\n트레이스백:\n{traceback.format_exc()}"
        print(error_message)
        input("종료하려면 Enter 키를 누르세요...")