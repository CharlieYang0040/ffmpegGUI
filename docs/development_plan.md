# 개발 계획

최종 갱신: 2026-08-09

## 0. 시작 기준선

- 기존 `ffmpegGUI v2.0.2` 저장소와 릴리스를 변경하지 않는다.
- 새 프로젝트는 별도 Git 저장소와 빌드 산출물 디렉터리를 사용한다.
- 외부 SDK가 없어도 C++ 편집 코어와 테스트가 빌드되어야 한다.

## 1. 편집 코어

- [x] C++23/CMake/MSVC 프로젝트
- [x] 나노초 시간 타입과 overflow 검사
- [x] VFR 프레임 PTS를 보존하는 `MediaAsset`
- [x] 숨김 FFprobe 프로세스로 실제 프레임 PTS 백그라운드 분석
- [x] 마그네틱 `TimelineModel`
- [x] 트림, 분할, 삭제, 삽입 재정렬
- [x] 시퀀스 위치와 원본 위치 양방향 매핑
- [x] 트림·이동·분할·삭제 undo/redo와 redo 분기 무효화
- [x] 나노초 정밀도를 보존하는 JSON 프로젝트 저장/불러오기

## 2. 네이티브 UI

- [x] Qt Quick 애플리케이션 골격
- [x] C++ Scene Graph 타임라인 렌더러
- [x] 재생 헤드, 트림 핸들, 드래그 중 삽입 미리보기
- [x] 실제 타임라인 드래그 트림·샷 재정렬·분할·삭제 연결
- [x] Ctrl+휠 확대/축소, 휠 스크롤, 보이는 클립만 렌더링
- [x] 트림 원본 범위에 맞춘 가시 구간 오디오 파형
- [x] 원본 시간 범위를 따라 잘리는 12프레임 썸네일 텍스처 아틀라스
- [x] 실제 VFR PTS 기반 이전·다음 프레임과 컷 경계 키보드 이동
- [x] 마우스 트림·분할 결과의 실제 VFR 프레임 경계 스냅
- [x] 선택 샷 마그네틱 복제와 단일 단계 undo
- [x] 썸네일 미디어 보관함과 재생 헤드 위치 드래그·버튼 삽입
- [x] 샷 중간 삽입 시 자동 분할과 단일 단계 undo
- [x] Ctrl 개별·Shift 연속 다중 선택과 묶음 리플 삭제
- [x] 선택 순서를 보존하는 다중 샷 묶음 복제와 단일 단계 undo
- [x] 선택 묶음의 순서 보존 드래그 재배치와 no-op 이력 제거
- [x] 연속 구조 편집의 미리보기 재구축 병합과 재생·탐색 시 최신성 보장
- [x] I/O 구간 마커, 타임라인 범위 표시와 프레임 정확 리플 삭제
- [x] 다중 선택 클립 볼륨·음소거·페이드 편집과 프로젝트 왕복
- [x] 자막 추가·내용/길이 편집·삭제와 타임라인 자막 바
- [x] 컷 삭제·삽입에 따른 자막 리플 매핑과 통합 undo/redo
- [x] 자막 바 본체 드래그 이동과 좌우 핸들 구간 트림
- [x] UTF-8 다중 행 SRT 가져오기·내보내기와 배치 undo
- [x] 25%~400% 클립 재생 속도 편집, 원본/시퀀스 시간 매핑과 프로젝트 왕복

## 3. 미디어 엔진

- [x] GStreamer 1.28.5 및 GES 로컬 의존성 잠금
- [x] MP4/MKV/CFR/VFR 4샷 연속 재생 프로토타입
- [x] `TimelineSpan` → `GESTimeline` 어댑터
- [x] 전체 시퀀스 seek와 클립 경계 재생
- [x] 로드 직후 stopped seek와 paused 역방향 seek의 preroll 완료 보장
- [x] GStreamer 오류와 EOS 상태를 Qt UI로 전달
- [x] D3D11 GPU 텍스처 → Qt Scene Graph 제로카피
- [x] GStreamer 재생 시계를 단일 타임라인 재생 헤드에 연결
- [x] 클립 경계 오디오 버퍼 PTS 연속성 정밀 측정
- [x] GES 클립 gain·음소거·페이드 제어 곡선 미리보기
- [ ] GES 자막 오버레이의 gap-safe 합성과 정확 seek 회귀(기존 구현은 기본 모드에서 비활성)
- [x] GES 클립별 영상·오디오 재생 속도 미리보기

## 4. 출력

- [x] FFmpeg 8.1.2 로컬 설치와 SHA-256 검증
- [x] 동일 원본·키프레임 정렬 컷의 stream-copy/remux와 실패 시 재인코딩 폴백
- [x] H.264 NVENC GPU 출력과 진행률 표시
- [x] CPU 폴백, 취소, 불완전 출력 정리
- [x] 미리보기 스냅샷과 출력 작업의 편집 리비전 동일성 검사
- [x] FFmpeg 클립 gain·음소거·페이드 합성과 stream-copy 안전 차단
- [x] UTF-8 ASS 자막 번인 출력과 stream-copy 안전 차단
- [x] FFmpeg 영상 setpts·오디오 atempo 속도 출력과 stream-copy 안전 차단

## 5. 배포 완료 조건

- [x] Qt/GStreamer 런타임을 포함한 독립 Windows x64 ZIP 패키징
- [ ] 별도 Windows 11 x64 클린 PC 설치/실행
- CFR, VFR, MKV, 이미지 시퀀스 실제 미디어 회귀
- [x] 4K H.264/HEVC 타임라인 탐색 성능 측정
- [x] 1000클립 타임라인 UI 프레임 시간 측정
- [x] 4K 혼합 코덱 반복 seek·상태 전환·파이프라인 재구축 120초 soak
- 공개 산출물 SHA-256 재검증

