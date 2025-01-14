# ffmpeg_utils_refactor.py

import os
import sys
import tempfile
import glob
import re
import shutil
import psutil
from concurrent.futures import ThreadPoolExecutor
import time
import gc
from typing import List, Dict, Tuple, Optional
import ffmpeg
import logging

# 로깅 설정
logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

# 전역 변수로 ffmpeg_path 설정
FFMPEG_PATH = None
FFPROBE_PATH = None

def set_ffmpeg_path(path: str):
    global FFMPEG_PATH, FFPROBE_PATH
    if os.path.exists(path):
        FFMPEG_PATH = path
        FFPROBE_PATH = os.path.join(os.path.dirname(path), 'ffprobe.exe')
        logger.debug(f"FFmpeg 경로 설정: {FFMPEG_PATH}")
        logger.debug(f"FFprobe 경로 설정: {FFPROBE_PATH}")
    else:
        logger.error(f"FFmpeg 경로를 찾을 수 없음: {path}")


def create_temp_file_list(temp_files: List[str]) -> str:
    """
    임시 파일 목록을 생성하고 파일 경로를 반환합니다.
    """
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as file_list:
        for video in temp_files:
            absolute_path = os.path.abspath(video).replace('\\', '/')
            file_list.write(f"file '{absolute_path}'\n")
    return file_list.name


def get_media_properties(input_file: str, debug_mode: bool = False) -> Dict[str, str]:
    """
    미디어 파일(비디오 또는 이미지 시퀀스)의 해상도를 반환합니다.
    """
    try:
        if is_image_sequence(input_file):
            # 이미지 시퀀스인 경우 첫 번째 이미지 파일을 사용하여 속성 추출
            pattern = input_file.replace('\\', '/')
            pattern = re.sub(r'%\d*d', '*', pattern)
            image_files = sorted(glob.glob(pattern))
            if not image_files:
                logger.warning(f"이미지 시퀀스 '{input_file}'를 찾을 수 없습니다.")
                return {}
            probe_input = image_files[0]
        else:
            probe_input = input_file

        probe = ffmpeg.probe(probe_input, cmd=FFPROBE_PATH)
        video_stream = next(
            (s for s in probe['streams'] if s['codec_type'] == 'video'),
            None
        )
        if video_stream is None:
            logger.warning(f"'{input_file}'에서 비디오 스트림을 찾을 수 없습니다.")
            return {}
        return {
            'width': video_stream['width'],
            'height': video_stream['height'],
        }
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
    width, height = target_properties['width'], target_properties['height']

    # 스케일 필터 적용
    stream = stream.filter('scale', width, height, force_original_aspect_ratio='decrease')

    # 패드 필터 적용
    stream = stream.filter('pad', width, height, x='(ow-iw)/2', y='(oh-ih)/2', color='black')

    return stream


def process_video_file(
    input_file: str,
    trim_start: int,
    trim_end: int,
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool,
    idx: int
) -> str:
    """비디오 파일을 트림하고 필터를 적용하여 처리된 파일을 반환합니다."""
    temp_output = f'temp_output_{idx}.mp4'
    logger.info(f"비디오 처리 시작: {input_file}")

    # 스레드와 메모리 최적화 옵션 적용
    encoding_options = get_optimal_encoding_options(encoding_options)

    # 입력 버퍼 크기 설정
    input_options = {
        'probesize': '100M',    # 파일 분석을 위한 버퍼 크기
        'analyzeduration': '100M'  # 스트림 분석 시간
    }

    # 트림 시간 계산
    framerate = float(encoding_options.get('r', 30))
    start_time = trim_start / framerate if trim_start > 0 else 0

    # 스트림 생성 (입력 옵션 추가)
    if trim_start > 0 or trim_end > 0:
        total_duration = get_video_duration(input_file)
        duration_time = total_duration - (trim_start + trim_end) / framerate
        if duration_time > 0:
            stream = ffmpeg.input(input_file, ss=start_time, t=duration_time, **input_options)
    else:
        stream = ffmpeg.input(input_file, **input_options)
    
    stream = apply_filters(stream, target_properties)
    stream = ffmpeg.output(stream, temp_output, **encoding_options)
    stream = stream.overwrite_output()

    if debug_mode:
        logger.debug(f"비디오 처리 명령어: {' '.join(ffmpeg.compile(stream))}")

    # FFmpeg 실행
    try:
        ffmpeg.run(stream, cmd=FFMPEG_PATH)
        logger.info(f"비디오 처리 완료: {input_file}")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"FFmpeg 실행 중 오류 발생: {error_message}")
        raise

    return temp_output


