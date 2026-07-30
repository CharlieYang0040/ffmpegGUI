import os
import logging
import shutil
import time
import gc
import tempfile
try:
    import psutil
except ModuleNotFoundError:
    class _VirtualMemoryFallback:
        total = 8 * 1024 * 1024 * 1024

    class _PsutilFallback:
        @staticmethod
        def cpu_count(logical=True):
            return os.cpu_count() or 1

        @staticmethod
        def virtual_memory():
            return _VirtualMemoryFallback()

    psutil = _PsutilFallback()
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Tuple, Optional, Callable
import concurrent.futures
import glob
import re

# 다른 모듈에서 필요한 함수 가져오기
from app.core.ffmpeg_core import get_media_properties, get_target_properties, create_temp_file_list, get_optimal_encoding_options, get_optimal_thread_count
from app.utils.utils import is_webp_file

# 로깅 서비스 가져오기
from app.services.logging_service import LoggingService

# FFmpegManager 싱글톤 가져오기
from app.core.ffmpeg_manager import FFmpegManager

# 프로세서 팩토리 가져오기
from app.core.processor_factory import ProcessorFactory

# 미디어 병합기 가져오기
from app.core.media_merger import MediaMerger

# 로깅 설정
logger = LoggingService().get_logger(__name__)

class BatchProcessor:
    """미디어 파일 일괄 처리를 위한 클래스"""

    def __init__(self, ffmpeg_manager=None):
        """
        배치 프로세서 초기화

        Args:
            ffmpeg_manager: FFmpegManager 인스턴스 (없으면 싱글톤 인스턴스 사용)
        """
        self.ffmpeg_manager = ffmpeg_manager or FFmpegManager()
        self.logger = LoggingService().get_logger(__name__)
        self.processor_factory = ProcessorFactory(self.ffmpeg_manager)
        self.media_merger = MediaMerger(self.ffmpeg_manager)

    def process_encoding_job(
        self,
        job,
        progress_callback: Optional[Callable[[int], None]] = None,
        task_callback: Optional[Callable[[str], None]] = None,
        cancel_token=None,
    ) -> str:
        """Process an EncodingJob through the existing batch pipeline."""
        from app.core.job_builder import (
            media_items_to_legacy_tuples,
            validate_encoding_job,
        )

        validate_encoding_job(job)
        if cancel_token:
            cancel_token.throw_if_cancelled()
        encoding_options = dict(job.options.ffmpeg_options)
        canonical_clips = [
            (item.source_path, item.source_range, int(item.frame_count))
            for item in job.media_items
            if item.source_range is not None and item.frame_count
        ]
        uses_canonical_ranges = len(canonical_clips) == len(job.media_items)
        return self.process_all_media(
            media_files=(
                []
                if uses_canonical_ranges
                else media_items_to_legacy_tuples(job.media_items)
            ),
            clip_ranges=canonical_clips if uses_canonical_ranges else None,
            output_file=job.output_file,
            encoding_options=encoding_options,
            debug_mode=job.options.debug_mode,
            progress_callback=progress_callback,
            task_callback=task_callback,
            use_frame_based_trim=job.options.use_frame_based_trim,
            cancel_token=cancel_token,
        )

    def process_all_media(
        self,
        media_files: List[Tuple[str, int, int]],
        output_file: str,
        encoding_options: Dict[str, str],
        debug_mode: bool = False,
        progress_callback: Optional[Callable[[int], None]] = None,
        task_callback: Optional[Callable[[str], None]] = None,
        target_properties: Optional[Dict[str, str]] = None,
        use_custom_framerate: bool = False,
        custom_framerate: float = 30.0,
        use_custom_resolution: bool = False,
        custom_width: int = 0,
        custom_height: int = 0,
        use_frame_based_trim: bool = False,
        cancel_token=None,
        clip_ranges=None,
    ) -> str:
        """
        여러 미디어 파일을 처리하고 하나의 출력 파일로 병합합니다.

        Args:
            media_files: 레거시 입력 목록 (파일 경로, 앞/뒤 제거 프레임)
            clip_ranges: 현대 입력 목록 (파일 경로, ClipRange, 전체 프레임 수)
            output_file: 출력 파일 경로
            encoding_options: 인코딩 옵션
            debug_mode: 디버그 모드 여부
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
        if clip_ranges is not None:
            media_files = [
                (
                    file_path,
                    source_range.source_in,
                    source_frame_count - source_range.source_out,
                )
                for file_path, source_range, source_frame_count in clip_ranges
            ]
        target_properties = target_properties or {}
        self._last_progress = 0
        if cancel_token:
            cancel_token.throw_if_cancelled()

        # 로그 추가: 프레임 기반 트림 사용 여부 및 미디어 파일 정보
        self.logger.info(f"프레임 기반 트림 사용 여부: {use_frame_based_trim}")
        for idx, (file_path, trim_start, trim_end) in enumerate(media_files):
            self.logger.info(f"미디어 파일 #{idx+1}: 경로={file_path}, 트림 시작={trim_start}, 트림 끝={trim_end}")

        temp_files = []
        temp_dirs = []

        try:
            # FFmpeg 경로 확인
            if not self.ffmpeg_manager.get_ffmpeg_path():
                raise ValueError("FFmpeg 경로가 설정되지 않았습니다.")

            if not media_files:
                raise ValueError("처리할 미디어 파일이 없습니다.")

            self.logger.info(f"{len(media_files)}개 미디어 파일 처리 시작")

            if task_callback:
                task_callback(f"미디어 처리 시작... ({len(media_files)}개 파일)")

            # 커스텀 프레임레이트 설정
            if use_custom_framerate and custom_framerate > 0:
                encoding_options['r'] = str(custom_framerate)
                self.logger.info(f"커스텀 프레임레이트 설정: {custom_framerate}fps")

            # 커스텀 해상도 설정
            if use_custom_resolution and custom_width > 0 and custom_height > 0:
                encoding_options['s'] = f"{custom_width}x{custom_height}"
                target_properties = {
                    'width': custom_width,
                    'height': custom_height
                }
                self.logger.info(f"커스텀 해상도 설정: {custom_width}x{custom_height}")

            # 타겟 속성이 없으면 첫 번째 파일에서 가져오기
            if not target_properties:
                input_files = [file_path for file_path, _, _ in media_files]
                target_properties = get_target_properties(input_files, encoding_options, debug_mode)
                if not target_properties:
                    raise ValueError("미디어 속성을 가져올 수 없습니다.")

            # 메모리 임계값 설정 (시스템 메모리의 80%)
            memory_threshold = int(psutil.virtual_memory().total * 0.8)

            # WebP 파일 처리 (이미지 시퀀스로 변환)
            webp_files = [f for f, _, _ in media_files if f.lower().endswith('.webp')]
            webp_count = len(webp_files)
            webp_processed = 0

            if webp_count > 0:
                self.logger.info(f"{webp_count}개의 WebP 파일 처리 시작")

                # 최적의 스레드 수 계산 (CPU 코어 수 기반, 최대 webp_count)
                max_workers = min(get_optimal_thread_count(), webp_count)
                self.logger.info(f"WebP 병렬 처리를 위한 스레드 풀 생성: {max_workers}개 스레드")

                # 처리할 WebP 파일 정보 수집
                webp_tasks = []
                for i, (file_path, trim_start, trim_end) in enumerate(media_files):
                    if file_path.lower().endswith('.webp'):
                        webp_tasks.append((i, file_path, trim_start, trim_end))

                # 결과를 저장할 딕셔너리
                webp_results = {}

                # 진행 상황 추적을 위한 락
                import threading
                progress_lock = threading.Lock()

                # WebP 파일 처리 함수
                def process_webp_file(task_idx, file_path, trim_start, trim_end):
                    try:
                        if task_callback:
                            task_callback(f"WebP 파일 처리 중... ({webp_processed+1}/{webp_count})")

                        # 진행률 업데이트 함수
                        def webp_progress_callback(progress):
                            if progress_callback:
                                with progress_lock:
                                    self.update_webp_progress(
                                        progress, task_idx, len(media_files),
                                        webp_count, webp_processed, progress_callback
                                    )

                        # 임시 디렉토리 생성
                        temp_dir = tempfile.mkdtemp()
                        temp_dirs.append(temp_dir)

                        # WebP 파일을 이미지 시퀀스로 추출
                        webp_processor = self.processor_factory.create_processor('webp')
                        image_sequence = webp_processor.extract_webp_to_image_sequence(
                            file_path, temp_dir, webp_progress_callback
                        )

                        # WebP 메타데이터 가져오기 (해상도 정보 포함)
                        webp_metadata = webp_processor.get_webp_metadata(file_path)

                        self.logger.info(f"WebP 파일 처리 완료: {file_path} -> {image_sequence}")

                        # 추출된 프레임 정보 확인
                        extracted_dir = os.path.dirname(image_sequence)
                        extracted_files = sorted(glob.glob(os.path.join(extracted_dir, 'frame_*.png')))

                        # 프레임 번호 범위 확인
                        frame_numbers = []
                        for file_path in extracted_files:
                            file_name = os.path.basename(file_path)
                            number_match = re.search(r'(\d+)', file_name)
                            if number_match:
                                frame_number = int(number_match.group(1))
                                frame_numbers.append(frame_number)

                        if frame_numbers:
                            min_frame = min(frame_numbers)
                            max_frame = max(frame_numbers)
                            self.logger.info(f"추출된 프레임 번호 범위: {min_frame}~{max_frame}, 총 {len(frame_numbers)}개 프레임")

                        # 결과 반환
                        return {
                            'task_idx': task_idx,
                            'image_sequence': image_sequence,
                            'metadata': webp_metadata,
                            'temp_dir': temp_dir,
                            'frame_count': len(extracted_files),
                            'frame_range': (min(frame_numbers) if frame_numbers else 0,
                                           max(frame_numbers) if frame_numbers else 0)
                        }
                    except Exception as e:
                        self.logger.exception(f"WebP 파일 처리 중 오류 발생: {str(e)}")
                        return {
                            'task_idx': task_idx,
                            'error': str(e)
                        }

                # 스레드 풀로 WebP 파일 병렬 처리
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # 작업 제출
                    future_to_task = {
                        executor.submit(process_webp_file, task_idx, file_path, trim_start, trim_end): (task_idx, trim_start, trim_end)
                        for task_idx, file_path, trim_start, trim_end in webp_tasks
                    }

                    # 작업 완료 대기 및 결과 수집
                    for future in concurrent.futures.as_completed(future_to_task):
                        task_idx, orig_trim_start, orig_trim_end = future_to_task[future]
                        try:
                            result = future.result()
                            if 'error' not in result:
                                webp_results[task_idx] = result

                                # WebP 파일에서 해상도 정보 추출
                                if 'metadata' in result and 'width' in result['metadata'] and 'height' in result['metadata']:
                                    width = result['metadata']['width']
                                    height = result['metadata']['height']
                                    self.logger.info(f"WebP 파일에서 해상도 정보 추출: {width}x{height}")

                                    # 해상도 정보가 없으면 WebP에서 추출한 정보 사용
                                    if not target_properties or 'width' not in target_properties or 'height' not in target_properties:
                                        target_properties = {
                                            'width': width,
                                            'height': height
                                        }

                                # WebP에서 추출한 FPS 정보가 있으면 인코딩 옵션에 추가
                                if 'metadata' in result and 'fps' in result['metadata'] and result['metadata']['fps'] > 0:
                                    encoding_options['r'] = str(result['metadata']['fps'])
                                    self.logger.info(f"WebP에서 추출한 프레임레이트를 인코딩 옵션에 적용: {result['metadata']['fps']}fps")

                                # WebP 처리 결과에서 인코딩 옵션이 있으면 업데이트
                                if 'encoding_options' in result:
                                    # 기존 인코딩 옵션 유지하면서 WebP 처리 결과의 옵션으로 업데이트
                                    for key, value in result['encoding_options'].items():
                                        encoding_options[key] = value
                                    self.logger.info(f"WebP 처리 결과의 인코딩 옵션으로 업데이트: {result['encoding_options']}")

                                # 이미지 시퀀스 경로 저장 (원본 트림 값은 그대로 유지)
                                media_files[task_idx] = (result['image_sequence'], orig_trim_start, orig_trim_end)
                                self.logger.info(f"WebP 이미지 시퀀스 경로 적용: {result['image_sequence']}, 트림 시작={orig_trim_start}, 트림 끝={orig_trim_end}")

                                with progress_lock:
                                    webp_processed += 1
                                    # WebP 처리 완료 후 진행률 업데이트
                                    if progress_callback:
                                        self._emit_progress((webp_processed / webp_count) * 10, progress_callback)
                            else:
                                self.logger.error(f"WebP 파일 처리 실패: {result['error']}")
                        except Exception as e:
                            self.logger.exception(f"WebP 작업 결과 처리 중 오류 발생: {str(e)}")

                self.logger.info(f"모든 WebP 파일 처리 완료: {webp_processed}/{webp_count}")

            # 각 미디어 파일 처리
            for i, (file_path, trim_start, trim_end) in enumerate(media_files):
                if (
                    isinstance(trim_start, bool)
                    or isinstance(trim_end, bool)
                    or not isinstance(trim_start, int)
                    or not isinstance(trim_end, int)
                ):
                    raise TypeError("클립 경계는 정수 프레임이어야 합니다.")
                trim_start = max(0, trim_start)
                trim_end = max(0, trim_end)

                # 프레임 기반 트림 사용 시 로그 출력 및 값 검증
                if use_frame_based_trim:
                    # 비디오 속성 가져오기
                    try:
                        video_properties = get_media_properties(file_path, debug_mode)
                        fps = float(video_properties.get('r', 30))

                        # nb_frames를 직접 사용하여 총 프레임 수 계산
                        if 'nb_frames' in video_properties and video_properties['nb_frames'] > 0:
                            total_frames = int(video_properties['nb_frames'])
                        else:
                            # nb_frames가 없는 경우에만 duration * fps 사용
                            duration = float(video_properties.get('duration', 0))
                            total_frames = int(duration * fps)
                            self.logger.warning(f"nb_frames 정보가 없어 duration * fps로 계산: {duration} * {fps} = {total_frames}")

                        # 트림 값이 프레임 번호로 지정된 경우 검증
                        if trim_start < 0:
                            trim_start = 0

                        self.logger.info(f"파일 {i+1} 프레임 기반 트림 적용: 제외할 앞 프레임={trim_start}, 제외할 뒤 프레임={trim_end}, 총 프레임={total_frames}")
                    except Exception as e:
                        self.logger.warning(f"비디오 속성 가져오기 실패: {e}")
                        self.logger.info(f"파일 {i+1} 프레임 기반 트림 적용: 시작={trim_start}, 끝={trim_end}")

                if task_callback:
                    task_callback(f"파일 처리 중... ({i+1}/{len(media_files)})")

                # 진행률 업데이트 함수
                def file_progress_callback(progress):
                    if progress_callback:
                        # WebP 처리 가중치 (10%)
                        webp_weight = 0.1 if webp_count > 0 else 0
                        # 파일 처리 가중치 (70%)
                        processing_weight = 0.7
                        # 병합 가중치 (20%)
                        merging_weight = 1.0 - webp_weight - processing_weight

                        # 기본 진행률 (WebP 처리 완료 후)
                        base_progress = webp_weight * 100 if webp_count > 0 else 0

                        self.update_file_progress(
                            progress, i, len(media_files),
                            base_progress, processing_weight, progress_callback
                        )

                # 파일 유형에 따라 적절한 프로세서 선택
                if '%' in file_path or os.path.isdir(file_path):
                    # 이미지 시퀀스 처리
                    self.logger.info(f"이미지 시퀀스 처리: {file_path}")
                    image_processor = self.processor_factory.create_processor('image')
                    temp_file = image_processor.process_image_sequence(
                        file_path, trim_start, trim_end, encoding_options,
                        target_properties, debug_mode, i, file_progress_callback,
                        use_frame_based_trim, cancel_token=cancel_token
                    )
                else:
                    # 비디오 파일 처리
                    self.logger.info(f"비디오 파일 처리: {file_path}")
                    video_processor = self.processor_factory.create_processor('video')
                    temp_file = video_processor.process_video_file(
                        file_path, trim_start, trim_end, encoding_options,
                        target_properties, debug_mode, i, file_progress_callback,
                        use_frame_based_trim, cancel_token=cancel_token
                    )

                temp_files.append(temp_file)
                self.logger.info(f"파일 처리 완료: {file_path} -> {temp_file}")

            # 모든 파일 처리 완료 후 병합
            if len(temp_files) > 1:
                if task_callback:
                    task_callback(f"파일 병합 중... ({len(temp_files)}개 파일)")

                # 진행률 업데이트 함수
                def merge_progress_callback(progress):
                    if progress_callback:
                        # WebP 처리 가중치 (10%)
                        webp_weight = 0.1 if webp_count > 0 else 0
                        # 파일 처리 가중치 (70%)
                        processing_weight = 0.7
                        # 병합 가중치 (20%)
                        merging_weight = 1.0 - webp_weight - processing_weight

                        # 기본 진행률 (WebP 처리 + 파일 처리 완료 후)
                        base_progress = (webp_weight + processing_weight) * 100

                        self.update_merge_progress(
                            progress, base_progress, merging_weight, progress_callback
                        )

                # 파일 병합
                self.logger.info(f"파일 병합 시작: {len(temp_files)}개 파일")
                self.media_merger.concat_media_files(
                    temp_files, output_file, encoding_options,
                    target_properties, debug_mode, merge_progress_callback, task_callback,
                    cancel_token=cancel_token
                )

                self.logger.info(f"파일 병합 완료: {output_file}")
            elif len(temp_files) == 1:
                if task_callback:
                    task_callback("단일 파일 마무리 중...")
                self.media_merger.finalize_media_file(
                    temp_files[0],
                    output_file,
                    cancel_token=cancel_token,
                )
                self.logger.info(f"단일 파일 컨테이너 확정 완료: {temp_files[0]} -> {output_file}")

                if progress_callback:
                    self._emit_progress(100, progress_callback)
            else:
                raise ValueError("처리된 파일이 없습니다.")

            if task_callback:
                task_callback("처리 완료!")

            return output_file

        except Exception as e:
            self.logger.exception(f"미디어 처리 중 오류 발생: {str(e)}")
            # 출력 파일 정리
            if os.path.exists(output_file):
                try:
                    os.remove(output_file)
                    self.logger.info(f"실패한 출력 파일 제거됨: {output_file}")
                except Exception as cleanup_error:
                    self.logger.warning(f"출력 파일 제거 실패: {cleanup_error}")
            raise

        finally:
            # 임시 파일 정리
            for temp_file in temp_files:
                try:
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        self.logger.debug(f"임시 파일 제거됨: {temp_file}")
                except Exception as e:
                    self.logger.warning(f"임시 파일 제거 실패: {e}")

            # 임시 디렉토리 정리
            for temp_dir in temp_dirs:
                try:
                    if os.path.exists(temp_dir):
                        shutil.rmtree(temp_dir)
                        self.logger.debug(f"임시 디렉토리 제거됨: {temp_dir}")
                except Exception as e:
                    self.logger.warning(f"임시 디렉토리 제거 실패: {e}")

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
        # 트림 값 로깅 추가
        self.logger.info(f"단일 미디어 처리: 파일={input_file}, 트림 시작={trim_start}, 트림 끝={trim_end}, 프레임 기반 트림={use_frame_based_trim}")

        # 파일 유형에 따라 적절한 프로세서 선택
        if '%' in input_file or os.path.isdir(input_file):
            # 이미지 시퀀스 처리
            self.logger.info(f"이미지 시퀀스 처리: {input_file}")
            image_processor = self.processor_factory.create_processor('image')
            return image_processor.process_image_sequence(
                input_file, trim_start, trim_end, encoding_options,
                target_properties, debug_mode, idx, progress_callback,
                use_frame_based_trim
            )
        else:
            # 비디오 파일 처리
            self.logger.info(f"비디오 파일 처리: {input_file}")
            video_processor = self.processor_factory.create_processor('video')
            return video_processor.process_video_file(
                input_file, trim_start, trim_end, encoding_options,
                target_properties, debug_mode, idx, progress_callback,
                use_frame_based_trim
            )

    def _emit_progress(self, progress, callback=None):
        """Emit bounded, monotonic aggregate progress."""
        if not callback:
            return

        bounded = max(0, min(100, int(progress)))
        last_progress = getattr(self, "_last_progress", 0)
        if bounded < last_progress:
            bounded = last_progress
        else:
            self._last_progress = bounded
        callback(bounded)

    def update_webp_progress(self, progress, file_idx, total_files, webp_count, webp_processed, callback=None):
        """Map WebP preparation into the first 10% of total progress."""
        if not callback or webp_count <= 0:
            return

        completed = webp_processed + (max(0, min(100, progress)) / 100)
        total_progress = (completed / webp_count) * 10
        self.logger.debug(
            "WebP progress: progress=%s, file_idx=%s, completed=%s/%s, aggregate=%s",
            progress,
            file_idx,
            completed,
            webp_count,
            total_progress,
        )
        self._emit_progress(total_progress, callback)

    def update_file_progress(self, progress, file_idx, total_files, base_progress, processing_weight, callback=None):
        """Map per-file processing progress into the processing stage."""
        if not callback or total_files <= 0:
            return

        stage_width = processing_weight * 100
        completed_files = file_idx + (max(0, min(100, progress)) / 100)
        total_progress = base_progress + (completed_files / total_files) * stage_width
        self._emit_progress(total_progress, callback)

    def update_merge_progress(self, progress, base_progress, merging_weight, callback=None):
        """Map merge progress into the final stage."""
        if not callback:
            return

        stage_width = merging_weight * 100
        total_progress = base_progress + (max(0, min(100, progress)) / 100) * stage_width
        self._emit_progress(total_progress, callback)
