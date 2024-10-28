# ffmpeg_utils.py

import os
import sys
import tempfile
import glob
import re
import shutil
import subprocess
from typing import List, Dict, Tuple
import ffmpeg
import time
import json
from utils import get_debug_mode, debug_print

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

# 전역 변수로 ffmpeg_path 설정
FFMPEG_PATH = None

def set_ffmpeg_path(path: str):
    global FFMPEG_PATH
    FFMPEG_PATH = path

def create_temp_file_list(temp_files: List[str]) -> str:
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as file_list:
        for video in temp_files:
            absolute_path = os.path.abspath(video).replace('\\', '/')
            file_list.write(f"file '{absolute_path}'\n")
    return file_list.name

def get_video_properties(input_file: str, debug_mode: bool = False) -> Dict[str, str]:
    """비디오 파일 또는 이미지 파일의 해상도와 SAR, DAR 값을 반환합니다."""
    if '%' in input_file:
        # 이미지 시퀀스인 경우
        pattern = input_file.replace('\\', '/')
        pattern = re.sub(r'%\d*d', '*', pattern)
        image_files = sorted(glob.glob(pattern))
        if not image_files:
            return {}
        probe_input = image_files[0]
    else:
        probe_input = input_file

    # ffprobe.exe 경로 설정
    ffprobe_path = os.path.join(os.path.dirname(FFMPEG_PATH), 'ffprobe.exe')

    try:
        probe_args = [ffprobe_path, '-v', 'quiet', '-print_format', 'json', '-show_format', '-show_streams', '-i', probe_input]
        if debug_mode:
            print("FFprobe 명령어:", ' '.join(probe_args))
        
        result = subprocess.run(probe_args, capture_output=True, text=True)
        if result.returncode != 0:
            if debug_mode:
                print("FFprobe 오류:", result.stderr)
            return {}
        
        probe = json.loads(result.stdout)
        video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        return {
            'width': video_stream['width'],
            'height': video_stream['height'],
            'sar': video_stream.get('sample_aspect_ratio', '1:1'),
            'dar': video_stream.get('display_aspect_ratio', 'N/A')
        }
    except subprocess.CalledProcessError as e:
        if debug_mode:
            print(f"FFprobe 실행 중 오류 발생: {e}")
        return {}
    except json.JSONDecodeError as e:
        if debug_mode:
            print(f"JSON 파싱 오류: {e}")
        return {}
    except Exception as e:
        if debug_mode:
            print(f"예상치 못한 오류 발생: {e}")
        return {}

def create_trimmed_video(input_file: str, trim_start: int, trim_end: int, index: int, encoding_options: Dict[str, str], target_resolution: str, target_sar: str, target_dar: str, debug_mode: bool) -> str:
    # trim_start와 trim_end가 모두 0이면 원본 파일을 그대로 반환
    if trim_start == 0 and trim_end == 0:
        return input_file

    temp_output = f'temp_trimmed_{index}.mp4'

    try:
        # 비디오 길이 가져오기
        probe = ffmpeg.probe(input_file)
        video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        duration = float(video_info['duration'])

        framerate = float(encoding_options.get("r", 30))
        start_time = trim_start / framerate
        end_time = duration - (trim_end / framerate)
        if start_time >= end_time:
            if debug_mode:
                print(f"'{input_file}'의 트림 설정이 잘못되었습니다.")
            return input_file

        # 지속 시간 계산
        duration_time = end_time - start_time

        # FFmpeg 명령어 생성
        stream = ffmpeg.input(input_file, ss=start_time, t=duration_time)
        
        # 필터 적용
        width, height = target_resolution.split('x')
        stream = stream.filter('scale', width=width, height=height)
        
        if target_sar != '1:1':
            stream = stream.filter('setsar', sar=target_sar)
        
        if target_dar != 'N/A':
            # DAR을 분수 형태로 변환
            dar_num, dar_den = map(int, target_dar.split(':'))
            stream = stream.filter('setdar', dar=f'{dar_num}/{dar_den}')

        # encoding_options에서 키 이름 변경
        encoding_options_modified = {k.replace('-', '_'): v for k, v in encoding_options.items()}
        stream = ffmpeg.output(stream, temp_output, **encoding_options_modified)
        stream = stream.overwrite_output()

        if debug_mode:
            print("트림 명령어:", ' '.join(ffmpeg.compile(stream)))
        
        ffmpeg.run(stream)

        if os.path.getsize(temp_output) > 0:
            return temp_output
        else:
            if debug_mode:
                print(f"경고: {input_file}의 트림된 파일이 비어 있습니다. 원본 파일을 사용합니다.")
            return input_file
    except ffmpeg.Error as e:
        if debug_mode:
            print(f"트림 중 에러 발생 {input_file}: {e}")
        return input_file

