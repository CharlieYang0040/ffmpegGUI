# app/core/ffmpeg_manager.py
import os
import logging
import shutil
import tempfile
import sys
import appdirs

class FFmpegManager:
    """
    FFmpeg 경로 및 실행을 관리하는 싱글톤 클래스
    
    이 클래스는 애플리케이션 전체에서 FFmpeg 경로를 일관되게 관리하고,
    FFmpeg 바이너리의 존재 여부를 확인하며, 필요한 경우 설치합니다.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FFmpegManager, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """싱글톤 인스턴스 초기화"""
        self.logger = logging.getLogger(__name__)
        self.ffmpeg_path = None
        self.ffprobe_path = None
        
        # 앱 데이터 디렉토리 설정
        self.app_name = "ffmpegGUI"
        self.company = "LHCinema"
        self.app_dir = appdirs.user_data_dir(self.app_name, self.company)
        self.ffmpeg_dir = os.path.join(self.app_dir, "ffmpeg")
        
        # 기본 경로 설정
        self.default_ffmpeg_path = os.path.join(self.ffmpeg_dir, "ffmpeg.exe")
        self.default_ffprobe_path = os.path.join(self.ffmpeg_dir, "ffprobe.exe")
        
        self.logger.debug("FFmpegManager 초기화됨")
    
    def set_ffmpeg_path(self, path):
        """
        FFmpeg 경로 설정
        
        Args:
            path (str): FFmpeg 실행 파일 경로
            
        Returns:
            bool: 경로 설정 성공 여부
        """
        self.logger.debug(f"FFmpeg 경로 설정 시도: {path}")
        
        if not path or not os.path.exists(path):
            self.logger.error(f"FFmpeg 경로를 찾을 수 없음: {path}")
            return False
            
        self.ffmpeg_path = path
        self.ffprobe_path = os.path.join(os.path.dirname(path), 'ffprobe.exe')
        
        if not os.path.exists(self.ffprobe_path):
            self.logger.warning(f"FFprobe 경로를 찾을 수 없음: {self.ffprobe_path}")
            return False
            
        self.logger.debug(f"FFmpeg 경로 설정 성공: {self.ffmpeg_path}")
        self.logger.debug(f"FFprobe 경로 설정: {self.ffprobe_path}")
        return True
    
    def get_ffmpeg_path(self):
        """FFmpeg 경로 반환"""
        return self.ffmpeg_path
    
    def get_ffprobe_path(self):
        """FFprobe 경로 반환"""
        return self.ffprobe_path
    
    def ensure_ffmpeg_exists(self):
        """
        FFmpeg 바이너리 존재 확인 및 설치
        
        Returns:
            str: FFmpeg 경로 (성공 시) 또는 빈 문자열 (실패 시)
        """
        # 이미 경로가 설정되어 있고 파일이 존재하는 경우
        if self.ffmpeg_path and os.path.exists(self.ffmpeg_path) and \
           self.ffprobe_path and os.path.exists(self.ffprobe_path):
            self.logger.info("기존 FFmpeg 바이너리 사용")
            return self.ffmpeg_path
            
        # 기본 경로에 파일이 존재하는 경우
        if os.path.exists(self.default_ffmpeg_path) and os.path.exists(self.default_ffprobe_path):
            self.ffmpeg_path = self.default_ffmpeg_path
            self.ffprobe_path = self.default_ffprobe_path
            self.logger.info("기본 경로의 FFmpeg 바이너리 사용")
            return self.ffmpeg_path
            
        # FFmpeg 바이너리 설치 시작
        self.logger.info("FFmpeg 바이너리 설치 시작")
        os.makedirs(self.ffmpeg_dir, exist_ok=True)
        
        # 실행 파일로 패키징된 경우
        if getattr(sys, 'frozen', False):
            meipass_ffmpeg = os.path.join(sys._MEIPASS, "libs", "ffmpeg-7.1-full_build", "bin", "ffmpeg.exe")
            meipass_ffprobe = os.path.join(sys._MEIPASS, "libs", "ffmpeg-7.1-full_build", "bin", "ffprobe.exe")
            
            if os.path.exists(meipass_ffmpeg) and os.path.exists(meipass_ffprobe):
                shutil.copy2(meipass_ffmpeg, self.default_ffmpeg_path)
                shutil.copy2(meipass_ffprobe, self.default_ffprobe_path)
                self.ffmpeg_path = self.default_ffmpeg_path
                self.ffprobe_path = self.default_ffprobe_path
                self.logger.info("FFmpeg 바이너리 설치 완료")
                return self.ffmpeg_path
        else:
            # 개발 환경에서는 libs 폴더에서 복사
            dev_ffmpeg = os.path.join("libs", "ffmpeg-7.1-full_build", "bin", "ffmpeg.exe")
            dev_ffprobe = os.path.join("libs", "ffmpeg-7.1-full_build", "bin", "ffprobe.exe")
            
            if os.path.exists(dev_ffmpeg) and os.path.exists(dev_ffprobe):
                shutil.copy2(dev_ffmpeg, self.default_ffmpeg_path)
                shutil.copy2(dev_ffprobe, self.default_ffprobe_path)
                self.ffmpeg_path = self.default_ffmpeg_path
                self.ffprobe_path = self.default_ffprobe_path
                self.logger.info("FFmpeg 바이너리 설치 완료")
                return self.ffmpeg_path
                
        self.logger.error("FFmpeg 바이너리를 찾을 수 없습니다")
        return ""
    
    def get_version_info(self):
        """
        FFmpeg 버전 정보 반환
        
        Returns:
            dict: FFmpeg 버전 정보
        """
        info = {
            'ffmpeg_path': self.ffmpeg_path or "설정되지 않음",
            'ffprobe_path': self.ffprobe_path or "설정되지 않음"
        }
        
        # FFmpeg 버전 확인 시도
        try:
            import subprocess
            if self.ffmpeg_path and os.path.exists(self.ffmpeg_path):
                result = subprocess.run(
                    [self.ffmpeg_path, '-version'],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    # 첫 번째 줄에서 버전 정보 추출
                    version_line = result.stdout.splitlines()[0]
                    info['ffmpeg_version'] = version_line
                else:
                    info['ffmpeg_version'] = "FFmpeg 버전 확인 실패"
            else:
                info['ffmpeg_version'] = "FFmpeg 경로가 설정되지 않음"
        except Exception as e:
            info['ffmpeg_version'] = f"오류: {str(e)}"
        
        return info
    
    def run_ffmpeg_command(self, args, progress_callback=None):
        """
        FFmpeg 명령 실행
        
        Args:
            args (list): FFmpeg 명령 인수 목록
            progress_callback (callable, optional): 진행률 콜백 함수
            
        Returns:
            tuple: (성공 여부, 출력 메시지)
        """
        if not self.ffmpeg_path:
            return False, "FFmpeg 경로가 설정되지 않았습니다."
            
        try:
            import subprocess
            
            # FFmpeg 경로를 명령 인수 목록의 첫 번째 요소로 설정
            cmd = [self.ffmpeg_path] + args
            
            self.logger.debug(f"FFmpeg 명령 실행: {' '.join(cmd)}")
            
            # 프로세스 실행
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            # 진행률 모니터링
            if progress_callback:
                import re
                for line in process.stderr:
                    self.logger.debug(line.strip())
                    
                    # 진행률 파싱 및 업데이트
                    if "time=" in line:
                        try:
                            time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                            if time_match:
                                time_str = time_match.group(1)
                                h, m, s = map(float, time_str.split(':'))
                                current_seconds = h * 3600 + m * 60 + s
                                # 여기서는 총 시간을 알 수 없으므로 raw 값을 전달
                                progress_callback(current_seconds)
                        except ValueError as e:
                            # 시간 형식이 잘못된 경우 (예: 숫자가 아닌 값)
                            self.logger.warning(f"진행률 파싱 오류 (잘못된 시간 형식): {e}")
                        except Exception as e:
                            self.logger.warning(f"진행률 파싱 오류: {e}")
            
            # 프로세스 완료 대기
            stdout, stderr = process.communicate()
            
            if process.returncode != 0:
                self.logger.error(f"FFmpeg 명령 실패 (반환 코드: {process.returncode})")
                self.logger.error(f"오류 메시지: {stderr}")
                return False, stderr
                
            return True, stdout
            
        except Exception as e:
            self.logger.exception(f"FFmpeg 명령 실행 중 오류 발생: {str(e)}")
            return False, str(e)

    def initialize_ffmpeg(self, ffmpeg_path: str) -> bool:
        """
        FFmpeg 경로를 초기화하고 유효성을 검사합니다.
        
        Args:
            ffmpeg_path: FFmpeg 실행 파일 경로
            
        Returns:
            bool: 초기화 성공 여부
        """
        self.logger.info(f"FFmpeg 초기화 시작: {ffmpeg_path}")
        
        if not os.path.exists(ffmpeg_path):
            self.logger.error(f"FFmpeg 경로가 존재하지 않음: {ffmpeg_path}")
            return False
            
        result = self.set_ffmpeg_path(ffmpeg_path)
        if not result:
            self.logger.error("FFmpeg 경로 설정 실패")
            return False
            
        self.logger.info(f"FFmpeg 초기화 완료. 경로: {self.get_ffmpeg_path()}")
        return True