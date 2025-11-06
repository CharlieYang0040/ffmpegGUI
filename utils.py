# utils.py

import logging
import os
import re
import glob
from collections import defaultdict
from typing import Dict
from PySide6.QtCore import QSettings
import appdirs
import shutil
import sys
import ffmpeg

# FFprobe 경로를 위한 전역 변수
FFPROBE_PATH = None

def set_ffprobe_path(path: str):
    """FFprobe 경로를 설정합니다."""
    global FFPROBE_PATH
    FFPROBE_PATH = path
    logger.info(f"utils.py에 FFprobe 경로 설정: {FFPROBE_PATH}")

def is_image_sequence(input_file: str) -> bool:
    """
    입력 파일이 이미지 시퀀스인지 확인합니다.
    """
    return '%' in input_file or re.search(r'%\d*d', input_file) is not None

# 설정에서 디버그 모드 상태 로드
settings = QSettings('LHCinema', 'ffmpegGUI')
DEBUG_MODE = settings.value('debug_mode', False, type=bool)

# 로깅 설정
logger = logging.getLogger(__name__)

def get_debug_mode():
    """현재 디버그 모드 상태 반환"""
    return DEBUG_MODE

def set_debug_mode(value: bool):
    """디버그 모드 설정 및 저장"""
    global DEBUG_MODE
    DEBUG_MODE = value
    settings.setValue('debug_mode', value)
    logger.info(f"DEBUG_MODE 설정됨: {DEBUG_MODE}")
    return DEBUG_MODE

def set_logger_level(is_debug: bool):
    """모든 관련 모듈의 로거 레벨을 설정합니다."""
    import logging
    
    # 기본 로그 포맷 설정
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 콘솔 핸들러 설정
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # 모든 관련 모듈의 로거를 가져옵니다
    loggers = [
        logging.getLogger('__main__'),  # 메인 모듈
        logging.getLogger('video_thread'),  # video_thread.py
        logging.getLogger('ffmpeg_utils'),  # ffmpeg_utils.py
        logging.getLogger('drag_drop_list_widget'),  # drag_drop_list_widget.py
        logging.getLogger('commands'),  # commands.py
        logging.getLogger('droppable_line_edit'),  # droppable_line_edit.py
        logging.getLogger('update'),  # update.py
        logging.getLogger('gui'),  # gui.py
        logging.getLogger('utils')  # utils.py
    ]
    
    level = logging.DEBUG if is_debug else logging.INFO
    for logger in loggers:
        # 기존 핸들러 제거
        logger.handlers.clear()
        # 새로운 핸들러 추가
        logger.addHandler(console_handler)
        logger.setLevel(level)
        # 상위 로거로 전파하지 않음
        logger.propagate = False

def is_media_file(file_path):
    _, ext = os.path.splitext(file_path)
    return ext.lower() in ['.mp4', '.avi', '.mov', '.mkv', '.jpg', '.jpeg', '.png', '.bmp', '.exr']

def is_image_file(file_path):
    _, ext = os.path.splitext(file_path)
    return ext.lower() in ['.jpg', '.jpeg', '.png', '.bmp', '.exr']

def is_video_file(file_path):
    _, ext = os.path.splitext(file_path)
    return ext.lower() in ['.mp4', '.avi', '.mov', '.mkv']

def parse_image_filename(file_name):
    base, ext = os.path.splitext(file_name)
    match = re.search(r'(\d+)$', base)
    if match:
        frame = match.group(1)
        base = base[:-len(frame)]
        return base, frame, ext
    return base, None, ext

def process_image_sequences(files):
    sequences = defaultdict(list)
    processed_files = []

    for file_path in files:
        if is_image_file(file_path):
            dir_path, filename = os.path.split(file_path)
            base, frame, ext = parse_image_filename(filename)
            if frame is not None:
                sequence_key = os.path.join(dir_path, f"{base}%0{len(frame)}d{ext}")
                sequences[sequence_key].append((int(frame), file_path))
                logger.debug(f"이미지 시퀀스 발견: {sequence_key}")
            else:
                processed_files.append(file_path)
        else:
            processed_files.append(file_path)

    for sequence, frame_files in sequences.items():
        if len(frame_files) > 1:
            processed_files.append(sequence)
            logger.info(f"이미지 시퀀스 처리 완료: {sequence} ({len(frame_files)}개 파일)")
        else:
            processed_files.append(frame_files[0][1])

    return processed_files

