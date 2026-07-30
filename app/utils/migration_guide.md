# FFmpegGUI 2.x 개발자 마이그레이션 가이드

## FFmpeg 경로

```python
from app.core.ffmpeg_manager import FFmpegManager

ffmpeg_path = FFmpegManager().get_ffmpeg_path()
```

`app.utils.ffmpeg_utils.FFMPEG_PATH`는 사용하지 않는다. 앱 시작 시 자동 탐색과
설치를 수행하며, 테스트에서는 `FFmpegManager`를 대체해 경로 계약을 검증한다.

## 설정

```python
from app.services.settings_service import SettingsService

settings = SettingsService()
output_path = settings.get("last_output_path", "")
settings.set("last_output_path", output_path)
settings.sync()
```

## 편집 상태와 인코딩 작업

UI에서 프레임 범위를 별도 변수로 추정하지 않는다.

```python
from app.core.models import ClipRange, EditClip, EditSequence, WorkspaceState

clip = EditClip(
    clip_id="clip-1",
    source_path="input.mp4",
    source_range=ClipRange(15, 90),
    source_frame_count=120,
    source_fps=30.0,
)
workspace = WorkspaceState(
    edit_sequence=EditSequence((clip,)),
    selected_clip_id=clip.clip_id,
)
```

`ClipRange`는 시작을 포함하고 끝을 포함하지 않는 0-based 범위다. 화면에는
필요할 때만 1-based 포함 범위로 변환한다. 실제 인코딩은 UI 객체를 직접
읽지 않고 `EncodingJob`을 만든 뒤 preflight를 통과시킨다.

## 처리 파사드

```python
from app.utils.ffmpeg_utils import FFmpegUtils

ffmpeg = FFmpegUtils()
properties = ffmpeg.get_media_properties("input.mp4")
```

`FFmpegUtils`는 2.x 호환 파사드다. 신규 core 모듈은 가능한 한
`FFmpegManager`, `BatchProcessor`, 미디어 processor를 직접 의존성으로
받는다.

## 버전

```python
from app.config import APP_VERSION
```

다른 모듈에 버전 문자열을 복제하지 않는다. 릴리즈 태그는
`v<APP_VERSION>`과 일치해야 한다.

## 확인

```powershell
.\.venv\Scripts\python.exe -m app.examples.migration_example
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