## 현재 검증 기준선

- 2026-08-03 Debug 빌드와 코어 테스트 28/28 및 타임라인 Scene Graph 테스트 통과
- CFR MP4 + CFR MKV + VFR MKV, 2배속 샷을 포함한 트림 4샷 2.425초 연속 재생 통과
- 실제 네이티브 창/D3D11 출력 초기화 후 5초 생존 검사 통과
- 실제 미디어 프로젝트 JSON 저장/불러오기 왕복 후 타임라인 길이 일치
- QML 정적 검사 무경고 통과
- FFmpeg 8.1.2 Windows 압축 파일 SHA-256 `db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec` 검증
- CFR/VFR 실제 프레임 PTS를 JSON 왕복하고 VFR 233ms 간격 보존 확인
- CFR MP4/CFR MKV/VFR MKV별 1920x90 썸네일 아틀라스 생성 및 프로젝트 왕복 확인
- 3개 실제 미디어 전체 타임라인을 H.264/AAC MP4 6.239초로 출력 확인
- 실제 H.264/AAC 원본의 키프레임 정렬 2개 컷을 재인코딩 없이 3초 MP4로 remux 확인
- 재생 엔진에 게시한 불변 스냅샷과 동일 리비전에서만 출력 시작하도록 검증
- 2배속 샷을 포함한 4샷 GES 2.425초 연속 재생에서 오디오 235버퍼·최대 양의 PTS gap 0ns 확인
- 개발 도구 PATH를 제거한 독립 패키지에서 프로젝트 왕복과 실제 타임라인 재생 통과
- 1,000클립 스냅샷 평균 1.91ms 이하(동일 PC Debug 빌드, 1,000회 측정)
- 1,000클립 정적 지오메트리를 재사용하는 재생 헤드 갱신 평균 0.000207ms
  (동일 PC Debug 빌드, 600프레임 측정, 60 FPS 예산 16.67ms)
- 실제 3840x2160 NVENC H.264/HEVC 입력의 PTS 검증 D3D11 하드웨어 탐색 8회에서
  H.264 중앙값 216.047ms·최대 381.205ms, HEVC 중앙값 136.125ms·최대 331.801ms
  (미리보기 출력 프로필 1280x720)
- 4K H.264/HEVC 혼합 타임라인 120초 soak에서 stopped/paused seek, 역방향 탐색과
  파이프라인 재구축을 포함한 257회 PTS 일치 프레임 확인, 최대 지연 1151.24ms,
  측정 구간 private memory 증가 0MiB
- 같은 4K 혼합 타임라인 10분 연속 soak에서 2,294회 PTS 일치 프레임 확인,
  최대 지연 1431.13ms, 측정 구간 private memory 증가 0MiB
- 12회 연속 구조 편집의 GES 재구축을 최대 2회로 병합해 동일 데스크톱 회귀 시간을
  136초에서 33.78초로 단축, 실제 전체 시퀀스 재생 포함 회귀는 41.85초 통과

## 2026-08-08 기본 편집기 안정성 복구

- [x] GES 타임라인 준비·seek·play/pause를 UI 비차단 단일 작업 경로로 이동
- [x] 연속 scrub·편집 중 최신 seek 위치와 타임라인 세대로 요청 병합
- [x] paused 전환 진행 중인 파이프라인의 정상 seek 허용과 상태 포함 오류 메시지
- [x] 동일 세대 준비 실패의 무한 자동 재시도 차단
- [x] `NleComposition structure is not valid` 상세 로그로 자막 오버레이 원인 특정
- [x] 기본 편집기 미리보기에서 불안정한 GES 자막 오버레이 격리
- [x] 프로그램 모니터를 고정 헤더·영상 영역으로 분리하고 준비/재생/오류 상태 표시
- [x] 편집 도구를 재생·이력·컷·구간 그룹으로 재배치하고 hover/pressed/danger 상태 적용
- [x] 타임라인 클립 hover 강조와 이동·트림 커서 피드백
- [x] 클립별 QML 썸네일·자막 delegate 제거 및 자산별 파형 데이터 캐시
- [x] 파형을 포함한 전체 QVariant 타임라인의 UI 스레드 깊은 비교 제거
- [x] 기본 모드에서 실험용 D3D11 Scene Graph 객체·GPU 장치 경로 완전 격리
- [x] 2초 UI 이벤트 루프 watchdog과 GES/Scene Graph/뷰 모델 구간별 지연 로그
- [x] Qt 테스트 플랫폼을 실제 설치된 `windows` 플러그인으로 고정해 숨은 오류창 제거
- [x] Debug 빌드, 28개 코어 회귀, Scene Graph, QML lint, 실제 GES/데스크톱 회귀 통과

다음 구현 순서:

1. 편집 후 전체 GES 파이프라인 재생성을 자산·클립 단위 증분 갱신으로 축소
2. 분할·리플 삭제·트림·이동·Undo/Redo 상호작용 회귀 확대
3. 삽입/덮어쓰기 및 리플/롤링 트림의 기본 편집 모드 구현

현재 차단 증거:

- 네이티브 `d3d11videosink`는 여러 GES 파이프라인 교체 뒤 Qt 컨테이너 HWND를 다시
  열지 못해 `Failed to open window`와 `READY → PAUSED` 실패를 발생시킨다.
- D3D11 appsink는 RGBA 셰이더 리소스와 Qt 장치 공유, 멀티스레드 보호를 적용해
  Scene Graph presentation 회귀를 통과했다. BGRA 네이티브 텍스처는 Qt의 RGBA 전용
  import에서 SRV 생성에 실패하므로 사용하지 않는다.

