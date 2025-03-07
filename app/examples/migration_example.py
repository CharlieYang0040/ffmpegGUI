"""
이 파일은 하위 호환성 함수를 제거하고 새로운 구조로 마이그레이션하는 방법을 보여주는 예제입니다.
"""

# 기존 코드 (하위 호환성 함수 사용)
def old_code_example():
    """하위 호환성 함수를 사용하는 기존 코드 예제"""
    from app.utils.ffmpeg_utils import (
        initialize_ffmpeg, get_media_properties, process_video_file,
        concat_media_files, FFMPEG_PATH
    )
    import logging
    
    # 로깅 직접 설정
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    
    # FFmpeg 초기화
    ffmpeg_path = "C:/ffmpeg/bin/ffmpeg.exe"
    initialize_ffmpeg(ffmpeg_path)
    
    # 미디어 속성 가져오기
    input_file = "input.mp4"
    properties = get_media_properties(input_file, debug_mode=True)
    
    # 비디오 처리
    encoding_options = {
        "codec": "h264",
        "preset": "medium",
        "crf": "23"
    }
    target_properties = {
        "width": 1920,
        "height": 1080,
        "fps": 30
    }
    output_file = process_video_file(
        input_file=input_file,
        trim_start=10,
        trim_end=20,
        encoding_options=encoding_options,
        target_properties=target_properties,
        debug_mode=True,
        idx=0,
        progress_callback=lambda p: print(f"Progress: {p}%")
    )
    
    # 파일 병합
    concat_media_files(
        input_files=[output_file, "another.mp4"],
        output_file="final.mp4",
        encoding_options=encoding_options,
        debug_mode=True
    )
    
    # FFmpeg 경로 직접 사용
    print(f"FFmpeg 경로: {FFMPEG_PATH}")


# 새로운 코드 (객체지향 구조 사용)
def new_code_example():
    """객체지향 구조를 사용하는 새로운 코드 예제"""
    from app.utils.ffmpeg_utils import FFmpegUtils
    from app.services.logging_service import LoggingService
    from app.services.settings_service import SettingsService
    from app.core.events import event_emitter, Events
    from app.core.commands import command_manager, TrimCommand, EncodingOptionsCommand
    
    # 로깅 서비스 사용
    logger = LoggingService().get_logger(__name__)
    
    # 설정 서비스 사용
    settings = SettingsService()
    ffmpeg_path = settings.get_ffmpeg_path()
    if not ffmpeg_path:
        ffmpeg_path = "C:/ffmpeg/bin/ffmpeg.exe"
        settings.set_ffmpeg_path(ffmpeg_path)
    
    # FFmpegUtils 인스턴스 사용 (싱글톤)
    ffmpeg_utils = FFmpegUtils()
    ffmpeg_utils.initialize_ffmpeg(ffmpeg_path)
    
    # 이벤트 리스너 등록
    def on_progress(progress):
        print(f"Progress: {progress}%")
    
    def on_complete(output_file):
        print(f"처리 완료: {output_file}")
    
    event_emitter.on(Events.PROCESS_PROGRESS, on_progress)
    event_emitter.on(Events.PROCESS_COMPLETED, on_complete)
    
    # 미디어 속성 가져오기
    input_file = "input.mp4"
    properties = ffmpeg_utils.get_media_properties(input_file, debug_mode=True)
    
    # 인코딩 옵션 설정 (명령 패턴 사용)
    old_options = {}
    new_options = {
        "codec": "h264",
        "preset": "medium",
        "crf": "23"
    }
    command = EncodingOptionsCommand(old_options, new_options)
    command_manager.execute(command)
    
    # 트리밍 설정 (명령 패턴 사용)
    trim_command = TrimCommand(
        file_id=input_file,
        old_start=0,
        old_end=0,
        new_start=10,
        new_end=20
    )
    command_manager.execute(trim_command)
    
    # 비디오 처리
    target_properties = {
        "width": 1920,
        "height": 1080,
        "fps": 30
    }
    
    # 진행 상황 업데이트를 위한 콜백 함수
    def progress_callback(progress):
        event_emitter.emit(Events.PROCESS_PROGRESS, progress)
    
    output_file = ffmpeg_utils.process_video_file(
        input_file=input_file,
        trim_start=10,
        trim_end=20,
        encoding_options=new_options,
        target_properties=target_properties,
        debug_mode=True,
        idx=0,
        progress_callback=progress_callback
    )
    
    # 처리 완료 이벤트 발행
    event_emitter.emit(Events.PROCESS_COMPLETED, output_file)
    
    # 파일 병합
    ffmpeg_utils.concat_media_files(
        input_files=[output_file, "another.mp4"],
        output_file="final.mp4",
        encoding_options=new_options,
        debug_mode=True,
        progress_callback=progress_callback
    )
    
    # FFmpeg 경로 가져오기 (설정 서비스 사용)
    print(f"FFmpeg 경로: {settings.get_ffmpeg_path()}")
    
    # 명령 취소 예제
    if command_manager.can_undo():
        print(f"명령 취소: {command_manager.get_undo_description()}")
        command_manager.undo()


if __name__ == "__main__":
    print("=== 기존 코드 실행 ===")
    old_code_example()
    
    print("\n=== 새로운 코드 실행 ===")
    new_code_example() 