# otio_utils.py
import json
import os
import subprocess
import re
import glob
from typing import List, Tuple, Dict
import logging
import ffmpeg
import tempfile
import time
import shutil

# 로깅 설정
logger = logging.getLogger(__name__)

# ffmpeg 경로 설정을 위한 전역 변수
FFPROBE_PATH = None

def set_ffmpeg_path(path: str):
    """ffmpeg 경로 설정"""
    global FFPROBE_PATH
    if os.path.exists(path):
        FFPROBE_PATH = os.path.join(os.path.dirname(path), 'ffprobe.exe')
        logger.debug(f"FFprobe 경로 설정: {FFPROBE_PATH}")
    else:
        logger.error(f"FFmpeg 경로를 찾을 수 없음: {path}")

class OTIOGenerator:
    def __init__(self):
        self.frame_rate = 30.0  # 프레임레이트를 30으로 설정
        
    def create_otio(self, clips: List[Tuple[str, int, int]]) -> Dict:
        """
        OTIO 파일 생성
        Args:
            clips: List of (file_path, trim_start, trim_end) tuples
        """
        timeline = {
            "OTIO_SCHEMA": "Timeline.1",
            "metadata": {},
            "name": "",
            "global_start_time": self._create_rational_time(0.0),
            "tracks": self._create_tracks(clips)
        }
        return timeline
    
    def _create_rational_time(self, value: float) -> Dict:
        return {
            "OTIO_SCHEMA": "RationalTime.1",
            "rate": self.frame_rate,
            "value": value
        }
    
    def _create_time_range(self, start_time: float, duration: float) -> Dict:
        return {
            "OTIO_SCHEMA": "TimeRange.1",
            "duration": self._create_rational_time(duration),
            "start_time": self._create_rational_time(start_time)
        }
    
    def _create_tracks(self, clips: List[Tuple[str, int, int]]) -> Dict:
        children = []
        for file_path, trim_start, trim_end in clips:
            clip = self._create_clip(file_path, trim_start, trim_end)
            if clip:
                children.append(clip)
                
        return {
            "OTIO_SCHEMA": "Stack.1",
            "metadata": {},
            "name": "tracks",
            "source_range": None,
            "effects": [],
            "markers": [],
            "enabled": True,
            "children": [{
                "OTIO_SCHEMA": "Track.1",
                "metadata": {},
                "name": "Main Sequence",
                "source_range": None,
                "effects": [],
                "markers": [],
                "enabled": True,
                "children": children,
                "kind": "Video"
            }]
        }
    
    def _create_clip(self, file_path: str, trim_start: int, trim_end: int) -> Dict:
        name = os.path.basename(file_path)
        
        # 이미지 시퀀스인지 확인
        is_sequence = '%' in file_path
        
        if is_sequence:  # 이미지 시퀀스
            pattern = file_path.replace('\\', '/')
            glob_pattern = re.sub(r'%\d*d', '*', pattern)
            image_files = sorted(glob.glob(glob_pattern))
            
            if not image_files:
                logger.warning(f"이미지 시퀀스 '{file_path}'를 찾을 수 없습니다.")
                return None
            
            # 시작과 끝 프레임 번호 추출
            frame_number_pattern = re.compile(r'(\d+)\.(\w+)$')
            first_image = os.path.basename(image_files[0])
            last_image = os.path.basename(image_files[-1])
            
            first_match = frame_number_pattern.search(first_image)
            last_match = frame_number_pattern.search(last_image)
            
            if not (first_match and last_match):
                logger.warning(f"프레임 번호를 추출할 수 없습니다: {first_image}, {last_image}")
                return None
            
            start_frame = int(first_match.group(1))
            end_frame = int(last_match.group(1))
            
            # trim 적용
            actual_start = start_frame + trim_start
            actual_end = end_frame - trim_end
            
            # %04d 패턴을 제거하고 파일명 생성
            base_name = re.sub(r'\.%\d*d', '', os.path.splitext(name)[0])
            if base_name.endswith('.'):
                base_name = base_name[:-1]
            
            media_reference = {
                "OTIO_SCHEMA": "ImageSequenceReference.1",
                "metadata": {},
                "name": "",
                "available_range": None,
                "available_image_bounds": {
                    "OTIO_SCHEMA": "Box2d.1",
                    "min": {
                        "OTIO_SCHEMA": "V2d.1",
                        "x": -0.8888888888888888,
                        "y": -0.5
                    },
                    "max": {
                        "OTIO_SCHEMA": "V2d.1",
                        "x": 0.8888888888888888,
                        "y": 0.5
                    }
                },
                "target_url_base": os.path.dirname(file_path),
                "name_prefix": f"{base_name}.",
                "name_suffix": ".png",
                "start_frame": actual_start,
                "frame_step": 1,
                "rate": 30.0,
                "frame_zero_padding": 4,
                "missing_frame_policy": "error"
            }
            
        else:  # 비디오 파일
            try:
                if not FFPROBE_PATH:
                    raise ValueError("FFprobe 경로가 설정되지 않았습니다.")
                    
                probe = ffmpeg.probe(file_path, cmd=FFPROBE_PATH)
                video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
                total_frames = int(video_info.get('nb_frames', 0))
                
                if total_frames == 0:  # nb_frames가 없는 경우
                    duration = float(video_info.get('duration', 0))
                    fps = eval(video_info.get('r_frame_rate', '30/1'))
                    total_frames = int(duration * fps)
                
                actual_start = trim_start
                actual_end = total_frames - trim_end
                
                base_name = os.path.splitext(name)[0]
                
                media_reference = {
                    "OTIO_SCHEMA": "ExternalReference.1",
                    "metadata": {},
                    "name": "",
                    "available_range": None,
                    "available_image_bounds": {
                        "OTIO_SCHEMA": "Box2d.1",
                        "min": {
                            "OTIO_SCHEMA": "V2d.1",
                            "x": -0.8888888888888888,
                            "y": -0.5
                        },
                        "max": {
                            "OTIO_SCHEMA": "V2d.1",
                            "x": 0.8888888888888888,
                            "y": 0.5
                        }
                    },
                    "target_url": file_path,
                    "rate": 30.0
                }
                
            except Exception as e:
                logger.error(f"비디오 정보 추출 실패: {e}")
                return None
        
        # 프레임 범위를 포함한 이름 생성
        frame_range = f"{actual_start}-{actual_end}#"
        display_name = f"{base_name}.{frame_range}"
        
        return {
            "OTIO_SCHEMA": "Clip.2",
            "metadata": {},
            "name": display_name,
            "source_range": self._create_time_range(float(actual_start), float(actual_end - actual_start + 1)),
            "effects": [],
            "markers": [],
            "enabled": True,
            "media_references": {
                "DEFAULT_MEDIA": media_reference
            },
            "active_media_reference_key": "DEFAULT_MEDIA"
        }