자막·전환·효과 확장은 위 기본 편집기 완료 기준이 충족될 때까지 보류한다.

## 2026-08-08 인프로세스 미리보기 안정성 기준선

- [x] 기본 `d3d11videosink`·외부 HWND 의존성 제거
- [x] 1280x720 BGRA appsink와 CPU 프레임 메모리 경계 검증
- [x] CPU/D3D 공용 `PreviewVideoFrame`·`VideoPreviewItem` 계약
- [x] 표시 대기 프레임 최신 한 장 병합으로 GUI 큐·메모리 상한 설정
- [x] 실제 노출 창 수신 137·전달 137·표시 136프레임 확인
- [x] CFR MP4·CFR MKV·VFR MKV 4샷에서 CPU BGRA 88프레임 및 오디오 gap 2ms 이하
- [x] 무음 클립의 GES 오디오 효과 금지와 영상/오디오 속도 효과 분리
- [x] 4K 무음 H.264/HEVC 접근 위반 회귀 통과
- [x] 4K CPU BGRA 30초 soak 112 seek, 최대 851.373ms, private 증가 0MiB
- [x] RGBA D3D11 텍스처와 Qt Scene Graph 직접 공유 및 GPU 복사 폴백
- [x] Qt/GStreamer 공유 장치의 D3D11 멀티스레드 보호로 교착·접근 위반 제거
- [x] CFR MP4·CFR/VFR MKV 노출 창 139/139/138 수신·전달·표시 회귀
- [x] 4K H.264/HEVC 노출 창 122/122/122 수신·전달·표시 회귀
- [x] D3D11 기본 경로와 `FFGUI_FORCE_CPU_PREVIEW=1` 폴백 자동 회귀

## 2026-08-08 편집 입출력 가시성 및 진단 복구

- [x] 최신 편집 모델에서 출력 전용 불변 스냅샷 캡처
- [x] 상단 내보내기 단계·파일명·진행률·취소 UI
- [x] FFprobe 영상 스트림·재생시간 후검증 후에만 출력 성공 처리
- [x] 출력 작업별 전체 FFmpeg/FFprobe 로그와 앱 로그 순환
- [x] MP4·CFR MKV·VFR MKV 분석 단계별 시간·실패 로그
- [x] MKV의 `N/A` duration을 스트림/실제 프레임 끝으로 보완
- [x] Windows 파일 드롭 미디어 추가
- [x] 타임라인 12프레임 아틀라스 및 트림 원본 범위 표시
- [x] 시간 눈금 드래그 탐색과 클립 본문 선택·이동·트림의 위치 기반 조작 통합
- [x] Debug 빌드, 코어/타임라인 테스트, 실제 MKV 포함 데스크톱 회귀 통과

## 2026-08-08 정밀 탐색·출력 프리셋

- [x] 고화질·균형·용량 절약 프리셋과 NVENC/CPU별 CQ·CRF·오디오 비트레이트
- [x] H.264·H.265/HEVC·원본 스트림 복사 및 MP4·MKV·MOV 컨테이너 선택
- [x] MP4/MOV의 faststart·hvc1과 MKV 옵션 경계 분리
- [x] 드래그 중 캐시 프레임 즉시 표시, 릴리스 시 한 번의 정확 seek로 탐색 경로 분리
- [x] 프로젝트 시간·실제 PTS 기반 누적 프레임 번호 타임라인 눈금
- [x] 탐색·클립 이동·좌우 트림 중 위치, 프레임 변화량, 초 변화량 피드백
- [x] 실제 HEVC MKV 출력과 FFprobe 코덱 검증 자동 회귀

## 2026-08-08 실시간 탐색·모듈형 인스펙터

- [x] 드래그 중 GES seek 반복 제거와 타임라인 좌표 기반 캐시 프레임 즉시 표시
- [x] 마우스 가운데 드래그, 일반 휠과 Shift+휠 가로 패닝 안내 및 조작
- [x] 출력·오디오·이펙트·전체 트림·출력 설정의 추가/접기/제거 노드 UI
- [x] 모든 클립 앞·뒤 프레임 일괄 트림과 단일 Undo, 원자적 유효성 검사
- [x] 원본/4K/FHD/HD 해상도와 원본/60/30/24 FPS 출력 필터
- [x] 선택 클립 밝기·대비·채도의 GES 미리보기/FFmpeg 출력/프로젝트 저장
- [x] 인접 클립 오버랩 모델과 디졸브 영상·오디오 GES 미리보기/FFmpeg 출력

## 2026-08-09 타임라인 명료화·그래픽 스탬프

- [x] 썸네일 색상 오버레이 제거와 클립 경계·선택 테두리 중심 표시
- [x] 클립 본문 클릭은 선택만 수행하고 시간 눈금에서만 탐색
- [x] 프로그램 모니터 직접 드래그 문구 배치, 크기·시간·좌표 프로젝트 저장
- [x] 영상 비율·크기를 유지하는 상·하단 오버레이 스탬프와 작업자·정보·타임코드
- [x] 자유 문구와 스탬프의 FFmpeg ASS 번인 및 실제 MP4/MKV 회귀
- [x] 자유 문구별 검은 배경 불투명도와 ASS opaque-box 출력
- [x] 스탬프 오버레이/캔버스 확장 모드와 공통 불투명도 UI
- [x] 원본 영상 무축소 `vstack` 확장 및 1280x720→1280x848 실제 출력 검증
- [x] 클립 파일명 헤더·독립 경계·상시 좌우 트림 그립 카드 표시
- [x] 작업 노드 초기 전체 접힘, 단일 펼침 아코디언과 문구·스탬프 기본 제외
- [x] 확장 스탬프 미리보기의 가장자리 픽셀 복제·불투명도·초 단위 타임코드 출력 일치
- [x] VFR/MKV 디졸브 입력의 공통 CFR·timebase·pixel format 정규화와 정지 프레임 회귀
- [x] 하드 컷 경계의 GES 합성기 빈 프레임 억제와 EOS 자동 처음부터 재생

