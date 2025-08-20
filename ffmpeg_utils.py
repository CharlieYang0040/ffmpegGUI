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
from utils import is_image_sequence

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


def apply_filters(stream, target_properties):
    width, height = target_properties['width'], target_properties['height']

    # 스케일 필터 적용
    stream = stream.filter('scale', width, height, force_original_aspect_ratio='decrease')

    # 패드 필터 적용
    stream = stream.filter('pad', width, height, x='(ow-iw)/2', y='(oh-ih)/2', color='black')

    return stream


def process_video_file(
    input_file: str,
    start_frame: int,
    end_frame: int,
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool,
    idx: int
) -> str:
    """비디오 파일을 트림하고 필터를 적용하여 처리된 파일을 반환합니다."""
    input_file = input_file.replace('\\', '/')
    temp_output = f'temp_output_{idx}.mp4'
    logger.info(f"비디오 처리 시작: {input_file}")

    # 비디오 정보 가져오기
    try:
        probe = ffmpeg.probe(input_file, cmd=FFPROBE_PATH)
        video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        
        # 프레임레이트 가져오기 (예: '30/1', '60/1', '24/1')
        fps = eval(video_info.get('r_frame_rate', '30/1'))
        
        # 총 프레임 수 계산
        total_frames = int(video_info.get('nb_frames', 0))
        if total_frames == 0:  # nb_frames가 없는 경우
            duration = float(video_info.get('duration', 0))
            total_frames = int(duration * fps)

        if debug_mode:
            logger.debug(f"비디오 정보:")
            logger.debug(f"  - 프레임레이트: {fps} fps")
            logger.debug(f"  - 총 프레임 수: {total_frames}")
            logger.debug(f"  - 영상 길이: {total_frames/fps:.2f} 초")
    except Exception as e:
        logger.error(f"비디오 정보 가져오기 실패: {e}")
        raise

    # 스레드와 메모리 최적화 옵션 적용
    encoding_options = get_optimal_encoding_options(encoding_options)
    
    # 입력 프레임레이트를 인코딩 옵션에 추가
    encoding_options['r'] = str(fps)

    # 입력 버퍼 크기 설정
    input_options = {
        'probesize': '100M',
        'analyzeduration': '100M'
    }

    # 스트림 생성
    stream = ffmpeg.input(input_file, **input_options)

    # 프레임 기반 트림 필터 적용
    if start_frame > 0 or end_frame > 0:
        if debug_mode:
            logger.debug(f"트림 정보:")
            logger.debug(f"  - 시작 프레임: {start_frame}")
            logger.debug(f"  - 끝 프레임: {end_frame}")
            logger.debug(f"  - 예상 출력 프레임 수: {end_frame - start_frame}")
        
        # 'end_frame'이 0이거나 지정되지 않은 경우, 영상 끝까지를 의미할 수 있도록 처리
        if end_frame > 0:
            stream = stream.filter('select', f'between(n,{start_frame},{end_frame})')
        else: # end_frame이 0 또는 음수이면 start_frame부터 끝까지
            stream = stream.filter('select', f'gte(n,{start_frame})')

        stream = stream.filter('setpts', 'PTS-STARTPTS')  # 타임스탬프 리셋
    
    stream = apply_filters(stream, target_properties)
    stream = ffmpeg.output(stream, temp_output, **encoding_options)
    stream = stream.overwrite_output()

    if debug_mode:
        logger.debug(f"비디오 처리 명령어: {' '.join(ffmpeg.compile(stream))}")

    # FFmpeg 실행
    try:
        ffmpeg.run(stream, cmd=FFMPEG_PATH, capture_stderr=True)
        logger.info(f"비디오 처리 완료: {input_file}")
    except ffmpeg.Error as e:
        error_message = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"FFmpeg 실행 중 오류 발생: {error_message}")
        
        # NVENC 관련 오류 확인
        if "nvenc" in error_message.lower():
            raise RuntimeError("NVENC를 사용할 수 없습니다. NVIDIA 드라이버를 확인하거나 다른 코덱을 선택하세요.")
        
        raise

    return temp_output


