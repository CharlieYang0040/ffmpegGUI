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
- Qt Quick 6.10.2
- GStreamer Editing Services 1.28.5
- FFmpeg 8.1.2

Qt와 GStreamer가 없어도 편집 코어와 테스트는 빌드할 수 있습니다. Windows 로컬
개발 의존성은 저장소 밖 시스템 경로를 바꾸지 않고 `.tools`에 설치합니다.

## 빌드

Visual Studio 2022 Build Tools, CMake 3.28 이상, Python 3가 필요합니다. Qt,
GStreamer, FFmpeg는 준비 스크립트가 프로젝트 로컬 경로에 설치합니다.

```powershell
.\scripts\bootstrap_windows.ps1
cmake --preset windows-msvc
cmake --build --preset windows-debug
ctest --preset windows-debug
.\scripts\run_ges_smoke.ps1
.\scripts\run_4k_seek_benchmark.ps1
.\scripts\run_playback_soak.ps1 -Seconds 60
.\out\build\windows-msvc\Debug\ffgui_core_benchmark.exe
.\scripts\run_desktop_smoke.ps1
```

`out/build/.../Release/ffmpegGUI-next.exe`는 개발용 빌드 산출물이므로 단독 실행하지
않습니다. 실행 가능한 배포본은 다음 명령으로 생성합니다.

```powershell
.\scripts\package_release.ps1 -Version 0.1.0
.\scripts\test_release_package.ps1 -Version 0.1.0
```

배포용 EXE는 `out/release-v0.1.0/ffmpegGUI-next-v0.1.0-win-x64`에 있으며 Qt DLL,
QML 모듈과 필요한 GStreamer 런타임을 함께 포함합니다.

`run_ges_smoke.ps1`은 CFR MP4, CFR MKV, VFR MKV를 생성해 트림된 4개 샷을 하나의
타임라인으로 연속 재생하고 1280x720 CPU BGRA 미리보기 프레임을 검증합니다.
`run_desktop_smoke.ps1`은 같은 파일로 인프로세스 미리보기, 프로젝트 왕복과 타임라인
썸네일 캐시 생성을 검사합니다. D3D11 제로카피와 CPU 폴백 모두 실제 Qt Scene Graph
표시까지 확인합니다. 기본 미리보기는 D3D11이며 드라이버 호환성 진단이 필요하면
`FFGUI_FORCE_CPU_PREVIEW=1`로 CPU BGRA 경로를 강제할 수 있습니다. 기본
`run_4k_seek_benchmark.ps1`은 실제 3840x2160 H.264/HEVC 개발용 영상을 만들고
D3D11 하드웨어 디코더의 임의 탐색 후 첫 GPU 프레임 도착 시간을 검사합니다.
`run_playback_soak.ps1`은 같은 영상이 섞인 타임라인에서 PTS 기반 seek와
pause/play/stop, 파이프라인 재구축을 반복하며 지연과 private memory 증가를 검사합니다.
기본
FFmpeg는 SHA-256 검증 후 `.tools/ffmpeg`에
설치된 8.1.2이며 `-FFmpegPath`로 바꿀 수 있습니다.

## 디렉터리

- `src/core`: 미디어 자산, VFR 시간표, 편집 시퀀스
- `src/playback`: 미리보기 엔진이 구현할 인터페이스
- `apps/desktop`: Qt Quick 애플리케이션
- `tests`: 외부 SDK 없이 실행되는 코어 회귀 테스트
- `scripts`: 의존성 설치와 실제 미디어 회귀 검사
- `tools`: GES 미디어 스모크와 대규모 타임라인 측정 도구

미디어를 추가하면 번쩍이는 터미널 창 없이 FFprobe가 백그라운드에서 실제 영상
프레임 PTS를 읽고, FFmpeg가 파형과 12프레임 썸네일 아틀라스를 캐시합니다. 분석이
끝나기 전에는 타임라인에 임시 길이를 넣지 않습니다.

내보내기는 H.264 NVENC를 먼저 사용하고 사용할 수 없으면 libx264 CPU 인코딩으로
자동 전환합니다. 같은 이름의 파일은 덮어쓰지 않고 `_001` 형식의 새 이름을 확인한
뒤 저장하며, 취소하거나 실패한 불완전 파일은 제거합니다.
동일 원본의 컷 경계가 실제 키프레임에 맞으면 자동으로 무손실 stream-copy를 사용하고,
적용할 수 없거나 실패하면 일반 인코딩 경로로 되돌아갑니다.
출력 중에는 상단 상태 막대에서 인코딩 방식, 파일명과 진행률을 확인할 수 있습니다.
FFmpeg가 끝난 뒤 FFprobe로 영상 스트림과 예상 재생시간을 다시 검사하며, 검증까지
통과해야 완료로 처리합니다. 출력마다 `logs/export-날짜-시간.log`에 전체 FFmpeg 출력과
검증 결과를 따로 보존합니다.

출력 패널에서 고화질·균형·용량 절약 화질 단계, H.264·H.265/HEVC·가능할 때 원본
스트림 복사 코덱 방식, MP4·MKV·MOV 컨테이너를 조합할 수 있습니다. H.264와 HEVC는
NVENC 실패 시 같은 코덱의 CPU 인코더로 전환하며, MKV에는 QuickTime 전용 옵션을
전달하지 않습니다.

