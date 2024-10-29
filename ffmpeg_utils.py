# ffmpeg_utils_refactor.py

import os
import sys
import tempfile
import glob
import re
import shutil
from typing import List, Dict, Tuple
import ffmpeg
import logging

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

# 전역 변수로 ffmpeg_path 설정
FFMPEG_PATH = None
FFPROBE_PATH = None

def set_ffmpeg_path(path: str):
    global FFMPEG_PATH
    global FFPROBE_PATH
    FFMPEG_PATH = path
    FFPROBE_PATH = os.path.join(os.path.dirname(path), 'ffprobe.exe')


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



def process_media_files(
    media_files: List[Tuple[str, int, int]],
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool,
    idx: int,
    progress_callback=None
) -> Tuple[List[str], List[str]]:
    """
    비디오 파일과 이미지 시퀀스를 처리하여 임시 파일 목록과 제거할 임시 파일 목록을 반환합니다.
    """
    temp_files_to_remove = []
    processed_files = []
    total_files = len(media_files)

    for file_idx, (input_file, trim_start, trim_end) in enumerate(media_files):
        try:
            if is_image_sequence(input_file):
                logger.debug(f"이미지 시퀀스 처리: {input_file}")
                output_file = process_image_sequence(
                    input_file, trim_start, trim_end, encoding_options,
                    target_properties, debug_mode, idx, file_idx
                )
            else:
                logger.debug(f"비디오 파일 처리: {input_file}")
                output_file = process_video_file(
                    input_file, trim_start, trim_end, encoding_options,
                    target_properties, debug_mode, idx, file_idx
                )
            processed_files.append(output_file)
            temp_files_to_remove.append(output_file)

        except Exception as e:
            logger.exception(f"'{input_file}' 처리 중 오류 발생: {e}")

        # 진행률 업데이트
        if progress_callback:
            progress = int((file_idx + 1) / total_files * 75)
            logger.debug(f"진행률 업데이트: {progress}% (파일 {file_idx + 1}/{total_files})")
            progress_callback(progress)

    return processed_files, temp_files_to_remove


def process_video_file(
    input_file: str,
    trim_start: int,
    trim_end: int,
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool,
    idx: int,
    file_idx: int
) -> str:
    """
    비디오 파일을 트림하고 필터를 적용하여 처리된 파일을 반환합니다.
    """
    temp_output = f'temp_output_{idx}_{file_idx}.mp4'

    # 트림 시간 계산
    framerate = float(encoding_options.get('r', 30))
    start_time = trim_start / framerate if trim_start > 0 else 0

    # 스트림 생성
    stream = ffmpeg.input(input_file)
    
    # 트림이 필요한 경우에만 적용
    if trim_start > 0 or trim_end > 0:
        total_duration = get_video_duration(input_file)
        duration_time = total_duration - (trim_start + trim_end) / framerate
        if duration_time > 0:
            stream = ffmpeg.input(input_file, ss=start_time, t=duration_time)
    
    stream = apply_filters(stream, target_properties)
    stream = ffmpeg.output(stream, temp_output, **encoding_options)
    stream = stream.overwrite_output()

    if debug_mode:
        logger.debug(f"비디오 처리 명령어: {' '.join(ffmpeg.compile(stream))}")

    ffmpeg.run(stream, cmd=FFMPEG_PATH)

    return temp_output


def process_image_sequence(
    input_file: str,
    trim_start: int,
    trim_end: int,
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool,
    idx: int,
    file_idx: int
) -> str:
    """
    이미지 시퀀스를 처리하여 비디오 파일로 변환하고 트림 및 필터를 적용합니다.
    """
    temp_output = f'temp_output_{idx}_{file_idx}.mp4'

    # 이미지 파일 패턴과 총 프레임 수 계산
    pattern = input_file.replace('\\', '/')
    glob_pattern = re.sub(r'%\d*d', '*', pattern)
    image_files = sorted(glob.glob(glob_pattern))

    if not image_files:
        logger.warning(f"이미지 시퀀스 '{input_file}'를 찾을 수 없습니다.")
        raise FileNotFoundError(f"No images found for pattern '{input_file}'")

    total_frames = len(image_files)
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
        logger.warning(f"트림 후 남은 프레임이 없습니다: '{input_file}'")
        raise ValueError(f"No frames left after trimming for '{input_file}'")

    # 스트림 생성
    stream = ffmpeg.input(
        input_file,
        framerate=encoding_options.get('r', 30),
        start_number=new_start_frame
    )
    stream = apply_filters(stream, target_properties)

    # 인코딩 옵션 적용
    stream = ffmpeg.output(
        stream,
        temp_output,
        frames=new_total_frames,
        **encoding_options
    )
    stream = stream.overwrite_output()

    if debug_mode:
        logger.debug(f"이미지 시퀀스 처리 명령어: {' '.join(ffmpeg.compile(stream))}")

    ffmpeg.run(stream, cmd=FFMPEG_PATH)

    return temp_output


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


