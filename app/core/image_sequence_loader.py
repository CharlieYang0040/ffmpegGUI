import os
import glob
import re
import time
import queue
from typing import List, Tuple

from PySide6.QtCore import QThread, Signal, QMutex, QWaitCondition, QMutexLocker
from PySide6.QtGui import QPixmap, QImage

from app.services.logging_service import LoggingService

logger = LoggingService().get_logger(__name__)

class ImageSequenceLoaderThread(QThread):
    """
    이미지 시퀀스 파일을 비동기적으로 로드하여 프레임 버퍼에 추가하는 워커 스레드.
    QPixmap을 직접 사용하여 네이티브 로딩을 수행합니다.
    """
    error = Signal(str)         # 오류 발생 시그널
    finished = Signal()         # 스레드 정상 종료 시그널
    loaded_count = Signal(int)    # 로드된 총 프레임 수 (정보 전달용)

    def __init__(self, file_pattern: str, frame_buffer: queue.Queue, start_frame: int = 1, target_fps: float = 30.0, buffer_size: int = 60, parent=None):
        """
        Args:
            file_pattern (str): 이미지 파일 패턴 (예: /path/to/seq.%04d.png)
            frame_buffer (queue.Queue): 로드된 QPixmap 객체를 저장할 스레드 안전 큐. (frame_index, QPixmap) 튜플 저장.
            start_frame (int): 시퀀스의 시작 프레임 번호 (1-based).
            target_fps (float): 목표 초당 프레임 수 (미리 로딩 및 슬립 조절에 사용될 수 있음).
            buffer_size (int): 프레임 버퍼의 최대 크기.
            parent: 부모 객체.
        """
        super().__init__(parent)
        self.file_pattern = file_pattern.replace("\\", "/") # 경로 정규화
        self.frame_buffer = frame_buffer
        self.start_frame = start_frame
        self.target_fps = max(target_fps, 1.0) # 최소 1 FPS 보장
        self.max_buffer_size = buffer_size
        self.image_files: List[str] = []

        self._running = False
        self._stop_requested = False
        self._seek_requested = False
        self._seek_frame_index = 0 # 0-based index

        # 동기화용 (탐색 요청 등)
        self.mutex = QMutex()
        self.condition = QWaitCondition() # 현재 사용 안 함 (seek 요청은 플래그로 처리)

        logger.debug(f"ImageSequenceLoaderThread 생성: pattern='{file_pattern}', fps={target_fps}, buffer={buffer_size}")

    def run(self):
        """스레드 메인 실행 로직"""
        self._running = True
        self._stop_requested = False
        current_list_index = 0 # 파일 목록(image_files)상의 인덱스
        processed_count = 0

        logger.info(f"이미지 시퀀스 로더 스레드 시작: {os.path.basename(self.file_pattern)}, 시작 프레임: {self.start_frame}")

        try:
            # 1. 파일 목록 검색 및 정렬
            pattern = re.sub(r'%(\d*)d', '*', self.file_pattern)
            base_dir = os.path.dirname(self.file_pattern)
            search_pattern = os.path.join(base_dir, os.path.basename(pattern))
            logger.debug(f"파일 검색 패턴: {search_pattern}")
            self.image_files = sorted(glob.glob(search_pattern))

            if not self.image_files:
                raise FileNotFoundError(f"이미지 시퀀스 파일을 찾을 수 없습니다: {search_pattern}")

            total_frames = len(self.image_files)
            logger.info(f"이미지 시퀀스 파일 {total_frames}개 발견.")
            self.loaded_count.emit(total_frames) # 총 프레임 수 전달

            # 실제 시작 프레임 번호에 해당하는 파일 목록 인덱스 찾기
            start_list_index = -1
            try:
                first_file_name = os.path.basename(self.image_files[0])
                match = re.search(r'(?:[._-])?(\d+)\.(?:\w+)$', first_file_name)
                if match:
                    detected_start_frame = int(match.group(1))
                    start_list_index = self.start_frame - detected_start_frame
                    if not (0 <= start_list_index < total_frames):
                        logger.error(f"계산된 시작 인덱스({start_list_index})가 파일 목록 범위를 벗어남.")
                        start_list_index = 0 # 실패 시 처음부터 로드 시도
                else:
                    logger.warning("파일 목록 첫 항목에서 프레임 번호 감지 실패, 0번 인덱스부터 로드 시작")
                    start_list_index = 0
            except Exception as e:
                logger.error(f"시작 인덱스 계산 중 오류: {e}", exc_info=True)
                start_list_index = 0
                
            current_list_index = start_list_index # 파일 목록상의 시작 인덱스 설정
            actual_frame_number = self.start_frame # 실제 프레임 번호 (1-based)

            # 2. 프레임 로딩 루프
            while current_list_index < total_frames and self._running:
                # 2.1. 중지 또는 인터럽트 요청 확인
                if self._stop_requested or self.isInterruptionRequested():
                    logger.debug("중지/인터럽트 요청 감지됨, 로딩 루프 종료.")
                    break

                # 2.2. 탐색 요청 확인
                with QMutexLocker(self.mutex):
                    if self._seek_requested:
                        target_index = self._seek_frame_index
                        self._seek_requested = False
                        if 0 <= target_index < total_frames:
                            logger.info(f"탐색 요청 처리: {current_list_index} -> {target_index}")
                            current_list_index = target_index
                            # 탐색 시 실제 프레임 번호도 업데이트 (target_index는 0-based 파일 목록 인덱스)
                            # 파일명에서 실제 프레임 번호를 다시 파싱하거나, start_frame 기준으로 계산
                            actual_frame_number = self.start_frame + (current_list_index - start_list_index)
                            logger.debug(f"탐색 후 실제 프레임 번호: {actual_frame_number}")
                        else:
                            logger.warning(f"잘못된 탐색 인덱스: {target_index}")

                # 2.3. 버퍼 상태 확인 및 대기 (버퍼가 가득 찼으면 잠시 대기)
                while self.frame_buffer.qsize() >= self.max_buffer_size and self._running and not self._stop_requested:
                    # logger.debug(f"버퍼 full ({self.frame_buffer.qsize()}), 잠시 대기...")
                    self.msleep(int(1000 / self.target_fps / 2)) # 목표 프레임 시간의 절반 정도 대기
                    # 대기 중 중지/탐색/인터럽트 요청 다시 확인
                    if self._stop_requested or self.isInterruptionRequested(): break
                    with QMutexLocker(self.mutex):
                        if self._seek_requested: break # 탐색 요청 시 대기 해제

                if self._stop_requested or self.isInterruptionRequested(): break # 버퍼 대기 중 중지/인터럽트된 경우
                with QMutexLocker(self.mutex): # 버퍼 대기 중 탐색된 경우
                    if self._seek_requested: continue # 루프 시작으로 돌아가 탐색 처리

                # 2.4. 이미지 로드 전 인터럽트 확인
                if self.isInterruptionRequested(): break

                # 2.4. 이미지 로드 (QPixmap 사용)
                if current_list_index < total_frames: # 범위 재확인
                    file_path = self.image_files[current_list_index]
                    # logger.debug(f"프레임 로드 시도: 인덱스 {current_list_index}, 파일: {os.path.basename(file_path)}")
                    
                    # QPixmap 로딩 (상대적으로 빠름)
                    pixmap = QPixmap(file_path) 

                    # 로드 실패 시 (더 견고하게 하려면 QImage 로드 후 변환)
                    if pixmap.isNull():
                         # QImage로 재시도
                         image = QImage(file_path)
                         if not image.isNull():
                             logger.warning(f"QPixmap 로드 실패, QImage로 재시도 성공: {os.path.basename(file_path)}")
                             pixmap = QPixmap.fromImage(image)
                         else:
                             logger.error(f"이미지 로드 실패 (QPixmap & QImage): {os.path.basename(file_path)}")
                             # 실패한 프레임은 건너뛰기? 또는 오류 시그널?
                             current_list_index += 1
                             actual_frame_number += 1 # 실패해도 실제 프레임 번호는 증가
                             continue # 다음 프레임으로

                    # 2.5. 프레임 버퍼에 추가 (인덱스, QPixmap)
                    try:
                        # put은 블로킹될 수 있으므로 qsize로 미리 확인했으나, 만약을 위해 timeout 사용 가능
                        # 버퍼에 (실제_프레임_번호 - 1, pixmap) 저장
                        self.frame_buffer.put((actual_frame_number - 1, pixmap), block=False) # non-blocking
                        processed_count += 1
                        # logger.debug(f"프레임 {actual_frame_number - 1} 버퍼에 추가됨 (qsize: {self.frame_buffer.qsize()}) ")
                    except queue.Full:
                        # 이론상 qsize 체크로 인해 발생하면 안 되지만, 동시성 문제 시 발생 가능
                        logger.warning("프레임 버퍼가 가득 찼습니다 (put 실패). 잠시 후 재시도합니다.")
                        self.msleep(50) # 잠시 대기
                        continue # 현재 인덱스 재처리 시도

                    # 2.6. 다음 프레임 인덱스로 이동
                    current_list_index += 1
                    actual_frame_number += 1 # 실제 프레임 번호도 증가
                
                # Optional: Give other threads a chance (if needed)
                # self.msleep(1) 

        except FileNotFoundError as e:
            logger.error(f"파일 검색 오류: {e}")
            self.error.emit(str(e))
        except Exception as e:
            logger.exception(f"이미지 시퀀스 로더 스레드 오류: {e}")
            self.error.emit(f"이미지 로딩 중 오류 발생: {e}")
        finally:
            self._running = False
            logger.info(f"이미지 시퀀스 로더 스레드 종료됨. 총 처리 프레임: {processed_count}")
            self.finished.emit() # 종료 시그널

    def stop(self):
        """스레드 실행 중지 요청"""
        logger.debug("Loader Thread 중지 요청 수신")
        # 인터럽트 요청 추가
        self.requestInterruption()
        self._stop_requested = True
        # 현재 wait 상태일 수 있으므로 깨워야 할 수도 있음 (현재는 wait 사용 안 함)
        # self.condition.wakeAll() 

    def seek(self, frame_number: int):
        """
        특정 프레임 번호로 로딩 위치 이동 요청 (1-based).
        실제 이동은 run() 루프 내에서 처리됩니다.
        """
        if not self.image_files:
             logger.warning("Seek 요청: 아직 파일 목록이 없습니다.")
             return
             
        target_index = frame_number - 1 # 0-based로 변환
        total_frames = len(self.image_files)

        if 0 <= target_index < total_frames:
            with QMutexLocker(self.mutex):
                logger.debug(f"Loader Thread 탐색 요청 수신: 프레임 {frame_number} (인덱스 {target_index})")
                self._seek_requested = True
                self._seek_frame_index = target_index
                # self.condition.wakeAll() # 혹시 wait 상태일 경우 대비 (현재는 불필요)
        else:
            logger.warning(f"Seek 요청: 유효하지 않은 프레임 번호 {frame_number} (인덱스 {target_index}), 총 {total_frames} 프레임")

    def is_running(self) -> bool:
        return self._running

    # 제거: def _clear_buffer(self): ... 