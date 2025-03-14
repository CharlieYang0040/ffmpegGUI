import os
import re
import glob
import logging
import ffmpeg
import subprocess
import shutil
import tempfile
from PIL import Image  # Pillow 라이브러리 추가
import io
from typing import Dict

# 로깅 서비스 가져오기
from app.services.logging_service import LoggingService

# FFmpegManager 싱글톤 가져오기
from app.core.ffmpeg_manager import FFmpegManager

# ffmpeg_core에서 필요한 함수 가져오기
from app.core.ffmpeg_core import apply_filters, get_optimal_encoding_options, get_media_properties

# 로깅 설정
logger = LoggingService().get_logger(__name__)

class ImageProcessor:
    """이미지 및 이미지 시퀀스 처리를 위한 클래스"""
    
    def __init__(self, ffmpeg_manager=None):
        """
        이미지 프로세서 초기화
        
        Args:
            ffmpeg_manager: FFmpegManager 인스턴스 (없으면 싱글톤 인스턴스 사용)
        """
        self.ffmpeg_manager = ffmpeg_manager or FFmpegManager()
        self.logger = LoggingService().get_logger(__name__)
    
    def process_image_sequence(
        self,
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
        이미지 시퀀스를 처리하여 비디오로 변환합니다.
        """
        try:
            # 프레임 기반 트림 로그 추가
            if use_frame_based_trim:
                self.logger.info(f"이미지 시퀀스 프레임 기반 트림 적용: 경로={input_file}, 시작 프레임={trim_start}, 끝 프레임={trim_end}")
            
            # 출력 파일 생성
            output_file = tempfile.mktemp(suffix='.mp4')
            
            # 이미지 시퀀스 정보 분석
            input_pattern = input_file
            
            # 경로 정규화 (Windows 경로 문제 해결)
            input_pattern = os.path.normpath(input_pattern)
            
            # 이미지 시퀀스 패턴에서 시작 번호 추출 (%04d 형식)
            pattern_match = re.search(r'%(\d+)d', input_pattern)
            if pattern_match:
                padding = int(pattern_match.group(1))
            else:
                padding = 4  # 기본값
            
            # 실제 파일 패턴 확인을 위한 코드 추가
            dir_path = os.path.dirname(input_pattern)
            base_name = os.path.basename(input_pattern)
            
            # 파일명.네자리숫자프레임.확장자 형식에 맞게 패턴 변환
            if '%' in base_name:
                # %04d 패턴을 *.확장자 형식으로 변환
                parts = base_name.split('%')
                if len(parts) == 2:
                    prefix = parts[0]  # 파일명 부분
                    # d 이후의 부분이 확장자
                    suffix_parts = parts[1].split('d', 1)
                    if len(suffix_parts) == 2:
                        suffix = suffix_parts[1]  # 확장자 부분
                        # 실제 파일 패턴 (예: '04_intro_01_High.*.png')
                        actual_pattern = os.path.join(dir_path, f"{prefix}*{suffix}")
                        self.logger.debug(f"변환된 실제 파일 패턴: {actual_pattern}")
                        existing_files = sorted(glob.glob(actual_pattern))
                    else:
                        self.logger.warning(f"패턴에서 확장자를 추출할 수 없습니다: {base_name}")
                        existing_files = []
                else:
                    self.logger.warning(f"패턴 형식이 예상과 다릅니다: {base_name}")
                    existing_files = []
            else:
                # 기존 방식 유지
                base_pattern = input_pattern.replace(f'%{padding}d', '*')
                existing_files = sorted(glob.glob(base_pattern))
            
            # 파일 존재 여부 확인
            if not existing_files:
                error_msg = f"이미지 시퀀스 파일을 찾을 수 없습니다: {input_pattern}"
                self.logger.error(error_msg)
                
                # 디버깅을 위한 추가 정보
                self.logger.error(f"디렉토리 내용 확인: {os.path.dirname(input_pattern)}")
                try:
                    dir_files = os.listdir(os.path.dirname(input_pattern))
                    if dir_files:
                        self.logger.error(f"디렉토리 내 파일 샘플: {dir_files[:10]}")
                    else:
                        self.logger.error("디렉토리가 비어 있습니다.")
                except Exception as e:
                    self.logger.error(f"디렉토리 내용 확인 중 오류: {str(e)}")
                
                raise Exception(error_msg)
                
            # 시작 번호 결정 및 총 프레임 수 계산
            start_number = 0  # 기본값
            total_frames = 0
            actual_frame_numbers = []  # 실제 파일 이름에서 추출한 프레임 번호 목록
            
            # 모든 파일에서 프레임 번호 추출
            for file_path in existing_files:
                file_name = os.path.basename(file_path)
                # 파일명.숫자.확장자 형식에서 숫자 부분 추출
                # 마지막 점(.) 이후의 확장자를 제외한 파일명에서 마지막 점(.) 이후의 숫자를 추출
                name_without_ext = os.path.splitext(file_name)[0]  # 확장자 제외
                parts = name_without_ext.split('.')
                if len(parts) > 1:  # 파일명에 점이 있는 경우
                    try:
                        # 마지막 부분을 프레임 번호로 사용
                        frame_number = int(parts[-1])
                        actual_frame_numbers.append(frame_number)
                        self.logger.debug(f"파일 {file_name}에서 프레임 번호 {frame_number} 추출")
                    except ValueError:
                        # 숫자로 변환할 수 없는 경우
                        self.logger.warning(f"파일 {file_name}에서 프레임 번호를 추출할 수 없습니다")
                else:
                    # 기존 방식 시도 (첫 번째 숫자 추출)
                    number_match = re.search(r'(\d+)', file_name)
                    if number_match:
                        frame_number = int(number_match.group(1))
                        actual_frame_numbers.append(frame_number)
                        self.logger.debug(f"파일 {file_name}에서 프레임 번호 {frame_number} 추출 (정규식)")
            
            if not actual_frame_numbers:
                error_msg = f"이미지 시퀀스 파일에서 프레임 번호를 추출할 수 없습니다: {input_pattern}"
                self.logger.error(error_msg)
                raise Exception(error_msg)
                
            # 실제 시작 번호와 끝 번호 결정
            start_number = min(actual_frame_numbers)
            end_number = max(actual_frame_numbers)
            total_frames = len(actual_frame_numbers)
            
            self.logger.info(f"이미지 시퀀스 프레임 번호 범위: {start_number}~{end_number}, 총 {total_frames}개 프레임")
            
            # 프레임 번호가 연속적인지 확인
            expected_frames = set(range(start_number, end_number + 1))
            actual_frames = set(actual_frame_numbers)
            
            # 누락된 프레임 확인 및 경고
            if expected_frames != actual_frames:
                missing_frames = expected_frames - actual_frames
                extra_frames = actual_frames - expected_frames
                
                if missing_frames:
                    missing_frames_list = sorted(missing_frames)
                    missing_msg = f"누락된 프레임 번호: {missing_frames_list}"
                    self.logger.warning(missing_msg)
                    
                    # 누락된 프레임이 많을 경우 처리 중단 여부 결정
                    if len(missing_frames) > total_frames * 0.1:  # 10% 이상 누락된 경우
                        error_msg = f"이미지 시퀀스에 너무 많은 프레임이 누락되었습니다 ({len(missing_frames)}개, 전체의 {len(missing_frames)/total_frames*100:.1f}%). 처리를 중단합니다."
                        self.logger.error(error_msg)
                        raise Exception(error_msg)
                
                if extra_frames:
                    self.logger.warning(f"예상 범위 외 추가 프레임 번호: {sorted(extra_frames)}")
            
            # 프레임레이트 설정
            fps = 30
            if 'r' in encoding_options:
                fps = float(encoding_options['r'])
            
            # 프레임 기반 트림 적용
            if use_frame_based_trim:
                # 트림 값이 소수점인 경우 정수로 변환
                if isinstance(trim_start, float):
                    trim_start = int(trim_start)
                if isinstance(trim_end, float):
                    trim_end = int(trim_end)
                
                # 트림 값 유효성 검사
                if trim_start > end_number or (trim_end > 0 and trim_end > end_number):
                    error_msg = f"트림 범위가 유효하지 않습니다. 시작={trim_start}, 끝={trim_end}, 실제 프레임 범위={start_number}~{end_number}"
                    self.logger.error(error_msg)
                    raise Exception(error_msg)
                
                # 기본 FFmpeg 명령 구성 (트림 적용)
                command = [
                    self.ffmpeg_manager.get_ffmpeg_path(),
                    '-framerate', str(fps)
                ]
                
                # 시작 프레임 번호 조정 - 실제 파일의 시작 번호 사용
                command.extend(['-start_number', str(start_number)])
                self.logger.debug(f"시작 프레임 번호 설정: {start_number}")
                
                # 입력 파일 지정
                command.extend(['-i', input_pattern])
                
                # 프레임 수 제한 (트림 끝 적용)
                if trim_end > 0:
                    # 실제 프레임 번호 기준으로 프레임 수 계산
                    if actual_frame_numbers:
                        sorted_frames = sorted(actual_frame_numbers)
                        
                        if trim_end < len(sorted_frames):
                            # trim_end 인덱스에 해당하는 실제 프레임까지 사용
                            end_frame = sorted_frames[trim_end]
                            # 시작 프레임부터 끝 프레임까지의 프레임 수 계산
                            if trim_start > 0 and trim_start < len(sorted_frames):
                                start_frame = sorted_frames[trim_start]
                                frame_count = sorted_frames.index(end_frame) - sorted_frames.index(start_frame) + 1
                            else:
                                # 처음부터 끝 프레임까지
                                frame_count = sorted_frames.index(end_frame) + 1
                        else:
                            # trim_end가 범위를 벗어나면 모든 프레임 사용
                            frame_count = len(sorted_frames) - (trim_start if trim_start < len(sorted_frames) else 0)
                    else:
                        # 기본 계산 방식 사용
                        frame_count = trim_end - trim_start + 1
                    
                    if frame_count <= 0:
                        self.logger.warning(f"계산된 프레임 수가 0 이하입니다: {frame_count}. 모든 프레임을 사용합니다.")
                        frame_count = total_frames
                    
                    command.extend(['-frames:v', str(frame_count)])
                    self.logger.debug(f"프레임 수 계산: {frame_count}")
                else:
                    # 트림 끝이 지정되지 않은 경우 모든 프레임 처리
                    if total_frames > 0:
                        # 시작 프레임부터 끝까지의 프레임 수 계산
                        if trim_start > 0 and actual_frame_numbers and trim_start < len(actual_frame_numbers):
                            frame_count = total_frames - trim_start
                        else:
                            frame_count = total_frames
                        
                        if frame_count > 0:
                            command.extend(['-frames:v', str(frame_count)])
                            self.logger.debug(f"시작 프레임({trim_start})부터 끝까지 프레임 수: {frame_count}")
                
                self.logger.info(f"이미지 시퀀스 트림 명령: 시작={trim_start}, 끝={trim_end}, 프레임 수={frame_count if 'frame_count' in locals() else '전체'}, 시작 번호={start_number}, 총 프레임 수={total_frames}, 실제 프레임 번호 범위={min(actual_frame_numbers)}~{max(actual_frame_numbers)}")
            else:
                # 기본 FFmpeg 명령 구성 (트림 없음)
                command = [
                    self.ffmpeg_manager.get_ffmpeg_path(),
                    '-framerate', str(fps),
                    '-start_number', str(start_number),
                    '-i', input_pattern
                ]
            
            # 해상도 설정
            if target_properties and 'width' in target_properties and 'height' in target_properties:
                width = target_properties['width']
                height = target_properties['height']
                scale_filter = f'scale={width}:{height}:force_original_aspect_ratio=decrease'
                pad_filter = f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black'
            else:
                # 원본 해상도 유지
                scale_filter = 'scale=iw:ih'
                pad_filter = 'pad=iw:ih:0:0'
            
            # 필터 체인 구성
            filter_chain = [scale_filter, pad_filter]
            
            # 인코딩 옵션 적용
            command.extend([
                '-vf', ','.join(filter_chain),
                '-c:v', 'libx264',
                '-pix_fmt', 'yuv420p',
                '-colorspace', 'bt709',
                '-color_primaries', 'bt709',
                '-color_trc', 'bt709',
                '-color_range', 'limited'
            ])
            
            # 추가 인코딩 옵션 적용
            for key, value in encoding_options.items():
                if key != 's':  # 해상도는 이미 처리됨
                    command.extend([f'-{key}', str(value)])
            
            # 출력 파일 지정
            command.extend(['-y', output_file])
            
            # 디버그 모드일 경우 명령어 출력
            if debug_mode:
                self.logger.debug(f"FFmpeg 명령: {' '.join(command)}")
            
            # FFmpeg 프로세스 실행
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # 진행 상황 모니터링
            for line in process.stderr:
                if debug_mode:
                    self.logger.debug(line.strip())
                if progress_callback:
                    progress = self.parse_ffmpeg_image_progress(line)
                    if progress is not None:
                        progress_callback(progress)
            
            # 프로세스 완료 대기
            process.wait()
            
            # 오류 확인
            if process.returncode != 0:
                stderr_output = process.stderr.read() if process.stderr else ""
                raise Exception(f"FFmpeg 처리 실패 (반환 코드: {process.returncode}): {stderr_output}")
            
            return output_file
            
        except Exception as e:
            self.logger.error(f"이미지 시퀀스 처리 중 오류 발생: {str(e)}")
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                except:
                    pass
            raise
    
    def parse_ffmpeg_image_progress(self, output: str) -> float:
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
                    return min(current_seconds / 1, 1.0)
        except Exception as e:
            self.logger.warning(f"진행률 파싱 중 오류: {e}")

        return None