import os
import re
import glob
import logging
import subprocess
import shutil
import tempfile
import json
from PIL import Image, ImageSequence  # Pillow for WebP handling
import io
from typing import Dict, Optional, Callable

# 로깅 서비스 가져오기
from app.services.logging_service import LoggingService

# FFmpegManager 싱글톤 가져오기
from app.core.ffmpeg_manager import FFmpegManager

# 로깅 설정
logger = LoggingService().get_logger(__name__)

class WebPProcessor:
    """WebP 파일 처리를 위한 클래스"""
    
    def __init__(self, ffmpeg_manager=None):
        """
        WebP 프로세서 초기화
        
        Args:
            ffmpeg_manager: FFmpegManager 인스턴스 (없으면 싱글톤 인스턴스 사용)
        """
        self.ffmpeg_manager = ffmpeg_manager or FFmpegManager()
        self.logger = LoggingService().get_logger(__name__)

    def extract_webp_to_image_sequence(
        self,
        input_file: str,
        temp_dir: str,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> str:
        """
        WebP 애니메이션 파일을 이미지 시퀀스로 추출합니다.
        추출된 이미지 파일 패턴을 반환합니다.
        Pillow 라이브러리를 사용하여 WebP 파일을 처리합니다.
        
        Args:
            input_file: WebP 파일 경로
            temp_dir: 이미지 시퀀스를 저장할 임시 디렉토리
            progress_callback: 진행률 콜백 함수 (선택적)
            
        Returns:
            추출된 이미지 파일 패턴 (예: '/path/to/temp/frame_%05d.png')
        """
        try:
            self.logger.info(f"WebP 애니메이션 추출 시작: {input_file}")
            
            if progress_callback:
                progress_callback(5)  # 시작 진행률
                
            # 임시 디렉토리 생성
            os.makedirs(temp_dir, exist_ok=True)
            temp_image_pattern = os.path.join(temp_dir, 'frame_%05d.png')
            
            if progress_callback:
                progress_callback(10)  # 디렉토리 생성 완료
            
            # Pillow를 사용하여 WebP 파일 로드
            webp_image = Image.open(input_file)
            
            # WebP가 애니메이션인지 확인
            is_animated = hasattr(webp_image, 'is_animated') and webp_image.is_animated
            
            if not is_animated:
                # 애니메이션이 아닌 경우 단일 이미지로 저장
                frame_path = os.path.join(temp_dir, 'frame_00000.png')
                webp_image.save(frame_path, 'PNG')
                self.logger.info(f"단일 프레임 WebP 저장됨: {frame_path}")
                
                if progress_callback:
                    progress_callback(100)  # 추출 완료
                    
                return temp_image_pattern
            
            # 애니메이션 WebP 처리
            frame_count = getattr(webp_image, 'n_frames', 1)
            self.logger.info(f"WebP 애니메이션 프레임 수: {frame_count}")
            
            # 각 프레임 추출 및 저장
            for frame_idx in range(frame_count):
                if progress_callback:
                    # 10%에서 시작하여 90%까지 진행
                    progress = 10 + int((frame_idx / frame_count) * 90)
                    progress_callback(progress)
                    # # 로그 추가
                    # if frame_idx % 10 == 0 or frame_idx == frame_count - 1:
                    #     self.logger.debug(f"WebP 프레임 추출 진행률: {progress}% ({frame_idx+1}/{frame_count})")
                
                # 현재 프레임으로 이동
                webp_image.seek(frame_idx)
                
                # 프레임 저장 (RGBA -> RGB 변환)
                frame_path = os.path.join(temp_dir, f'frame_{frame_idx:05d}.png')
                
                # RGBA 모드인 경우 RGB로 변환 (알파 채널 제거)
                if webp_image.mode == 'RGBA':
                    # 흰색 배경에 알파 채널 합성
                    background = Image.new('RGB', webp_image.size, (255, 255, 255))
                    background.paste(webp_image, mask=webp_image.split()[3])  # 알파 채널을 마스크로 사용
                    background.save(frame_path, 'PNG')
                else:
                    webp_image.convert('RGB').save(frame_path, 'PNG')
                
                # self.logger.debug(f"프레임 저장됨: {frame_path}")
            
            # 추출된 파일 확인
            extracted_files = sorted(glob.glob(os.path.join(temp_dir, 'frame_*.png')))
            if not extracted_files:
                raise FileNotFoundError(f"WebP에서 추출된 이미지 파일이 없습니다: {temp_dir}")
            
            self.logger.info(f"WebP 추출 완료: {len(extracted_files)}개 프레임")
            
            if progress_callback:
                progress_callback(100)  # 추출 완료
            
            return temp_image_pattern
        
        except Exception as e:
            self.logger.exception(f"WebP 추출 중 오류 발생: {str(e)}")
            # 임시 디렉토리 정리
            try:
                shutil.rmtree(temp_dir)
                self.logger.info(f"임시 디렉토리 제거됨: {temp_dir}")
            except Exception as cleanup_error:
                self.logger.warning(f"임시 디렉토리 제거 실패: {cleanup_error}")
            raise

    def get_webp_metadata(self, input_file: str) -> Dict:
        """
        WebP 파일의 메타데이터를 분석합니다.
        
        Args:
            input_file: WebP 파일 경로
            
        Returns:
            메타데이터 정보를 담은 딕셔너리
        """
        try:
            self.logger.info(f"WebP 메타데이터 분석 시작: {input_file}")
            
            metadata = {
                'width': 0,
                'height': 0,
                'frame_count': 0,
                'is_animated': False,
                'fps': 0,
                'duration_ms': 0,
                'loop_count': 0,
                'frame_durations': []
            }
            
            # Pillow를 사용하여 WebP 파일 로드
            with Image.open(input_file) as webp_image:
                # 기본 정보 추출
                metadata['width'] = webp_image.width
                metadata['height'] = webp_image.height
                metadata['is_animated'] = hasattr(webp_image, 'is_animated') and webp_image.is_animated
                
                if metadata['is_animated']:
                    # 애니메이션 정보 추출
                    metadata['frame_count'] = getattr(webp_image, 'n_frames', 1)
                    
                    # 프레임 지속 시간 추출
                    total_duration = 0
                    frame_durations = []
                    
                    for i in range(metadata['frame_count']):
                        webp_image.seek(i)
                        duration = webp_image.info.get('duration', 0)  # 밀리초 단위
                        frame_durations.append(duration)
                        total_duration += duration
                    
                    metadata['frame_durations'] = frame_durations
                    metadata['duration_ms'] = total_duration
                    
                    # 평균 FPS 계산 (총 프레임 수 / 총 시간(초))
                    if total_duration > 0:
                        metadata['fps'] = round((metadata['frame_count'] * 1000) / total_duration, 2)
                    
                    # 루프 정보 추출
                    metadata['loop_count'] = webp_image.info.get('loop', 0)  # 0은 무한 루프
                else:
                    # 단일 이미지인 경우
                    metadata['frame_count'] = 1
            
            # FFmpeg를 사용한 추가 메타데이터 추출 시도
            try:
                ffprobe_path = self.ffmpeg_manager.get_ffprobe_path()
                if ffprobe_path and os.path.exists(ffprobe_path):
                    cmd = [
                        ffprobe_path,
                        '-v', 'quiet',
                        '-print_format', 'json',
                        '-show_format',
                        '-show_streams',
                        input_file
                    ]
                    
                    result = subprocess.run(cmd, capture_output=True, text=True)
                    if result.returncode == 0:
                        ffprobe_data = json.loads(result.stdout)
                        
                        # 스트림 정보에서 프레임레이트 추출
                        for stream in ffprobe_data.get('streams', []):
                            if stream.get('codec_type') == 'video':
                                # 프레임레이트 확인
                                if 'r_frame_rate' in stream:
                                    try:
                                        num, denom = map(int, stream['r_frame_rate'].split('/'))
                                        if denom > 0:
                                            ffmpeg_fps = num / denom
                                            # 기존 fps가 없거나 너무 낮은 경우 ffprobe 정보 사용
                                            if metadata['fps'] == 0 or metadata['fps'] < 1:
                                                metadata['fps'] = round(ffmpeg_fps, 2)
                                    except (ValueError, ZeroDivisionError):
                                        pass
            except Exception as e:
                self.logger.warning(f"FFprobe를 통한 메타데이터 추출 실패: {e}")
            
            # 기본 FPS 설정 (다른 방법으로 얻지 못한 경우)
            if metadata['fps'] == 0 or metadata['fps'] < 1:
                # WebP의 일반적인 기본값은 20fps이지만, 편집에는 표준 24fps가 더 적합할 수 있음
                metadata['fps'] = 20
            
            self.logger.info(f"WebP 메타데이터 분석 완료: {metadata}")
            return metadata
            
        except Exception as e:
            self.logger.exception(f"WebP 메타데이터 분석 중 오류 발생: {str(e)}")
            # 기본 메타데이터 반환
            return {
                'width': 0,
                'height': 0,
                'frame_count': 0,
                'is_animated': False,
                'fps': 20,  # 기본값
                'duration_ms': 0,
                'loop_count': 0,
                'frame_durations': []
            }

    def process_webp_file(
        self, 
        input_file: str, 
        encoding_options: Dict,
        debug_mode: bool = False,
        progress_callback: Optional[Callable[[int], None]] = None
    ) -> Dict:
        """
        WebP 파일을 처리하고 이미지 시퀀스로 변환합니다.
        
        Args:
            input_file: WebP 파일 경로
            encoding_options: 인코딩 옵션
            debug_mode: 디버그 모드 활성화 여부
            progress_callback: 진행률 콜백 함수
            
        Returns:
            처리 결과 정보 (이미지 시퀀스 패턴, 메타데이터 등)
        """
        try:
            self.logger.info(f"WebP 파일 처리 시작: {input_file}")
            
            if progress_callback:
                progress_callback(5)  # 시작 진행률
            
            # WebP 메타데이터 분석
            metadata = self.get_webp_metadata(input_file)
            
            if progress_callback:
                progress_callback(15)  # 메타데이터 분석 완료
            
            # FPS 정보가 있으면 인코딩 옵션에 추가
            if metadata['fps'] > 0:
                encoding_options['r'] = str(metadata['fps'])
                self.logger.info(f"WebP에서 추출한 프레임레이트 사용: {metadata['fps']}fps")
            
            if debug_mode:
                self.logger.debug(f"WebP 메타데이터: {metadata}")
                self.logger.debug(f"업데이트된 인코딩 옵션: {encoding_options}")
            
            # 임시 디렉토리 생성
            temp_dir = tempfile.mkdtemp()
            
            # 진행률 업데이트를 위한 래퍼 함수
            def webp_extract_progress(progress):
                if progress_callback:
                    # 15%에서 시작하여 90%까지 진행
                    adjusted_progress = 15 + (progress * 0.75)
                    progress_callback(int(adjusted_progress))
            
            # WebP 파일을 이미지 시퀀스로 변환
            image_sequence = self.extract_webp_to_image_sequence(
                input_file, temp_dir, webp_extract_progress
            )
            
            if progress_callback:
                progress_callback(100)  # 처리 완료
            
            return {
                'image_sequence': image_sequence,
                'temp_dir': temp_dir,
                'metadata': metadata,
                'encoding_options': encoding_options
            }
            
        except Exception as e:
            self.logger.exception(f"WebP 파일 처리 중 오류 발생: {str(e)}")
            raise