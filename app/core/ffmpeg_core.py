import os
import sys
import tempfile
import glob
import re
import logging
import ffmpeg
import psutil
import subprocess

# 로깅 서비스 가져오기
from app.services.logging_service import LoggingService

# FFmpegManager 싱글톤 가져오기
from app.core.ffmpeg_manager import FFmpegManager

# 로깅 설정
logger = LoggingService().get_logger(__name__)

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

# 전역 변수로 ffmpeg_path 설정
FFMPEG_PATH = None
FFPROBE_PATH = None

def set_ffmpeg_path(path: str):
    """FFmpeg 경로 설정 함수"""
    global FFMPEG_PATH, FFPROBE_PATH
    logger.debug(f"FFmpeg 경로 설정 시도: {path}")
    if os.path.exists(path):
        FFMPEG_PATH = path
        FFPROBE_PATH = os.path.join(os.path.dirname(path), 'ffprobe.exe')
        logger.debug(f"FFmpeg 경로 설정 성공: {FFMPEG_PATH}")
        logger.debug(f"FFprobe 경로 설정: {FFPROBE_PATH}")
        return True
    else:
        logger.error(f"FFmpeg 경로를 찾을 수 없음: {path}")
        return False

def create_temp_file_list(temp_files: list) -> str:
    """
    임시 파일 목록을 생성하고 파일 경로를 반환합니다.
    """
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as file_list:
        for video in temp_files:
            absolute_path = os.path.abspath(video).replace('\\', '/')
            file_list.write(f"file '{absolute_path}'\n")
    return file_list.name