기본 편집 단축키는 `Space` 재생/일시정지, `←/→` 실제 프레임 이동, `↑/↓` 이전/다음
컷 경계, `Ctrl+K` 분할, `Delete` 선택 샷 삭제입니다. 프레임 이동은 CFR 표시 FPS가
아니라 원본 VFR PTS를 사용합니다. `Ctrl+D`는 선택 샷을 바로 뒤에 마그네틱하게
복제하며 한 번의 Undo로 되돌릴 수 있습니다.
마우스로 트림하거나 분할한 결과도 가장 가까운 실제 원본 프레임 경계로 확정됩니다.
왼쪽 미디어 보관함의 `+`를 누르거나 샷을 타임라인으로 끌면 재생 헤드 또는 놓은
위치에 삽입됩니다. 기존 샷 중간에 삽입하면 원본 샷은 자동으로 양쪽에 보존됩니다.
타임라인에서 `Ctrl+클릭`으로 떨어진 샷을 추가 선택하고 `Shift+클릭`으로 연속 범위를
선택할 수 있습니다. `Delete`는 선택한 샷을 한 번에 지우고 빈자리를 자동으로 닫습니다.
`Ctrl+D`는 하나 또는 여러 선택 샷을 원래 순서 그대로 한 번에 복제합니다.
여러 샷을 선택한 뒤 선택된 샷 하나를 끌면 묶음 전체를 함께 재배치할 수 있습니다.
`V` 선택 도구에서는 클립 이동과 가장자리 트림을 하고, `A` 탐색 도구에서는 클립 위를
포함한 타임라인 어디서든 드래그해 재생 헤드와 미리보기를 탐색합니다. Windows 탐색기의
영상 파일을 앱 창으로 놓아 미디어를 추가할 수도 있습니다.
GES 타임라인 준비와 seek는 UI 스레드 밖에서 직렬 처리합니다. 빠르게 여러 위치를
scrub하거나 연속 편집하면 오래된 요청을 차례로 화면에 반영하지 않고 마지막 요청으로
수렴하며, 프로그램 모니터 헤더에서 준비·재생·오류 상태를 색으로 확인할 수 있습니다.
기본 영상 출력은 GStreamer `d3d11videosink`의 외부 HWND를 사용하지 않습니다.
GES의 1280x720 BGRA appsink 프레임을 앱 내부 `VideoPreviewItem`으로 전달해 Qt Scene
Graph에서 표시하며, UI가 밀릴 때는 아직 표시하지 않은 프레임을 최신 한 장으로 합쳐
프레임 복사 작업과 메모리가 무제한 쌓이지 않게 합니다.
타임라인의 클립·파형·hover는 C++ Scene Graph에서 그리고, 캐시된 12프레임 아틀라스는
현재 viewport 좌표와 트림된 원본 범위에 맞춰 이미지 계층에서 표시합니다.
앱 시작과 미리보기/GStreamer 오류는
`%LOCALAPPDATA%\CharlieYang0040\ffmpegGUI Next\logs\editor.log`에 계속 기록됩니다.
미디어 분석은 duration, 프레임 타임라인, 파형, 썸네일 단계별 소요 시간을 남깁니다.
상단 `로그` 버튼으로 폴더를 바로 열 수 있으며, 10MiB가 넘은 앱 로그는
`editor.previous.log`로 한 번 순환합니다.
`I`와 `O`로 구간 시작·끝을 표시하고 `Shift+Delete`로 해당 구간을 프레임 정확하게
삭제할 수 있습니다. 삭제 후 빈자리는 자동으로 닫히며 한 번의 Undo로 복원됩니다.
오른쪽 클립 오디오 패널에서 선택한 하나 이상의 샷에 볼륨, 음소거, 페이드 인·아웃을
적용할 수 있습니다. `M`은 선택 샷의 음소거를 전환합니다. 같은 설정을 GES 전체
타임라인 미리보기와 FFmpeg 출력이 공유하며, 오디오 효과가 있으면 안전을 위해
stream-copy 대신 재인코딩합니다.
같은 패널의 재생 속도는 선택한 샷을 25%~400%로 변경합니다. 원본 프레임 범위는
보존한 채 타임라인 길이와 프레임 이동이 속도에 맞게 바뀌며, GES 미리보기와 FFmpeg
출력에는 같은 영상·오디오 속도가 적용됩니다. 속도 변경이 있으면 stream-copy는
사용하지 않습니다.
자막 모델과 SRT/ASS 출력 코드는 보존하지만 기본 컷 편집기 안정화 기간에는 자막 UI와
GES 오버레이 미리보기를 비활성화합니다. GES 텍스트 오버레이가 정확 seek 중 아래 영상
객체를 잃어 전체 NLE composition을 중단시키는 문제가 확인됐기 때문입니다. 기본 재생과
편집 완료 기준을 통과한 뒤 gap-safe 합성 구조와 독립 회귀 검사를 갖춰 다시 활성화합니다.
- `docs`: 아키텍처와 단계별 완료 기준
