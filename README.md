# ffmpegGUI 2.0

ffmpegGUI는 Windows에서 영상, 이미지 시퀀스, 애니메이션 WebP를 한 작업
목록에 놓고 프레임 단위로 컷 편집한 뒤 FFmpeg로 변환하는 데스크톱 앱입니다.

## 주요 기능

- 단일 트랙 컷 타임라인에서 선택, 구간 조정, 분할, 복제, 삭제, 재정렬
- CFR/VFR 영상, PNG·JPG 이미지 시퀀스, 애니메이션 WebP 지원
- CPU H.264·H.265·VP9과 NVIDIA NVENC 프리셋
- 실제 실행 가능 여부까지 확인하는 NVENC 사전 검사와 CPU 대체 안내
- 출력 이름 자동 생성, 실행 전 문제 확인, 취소 후 안전한 재실행
- OTIO 가져오기·내보내기와 프레임 단위 미리보기
- FFmpeg가 없을 때 공식 Windows 빌드를 SHA-256 검증 후 사용자 폴더에 설치

## 기본 사용법

1. `소스 추가` 또는 드래그 앤 드롭으로 미디어를 추가합니다.
2. 소스를 선택하고 미리보기와 하단 타임라인에서 사용할 구간을 조정합니다.
3. 결과 프리셋과 저장 위치를 선택합니다.
4. 실행 전 확인 결과가 `문제 없음`인지 확인한 뒤 `인코딩 시작`을 누릅니다.

### 편집 조작

| 조작 | 기능 |
|---|---|
| 타임라인 클릭 | 클립 선택 및 해당 프레임으로 이동 |
| 클립 가장자리 드래그 | 사용할 시작·끝 구간 조정 |
| 클립 본문 드래그 | 클립 순서 변경 |
| `Ctrl+K` | 재생 헤드에서 클립 분할 |
| `Ctrl+D` | 선택 클립 복제 |
| `Delete` | 선택 클립 삭제 |
| `I` / `O` | 현재 프레임을 시작 / 끝 지점으로 지정 |
| `Space` | 재생 / 일시정지 |
| `←` / `→` | 한 프레임 이동 |
| `Ctrl+마우스 휠` | 타임라인 확대 / 축소 |
| `마우스 휠` | 확대된 타임라인 가로 이동 |
| `Ctrl+Z` / `Ctrl+Shift+Z` | 실행 취소 / 다시 실행 |

## 설치

가장 간단한 방법은
[GitHub Releases](https://github.com/CharlieYang0040/ffmpegGUI/releases/latest)에서
`ffmpegGUI-*-windows-x64.exe`와 `SHA256SUMS.txt`를 내려받는 것입니다.
실행 파일은 현재 코드 서명이 없으므로 Windows SmartScreen 안내가 나타날 수
있습니다.

## 개발 환경

- Windows 10/11 x64
- Python 3.13
- PySide6 6.8
- FFmpeg 8.x

```powershell
git clone https://github.com/CharlieYang0040/ffmpegGUI.git
cd ffmpegGUI
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

FFmpeg 경로를 설정하지 않아도 첫 실행 시 자동으로 준비합니다. 수동으로
사용하려면 설정 화면에서 `ffmpeg.exe` 경로를 지정할 수 있습니다.

## 검사와 빌드

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
.\scripts\build_release.ps1
```

릴리즈 스크립트는 테스트 후 `main.spec`으로 단일 실행 파일을 만들고
`artifacts/release/v<버전>/`에 실행 파일과 SHA-256 체크섬을 생성합니다.
버전의 단일 원천은 `app/config.py`의 `APP_VERSION`입니다.

실제 미디어 검증은 다음 명령으로 실행합니다.

```powershell
.\.venv\Scripts\python.exe .\scripts\run_real_media_regression.py
```

샘플 구성과 판정 기준은
[실제 미디어 회귀 가이드](docs/manual_real_media_regression.md)를 참고하세요.

## 문서

- [현재 개발 상태와 완료 기준](docs/development_plan.md)
- [2.0 변경 기록](CHANGELOG.md)
- [UI/UX V2 결과](docs/ui_ux_redesign_v2_plan.md)
- [미리보기 구조](docs/media_play_refactor_plan.md)
- [마이그레이션 가이드](app/utils/migration_guide.md)

## 알려진 제한

- Windows 전용입니다.
- 실행 파일은 Authenticode 코드 서명되지 않았습니다.
- 실제 출력 장치에서의 주관적 오디오 청취는 자동 회귀 범위에 포함하지
  않습니다. 대신 오디오 스트림, 비무음 신호, 앱 재생 진행을 확인합니다.
- 이미지 시퀀스에는 자체 FPS 정보가 없으므로 출력 FPS를 명시해야 합니다.

## 라이선스

[MIT License](LICENSE) — Copyright © 2024-2026 LHCinema
