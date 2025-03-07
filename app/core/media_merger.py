import os
import re
import tempfile
import subprocess
import logging
import shutil  # 전역 shutil 모듈 임포트
from typing import List, Dict, Optional, Callable, Tuple

import ffmpeg

# 로깅 서비스 가져오기
from app.services.logging_service import LoggingService

# FFmpegManager 싱글톤 가져오기
from app.core.ffmpeg_manager import FFmpegManager

# ffmpeg_core에서 필요한 함수 가져오기
from app.core.ffmpeg_core import apply_filters, create_temp_file_list, get_video_duration

# 로거 설정
logger = LoggingService().get_logger(__name__)

class MediaMerger:
    """미디어 파일 병합을 위한 클래스"""
    
    def __init__(self, ffmpeg_manager=None):
        """
        미디어 병합기 초기화
        
        Args:
            ffmpeg_manager: FFmpegManager 인스턴스 (없으면 싱글톤 인스턴스 사용)
        """
        self.ffmpeg_manager = ffmpeg_manager or FFmpegManager()
        self.logger = LoggingService().get_logger(__name__)
    
    def concat_media_files(
        self,
        input_files: List[str],
        output_file: str,
        encoding_options: Dict[str, str],
        target_properties: Dict[str, str] = None,
        debug_mode: bool = False,
        progress_callback=None,
        task_callback=None
    ) -> str:
        """
        여러 미디어 파일을 하나로 병합합니다.
        
        Args:
            input_files: 병합할 미디어 파일 목록
            output_file: 출력 파일 경로
            encoding_options: 인코딩 옵션
            target_properties: 출력 미디어의 속성 (해상도 등)
            debug_mode: 디버그 모드 여부
            progress_callback: 진행률 콜백 함수
            task_callback: 작업 상태 콜백 함수
            
        Returns:
            병합된 출력 파일 경로
        """
        temp_list_file = None
        try:
            # FFmpeg 경로 확인
            ffmpeg_path = self.ffmpeg_manager.get_ffmpeg_path()
            if not ffmpeg_path:
                raise ValueError("FFmpeg 경로가 설정되지 않았습니다.")
                
            if not input_files:
                raise ValueError("병합할 파일이 없습니다.")
            
            if len(input_files) == 1:
                self.logger.info("병합할 파일이 하나뿐이므로 파일을 복사합니다.")
                try:
                    # 파일이 하나면 그냥 복사
                    import shutil as file_copy_module  # 지역 변수로 다시 임포트
                    file_copy_module.copy2(input_files[0], output_file)
                    if progress_callback:
                        progress_callback(100)  # 완료
                    return output_file
                except Exception as copy_error:
                    self.logger.error(f"파일 복사 중 오류 발생: {copy_error}")
                    raise
                
            self.logger.info(f"{len(input_files)}개 미디어 파일 병합 시작")
            
            if task_callback:
                task_callback(f"파일 병합 중... ({len(input_files)}개 파일)")
            
            if progress_callback:
                progress_callback(5)  # 시작 진행률
            
            # 임시 파일 목록 생성
            temp_list_file = create_temp_file_list(input_files)
            
            if progress_callback:
                progress_callback(10)  # 파일 목록 생성 완료

            # 병합 옵션 설정
            concat_options = {
                'f': 'concat',
                'safe': '0'
            }
            
            if progress_callback:
                progress_callback(15)  # FFmpeg 명령 준비 완료
            
            # 스트림 생성
            stream = ffmpeg.input(temp_list_file, **concat_options)
            
            # 필터 적용 (필요한 경우)
            if target_properties:
                stream = apply_filters(stream, target_properties)

            # 출력 스트림 설정
            stream = ffmpeg.output(stream, output_file, **encoding_options)
            stream = stream.overwrite_output()

            if debug_mode:
                self.logger.debug(f"병합 명령어: {' '.join(ffmpeg.compile(stream, cmd=ffmpeg_path))}")
            
            # 총 길이 계산 (모든 파일의 길이 합산)
            total_duration = 0
            for file in input_files:
                try:
                    duration = get_video_duration(file)
                    total_duration += duration
                    if debug_mode:
                        self.logger.debug(f"파일 길이: {file} - {duration}초")
                except Exception as e:
                    self.logger.warning(f"파일 길이 계산 실패: {file} - {e}")
            
            if total_duration <= 0:
                # 길이를 계산할 수 없는 경우 적당한 기본값 설정
                total_duration = len(input_files) * 60  # 파일당 평균 1분으로 가정
                self.logger.warning(f"파일 길이를 계산할 수 없어 기본값 사용: {total_duration}초")
                
            if debug_mode:
                self.logger.debug(f"총 병합 길이: {total_duration}초")

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
                            if total_duration > 0:
                                progress = min(15 + (current_seconds / total_duration) * 85, 100)
                            else:
                                progress = 50  # 총 기간을 알 수 없는 경우 기본값 사용
                            progress_callback(int(progress))
                    except Exception as e:
                        self.logger.warning(f"진행률 파싱 오류: {e}")
            
            process.wait()
            
            if process.returncode != 0:
                stderr_output = "\n".join([line for line in process.stderr])
                
                # 특정 에러 코드 처리 (4294967274 = -22, 유효하지 않은 인자)
                if process.returncode == 4294967274 or process.returncode == -22:
                    self.logger.warning(f"FFmpeg concat 명령 실패 (코드: {process.returncode}), 대체 방법 시도")
                    
                    # 파일이 하나뿐인 경우 단순 복사로 대체
                    if len(input_files) == 1:
                        self.logger.warning("병합 실패, 단일 파일 복사로 대체합니다.")
                        try:
                            import shutil as file_copy_module  # 지역 변수로 다시 임포트
                            file_copy_module.copy2(input_files[0], output_file)
                            self.logger.info(f"파일 복사 완료: {input_files[0]} -> {output_file}")
                            return output_file
                        except Exception as copy_error:
                            self.logger.error(f"파일 복사 실패: {copy_error}")
                    
                    # 여러 파일인 경우 대체 방법으로 병합 시도
                    else:
                        self.logger.warning(f"대체 방법으로 {len(input_files)}개 파일 병합 시도")
                        try:
                            # 대체 방법: filter_complex를 사용한 병합
                            return self.concat_with_filter_complex(
                                input_files, output_file, encoding_options, 
                                target_properties, debug_mode, progress_callback, task_callback
                            )
                        except Exception as alt_error:
                            self.logger.error(f"대체 병합 방법도 실패: {alt_error}")
                
                # 일반적인 에러 처리
                error_msg = f"FFmpeg 실행 실패 (반환 코드: {process.returncode})"
                if stderr_output:
                    error_msg += f"\n오류 메시지: {stderr_output}"
                
                self.logger.error(error_msg)
                raise Exception(error_msg)
            
            self.logger.info(f"파일 병합 완료: {output_file}")
            
            if task_callback:
                task_callback("병합 완료!")
                
            if progress_callback:
                progress_callback(100)  # 처리 완료
                
            return output_file

        except Exception as e:
            self.logger.exception(f"파일 병합 중 오류 발생: {str(e)}")
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                    self.logger.info(f"실패한 출력 파일 제거됨: {output_file}")
                except Exception as cleanup_error:
                    self.logger.warning(f"출력 파일 제거 실패: {cleanup_error}")
            raise
            
        finally:
            # 임시 파일 목록 정리
            if temp_list_file and os.path.exists(temp_list_file):
                try:
                    os.remove(temp_list_file)
                    self.logger.debug(f"임시 파일 목록 제거됨: {temp_list_file}")
                except Exception as e:
                    self.logger.warning(f"임시 파일 목록 제거 실패: {e}")
    
    def check_merge_compatibility(
        self,
        input_files: List[str], 
        debug_mode: bool = False
    ) -> Dict[str, bool]:
        """
        병합될 파일들의 호환성을 검사합니다.
        
        Args:
            input_files: 병합할 미디어 파일 목록
            debug_mode: 디버그 모드 여부
            
        Returns:
            호환성 검사 결과를 포함하는 딕셔너리
            {
                'compatible': 모든 파일이 호환 가능한지 여부,
                'resolution_match': 해상도가 일치하는지 여부,
                'codec_match': 코덱이 일치하는지 여부,
                'framerate_match': 프레임레이트가 일치하는지 여부
            }
        """
        if not input_files or len(input_files) < 2:
            return {'compatible': True}  # 파일이 하나이면 호환 문제 없음
            
        try:
            from app.core.ffmpeg_core import get_media_properties
            
            result = {
                'compatible': True,
                'resolution_match': True,
                'codec_match': True,
                'framerate_match': True
            }
            
            # 첫 번째 파일의 속성을 기준으로 사용
            base_props = get_media_properties(input_files[0], debug_mode)
            if not base_props:
                self.logger.warning(f"첫 번째 파일의 속성을 가져올 수 없습니다: {input_files[0]}")
                return {'compatible': False}
                
            base_width = base_props.get('width')
            base_height = base_props.get('height')
            base_codec = base_props.get('codec_name')
            base_fps = base_props.get('r')
            
            if debug_mode:
                self.logger.debug(f"기준 파일 속성: 해상도={base_width}x{base_height}, 코덱={base_codec}, FPS={base_fps}")
            
            # 나머지 파일들과 비교
            for i, file_path in enumerate(input_files[1:], 1):
                props = get_media_properties(file_path, debug_mode)
                if not props:
                    self.logger.warning(f"파일 속성을 가져올 수 없습니다: {file_path}")
                    result['compatible'] = False
                    continue
                    
                width = props.get('width')
                height = props.get('height')
                codec = props.get('codec_name')
                fps = props.get('r')
                
                if debug_mode:
                    self.logger.debug(f"파일 {i+1} 속성: 해상도={width}x{height}, 코덱={codec}, FPS={fps}")
                
                # 해상도 검사
                if base_width != width or base_height != height:
                    result['resolution_match'] = False
                    if debug_mode:
                        self.logger.debug(f"해상도 불일치: {base_width}x{base_height} != {width}x{height}")
                
                # 코덱 검사
                if base_codec != codec:
                    result['codec_match'] = False
                    if debug_mode:
                        self.logger.debug(f"코덱 불일치: {base_codec} != {codec}")
                
                # 프레임레이트 검사
                if base_fps != fps:
                    result['framerate_match'] = False
                    if debug_mode:
                        self.logger.debug(f"프레임레이트 불일치: {base_fps} != {fps}")
            
            # 최종 호환성 결정
            # 해상도가 다르면 호환성 문제가 있지만, 자동으로 조정 가능
            # 따라서 해당 불일치만으로는 완전히 호환 불가능이라고 판단하지 않음
            result['compatible'] = result['codec_match'] and result['framerate_match']
            
            if debug_mode:
                self.logger.debug(f"호환성 검사 결과: {result}")
            
            return result
            
        except Exception as e:
            self.logger.exception(f"호환성 검사 중 오류 발생: {str(e)}")
            return {'compatible': False}

    def concat_with_filter_complex(
        self,
        input_files: List[str],
        output_file: str,
        encoding_options: Dict[str, str],
        target_properties: Dict[str, str] = None,
        debug_mode: bool = False,
        progress_callback=None,
        task_callback=None
    ) -> str:
        """
        filter_complex를 사용하여 미디어 파일을 병합합니다.
        concat 프로토콜이 실패할 경우 사용하는 대체 방법입니다.
        
        Args:
            input_files: 병합할 파일 목록
            output_file: 출력 파일 경로
            encoding_options: 인코딩 옵션
            target_properties: 타겟 속성 (해상도, 프레임레이트 등)
            debug_mode: 디버그 모드 여부
            progress_callback: 진행률 콜백 함수
            task_callback: 작업 상태 콜백 함수
            
        Returns:
            출력 파일 경로
        """
        try:
            # FFmpeg 경로 확인
            ffmpeg_path = self.ffmpeg_manager.get_ffmpeg_path()
            if not ffmpeg_path:
                raise ValueError("FFmpeg 경로가 설정되지 않았습니다.")
                
            if not input_files:
                raise ValueError("병합할 파일이 없습니다.")
            
            if len(input_files) == 1:
                self.logger.info("병합할 파일이 하나뿐이므로 파일을 복사합니다.")
                # 파일이 하나면 그냥 복사
                import shutil as file_copy_module
                file_copy_module.copy2(input_files[0], output_file)
                if progress_callback:
                    progress_callback(100)  # 완료
                return output_file
                
            self.logger.info(f"filter_complex로 {len(input_files)}개 미디어 파일 병합 시작")
            
            if task_callback:
                task_callback(f"filter_complex로 파일 병합 중... ({len(input_files)}개 파일)")
            
            if progress_callback:
                progress_callback(5)  # 시작 진행률
            
            # 입력 스트림 생성
            inputs = []
            for input_file in input_files:
                inputs.append(ffmpeg.input(input_file))
            
            if progress_callback:
                progress_callback(10)  # 입력 스트림 생성 완료
            
            # filter_complex 문자열 생성
            filter_complex = ""
            for i in range(len(inputs)):
                filter_complex += f"[{i}:v]"
            filter_complex += f"concat=n={len(inputs)}:v=1:a=0[outv]"
            
            # 출력 스트림 설정
            stream = ffmpeg.output(
                inputs[0].video.filter("concat", n=len(inputs), v=1, a=0),
                output_file,
                **encoding_options
            )
            stream = stream.overwrite_output()
            
            if debug_mode:
                self.logger.debug(f"filter_complex 병합 명령어: {' '.join(ffmpeg.compile(stream, cmd=ffmpeg_path))}")
            
            # 총 길이 계산 (모든 파일의 길이 합산)
            total_duration = 0
            for file in input_files:
                try:
                    duration = get_video_duration(file)
                    total_duration += duration
                    if debug_mode:
                        self.logger.debug(f"파일 길이: {file} - {duration}초")
                except Exception as e:
                    self.logger.warning(f"파일 길이 계산 실패: {file} - {e}")
            
            if total_duration <= 0:
                # 길이를 계산할 수 없는 경우 적당한 기본값 설정
                total_duration = len(input_files) * 60  # 파일당 평균 1분으로 가정
                self.logger.warning(f"파일 길이를 계산할 수 없어 기본값 사용: {total_duration}초")
                
            if debug_mode:
                self.logger.debug(f"총 병합 길이: {total_duration}초")
            
            if progress_callback:
                progress_callback(15)  # FFmpeg 명령 준비 완료
            
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
                            if total_duration > 0:
                                progress = min(15 + (current_seconds / total_duration) * 85, 100)
                            else:
                                progress = 50  # 총 기간을 알 수 없는 경우 기본값 사용
                            progress_callback(int(progress))
                    except Exception as e:
                        self.logger.warning(f"진행률 파싱 오류: {e}")
            
            process.wait()
            
            if process.returncode != 0:
                stderr_output = "\n".join([line for line in process.stderr])
                error_msg = f"filter_complex 병합 실패 (반환 코드: {process.returncode})"
                if stderr_output:
                    error_msg += f"\n오류 메시지: {stderr_output}"
                
                self.logger.error(error_msg)
                raise Exception(error_msg)
            
            self.logger.info(f"filter_complex 병합 완료: {output_file}")
            
            if task_callback:
                task_callback("병합 완료!")
                
            if progress_callback:
                progress_callback(100)  # 처리 완료
                
            return output_file
            
        except Exception as e:
            self.logger.exception(f"filter_complex 병합 중 오류 발생: {str(e)}")
            
            # 출력 파일이 존재하면 제거
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                    self.logger.info(f"실패한 출력 파일 제거됨: {output_file}")
                except Exception as remove_error:
                    self.logger.warning(f"실패한 출력 파일 제거 실패: {remove_error}")
            
            raise


# # 이전 버전과의 호환성을 위한 함수
# def concat_media_files(
#     input_files: List[str],
#     output_file: str,
#     encoding_options: Dict[str, str],
#     target_properties: Dict[str, str] = None,
#     debug_mode: bool = False,
#     progress_callback=None,
#     task_callback=None
# ) -> str:
#     """
#     여러 미디어 파일을 하나로 병합합니다.
    
#     이 함수는 이전 버전과의 호환성을 위해 유지됩니다.
#     """
#     merger = MediaMerger()
#     return merger.concat_media_files(
#         input_files, output_file, encoding_options, target_properties,
#         debug_mode, progress_callback, task_callback
#     )

# def check_merge_compatibility(
#     input_files: List[str], 
#     debug_mode: bool = False
# ) -> Dict[str, bool]:
#     """
#     병합될 파일들의 호환성을 검사합니다.
    
#     이 함수는 이전 버전과의 호환성을 위해 유지됩니다.
#     """
#     merger = MediaMerger()
#     return merger.check_merge_compatibility(input_files, debug_mode)