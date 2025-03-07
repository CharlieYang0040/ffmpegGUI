"""
FFmpeg GUI 애플리케이션을 위한 유틸리티 모듈

이 모듈은 비디오 처리, 이미지 시퀀스 처리, 미디어 병합 등의
모든 FFmpeg 관련 기능에 대한 통합 인터페이스를 제공합니다.
"""

import logging
from typing import List, Dict, Tuple, Optional, Callable
import os

# 로깅 서비스 가져오기
from app.services.logging_service import LoggingService

# FFmpegManager 싱글톤 가져오기
from app.core.ffmpeg_manager import FFmpegManager

# 프로세서 팩토리 가져오기
from app.core.processor_factory import ProcessorFactory

# 배치 프로세서 가져오기
from app.core.batch_processor import BatchProcessor

# 로거 설정
logger = LoggingService().get_logger(__name__)

# 현재 모듈에서 직접 노출할 상수 및 변수 정의
__version__ = "2.0.0"

# 버전 정보 로깅
logger.debug(f"FFmpeg GUI 유틸리티 모듈 버전 {__version__} 로드됨")

class FFmpegUtils:
    """
    FFmpeg 관련 유틸리티 기능을 제공하는 클래스
    
    이 클래스는 FFmpegManager, ProcessorFactory, BatchProcessor 등의
    핵심 클래스를 사용하여 통합된 인터페이스를 제공합니다.
    """
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FFmpegUtils, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        """싱글톤 인스턴스 초기화"""
        from app.core.ffmpeg_manager import FFmpegManager
        from app.core.processor_factory import ProcessorFactory
        from app.core.batch_processor import BatchProcessor
        from app.services.logging_service import LoggingService
        
        self.ffmpeg_manager = FFmpegManager()
        self.processor_factory = ProcessorFactory(self.ffmpeg_manager)
        self.batch_processor = BatchProcessor(self.ffmpeg_manager)
        self.logger = LoggingService().get_logger(__name__)
        
        self.logger.debug("FFmpegUtils 초기화됨")
    
    def get_version_info(self) -> Dict[str, str]:
        """
        현재 모듈 및 FFmpeg 버전 정보를 반환합니다.
        
        Returns:
            버전 정보가 포함된 딕셔너리
        """
        return {
            'module_version': __version__,
            **self.ffmpeg_manager.get_version_info()
        }
    
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
        
        Args:
            input_file: 입력 파일 경로
            trim_start: 트림 시작 값
            trim_end: 트림 끝 값
            encoding_options: 인코딩 옵션
            target_properties: 출력 미디어의 속성 (해상도 등)
            debug_mode: 디버그 모드 여부
            idx: 파일 인덱스
            progress_callback: 진행률 콜백 함수
            use_frame_based_trim: 프레임 기반 트림 사용 여부
            
        Returns:
            처리된 임시 파일 경로
        """
        video_processor = self.processor_factory.create_processor('video')
        return video_processor.process_video_file(
            input_file, trim_start, trim_end, encoding_options,
            target_properties, debug_mode, idx, progress_callback,
            use_frame_based_trim
        )
    
    def process_image_sequence(
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
        이미지 시퀀스를 처리하고 임시 출력 파일을 반환합니다.
        
        Args:
            input_file: 입력 파일 패턴
            trim_start: 트림 시작 값
            trim_end: 트림 끝 값
            encoding_options: 인코딩 옵션
            target_properties: 출력 미디어의 속성 (해상도 등)
            debug_mode: 디버그 모드 여부
            idx: 파일 인덱스
            progress_callback: 진행률 콜백 함수
            use_frame_based_trim: 프레임 기반 트림 사용 여부
            
        Returns:
            처리된 임시 파일 경로
        """
        image_processor = self.processor_factory.create_processor('image')
        return image_processor.process_image_sequence(
            input_file, trim_start, trim_end, encoding_options,
            target_properties, debug_mode, idx, progress_callback,
            use_frame_based_trim
        )
    
    def extract_webp_to_image_sequence(
        self,
        input_file: str,
        temp_dir: str,
        progress_callback=None
    ) -> str:
        """
        WebP 애니메이션 파일을 이미지 시퀀스로 추출합니다.
        
        Args:
            input_file: WebP 파일 경로
            temp_dir: 임시 디렉토리 경로
            progress_callback: 진행률 콜백 함수
            
        Returns:
            추출된 이미지 시퀀스 패턴
        """
        image_processor = self.processor_factory.create_processor('image')
        return image_processor.extract_webp_to_image_sequence(
            input_file, temp_dir, progress_callback
        )
    
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
        media_merger = self.processor_factory.create_processor('merger')
        return media_merger.concat_media_files(
            input_files, output_file, encoding_options, target_properties,
            debug_mode, progress_callback, task_callback
        )
    
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
        """
        media_merger = self.processor_factory.create_processor('merger')
        return media_merger.check_merge_compatibility(input_files, debug_mode)
    
    def process_all_media(
        self,
        media_files: List[Tuple[str, int, int]],
        output_file: str,
        encoding_options: Dict[str, str],
        debug_mode: bool = False,
        trim_values: List[Tuple[int, int]] = None,
        global_trim_start: int = 0,
        global_trim_end: int = 0,
        progress_callback: Optional[Callable[[int], None]] = None,
        task_callback: Optional[Callable[[str], None]] = None,
        target_properties: Dict[str, str] = {},
        use_custom_framerate: bool = False,
        custom_framerate: float = 30.0,
        use_custom_resolution: bool = False,
        custom_width: int = 0,
        custom_height: int = 0,
        use_frame_based_trim: bool = False
    ) -> str:
        """
        여러 미디어 파일을 처리하고 하나의 출력 파일로 병합합니다.
        
        Args:
            media_files: 처리할 미디어 파일 목록 (파일 경로, 트림 시작, 트림 끝)
            output_file: 출력 파일 경로
            encoding_options: 인코딩 옵션
            debug_mode: 디버그 모드 여부
            trim_values: 각 파일별 트림 값 (시작, 끝)
            global_trim_start: 전역 트림 시작 값
            global_trim_end: 전역 트림 끝 값
            progress_callback: 진행률 콜백 함수
            task_callback: 작업 상태 콜백 함수
            target_properties: 출력 미디어의 속성 (해상도 등)
            use_custom_framerate: 커스텀 프레임레이트 사용 여부
            custom_framerate: 커스텀 프레임레이트 값
            use_custom_resolution: 커스텀 해상도 사용 여부
            custom_width: 커스텀 너비
            custom_height: 커스텀 높이
            use_frame_based_trim: 프레임 기반 트림 사용 여부
            
        Returns:
            처리된 출력 파일 경로
        """
        return self.batch_processor.process_all_media(
            media_files, output_file, encoding_options, debug_mode, trim_values,
            global_trim_start, global_trim_end, progress_callback, task_callback,
            target_properties, use_custom_framerate, custom_framerate,
            use_custom_resolution, custom_width, custom_height, use_frame_based_trim
        )
    
    def process_single_media(
        self,
        input_file: str,
        trim_start: int,
        trim_end: int,
        encoding_options: Dict[str, str],
        target_properties: Dict[str, str],
        debug_mode: bool,
        idx: int,
        memory_threshold: int,
        progress_callback=None,
        use_frame_based_trim: bool = False
    ) -> str:
        """
        단일 미디어 파일을 처리합니다.
        
        Args:
            input_file: 입력 파일 경로
            trim_start: 트림 시작 값
            trim_end: 트림 끝 값
            encoding_options: 인코딩 옵션
            target_properties: 출력 미디어의 속성 (해상도 등)
            debug_mode: 디버그 모드 여부
            idx: 파일 인덱스
            memory_threshold: 메모리 임계값
            progress_callback: 진행률 콜백 함수
            use_frame_based_trim: 프레임 기반 트림 사용 여부
            
        Returns:
            처리된 임시 파일 경로
        """
        return self.batch_processor.process_single_media(
            input_file, trim_start, trim_end, encoding_options, target_properties,
            debug_mode, idx, memory_threshold, progress_callback, use_frame_based_trim
        )
    
    def get_media_properties(self, input_file: str, debug_mode: bool = False) -> dict:
        """
        미디어 파일의 속성을 가져옵니다.
        
        Args:
            input_file: 미디어 파일 경로
            debug_mode: 디버그 모드 여부
            
        Returns:
            미디어 속성 딕셔너리
        """
        from app.core.ffmpeg_core import get_media_properties
        return get_media_properties(input_file, debug_mode)
    
    def get_video_duration(self, input_file: str) -> float:
        """
        비디오 파일의 길이를 가져옵니다.
        
        Args:
            input_file: 비디오 파일 경로
            
        Returns:
            비디오 길이 (초)
        """
        from app.core.ffmpeg_core import get_video_duration
        return get_video_duration(input_file)
    
    def is_image_sequence(self, input_file: str) -> bool:
        """
        입력 파일이 이미지 시퀀스인지 확인합니다.
        
        Args:
            input_file: 입력 파일 경로
            
        Returns:
            이미지 시퀀스 여부
        """
        from app.core.ffmpeg_core import is_image_sequence
        return is_image_sequence(input_file)
    
    def get_target_properties(self, input_files: list, encoding_options: dict, debug_mode: bool) -> dict:
        """
        입력 파일들의 타겟 속성을 결정합니다.
        
        Args:
            input_files: 입력 파일 목록
            encoding_options: 인코딩 옵션
            debug_mode: 디버그 모드 여부
            
        Returns:
            타겟 속성 딕셔너리
        """
        from app.core.ffmpeg_core import get_target_properties
        return get_target_properties(input_files, encoding_options, debug_mode)
    
    def check_media_properties(self, input_files: list, target_properties: dict, debug_mode: bool):
        """
        입력 파일들의 속성을 확인하고 타겟 속성과 비교합니다.
        
        Args:
            input_files: 입력 파일 목록
            target_properties: 타겟 속성
            debug_mode: 디버그 모드 여부
        """
        from app.core.ffmpeg_core import check_media_properties
        check_media_properties(input_files, target_properties, debug_mode)
    
    def get_optimal_thread_count(self) -> int:
        """
        최적의 스레드 수를 반환합니다.
        
        Returns:
            최적의 스레드 수
        """
        from app.core.ffmpeg_core import get_optimal_thread_count
        return get_optimal_thread_count()
    
    def get_optimal_encoding_options(self, encoding_options: dict) -> dict:
        """
        최적화된 인코딩 옵션을 반환합니다.
        
        Args:
            encoding_options: 기본 인코딩 옵션
            
        Returns:
            최적화된 인코딩 옵션
        """
        from app.core.ffmpeg_core import get_optimal_encoding_options
        return get_optimal_encoding_options(encoding_options)
    
    def create_temp_file_list(self, temp_files: list) -> str:
        """
        임시 파일 목록을 생성합니다.
        
        Args:
            temp_files: 임시 파일 목록
            
        Returns:
            임시 파일 목록 파일 경로
        """
        from app.core.ffmpeg_core import create_temp_file_list
        return create_temp_file_list(temp_files)
    
    def parse_ffmpeg_video_progress(self, output: str) -> float:
        """
        FFmpeg 출력에서 진행률을 파싱합니다.
        
        Args:
            output: FFmpeg 출력 문자열
            
        Returns:
            진행률 (0.0 ~ 1.0)
        """
        video_processor = self.processor_factory.create_processor('video')
        return video_processor.parse_ffmpeg_video_progress(output)
    
    def parse_ffmpeg_image_progress(self, output: str) -> float:
        """
        FFmpeg 출력에서 진행률을 파싱합니다.

        Args:
            output: FFmpeg 출력 문자열
            
        Returns:
            진행률 (0.0 ~ 1.0)
        """
        image_processor = self.processor_factory.create_processor('image')
        return image_processor.parse_ffmpeg_image_progress(output)
    
    def update_webp_progress(self, progress, file_idx, total_files, webp_count, webp_processed, callback=None):
        """
        WebP 처리 진행률을 업데이트합니다.
        
        Args:
            progress: 현재 진행률
            file_idx: 현재 파일 인덱스
            total_files: 총 파일 수
            webp_count: WebP 파일 수
            webp_processed: 처리된 WebP 파일 수
            callback: 진행률 콜백 함수 (선택적)
        """
        if callback:
            self.batch_processor.update_webp_progress(
                progress, file_idx, total_files, webp_count, webp_processed, callback
            )
    
    def update_file_progress(self, progress, file_idx, total_files, base_progress, processing_weight, callback=None):
        """
        파일 처리 진행률을 업데이트합니다.
        
        Args:
            progress: 현재 진행률
            file_idx: 현재 파일 인덱스
            total_files: 총 파일 수
            base_progress: 기본 진행률
            processing_weight: 처리 가중치
            callback: 진행률 콜백 함수 (선택적)
        """
        if callback:
            self.batch_processor.update_file_progress(
                progress, file_idx, total_files, base_progress, processing_weight, callback
            )
    
    def update_merge_progress(self, progress, base_progress, merging_weight, callback=None):
        """
        병합 진행률을 업데이트합니다.
        
        Args:
            progress: 현재 진행률
            base_progress: 기본 진행률
            merging_weight: 병합 가중치
            callback: 진행률 콜백 함수 (선택적)
        """
        if callback:
            self.batch_processor.update_merge_progress(
                progress, base_progress, merging_weight, callback
            )

# 하위 호환성을 위한 전역 인스턴스 생성
ffmpeg_utils = FFmpegUtils()

# 아래의 모든 함수들은 점진적으로 제거될 예정입니다.
# 새로운 코드에서는 FFmpegUtils 클래스의 인스턴스를 직접 사용하세요.