def get_target_properties(input_files: List[str], encoding_options: Dict[str, str], debug_mode: bool):
    # 커스텀 해상도 설정이 있는 경우
    if "-s" in encoding_options:
        target_resolution = encoding_options["-s"]
        width, height = target_resolution.split('x')
        target_properties = {
            'width': width,
            'height': height,
            'sar': '1:1',  # 커스텀 해상도에서는 기본값 사용
            'dar': 'N/A'
        }
        if debug_mode:
            print(f"커스텀 해상도 사용: {width}x{height}")
        return target_properties

    # 커스텀 해상도가 없는 경우 첫 번째 파일의 속성 사용
    first_input_file = input_files[0] if input_files else None
    if not first_input_file:
        if debug_mode:
            print("처리할 파일이 없습니다.")
        return {}

    target_properties = get_video_properties(first_input_file, debug_mode)
    if not target_properties:
        if debug_mode:
            print(f"'{first_input_file}'의 속성을 가져올 수 없습니다.")
        return {}

    return target_properties

def check_video_properties(input_files: List[str], target_properties: Dict[str, str], debug_mode: bool):
    for input_file in input_files:
        props = get_video_properties(input_file)
        input_sar = props.get('sar', '1:1')
        input_dar = props.get('dar', 'N/A')
        input_width = props.get('width')
        input_height = props.get('height')
        input_resolution = f"{input_width}x{input_height}" if input_width and input_height else 'Unknown'

        # 해상도 불일치는 디버그 모드에서만 정보 출력
        if input_width != target_properties['width'] or input_height != target_properties['height']:
            if debug_mode:
                print(f"해상도 불일치 (자동으로 조정됨): {input_resolution} -> {target_properties['width']}x{target_properties['height']}")
        
        # SAR과 DAR 불일치도 디버그 모드에서만 정보 출력
        if input_sar != target_properties['sar'] and debug_mode:
            print(f"SAR 불일치 (자동으로 조정됨): {input_sar} -> {target_properties['sar']}")
        if input_dar != target_properties['dar'] and debug_mode:
            print(f"DAR 불일치 (자동으로 조정됨): {input_dar} -> {target_properties['dar']}")

def apply_debug_options(encoding_options: Dict[str, str]):
    """디버그 모드에 따라 verbosity 옵션 적용"""
    debug_mode = get_debug_mode()  # 함수 호출
    # print(f"디버그 모드: {debug_mode}")
    
    if not debug_mode:
        # 디버그 모드가 꺼져있으면 quiet 모드 적용
        encoding_options['v'] = 'quiet'
    else:
        # 디버그 모드가 켜져있으면 quiet 모드 제거
        encoding_options.pop('v', None)
    return encoding_options

def process_video_files(video_files: List[Tuple[str, int, int]], encoding_options: Dict[str, str], target_properties: Dict[str, str], debug_mode: bool, idx: int) -> Tuple[List[str], List[str]]:
    # encoding_options 복사 후 디버그 옵션 적용
    encoding_options = encoding_options.copy()
    encoding_options = apply_debug_options(encoding_options)
    
    temp_video_files = []
    temp_files_to_remove = []

    for file_idx, (input_file, trim_start, trim_end) in enumerate(video_files):
        # trim_start와 trim_end가 모두 0이면 원본 파일을 그대로 사용
        if trim_start == 0 and trim_end == 0:
            temp_video_files.append(input_file)
        else:
            temp_file = create_trimmed_video(
                input_file, trim_start, trim_end, f"{idx}_{file_idx}", encoding_options,
                f"{target_properties['width']}x{target_properties['height']}",
                target_properties['sar'], target_properties['dar'], debug_mode
            )
            temp_video_files.append(temp_file)
            if temp_file != input_file:
                temp_files_to_remove.append(temp_file)

    if temp_video_files:
        file_list_path = create_temp_file_list(temp_video_files)
        temp_files_to_remove.append(file_list_path)

        if debug_mode:
            print("비디오 파일 목록 내용:")
            with open(file_list_path, 'r', encoding='utf-8') as f:
                print(f.read())

        video_output = f'temp_video_concat_{idx}.mp4'
        stream = ffmpeg.input(file_list_path, f='concat', safe=0)

        # 필터 적용
        stream = apply_filters(stream, target_properties)

        # encoding_options에서 키 이름 변경 (하이픈 제거)
        encoding_options_modified = {k.lstrip('-'): v for k, v in encoding_options.items()}
        # '_r' 옵션을 'r'로 수정
        if '_r' in encoding_options_modified:
            encoding_options_modified['r'] = encoding_options_modified.pop('_r')
        stream = ffmpeg.output(stream, video_output, **encoding_options_modified)
        stream = stream.overwrite_output()

        if debug_mode:
            print("비디오 파일 concat 명령어:", ' '.join(ffmpeg.compile(stream)))

        ffmpeg.run(stream, cmd=FFMPEG_PATH)
        temp_files_to_remove.append(video_output)
        return [video_output], temp_files_to_remove
    
    return temp_video_files, temp_files_to_remove

