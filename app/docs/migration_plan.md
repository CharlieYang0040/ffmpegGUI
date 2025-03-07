# FFmpegGUI 마이그레이션 계획

## 개요

이 문서는 FFmpegGUI 프로젝트의 하위 호환성 코드를 제거하고 근본적인 구조 개선을 위한 마이그레이션 계획을 설명합니다.

## 현재 상황

현재 `ffmpeg_utils.py` 파일에는 두 가지 유형의 코드가 공존합니다:

1. `FFmpegUtils` 클래스 - 새로운 객체지향 구조
2. 전역 함수들 - 하위 호환성을 위해 유지되는 코드

이러한 구조는 다음과 같은 문제를 야기합니다:

- 코드 중복
- 유지보수 어려움
- 의존성 관리 복잡성
- 테스트 어려움

## 개선 목표

1. 싱글톤 패턴 도입
   - FFmpeg 경로 관리와 같은 전역 상태를 관리하기 위한 싱글톤 패턴 도입

2. 의존성 주입 패턴 도입
   - 모듈 간 의존성을 명시적으로 관리하기 위한 의존성 주입 패턴 도입

3. 설정 관리 중앙화
   - 설정 관리를 중앙화하여 일관된 설정 접근 방식 제공

4. 팩토리 패턴 도입
   - 미디어 처리기를 생성하기 위한 팩토리 패턴 도입

5. 이벤트 기반 아키텍처 도입
   - 진행 상황 업데이트와 같은 비동기 작업을 위한 이벤트 기반 아키텍처 도입

6. 명령 패턴 개선
   - UI 작업을 위한 명령 패턴을 개선하여 실행 취소/다시 실행 기능 강화

7. 로깅 서비스 개선
   - 로깅을 중앙화하여 일관된 로깅 방식 제공

## 마이그레이션 단계

### 1단계: 의존성 매핑 및 분석 (1주)

- 하위 호환성 함수들이 어디서 사용되는지 파악
- 각 함수의 호출 지점을 식별하고 문서화
- 의존성 그래프 작성

### 2단계: 핵심 클래스 구현 (2주)

- FFmpegUtils 싱글톤 패턴 구현
- FFmpegManager 개선
- ProcessorFactory 개선
- BatchProcessor 개선
- 이벤트 시스템 구현

### 3단계: 서비스 클래스 구현 (1주)

- SettingsService 개선
- LoggingService 개선
- CommandManager 구현

### 4단계: 새로운 인터페이스로 마이그레이션 (2주)

- 모든 하위 호환성 함수 호출을 새로운 객체지향 인터페이스로 변경
- 다음과 같은 패턴으로 변경:
  ```python
  # 기존 코드
  result = get_media_properties(input_file, debug_mode)
  
  # 새 코드
  ffmpeg_utils = FFmpegUtils()
  result = ffmpeg_utils.get_media_properties(input_file, debug_mode)
  ```

### 5단계: 테스트 및 검증 (1주)

- 단위 테스트 작성
- 통합 테스트 작성
- 회귀 테스트 작성
- 성능 테스트 수행

### 6단계: 하위 호환성 함수 제거 (1일)

- 모든 코드가 새로운 인터페이스를 사용하도록 변경된 후, 하위 호환성 함수 제거
- 제거 전에 모든 테스트가 통과하는지 확인

### 7단계: 문서화 및 배포 (3일)

- 새로운 구조에 대한 문서 작성
- 마이그레이션 가이드 작성
- 새 버전 배포

## 구현 세부 사항

### 싱글톤 패턴 구현

```python
class FFmpegUtils:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FFmpegUtils, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        # 초기화 코드
```

### 의존성 주입 패턴 구현

```python
class VideoProcessor:
    def __init__(self, ffmpeg_manager=None):
        from app.core.ffmpeg_manager import FFmpegManager
        self.ffmpeg_manager = ffmpeg_manager or FFmpegManager()
```

### 이벤트 기반 아키텍처 구현

```python
# 이벤트 발행
event_emitter.emit(Events.PROCESS_PROGRESS, progress)

# 이벤트 구독
event_emitter.on(Events.PROCESS_PROGRESS, on_progress)
```

### 명령 패턴 구현

```python
# 명령 생성
command = TrimCommand(file_id, old_start, old_end, new_start, new_end)

# 명령 실행
command_manager.execute(command)

# 명령 취소
command_manager.undo()
```

## 위험 요소 및 완화 전략

1. **기존 코드 호환성 문제**
   - 완화: 점진적 마이그레이션 및 철저한 테스트

2. **성능 저하 가능성**
   - 완화: 성능 테스트 및 최적화

3. **개발자 학습 곡선**
   - 완화: 문서화 및 예제 코드 제공

4. **마이그레이션 중 버그 발생**
   - 완화: 단계별 테스트 및 롤백 계획

## 일정

- 총 마이그레이션 기간: 약 6주
- 1단계: 1주
- 2단계: 2주
- 3단계: 1주
- 4단계: 2주
- 5단계: 1주
- 6-7단계: 4일

## 결론

이 마이그레이션 계획을 통해 FFmpegGUI 프로젝트의 코드 품질을 향상시키고, 유지보수성을 개선하며, 확장성을 높일 수 있습니다. 점진적인 접근 방식과 철저한 테스트를 통해 마이그레이션 과정에서 발생할 수 있는 위험을 최소화할 수 있습니다. 