def get_media_properties(input_file: str, debug_mode: bool = False) -> dict:
    """
    미디어 파일(비디오 또는 이미지 시퀀스)의 속성을 반환합니다.
    """
    ffmpeg_manager = FFmpegManager()
    ffprobe_path = ffmpeg_manager.get_ffprobe_path()
    
    try:
        if is_image_sequence(input_file):
            # 이미지 시퀀스인 경우 첫 번째 이미지 파일을 사용하여 속성 추출
            pattern = input_file.replace('\\', '/')
            pattern = re.sub(r'%\d*d', '*', pattern)
            image_files = sorted(glob.glob(pattern))
            if not image_files:
                logger.warning(f"이미지 시퀀스 '{input_file}'를 찾을 수 없습니다.")
                return {}
                
            # 첫 번째 이미지 파일로 속성 추출
            probe_input = image_files[0]
            
            # PIL을 사용하여 이미지 크기 확인 (ffprobe가 실패할 경우 대비)
            try:
                from PIL import Image
                with Image.open(probe_input) as img:
                    width, height = img.size
                    return {
                        'width': width,
                        'height': height,
                        # 이미지 시퀀스의 경우 기본값 설정
                        'duration': len(image_files) / 30.0,  # 기본 30fps 가정
                        'r': 30.0,  # 기본 프레임 레이트
                        'nb_frames': len(image_files)
                    }
            except Exception as pil_error:
                logger.warning(f"PIL로 이미지 크기를 가져오는 데 실패: {pil_error}")
                # PIL 실패 시 ffprobe로 계속 진행
        else:
            probe_input = input_file

        # ffprobe 명령어 실행
        if debug_mode:
            logger.debug(f"FFprobe 명령: {ffprobe_path} -v error -select_streams v:0 -show_entries stream=width,height,r_frame_rate,duration,nb_frames -of default=noprint_wrappers=1:nokey=0 {probe_input}")
        
        probe = ffmpeg.probe(probe_input, cmd=ffprobe_path)
        video_stream = next(
            (s for s in probe['streams'] if s['codec_type'] == 'video'),
            None
        )
        
        if video_stream is None:
            logger.warning(f"'{input_file}'에서 비디오 스트림을 찾을 수 없습니다.")
            return {}
        
        # 기본 비디오 속성 추출
        properties = {
            'width': video_stream.get('width', 0),
            'height': video_stream.get('height', 0),
        }
        
        # 프레임 레이트 추출 및 계산
        if 'r_frame_rate' in video_stream:
            r_frame_rate = video_stream['r_frame_rate']
            if '/' in r_frame_rate:
                num, den = map(int, r_frame_rate.split('/'))
                fps = num / den if den != 0 else 0
            else:
                fps = float(r_frame_rate)
            properties['r'] = fps
        else:
            properties['r'] = 30.0  # 기본값
        
        # 지속 시간 추출
        if 'duration' in video_stream:
            properties['duration'] = float(video_stream['duration'])
        elif 'duration' in probe['format']:
            properties['duration'] = float(probe['format']['duration'])
        else:
            properties['duration'] = 0.0
        
        # 총 프레임 수 추출
        if 'nb_frames' in video_stream and video_stream['nb_frames'] != 'N/A' and int(video_stream['nb_frames']) > 0:
            properties['nb_frames'] = int(video_stream['nb_frames'])
            if debug_mode:
                logger.debug(f"비디오 스트림에서 직접 nb_frames 추출: {properties['nb_frames']}")
        else:
            # 프레임 수가 없으면 지속 시간과 프레임 레이트로 계산
            calculated_frames = int(properties['duration'] * properties['r'])
            properties['nb_frames'] = calculated_frames
            if debug_mode:
                logger.debug(f"nb_frames 정보가 없어 계산: {properties['duration']} * {properties['r']} = {calculated_frames}")
            
            # 추가 검증: ffprobe로 직접 프레임 수 확인 시도
            try:
                cmd = [
                    ffprobe_path, 
                    '-v', 'error', 
                    '-count_frames', 
                    '-select_streams', 'v:0', 
                    '-show_entries', 'stream=nb_read_frames', 
                    '-of', 'default=noprint_wrappers=1:nokey=1', 
                    probe_input
                ]
                if debug_mode:
                    logger.debug(f"프레임 수 확인 명령: {' '.join(cmd)}")
                
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if result.returncode == 0 and result.stdout.strip() and result.stdout.strip() != 'N/A':
                    frame_count = int(result.stdout.strip())
                    if frame_count > 0:
                        properties['nb_frames'] = frame_count
                        if debug_mode:
                            logger.debug(f"count_frames로 프레임 수 확인: {frame_count}")
            except Exception as e:
                if debug_mode:
                    logger.debug(f"프레임 수 확인 중 오류: {e}")
        
        # 오디오 스트림 존재 여부 확인
        audio_stream = next(
            (s for s in probe['streams'] if s['codec_type'] == 'audio'),
            None
        )
        if audio_stream:
            properties['a'] = True
            if 'sample_rate' in audio_stream:
                properties['sample_rate'] = int(audio_stream['sample_rate'])
        
        if debug_mode:
            logger.debug(f"비디오 속성: {properties}")
        
        return properties
    except ffmpeg.Error as e:
        logger.error(f"'{input_file}'를 프로브하는 중 오류 발생: {e}")
        return {}
    except Exception as e:
        logger.exception(f"'{input_file}'의 속성을 가져오는 중 예외 발생: {e}")
        return {}

def is_image_sequence(input_file: str) -> bool:
    """
    입력 파일이 이미지 시퀀스인지 확인합니다.
    """
    return '%' in input_file or re.search(r'%\d*d', input_file) is not None

def apply_filters(stream, target_properties):
    """
    스트림에 필터를 적용합니다. (스케일, 패딩 등)
    """
    width, height = target_properties['width'], target_properties['height']

    # 스케일 필터 적용
    stream = stream.filter('scale', width, height, force_original_aspect_ratio='decrease')

    # 패드 필터 적용
    stream = stream.filter('pad', width, height, x='(ow-iw)/2', y='(oh-ih)/2', color='black')

    return stream