## 2026-08-09 GIF 전용 출력

- [x] MP4/MKV/MOV와 분리된 GIF 컨테이너·파일 대화상자·진행 단계
- [x] 가볍게/균형/부드럽게 프리셋과 크기·FPS·색상·디더링·반복 세부 설정
- [x] GIF 세부 설정의 프로젝트 저장/불러오기와 선택 형식·파일 확장자 일치 보장
- [x] 타임라인 길이 기반 예상 용량 범위와 20MB 주의·50MB 확인 경고
- [x] 오디오 제거 및 `palettegen`/`paletteuse` 2단계 팔레트 최적화
- [x] 480×270·8fps·64색 실제 GIF 출력과 10MB 회귀 상한 검증

## 2026-08-09 CG 미디어·컬러 파이프라인 대개편

고정 원칙: 새 프로젝트와 마이그레이션 프로젝트 모두 `Legacy`가 기본이며, 사용자가
명시적으로 활성화하기 전에는 ACES/OCIO 변환을 적용하지 않는다.

### 완료된 기반

- [x] 프로젝트별 출력 폴더, 최근 폴더 상속, `시퀀스이름_v001` 원자적 자동 증가
- [x] 저장 대화상자 없는 즉시 출력과 출력 노드의 경로 변경·열기·복사·진행 정보
- [x] 프로젝트 v1/v2 → v3 무손실 마이그레이션과 출력/컬러/그레이드 설정 저장
- [x] Video/AnimatedImage/StillImage/ImageSequence 통합 자산 모델
- [x] GIF 실제 FFprobe PTS를 보존하는 VFR 프레임 시간표
- [x] 음수·1001 시작·혼합 범위·누락 프레임 이미지 시퀀스 탐지
- [x] 누락 프레임 미리보기 슬레이트와 출력용 nearest-frame 대체 소스 분리
- [x] 반 해상도 intra H.264 재생 프록시와 원본 해상도 10-bit 4:4:4 출력 소스 분리
- [x] OpenImageIO 3.1/OpenEXR 멀티파트·레이어·AOV·알파 메타데이터 수집
- [x] 선택 part/AOV RGBA를 32-bit float로 읽는 OIIO 프레임 소스와 512MB LRU 캐시
- [x] 선택 part/AOV를 단일 half-float RGBA EXR로 준비해 프록시·혼합 출력 소스에 연결
- [x] EXR part/view/layer/channel을 포함하는 캐시 키로 선택 변경 시 프록시 분리
- [x] 미디어 카드의 EXR part/view/AOV 선택과 기존 클립을 보존하는 비동기 자산 교체
- [x] part별 view/layer/channel 저장·복원과 구 프로젝트 EXR 메타데이터 호환 마이그레이션
- [x] 원본 경로·크기·수정 시각·part/view/channel별 content-addressed EXR 프레임 캐시
- [x] 48프레임 intra 프록시 구간 캐시와 무손실 결합으로 변경 구간만 재인코딩
- [x] 파일 크기·수정 시각 기반 캐시 키와 자산별 증분 무효화 계약
- [x] Deep EXR 명시적 차단과 ACEScg/sRGB 기본 입력 규칙
- [x] OpenColorIO 2.5.2와 ACES 2.0 Studio Config 의존성 잠금
- [x] premultiplied 알파 분리/복원, 입력→ACEScg→그레이드→출력 CPU 기준 렌더
- [x] OCIO D3D11 HLSL·1D/3D LUT texture·binding 추출 및 shader cache ID
- [x] 타임라인 ns→트림/속도/원본 프레임→시퀀스 번호→nearest 누락 대체→float 컬러 처리 서버
- [x] 이미지 시퀀스 정지·스크럽의 float 결과를 프로그램 모니터 CPU 프레임으로 실제 표시
- [x] 빠른 스크럽 최신 요청 병합과 watcher 완료 콜백 직렬화·종료 수명 보장
- [x] 이미지 시퀀스 타임라인의 실제 시간 기반 float 연속 재생·일시정지·끝점 되감기
- [x] 디졸브 양쪽 클립의 컬러 처리 후 선형 합성을 수행하는 공통 타임라인 프레임 서버
- [x] 이미지 시퀀스 컬러 결과를 16-bit RGBA로 FFmpeg에 공급하는 MP4/MOV/MKV/GIF 출력
- [x] float 출력 진행률·취소·NVENC 실패 시 CPU 재시도·ffprobe 결과 검증
- [x] GES 지속 디코더의 RGBA64_LE 일반 영상 프레임 계약과 640×360 컬러 프록시
- [x] 일반 영상·이미지 시퀀스 혼합 타임라인의 비동기 OCIO/GradeGraph 미리보기
- [x] 공통 CPU 컬러 경로를 33³ Cube LUT로 베이크해 일반 영상 GradeGraph 최종 출력
- [x] 클립별 LUT를 scale·디졸브 전에 적용하는 FFmpeg 합성 계약
- [x] 영상·이미지 시퀀스 혼합 출력에서 디졸브·오디오·문구·스탬프 동시 합성
- [x] 출력 중 GES 재구축을 중지해 미리보기 네이티브 그래프와 출력 준비의 경합 제거
- [x] GES 1.28 자동 전환 생성 접근 위반 격리와 충돌 없는 하드컷 fallback
- [x] 별도 GES Effect/Transition 없이 URI 소스 alpha·volume 제어 곡선으로 디졸브와
      gain·mute·fade 미리보기 복구