def process_image_sequence(
    input_file: str,
    start_frame: int,
    end_frame: int,
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool,
    idx: int
) -> str:
    try:
        input_file = input_file.replace('\\', '/')
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

        # end_frame이 0이거나 지정되지 않았으면 시퀀스의 마지막 프레임을 사용
        if end_frame <= 0:
            end_frame = total_frames + original_start_frame -1

        new_total_frames = end_frame - start_frame + 1

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
            'start_number': str(start_frame)  # 트림된 시작 프레임
        }

        # frames 옵션 추가 (트림된 총 프레임 수)
        encoding_options['vframes'] = str(new_total_frames)

        if debug_mode:
            logger.debug(f"트림 정보 - 시작: {start_frame}, 프레임 수: {new_total_frames}")
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
            ffmpeg.run(stream, cmd=FFMPEG_PATH, capture_stderr=True)
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
    frame_ranges: List[Tuple[int, int]] = None,
    global_trim_start: int = 0,
    global_trim_end: int = 0,
    progress_callback: Optional[callable] = None,
    target_properties: Dict[str, str] = {},
    max_workers_override: Optional[int] = None
):
    """
    모든 미디어 파일을 처리하고 하나의 파일로 합칩니다.
    """
    try:
        if frame_ranges is None:
            # media_files의 개별 프레임 범위를 사용
            frame_ranges = [(media_file[1], media_file[2]) for media_file in media_files]

        if debug_mode:
            logger.debug(f"전역 트림 값 - 시작: {global_trim_start}, 끝: {global_trim_end}")
            logger.debug(f"개별 프레임 범위: {frame_ranges}")

        # 전역 트림 값과 개별 트림 값을 합산 (이 부분은 유지하거나, 새 정책에 맞게 변경 필요)
        # 여기서는 기존 로직을 유지하여 global trim을 시작/끝 프레임에 더하고 빼는 것으로 해석
        combined_frame_ranges = [
            (sf + global_trim_start, ef - global_trim_end if ef > 0 else 0)
            for sf, ef in frame_ranges
        ]

        if debug_mode:
            logger.debug(f"합산된 프레임 범위: {combined_frame_ranges}")

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

        # NVENC 코덱 사용 시 동시 작업 수를 2로 제한, 그 외에는 CPU 코어 수만큼 사용
        codec = encoding_options.get("c:v")
        if codec in ["h264_nvenc", "hevc_nvenc"]:
            if max_workers_override:
                max_workers = max_workers_override
                logger.info(f"사용자 설정에 따라 NVENC 최대 작업 수를 {max_workers}개로 설정합니다.")
            else:
                max_workers = 2 # 기본값
                logger.info(f"NVENC 코덱({codec}) 사용으로 최대 작업 수를 {max_workers}개로 제한합니다.")
        else:
            max_workers = os.cpu_count()
            logger.info(f"CPU 코덱({codec}) 사용으로 최대 작업 수를 {max_workers}개로 설정합니다.")

        # 메모리 사용량 모니터링 설정
        total_memory = psutil.virtual_memory().total
        memory_threshold = total_memory * 0.8

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            
            for idx, ((input_file, _, _), (start_frame, end_frame)) in enumerate(zip(media_files, combined_frame_ranges)):
                if debug_mode:
                    logger.debug(f"파일 처리: {input_file}")
                    logger.debug(f"적용될 프레임 범위 - 시작: {start_frame}, 끝: {end_frame}")

                future = executor.submit(
                    process_single_media,
                    input_file,
                    start_frame,
                    end_frame,
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
    start_frame: int,
    end_frame: int,
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
                input_file, start_frame, end_frame,
                encoding_options, target_properties, debug_mode, idx
            )
        else:
            return process_video_file(
                input_file, start_frame, end_frame,
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


def get_total_duration(media_files: List[Tuple[str, int, int]], encoding_options: Dict[str, str]) -> float:
    """
    모든 미디어 파일의 총 길이를 초 단위로 계산합니다.
    """
    total_duration = 0.0
    framerate = float(encoding_options.get('r', 30))

    for input_file, start_frame, end_frame in media_files:
        if is_image_sequence(input_file):
            pattern = input_file.replace('\\', '/')
            glob_pattern = re.sub(r'%\d*d', '*', pattern)
            image_files = sorted(glob.glob(glob_pattern))
            
            if not image_files:
                continue

            total_frames = len(image_files)
            
            # 프레임 번호 추출하여 원본 시작 프레임 확인
            frame_number_pattern = re.compile(r'(\d+)\.(\w+)$')
            first_image_match = frame_number_pattern.search(os.path.basename(image_files[0]))
            original_start_frame = int(first_image_match.group(1)) if first_image_match else 0

            # 실제 사용될 프레임 범위 계산
            actual_start = start_frame
            actual_end = end_frame if end_frame > 0 else total_frames + original_start_frame - 1
            
            num_frames = actual_end - actual_start + 1
            if num_frames > 0:
                total_duration += num_frames / framerate
        else:
            try:
                probe = ffmpeg.probe(input_file, cmd=FFPROBE_PATH)
                duration = float(probe['format']['duration'])
                
                # 비디오는 프레임 기반 트림이 아닌 시간 기반으로 길이를 다시 계산해야 할 수 있으나,
                # 여기서는 단순화를 위해 전체 길이를 사용합니다.
                # 정확도를 높이려면 process_video_file의 트림 로직을 반영해야 합니다.
                total_duration += duration
            except (ffmpeg.Error, KeyError) as e:
                logger.warning(f"'{input_file}'의 길이를 가져오는 중 오류: {e}")

    return total_duration


def run_sample_analysis(
    sample_info: Dict,
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool
) -> float:
    """단일 샘플 지점에서 비트레이트를 분석하여 반환합니다."""
    
    file_path = sample_info['file_path']
    start_time = sample_info.get('start_time') # 비디오용
    start_frame = sample_info.get('start_frame') # 이미지 시퀀스용
    
    try:
        # 스트림 생성
        if is_image_sequence(file_path):
            framerate = float(encoding_options.get('r', 30))
            input_args = {'framerate': str(framerate), 'start_number': str(start_frame)}
            stream = ffmpeg.input(file_path, **input_args)
        else:
            stream = ffmpeg.input(file_path, ss=start_time)

        # 공통 필터 적용
        stream = apply_filters(stream, target_properties)
        
        # 분석용 인코딩 옵션 설정
        analysis_options = get_optimal_encoding_options(encoding_options)
        analysis_options.pop('pass', None)

        if is_image_sequence(file_path):
            framerate = float(encoding_options.get('r', 30))
            analysis_options['vframes'] = int(2 * framerate)  # 2초 분량
        else:
            analysis_options['t'] = 2  # 2초만 인코딩

        stream = ffmpeg.output(
            stream, 'NUL' if os.name == 'nt' else '/dev/null', **analysis_options, f='null'
        ).overwrite_output()
        
        if debug_mode:
            logger.debug(f"샘플 분석 명령어 ({sample_info['type']}): {' '.join(ffmpeg.compile(stream, cmd=FFMPEG_PATH))}")

        # 분석 실행 및 stderr 캡처
        _, stderr_bytes = ffmpeg.run(stream, cmd=FFMPEG_PATH, capture_stdout=True, capture_stderr=True)
        stderr_str = stderr_bytes.decode(errors='ignore')

        # 비트레이트 계산
        match_size = re.search(r"video:(\d+)KiB", stderr_str)
        matches_time = re.findall(r"time=(\d{2}):(\d{2}):(\d{2}\.\d{2})", stderr_str)

        if match_size and matches_time:
            sample_size_kib = int(match_size.group(1))
            h, m, s = matches_time[-1]
            sample_time_sec = int(h) * 3600 + int(m) * 60 + float(s)
            if sample_time_sec > 0:
                bitrate = (sample_size_kib * 8) / sample_time_sec  # kbits/s
                logger.info(f"샘플 분석 성공 ({sample_info['type']}): {bitrate:.2f} kb/s")
                return bitrate
    
    except Exception as e:
        logger.warning(f"샘플 분석 중 오류 ({sample_info['type']}): {e}")

    return 0.0


def estimate_filesize_fast(
    media_files: List[Tuple[str, int, int]],
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool = False
) -> float:
    """
    다중 지점 샘플링을 통해 예상 파일 크기를 MB 단위로 반환합니다. (빠르지만 부정확)
    """
    if not media_files:
        return 0.0

    total_duration_sec = get_total_duration(media_files, encoding_options)
    if total_duration_sec <= 0:
        return 0.0

    # 1. 비트레이트가 직접 지정된 경우
    if 'b:v' in encoding_options:
        bitrate_str = encoding_options['b:v']
        bitrate_kbps = 0
        if isinstance(bitrate_str, str):
            if bitrate_str.lower().endswith('k'): bitrate_kbps = float(bitrate_str[:-1])
            elif bitrate_str.lower().endswith('m'): bitrate_kbps = float(bitrate_str[:-1]) * 1024
            else: bitrate_kbps = float(bitrate_str) / 1000
        else: bitrate_kbps = float(bitrate_str) / 1000
        return (bitrate_kbps * total_duration_sec) / (8 * 1024)

    # 2. 품질 기반인 경우 (다중 지점 샘플링)
    sampling_points = []
    
    # 샘플링 지점 결정
    if len(media_files) == 1:
        file_path, start_f, end_f = media_files[0]
        duration = get_total_duration([(file_path, start_f, end_f)], encoding_options)
        if duration > 6:
            sampling_points.append({'type': 'start', 'file_path': file_path, 'start_time': 0, 'start_frame': start_f})
            sampling_points.append({'type': 'middle', 'file_path': file_path, 'start_time': duration / 2, 'start_frame': start_f + int((end_f - start_f) / 2)})
            sampling_points.append({'type': 'end', 'file_path': file_path, 'start_time': duration - 4, 'start_frame': end_f - (2*int(encoding_options.get('r', 30)))})
        else:
             sampling_points.append({'type': 'start', 'file_path': file_path, 'start_time': 0, 'start_frame': start_f})
    else:
        start_file, start_sf, _ = media_files[0]
        sampling_points.append({'type': 'start', 'file_path': start_file, 'start_time': 0, 'start_frame': start_sf})

        middle_idx = len(media_files) // 2
        mid_file, mid_sf, mid_ef = media_files[middle_idx]
        mid_duration = get_total_duration([(mid_file, mid_sf, mid_ef)], encoding_options)
        sampling_points.append({'type': 'middle', 'file_path': mid_file, 'start_time': mid_duration / 2, 'start_frame': mid_sf + int((mid_ef-mid_sf)/2)})

        end_file, end_sf, end_ef = media_files[-1]
        end_duration = get_total_duration([(end_file, end_sf, end_ef)], encoding_options)
        sampling_points.append({'type': 'end', 'file_path': end_file, 'start_time': max(0, end_duration - 4), 'start_frame': end_ef - (2*int(encoding_options.get('r', 30)))})

    total_bitrate = 0
    valid_samples = 0
    for point in sampling_points:
        bitrate = run_sample_analysis(point, encoding_options, target_properties, debug_mode)
        if bitrate > 0:
            total_bitrate += bitrate
            valid_samples += 1
            
    if valid_samples > 0:
        avg_bitrate_kbps = total_bitrate / valid_samples
        logger.info(f"최종 평균 비트레이트 (빠른 예상): {avg_bitrate_kbps:.2f} kb/s ({valid_samples}개 샘플 기준)")
        return (avg_bitrate_kbps * total_duration_sec) / (8 * 1024)
    else:
        logger.error("모든 샘플 지점에서 비트레이트 분석에 실패했습니다.")
        return 0.0


def estimate_filesize_accurate(
    media_files: List[Tuple[str, int, int]],
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool = False,
    max_workers_override: Optional[int] = None
) -> float:
    """
    가장 빠른 프리셋으로 전체 영상을 분석하여 예상 파일 크기를 MB 단위로 반환합니다. (정확하지만 느림)
    """
    if not media_files:
        return 0.0

    total_duration_sec = get_total_duration(media_files, encoding_options)
    if total_duration_sec <= 0: return 0.0

    if 'b:v' in encoding_options:
        # 비트레이트 모드는 계산이 정확하므로 빠른 모드와 동일하게 처리
        return estimate_filesize_fast(media_files, encoding_options, target_properties, debug_mode)

    # 1. 모든 미디어를 처리하는 임시 파일들 생성
    temp_files = []
    try:
        from concurrent.futures import ThreadPoolExecutor

        # 작업자 수 결정
        codec = encoding_options.get("c:v")
        if codec in ["h264_nvenc", "hevc_nvenc"]:
            max_workers = max_workers_override if max_workers_override else 2
        else:
            max_workers = os.cpu_count()

        # 실제 인코딩과 동일하게 병렬로 임시 파일 생성
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for idx, (input_file, start_frame, end_frame) in enumerate(media_files):
                future = executor.submit(
                    process_single_media,
                    input_file, start_frame, end_frame,
                    encoding_options.copy(), debug_mode, idx,
                    psutil.virtual_memory().total * 0.9, # 메모리 임계값
                    target_properties
                )
                futures.append(future)
            
            for future in futures:
                temp_files.append(future.result())

        if not temp_files:
            raise RuntimeError("임시 파일 생성에 실패했습니다.")

        # 2. 생성된 임시 파일들을 concat demuxer로 연결
        file_list_path = create_temp_file_list(temp_files)
        
        analysis_options = get_optimal_encoding_options(encoding_options)
        analysis_options.pop('pass', None)
        
        # 가장 빠른 프리셋으로 강제 변경
        codec = analysis_options.get("c:v")
        if codec in ["h264_nvenc", "hevc_nvenc"]:
            analysis_options['preset'] = 'p1'
        elif codec in ["libx264", "libx265"]:
            analysis_options['preset'] = 'ultrafast'

        input_options = {'safe': '0', 'f': 'concat', 'protocol_whitelist': 'file,pipe'}
        stream = ffmpeg.input(file_list_path, **input_options)
        stream = ffmpeg.output(
            stream, 'NUL' if os.name == 'nt' else '/dev/null', **analysis_options, f='null'
        ).overwrite_output()

        if debug_mode:
            logger.debug(f"정밀 분석 명령어: {' '.join(ffmpeg.compile(stream, cmd=FFMPEG_PATH))}")

        # 3. 전체 분석 실행
        _, stderr_bytes = ffmpeg.run(stream, cmd=FFMPEG_PATH, capture_stdout=True, capture_stderr=True)
        stderr_str = stderr_bytes.decode(errors='ignore')

        match_size = re.search(r"video:(\d+)KiB", stderr_str)
        if match_size:
            total_size_kib = int(match_size.group(1))
            estimated_size_mb = total_size_kib / 1024
            logger.info(f"정밀 분석 성공: 총 비디오 크기 {total_size_kib} KiB -> {estimated_size_mb:.2f} MB")
            return estimated_size_mb
        else:
            logger.error(f"정밀 분석 결과에서 비디오 크기를 찾지 못했습니다. stderr: {stderr_str}")
            return 0.0

    except Exception as e:
        logger.exception(f"정밀 분석 중 예외 발생: {e}")
        return 0.0
    finally:
        # 모든 임시 파일 정리
        if 'file_list_path' in locals() and os.path.exists(file_list_path):
            os.remove(file_list_path)
        for f in temp_files:
            if os.path.exists(f):
                os.remove(f)