def get_target_properties(
    input_files: List[str],
    encoding_options: Dict[str, str],
    debug_mode: bool
) -> Dict[str, str]:
    """
    타겟 해상도를 결정합니다.
    """
    # 커스텀 해상도 설정이 있는 경우
    if "-s" in encoding_options:
        target_resolution = encoding_options["-s"]
        width, height = target_resolution.split('x')
        target_properties = {
            'width': width,
            'height': height,
        }
        if debug_mode:
            logger.debug(f"커스텀 해상도 사용: {width}x{height}")
        return target_properties

    # 커스텀 해상도가 없는 경우 첫 번째 파일의 속성 사용
    first_input_file = input_files[0] if input_files else None
    if not first_input_file:
        logger.warning("처리할 파일이 없습니다.")
        return {}

    target_properties = get_media_properties(first_input_file, debug_mode)
    if not target_properties:
        logger.warning(f"'{first_input_file}'의 속성을 가져올 수 없습니다.")
        return {}

    # 첫 번째 파일의 해상도를 -s 옵션으로 설정
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
            logger.debug(
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
    """
    처리된 파일들을 하나의 파일로 합칩니다.
    """
    if not processed_files:
        logger.warning("합칠 파일이 없습니다.")
        return

    if len(processed_files) == 1:
        shutil.move(processed_files[0], output_file)
        if progress_callback:
            progress_callback(100)
        return

    file_list_path = create_temp_file_list(processed_files)

    stream = ffmpeg.input(file_list_path, f='concat', safe=0)

    # 필요한 경우 필터 적용 (필요 없을 시 제거 가능)
    stream = apply_filters(stream, target_properties)

    stream = ffmpeg.output(stream, output_file, **encoding_options)
    stream = stream.overwrite_output()

    if debug_mode:
        logger.debug(f"최종 합치기 명령어: {' '.join(ffmpeg.compile(stream))}")

    process = ffmpeg.run_async(stream, cmd=FFMPEG_PATH, pipe_stdout=True, pipe_stderr=True)

    # 진행 상황 모니터링
    while True:
        output = process.stderr.readline().decode()
        if output == '' and process.poll() is not None:
            break
        if output:
            progress = parse_ffmpeg_progress(output)
            if progress is not None and progress_callback:
                # 진행률을 75%에서 100%로 조정
                adjusted_progress = 75 + int(progress * 0.25)
                progress_callback(adjusted_progress)

    process.wait()

    os.remove(file_list_path)


def parse_ffmpeg_progress(output: str) -> int:
    """
    FFmpeg 출력에서 진행 상황을 파싱하여 퍼센트 값을 반환합니다.
    """
    if "time=" in output:
        time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", output)
        if time_match:
            time_str = time_match.group(1)
            hours, minutes, seconds = map(float, time_str.split(":"))
            total_seconds = hours * 3600 + minutes * 60 + seconds
            # 진행률 계산 로직 필요 (예: 전체 길이를 알고 있는 경우)
            return int(total_seconds)  # 예시로 초 단위 반환
    return None


def process_all_media(
    input_files: List[str],
    output_file: str,
    encoding_options: Dict[str, str],
    debug_mode: bool = False,
    trim_values: List[Tuple[int, int]] = None,
    global_trim_start: int = 0,
    global_trim_end: int = 0,
    progress_callback=None
):
    """
    모든 미디어 파일을 처리하고 하나의 파일로 합칩니다.
    """
    # 디버그 모드 설정
    if debug_mode:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)

    if trim_values is None:
        trim_values = [(0, 0)] * len(input_files)

    # 전역 트림 값을 각 파일의 트림 값에 적용
    trim_values = [(ts + global_trim_start, te + global_trim_end) for ts, te in trim_values]

    # 타겟 속성 결정
    target_properties = get_target_properties(input_files, encoding_options, debug_mode)
    if not target_properties:
        logger.error("타겟 속성을 결정할 수 없습니다.")
        return

    # 입력 파일들의 속성 확인
    check_media_properties(input_files, target_properties, debug_mode)

    # 미디어 파일 처리
    media_files = list(zip(input_files, *zip(*trim_values)))
    processed_files, temp_files_to_remove = process_media_files(
        media_files, encoding_options, target_properties, debug_mode, idx=0, progress_callback=progress_callback
    )

    # 진행 상황 콜백 호출
    if progress_callback:
        progress_callback(75)  # 처리 완료 후 75% 진행

    # 파일 합치기
    concat_media_files(processed_files, output_file, encoding_options, target_properties, debug_mode, progress_callback=progress_callback)

    # 임시 파일 정리
    for temp_file in temp_files_to_remove:
        if os.path.exists(temp_file):
            os.remove(temp_file)
            logger.debug(f"임시 파일 삭제: {temp_file}")

    if progress_callback:
        progress_callback(100)  # 완료

    logger.info("모든 처리가 완료되었습니다.")