- [x] Legacy 밝기·대비·채도를 안정적인 top effect로 클립 소스에 적용해 디졸브 전 처리
- [x] 디코더 프레임 최신 요청 병합과 편집 세대가 지난 결과 폐기
- [x] 1280×720→640×360 float 프록시로 Debug 첫 프레임 처리 약 217ms→56ms
- [x] OCIO 구성 캐시·비동기 사전 준비로 ACES 첫 표시 프레임 약 397ms→95ms, 후속 약 83ms
- [x] 노드 파라미터 프레임 단위 컴파일로 640×360 Primary 처리 5초 이상→약 47ms
- [x] Legacy/ACES Managed/Custom OCIO 프로젝트 모델과 HDR 메타데이터 설정 기반
- [x] 클립별 순서형 GradeGraph, 노드 추가·삭제·순서·bypass·mix·기본 파라미터 UI
- [x] 미디어 오프라인·누락·관리형 입력 색공간 미확정 출력 사전 검사
- [x] 미디어 카드에서 OCIO 입력 색공간을 명시적으로 재지정하고 프로젝트에 보존
- [x] 일반 영상의 Legacy GradeGraph와 관리형 컬러를 소스별 33³ RGBA64 LUT로 적용한 뒤 합성
- [x] straight alpha를 보존하는 GStreamer LUT 필터와 전환 양쪽 소스 바인딩 회귀
- [x] 공통 33³ 기준 LUT를 D3D11 3D texture shader로 처리하고 CPU 자동 대체
- [x] GPU 업로드·셰이더·다운로드 RGBA64 경로에서 straight alpha와 소스별 디졸브 검증
- [x] OCIO 동적 HLSL과 1D/2D/3D LUT texture를 D3D reflection으로 실제 slot에 바인딩
- [x] 관리형 입력·출력은 정확한 OCIO shader, 창작용 GradeGraph는 working-space 33³ texture로 분리
- [x] GStreamer C 객체에서 C++ GPU 상태를 분리하고 재협상·프레임 실행을 직렬화해 디졸브 충돌 제거
- [x] 프로그램 모니터 최종 표시 프레임의 Waveform/RGB Parade/Vectorscope/Histogram
- [x] GPU 동일 샘플 비동기 readback·CPU/float 픽셀 재사용과 최신 요청 병합으로 스코프가 재생 그래프를 방해하지 않는 10fps 분석
- [x] 편집 중 이전 seek 실패가 최신 재생 요청을 지우지 않는 세대 기반 재시도
- [x] 개발 Debug EXE의 Qt/GStreamer 런타임 자동 배치와 탐색기 직접 실행
- [x] GES frame-composition 메타를 alpha·위치·크기·z-order로 적용하는 전용 D3D11 mixer
- [x] GPU 컬러 bin 전후의 합성 메타 보존과 NLE gap source로 디졸브·끝점 seek 연속성 보장
- [x] D3D11 compositor 기본 사용과 `FFGUI_FORCE_SYSTEM_COMPOSITOR=1` 진단 fallback
- [x] converter 없는 native GES effect로 source shader texture를 D3D11 compositor에 직접 전달
- [x] D3D11 경로의 Legacy clip controls와 2배속 videorate를 GPU-memory 호환 경로로 통합
- [x] Primary 전체 창작 파라미터, Log Wheels, RGB/Hue Curves, HDR Zones, Color Warper 공통 float 렌더
- [x] 고급 노드의 일반 영상 GPU LUT·이미지 시퀀스 CPU 기준 경로와 편집 UI 연결

### 2026-08-12 단계 마감 기준점

이 표는 UI가 존재하는지보다 실제 미리보기·출력·저장·회귀 검증이 연결되었는지를 기준으로
판정한다. `부분 완료`는 모델이나 일부 렌더 경로만 존재해 원래 완료 조건을 아직 만족하지
못한다는 뜻이다.