def generate_and_open_otio(clips: List[Tuple[str, int, int]], output_path: str, rv_path: str = None):
    """
    OTIO 파일을 생성하고 OpenRV로 엽니다
    """
    try:
        # ffmpeg_utils의 ffmpeg 경로를 공유
        from app.utils.ffmpeg_utils import FFMPEG_PATH
        if FFMPEG_PATH:
            set_ffmpeg_path(FFMPEG_PATH)
        
        generator = OTIOGenerator()
        timeline = generator.create_otio(clips)
        
        # 임시 디렉토리에 OTIO 파일 생성
        temp_dir = tempfile.gettempdir()
        temp_otio = os.path.join(temp_dir, f"temp_{int(time.time())}.otio")
        
        # 임시 파일에 OTIO 내용 저장
        with open(temp_otio, 'w') as f:
            json.dump(timeline, f, indent=4)
        
        # RV로 임시 파일 열기
        if rv_path and os.path.exists(rv_path):
            rv_process = subprocess.Popen([rv_path, temp_otio])
            
            def cleanup_temp_file():
                """RV 프로세스가 종료되면 임시 파일 삭제"""
                rv_process.wait()  # RV 프로세스가 종료될 때까지 대기
                try:
                    os.remove(temp_otio)
                    logger.debug(f"임시 OTIO 파일 삭제 완료: {temp_otio}")
                except Exception as e:
                    logger.debug(f"임시 OTIO 파일 삭제 실패: {e}")
            
            # 별도 스레드에서 cleanup 실행
            import threading
            cleanup_thread = threading.Thread(target=cleanup_temp_file)
            cleanup_thread.daemon = True  # 메인 프로그램 종료시 같이 종료되도록 설정
            cleanup_thread.start()
        
        # 사용자가 지정한 경로에 OTIO 파일 복사
        if output_path:
            shutil.copy2(temp_otio, output_path)
            logger.debug(f"OTIO 파일이 {output_path}에 저장되었습니다.")
            
    except Exception as e:
        logger.error(f"OTIO 파일 생성 중 오류 발생: {e}")
        raise