def process_image_sequences(image_sequences: List[Tuple[str, int, int]], encoding_options: Dict[str, str], target_properties: Dict[str, str], debug_mode: bool, idx: int) -> Tuple[List[str], List[str]]:
    # encoding_options 복사 후 디버그 옵션 적용
    encoding_options = encoding_options.copy()
    apply_debug_options(encoding_options)
    
    temp_files_to_remove = []
    processed_files = []

    for seq_idx, (input_file, trim_start, trim_end) in enumerate(image_sequences):
        pattern = input_file.replace('\\', '/')
        glob_pattern = re.sub(r'%\d*d', '*', pattern)
        image_files = sorted(glob.glob(glob_pattern))

        if not image_files:
            if debug_mode:
                print(f"이미지 시퀀스 '{input_file}'를 찾을 수 없습니다.")
            continue

        total_frames = len(image_files)
        frame_number_pattern = re.compile(r'(\d+)\.(\w+)$')
        first_image = os.path.basename(image_files[0])
        match = frame_number_pattern.search(first_image)
        if not match:
            if debug_mode:
                print(f"'{first_image}'에서 시작 프레임 번호를 추출할 수 없습니다.")
            continue

        original_start_frame = int(match.group(1))
        new_start_frame = original_start_frame + trim_start
        new_total_frames = total_frames - trim_start - trim_end

        if new_total_frames <= 0:
            if debug_mode:
                print(f"트림 후 남은 프레임이 없습니다: '{input_file}'")
            continue

        # 이미지 시퀀스 출력 파일 지정
        image_output = f'temp_image_sequence_{idx}_{seq_idx}.mp4'
        temp_files_to_remove.append(image_output)

        # 필터 체인 구성
        width, height = target_properties['width'], target_properties['height']
        filter_chain = [
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
        ]
        
        if target_properties['sar'] != '1:1':
            filter_chain.append(f"setsar={target_properties['sar']}")
        if target_properties['dar'] != 'N/A':
            filter_chain.append(f"setdar={target_properties['dar']}")
        
        filter_str = ','.join(filter_chain)

        # FFmpeg 명령어 생성
        args = [
            FFMPEG_PATH,
            '-framerate', str(encoding_options.get('r', 30)),
            '-start_number', str(new_start_frame),
            '-i', input_file.replace('\\', '/'),
            '-frames:v', str(new_total_frames),
            '-vf', filter_str
        ]

        # encoding_options에서 키 이름 변경
        for k, v in encoding_options.items():
            if k.startswith('-'):
                args.extend([k, str(v)])
            else:
                args.extend([f'-{k}', str(v)])

        args.append(image_output)

        if debug_mode:
            print("이미지 시퀀스 처리 명령어:", ' '.join(args))

        # FFmpeg 실행
        subprocess.run(args, check=True)
        processed_files.append(image_output)

    return processed_files, temp_files_to_remove

def concat_video_and_image(video_output: str, image_output: str, output_file: str, encoding_options: Dict[str, str], target_properties: Dict[str, str], debug_mode: bool) -> str:
    final_file_list = create_temp_file_list([video_output, image_output])

    stream = ffmpeg.input(final_file_list, f='concat', safe=0)

    # 필터 적용
    width, height = target_properties['width'], target_properties['height']
    stream = stream.filter('scale', width=width, height=height)
    
    if target_properties['sar'] != '1:1':
        stream = stream.filter('setsar', sar=target_properties['sar'])
    
    if target_properties['dar'] != 'N/A':
        # DAR을 분수 형태로 변환
        dar_num, dar_den = map(int, target_properties['dar'].split(':'))
        stream = stream.filter('setdar', dar=f'{dar_num}/{dar_den}')

    # encoding_options에서 키 이름 변경
    encoding_options_modified = {k.replace('-', '_'): v for k, v in encoding_options.items()}
    stream = ffmpeg.output(stream, output_file, **encoding_options_modified)
    stream = stream.overwrite_output()

    if debug_mode:
        print("최종 concat 명령어:", ' '.join(ffmpeg.compile(stream)))

    ffmpeg.run(stream)

    os.remove(final_file_list)
    return output_file

