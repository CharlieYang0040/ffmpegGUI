# ffmpeg_utils.py

import os
import sys
import subprocess
import tempfile
from typing import List, Dict

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

def apply_2f_offset(input_files: List[str], debug_mode: bool) -> List[str]:
    temp_files = []
    for i, video in enumerate(input_files):
        temp_output = f'temp_output_{i}.mp4'
        trim_command = [
            FFMPEG_PATH, '-i', video, '-ss', '0.0667',
            '-c:v', 'libx264', '-c:a', 'aac', '-y', temp_output
        ]
        try:
            subprocess.run(trim_command, check=True)
            if os.path.getsize(temp_output) > 0:
                temp_files.append(temp_output)
            else:
                if debug_mode:
                    print(f"경고: {video}의 출력 파일이 비어 있습니다. 원본 파일을 사용합니다.")
                temp_files.append(video)
        except subprocess.CalledProcessError as e:
            if debug_mode:
                print(f"에러 발생 {video}: {e}")
            temp_files.append(video)
    return temp_files

def create_ffmpeg_command(file_list_path: str, encoding_options: Dict[str, str], output_file: str) -> List[str]:
    command = [FFMPEG_PATH, '-y', '-f', 'concat', '-safe', '0', '-i', file_list_path]
    if "-r" in encoding_options:
        command.extend(["-r", encoding_options["-r"]])
    if "-s" in encoding_options:
        command.extend(["-s", encoding_options["-s"]])
    command = add_encoding_options(command, encoding_options)
    command.append(output_file)
    return command

def concat_videos(input_files: List[str], output_file: str, encoding_options: Dict[str, str], use_2f_offset: bool = False, debug_mode: bool = False):
    temp_files = apply_2f_offset(input_files, debug_mode) if use_2f_offset else input_files
    file_list_path = create_temp_file_list(temp_files)

    if debug_mode:
        print("파일 목록 내용:")
        with open(file_list_path, 'r', encoding='utf-8') as f:
            print(f.read())

    command = create_ffmpeg_command(file_list_path, encoding_options, output_file)

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
        os.remove(file_list_path)
        if use_2f_offset:
            for temp_file in temp_files:
                if temp_file.startswith('temp_output_') and os.path.exists(temp_file):
                    os.remove(temp_file)
        if debug_mode:
            print("임시 파일이 정리되었습니다.")