| 원 계획 | 상태 | 현재 증거 | 완료를 위해 남은 것 |
| --- | --- | --- | --- |
| M1 출력 워크플로 | 완료 | 프로젝트별 출력 폴더, 최근 경로 상속, 원자적 `v001` 증가, 즉시 출력, 진행률·취소·사전 검사 회귀 | 깨끗한 PC 배포 검증은 최종 릴리스 게이트에서 반복 |
| M2 GIF·스틸·시퀀스 수집 | 부분 완료 | GIF VFR, 스틸·시퀀스, 음수/1001 시작, 누락 대체, EXR part/view/AOV 선택과 저장·복원 | 혼합 자리수·마지막 누락·대규모 드롭 가져오기 전체 매트릭스, ICC/영상 메타데이터 추정 UX |
| M3 프록시·캐시 | 부분 완료 | content-addressed EXR 캐시, 48프레임 증분 프록시, 최신 스크럽 요청 병합 | 사용자 캐시 위치·예상 용량·삭제/재생성 UI, 알파 보존 10-bit 중간 코덱 정책, 4K 100ms 목표 측정 |
| M4 ACES/OCIO | 부분 완료 | Legacy 기본값, OCIO 2.5.2/ACES 2.0, CPU 기준 float 변환, D3D11 OCIO shader와 LUT, 입력 공간 재지정 | 모니터 Display/View 선택, 변환 우회, gamut warning, ACES 적용 전후 비교와 기술 노드 UX |
| M4 HDR10 | 미완료 | 프로젝트 HDR 설정과 메타데이터 저장 계약 | scRGB/PQ swapchain, 모니터 이동 재검사, SDR white 보정, HDR fallback, HDR10 파일 메타데이터 검증 |
| M5 Primary·스코프 | 부분 완료 | Primary 전체 파라미터, RGB Mixer/Curve 공통 렌더와 Waveform/Parade/Vectorscope/Histogram | 스코프 기준점, false color/pixel inspector, parameter keyframe |
| M5 고급 그레이딩 | 부분 완료 | Log Wheels, RGB/Hue 곡선군, HDR Zones, Color Warper, 외부 LUT/Look의 CPU 기준·GPU LUT·UI 연결과 이름·복사·초기화 | 공유 grade, keyframe |
| M6 LUT·Unreal 전달 | 미완료 | 공통 컬러 결과를 내부 33³ LUT로 베이크하는 기반 | 33³/65³ 외부 Cube, shaper, look/display 구분, `.ocioz`, CLF/CTF, manifest, Unreal 사전 검사·실기 검증 |
| R1 네이티브 GPU 프레임 | 완료 | native GES asset/effect, D3D11 source download 0회, VFR·2배속·디졸브·오디오 및 fallback 회귀 | 최종 릴리스 GPU 매트릭스에서 반복 검증 |
| 세컨더리 도구 | 미착수 | 저장·렌더 계약도 아직 확정 전 | qualifier, matte 정리, power window, mask/outside, tracking, shot still, wipe/split, shot matching |
| 최종 품질 게이트 | 미완료 | Debug 자동 회귀와 여러 실제 미디어 smoke/soak 기준선 | 전체 입력 매트릭스, CPU/GPU 수치 비교, HDR 다중 모니터, Unreal 5.5–5.8, 깨끗한 PC 패키지 |

#### 한눈에 보는 현재 상태

- **지금 사용할 수 있는 기반:** 마그네틱 타임라인 편집, 전체 타임라인 재생·탐색, VFR/GIF/스틸/
  이미지 시퀀스/EXR 수집, 프로젝트별 자동 버전 출력, 프록시·썸네일, 문구·스탬프, 기본 컬러와
  고급 GradeGraph, 스코프, D3D11 미리보기와 CPU 대체 경로가 하나의 프로젝트 모델에 연결되어 있다.
- **이번 단계에서 닫은 핵심:** 관리형 컬러를 클립별로 디졸브 전에 적용하면서도 source에서
  compositor까지 D3D11 texture를 유지한다. Primary, Log, RGB/Hue Curves, HDR Zones,
  Color Warper는 공통 float 기준 렌더와 일반 영상용 GPU LUT 경로를 공유한다.
- **아직 완성 제품으로 볼 수 없는 이유:** 파라미터 keyframe·shared grade,
  Display/View 검수 도구, Windows HDR, Unreal 전달 패키지, qualifier·mask·tracking이 남아 있다.
  대규모 입력·깨끗한 PC·여러 GPU·실제 Unreal 버전의 최종 품질 감사도 수행 전이다.
- **재개 지점:** 아래 R2의 파라미터 keyframe과 shared grade부터 시작한다. R2 완료 전에는 HDR나
  세컨더리로 건너뛰지 않으며, 각 단계는 미리보기·출력·저장·undo/redo 회귀가 모두 연결된
  경우에만 완료로 바꾼다.

#### 안정 기준선

- 단계 마감 기준 커밋은 `681c4e8`이다. 이 커밋까지 native D3D11 source color,
  관리형 컬러·디졸브, 고급 GradeGraph, CPU fallback, 데스크톱 smoke와 4K 탐색 soak가
  통과했다. 문서 마감 커밋은 이 기준 위에 문서만 변경한다.
- 첫 `GESBaseEffect` 직접 생성 실험은 asset이 없어 `nleobject`를 만들지 못했다. 최종 구현은
  `GESEffect`의 extractable/asset 계약을 유지한 하위 타입에서 `create_element`만 재정의해
  converter 없는 유효한 `nleoperation`을 생성한다.
- source는 한 번 D3D11에 upload되지만 OCIO/Grade shader 이후 compositor까지 download하지 않는다.
  2배속 `videorate`와 Legacy clip controls도 이 계약 안에서 처리한다.
- 새 작업은 항상 Debug build, CTest, GES GPU/system/CPU 3경로, desktop smoke를 통과한 뒤
  다음 단계로 이동한다. 성능 변경은 4K seek/playback soak 수치도 함께 기록한다.

### 재정비된 구현 순서

#### R1. 네이티브 GPU 프레임 경로 — 완료

- [x] GES의 일반 `GESEffect` converter를 우회하는 asset-backed native effect
- [x] source OCIO/Grade 결과의 D3D11 texture와 composition meta를 compositor까지 유지
- [x] D3D11 source download 0회와 D3D compositor frame 증가 검증
- [x] 디졸브·straight alpha·VFR·2배속·오디오 연속성 회귀
- [x] system compositor와 CPU color fallback 및 전체 desktop smoke 통과

#### R2. 컬러 노드 실행 계약 완성 — 진행 중

- [x] `GradeGraph`의 공간 비의존 노드가 하나의 순서형 float 계약으로 CPU 기준 렌더를 갖는다.
- [x] 같은 파라미터를 OCIO/D3D11 동적 shader 또는 LUT 자원으로 게시해 일반 영상, 이미지
  시퀀스, 미리보기, 최종 출력 사이의 결과를 맞춘다.
- [x] Primary/Log/HDR wheels, RGB/Hue 곡선군, Warper를 공통 렌더와 UI에 연결했다.
- [x] Cube/3DL/CLF/CTF LUT/Look 파일 로더, 파일 검증, float 렌더,
  GPU LUT와 프로젝트 저장을 한 묶음으로 연결한다.
