import os
import sys
import tempfile
import glob
import re
import shutil
import subprocess
from typing import List, Dict, Tuple
import ffmpeg

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

def create_temp_file_list(temp_files: List[str]) -> str:
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as file_list:
        for video in temp_files:
            absolute_path = os.path.abspath(video).replace('\\', '/')
            file_list.write(f"file '{absolute_path}'\n")
    return file_list.name

def get_video_properties(input_file: str) -> Dict[str, str]:
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

    try:
        probe = ffmpeg.probe(probe_input)
        video_stream = next(s for s in probe['streams'] if s['codec_type'] == 'video')
        return {
            'width': video_stream['width'],
            'height': video_stream['height'],
            'sar': video_stream.get('sample_aspect_ratio', '1:1'),
            'dar': video_stream.get('display_aspect_ratio', 'N/A')
        }
    except ffmpeg.Error:
        return {}

def create_trimmed_video(input_file: str, trim_start: int, trim_end: int, index: int, encoding_options: Dict[str, str], target_resolution: str, target_sar: str, target_dar: str, debug_mode: bool) -> str:
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

        if debug_mode:
            print("트림 명령어:", ' '.join(ffmpeg.compile(stream)))
        
        ffmpeg.run(stream, overwrite_output=True)

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

def get_target_properties(input_files: List[str], encoding_options: Dict[str, str], debug_mode: bool) -> Dict[str, str]:
    if "-s" in encoding_options:
        target_resolution = encoding_options["-s"]
        width, height = target_resolution.split('x')
        target_properties = {'width': width, 'height': height}
    else:
        first_input_file = input_files[0] if input_files else None
        if not first_input_file:
            if debug_mode:
                print("처리할 파일이 없습니다.")
            return {}

        target_properties = get_video_properties(first_input_file)
        if target_properties.get('width') and target_properties.get('height'):
            target_resolution = f"{target_properties['width']}x{target_properties['height']}"
            if debug_mode:
                print(f"타겟 해상도는 {target_resolution}입니다.")
        else:
            if debug_mode:
                print(f"'{first_input_file}'의 해상도를 가져올 수 없습니다.")
            return {}

    target_properties['sar'] = target_properties.get('sar', '1:1')
    target_properties['dar'] = target_properties.get('dar', 'N/A')
    if debug_mode:
        print(f"타겟 SAR: {target_properties['sar']}")
        print(f"타겟 DAR: {target_properties['dar']}")

    return target_properties

def check_video_properties(input_files: List[str], target_properties: Dict[str, str], debug_mode: bool):
    for input_file in input_files:
        props = get_video_properties(input_file)
        input_sar = props.get('sar', '1:1')
        input_dar = props.get('dar', 'N/A')
        input_width = props.get('width')
        input_height = props.get('height')
        input_resolution = f"{input_width}x{input_height}" if input_width and input_height else 'Unknown'

        mismatches = []
        if input_width != target_properties['width'] or input_height != target_properties['height']:
            mismatches.append(f"해상도 불일치: {input_resolution} != {target_properties['width']}x{target_properties['height']}")
        if input_sar != target_properties['sar']:
            mismatches.append(f"SAR 불일치: {input_sar} != {target_properties['sar']}")
        if input_dar != target_properties['dar']:
            mismatches.append(f"DAR 불일치: {input_dar} != {target_properties['dar']}")

        if mismatches:
            warning_message = f"경고: 파일 '{input_file}'의 속성이 타겟과 일치하지 않습니다:\n"
            for mismatch in mismatches:
                warning_message += f"  {mismatch}\n"
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, "속성 불일치 경고", warning_message)
            raise ValueError("속성 불일치로 인해 작업이 중지되었습니다.")

