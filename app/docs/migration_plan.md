# FFmpegGUI 구조 마이그레이션 기록

최종 갱신: 2026-07-30

이 문서는 2.0 구조 전환의 완료 기록이다. 새 기능은 아래 경계를 따라
구현하며 제거된 전역 경로나 UI 전용 트림 값을 다시 도입하지 않는다.

## 현재 의존 방향

```text
UI
 ├─ WorkspaceState / EncodingJob
 ├─ SettingsService
 └─ EncodingThread
      └─ FFmpegUtils (호환 파사드)
           ├─ FFmpegManager
           ├─ BatchProcessor
           ├─ ProcessorFactory
           └─ MediaMerger
```

## 완료된 전환

- FFmpeg 경로: 제거된 `FFMPEG_PATH` 대신
  `FFmpegManager().get_ffmpeg_path()` 사용
- 설정: `SettingsService.get/set/sync`로 통합
- 작업 입력: 튜플 대신 `EncodingJob`과 `MediaItem`
- 편집 상태: `WorkspaceState`, `EditSequence`, `EditClip`, `ClipRange`
- 진행과 취소: `EncodingThread`, `CancellationToken`, 이벤트 계약
- 미디어 처리: `ProcessorFactory`와 미디어별 processor
- UI 타임라인: 구형 마커·스핀박스 구현을 제거하고
  `CutTimelineWidget`로 통합
- 버전: `app.config.APP_VERSION` 한 곳에서 관리

## 유지하는 호환 경계

`FFmpegUtils`는 UI와 기존 처리기를 연결하는 얇은 파사드로 2.x 동안
유지한다. 새 core 코드는 파사드를 역으로 import하지 않는다. 하위 호환
함수는 신규 코드에서 사용하지 않으며 제거 전 사용처와 회귀 테스트를 먼저
확인한다.

## 변경 완료 조건

- `python -m compileall -q app tests`
- `python -m unittest discover -s tests -v`
- 문서 예제 import 성공
- 실제 미디어 회귀 성공
- PyInstaller 패키지 시작 성공

현재 검증 결과와 배포 절차는 `docs/development_plan.md`를 따른다.
