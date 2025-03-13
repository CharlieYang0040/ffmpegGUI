import os
import re
import logging
import ffmpeg
import subprocess

# 로깅 서비스 가져오기
from app.services.logging_service import LoggingService

# FFmpegManager 싱글톤 가져오기
from app.core.ffmpeg_manager import FFmpegManager

# ffmpeg_core에서 필요한 함수 가져오기
from app.core.ffmpeg_core import apply_filters, get_optimal_encoding_options, get_media_properties

# 로거 설정
logger = LoggingService().get_logger(__name__)

class VideoProcessor:
    """비디오 파일 처리를 위한 클래스"""
    
    def __init__(self, ffmpeg_manager=None):
        """
        비디오 프로세서 초기화
        
        Args:
            ffmpeg_manager: FFmpegManager 인스턴스 (없으면 싱글톤 인스턴스 사용)
        """
        self.ffmpeg_manager = ffmpeg_manager or FFmpegManager()
        self.logger = LoggingService().get_logger(__name__)
    
    def process_video_file(
        self,
        input_file: str,
        trim_start: int,
        trim_end: int,
        encoding_options: dict,
        target_properties: dict,
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
            self.logger.info(f"비디오 파일 처리 시작: {input_file}")
            
            # FFmpeg 경로 확인
            ffmpeg_path = self.ffmpeg_manager.get_ffmpeg_path()
            if not ffmpeg_path:
                raise ValueError("FFmpeg 경로가 설정되지 않았습니다.")

            if progress_callback:
                progress_callback(5)  # 시작 진행률

            # 비디오 속성 가져오기
            video_properties = get_media_properties(input_file, debug_mode)
            
            if progress_callback:
                progress_callback(15)  # 속성 분석 완료

            # 비디오 길이 계산
            duration = float(video_properties.get('duration', 0))
            if duration <= 0:
                self.logger.warning(f"'{input_file}'의 길이를 가져올 수 없습니다.")
                duration = 0

            # 인코딩 옵션 설정
            encoding_options = get_optimal_encoding_options(encoding_options)

            # 비디오 총 프레임 수 계산
            fps = float(video_properties.get('r', 30))
            
            # nb_frames를 직접 사용하여 총 프레임 수 계산
            if 'nb_frames' in video_properties and int(video_properties['nb_frames']) > 0:
                total_frames = int(video_properties['nb_frames'])
                if debug_mode:
                    self.logger.debug(f"nb_frames 정보 사용: {total_frames}프레임")
            else:
                # nb_frames가 없는 경우에만 duration * fps 사용
                total_frames = int(duration * fps)
                self.logger.warning(f"nb_frames 정보가 없어 duration * fps로 계산: {duration} * {fps} = {total_frames}")
            
            # 오디오 스트림 존재 여부 확인
            has_audio = 'a' in video_properties
            if debug_mode:
                self.logger.debug(f"오디오 스트림 존재 여부: {has_audio}")
            
            # 프레임 기반 트림 사용 시 트림 값 검증 및 조정
            if use_frame_based_trim:
                # 트림 값이 소수점인 경우 정수로 변환
                if isinstance(trim_start, float):
                    trim_start = int(trim_start)
                if isinstance(trim_end, float):
                    trim_end = int(trim_end)
                
                # 시작 프레임이 0이면 처음부터 시작
                if trim_start <= 0:
                    trim_start = 0
                
                # 끝 프레임이 0이면 마지막 프레임까지 사용
                if trim_end <= 0:
                    end_frame = total_frames - 1
                else:
                    # 끝 프레임이 총 프레임 수보다 크면 조정
                    end_frame = min(total_frames - 1, trim_end)
                
                # 시작 프레임이 끝 프레임보다 크면 조정
                if trim_start >= end_frame:
                    self.logger.warning(f"시작 프레임({trim_start})이 끝 프레임({end_frame})보다 크거나 같습니다. 값을 조정합니다.")
                    trim_start = max(0, end_frame - 1)
                
                # 트림 후 남은 프레임 수 계산
                new_total_frames = end_frame - trim_start + 1
                
                if new_total_frames <= 0:
                    self.logger.warning(f"'{input_file}'의 트림 후 남은 프레임이 없습니다. 기본값을 사용합니다.")
                    # 최소 1프레임은 남기도록 조정
                    trim_start = 0
                    end_frame = max(1, total_frames - 1)
                    new_total_frames = end_frame - trim_start + 1
            else:
                # 초 단위 트림 방식 (기존 로직)
                # 트림 후 남은 프레임 수 계산
                new_total_frames = total_frames - trim_start - trim_end
                if new_total_frames <= 0:
                    self.logger.warning(f"'{input_file}'의 트림 후 남은 프레임이 없습니다. 원본 파일을 사용합니다.")
                    # 트림 값을 0으로 설정하여 원본 파일 그대로 사용
                    trim_start = 0
                    trim_end = 0
                    new_total_frames = total_frames
                
                # 트림 끝 프레임 계산
                end_frame = total_frames - trim_end - 1
            
            if debug_mode:
                self.logger.debug(f"비디오 속성: {video_properties}")
                self.logger.debug(f"총 프레임 수: {total_frames}")
                self.logger.debug(f"트림 정보 - 시작 프레임: {trim_start}, 끝 프레임: {end_frame}, 남은 프레임 수: {new_total_frames}")

            if progress_callback:
                progress_callback(20)  # 트림 계산 완료

            # 프레임 단위 트림 방식 선택 (초 단위 변환 또는 프레임 단위 직접 트림)
            if use_frame_based_trim:
                # 프레임 단위 직접 트림 (select 필터 사용)
                # 입력 옵션 설정
                input_args = {
                    'probesize': '100M',
                    'analyzeduration': '100M'
                }
                
                # 필터 설정 (프레임 번호로 직접 선택)
                vf_filter = f"select=between(n\\,{trim_start}\\,{end_frame}),setpts=PTS-STARTPTS"
                
                # 로그 출력 추가
                self.logger.info(f"프레임 기반 트림 적용: 파일={input_file}, 시작 프레임={trim_start}, 끝 프레임={end_frame}")
                self.logger.info(f"비디오 필터: {vf_filter}")
                
                if debug_mode:
                    self.logger.debug(f"프레임 단위 트림 필터: {vf_filter}")
                
                if progress_callback:
                    progress_callback(25)  # 옵션 설정 완료
                
                # 스트림 생성
                stream = ffmpeg.input(input_file, **input_args)
                
                # 비디오 필터 적용
                video_stream = stream.video.filter('select', f'between(n,{trim_start},{end_frame})').filter('setpts', 'PTS-STARTPTS')
                
                # 필터 적용 후 추가 필터 적용
                if target_properties:
                    video_stream = apply_filters(video_stream, target_properties)
                
                # 오디오 스트림이 있는 경우에만 오디오 처리
                if has_audio:
                    try:
                        # 오디오 필터 설정
                        af_filter = f"aselect=between(n\\,{trim_start * 1470 // total_frames}\\,{end_frame * 1470 // total_frames}),asetpts=PTS-STARTPTS"
                        self.logger.info(f"오디오 필터: {af_filter}")
                        
                        if debug_mode:
                            self.logger.debug(f"오디오 트림 필터: {af_filter}")
                        
                        # 오디오 필터 적용
                        audio_stream = stream.audio.filter('aselect', f'between(n,{trim_start * 1470 // total_frames},{end_frame * 1470 // total_frames})').filter('asetpts', 'PTS-STARTPTS')
                        
                        # 출력 스트림 설정 (비디오 + 오디오)
                        stream = ffmpeg.output(video_stream, audio_stream, temp_output, **encoding_options)
                    except Exception as e:
                        self.logger.warning(f"오디오 스트림 처리 중 오류 발생: {e}")
                        # 오디오 처리 실패 시 비디오만 출력
                        stream = ffmpeg.output(video_stream, temp_output, **encoding_options)
                else:
                    # 오디오 스트림이 없는 경우 비디오만 출력
                    self.logger.info("오디오 스트림이 없습니다. 비디오만 처리합니다.")
                    stream = ffmpeg.output(video_stream, temp_output, **encoding_options)
            else:
                # 기존 방식: 초 단위로 변환하여 트림
                # 트림 값을 초 단위로 변환
                trim_start_sec = trim_start / fps if fps > 0 else 0
                trim_end_sec = trim_end / fps if fps > 0 else 0

                # 새 길이 계산
                new_duration = duration - trim_start_sec - trim_end_sec
                
                if debug_mode:
                    self.logger.debug(f"트림 정보 - 시작: {trim_start_sec}초, 끝: {trim_end_sec}초, 새 길이: {new_duration}초")

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
                    self.logger.debug(f"입력 옵션: {input_args}")
                    self.logger.debug(f"인코딩 옵션: {encoding_options}")

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
                self.logger.debug(f"비디오 처리 명령어: {' '.join(ffmpeg.compile(stream, cmd=ffmpeg_path))}")

            if progress_callback:
                progress_callback(30)  # FFmpeg 명령 준비 완료

            # FFmpeg 실행 (진행률 모니터링)
            process = subprocess.Popen(
                ffmpeg.compile(stream, cmd=ffmpeg_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                bufsize=1
            )
            
            # 진행률 모니터링
            for line in process.stderr:
                if debug_mode:
                    self.logger.debug(line.strip())
                
                # 진행률 파싱 및 업데이트
                if progress_callback and "time=" in line:
                    try:
                        time_match = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                        if time_match:
                            time_str = time_match.group(1)
                            h, m, s = map(float, time_str.split(':'))
                            current_seconds = h * 3600 + m * 60 + s
                            # 0으로 나누기 방지
                            if new_duration > 0:
                                progress = min(30 + (current_seconds / new_duration) * 70, 100)
                            else:
                                progress = 50  # 총 기간을 알 수 없는 경우 기본값 사용
                            progress_callback(int(progress))
                    except Exception as e:
                        self.logger.warning(f"진행률 파싱 오류: {e}")
            
            process.wait()
            
            if process.returncode != 0:
                raise Exception(f"FFmpeg 실행 실패 (반환 코드: {process.returncode})")
            
            self.logger.info(f"비디오 파일 처리 완료: {input_file}")
            
            if progress_callback:
                progress_callback(100)  # 처리 완료
                
            return temp_output

        except Exception as e:
            self.logger.exception(f"비디오 파일 처리 중 오류 발생: {str(e)}")
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                    self.logger.info(f"임시 파일 제거됨: {temp_output}")
                except Exception as cleanup_error:
                    self.logger.warning(f"임시 파일 제거 실패: {cleanup_error}")
            raise
    
    def parse_ffmpeg_video_progress(self, output: str) -> float:
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
            self.logger.warning(f"진행률 파싱 중 오류: {e}")
        
        return None


# # 이전 버전과의 호환성을 위한 함수
# def process_video_file(
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
#     비디오 파일을 처리하고 임시 출력 파일을 반환합니다.
    
#     이 함수는 이전 버전과의 호환성을 위해 유지됩니다.
#     """
#     processor = VideoProcessor()
#     return processor.process_video_file(
#         input_file, trim_start, trim_end, encoding_options, target_properties,
#         debug_mode, idx, progress_callback, use_frame_based_trim
#     )

# def parse_ffmpeg_progress(output: str) -> float:
#     """
#     FFmpeg 출력에서 진행률 파싱
    
#     이 함수는 이전 버전과의 호환성을 위해 유지됩니다.
#     """
#     processor = VideoProcessor()
#     return processor.parse_ffmpeg_progress(output)