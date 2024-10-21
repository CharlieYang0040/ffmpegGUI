import os
import sys
import subprocess
import tempfile
import glob
import re
import shutil
from typing import List, Dict, Tuple

if getattr(sys, 'frozen', False):
    # PyInstaller로 패키징된 경우 실행 파일의 위치를 찾습니다.
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

FFMPEG_PATH = os.path.join(base_path, 'libs', 'ffmpeg-7.1-full_build', 'bin', 'ffmpeg.exe')

def add_encoding_options(command: List[str], encoding_options: Dict[str, str]) -> List[str]:
    return [*command, *[item for option, value in encoding_options.items() if value != "none" for item in [option, value]]]

def create_temp_file_list(temp_files: List[str]) -> str:
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as file_list:
        for video in temp_files:
            absolute_path = os.path.abspath(video).replace('\\', '/')
            file_list.write(f"file '{absolute_path}'\n")
    return file_list.name

def create_trimmed_video(input_file: str, trim_start: int, trim_end: int, index: int, encoding_options: Dict[str, str], target_resolution: str, target_sar: str, target_dar: str, debug_mode: bool) -> str:
    temp_output = f'temp_trimmed_{index}.mp4'

    # 비디오 길이 가져오기
    duration_command = [
        os.path.join(os.path.dirname(FFMPEG_PATH), 'ffprobe.exe'),
        '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        input_file
    ]
    result = subprocess.run(duration_command, capture_output=True, text=True)
    duration_str = result.stdout.strip()
    if not duration_str:
        if debug_mode:
            print(f"'{input_file}'의 길이를 가져올 수 없습니다.")
        return input_file
    duration = float(duration_str)

    framerate = float(encoding_options.get("-r", 30))
    start_time = trim_start / framerate
    end_time = duration - (trim_end / framerate)
    if start_time >= end_time:
        if debug_mode:
            print(f"'{input_file}'의 트림 설정이 잘못되었습니다.")
        return input_file

    # 지속 시간 계산
    duration_time = end_time - start_time

    # 비디오 속성 가져오기
    props = get_video_properties(input_file)
    input_sar = props.get('sar', '1:1')
    input_dar = props.get('dar', 'N/A')

    # 필터 체인 생성
    filter_chain = f"scale={target_resolution}"
    if input_sar != target_sar:
        filter_chain += f",setsar={target_sar}"
    if input_dar != target_dar and input_dar != 'N/A' and target_dar != 'N/A':
        filter_chain += f",setdar={target_dar}"

    # FFmpeg 명령어 생성
    trim_command = [
        FFMPEG_PATH,
        '-y',
        '-ss', str(start_time),
        '-i', input_file,
        '-t', str(duration_time),
        '-vf', filter_chain,
        '-c:v', 'libx264',
        '-c:a', 'copy',
    ]

    # 인코딩 옵션 적용
    for key, value in encoding_options.items():
        if key not in ["-r", "-s"]:
            trim_command.extend([key, value])

    # 프레임레이트 설정
    if "-r" in encoding_options:
        trim_command.extend(["-r", encoding_options["-r"]])

    # 출력 파일 지정
    trim_command.append(temp_output)

    try:
        if debug_mode:
            print("트림 명령어:", ' '.join(trim_command))
        subprocess.run(trim_command, check=True)
        if os.path.getsize(temp_output) > 0:
            return temp_output
        else:
            if debug_mode:
                print(f"경고: {input_file}의 트림된 파일이 비어 있습니다. 원본 파일을 사용합니다.")
            return input_file
    except subprocess.CalledProcessError as e:
        if debug_mode:
            print(f"트림 중 에러 발생 {input_file}: {e}")
        return input_file

def get_video_properties(input_file: str) -> Dict[str, str]:
    """비디오 파일 또는 이미지 파일의 해상도와 SAR, DAR 값을 반환합니다."""
    if '%' in input_file:
        # 이미지 시퀀스인 경우
        pattern = input_file.replace('\\', '/')
        # %숫자d 패턴을 '*'로 치환하여 실제 파일 목록을 찾습니다.
        pattern = re.sub(r'%\d*d', '*', pattern)
        image_files = sorted(glob.glob(pattern))
        if not image_files:
            return {}
        # 첫 번째 이미지 파일 선택
        first_image_file = image_files[0]
        probe_input = first_image_file
    else:
        # 비디오 파일인 경우
        probe_input = input_file

    probe_command = [
        os.path.join(os.path.dirname(FFMPEG_PATH), 'ffprobe.exe'),
        '-v', 'error',
        '-select_streams', 'v:0',
        '-show_entries', 'stream=width,height,sample_aspect_ratio,display_aspect_ratio',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        probe_input
    ]
    result = subprocess.run(probe_command, capture_output=True, text=True)
    output = result.stdout.strip()
    properties = {}
    if output:
        lines = output.split('\n')
        if len(lines) >= 4:
            properties['width'] = lines[0]
            properties['height'] = lines[1]
            properties['sar'] = lines[2]
            properties['dar'] = lines[3]
    return properties

