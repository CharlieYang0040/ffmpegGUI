# ffmpegGUI Next

Windows용 네이티브 마그네틱 컷 편집기입니다. 기존 Python `ffmpegGUI v2.0.2`는
안정판으로 유지하고, 이 저장소에서 C++23 기반 차세대 구조를 개발합니다.

## 목표

- 전체 타임라인 연속 재생
- 나노초 시간축과 VFR 원본 프레임 매핑
- 트림·분할·삭제 시 빈 공간이 생기지 않는 마그네틱 단일 트랙
- GPU 디코딩에서 화면 출력까지 D3D11 제로카피
- 키프레임 정렬 컷의 무손실 스트림 복사와 NVENC 빠른 출력
- 미리보기와 최종 출력이 공유하는 하나의 편집 모델

## 기술 기준선

- C++23 / CMake / MSVC x64
- Qt Quick 6.8 이상
- GStreamer Editing Services 1.28.x
- FFmpeg 8.x

Qt와 GStreamer가 없어도 편집 코어와 테스트는 빌드할 수 있습니다.

## 빌드

```powershell
cmake --preset windows-msvc
cmake --build --preset windows-debug
ctest --preset windows-debug
```

Qt가 발견되면 `ffmpegGUI-next` 데스크톱 대상도 함께 생성됩니다. 현재 시스템에서
Qt가 발견되지 않으면 코어와 테스트만 빌드하고 구성 단계에 안내를 표시합니다.

## 디렉터리

- `src/core`: 미디어 자산, VFR 시간표, 편집 시퀀스
- `src/playback`: 미리보기 엔진이 구현할 인터페이스
- `apps/desktop`: Qt Quick 애플리케이션
- `tests`: 외부 SDK 없이 실행되는 코어 회귀 테스트
- `docs`: 아키텍처와 단계별 완료 기준