def process_image_sequence(
    input_file: str,
    trim_start: int,
    trim_end: int,
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool,
    idx: int
) -> str:
    try:
        temp_output = f'temp_output_{idx}.mp4'
        logger.info(f"이미지 시퀀스 처리 시작: {input_file}")

        # 이미지 파일 패턴과 총 프레임 수 계산
        pattern = input_file.replace('\\', '/')
        glob_pattern = re.sub(r'%\d*d', '*', pattern)
        image_files = sorted(glob.glob(glob_pattern))

        if not image_files:
            logger.warning(f"이미지 시퀀스 '{input_file}'를 찾을 수 없습니다.")
            raise FileNotFoundError(f"No images found for pattern '{input_file}'")

        total_frames = len(image_files)

        # 시작 프레임 번호 추출
        frame_number_pattern = re.compile(r'(\d+)\.(\w+)$')
        first_image = os.path.basename(image_files[0])
        match = frame_number_pattern.search(first_image)
        if not match:
            logger.warning(f"'{first_image}'에서 시작 프레임 번호를 추출할 수 없습니다.")
            raise ValueError(f"Cannot extract frame number from '{first_image}'")

        original_start_frame = int(match.group(1))
        new_start_frame = original_start_frame + trim_start
        new_total_frames = total_frames - trim_start - trim_end

        if new_total_frames <= 0:
            raise ValueError("트림 후 남은 프레임이 없습니다.")

        # 인코딩 옵션 설정
        encoding_options = get_optimal_encoding_options(encoding_options)
        framerate = float(encoding_options.get('r', 30))

        # 입력 옵션 설정
        input_args = {
            'framerate': str(framerate),
            'probesize': '100M',
            'analyzeduration': '100M',
            'start_number': str(new_start_frame)  # 트림된 시작 프레임
        }

        # frames 옵션 추가 (트림된 총 프레임 수)
        encoding_options['frames'] = str(new_total_frames)

        if debug_mode:
            logger.debug(f"트림 정보 - 시작: {new_start_frame}, 프레임 수: {new_total_frames}")
            logger.debug(f"입력 옵션: {input_args}")
            logger.debug(f"인코딩 옵션: {encoding_options}")

        # 스트림 생성
        stream = ffmpeg.input(input_file, **input_args)

        # 필터 적용
        if target_properties:
            stream = apply_filters(stream, target_properties)

        # 출력 스트림 설정
        stream = ffmpeg.output(stream, temp_output, **encoding_options)
        stream = stream.overwrite_output()

        if debug_mode:
            logger.debug(f"이미지 시퀀스 처리 명령어: {' '.join(ffmpeg.compile(stream))}")

        # FFmpeg 실행
        try:
            ffmpeg.run(stream, cmd=FFMPEG_PATH)
            logger.info(f"이미지 시퀀스 처리 완료: {input_file}")
        except ffmpeg.Error as e:
            error_message = e.stderr.decode() if e.stderr else str(e)
            logger.error(f"FFmpeg 실행 중 오류 발생: {error_message}")
            raise

        return temp_output

    except Exception as e:
        logger.exception(f"이미지 시퀀스 처리 중 오류 발생: {str(e)}")
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
                logger.info(f"임시 파일 제거됨: {temp_output}")
            except Exception as cleanup_error:
                logger.warning(f"임시 파일 제거 실패: {cleanup_error}")
        raise


def get_video_duration(input_file: str) -> float:
    """
    비디오 파일의 총 길이(초)를 반환합니다.
    """
    try:
        probe = ffmpeg.probe(input_file, cmd=FFPROBE_PATH)
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


def get_target_properties(input_files: List[str], encoding_options: Dict[str, str], debug_mode: bool):
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
    input_files: List[str],
    target_properties: Dict[str, str],
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