def concat_videos(input_files: List[str], output_file: str, encoding_options: Dict[str, str], debug_mode: bool = False, trim_values: List[Tuple[int, int]] = None, global_trim_start: int = 0, global_trim_end: int = 0, progress_callback=None):
    # encoding_options 복사 후 디버그 옵션 적용
    encoding_options = encoding_options.copy()
    encoding_options = apply_debug_options(encoding_options)
    
    if trim_values is None:
        trim_values = [(0, 0)] * len(input_files)

    # 전역 트림 값을 각 파일의 트림 값에 적용
    trim_values = [(ts + global_trim_start, te + global_trim_end) for ts, te in trim_values]

    target_properties = get_target_properties(input_files, encoding_options, debug_mode)
    if not target_properties:
        return

    check_video_properties([f for f in input_files if '%' not in f], target_properties, debug_mode)

    temp_files_to_remove = []
    processed_files = []

    total_files = len(input_files)
    for idx, ((input_file, trim_start, trim_end), trim_value) in enumerate(zip(zip(input_files, *zip(*trim_values)), trim_values)):
        if '%' in input_file:
            # 이미지 시퀀스 처리
            output, temp_files = process_image_sequences([(input_file, trim_start, trim_end)], encoding_options, target_properties, debug_mode, idx)
        else:
            # 비디오 파일 처리
            output, temp_files = process_video_files([(input_file, trim_start, trim_end)], encoding_options, target_properties, debug_mode, idx)
        
        processed_files.extend(output)
        temp_files_to_remove.extend(temp_files)

        if progress_callback:
            progress = int((idx + 1) / total_files * 50)  # 50%까지 진행
            progress_callback(progress)

    if not processed_files:
        if debug_mode:
            print("처리할 파일이 없습니다.")
        return

    # 최종 출력 생성
    if len(processed_files) > 1:
        final_file_list = create_temp_file_list(processed_files)
        temp_files_to_remove.append(final_file_list)

        stream = ffmpeg.input(final_file_list, f='concat', safe=0)
        stream = apply_filters(stream, target_properties)
        
        # encoding_options에서 키 이름 변경
        encoding_options_modified = {k.lstrip('-'): v for k, v in encoding_options.items()}
        stream = ffmpeg.output(stream, output_file, **encoding_options_modified)
        stream = stream.overwrite_output()

        if debug_mode:
            debug_print("최종 concat 명령어:", ' '.join(ffmpeg.compile(stream)))

        process = ffmpeg.run_async(stream, cmd=FFMPEG_PATH, pipe_stdout=True, pipe_stderr=True)
        
        # 진행 상황 모니터링
        while True:
            output = process.stderr.readline().decode()
            if output == '' and process.poll() is not None:
                break
            if output:
                progress = parse_ffmpeg_progress(output)
                if progress is not None and progress_callback:
                    progress_callback(50 + int(progress / 2))  # 50%에서 100%까지 진행
        
        process.wait()
    else:
        shutil.move(processed_files[0], output_file)

    # 임시 파일 정리
    for temp_file in temp_files_to_remove:
        if os.path.exists(temp_file):
            os.remove(temp_file)

    if debug_mode:
        print("인코딩이 완료되었습니다.")

    if progress_callback:
        progress_callback(100)  # 완료

    return output_file

def parse_ffmpeg_progress(output):
    if "time=" in output:
        time_parts = output.split("time=")[1].split()[0].split(":")
        if len(time_parts) == 3:
            hours, minutes, seconds = map(float, time_parts)
            total_seconds = hours * 3600 + minutes * 60 + seconds
            return min(int(total_seconds / 3600 * 100), 100)  # 최대 100%
    return None

# 새로운 헬퍼 함수들
def apply_filters(stream, target_properties):
    width, height = target_properties['width'], target_properties['height']
    # scale 필터 수정: force_original_aspect_ratio=decrease 옵션 추가
    stream = stream.filter('scale', width=width, height=height, force_original_aspect_ratio='decrease')
    
    # pad 필터 추가: 남는 공간을 검은색으로 채움
    stream = stream.filter('pad', width=width, height=height, x='(ow-iw)/2', y='(oh-ih)/2', color='black')
    
    if target_properties['sar'] != '1:1':
        stream = stream.filter('setsar', sar=target_properties['sar'])
    
    if target_properties['dar'] != 'N/A':
        dar_num, dar_den = map(int, target_properties['dar'].split(':'))
        stream = stream.filter('setdar', dar=f'{dar_num}/{dar_den}')
    
    return stream

def apply_encoding_options(stream, encoding_options, output_file):
    encoding_options_modified = {k.replace('-', '_'): v for k, v in encoding_options.items()}
    if '_r' in encoding_options_modified:
        encoding_options_modified['r'] = encoding_options_modified.pop('_r')
    return ffmpeg.output(stream, output_file, **encoding_options_modified)