- [x] 노드 초기화·복사·붙여넣기를 기존 타임라인 command와 undo/redo에 통합한다.
- [ ] **다음 재개 작업:** 파라미터 keyframe과 shared grade를 같은 저장 버전으로 묶는다.
- [ ] 각 노드의 bypass/mix/order/keyframe CPU·GPU golden patch 비교를 통과시킨다.

외부 Look은 OpenColorIO `FileTransform`으로 한 번 검증·컴파일해 파일 경로, 수정 시간과 크기로
캐시한다. 작업 색공간의 창작 노드로 적용한 뒤 공통 33³ GPU texture에도 포함하며, 기술적
입력·표시·출력 변환은 프로젝트 컬러 설정으로 분리한다. 파일이 없어지거나 손상되면 출력
사전 검사에서 차단한다. R2는 시간 좌표가 필요한 keyframe과 shared grade가 남아 있어 완료가
아니며, 두 항목과 CPU·GPU golden patch 비교를 끝낸 뒤 R3로 이동한다.

#### R3. 검수용 표시와 스코프

- D3D11 장치 제거를 감지해 현재 GPU 자원을 폐기하고 CPU preview로 복구하며, 사용자에게
  복구 상태를 표시한다. 연속 GPU 회귀 중 `DXGI_ERROR_DEVICE_REMOVED`가 한 차례 관측됐고
  동일 표시 회귀 5회 연속 및 전체 desktop smoke 재실행은 통과했지만 런타임 복구는 아직 없다.
- 스코프 입력을 `그레이드 전`, `그레이드 후`, `디스플레이 변환 후`로 명시적으로 선택한다.
- gamut warning, false color, pixel inspector를 추가하고 SDR/HDR 단위를 분리한다.
- OCIO Display/View, 모니터 ICC, 표시 변환 bypass와 적용 전후 비교를 프로그램 모니터에 연결한다.

#### R4. Windows HDR와 HDR10 출력

- Qt RHI/D3D11에서 16-bit float scRGB를 우선하고 불가능할 때 Rec.2020 PQ 10-bit로 전환한다.
- 창의 모니터 이동 때 HDR 능력과 SDR white level을 재평가하고 SDR tone-map fallback을 표시한다.
- Rec.2100 PQ, mastering display, MaxCLL/MaxFALL을 인코더와 ffprobe 검증까지 연결한다.

#### R5. LUT·Unreal 전달

- 창작용 look만 굽는 33³/65³ Cube와 선택형 shaper를 우선 구현한다.
- 공간·시간 효과 등 3D LUT로 표현 불가능한 노드를 보고하고 내보내기를 차단한다.
- Unreal용 OCIO 2.2 호환 `.ocioz`, 필요한 CLF/CTF/LUT, manifest와 설정 안내를 한 패키지로 만든다.
- Unreal 5.5–5.8에서 차트·회색 램프·고채도 패치와 이중 tone mapping 검사를 통과시킨다.

#### R6. 세컨더리와 샷 관리

- qualifier와 matte, power window/mask/outside, tracking·수동 keyframe 순서로 구현한다.
- shot still, reference wipe, split screen, grade 복사와 기본 shot matching을 추가한다.
- 신경망 Magic Mask, 얼굴 보정, 노이즈 제거, Fusion급 합성은 기존 범위대로 제외한다.

#### R7. 완료 감사와 배포

- 원 계획의 기능·컬러 정확도·HDR·성능·안정성 항목을 요구사항별 증거표로 다시 감사한다.
- CFR/VFR/GIF/PNG/WebP/DPX/EXR과 alpha/multipart/multiview/AOV 실제 미디어를 자동 회귀한다.
- OCIO/OIIO/OpenEXR DLL, ACES config와 GPU/CPU fallback을 깨끗한 Windows PC에서 확인한다.
- 이 단계 전에는 전체 계획을 완료로 표시하거나 정식 릴리스를 만들지 않는다.

### 현재 완료 경계

- Primary exposure/LGG/temperature/tint/contrast/pivot/saturation/hue/color boost, Log Wheels,
  RGB Mixer, master·채널 RGB Curve, 7종 Hue Curve, HDR Zone, Color Warper의 CPU float 처리는
  이미지 시퀀스의 정지·탐색·연속 재생·디졸브·최종 출력에서 같은 프레임 서버를 사용한다.
  일반 영상과 혼합 타임라인 출력은 이 기준 경로를 33³ LUT로 베이크하고 각 클립의
  scale·xfade 전에 적용한다. 따라서 문구·스탬프·레터박스와 편집 오디오도 같은 FFmpeg
  합성 작업에서 함께 출력된다.
- 순수 이미지 시퀀스에 그래픽이 없으면 16-bit 원본 float 프레임 서버를 유지한다.
  혼합 또는 그래픽 출력은 이미지 시퀀스의 10-bit 4:4:4 준비 소스를 사용하므로 EXR 원본
  32-bit 정밀도와 그래픽을 동시에 보존하는 단일 프레임 서버 결합은 아직 남아 있다.