def concat_videos(input_files: List[str], output_file: str, encoding_options: Dict[str, str], debug_mode: bool = False, trim_values: List[Tuple[int, int]] = None):
    if trim_values is None:
        trim_values = [(0, 0)] * len(input_files)

    # 비디오 파일과 이미지 시퀀스 파일을 분리
    video_files = []
    image_sequences = []

    for idx, (input_file, (trim_start, trim_end)) in enumerate(zip(input_files, trim_values)):
        if '%' in input_file:
            # 이미지 시퀀스 파일 처리
            image_sequences.append((input_file, trim_start, trim_end))
        else:
            # 비디오 파일 처리
            video_files.append((input_file, trim_start, trim_end))

    # 타겟 속성 결정
    if "-s" in encoding_options:
        target_resolution = encoding_options["-s"]
        width, height = target_resolution.split('x')
        target_properties = {'width': width, 'height': height}
    else:
        # 첫 번째 입력 파일의 속성을 사용
        if video_files:
            first_input_file = video_files[0][0]
        elif image_sequences:
            first_input_file = image_sequences[0][0]
        else:
            if debug_mode:
                print("처리할 파일이 없습니다.")
            return

        target_properties = get_video_properties(first_input_file)
        if target_properties.get('width') and target_properties.get('height'):
            target_resolution = f"{target_properties['width']}x{target_properties['height']}"
            if debug_mode:
                print(f"타겟 해상도는 {target_resolution}입니다.")
        else:
            if debug_mode:
                print(f"'{first_input_file}'의 해상도를 가져올 수 없습니다.")
            return

    # 타겟 SAR과 DAR 저장
    target_sar = target_properties.get('sar', '1:1')
    target_dar = target_properties.get('dar', 'N/A')
    if debug_mode:
        print(f"타겟 SAR: {target_sar}")
        print(f"타겟 DAR: {target_dar}")

    # 모든 입력 파일의 속성 확인
    all_input_files = [file for file, _, _ in video_files + image_sequences]
    for input_file in all_input_files:
        props = get_video_properties(input_file)
        input_sar = props.get('sar', '1:1')
        input_dar = props.get('dar', 'N/A')
        input_width = props.get('width')
        input_height = props.get('height')
        input_resolution = f"{input_width}x{input_height}" if input_width and input_height else 'Unknown'

        mismatches = []
        if input_width != target_properties['width'] or input_height != target_properties['height']:
            mismatches.append(f"해상도 불일치: {input_resolution} != {target_resolution}")
        if input_sar != target_sar:
            mismatches.append(f"SAR 불일치: {input_sar} != {target_sar}")
        if input_dar != target_dar:
            mismatches.append(f"DAR 불일치: {input_dar} != {target_dar}")

        if mismatches:
            warning_message = f"경고: 파일 '{input_file}'의 속성이 타겟과 일치하지 않습니다:\n"
            for mismatch in mismatches:
                warning_message += f"  {mismatch}\n"
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(None, "속성 불일치 경고", warning_message)
            raise ValueError("속성 불일치로 인해 작업이 중지되었습니다.")
            # 여기서 필요한 작업을 수행합니다.

    # 비디오 파일 처리
    if video_files:
        temp_video_files = []
        for idx, (input_file, trim_start, trim_end) in enumerate(video_files):
            # 트림 및 스케일링 적용
            temp_file = create_trimmed_video(
                input_file, trim_start, trim_end, idx, encoding_options,
                target_resolution, target_sar, target_dar, debug_mode
            )
            temp_video_files.append(temp_file)

        # 비디오 파일 목록 생성
        file_list_path = create_temp_file_list(temp_video_files)

        if debug_mode:
            print("비디오 파일 목록 내용:")
            with open(file_list_path, 'r', encoding='utf-8') as f:
                print(f.read())

        # 비디오 파일 연결
        video_output = 'temp_video_concat.mp4'
        concat_command = [FFMPEG_PATH, '-y', '-f', 'concat', '-safe', '0', '-i', file_list_path]

        # 인코딩 옵션 적용
        concat_command.extend(['-c:v', 'libx264'])
        for key, value in encoding_options.items():
            if key not in ["-r", "-s"]:
                concat_command.extend([key, value])

        # 프레임레이트 설정
        if "-r" in encoding_options:
            concat_command.extend(["-r", encoding_options["-r"]])

        # 출력 파일 지정
        concat_command.append(video_output)

        if debug_mode:
            print("비디오 파일 concat 명령어:", ' '.join(concat_command))

        # 비디오 파일 연결 실행
        subprocess.run(concat_command, check=True)

        # 임시 파일 정리
        os.remove(file_list_path)
        for temp_file in temp_video_files:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        if debug_mode:
            print("비디오 임시 파일이 정리되었습니다.")
    else:
        video_output = None

    # 이미지 시퀀스 파일 처리
    if image_sequences:
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

            # 입력 파일의 속성 가져오기
            props = get_video_properties(input_file)
            input_sar = props.get('sar', '1:1')
            input_dar = props.get('dar', 'N/A')

            # 필터 생성
            filter_chain = f"[{filter_index}:v]trim=start_frame=0:end_frame={new_total_frames},scale={target_resolution}"
            if input_sar != target_sar:
                filter_chain += f",setsar={target_sar}"
            if input_dar != target_dar and input_dar != 'N/A' and target_dar != 'N/A':
                filter_chain += f",setdar={target_dar}"
            filter_chain += f"[v{filter_index}];"
            filter_complex_parts.append(filter_chain)
            filter_index += 1

        # 필터 복합 생성
        concat_inputs = ''.join([f"[v{i}]" for i in range(filter_index)])
        filter_complex = ''.join(filter_complex_parts) + f"{concat_inputs}concat=n={filter_index}:v=1:a=0 [v]"

        # 이미지 시퀀스 출력 파일 지정
        image_output = 'temp_image_concat.mp4'

        # 이미지 시퀀스 연결 명령어 생성
        command = [FFMPEG_PATH, '-y'] + input_commands + ['-filter_complex', filter_complex, '-map', '[v]']

        # 인코딩 옵션 적용
        command.extend(['-c:v', 'libx264'])
        for key, value in encoding_options.items():
            if key not in ["-r", "-s"]:
                command.extend([key, value])

        # 프레임레이트 설정
        if "-r" in encoding_options:
            command.extend(["-r", encoding_options["-r"]])

        # 출력 파일 지정
        command.append(image_output)

        if debug_mode:
            print("이미지 시퀀스 concat 명령어:", ' '.join(command))

        # 이미지 시퀀스 연결 실행
        subprocess.run(command, check=True)
    else:
        image_output = None

    # 비디오 파일과 이미지 시퀀스 파일을 모두 처리한 경우, 두 결과를 연결
    if video_output and image_output:
        final_file_list = create_temp_file_list([video_output, image_output])

        if debug_mode:
            print("최종 파일 목록 내용:")
            with open(final_file_list, 'r', encoding='utf-8') as f:
                print(f.read())

        final_concat_command = [FFMPEG_PATH, '-y', '-f', 'concat', '-safe', '0', '-i', final_file_list]

        # 인코딩 옵션 적용
        final_concat_command.extend(['-c:v', 'libx264'])
        for key, value in encoding_options.items():
            if key not in ["-r", "-s"]:
                final_concat_command.extend([key, value])

        # 프레임레이트 설정
        if "-r" in encoding_options:
            final_concat_command.extend(["-r", encoding_options["-r"]])

        # 출력 파일 지정
        final_concat_command.append(output_file)

        if debug_mode:
            print("최종 concat 명령어:", ' '.join(final_concat_command))

        # 최종 연결 실행
        subprocess.run(final_concat_command, check=True)

        # 임시 파일 정리
        os.remove(final_file_list)
        os.remove(video_output)
        os.remove(image_output)
        if debug_mode:
            print("최종 임시 파일이 정리되었습니다.")
    elif video_output:
        # 비디오 출력만 있는 경우
        try:
            shutil.move(video_output, output_file)
            if debug_mode:
                print(f"파일 이동 완료: {video_output} -> {output_file}")
        except PermissionError:
            print(f"권한 오류: {output_file}에 접근할 수 없습니다.")
        except FileNotFoundError:
            print(f"파일을 찾을 수 없음: {video_output}")
        except Exception as e:
            print(f"파일 이동 중 오류 발생: {e}")
    elif image_output:
        # 이미지 출력만 있는 경우
        try:
            shutil.move(image_output, output_file)
            if debug_mode:
                print(f"파일 이동 완료: {image_output} -> {output_file}")
        except PermissionError:
            print(f"권한 오류: {output_file}에 접근할 수 없습니다.")
        except FileNotFoundError:
            print(f"파일을 찾을 수 없음: {image_output}")
        except Exception as e:
            print(f"파일 이동 중 오류 발생: {e}")
    else:
        if debug_mode:
            print("처리할 파일이 없습니다.")

    if debug_mode:
        print("인코딩이 완료되었습니다.")
