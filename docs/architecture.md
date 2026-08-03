# 아키텍처

## 단일 원본

`TimelineModel`이 편집 결과의 단일 원본이다. Qt UI, GES 미리보기와 FFmpeg 출력은
모두 불변 스냅샷인 `TimelineSpan` 목록을 소비한다. 외부 엔진 객체를 프로젝트
상태로 저장하지 않는다.

```text
TimelineModel
  ├─ MediaAsset: 경로, 길이, 실제 프레임 PTS
  └─ Clip: asset, source-in, duration
          ↓ snapshot
      TimelineSpan[]
       ├─ Qt timeline view
       ├─ GES adapter
       └─ FFmpeg export compiler
```

## 시간 계약

- 모든 내부 시간은 부호 있는 64비트 나노초 정수다.
- 구간은 `[in, out)` 반열림 범위다.
- 미디어 프레임 PTS는 원본의 첫 표시 프레임을 0으로 정규화한다.
- 타임라인 길이는 활성 클립 길이의 합이다.
- 단일 트랙은 항상 마그네틱하다. 일반 클립 사이에 암묵적 gap을 저장하지 않는다.
- 화면 프레임 번호와 타임코드는 프로젝트 표시 FPS에서 파생하며 저장 좌표로
  사용하지 않는다.

## 스레드 경계

- UI 스레드는 편집 명령을 적용하고 작은 모델 스냅샷을 게시한다.
- GStreamer는 전용 GLib 컨텍스트 스레드에서 동작한다.
- FFmpeg 출력은 별도 프로세스로 실행해 충돌과 취소를 격리한다.
- 썸네일·파형·PTS 분석은 제한된 작업 큐에서 수행한다.
- 디코딩 프레임을 CPU `QImage`로 변환하지 않고 D3D11 텍스처로 전달한다.

## 의존성 원칙

`src/core`는 Qt, GStreamer와 FFmpeg 헤더를 포함하지 않는다. 통합 코드는 어댑터
계층에만 위치한다. 따라서 편집 규칙은 빠른 단위 테스트로 검증할 수 있고 미디어
엔진을 교체해도 프로젝트 포맷과 실행 취소 기록을 유지할 수 있다.