- GES 1.28의 자동/명시적 전환 클립은 빠르게 편집된 오버랩에서 null 네이티브 요소 접근
  위반을 일으킨다. 대신 URI 코어 소스의 alpha와 volume에 원본 PTS 기준 제어 곡선을
  직접 연결해 일반 영상 디졸브와 gain·mute·fade 미리보기를 복구했다. VFR·2배속·오디오
  페이드가 함께 있는 4샷 연속 재생에서 3개 자동화 바인딩, 0ns 최대 오디오 gap을 확인했다.
  Legacy 밝기·대비·채도는 각 소스의 top effect에서 디졸브 전에 처리한다. GradeGraph 또는
  관리형 컬러가 필요한 소스에는 공통 CPU 기준 결과를 33³ LUT로 게시하고 `RGBA64_LE`
  top effect에서 straight alpha를 보존해 적용한다. 따라서 전환 양쪽은 각각 색처리된 뒤
  source alpha로 합성되고, 합성 결과에 활성 클립 컬러를 다시 적용하지 않는다. D3D11이
   가능하면 OCIO가 추출한 입력·출력 HLSL과 LUT texture를 직접 실행하고 창작용 GradeGraph만
   working-space 33³ texture로 적용한다. 사용할 수 없거나 `FFGUI_FORCE_CPU_COLOR=1`이면 전체
   기준 결과를 CPU trilinear 필터로 자동 대체한다. 전용 D3D11 mixer는 GES composition meta를
   sink pad에 적용하고 GPU 색처리 bin이 해당 meta를 PTS별로 복원하므로 4샷·100ms 디졸브·VFR·
   2배속·오디오 연속 재생이 함께 통과한다. NLE gap source도 포함해 끝점의 빈 mixing operation
   오류를 막았다. asset-backed native effect는 일반 `GESEffect`가 넣던 출력 `videoconvert`를
   제거하고 source shader의 D3D11 texture를 compositor에 직접 전달한다. 관리형 4샷 회귀에서
   source download 0회, VFR·2배속·디졸브·오디오 gap 0ns를 확인했다.
- HDR 설정은 프로젝트 계약까지 구현되었고 scRGB/PQ 스왑체인 전환은 미구현이다.
- 자동 또는 사용자가 선택한 EXR part/view/AOV는 float 미리보기와 프록시·혼합 출력에서
  같은 픽셀을 사용한다. 선택은 기존 자산 ID와 타임라인 클립을 보존한 채 백그라운드에서
  교체되며 프로젝트 재로드 후에도 part별 선택지가 복원된다. 정규화 EXR 프레임은 원본
  파일 단위 content-addressed 캐시라 변경되지 않은 프레임을 재사용한다. 재생·출력 프록시도
  48프레임 intra 구간으로 주소화한다. 원본 한 프레임이 바뀌면 해당 구간만 다시 인코딩하고
  나머지 구간은 재사용한 뒤 최종 MKV/MOV를 stream-copy로 빠르게 다시 결합한다.

2026-08-12 단계 마감 재검증은 Debug 전체 빌드, CTest 코어·타임라인 2/2,
GES GPU/system compositor/CPU color 3경로와 전체 desktop smoke를 연속 실행해 모두 통과했다.
GES 회귀는 VFR·2배속·source-alpha 디졸브가 포함된 4샷을 2.325초 동안 재생했고 최대 오디오
gap은 0ns였다. 아래는 이 재검증 이전부터 누적해 유지하는 상세 기준선이다.

검증 기준선: Debug 빌드, 코어 48/48와 타임라인 테스트 통과. 누락 1장을 포함한
1001–1048 PNG 시퀀스를 별도 환경 변수 없이 Debug EXE에서 가져와 프로젝트 v3
저장·재로드했으며 `proxy-v4.mkv`와 `export-nearest-v3.mov` 생성을 확인했다.
일반 영상 3개 출력은 5.968초 MP4, 1280×848 확장 스탬프, 영상·오디오 스트림과
변화하는 300ms 디졸브 프레임을 확인했다. 일반 영상+누락 PNG 시퀀스+VFR MKV 혼합
출력도 5.926초 MP4, 영상·오디오, 확장 스탬프와 컬러 LUT를 포함해 통과했다.
2프레임 EXR 시퀀스에서 part/view/AOV 비동기 재선택, 클립 ID 보존, 프로젝트 저장·재로드와
선택지 복원을 자동 검증했다. 멀티파트 EXR의 view별 픽셀 선택과 불일치 view 차단도 통과했다.
96프레임 EXR에서 50번 프레임만 변경했을 때 재생·출력 프록시 모두 첫 48프레임 구간을
재사용하고 두 번째 구간만 새 주소로 생성하는 증분 캐시 회귀도 통과했다.
색공간 메타데이터가 없는 MP4/MKV/VFR 자산 3개에 사용자가 `Camera Rec.709`를 지정한 뒤
ACES Managed 미리보기를 재구축해 소스 LUT 3개가 합성 전에 연결되고 post-composite float
처리가 0회인 상태로 연속 재생되는 데스크톱 회귀도 통과했다.
D3D11 3D LUT 경로는 반투명 RGBA64 테스트 픽셀과 관리형 4샷 타임라인에서 모두 통과했다.
동일한 Debug GES 회귀의 BGRA 전달량은 CPU LUT 약 25프레임에서 GPU LUT 약 85프레임으로
증가했으며, GPU 강제 비활성화 시 같은 결과를 내는 CPU fallback도 별도로 통과했다.
프로그램 모니터 스코프를 켠 D3D11 데스크톱 회귀에서는 5초 동안 GPU 프레임 117개를
컨트롤러에 전달하면서 38개를 분석했고 Qt Scene Graph 표시까지 통과했다. 스코프를 닫은
기본 재생, 스코프를 연 D3D11 표시와 CPU BGRA fallback을 포함한 전체 데스크톱 회귀도 통과했다.
전용 D3D11 mixer를 기본으로 전환한 뒤 GPU/CPU GES 회귀, 관리형 컬러 데스크톱 회귀,
프로젝트·EXR·MP4/GIF/HEVC/stream-copy 출력, D3D11/CPU Qt 표시와 10초 4K 탐색 반복도 통과했다.
