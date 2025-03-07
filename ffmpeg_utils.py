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
from utils import is_webp_file
import subprocess

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
    idx: int,
    progress_callback=None,
    use_frame_based_trim: bool = False
) -> str:
    """
    비디오 파일을 처리하고 임시 출력 파일을 반환합니다.
    진행률 콜백을 통해 처리 진행 상황을 보고합니다.
    """
    temp_output = f'temp_output_{idx}.mp4'
    try:
        logger.info(f"비디오 파일 처리 시작: {input_file}")

        if progress_callback:
            progress_callback(5)  # 시작 진행률

        # 비디오 속성 가져오기
        video_properties = get_media_properties(input_file, debug_mode)
        
        if progress_callback:
            progress_callback(15)  # 속성 분석 완료

        # 비디오 길이 계산
        duration = float(video_properties.get('duration', 0))
        if duration <= 0:
            logger.warning(f"'{input_file}'의 길이를 가져올 수 없습니다.")
            duration = 0

        # 인코딩 옵션 설정
        encoding_options = get_optimal_encoding_options(encoding_options)

        # 비디오 총 프레임 수 계산
        fps = float(video_properties.get('r', 30))
        total_frames = int(duration * fps)
        
        # 트림 후 남은 프레임 수 계산
        new_total_frames = total_frames - trim_start - trim_end
        if new_total_frames <= 0:
            raise ValueError("트림 후 남은 프레임이 없습니다.")
        
        # 트림 끝 프레임 계산
        end_frame = total_frames - trim_end
        
        if debug_mode:
            logger.debug(f"비디오 속성: {video_properties}")
            logger.debug(f"총 프레임 수: {total_frames}")
            logger.debug(f"트림 정보 - 시작 프레임: {trim_start}, 끝 프레임: {end_frame}, 남은 프레임 수: {new_total_frames}")

        if progress_callback:
            progress_callback(20)  # 트림 계산 완료

        # 프레임 단위 트림 방식 선택 (초 단위 변환 또는 프레임 단위 직접 트림)
        # use_frame_based_trim 매개변수를 그대로 사용
        
        if use_frame_based_trim:
            # 프레임 단위 직접 트림 (select 필터 사용)
            # 입력 옵션 설정
            input_args = {
                'probesize': '100M',
                'analyzeduration': '100M'
            }
            
            # 필터 설정 (프레임 번호로 직접 선택)
            vf_filter = f"select=between(n\\,{trim_start}\\,{end_frame}),setpts=PTS-STARTPTS"
            af_filter = "aselect=between(n\\,{0}\\,{1}),asetpts=PTS-STARTPTS".format(
                int(trim_start * (float(video_properties.get('sample_rate', 44100)) / fps)),
                int(end_frame * (float(video_properties.get('sample_rate', 44100)) / fps))
            )
            
            if debug_mode:
                logger.debug(f"프레임 단위 트림 필터: {vf_filter}")
                logger.debug(f"오디오 트림 필터: {af_filter}")
            
            if progress_callback:
                progress_callback(25)  # 옵션 설정 완료
            
            # 스트림 생성
            stream = ffmpeg.input(input_file, **input_args)
            
            # 비디오 필터 적용
            video_stream = stream.video.filter('select', f'between(n,{trim_start},{end_frame})').filter('setpts', 'PTS-STARTPTS')
            
            # 오디오 필터 적용 (오디오 스트림이 있는 경우)
            try:
                audio_stream = stream.audio.filter('aselect', f'between(n,{trim_start},{end_frame})').filter('asetpts', 'PTS-STARTPTS')
                # 필터 적용 후 추가 필터 적용
                if target_properties:
                    video_stream = apply_filters(video_stream, target_properties)
                
                # 출력 스트림 설정 (비디오 + 오디오)
                stream = ffmpeg.output(video_stream, audio_stream, temp_output, **encoding_options)
            except Exception as e:
                logger.warning(f"오디오 스트림 처리 중 오류 발생: {e}")
                # 오디오 스트림이 없는 경우 비디오만 처리
                if target_properties:
                    video_stream = apply_filters(video_stream, target_properties)
                
                # 출력 스트림 설정 (비디오만)
                stream = ffmpeg.output(video_stream, temp_output, **encoding_options)
        else:
            # 기존 방식: 초 단위로 변환하여 트림
            # 트림 값을 초 단위로 변환
            trim_start_sec = trim_start / fps if fps > 0 else 0
            trim_end_sec = trim_end / fps if fps > 0 else 0

            # 새 길이 계산
            new_duration = duration - trim_start_sec - trim_end_sec
            
            if debug_mode:
                logger.debug(f"트림 정보 - 시작: {trim_start_sec}초, 끝: {trim_end_sec}초, 새 길이: {new_duration}초")

            # 입력 옵션 설정
            input_args = {
                'probesize': '100M',
                'analyzeduration': '100M'
            }

            # 시작 시간이 있으면 추가
            if trim_start_sec > 0:
                input_args['ss'] = str(trim_start_sec)

            # 길이 제한이 있으면 추가
            if new_duration < duration:
                encoding_options['t'] = str(new_duration)

            if debug_mode:
                logger.debug(f"입력 옵션: {input_args}")
                logger.debug(f"인코딩 옵션: {encoding_options}")

            if progress_callback:
                progress_callback(25)  # 옵션 설정 완료

            # 스트림 생성
            stream = ffmpeg.input(input_file, **input_args)

            # 필터 적용
            if target_properties:
                stream = apply_filters(stream, target_properties)

            # 출력 스트림 설정
            stream = ffmpeg.output(stream, temp_output, **encoding_options)
        
        stream = stream.overwrite_output()

        if debug_mode:
            logger.debug(f"비디오 처리 명령어: {' '.join(ffmpeg.compile(stream))}")

        if progress_callback:
            progress_callback(30)  # FFmpeg 명령 준비 완료

        # FFmpeg 실행 (진행률 모니터링)
        process = subprocess.Popen(
            ffmpeg.compile(stream, cmd=FFMPEG_PATH),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1
        )
        
        # 진행률 모니터링
        for line in process.stderr:
            if debug_mode:
                logger.debug(line.strip())
            
            # 진행률 파싱 및 업데이트
            if progress_callback and "time=" in line:
                try:
                    time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                    if time_match:
                        time_str = time_match.group(1)
                        h, m, s = map(float, time_str.split(':'))
                        current_seconds = h * 3600 + m * 60 + s
                        progress = min(30 + (current_seconds / new_duration) * 70, 100)
                        progress_callback(int(progress))
                except Exception as e:
                    logger.warning(f"진행률 파싱 오류: {e}")
        
        process.wait()
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg 실행 실패 (반환 코드: {process.returncode})")
        
        logger.info(f"비디오 파일 처리 완료: {input_file}")
        
        if progress_callback:
            progress_callback(100)  # 처리 완료
            
        return temp_output

    except Exception as e:
        logger.exception(f"비디오 파일 처리 중 오류 발생: {str(e)}")
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
                logger.info(f"임시 파일 제거됨: {temp_output}")
            except Exception as cleanup_error:
                logger.warning(f"임시 파일 제거 실패: {cleanup_error}")
        raise


