# utils.py

import os
import re
import glob
from collections import defaultdict
from PySide6.QtCore import QSettings

# 설정에서 디버그 모드 상태 로드
settings = QSettings('LHCinema', 'ffmpegGUI')
DEBUG_MODE = settings.value('debug_mode', False, type=bool)

def get_debug_mode():
    """현재 디버그 모드 상태 반환"""
    return DEBUG_MODE

def set_debug_mode(value: bool):
    """디버그 모드 설정 및 저장"""
    global DEBUG_MODE
    DEBUG_MODE = value
    settings.setValue('debug_mode', value)
    print(f"[utils.py] DEBUG_MODE 설정됨: {DEBUG_MODE}")  # 디버그용
    return DEBUG_MODE  # 설정된 값 반환

def debug_print(*args, **kwargs):
    """디버그 모드일 때만 print 실행"""
    if get_debug_mode():
        print(*args, **kwargs)

def is_media_file(file_path):
    _, ext = os.path.splitext(file_path)
    return ext.lower() in ['.mp4', '.avi', '.mov', '.mkv', '.jpg', '.jpeg', '.png', '.bmp']

def is_image_file(file_path):
    _, ext = os.path.splitext(file_path)
    return ext.lower() in ['.jpg', '.jpeg', '.png', '.bmp']

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
            else:
                processed_files.append(file_path)
        else:
            processed_files.append(file_path)

    for sequence, frame_files in sequences.items():
        if len(frame_files) > 1:
            processed_files.append(sequence)
        else:
            processed_files.append(frame_files[0][1])

    return processed_files

def process_file(file_path):
    _, ext = os.path.splitext(file_path)
    return process_image_file(file_path) if ext.lower() in ['.jpg', '.jpeg', '.png'] else file_path

def process_image_file(file_path):
    dir_path, file_name = os.path.split(file_path)
    base_name, ext = os.path.splitext(file_name)

    match = re.search(r'(\d+)$', base_name)
    if match:
        number_part = match.group(1)
        prefix = base_name[:-len(number_part)]
        pattern = f"{prefix}[0-9]*{ext}"
        matching_files = [f for f in os.listdir(dir_path) if re.match(pattern, f)]

        if len(matching_files) > 1:
            return os.path.join(dir_path, f"{prefix}%0{len(number_part)}d{ext}")

    return file_path

def get_sequence_start_number(sequence_path):
    dir_path, filename = os.path.split(sequence_path)
    base, ext = os.path.splitext(filename)
    pattern = base.replace('%04d', r'(\d+)')

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
    pattern = sequence_pattern.replace('%04d', '*')
    files = sorted(glob.glob(pattern))
    return files[0] if files else ""

def format_drag_to_output(file_path):
    print(f"[format_drag_to_output] 입력 파일: {file_path}")

    dir_path, filename = os.path.split(file_path)

    base_name = os.path.splitext(filename)[0]
    base_name = re.sub(r'%\d*d', '', base_name)
    base_name = base_name.rstrip('.')
    
    print(f"[format_drag_to_output] 변환된 이름: {base_name}")
    return base_name
