import ffmpeg
import logging
from typing import Dict, Optional, List, Any

logger = logging.getLogger(__name__)

class FFmpegCommandBuilder:
    def __init__(self, input_path: str, **input_kwargs):
        self.input_path = input_path
        self.input_kwargs = input_kwargs
        self.stream = ffmpeg.input(input_path, **input_kwargs)
        self.filters = []

    def add_filter(self, filter_name: str, *args, **kwargs):
        """필터 추가"""
        self.stream = self.stream.filter(filter_name, *args, **kwargs)
        self.filters.append((filter_name, args, kwargs))
        return self

    def add_scale(self, width: int, height: int, force_original_aspect_ratio: str = 'decrease'):
        """스케일 필터 추가"""
        return self.add_filter('scale', width, height, force_original_aspect_ratio=force_original_aspect_ratio)

    def add_pad(self, width: int, height: int, x: str, y: str, color: str = 'black'):
        """패드 필터 추가"""
        return self.add_filter('pad', width, height, x=x, y=y, color=color)

    def add_drawbox(self, x: int, y: int, width: int, height: str, color: str, t: str = 'fill'):
        """Drawbox 필터 추가"""
        return self.add_filter('drawbox', x=x, y=y, width=width, height=height, color=color, t=t)

    def add_drawtext(self, text: str, **kwargs):
        """Drawtext 필터 추가"""
        # 필수 인자 체크 및 기본값 설정
        if 'fontcolor' not in kwargs:
            kwargs['fontcolor'] = 'white'
        kwargs['text'] = text
        return self.add_filter('drawtext', **kwargs)

    def add_overlay_layout(self, target_properties: Dict[str, Any], shot_label: Optional[str] = None, 
                          output_label: Optional[str] = None, font_path: Optional[str] = None,
                          debug_mode: bool = False):
        """복잡한 오버레이 레이아웃 로직을 캡슐화"""
        
        # 이 메소드는 기존 apply_filters의 로직을 대체하기 위해 설계됨
        # 하지만 기존 로직이 매우 복잡하고 상태 의존적이므로, 
        # 여기서는 기본 구조만 잡고 실제 구현은 ffmpeg_utils에서 이 클래스를 활용하는 방식으로 진행
        pass

    def build(self, output_path: str, **output_kwargs):
        """출력 스트림 생성"""
        stream = ffmpeg.output(self.stream, output_path, **output_kwargs)
        return stream.overwrite_output()

    def get_stream(self):
        return self.stream
