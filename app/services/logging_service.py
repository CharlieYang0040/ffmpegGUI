# app/services/logging_service.py
import logging
import os
import sys
import traceback
import datetime

class LoggingService:
    """
    애플리케이션 로깅을 관리하는 싱글톤 클래스
    
    이 클래스는 애플리케이션 전체에서 일관된 로깅 설정을 제공합니다.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LoggingService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """싱글톤 인스턴스 초기화"""
        self.loggers = {}
        self.formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        
        # 콘솔 핸들러 설정
        self.console_handler = logging.StreamHandler()
        self.console_handler.setFormatter(self.formatter)
        
        # 파일 핸들러 설정 (선택적)
        self.file_handler = None
        self.log_file_path = None
        
        # 기본 로그 레벨 설정
        self.default_level = logging.INFO
        
        print("LoggingService 초기화됨")
    
    def setup_file_logging(self, log_dir=None):
        """
        파일 로깅 설정
        
        Args:
            log_dir (str, optional): 로그 파일 디렉토리
        """
        if not log_dir:
            # 기본 로그 디렉토리 설정
            if getattr(sys, 'frozen', False):
                # 실행 파일로 패키징된 경우
                base_dir = os.path.dirname(sys.executable)
            else:
                # 개발 환경인 경우
                base_dir = os.path.dirname(os.path.abspath(__file__))
                base_dir = os.path.dirname(os.path.dirname(base_dir))  # app/services -> app -> project root
            
            log_dir = os.path.join(base_dir, 'logs')
        
        # 로그 디렉토리 생성
        os.makedirs(log_dir, exist_ok=True)
        
        # 로그 파일 경로 설정
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file_path = os.path.join(log_dir, f'ffmpegGUI_{timestamp}.log')
        
        # 파일 핸들러 설정
        self.file_handler = logging.FileHandler(self.log_file_path, encoding='utf-8')
        self.file_handler.setFormatter(self.formatter)
        
        # 기존 로거에 파일 핸들러 추가
        for logger in self.loggers.values():
            logger.addHandler(self.file_handler)
        
        print(f"파일 로깅 설정 완료: {self.log_file_path}")
    
    def get_logger(self, name):
        """
        로거 가져오기
        
        Args:
            name (str): 로거 이름
            
        Returns:
            logging.Logger: 로거 인스턴스
        """
        if name not in self.loggers:
            logger = logging.getLogger(name)
            logger.setLevel(self.default_level)
            logger.addHandler(self.console_handler)
            
            # 파일 핸들러가 설정된 경우 추가
            if self.file_handler:
                logger.addHandler(self.file_handler)
                
            # 상위 로거로 전파하지 않음
            logger.propagate = False
            
            self.loggers[name] = logger
        
        return self.loggers[name]
    
    def set_level(self, level):
        """
        모든 로거의 로그 레벨 설정
        
        Args:
            level: 로그 레벨 (logging.DEBUG, logging.INFO 등)
        """
        self.default_level = level
        for logger in self.loggers.values():
            logger.setLevel(level)
    
    def set_debug_mode(self, enabled):
        """
        디버그 모드 설정
        
        Args:
            enabled (bool): 디버그 모드 활성화 여부
        """
        level = logging.DEBUG if enabled else logging.INFO
        self.set_level(level)

    def setup_crash_handler(self):
        """충돌 시 로그 기록을 위한 핸들러 설정"""
        def exception_handler(exc_type, exc_value, exc_traceback):
            """예외 처리 핸들러"""
            # 기본 예외 처리기 호출 방지
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            
            # 로그에 예외 정보 기록
            logger = self.get_logger("crash_handler")
            logger.critical("미처리 예외 발생:", exc_info=(exc_type, exc_value, exc_traceback))
            
            # 예외 정보를 파일에 기록
            try:
                with open("crash_log.txt", "a", encoding="utf-8") as f:
                    f.write("\n\n===== 애플리케이션 충돌 =====\n")
                    f.write(f"시간: {datetime.datetime.now()}\n")
                    f.write("예외 정보:\n")
                    traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
                    f.write("========================\n")
            except:
                pass
        
        # 전역 예외 핸들러 설정
        sys.excepthook = exception_handler