def process_image_sequence(
    input_file: str,
    trim_start: int,
    trim_end: int,
    encoding_options: Dict[str, str],
    target_properties: Dict[str, str],
    debug_mode: bool,
    idx: int,
    progress_callback=None,
    use_frame_based_trim: bool = False
) -> str:
    try:
        temp_output = f'temp_output_{idx}.mp4'
        logger.info(f"이미지 시퀀스 처리 시작: {input_file}")

        if progress_callback:
            progress_callback(5)  # 시작 진행률

        # 이미지 파일 패턴과 총 프레임 수 계산
        pattern = input_file.replace('\\', '/')
        glob_pattern = re.sub(r'%\d*d', '*', pattern)
        image_files = sorted(glob.glob(glob_pattern))

        if not image_files:
            logger.warning(f"이미지 시퀀스 '{input_file}'를 찾을 수 없습니다.")
            raise FileNotFoundError(f"No images found for pattern '{input_file}'")

        total_frames = len(image_files)

        if progress_callback:
            progress_callback(10)  # 파일 분석 완료

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

        if progress_callback:
            progress_callback(15)  # 트림 계산 완료

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
        
        if progress_callback:
            progress_callback(20)  # 옵션 설정 완료
        
        # 첫 번째 이미지에서 크기 정보 가져오기
        if not target_properties or 'width' not in target_properties or 'height' not in target_properties or target_properties.get('width', 0) == 0 or target_properties.get('height', 0) == 0:
            from PIL import Image
            try:
                with Image.open(image_files[0]) as img:
                    width, height = img.size
                    target_properties = {'width': width, 'height': height}
                    logger.debug(f"이미지에서 크기 정보 추출: {width}x{height}")
            except Exception as e:
                logger.warning(f"이미지에서 크기 정보를 추출할 수 없습니다: {e}")
                # 기본 크기 설정
                target_properties = {'width': 512, 'height': 512}
                logger.debug(f"기본 크기 설정: 512x512")
        
        # 크기 옵션 설정 (0x0이면 안됨)
        if 's' in encoding_options and encoding_options['s'] == '0x0':
            encoding_options['s'] = f"{target_properties['width']}x{target_properties['height']}"
            logger.debug(f"크기 옵션 수정: {encoding_options['s']}")

        if debug_mode:
            logger.debug(f"트림 정보 - 시작: {new_start_frame}, 프레임 수: {new_total_frames}")
            logger.debug(f"입력 옵션: {input_args}")
            logger.debug(f"인코딩 옵션: {encoding_options}")
            logger.debug(f"프레임 단위 트림 사용: {use_frame_based_trim}")

        if progress_callback:
            progress_callback(25)  # 속성 설정 완료

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

        if progress_callback:
            progress_callback(30)  # FFmpeg 명령 준비 완료

        # FFmpeg 실행 (진행률 모니터링)
        try:
            process = subprocess.Popen(
                ffmpeg.compile(stream, cmd=FFMPEG_PATH),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            # 진행률 모니터링
            for line in process.stderr:
                if debug_mode:
                    logger.debug(line.strip())
                
                # 진행률 파싱 및 업데이트
                if progress_callback and "frame=" in line:
                    try:
                        frame_match = re.search(r"frame=\s*(\d+)", line)
                        if frame_match:
                            current_frame = int(frame_match.group(1))
                            progress = min(30 + (current_frame / new_total_frames) * 70, 100)
                            progress_callback(int(progress))
                    except Exception as e:
                        logger.warning(f"진행률 파싱 오류: {e}")
            
            process.wait()
            
            if process.returncode != 0:
                raise Exception(f"FFmpeg 실행 실패 (반환 코드: {process.returncode})")
            
            logger.info(f"이미지 시퀀스 처리 완료: {input_file}")
            
            if progress_callback:
                progress_callback(100)  # 처리 완료
        except Exception as e:
            error_message = str(e)
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
    progress_callback=None,
    task_callback=None
):
    """
    처리된 미디어 파일들을 하나로 병합합니다.
    진행률 콜백과 작업 상태 콜백을 통해 진행 상황을 보고합니다.
    """
    temp_list_file = None
    try:
        if not processed_files:
            raise ValueError("병합할 파일이 없습니다.")

        logger.info(f"파일 병합 시작: {len(processed_files)}개 파일")
        
        if task_callback:
            task_callback(f"파일 병합 중... ({len(processed_files)}개 파일)")
        
        if progress_callback:
            progress_callback(5)  # 시작 진행률

        # 임시 파일 목록 생성
        temp_list_file = create_temp_file_list(processed_files)
        
        if progress_callback:
            progress_callback(10)  # 파일 목록 생성 완료

        # 병합 옵션 설정
        concat_options = {
            'f': 'concat',
            'safe': '0'
        }

        # 인코딩 옵션 설정
        encoding_options = get_optimal_encoding_options(encoding_options)

        # 스트림 생성
        stream = ffmpeg.input(temp_list_file, **concat_options)

        # 필터 적용
        if target_properties:
            stream = apply_filters(stream, target_properties)

        # 출력 스트림 설정
        stream = ffmpeg.output(stream, output_file, **encoding_options)
        stream = stream.overwrite_output()

        if debug_mode:
            logger.debug(f"병합 명령어: {' '.join(ffmpeg.compile(stream))}")
        
        if progress_callback:
            progress_callback(15)  # FFmpeg 명령 준비 완료

        # 총 길이 계산 (모든 파일의 길이 합산)
        total_duration = 0
        for file in processed_files:
            try:
                duration = get_video_duration(file)
                total_duration += duration
            except Exception as e:
                logger.warning(f"파일 길이 계산 실패: {file} - {e}")
        
        if total_duration <= 0:
            total_duration = 1  # 기본값 설정
            
        if debug_mode:
            logger.debug(f"총 병합 길이: {total_duration}초")

        # FFmpeg 실행 (진행률 모니터링)
        process = subprocess.Popen(
            ffmpeg.compile(stream, cmd=FFMPEG_PATH),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            bufsize=1
        )
        
        # 진행률 모니터링
        for line in process.stderr:
            if debug_mode:
                logger.debug(line.strip())
            
            # 진행률 파싱 및 업데이트
            if progress_callback and "time=" in line:
                try:
                    time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                    if time_match:
                        time_str = time_match.group(1)
                        h, m, s = map(float, time_str.split(':'))
                        current_seconds = h * 3600 + m * 60 + s
                        progress = min(15 + (current_seconds / total_duration) * 85, 100)
                        progress_callback(int(progress))
                except Exception as e:
                    logger.warning(f"진행률 파싱 오류: {e}")
        
        process.wait()
        
        if process.returncode != 0:
            raise Exception(f"FFmpeg 실행 실패 (반환 코드: {process.returncode})")
        
        logger.info(f"파일 병합 완료: {output_file}")
        
        if task_callback:
            task_callback("병합 완료!")
            
        if progress_callback:
            progress_callback(100)  # 처리 완료

    except Exception as e:
        logger.exception(f"파일 병합 중 오류 발생: {str(e)}")
        raise
        
    finally:
        # 임시 파일 목록 정리
        if temp_list_file and os.path.exists(temp_list_file):
            try:
                os.remove(temp_list_file)
                logger.debug(f"임시 파일 목록 제거됨: {temp_list_file}")
            except Exception as e:
                logger.warning(f"임시 파일 목록 제거 실패: {e}")

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
    task_callback: Optional[callable] = None,
    target_properties: Dict[str, str] = {},
    use_custom_framerate: bool = False,
    custom_framerate: float = 30.0,
    use_custom_resolution: bool = False,
    custom_width: int = 0,
    custom_height: int = 0,
    use_frame_based_trim: bool = False
):
    """
    모든 미디어 파일을 처리하고 하나의 파일로 합칩니다.
    
    진행률 가중치:
    - WebP 변환: 10%
    - 개별 파일 처리: 60%
    - 파일 병합: 30%
    
    매개변수:
        use_frame_based_trim (bool): 프레임 단위로 직접 트림을 적용할지 여부. 
                                    True이면 select 필터를 사용하여 프레임 번호로 직접 트림합니다.
                                    False이면 초 단위로 변환하여 트림합니다.
    """
    temp_dirs_to_cleanup = []
    try:
        if trim_values is None:
            # media_files의 개별 트림 값을 사용
            trim_values = [(media_file[1], media_file[2]) for media_file in media_files]

        if debug_mode:
            logger.debug(f"전역 트림 값 - 시작: {global_trim_start}, 끝: {global_trim_end}")
            logger.debug(f"개별 트림 값: {trim_values}")
            logger.debug(f"사용자 지정 프레임레이트: {use_custom_framerate}, 값: {custom_framerate}")
            logger.debug(f"사용자 지정 해상도: {use_custom_resolution}, 값: {custom_width}x{custom_height}")

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
        
        if task_callback:
            task_callback("미디어 파일 분석 중...")
        
        # WebP 파일 개수 확인
        webp_files_count = sum(1 for file, _, _ in media_files if is_webp_file(file))
        webp_files_processed = 0
        
        # WebP 파일을 이미지 시퀀스로 미리 변환
        processed_media_files = []
        for idx, (input_file, trim_start, trim_end) in enumerate(media_files):
            if is_webp_file(input_file):
                if task_callback:
                    task_callback(f"WebP 파일 변환 중 ({idx+1}/{len(media_files)}): {os.path.basename(input_file)}")
                
                logger.info(f"WebP 파일 사전 처리: {input_file}")
                try:
                    # WebP 파일을 이미지 시퀀스로 변환
                    image_sequence, webp_metadata, temp_dir = extract_webp_to_image_sequence(
                        input_file, 
                        debug_mode,
                        lambda p: update_webp_progress(p, idx, len(media_files), webp_files_count, webp_files_processed, progress_callback)
                    )
                    temp_dirs_to_cleanup.append(temp_dir)
                    webp_files_processed += 1
                    
                    # 프레임레이트 설정
                    if use_custom_framerate:
                        fps = custom_framerate
                    else:
                        fps = webp_metadata['fps']
                    
                    # 해상도 설정
                    if use_custom_resolution and custom_width > 0 and custom_height > 0:
                        width, height = custom_width, custom_height
                    else:
                        width, height = webp_metadata['width'], webp_metadata['height']
                    
                    # 변환된 이미지 시퀀스와 메타데이터를 저장
                    processed_media_files.append((image_sequence, trim_start, trim_end, {
                        'fps': fps,
                        'width': width,
                        'height': height,
                        'is_webp_sequence': True
                    }))
                    
                    if debug_mode:
                        logger.debug(f"WebP 파일 변환 완료: {input_file} -> {image_sequence}")
                        logger.debug(f"메타데이터: fps={fps}, 크기={width}x{height}")
                except Exception as e:
                    logger.error(f"WebP 파일 변환 실패: {input_file} - {e}")
                    # 변환 실패 시 원본 파일 사용
                    processed_media_files.append((input_file, trim_start, trim_end, {}))
            else:
                # WebP가 아닌 파일은 그대로 사용
                processed_media_files.append((input_file, trim_start, trim_end, {}))
        
        if task_callback:
            task_callback("파일 속성 분석 중...")
            
        # 먼저 target_properties 얻기
        input_files = [file[0] for file in processed_media_files]  # 파일 경로만 추출
        if not target_properties:
            target_properties = get_target_properties(input_files, encoding_options, debug_mode)
        
        # 사용자 지정 해상도가 있으면 target_properties 업데이트
        if use_custom_resolution and custom_width > 0 and custom_height > 0:
            target_properties = {'width': custom_width, 'height': custom_height}
            logger.debug(f"사용자 지정 해상도로 target_properties 업데이트: {target_properties}")
        
        if not target_properties:
            logger.warning("대상 속성을 가져올 수 없습니다. 기본값을 사용합니다.")
            target_properties = {'width': 1920, 'height': 1080}
        
        temp_files_to_remove = []
        processed_files = [None] * len(processed_media_files)  # 순서 유지를 위한 초기화

        # 최적의 스레드 수 계산
        max_workers = min(len(processed_media_files), os.cpu_count() or 1)
        
        # 메모리 사용량 모니터링 설정
        total_memory = psutil.virtual_memory().total
        memory_threshold = total_memory * 0.8

        # WebP 변환 진행률 가중치: 10%
        # 개별 파일 처리 진행률 가중치: 60%
        # 파일 병합 진행률 가중치: 30%
        webp_weight = 0.1
        processing_weight = 0.6
        merging_weight = 0.3
        
        # WebP 변환 완료 후 시작 진행률
        current_progress = webp_weight * 100 if webp_files_count > 0 else 0
        
        if progress_callback:
            progress_callback(int(current_progress))

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            
            for idx, ((input_file, trim_start, trim_end, metadata), (combined_trim_start, combined_trim_end)) in enumerate(zip(processed_media_files, combined_trim_values)):
                if task_callback:
                    task_callback(f"파일 처리 중 ({idx+1}/{len(processed_media_files)}): {os.path.basename(input_file)}")
                
                if debug_mode:
                    logger.debug(f"파일 처리: {input_file}")
                    logger.debug(f"적용될 트림 값 - 시작: {combined_trim_start}, 끝: {combined_trim_end}")
                
                # 인코딩 옵션 복사 및 WebP 메타데이터 적용
                file_encoding_options = encoding_options.copy()
                file_target_properties = target_properties.copy()
                
                # WebP 시퀀스인 경우 메타데이터 적용
                if 'is_webp_sequence' in metadata and metadata['is_webp_sequence']:
                    if not use_custom_framerate:
                        file_encoding_options["r"] = str(metadata['fps'])
                    
                    if not use_custom_resolution:
                        file_target_properties['width'] = metadata['width']
                        file_target_properties['height'] = metadata['height']

                future = executor.submit(
                    process_single_media,
                    input_file,
                    combined_trim_start,
                    combined_trim_end,
                    file_encoding_options,
                    debug_mode,
                    idx,
                    memory_threshold,
                    file_target_properties,
                    use_custom_framerate,
                    custom_framerate,
                    use_custom_resolution,
                    custom_width,
                    custom_height,
                    lambda p: update_file_progress(p, idx, len(processed_media_files), current_progress, processing_weight, progress_callback),
                    use_frame_based_trim
                )
                futures.append((idx, future))

            # 순서대로 결과 수집 및 진행률 업데이트
            total_files = len(processed_media_files)
            for idx, future in futures:
                try:
                    temp_output = future.result()
                    processed_files[idx] = temp_output  # 원래 순서대로 저장
                    temp_files_to_remove.append(temp_output)
                    
                    # 파일 처리 완료 후 진행률 업데이트
                    if progress_callback:
                        file_progress = webp_weight * 100 + processing_weight * 100 * (idx + 1) / total_files
                        progress_callback(int(file_progress))
                        
                except Exception as e:
                    logger.error(f"'{processed_media_files[idx][0]}' 처리 중 오류 발생: {e}")
                    raise

        # 빈 항목 제거
        processed_files = [f for f in processed_files if f is not None]

        # 처리된 파일들을 하나로 병합
        if processed_files:
            if task_callback:
                task_callback(f"파일 병합 중... ({len(processed_files)}개 파일)")
                
            try:
                # 병합 시작 진행률 계산
                merge_start_progress = webp_weight * 100 + processing_weight * 100
                
                concat_media_files(
                    processed_files,
                    output_file,
                    encoding_options,
                    target_properties,
                    debug_mode,
                    lambda p: update_merge_progress(p, merge_start_progress, merging_weight, progress_callback),
                    task_callback
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

        if task_callback:
            task_callback("인코딩 완료!")
            
        if progress_callback:
            progress_callback(100)  # 최종 진행률 100%로 설정
            
        return output_file

    except Exception as e:
        logger.exception("미디어 처리 중 오류 발생")
        if task_callback:
            task_callback(f"오류 발생: {str(e)}")
        raise
    finally:
        # 임시 디렉토리 정리
        for temp_dir in temp_dirs_to_cleanup:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    logger.debug(f"임시 디렉토리 정리 중: {temp_dir}")
                    shutil.rmtree(temp_dir)
                    logger.debug(f"임시 디렉토리 정리 완료: {temp_dir}")
                except Exception as cleanup_error:
                    logger.warning(f"임시 디렉토리 정리 실패: {temp_dir} - {cleanup_error}")

# 진행률 업데이트 헬퍼 함수들
def update_webp_progress(progress, file_idx, total_files, webp_count, webp_processed, callback):
    """WebP 변환 진행률 업데이트"""
    if callback and webp_count > 0:
        # WebP 변환은 전체의 10%
        webp_weight = 0.1
        # 현재 WebP 파일의 가중치
        file_weight = 1.0 / webp_count
        # 이전 WebP 파일들의 진행률
        previous_progress = webp_processed * file_weight
        # 현재 WebP 파일의 진행률
        current_file_progress = progress / 100 * file_weight
        # 전체 진행률
        total_progress = (previous_progress + current_file_progress) * webp_weight * 100
        callback(int(total_progress))

def update_file_progress(progress, file_idx, total_files, base_progress, processing_weight, callback):
    """개별 파일 처리 진행률 업데이트"""
    if callback:
        # 파일 처리는 전체의 60%
        # 현재 파일의 가중치
        file_weight = 1.0 / total_files
        # 현재 파일의 진행률 기여도
        file_progress = progress / 100 * file_weight * processing_weight * 100
        # 전체 진행률
        total_progress = base_progress + file_progress
        callback(int(total_progress))

def update_merge_progress(progress, base_progress, merging_weight, callback):
    """파일 병합 진행률 업데이트"""
    if callback:
        # 병합은 전체의 30%
        merge_progress = progress / 100 * merging_weight * 100
        total_progress = base_progress + merge_progress
        callback(int(total_progress))

def process_single_media(
    input_file: str,
    trim_start: int,
    trim_end: int,
    encoding_options: Dict[str, str],
    debug_mode: bool,
    idx: int,
    memory_threshold: int,
    target_properties: Dict[str, str] = {},
    use_custom_framerate: bool = False,
    custom_framerate: float = 30.0,
    use_custom_resolution: bool = False,
    custom_width: int = 0,
    custom_height: int = 0,
    progress_callback=None,
    use_frame_based_trim: bool = False
) -> str:
    """단일 미디어 파일 처리 (메모리 모니터링 포함)"""
    temp_dirs_to_cleanup = []
    try:
        # 현재 메모리 사용량 확인
        current_memory = psutil.virtual_memory().used
        if current_memory > memory_threshold:
            # 메모리 사용량이 임계값을 초과하면 잠시 대기
            logger.warning("메모리 사용량이 높습니다. 처리 대기 중...")
            time.sleep(5)  # 5초 대기
            gc.collect()  # 가비지 컬렉션 강제 실행

        if progress_callback:
            progress_callback(5)  # 시작 진행률

        # webp 파일인지 확인
        if is_webp_file(input_file):
            # webp 파일을 이미지 시퀀스로 변환
            image_sequence, webp_metadata, temp_dir = extract_webp_to_image_sequence(
                input_file, 
                debug_mode,
                lambda p: progress_callback(int(p * 0.4)) if progress_callback else None  # 변환은 전체의 40%
            )
            temp_dirs_to_cleanup.append(temp_dir)
            
            # 편집 옵션에서 설정한 값이 있으면 우선 적용
            if use_custom_framerate:
                logger.debug(f"사용자 지정 프레임레이트 사용: {custom_framerate} fps")
                encoding_options["r"] = str(custom_framerate)
            else:
                # webp에서 추출한 프레임레이트 사용
                logger.debug(f"webp에서 추출한 프레임레이트 사용: {webp_metadata['fps']} fps")
                encoding_options["r"] = str(webp_metadata['fps'])
            
            # 해상도 설정
            if use_custom_resolution and custom_width > 0 and custom_height > 0:
                logger.debug(f"사용자 지정 해상도 사용: {custom_width}x{custom_height}")
                target_properties['width'] = custom_width
                target_properties['height'] = custom_height
            elif 'width' in webp_metadata and 'height' in webp_metadata and webp_metadata['width'] > 0 and webp_metadata['height'] > 0:
                logger.debug(f"webp에서 추출한 해상도 사용: {webp_metadata['width']}x{webp_metadata['height']}")
                target_properties['width'] = webp_metadata['width']
                target_properties['height'] = webp_metadata['height']
            
            if progress_callback:
                progress_callback(45)  # WebP 변환 및 설정 완료
            
            # 변환된 이미지 시퀀스를 처리
            result = process_image_sequence(
                image_sequence, 
                trim_start, 
                trim_end,
                encoding_options, 
                target_properties, 
                debug_mode, 
                idx,
                lambda p: progress_callback(45 + int(p * 0.55)) if progress_callback else None,  # 처리는 전체의 55%
                use_frame_based_trim
            )
            
            if progress_callback:
                progress_callback(100)  # 처리 완료
                
            return result
            
        # 이미지 시퀀스인지 확인
        elif is_image_sequence(input_file):
            # 편집 옵션에서 설정한 값이 있으면 우선 적용
            if use_custom_framerate:
                logger.debug(f"사용자 지정 프레임레이트 사용: {custom_framerate} fps")
                encoding_options["r"] = str(custom_framerate)
            
            # 해상도 설정
            if use_custom_resolution and custom_width > 0 and custom_height > 0:
                logger.debug(f"사용자 지정 해상도 사용: {custom_width}x{custom_height}")
                target_properties['width'] = custom_width
                target_properties['height'] = custom_height
            
            if progress_callback:
                progress_callback(10)  # 설정 완료
                
            return process_image_sequence(
                input_file, 
                trim_start, 
                trim_end,
                encoding_options, 
                target_properties, 
                debug_mode, 
                idx,
                lambda p: progress_callback(10 + int(p * 0.9)) if progress_callback else None,  # 처리는 전체의 90%
                use_frame_based_trim
            )
        else:
            # 비디오 파일 처리
            # 편집 옵션에서 설정한 값이 있으면 우선 적용
            if use_custom_framerate:
                logger.debug(f"사용자 지정 프레임레이트 사용: {custom_framerate} fps")
                encoding_options["r"] = str(custom_framerate)
            
            # 해상도 설정
            if use_custom_resolution and custom_width > 0 and custom_height > 0:
                logger.debug(f"사용자 지정 해상도 사용: {custom_width}x{custom_height}")
                target_properties['width'] = custom_width
                target_properties['height'] = custom_height
            
            if progress_callback:
                progress_callback(10)  # 설정 완료
                
            return process_video_file(
                input_file, 
                trim_start, 
                trim_end,
                encoding_options, 
                target_properties, 
                debug_mode, 
                idx,
                lambda p: progress_callback(10 + int(p * 0.9)) if progress_callback else None,  # 처리는 전체의 90%
                use_frame_based_trim
            )

    except Exception as e:
        logger.exception(f"'{input_file}' 처리 중 오류 발생")
        raise
    finally:
        # 임시 디렉토리 정리
        for temp_dir in temp_dirs_to_cleanup:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    logger.debug(f"임시 디렉토리 정리 중: {temp_dir}")
                    shutil.rmtree(temp_dir)
                    logger.debug(f"임시 디렉토리 정리 완료: {temp_dir}")
                except Exception as cleanup_error:
                    logger.warning(f"임시 디렉토리 정리 실패: {temp_dir} - {cleanup_error}")

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

def extract_webp_to_image_sequence(webp_file_path: str, debug_mode: bool = False, progress_callback=None) -> tuple:
    """
    Pillow를 사용하여 webp 파일을 이미지 시퀀스로 변환합니다.
    애니메이션 webp와 정적 webp 모두 지원합니다.
    
    Args:
        webp_file_path (str): webp 파일 경로
        debug_mode (bool): 디버그 모드 여부
        progress_callback (callable, optional): 진행률 업데이트 콜백 함수
        
    Returns:
        tuple: (이미지 시퀀스 패턴, 메타데이터 딕셔너리, 임시 디렉토리 경로)
               메타데이터는 'fps', 'width', 'height' 등의 정보를 포함
    """
    temp_dir = None
    try:
        from PIL import Image
        import io
        
        logger.info(f"webp 파일을 이미지 시퀀스로 변환 시작: {webp_file_path}")
        
        if progress_callback:
            progress_callback(5)  # 시작 진행률
        
        # 출력 디렉토리 생성 (임시 디렉토리)
        temp_dir = tempfile.mkdtemp(prefix="webp_extract_")
        
        # 파일 이름에서 확장자 제거
        base_name = os.path.basename(webp_file_path)
        file_name_without_ext = os.path.splitext(base_name)[0]
        
        # 메타데이터를 저장할 딕셔너리
        metadata = {
            'fps': 25,  # 기본값
            'width': 0,
            'height': 0
        }
        
        if progress_callback:
            progress_callback(10)  # 초기화 완료
        
        # webp 파일 열기
        try:
            with Image.open(webp_file_path) as img:
                # 이미지 크기 정보 저장
                metadata['width'], metadata['height'] = img.size
                
                # 애니메이션 webp인지 확인
                is_animated = hasattr(img, 'n_frames') and img.n_frames > 1
                
                if debug_mode:
                    logger.debug(f"webp 파일 정보: 애니메이션={is_animated}, 크기={img.size}, 모드={img.mode}")
                    if is_animated:
                        logger.debug(f"프레임 수: {img.n_frames}")
                
                if progress_callback:
                    progress_callback(20)  # 파일 분석 완료
                
                # 애니메이션 webp인 경우 프레임레이트 추출 시도
                if is_animated:
                    # webp 파일에서 프레임레이트 정보 추출 시도
                    try:
                        # info 딕셔너리에서 duration 정보 확인
                        if hasattr(img, 'info') and 'duration' in img.info:
                            # duration은 밀리초 단위, 이를 fps로 변환
                            duration_ms = img.info['duration']
                            if duration_ms > 0:
                                metadata['fps'] = round(1000 / duration_ms, 2)
                                logger.debug(f"추출된 프레임레이트: {metadata['fps']} fps (duration: {duration_ms}ms)")
                    except Exception as e:
                        logger.warning(f"프레임레이트 추출 실패: {e}")
                    
                    # 모든 프레임 추출
                    total_frames = img.n_frames
                    for i in range(total_frames):
                        img.seek(i)
                        frame_path = os.path.join(temp_dir, f"{file_name_without_ext}_{i+1:04d}.png")
                        img.save(frame_path, "PNG")
                        
                        if progress_callback:
                            # 프레임 추출 진행률 (20-90%)
                            extract_progress = 20 + (i + 1) / total_frames * 70
                            progress_callback(int(extract_progress))
                            
                        if debug_mode and i == 0:
                            logger.debug(f"첫 번째 프레임 저장됨: {frame_path}")
                # 정적 webp인 경우
                else:
                    frame_path = os.path.join(temp_dir, f"{file_name_without_ext}_0001.png")
                    img.save(frame_path, "PNG")
                    if debug_mode:
                        logger.debug(f"단일 이미지 저장됨: {frame_path}")
                    
                    if progress_callback:
                        progress_callback(90)  # 단일 이미지 저장 완료
        except Exception as e:
            logger.error(f"Pillow로 webp 파일 열기 실패: {e}")
            raise Exception(f"webp 파일을 열 수 없습니다: {e}")
        
        # 생성된 파일 확인
        image_files = sorted(glob.glob(os.path.join(temp_dir, f"{file_name_without_ext}_*.png")))
        
        if not image_files:
            logger.error(f"변환된 이미지 파일을 찾을 수 없습니다: {temp_dir}")
            raise Exception("변환된 이미지 파일을 찾을 수 없습니다")
        
        logger.info(f"webp 파일 변환 완료: {len(image_files)}개 이미지 생성됨")
        logger.info(f"추출된 메타데이터: 프레임레이트={metadata['fps']} fps, 크기={metadata['width']}x{metadata['height']}")
        
        if progress_callback:
            progress_callback(100)  # 변환 완료
        
        # 이미지 시퀀스 패턴과 메타데이터, 임시 디렉토리 경로 반환
        return os.path.join(temp_dir, f"{file_name_without_ext}_%04d.png"), metadata, temp_dir
    
    except Exception as e:
        logger.exception(f"webp 파일 변환 중 오류 발생: {str(e)}")
        
        # 임시 디렉토리 정리
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except Exception as cleanup_error:
                logger.warning(f"임시 디렉토리 정리 실패: {cleanup_error}")
        
        raise