def concat_media_files(
    processed_files: List[str],
    output_file: str,
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool,
    progress_callback=None
):
    """최적화된 파일 병합 처리"""
    logger.info(f"파일 병합 시작: {len(processed_files)}개 파일")
    
    # 단일 파일인 경우 직접 이동
    if len(processed_files) == 1:
        shutil.move(processed_files[0], output_file)
        if progress_callback:
            progress_callback(100)
        return

    # 병합을 위한 최적화된 인코딩 옵션
    concat_options = get_optimal_encoding_options(encoding_options)
    
    # 입력 버퍼 최적화
    input_options = {
        'safe': '0',
        'probesize': '100M',
        'analyzeduration': '100M',
    }

    # 파일 목록 생성
    file_list_path = create_temp_file_list(processed_files)
    
    try:
        # concat demuxer를 사용한 스트림 생성
        stream = ffmpeg.input(file_list_path, **input_options, f='concat')

        # 필터 적용 (필요한 경우)
        if target_properties:
            stream = apply_filters(stream, target_properties)

        # 출력 스트림 설정
        stream = ffmpeg.output(stream, output_file, **concat_options)
        stream = stream.overwrite_output()

        if debug_mode:
            logger.debug(f"병합 명령어: {' '.join(ffmpeg.compile(stream))}")

        # 비동기 처리를 위한 프로세스 실행
        process = ffmpeg.run_async(
            stream, 
            cmd=FFMPEG_PATH,
            pipe_stdout=True, 
            pipe_stderr=True
        )

        # 진행 상황 모니터링
        while True:
            output = process.stderr.readline().decode()
            if output == '' and process.poll() is not None:
                break
            if output:
                # 진행률 파싱 및 콜백
                progress = parse_ffmpeg_progress(output)
                if progress is not None and progress_callback:
                    # 진행률을 75%에서 100% 사이로 조정
                    adjusted_progress = 75 + int(progress * 0.25)
                    progress_callback(adjusted_progress)

        # 프로세스 완료 대기
        process.wait()

    except Exception as e:
        logger.error(f"파일 병합 중 오류 발생: {e}")
        raise
    finally:
        # 임시 파일 정리
        try:
            os.remove(file_list_path)
            logger.debug("임시 파일 목록 제거됨")
        except Exception as e:
            logger.warning(f"임시 파일 제거 중 오류: {e}")

def parse_ffmpeg_progress(output: str) -> Optional[float]:
    """FFmpeg 출력에서 진행률 파싱"""
    try:
        if "time=" in output:
            # 시간 정보 추출
            time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", output)
            if time_match:
                time_str = time_match.group(1)
                h, m, s = map(float, time_str.split(':'))
                current_seconds = h * 3600 + m * 60 + s
                
                # 전체 시간 대비 현재 진행률 계산
                # 여기서는 예시로 100%를 반환하지만, 
                # 실제로는 전체 길이를 알아야 정확한 진행률 계산 가능
                return min(current_seconds / 1, 1.0)
    except Exception as e:
        logger.warning(f"진행률 파싱 중 오류: {e}")
    
    return None

