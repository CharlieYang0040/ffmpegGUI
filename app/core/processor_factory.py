# app/core/processor_factory.py
class ProcessorFactory:
    def __init__(self, ffmpeg_manager):
        self.ffmpeg_manager = ffmpeg_manager
    
    def create_processor(self, media_type):
        if media_type == 'video':
            from app.core.video_processor import VideoProcessor
            return VideoProcessor(self.ffmpeg_manager)
        elif media_type == 'image':
            from app.core.image_processor import ImageProcessor
            return ImageProcessor(self.ffmpeg_manager)
        elif media_type == 'webp':
            from app.core.webp_processor import WebPProcessor
            return WebPProcessor(self.ffmpeg_manager)
        else:
            raise ValueError(f"지원하지 않는 미디어 타입: {media_type}")