def get_video_duration(input_file: str) -> float:
    """
    비디오 파일의 총 길이(초)를 반환합니다.
    """
    ffmpeg_manager = FFmpegManager()
    ffprobe_path = ffmpeg_manager.get_ffprobe_path()
    
    try:
        probe = ffmpeg.probe(input_file, cmd=ffprobe_path)
        video_stream = next(
            (s for s in probe['streams'] if s['codec_type'] == 'video'),
            None
        )
        if video_stream and 'duration' in video_stream:
            return float(video_stream['duration'])
        else:
            format_info = probe.get('format', {})
            if 'duration' in format_info:
                return float(format_info['duration'])
    except ffmpeg.Error as e:
        logger.error(f"'{input_file}'의 길이를 가져오는 중 오류 발생: {e}")
    return 0.0

def get_target_properties(input_files: list, encoding_options: dict, debug_mode: bool):
    """
    입력 파일들의 타겟 속성을 결정합니다.
    """
    # 디버그 로깅
    if debug_mode:
        logger.debug(f"입력 파일 목록: {input_files}")
        logger.debug(f"인코딩 옵션: {encoding_options}")

    # 커스텀 해상도 설정이 있는 경우
    if "s" in encoding_options or "-s" in encoding_options:
        resolution = encoding_options.get("s") or encoding_options.get("-s")
        try:
            width, height = resolution.split('x')
            target_properties = {
                'width': int(width),
                'height': int(height),
            }
            if debug_mode:
                logger.debug(f"커스텀 해상도 사용: {width}x{height}")
            return target_properties
        except (ValueError, AttributeError) as e:
            logger.error(f"해상도 파싱 오류: {e}")
            return {}

    # 입력 파일 목록이 비어있는 경우
    if not input_files:
        logger.warning("처리할 파일이 없습니다.")
        return {}

    # 첫 번째 유효한 파일 찾기
    first_valid_file = None
    for file_path in input_files:
        if isinstance(file_path, (list, tuple)):
            # 튜플이나 리스트인 경우 첫 번째 요소(파일 경로)를 사용
            file_path = file_path[0]
        
        if file_path and isinstance(file_path, str):
            first_valid_file = file_path
            break

    if not first_valid_file:
        logger.warning("유효한 입력 파일을 찾을 수 없습니다.")
        return {}

    if debug_mode:
        logger.debug(f"속성을 가져올 파일: {first_valid_file}")

    # 미디어 속성 가져오기
    target_properties = get_media_properties(first_valid_file, debug_mode)
    if not target_properties:
        logger.warning(f"'{first_valid_file}'의 속성을 가져올 수 없습니다.")
        return {}

    # 해상도를 인코딩 옵션에 추가
    encoding_options["s"] = f"{target_properties['width']}x{target_properties['height']}"

    return target_properties

def check_media_properties(
    input_files: list,
    target_properties: dict,
    debug_mode: bool
):
    """
    입력 파일들의 해상도를 확인하고, 타겟 속성과 다른 경우 로그에 출력합니다.
    """
    for input_file in input_files:
        props = get_media_properties(input_file)
        input_width = props.get('width')
        input_height = props.get('height')
        input_resolution = f"{input_width}x{input_height}" if input_width and input_height else 'Unknown'

        if input_width != target_properties['width'] or input_height != target_properties['height']:
            logger.info(
                f"해상도 불일치 (자동으로 조정됨): {input_resolution} -> {target_properties['width']}x{target_properties['height']}"
            )

def get_optimal_thread_count():
    """libx264에 최적화된 스레드 수를 반환"""
    cpu_count = psutil.cpu_count(logical=True)
    # libx264의 권장 최대값인 16으로 제한
    return min(cpu_count, 16)

def get_optimal_encoding_options(encoding_options: dict) -> dict:
    """기본 인코딩 옵션에 성능 최적화 옵션을 추가"""
    optimal_options = encoding_options.copy()
    
    # CPU 스레드 최적화
    optimal_options.update({
        "threads": str(get_optimal_thread_count()),  # 최대 16개로 제한된 CPU 스레드 수
        
        # 메모리 버퍼 최적화
        "thread_queue_size": "4096",     # 스레드 큐 크기
        "max_muxing_queue_size": "4096"  # 먹싱 큐 크기
    })
    
    return optimal_options