def process_all_media(
    media_files: List[Tuple[str, int, int]],
    output_file: str,
    encoding_options: Dict[str, str],
    debug_mode: bool = False,
    trim_values: List[Tuple[int, int]] = None,
    global_trim_start: int = 0,
    global_trim_end: int = 0,
    progress_callback: Optional[callable] = None,
    target_properties: Dict[str, str] = {}
):
    """
    모든 미디어 파일을 처리하고 하나의 파일로 합칩니다.
    """
    try:
        if trim_values is None:
            # media_files의 개별 트림 값을 사용
            trim_values = [(media_file[1], media_file[2]) for media_file in media_files]

        if debug_mode:
            logger.debug(f"전역 트림 값 - 시작: {global_trim_start}, 끝: {global_trim_end}")
            logger.debug(f"개별 트림 값: {trim_values}")

        # 전역 트림 값과 개별 트림 값을 합산
        combined_trim_values = [
            (ts + global_trim_start, te + global_trim_end) 
            for ts, te in trim_values
        ]

        if debug_mode:
            logger.debug(f"합산된 트림 값: {combined_trim_values}")

        # 디버그 모드일 때 -v quiet 옵션 제거, 아닐 때 추가
        if debug_mode:
            encoding_options.pop('v', None)  # 'v' 키가 있다면 제거
        else:
            encoding_options['v'] = 'quiet'

        logger.info(f"미디어 처리 시작: {len(media_files)}개 파일")
        
        # 먼저 target_properties 얻기
        input_files = [file[0] for file in media_files]  # 파일 경로만 추출
        target_properties = get_target_properties(input_files, encoding_options, debug_mode)
        
        if not target_properties:
            raise ValueError("대상 속성을 가져올 수 없습니다.")
        
        temp_files_to_remove = []
        processed_files = [None] * len(media_files)  # 순서 유지를 위한 초기화

        # 최적의 스레드 수 계산
        max_workers = min(len(media_files), os.cpu_count() or 1)
        
        # 메모리 사용량 모니터링 설정
        total_memory = psutil.virtual_memory().total
        memory_threshold = total_memory * 0.8

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            
            for idx, ((input_file, _, _), (trim_start, trim_end)) in enumerate(zip(media_files, combined_trim_values)):
                if debug_mode:
                    logger.debug(f"파일 처리: {input_file}")
                    logger.debug(f"적용될 트림 값 - 시작: {trim_start}, 끝: {trim_end}")

                future = executor.submit(
                    process_single_media,
                    input_file,
                    trim_start,
                    trim_end,
                    encoding_options.copy(),
                    debug_mode,
                    idx,
                    memory_threshold,
                    target_properties
                )
                futures.append((idx, future))

            # 순서대로 결과 수집 및 진행률 업데이트
            total_files = len(media_files)
            for idx, future in futures:
                try:
                    temp_output = future.result()
                    processed_files[idx] = temp_output  # 원래 순서대로 저장
                    temp_files_to_remove.append(temp_output)
                    
                    if progress_callback:
                        progress = int(((idx + 1) / total_files) * 75)
                        progress_callback(progress)
                        
                except Exception as e:
                    logger.error(f"'{media_files[idx][0]}' 처리 중 오류 발생: {e}")
                    raise

        # 빈 항목 제거
        processed_files = [f for f in processed_files if f is not None]

        # 처리된 파일들을 하나로 병합
        if processed_files:
            try:
                concat_media_files(
                    processed_files,
                    output_file,
                    encoding_options,
                    target_properties,
                    debug_mode,
                    progress_callback
                )
            finally:
                # 임시 파일 정리
                for temp_file in temp_files_to_remove:
                    try:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                            logger.debug(f"임시 파일 제거됨: {temp_file}")
                    except Exception as e:
                        logger.warning(f"임시 파일 제거 실패: {temp_file} - {e}")

        return output_file

    except Exception as e:
        logger.exception("미디어 처리 중 오류 발생")
        raise

def process_single_media(
    input_file: str,
    trim_start: int,
    trim_end: int,
    encoding_options: Dict[str, str],
    debug_mode: bool,
    idx: int,
    memory_threshold: int,
    target_properties: Dict[str, str] = {}
) -> str:
    """단일 미디어 파일 처리 (메모리 모니터링 포함)"""
    try:
        # 현재 메모리 사용량 확인
        current_memory = psutil.virtual_memory().used
        if current_memory > memory_threshold:
            # 메모리 사용량이 임계값을 초과하면 잠시 대기
            logger.warning("메모리 사용량이 높습니다. 처리 대기 중...")
            time.sleep(5)  # 5초 대기
            gc.collect()  # 가비지 컬렉션 강제 실행

        # 이미지 시퀀스인지 확인
        if is_image_sequence(input_file):
            return process_image_sequence(
                input_file, trim_start, trim_end,
                encoding_options, target_properties, debug_mode, idx
            )
        else:
            return process_video_file(
                input_file, trim_start, trim_end,
                encoding_options, target_properties, debug_mode, idx
            )

    except Exception as e:
        logger.exception(f"'{input_file}' 처리 중 오류 발생")
        raise

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
