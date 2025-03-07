# FFmpegGUI 마이그레이션 가이드

## 개요

이 문서는 FFmpegGUI 프로젝트의 구조 개선에 따른 마이그레이션 가이드입니다. 기존의 하위 호환성을 위한 전역 함수들이 제거되고, 객체지향적인 접근 방식으로 변경되었습니다.

## 주요 변경 사항

1. 싱글톤 패턴 도입
2. 의존성 주입 패턴 도입
3. 설정 관리 중앙화
4. 팩토리 패턴 도입
5. 이벤트 기반 아키텍처 도입
6. 명령 패턴 개선
7. 로깅 서비스 개선

## 마이그레이션 방법

### 1. FFmpegUtils 사용 방법 변경

**기존 코드:**
```python
from app.utils.ffmpeg_utils import get_media_properties, process_video_file

# 함수 직접 호출
properties = get_media_properties(input_file, debug_mode)
output_file = process_video_file(input_file, trim_start, trim_end, encoding_options, 
                                target_properties, debug_mode, idx, progress_callback)
```

**새로운 코드:**
```python
from app.utils.ffmpeg_utils import FFmpegUtils

# FFmpegUtils 인스턴스 생성 (싱글톤이므로 항상 같은 인스턴스 반환)
ffmpeg_utils = FFmpegUtils()

# 인스턴스 메서드 호출
properties = ffmpeg_utils.get_media_properties(input_file, debug_mode)
output_file = ffmpeg_utils.process_video_file(input_file, trim_start, trim_end, encoding_options, 
                                            target_properties, debug_mode, idx, progress_callback)
```

### 2. 의존성 주입 활용

**기존 코드:**
```python
class MyClass:
    def __init__(self):
        # 전역 함수 직접 사용
        self.thread_count = get_optimal_thread_count()
```

**새로운 코드:**
```python
from app.utils.ffmpeg_utils import FFmpegUtils

class MyClass:
    def __init__(self, ffmpeg_utils=None):
        # 의존성 주입 또는 기본값 사용
        self.ffmpeg_utils = ffmpeg_utils or FFmpegUtils()
        self.thread_count = self.ffmpeg_utils.get_optimal_thread_count()
```

### 3. 설정 서비스 활용

**기존 코드:**
```python
from app.utils.ffmpeg_utils import FFMPEG_PATH

# 전역 변수 직접 사용
ffmpeg_path = FFMPEG_PATH
```

**새로운 코드:**
```python
from app.services.settings_service import SettingsService

# 설정 서비스 사용
settings = SettingsService()
ffmpeg_path = settings.get_ffmpeg_path()
```

### 4. 로깅 서비스 활용

**기존 코드:**
```python
import logging

# 로깅 직접 설정
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
```

**새로운 코드:**
```python
from app.services.logging_service import LoggingService

# 로깅 서비스 사용
logger = LoggingService().get_logger(__name__)
```

## 마이그레이션 체크리스트

1. 모든 전역 함수 호출을 FFmpegUtils 인스턴스 메서드 호출로 변경
2. 모든 클래스에 의존성 주입 패턴 적용
3. 설정 관련 코드를 SettingsService 사용으로 변경
4. 로깅 관련 코드를 LoggingService 사용으로 변경
5. 이벤트 기반 진행 상황 업데이트 구현
6. 테스트 코드 업데이트

## 주의 사항

1. 모든 변경 사항은 테스트 후 적용해야 합니다.
2. 대규모 변경 시 단계적으로 적용하는 것이 좋습니다.
3. 변경 후 기존 기능이 정상 작동하는지 확인해야 합니다.

## 지원 및 문의

문제가 발생하거나 도움이 필요한 경우 이슈 트래커를 통해 문의해 주세요. 