def process_file(file_path):
    _, ext = os.path.splitext(file_path)
    return process_image_file(file_path) if ext.lower() in ['.jpg', '.jpeg', '.png', '.exr'] else file_path

_OPENEXR_IMPORT_FAILED = False


def process_image_file(file_path):
    dir_path, file_name = os.path.split(file_path)
    base_name, ext = os.path.splitext(file_name)

    logger.debug(f"처리 중인 이미지 파일: {file_path}")
    logger.debug(f"파일 이름에서 숫자 부분 검색 중: {base_name}")
    
    # 파일명에서 연속된 숫자 구간 중 '마지막' 구간(프레임 번호)을 사용
    matches = list(re.finditer(r'(\d+)', base_name))
    if matches:
        last_match = matches[-1]
        number_part = last_match.group(1)
        logger.debug(f"찾은 숫자 부분: {number_part}")
        prefix = base_name[:last_match.start()]  # 숫자 앞부분
        suffix = base_name[last_match.end():]    # 숫자 뒷부분(있을 수도 있음)
        logger.debug(f"프리픽스: {prefix}")
        if suffix:
            logger.debug(f"서픽스: {suffix}")
        
        # 특수문자를 포함한 파일명에 대응하기 위해 re.escape 사용
        pattern = f"^{re.escape(prefix)}[0-9]+{re.escape(suffix)}{re.escape(ext)}$"
        logger.debug(f"검색 패턴: {pattern}")
        
        try:
            # glob을 사용하여 네트워크 경로에서도 파일 검색
            search_path = os.path.join(dir_path, f"{prefix}*{suffix}{ext}")
            matching_files = [os.path.basename(f) for f in glob.glob(search_path)]
            matching_files = [f for f in matching_files if re.match(pattern, f)]
            logger.debug(f"일치하는 파일 목록: {matching_files}")
            
            if len(matching_files) > 1:
                logger.info(f"이미지 시퀀스 발견: {prefix}%0{len(number_part)}d{suffix}{ext}")
                return os.path.join(dir_path, f"{prefix}%0{len(number_part)}d{suffix}{ext}")
                
        except Exception as e:
            logger.error(f"파일 검색 중 오류 발생: {str(e)}")
    else:
        logger.warning(f"숫자 부분을 찾지 못했습니다: {base_name}")

    logger.warning(f"이미지 파일 처리 실패: {file_path}")
    return file_path


def _sanitize_metadata_key(key: str) -> str:
    sanitized = re.sub(r'[^A-Za-z0-9_.-]', '_', key)
    return sanitized or 'metadata'


def _stringify_exr_attribute(value) -> str:
    try:
        if isinstance(value, bytes):
            try:
                return value.decode('utf-8')
            except UnicodeDecodeError:
                return value.hex()
        return str(value)
    except Exception as exc:  # pragma: no cover - 보호적 캐치
        logger.warning(f"EXR 메타데이터 값을 문자열로 변환하는 중 오류: {exc}")
        return ''


