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
            # 출력 파일 생성
            output_file = tempfile.mktemp(suffix='.mp4')
            
            # 기본 FFmpeg 명령 구성
            command = [
                self.ffmpeg_manager.get_ffmpeg_path(),
                '-framerate', '30',  # 기본 프레임레이트
                '-i', input_file
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
            

    # def extract_webp_to_image_sequence(
    #     self,
    #     input_file: str,
    #     temp_dir: str,
    #     progress_callback=None
    # ) -> str:
    #     """
    #     WebP 애니메이션 파일을 이미지 시퀀스로 추출합니다.
    #     추출된 이미지 파일 패턴을 반환합니다.
    #     Pillow 라이브러리를 사용하여 WebP 파일을 처리합니다.
    #     """
    #     try:
    #         self.logger.info(f"WebP 애니메이션 추출 시작: {input_file}")
            
    #         if progress_callback:
    #             progress_callback(5)  # 시작 진행률
                
    #         # 임시 디렉토리 생성
    #         os.makedirs(temp_dir, exist_ok=True)
    #         temp_image_pattern = os.path.join(temp_dir, 'frame_%05d.png')
            
    #         if progress_callback:
    #             progress_callback(10)  # 디렉토리 생성 완료
            
    #         # Pillow를 사용하여 WebP 파일 로드
    #         webp_image = Image.open(input_file)
            
    #         # WebP가 애니메이션인지 확인
    #         is_animated = hasattr(webp_image, 'is_animated') and webp_image.is_animated
            
    #         if not is_animated:
    #             # 애니메이션이 아닌 경우 단일 이미지로 저장
    #             frame_path = os.path.join(temp_dir, 'frame_00000.png')
    #             webp_image.save(frame_path, 'PNG')
    #             self.logger.info(f"단일 프레임 WebP 저장됨: {frame_path}")
                
    #             if progress_callback:
    #                 progress_callback(100)  # 추출 완료
                    
    #             return temp_image_pattern
            
    #         # 애니메이션 WebP 처리
    #         frame_count = getattr(webp_image, 'n_frames', 1)
    #         self.logger.info(f"WebP 애니메이션 프레임 수: {frame_count}")
            
    #         # 각 프레임 추출 및 저장
    #         for frame_idx in range(frame_count):
    #             if progress_callback:
    #                 # 10%에서 시작하여 90%까지 진행
    #                 progress = 10 + int((frame_idx / frame_count) * 90)
    #                 progress_callback(progress)
                
    #             # 현재 프레임으로 이동
    #             webp_image.seek(frame_idx)
                
    #             # 프레임 저장 (RGBA -> RGB 변환)
    #             frame_path = os.path.join(temp_dir, f'frame_{frame_idx:05d}.png')
                
    #             # RGBA 모드인 경우 RGB로 변환 (알파 채널 제거)
    #             if webp_image.mode == 'RGBA':
    #                 # 흰색 배경에 알파 채널 합성
    #                 background = Image.new('RGB', webp_image.size, (255, 255, 255))
    #                 background.paste(webp_image, mask=webp_image.split()[3])  # 알파 채널을 마스크로 사용
    #                 background.save(frame_path, 'PNG')
    #             else:
    #                 webp_image.convert('RGB').save(frame_path, 'PNG')
                
    #             self.logger.debug(f"프레임 저장됨: {frame_path}")
            
    #         # 추출된 파일 확인
    #         extracted_files = sorted(glob.glob(os.path.join(temp_dir, 'frame_*.png')))
    #         if not extracted_files:
    #             raise FileNotFoundError(f"WebP에서 추출된 이미지 파일이 없습니다: {temp_dir}")
            
    #         self.logger.info(f"WebP 추출 완료: {len(extracted_files)}개 프레임")
            
    #         if progress_callback:
    #             progress_callback(100)  # 추출 완료
            
    #         return temp_image_pattern
        
    #     except Exception as e:
    #         self.logger.exception(f"WebP 추출 중 오류 발생: {str(e)}")
    #         # 임시 디렉토리 정리
    #         try:
    #             shutil.rmtree(temp_dir)
    #             self.logger.info(f"임시 디렉토리 제거됨: {temp_dir}")
    #         except Exception as cleanup_error:
    #             self.logger.warning(f"임시 디렉토리 제거 실패: {cleanup_error}")
    #         raise


# # 이전 버전과의 호환성을 위한 함수
# def process_image_sequence(
#     input_file: str,
#     trim_start: int,
#     trim_end: int,
#     encoding_options: dict,
#     target_properties: dict,
#     debug_mode: bool,
#     idx: int,
#     progress_callback=None,
#     use_frame_based_trim: bool = False
# ) -> str:
#     """
#     이미지 시퀀스를 처리하고 임시 출력 파일을 반환합니다.
#     진행률 콜백을 통해 처리 진행 상황을 보고합니다.
    
#     이 함수는 이전 버전과의 호환성을 위해 유지됩니다.
#     """
#     processor = ImageProcessor()
#     return processor.process_image_sequence(
#         input_file, trim_start, trim_end, encoding_options, target_properties,
#         debug_mode, idx, progress_callback, use_frame_based_trim
#     )

# def extract_webp_to_image_sequence(
#     input_file: str,
#     temp_dir: str,
#     progress_callback=None
# ) -> str:
#     """
#     WebP 애니메이션 파일을 이미지 시퀀스로 추출합니다.
    
#     이 함수는 이전 버전과의 호환성을 위해 유지됩니다.
#     """
#     processor = ImageProcessor()
#     return processor.extract_webp_to_image_sequence(input_file, temp_dir, progress_callback)