def parse_otio_file(otio_path: str) -> List[Tuple[str, int, int]]:
    """
    OTIO 파일을 파싱하여 (파일경로, trim_start, trim_end) 튜플 리스트를 반환합니다.
    """
    try:
        logger.debug(f"OTIO 파일 읽기 시작: {otio_path}")
        with open(otio_path, 'r') as f:
            otio_data = json.load(f)
        
        clips = []
        tracks = otio_data.get("tracks", {}).get("children", [])
        logger.debug(f"트랙 수: {len(tracks)}")
        
        for track in tracks:
            for clip in track.get("children", []):
                if clip.get("OTIO_SCHEMA") == "Clip.2":
                    logger.debug(f"클립 데이터: {clip}")
                    media_ref = clip["media_references"]["DEFAULT_MEDIA"]
                    logger.debug(f"미디어 레퍼런스: {media_ref}")
                    
                    # 미디어 타입에 따라 파일 경로 추출
                    if media_ref["OTIO_SCHEMA"] == "ImageSequenceReference.1":
                        # 이미지 시퀀스의 경우
                        base_path = media_ref["target_url_base"]
                        name_prefix = media_ref["name_prefix"]
                        frame_zero_padding = media_ref.get("frame_zero_padding", 4)
                        file_path = os.path.join(
                            base_path, 
                            f"{name_prefix}%0{frame_zero_padding}d.{media_ref['name_suffix'].lstrip('.')}"
                        )
                        
                        # 이미지 시퀀스의 실제 시작/끝 프레임 추출
                        clip_name = clip.get("name", "")
                        frame_range_match = re.search(r'(\d+)-(\d+)#', clip_name)
                        if frame_range_match:
                            start_frame = int(frame_range_match.group(1))
                            end_frame = int(frame_range_match.group(2))
                            # 시퀀스의 실제 프레임 범위를 사용하므로 trim은 0으로 설정
                            trim_start = 0
                            trim_end = 0
                        else:
                            trim_start = 0
                            trim_end = 0
                    else:
                        # 비디오 파일의 경우
                        file_path = media_ref["target_url"].replace('\\', '/')
                        # source_range에서 trim 정보 추출
                        source_range = clip.get("source_range", {})
                        start_time = source_range.get("start_time", {}).get("value", 0)
                        trim_start = int(start_time)
                        trim_end = 0
                    
                    logger.debug(f"추출된 파일 경로: {file_path}")
                    logger.debug(f"추출된 트림 정보: 시작={trim_start}, 끝={trim_end}")
                    clips.append((file_path, trim_start, trim_end))
        
        logger.debug(f"최종 추출된 클립 목록: {clips}")
        return clips
        
    except Exception as e:
        logger.error(f"OTIO 파일 파싱 중 오류 발생: {str(e)}", exc_info=True)
        raise