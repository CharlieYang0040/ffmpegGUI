# ffmpeg_utils.py

import os
import sys
import subprocess
import tempfile
import re
from typing import List, Dict, Tuple

if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.abspath(__file__))

FFMPEG_PATH = os.path.join(base_path, 'libs', 'ffmpeg-7.1-full_build', 'bin', 'ffmpeg.exe')

def add_encoding_options(command: List[str], encoding_options: Dict[str, str]) -> List[str]:
    return [*command, *[item for option, value in encoding_options.items() if value != "none" for item in [option, value]]]

def is_image_sequence(file_path: str) -> bool:
    return '%' in file_path

def create_temp_file_list(input_files: List[str], start_numbers: List[str]) -> str:
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt', encoding='utf-8') as file_list:
        for input_file, start_number in zip(input_files, start_numbers):
            absolute_path = os.path.abspath(input_file).replace('\\', '/')
            file_list.write(f"file '{absolute_path}'\n")
            if is_image_sequence(input_file) and start_number is not None:
                file_list.write(f"start_number {start_number}\n")
    return file_list.name

def apply_2f_offset(input_files: List[str], start_numbers: List[str], debug_mode: bool) -> Tuple[List[str], List[str]]:
    temp_files = []
    new_start_numbers = []
    
    for i, (input_file, start_number) in enumerate(zip(input_files, start_numbers)):
        if is_image_sequence(input_file):
            dir_path, filename = os.path.split(input_file)
            base, ext = os.path.splitext(filename)
            pattern = base.replace('%04d', r'(\d+)')
            
            files = os.listdir(dir_path)
            frame_numbers = []
            
            for file in files:
                match = re.match(pattern + ext, file)
                if match:
                    frame_numbers.append(int(match.group(1)))
            
            if frame_numbers:
                min_frame = min(frame_numbers)
                offset_frame = min_frame + 2  # 2프레임 오프셋 적용
                new_start_numbers.append(str(offset_frame))
                temp_files.append(input_file)
            else:
                new_start_numbers.append(start_number)
                temp_files.append(input_file)
        else:
            temp_output = f'temp_output_{i}.mp4'
            trim_command = [
                FFMPEG_PATH, '-i', input_file, '-ss', '0.0667',
                '-c:v', 'libx264', '-c:a', 'aac', '-y', temp_output
            ]
            
            try:
                subprocess.run(trim_command, check=True)
                if os.path.getsize(temp_output) > 0:
                    temp_files.append(temp_output)
                    new_start_numbers.append(None)
                else:
                    if debug_mode:
                        print(f"경고: {input_file}의 출력 파일이 비어 있습니다. 원본 파일을 사용합니다.")
                    temp_files.append(input_file)
                    new_start_numbers.append(None)
            except subprocess.CalledProcessError as e:
                if debug_mode:
                    print(f"에러 발생 {input_file}: {e}")
                temp_files.append(input_file)
                new_start_numbers.append(None)
    
    return temp_files, new_start_numbers

def create_ffmpeg_command(input_files: List[str], start_numbers: List[str], encoding_options: Dict[str, str], output_file: str) -> Tuple[List[str], str]:
    command = [FFMPEG_PATH, "-y"]
    
    if all(is_image_sequence(file) for file in input_files):
        for i, (input_file, start_number) in enumerate(zip(input_files, start_numbers)):
            command.extend(["-start_number", start_number, "-i", input_file])
        
        # filter_complex를 사용하여 이미지 시퀀스 입력을 연결
        filter_complex = "[" + "][".join(f"{i}:v" for i in range(len(input_files))) + "]"
        filter_complex += f"concat=n={len(input_files)}:v=1[outv]"
        command.extend(["-filter_complex", filter_complex])
        command.extend(["-map", "[outv]"])
        file_list_path = None
    else:
        file_list_path = create_temp_file_list(input_files, start_numbers)
        command.extend(["-f", "concat", "-safe", "0", "-i", file_list_path])
        command.extend(["-map", "0:v"])
    
    command = add_encoding_options(command, encoding_options)
    command.append(output_file)
    return command, file_list_path

def concat_videos(input_files: List[str], output_file: str, encoding_options: Dict[str, str], use_2f_offset: bool = False, debug_mode: bool = False):
    start_numbers = encoding_options.pop("-start_number", [None] * len(input_files))
    
    if use_2f_offset:
        temp_files, start_numbers = apply_2f_offset(input_files, start_numbers, debug_mode)
    else:
        temp_files = input_files
    
    command, file_list_path = create_ffmpeg_command(temp_files, start_numbers, encoding_options, output_file)

    if debug_mode:
        print("실행할 명령어:", ' '.join(command))

    try:
        subprocess.run(command, check=True)
        if debug_mode:
            print("인코딩이 완료되었습니다.")
    except subprocess.CalledProcessError as e:
        if debug_mode:
            print(f"FFmpeg 실행 중 에러 발생: {e}")
        raise
    finally:
        if file_list_path and os.path.exists(file_list_path):
            os.remove(file_list_path)
        if use_2f_offset:
            for temp_file in temp_files:
                if temp_file.startswith('temp_output_') and os.path.exists(temp_file):
                    os.remove(temp_file)
        if debug_mode:
            print("임시 파일이 정리되었습니다.")