def extract_exr_metadata(file_path: str) -> Dict[str, str]:
    """EXR 파일의 Unreal 관련 메타데이터를 추출하여 딕셔너리로 반환."""
    global _OPENEXR_IMPORT_FAILED

    metadata: Dict[str, str] = {}

    try:
        if _OPENEXR_IMPORT_FAILED:
            return metadata

        import OpenEXR  # type: ignore
        import Imath  # type: ignore
        _ = Imath  # noqa: F841 - 사용 여부 확인용
    except ImportError:
        if not _OPENEXR_IMPORT_FAILED:
            logger.warning("OpenEXR 라이브러리를 찾을 수 없어 EXR 메타데이터를 추출하지 못했습니다. 'pip install OpenEXR Imath'로 설치할 수 있습니다.")
            _OPENEXR_IMPORT_FAILED = True
        return metadata

    exr_file = None
    try:
        exr_file = OpenEXR.InputFile(file_path)
        header = exr_file.header()
    except Exception as exc:
        logger.error(f"EXR 메타데이터를 읽는 중 오류 발생 ({file_path}): {exc}")
        return metadata
    finally:
        if exr_file:
            try:
                exr_file.close()
            except Exception:
                pass

    seen_keys = set()
    for key, value in header.items():
        if not key.lower().startswith('unreal'):
            continue

        sanitized_key = _sanitize_metadata_key(key)
        base_key = sanitized_key
        suffix = 1
        while sanitized_key.lower() in seen_keys:
            sanitized_key = f"{base_key}_{suffix}"
            suffix += 1

        seen_keys.add(sanitized_key.lower())
        metadata[sanitized_key] = _stringify_exr_attribute(value)

    if metadata:
        logger.info(f"EXR 메타데이터 추출 완료 ({file_path}): {list(metadata.keys())}")
    else:
        logger.debug(f"EXR 메타데이터가 발견되지 않았습니다 ({file_path}).")

    return metadata

def get_sequence_start_number(sequence_path):
    dir_path, filename = os.path.split(sequence_path)
    base, ext = os.path.splitext(filename)
    # %0Nd 전폭 패턴을 일반화하여 처리
    pattern = re.sub(r'%\d*d', r'(\\d+)', base)

    files = os.listdir(dir_path)
    frame_numbers = []

    for file in files:
        match = re.match(pattern + ext, file)
        if match:
            frame_numbers.append(int(match.group(1)))

    if frame_numbers:
        return min(frame_numbers)
    return None

def get_first_sequence_file(sequence_pattern):
    # %0Nd 전폭 패턴을 일반화하여 처리
    pattern = re.sub(r'%\d*d', '*', sequence_pattern)
    files = sorted(glob.glob(pattern))
    return files[0] if files else ""

def format_drag_to_output(file_path):
    logger.info(f"드래그 출력 형식 변환: {file_path}")

    dir_path, filename = os.path.split(file_path)
    base_name = os.path.splitext(filename)[0]
    base_name = re.sub(r'%\d*d', '', base_name)
    base_name = base_name.rstrip('.')
    
    logger.info(f"변환된 출력 이름: {base_name}")
    return base_name

def normalize_path_separator(path):
    return path.replace('\\', '/')

def get_frame_range_from_sequence(sequence_path: str) -> (int, int):
    """이미지 시퀀스 경로에서 실제 시작과 끝 프레임 번호를 추출합니다."""
    if not is_image_sequence(sequence_path):
        return 0, 0

    try:
        pattern = sequence_path.replace('\\', '/')
        glob_pattern = re.sub(r'%\d*d', '*', pattern)
        files = glob.glob(glob_pattern)

        if not files:
            return 0, 0

        frame_numbers = []
        # 파일 이름에서 숫자 부분을 추출하기 위한 정규식 재구성
        # 예: "shot.%04d.exr" -> "shot.(\\d+).exr"
        regex_pattern_str = re.sub(r'%\d*d', r'(\\d+)', os.path.basename(pattern))
        regex_pattern = re.compile(regex_pattern_str)

        for f in files:
            match = regex_pattern.search(os.path.basename(f))
            if match:
                frame_numbers.append(int(match.group(1)))

        if frame_numbers:
            return min(frame_numbers), max(frame_numbers)
        
    except Exception as e:
        logger.error(f"시퀀스 프레임 범위 분석 중 오류 발생: {e}")

    return 0, 0