def process_video_files(video_files: List[Tuple[str, int, int]], encoding_options: Dict[str, str], target_properties: Dict[str, str], debug_mode: bool) -> Tuple[str, List[str]]:
    temp_video_files = []
    temp_files_to_remove = []

    for idx, (input_file, trim_start, trim_end) in enumerate(video_files):
        temp_file = create_trimmed_video(
            input_file, trim_start, trim_end, idx, encoding_options,
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

        video_output = 'temp_video_concat.mp4'
        stream = ffmpeg.input(file_list_path, f='concat', safe=0)

        # 필터 적용
        width, height = target_properties['width'], target_properties['height']
        stream = stream.filter('scale', width=width, height=height)
        
        if target_properties['sar'] != '1:1':
            stream = stream.filter('setsar', sar=target_properties['sar'])
        
        if target_properties['dar'] != 'N/A':
            dar_num, dar_den = map(int, target_properties['dar'].split(':'))
            stream = stream.filter('setdar', dar=f'{dar_num}/{dar_den}')

        encoding_options_modified = {k.replace('-', '_'): v for k, v in encoding_options.items()}
        stream = ffmpeg.output(stream, video_output, **encoding_options_modified)

        if debug_mode:
            print("비디오 파일 concat 명령어:", ' '.join(ffmpeg.compile(stream)))

        ffmpeg.run(stream, overwrite_output=True)
        temp_files_to_remove.append(video_output)
        return video_output, temp_files_to_remove
    
    return None, temp_files_to_remove

def process_image_sequences(image_sequences: List[Tuple[str, int, int]], encoding_options: Dict[str, str], target_properties: Dict[str, str], debug_mode: bool) -> Tuple[str, List[str]]:
    if not image_sequences:
        return None, []

    temp_files_to_remove = []
    input_commands = []
    filter_complex_parts = []
    filter_index = 0

    for idx, (input_file, trim_start, trim_end) in enumerate(image_sequences):
        pattern = input_file.replace('\\', '/')
        glob_pattern = re.sub(r'%\d*d', '*', pattern)
        image_files = sorted(glob.glob(glob_pattern))

        if not image_files:
            if debug_mode:
                print(f"이미지 시퀀스 '{input_file}'를 찾을 수 없습니다.")
            continue

        total_frames = len(image_files)

        # 시작 프레임 번호 추출
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

        # 입력 명령어 생성
        input_commands.extend([
            '-start_number', str(new_start_frame),
            '-i', input_file.replace('\\', '/')
        ])

        # 필터 생성
        filter_params = {
            'width': target_properties['width'],
            'height': target_properties['height']
        }
        if target_properties['sar'] != '1:1':
            filter_params['sar'] = target_properties['sar']
        if target_properties['dar'] != 'N/A':
            filter_params['dar'] = target_properties['dar']

        filter_chain = (
            f"[{filter_index}:v]trim=start_frame=0:end_frame={new_total_frames},"
            f"scale={target_properties['width']}:{target_properties['height']}"
        )
        if target_properties['sar'] != '1:1':
            filter_chain += f",setsar={target_properties['sar']}"
        if target_properties['dar'] != 'N/A':
            filter_chain += f",setdar={target_properties['dar']}"
        filter_chain += f"[v{filter_index}];"

        filter_complex_parts.append(filter_chain)
        filter_index += 1

    if filter_index == 0:
        return None, temp_files_to_remove

    # 필터 복합 생성
    concat_inputs = ''.join([f"[v{i}]" for i in range(filter_index)])
    filter_complex = ''.join(filter_complex_parts) + f"{concat_inputs}concat=n={filter_index}:v=1:a=0 [v]"

    # 이미지 시퀀스 출력 파일 지정
    image_output = 'temp_image_concat.mp4'
    temp_files_to_remove.append(image_output)

    # FFmpeg 명령어 생성
    args = [
        'ffmpeg',
        *input_commands,
        '-filter_complex', filter_complex,
        '-map', '[v]'
    ]

    # encoding_options에서 키 이름 변경
    for k, v in encoding_options.items():
        if k.startswith('-'):
            args.extend([k, str(v)])
        else:
            args.extend([f'-{k}', str(v)])

    args.append(image_output)

    if debug_mode:
        print("이미지 시퀀스 concat 명령어:", ' '.join(args))

    # FFmpeg 실행
    subprocess.run(args, check=True)

    return image_output, temp_files_to_remove

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

    if debug_mode:
        print("최종 concat 명령어:", ' '.join(ffmpeg.compile(stream)))

    ffmpeg.run(stream, overwrite_output=True)

    os.remove(final_file_list)
    return output_file

def concat_videos(input_files: List[str], output_file: str, encoding_options: Dict[str, str], debug_mode: bool = False, trim_values: List[Tuple[int, int]] = None, global_trim_start: int = 0, global_trim_end: int = 0):
    if trim_values is None:
        trim_values = [(0, 0)] * len(input_files)

    # 전역 트림 값을 각 파일의 트림 값에 적용
    trim_values = [(ts + global_trim_start, te + global_trim_end) for ts, te in trim_values]

    # 비디오 파일과 이미지 시퀀스 파일을 분리
    video_files = [(f, ts, te) for f, (ts, te) in zip(input_files, trim_values) if '%' not in f]
    image_sequences = [(f, ts, te) for f, (ts, te) in zip(input_files, trim_values) if '%' in f]

    target_properties = get_target_properties(input_files, encoding_options, debug_mode)
    if not target_properties:
        return

    check_video_properties([f for f, _, _ in video_files], target_properties, debug_mode)

    temp_files_to_remove = []

    # 비디오 파일 처리
    video_output, video_temp_files = process_video_files(video_files, encoding_options, target_properties, debug_mode)
    temp_files_to_remove.extend(video_temp_files)

    # 이미지 시퀀스 처리
    image_output, image_temp_files = process_image_sequences(image_sequences, encoding_options, target_properties, debug_mode)
    temp_files_to_remove.extend(image_temp_files)

    # 최종 출력 생성
    if video_output and image_output:
        final_output = concat_video_and_image(video_output, image_output, output_file, encoding_options, target_properties, debug_mode)
        temp_files_to_remove.extend([video_output, image_output])
    elif video_output:
        shutil.move(video_output, output_file)
        final_output = output_file
    elif image_output:
        shutil.move(image_output, output_file)
        final_output = output_file
    else:
        if debug_mode:
            print("처리할 파일이 없습니다.")
        return

    # 임시 파일 정리
    for temp_file in temp_files_to_remove:
        if os.path.exists(temp_file):
            os.remove(temp_file)

    if debug_mode:
        print("인코딩이 완료되었습니다.")

    return final_output
