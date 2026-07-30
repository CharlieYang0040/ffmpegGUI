# ffmpegGUI 2.0 개발 완료 기준

최종 갱신: 2026-07-30

## 상태

중단되어 있던 구조 복구, 실제 미디어 회귀, NVENC 재검증, UI/UX V2,
단일 트랙 컷 편집과 Windows 배포 자동화를 완료했다. 이 문서는 더 이상
미완료 작업 목록이 아니라 2.0 기준선과 향후 변경 시 지켜야 할 회귀 조건이다.

## 2.0에 포함된 결과

### 편집 작업 공간

- `WorkspaceState → EditSequence → EditClip → ClipRange`를 편집 상태의 단일
  원천으로 사용한다.
- 소스 목록, 미리보기, 타임라인, 인코딩 작업이 동일한 반열림 프레임 구간을
  사용한다.
- 하단 단일 트랙에서 선택, 탐색, 좌우 트림, 분할, 복제, 삭제, 재정렬,
  확대·축소와 가로 이동을 제공한다.
- 빈 타임라인 위치도 가장 가까운 클립과 프레임으로 탐색한다.
- 트림 중 시작·끝 프레임과 결과 시간을 즉시 표시한다.
- 선택은 색 외에도 흰색 점선과 양쪽 핸들로 구분한다.
- 화면 밖 클립과 썸네일 타일은 그리지 않으며, 소스 썸네일은 백그라운드에서
  준비되어 타임라인 캐시에 전달된다.
- 기존 `TimelineMarker`/`TimelineWidget`과 숨은 스핀박스 기반 프레임
  컨트롤을 제거하고 `CutTimelineWidget` 한 구현으로 통합했다.

### 인코딩과 사전 검사

- 목적 중심 CPU/GPU 프리셋과 사용자 설정을 `EncodingJob`으로 수집한다.
- 입력 누락, 출력 충돌, 저장 위치, 컨테이너 불일치와 encoder 사용 가능성을
  시작 전에 검사한다.
- FFmpeg encoder 목록뿐 아니라 짧은 실제 초기화로 NVENC 런타임을 확인한다.
- 취소 시 자식 FFmpeg와 작업 스레드를 종료하고 불완전 출력을 남기지 않는다.
- 취소 뒤 동일 앱 세션에서 재실행할 수 있다.

### 미디어와 상호운용

- CFR/VFR 영상, 이미지 시퀀스, 애니메이션 WebP를 동일 작업 흐름에서 다룬다.
- 비디오 미리보기는 `QMediaPlayer`, 이미지 시퀀스는 Qt 로더 스레드와
  버퍼를 사용한다.
- OTIO는 현재 `FFmpegManager` 경로 계약과 목록의 클립 구간을 사용한다.
- FFmpeg 자동 설치는 버전 정보와 SHA-256을 확인한 뒤 사용자 데이터 폴더의
  버전별 캐시에 설치한다.

## 검증 기준선

- 자동 테스트: 74개
- 컴파일 검사와 `pip check`
- 실제 미디어 자동 회귀: CFR, VFR, PNG 시퀀스, WebP, 취소, 재실행,
  NVENC의 7개 시나리오
- 실제 앱 미리보기: 재생, 일시정지, seek, 속도 변경, 영상/시퀀스 전환
- 패키징: PyInstaller 단일 실행 파일 시작 스모크
- 긴 타임라인: 50개 클립과 최대 확대 geometry 회귀

표준 검사:

```powershell
.\.venv\Scripts\python.exe -m compileall -q app tests
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
git diff --check
.\.venv\Scripts\python.exe .\scripts\run_real_media_regression.py
.\scripts\build_release.ps1
```

## 화면 인수 기준

아래 Windows 논리 해상도에서 앱 시작 직후 소스, 미리보기, 결과 설정,
타임라인과 인코딩 버튼이 잘리지 않아야 한다.

- 1366×768
- 1440×900
- 1920×1080
- 표시 배율 100%, 125%, 150%, 200%

최소 논리 크기보다 작은 화면에서는 창 최대화를 우선하며, 저장된 창 크기가
현재 화면을 벗어나면 안전한 기본 크기로 복구한다. 포커스가 있는 타임라인은
점선 테두리로 표시하고, 선택과 오류를 색 하나에만 의존하지 않는다.

## 배포 정책

- 버전의 단일 원천: `app/config.py::APP_VERSION`
- 지원 개발 환경: Windows x64, Python 3.13
- 태그 형식: `v<APP_VERSION>`
- 산출물: `ffmpegGUI-v<버전>-windows-x64.exe`, `SHA256SUMS.txt`
- `main`과 PR은 Windows CI에서 컴파일, 74개 테스트, 의존성 검사를 수행한다.
- 태그가 푸시되면 별도 릴리즈 워크플로가 테스트, 패키징, 체크섬 생성,
  GitHub Release 업로드를 수행한다.
- 공개 산출물은 다운로드한 파일의 체크섬까지 다시 확인해야 배포 완료로 본다.

## 앞으로의 변경

2.0 이후 기능은 별도 이슈와 계획으로 시작한다. 다음 항목은 알려진 확장
후보이며 2.0 배포 차단 사항은 아니다.

- 대형 4K 이미지 시퀀스의 장시간 메모리·프레임 드롭 계측
- OTIO에서 소스 FPS와 이미지 시퀀스 패딩을 더 엄격하게 보존
- Windows 코드 서명
- 다중 트랙, 전환 효과, 오디오 믹싱