def get_total_frames(file_path: str) -> int:
    """미디어 파일의 총 프레임 수를 반환합니다."""
    try:
        if is_image_sequence(file_path):
            pattern = file_path.replace('\\', '/')
            glob_pattern = re.sub(r'%\d*d', '*', pattern)
            image_files = glob.glob(glob_pattern)
            return len(image_files)
        else:
            probe = ffmpeg.probe(file_path, cmd=FFPROBE_PATH)
            video_info = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
            if video_info and 'nb_frames' in video_info:
                total_frames = int(video_info['nb_frames'])
                if total_frames > 0:
                    return total_frames

            # nb_frames가 없거나 0인 경우 duration과 framerate로 계산
            if video_info and 'duration' in video_info and 'r_frame_rate' in video_info:
                duration = float(video_info['duration'])
                fps = eval(video_info['r_frame_rate'])
                return int(duration * fps)

            # 스트림 정보에도 없을 경우 format 정보 확인
            if 'format' in probe and 'duration' in probe['format']:
                 duration = float(probe['format']['duration'])
                 # 비디오 스트림이 있다면 프레임레이트 가져오기
                 fps = 30 # 기본값
                 if video_info and 'r_frame_rate' in video_info:
                     fps = eval(video_info['r_frame_rate'])
                 return int(duration * fps)

    except (ffmpeg.Error, StopIteration, FileNotFoundError) as e:
        logger.error(f"'{file_path}'의 총 프레임 수를 가져오는 중 오류 발생: {e}")
    except Exception as e:
        logger.exception(f"'{file_path}'의 총 프레임 수를 가져오는 중 예외 발생: {e}")

    return 0 # 오류 발생 시 0 반환


class FFmpegManager:
    def __init__(self):
        self.app_name = "ffmpegGUI"
        self.company = "LHCinema"
        # 사용자 앱 데이터 디렉토리 사용
        self.app_dir = appdirs.user_data_dir(self.app_name, self.company)
        self.ffmpeg_dir = os.path.join(self.app_dir, "ffmpeg")
        self.ffmpeg_path = os.path.join(self.ffmpeg_dir, "ffmpeg.exe")
        self.ffprobe_path = os.path.join(self.ffmpeg_dir, "ffprobe.exe")
        
    def ensure_ffmpeg_exists(self) -> str:
        """FFmpeg 바이너리 존재 확인 및 설치"""
        if os.path.exists(self.ffmpeg_path) and os.path.exists(self.ffprobe_path):
            logger.info("기존 FFmpeg 바이너리 사용")
            return self.ffmpeg_path
            
        logger.info("FFmpeg 바이너리 설치 시작")
        os.makedirs(self.ffmpeg_dir, exist_ok=True)
        
        if getattr(sys, 'frozen', False):
            # 실행 파일로 패키징된 경우
            meipass_ffmpeg = os.path.join(sys._MEIPASS, "libs", "ffmpeg-7.1-full_build", "bin", "ffmpeg.exe")
            meipass_ffprobe = os.path.join(sys._MEIPASS, "libs", "ffmpeg-7.1-full_build", "bin", "ffprobe.exe")
            
            if os.path.exists(meipass_ffmpeg) and os.path.exists(meipass_ffprobe):
                shutil.copy2(meipass_ffmpeg, self.ffmpeg_path)
                shutil.copy2(meipass_ffprobe, self.ffprobe_path)
                logger.info("FFmpeg 바이너리 설치 완료")
                return self.ffmpeg_path
                
        else:
            # 개발 환경에서는 libs 폴더에서 복사
            dev_ffmpeg = os.path.join("libs", "ffmpeg-7.1-full_build", "bin", "ffmpeg.exe")
            dev_ffprobe = os.path.join("libs", "ffmpeg-7.1-full_build", "bin", "ffprobe.exe")
            
            if os.path.exists(dev_ffmpeg) and os.path.exists(dev_ffprobe):
                shutil.copy2(dev_ffmpeg, self.ffmpeg_path)
                shutil.copy2(dev_ffprobe, self.ffprobe_path)
                logger.info("FFmpeg 바이너리 설치 완료")
                return self.ffmpeg_path
        logger.error("FFmpeg 바이너리를 찾을 수 없습니다")
        return ""

# 싱글톤 인스턴스
ffmpeg_manager = FFmpegManager()
