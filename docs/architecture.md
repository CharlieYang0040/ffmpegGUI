# 아키텍처

## 단일 원본

`TimelineModel`이 편집 결과의 단일 원본이다. Qt UI, GES 미리보기와 FFmpeg 출력은
모두 불변 스냅샷인 `TimelineSpan` 목록을 소비한다. 외부 엔진 객체를 프로젝트
상태로 저장하지 않는다.

```text
TimelineModel
  ├─ MediaAsset: 경로, 길이, 실제 프레임 PTS
  ├─ Clip: asset, source-in, source-duration, playback-rate, gain/mute/fades
  └─ CaptionCue: sequence-in, duration, UTF-8 text
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
- 타임라인 길이는 각 클립의 `source-duration / playback-rate` 합이다.
- 단일 트랙은 항상 마그네틱하다. 일반 클립 사이에 암묵적 gap을 저장하지 않는다.
- 화면 프레임 번호와 타임코드는 프로젝트 표시 FPS에서 파생하며 저장 좌표로
  사용하지 않는다.
- 좌우 프레임 이동은 고정 FPS 간격을 더하지 않는다. 현재 클립의 `MediaAsset` 실제
  PTS에서 다음·이전 값을 찾고, 트림 끝에서는 정확한 마그네틱 컷 경계로 이동한다.
- 타임라인 seek와 scrub은 연속 나노초 좌표를 허용하지만 구조 편집은 다르다. 트림과
  분할을 커밋할 때 원본의 가장 가까운 실제 프레임 PTS 또는 미디어 끝 경계로 스냅해
  프레임 사이에 저장된 컷이 생기지 않는다. 같은 프레임 범위로 다시 스냅된 no-op
  트림은 새 undo 리비전을 만들지 않는다.
- 미디어 보관함의 샷을 컷 경계에 놓으면 그 경계에 바로 삽입한다. 기존 샷 내부에
  놓으면 실제 프레임 경계로 위치를 맞춘 뒤 기존 샷을 좌우로 나누고 가운데에 새 샷을
  넣는다. 이 세 변화는 하나의 원자적 편집이므로 Undo 한 번으로 원래 샷으로 돌아간다.
- Ctrl 선택은 떨어진 샷을 추가·제거하고 Shift 선택은 기준 샷부터 연속 범위를 만든다.
  선택된 여러 샷의 삭제는 존재 여부를 모두 먼저 검증한 다음 한 번에 적용한다. 중간에
  잘못된 ID가 있으면 아무 샷도 지우지 않으며, 성공한 묶음 삭제는 Undo 한 번으로 모두
  복원되고 남은 샷은 자동으로 붙는다.
- 여러 샷 복제는 원래 타임라인 순서로 복사본을 만든 뒤 선택 범위의 마지막 샷 뒤에
  한 묶음으로 삽입한다. 복사본 ID와 원본 범위를 모두 검증한 후 한 번에 적용하므로
  부분 복제 상태가 생기지 않고 Undo 한 번으로 전체 복사본을 제거한다.
- 선택 묶음을 드래그하면 선택된 샷과 남은 샷의 상대 순서를 각각 보존한 채 하나의
  삽입 위치로 이동한다. 드롭 위치는 선택 샷을 제외한 목록 기준으로 계산해 앞·뒤 이동의
  의미가 같으며, 결과 순서가 기존과 같으면 새 편집 리비전을 만들지 않는다.
- 인·아웃 마커는 연속 seek 좌표를 실제 VFR 프레임 경계로 스냅해 저장한다. 표시 구간
  리플 삭제는 범위 안의 샷을 제거하고 양 끝 샷의 남은 원본 범위만 보존한다. 한 샷
  내부 범위라면 오른쪽 조각에 새 ID를 부여하며, 전체 변경은 원자적으로 검증한 뒤
  Undo 한 단계로 기록한다.
- 클립 오디오 설정은 선형 gain, 음소거, 나노초 페이드 인·아웃으로 저장한다. 다중 선택
  변경은 하나의 편집 리비전이며, 분할 시 새 내부 컷에는 페이드를 만들지 않고 원래
  클립의 바깥쪽 페이드만 좌우 조각에 보존한다. 트림으로 두 페이드의 합이 클립보다
  길어지면 재생과 출력 모두 같은 비율로 축소해 클립 경계 안에 맞춘다.
- 재생 속도는 0.25~4.0 배율로 저장한다. 클립의 원본 범위는 바꾸지 않고 원본 오프셋과
  시퀀스 오프셋을 배율로 양방향 변환한다. 트림·분할·VFR 프레임 이동은 이 변환을 거쳐
  항상 원본 프레임 경계에 확정되며, 여러 선택 샷의 속도 변경과 뒤 자막 리플 이동은
  하나의 undo 단계다.
- 문구 그래픽은 원본 클립 시간이 아닌 시퀀스 나노초 범위와 0~1 정규화 화면 좌표에 놓인다. 리플 삭제에 완전히 포함된
  자막은 제거하고, 경계에 걸친 자막은 남은 부분으로 자르며, 뒤 자막은 삭제 길이만큼
  당긴다. 시간 삽입은 해당 위치 이후 자막을 밀어낸다. 클립과 자막을 하나의 편집 상태로
  저장하므로 Undo/Redo에서 영상만 돌아가 자막이 어긋나는 중간 상태가 생기지 않는다.
- 프로그램 모니터의 문구 드래그는 QML 레이어에서 즉시 움직이고 놓을 때만 정규화 좌표를
  `TimelineModel::update_caption` 한 번으로 확정한다. GES 영상 그래프를 재구성하지 않아
  문구 이동 중 재생·탐색 파이프라인을 방해하지 않는다.
- SRT 입출력은 Qt UI와 분리된 코어 파서가 담당한다. UTF-8 BOM, CRLF/LF, 여러 줄 텍스트,
  쉼표 또는 점 밀리초를 읽고, 출력은 CRLF와 쉼표 밀리초의 표준 형태로 정규화한다.
  가져온 자막 묶음은 전체 검증 뒤 하나의 편집 상태로 추가한다.

## 스레드 경계

- UI 스레드는 편집 명령을 적용하고 작은 모델 스냅샷을 게시한다.
- GStreamer는 전용 GLib 컨텍스트 스레드에서 동작한다.
- FFmpeg 출력은 별도 프로세스로 실행해 충돌과 취소를 격리한다.
- 썸네일·파형·PTS 분석은 제한된 작업 큐에서 수행한다.
- 기본 경로는 1280x720 RGBA D3D11 appsink 텍스처를 Qt Scene Graph와 직접 공유한다.
  공유 조건을 충족하지 않는 GPU 텍스처만 같은 장치의 표시용 텍스처로 복사하며,
  `FFGUI_FORCE_CPU_PREVIEW=1`일 때는 BGRA CPU 버퍼 업로드 경로를 사용한다.
- 프레임에는 GStreamer PTS를 함께 전달해 seek 이전 큐의 프레임과 현재
  타임라인 위치의 프레임을 구분한다.
- 파이프라인 상태와 사용자 콜백은 별도 mutex로 보호한다. 따라서 stopped 상태의
  초기 preroll과 paused seek의 `ASYNC_DONE`을 기다리는 동안에도 appsink가
  프레임을 전달할 수 있다. `seek()`는 paused 화면에 요청 위치의 프레임이 준비되기
  전에 성공으로 반환하지 않는다.
- GStreamer 스레드는 프레임마다 GUI 이벤트를 무제한 추가하지 않는다. 전달 대기 중인
  프레임은 최신 한 장으로 교체하고 Qt 이벤트는 최대 하나만 예약한다.

## 의존성 원칙

`src/core`는 Qt, GStreamer와 FFmpeg 헤더를 포함하지 않는다. 통합 코드는 어댑터
계층에만 위치한다. 따라서 편집 규칙은 빠른 단위 테스트로 검증할 수 있고 미디어
엔진을 교체해도 프로젝트 포맷과 실행 취소 기록을 유지할 수 있다.

## 현재 미리보기 경로

`TimelineModel::snapshot()`은 트림된 원본 경로와 시퀀스 구간을 포함한다. GES
어댑터는 이 스냅샷 전체를 하나의 `GESTimeline`으로 만들기 때문에 UI에서 선택한
클립 하나가 아니라 편집 결과 전체가 재생된다. Qt의 재생 헤드는 GStreamer 재생
시계를 따라가며 seek 또한 항상 시퀀스 나노초 좌표를 사용한다.

디졸브는 뒤 클립의 `transition_in`에 저장한다. `TimelineModel::snapshot()`은 그 길이만큼
뒤 클립의 시작을 앞으로 당겨 두 `TimelineSpan`을 겹치고, 전체 시퀀스 길이와 원본 프레임
매핑도 같은 겹침을 반영한다. 겹침 구간의 편집 좌표는 화면 위에 놓이는 뒤 클립을
우선한다. GES 자동 전환 객체는 사용하지 않고 뒤 URI 소스의 core video `alpha`에
원본 PTS 기준 0→1 선형 제어를 연결한다. 따라서 네이티브 전환 객체 없이 겹친 앞 영상을
배경으로 유지하면서 디졸브한다.

현재 기본 영상 출력은 `d3d11upload ! d3d11convert ! RGBA D3D11 appsink`이며 별도
네이티브 `QWindow`, HWND와 `d3d11videosink`를 사용하지 않는다. Qt와 GStreamer가 같은
D3D11 장치를 쓰고 멀티스레드 보호를 켠 상태에서 셰이더 리소스 텍스처를 Scene Graph에
직접 전달한다. 실제 노출 창 회귀에서 CFR MP4·CFR MKV·VFR MKV는 수신 139·전달 139·
표시 138프레임, 4K H.264/HEVC는 수신·전달·표시 122프레임을 확인했다.

`FFGUI_FORCE_CPU_PREVIEW=1`은 드라이버·원격 데스크톱 호환성 진단을 위한 안전 경로다.
이 모드도 실제 노출 창에서 CPU BGRA 프레임 표시를 별도로 회귀한다.

GradeGraph 또는 관리형 컬러가 필요한 일반 영상은 입력→working space→GradeGraph→표시 변환을
소스별 `RGBA64_LE` top effect에서 수행한다. 관리형 GPU 경로는 OCIO 2.5가 생성한 입력·출력
HLSL과 1D/2D/3D LUT texture를 그대로 컴파일하고, D3D reflection으로 실제 texture·sampler
slot을 바인딩한다. 현재 창작용 GradeGraph만 working-space 33³ texture로 평가한다. straight
alpha는 shader 밖에서 보존한다. 이후 source alpha 디졸브가 수행되므로 서로 다른 두 샷의 색이
합성 전에 독립적으로 처리되며 합성 결과를 다시 그레이드하지 않는다. GPU 생성이나 협상이
불가능하면 입력·GradeGraph·출력 전체를 평가한 33³ CPU 기준 경로를 사용한다. Legacy GradeGraph도
같은 cube 경로를 사용하고, 컬러 처리가 없는 타임라인은 기존 D3D11 texture 공유 경로를 유지한다.
시스템 합성 경로의 Legacy 밝기·대비·채도는 `GESClip`의 안정적인 top `videobalance` effect로
적용한다. D3D11 합성 경로에서는 같은 조절을 `compose_clip_grade()`에 합쳐 source GPU LUT에서
처리하므로 CPU 전용 effect로 되돌아가지 않는다.
영상 트랙은 GES의 고정 system compositor 대신 전용 `FfguiD3DVideoTrack`과
`d3d11compositor`를 기본 사용한다. 전용 mixer는 각 입력 버퍼의 GES frame-composition
메타데이터를 D3D11 sink pad의 alpha·위치·크기·z-order에 적용한다. GPU 색처리 도중 손실될 수
있는 이 메타데이터는 `ffguid3dcolor` bin이 입력 PTS별로 보존했다가 shader 출력에 복원하므로
서로 다른 그레이드의 두 샷도 디졸브 값이 유지된다.

일반 `GESEffect`는 영상 effect 앞뒤에 `videoconvert`를 자동 삽입해 system-memory 협상을
유발한다. D3D11 경로는 이를 사용하지 않고 `GESEffect`의 extractable/asset 수명주기를 따르는
`FfguiDirectD3DEffect`가 converter 없는 `nleoperation`을 만든다. 색처리 bin은 최초 source
upload와 shader만 포함하고 그 출력 texture를 compositor에 직접 전달한다. 2배속의 `videorate`도
`video/x-raw(ANY)`를 지원하는 같은 native effect로 연결한다. 결과적으로 source color effect의
`d3d11download` 인스턴스는 0개다. 시스템 compositor 또는 CPU color를 강제하면 기존
`GESEffect`와 download 경로로 자동 복귀한다.

컷 사이의 짧은 공백에는 D3D11 black gap source를 공급해 NLE mixing operation이 자식 없이
seek되는 오류를 막는다. 문구와 스탬프는 현재 Qt overlay에서 미리보고 FFmpeg 공통 출력 그래프에서
렌더하므로 GES title source를 D3D 트랙에 혼합하지 않는다. 문제가 있는 드라이버에서는
`FFGUI_FORCE_SYSTEM_COMPOSITOR=1`로 기존 합성기를 강제할 수 있다.

GradeGraph의 공간 비의존 기준 렌더는 `apply_grade_graph_rgba32f()` 하나로 유지한다. 현재
Primary exposure/LGG/temperature/tint/contrast/pivot/saturation/hue/color boost, Log Wheels,
RGB Mixer, master·채널별 RGB Curves, Hue vs Hue/Sat/Lum과 Lum/Sat 교차 곡선, scene-linear
HDR zone exposure, Hue-Sat/Luma Color Warper가 이 경로를 사용한다. 이미지 시퀀스는 float
프레임에 직접 적용하고 일반 영상은 같은 함수를 33³ working-space cube로 평가해 D3D11
source shader에 게시한다. 외부 Cube/3DL/CLF/CTF Look도 OCIO `FileTransform`으로 검증·컴파일해
같은 노드 순서에서 실행한다. 프로세서는 정규화 경로·수정 시간·파일 크기로 캐시하며 파일이
바뀌면 다시 컴파일한다. 파일 경로는 UTF-8로 프로젝트에 저장하고, 누락·손상된 Look은 렌더
사전 검사에서 `offline-grade-lut` blocker로 보고한다. 노드 복사·붙여넣기와 초기화는 모두
`TimelineModel::set_clip_grade_graph()` 한 단계 편집이므로 기존 undo/redo와 리비전 계약을 따른다.
qualifier와 power window는 공간 마스크 계약이 생기기 전까지
명시적으로 render unsupported 상태를 유지한다.

구조 편집은 `TimelineModel`과 Scene Graph 화면에 즉시 반영하지만 GES 파이프라인은
각 마우스 동작마다 다시 만들지 않는다. 50ms 단일 타이머가 연속 편집을 최신 스냅샷
하나로 합치며, 사용자가 그 전에 seek 또는 재생을 요청하면 타이머를 취소하고 최신
세대를 즉시 적용한다. 모델 리비전은 출력 일치 검사에, 별도 게시 세대는 프로젝트를
바꿔 불러온 경우까지 포함한 미리보기 적용 여부에 사용한다.

그레이드 파라미터, 노드 순서, 클립 밝기·대비·채도는 구조가 같으면 GES 그래프를
파괴하지 않는다. 소스 LUT/OCIO 셰이더는 클립 ID로 고정되고, 필터는 프레임마다
게시된 큐브를 다시 읽는다. 따라서 재생 중에 컬러를 조절해도 파이프라인 preroll이나
UI 워치독 지연이 발생하지 않는다. 효과가 새로 필요하거나 사라진 경우에만 전체
재구축으로 폴백한다. 연속 그레이드 조절은 350ms 동안 하나의 undo 단계로 합친다.

GES 파이프라인 생성, paused 준비, 정확 seek와 재생 상태 전환은 Qt UI 스레드에서 직접
기다리지 않는다. 컨트롤러의 단일 비동기 작업 슬롯에서 순서대로 실행하며 작업 중 들어온
scrub·편집 요청은 마지막 위치와 최신 타임라인 세대로 합친다. 이전 세대 작업이 끝나도
현재 세대가 아니면 즉시 최신 스냅샷을 준비한다. 같은 세대의 준비 실패는 무한 재시도하지
않고 오류 상태로 남겨 UI가 살아 있는 상태에서 다음 사용자 요청으로 복구할 수 있게 한다.
드래그 scrub 중에는 GES seek를 반복하지 않는다. 현재 시퀀스 좌표를 원본 좌표로 매핑한
뒤 12프레임 아틀라스에서 가장 가까운 CPU 프레임을 즉시 프로그램 모니터에 제출한다.
마우스를 놓은 마지막 위치에서만 `ASYNC_DONE`까지 기다리는 정확 seek를 한 번 수행해
실제 디코딩 프레임으로 교체한다. 따라서 드래그 속도와 디코더 preroll 성능이 분리되고
겹친 seek로 `GES timeline seek failed`가 발생하지 않는다. 타임라인 눈금과 편집 피드백의 프레임 번호는 고정 FPS 환산이 아니라
각 클립의 FFprobe PTS와 트림·속도 매핑을 누적해 계산한다.

현재 GES 미리보기 출력 프로필은 1280x720 RGBA D3D11이다. 4K H.264/HEVC 원본은 선택된
디코더가 원본 해상도로 해제하고 미리보기 합성 단계에서 축소한다. CPU appsink 30초
soak는 112회 PTS 일치 seek, 최대 851.373ms, 측정 구간 private memory 증가 0MiB를
확인했다. CPU BGRA 30초 soak도 112회 PTS 일치 seek, 최대 851.373ms, 메모리 증가
0MiB로 폴백 기준선을 유지한다.

`TimelineSpan::has_audio`는 분석된 자산의 실제 오디오 존재 여부를 전달한다. 속도 변경은
영상 `videorate`, 오디오 `pitch`로 분리하며 영상만 있는 클립에는 오디오 자동화를 만들지
않는다. gain·mute·클립 fade와 전환 crossfade는 core audio source의 `volume`에 원본 PTS
기준 선형 제어를 연결한다. 효과의 동적 자식을 사용하지 않아 빠른 재구축 수명 문제를 피한다.

## 타임라인 시각 캐시

미디어를 가져올 때 FFmpeg가 원본 전체에서 최대 12프레임을 뽑아 하나의 PNG
아틀라스로 캐시한다. 캐시 키는 정규화된 파일 경로, 크기와 수정 시각으로 만들어
원본이 바뀌면 자동으로 새 아틀라스를 사용한다. QML 이미지 계층과 C++ Scene Graph
타임라인은 같은 viewport 나노초 좌표를 공유한다. 따라서 확대·스크롤·트림 뒤에도
현재 클립의 `source-in`과 길이에 해당하는 아틀라스 영역만 표시된다.

클립·파형·트림 핸들은 정적 Scene Graph 레이어에 보관하고 재생 헤드는 별도 동적
레이어로 갱신한다. 재생 중 `playhead`만 변할 때는 정적 지오메트리를 삭제하거나 다시
할당하지 않는다. 클립 편집, 선택, 확대·스크롤, 크기 변경이 있을 때만 정적 레이어를
다시 만든다. 1,000클립 자동 검사는 600회 재생 헤드 갱신 동안 같은 정적 노드를
재사용하는지 함께 검사한다.
클립 본체, 파형, 선택·hover와 트림 핸들은 가시 구간만 C++ Scene Graph에서 만든다.
썸네일은 동일 viewport 좌표를 쓰는 별도 이미지 계층에서 캐시 아틀라스의 source-in 범위를
잘라 표시한다. 파형 QVariant 데이터는 미디어 자산별로 한 번 변환한 뒤 공유한다.
타임라인 리비전 신호가 새 목록의 발행 여부를 이미 보장하므로 `QVariantList` 전체를
다시 깊게 비교하지 않는다. 이 비교는 각 클립에 공유된 파형 표본까지 순회해 큰 프로젝트의
UI 스레드를 멈출 수 있다. 2초 이상 UI heartbeat가 갱신되지 않거나 Scene Graph·뷰 모델
재생성이 50ms를 넘으면 영구 로그에 구간명과 소요 시간을 기록한다.

## 출력 작업

출력 시작 시점에 현재 `TimelineModel`에서 불변 `TimelineSpan` 스냅샷을 직접 캡처한다.
미리보기 준비는 비동기이므로 그 성공·실패나 이전 게시 리비전이 최신 편집의 출력을
막거나 오래된 샷을 출력 기준으로 만들지 않는다. 출력 컴파일러는 이 스냅샷의 각 클립
`source-in`과 길이를 나노초 정밀도 FFmpeg 입력 범위로 변환한다. 영상과 48kHz 오디오는 클립 순서대로
하나의 필터 그래프에서 연결하며, 오디오가 없거나 짧은 샷은 정확한 샷 길이만큼
무음으로 보완한다. 출력 프리셋은 화질(`high`, `balanced`, `compact`), 코덱(H.264,
HEVC, 안전할 때 stream-copy), 컨테이너(MP4, MKV, MOV), 해상도와 FPS를 독립 축으로 유지한다.
NVENC 실패 시 선택한 코덱의 CPU 인코더로만 전환하며 MP4/MOV 전용 `faststart`·`hvc1`
옵션은 Matroska에 전달하지 않는다. 취소·실패 시 불완전 출력은 삭제하고 기존 파일은
자동으로 덮어쓰지 않는다.
클립 gain·음소거·페이드는 FFmpeg `volume`/`afade` 필터로 최종 출력에 컴파일한다.
GES 1.28 URI 클립의 동적 `volume` 자식은 빠른 그래프 재구축 중 미해결 객체가 될 수 있어
미리보기에서는 적용하지 않는다. 오디오 효과가 하나라도 있으면 stream-copy 조건에서 제외한다.
클립 속도는 GES `pitch tempo` 효과로 미리보고, FFmpeg에서는 영상 `setpts`와 오디오
`atempo` 체인으로 컴파일한다. 0.25배처럼 단일 `atempo` 범위를 벗어나는 값은 여러
필터로 나누며 속도 변경이 있는 출력은 stream-copy 조건에서 제외한다.
클립 밝기·대비·채도와 GradeGraph는 공통 float 처리기로 미리보고, 최종 출력에서는 같은
처리 결과를 33³ Cube LUT로 베이크해 클립 입력에 적용한다. 색변환이 없는 단순 Legacy
출력만 FFmpeg `eq` 빠른 경로를 사용할 수 있다.
해상도 변경은 비율 유지 scale/pad, FPS 변경은 `fps` 필터로 컴파일하며 이 변환이나
색보정이 하나라도 있으면 stream-copy 조건에서 제외한다.
디졸브는 FFmpeg 영상 `xfade`와 오디오 `acrossfade`로 컴파일한다. 클립 LUT는 scale과
`xfade`보다 먼저 실행되어 양쪽 샷이 각각 색처리된 후 합성된다. 각 전환의 offset은
앞에서 이미 합성한 길이에서 현재 겹침을 뺀 시퀀스 좌표이며, 전환이 하나라도 있으면
stream-copy 대신 재인코딩한다. `xfade` 전에는 MKV/VFR을 포함한 각 영상 입력을 공통
CFR(사용자 지정 FPS, 미지정 시 전환 합성용 30fps), AVTB, 0 기반 PTS와 `yuv420p`로
정규화하고 정확한 타임라인 길이로 다시 자른다. 마지막 프레임 한 장을 보강한 뒤 재트림해
짧은 입력 EOF 때문에 전환 구간 전체가 정지 프레임으로 채워지지 않게 한다.
GES 1.28의 자동 전환과 명시적 `GESTransitionClip`은 빠른 오버랩 재구축에서 네이티브
접근 위반이 재현되어 비활성화했다. 일반 영상 미리보기는 URI source alpha 제어로,
이미지 시퀀스 float 미리보기와 최종 출력은 공통 모델의 디졸브를 직접 계산한다.
자유 문구는 출력 시 정규화 좌표를 1280x720 ASS 기준 좌표로 바꿔 UTF-8 스크립트에
컴파일하고 FFmpeg `ass` 필터로 번인한다. 문구의 검은 배경 불투명도는 문구별 ASS opaque-box
스타일로 컴파일한다. 스탬프 오버레이 방식은 ASS 도형을 영상 위에 합성해 해상도를 유지한다.
확장 방식은 원본 영상 가장자리 띠를 복제하고 검은색을 지정 불투명도로 합성한 뒤
`vstack`으로 위·아래에 붙인다. 예를 들어 1280x720 영상에 9% 바를 적용하면 중앙 영상은
그대로 두고 64픽셀씩 추가한 1280x848 출력이 된다. 확장된 ASS PlayResY와 문구 Y 오프셋도
같이 조정해 화면 배치가 어긋나지 않는다. 작업자·영상 정보와 초 단위 타임코드 이벤트를
함께 만들며 미리보기는 Qt 레이어가 담당한다. GES `GESTextOverlayClip`은 정확 seek 중
`NleComposition` 연결을 잃는 오류가 있어 기본 영상 그래프에서 계속 격리한다. 문구나
스탬프가 있는 출력은 stream-copy를 사용하지 않는다.

GIF 출력은 일반 영상 인코더와 무손실 복사 경로에서 완전히 분리한다. 최종 합성 영상에
선택 FPS와 고정 캔버스를 적용한 뒤 두 갈래로 나눠 한쪽에서 `palettegen`으로 최대 색상 수를
제한한 팔레트를 만들고, 다른 쪽에 `paletteuse`로 적용한다. Bayer는 규칙적 디더링과
`diff_mode=rectangle`로 변화 영역을 제한해 용량 예측성을 우선하고, Sierra는 그라데이션
품질을 우선한다. GIF muxer에는 오디오를 매핑하지 않으며 `loop=0`은 무한 반복,
`loop=-1`은 한 번 재생으로 컴파일한다. UI의 용량 표시는 픽셀 수×FPS×길이에 색상 수와
디더링 계수를 적용한 보수적 범위이며 실제 장면 변화량에 따라 달라진다는 점을 항상 표시한다.

EXR 시퀀스는 선택한 part와 RGBA 채널 매핑을 OpenImageIO로 읽어 캐시 안의 단일
half-float RGBA EXR로 정규화한다. FFmpeg 프록시와 혼합 출력은 원본의 기본 part가 아니라
이 준비 프레임을 사용한다. 캐시 키에는 part, view, layer, 네 채널 매핑과 각 원본 프레임의
크기·수정 시각이 포함되어 다른 AOV 결과가 같은 프록시를 공유하지 않는다.
미디어 카드의 part/view/AOV 변경은 새 클립을 만들지 않고 같은 자산 ID를 비동기로 교체한다.
교체 전 모든 기존 클립의 소스 범위를 검증하고 실패하면 기존 자산을 그대로 유지한다.
part별 view/layer/channel 목록도 프로젝트에 저장한다. 정규화 프레임은 원본 파일의 경로,
크기, 수정 시각과 선택 채널로 주소화해 시퀀스의 다른 프레임이 바뀌어도 재사용한다.
재생·출력 프록시는 48프레임 단위 intra 구간으로 인코딩한다. 구간 키는 실제 입력 프레임,
누락 슬레이트 정책, 해상도, FPS, 픽셀 형식을 포함한다. 변경된 원본이 속한 구간만 새로
인코딩하며 최종 MKV/MOV는 캐시 구간들을 재인코딩 없이 concat하여 기존 단일 파일 소비자와
호환한다.

GES appsink가 길이 0인 하드 컷 시점에 합성기 배경 한 프레임을 내보낼 수 있으므로 재생
중 정확한 컷 시점의 프레임은 표시하지 않고 직전 정상 프레임을 다음 클립 프레임까지 유지한다.
정지 탐색에는 이 가드를 적용하지 않아 컷 위치 seek 결과는 그대로 갱신한다. EOS에서는
위치 콜백을 먼저 타임라인 끝으로 확정하고, 재생 의도가 유지된 경우 컨트롤러가 0으로 seek해
전체 시퀀스 재생을 즉시 이어 간다.

같은 원본 파일에서 나온 모든 컷의 시작과 끝이 실제 영상 키프레임 PTS 또는 원본
끝에 정확히 맞으면 concat demuxer와 `-c copy`로 재인코딩 없이 remux한다. 서로 다른
원본, 비키프레임 경계, 키프레임 정보가 없는 예전 프로젝트는 이 최적화를 사용하지
않는다. 무손실 remux 자체가 실패해도 결과를 성공으로 오인하지 않고 NVENC, libx264
순서로 안전하게 다시 시도한다.

## 공유 그레이드와 파라미터 키프레임

프로젝트 형식 v4의 `GradeNode`는 선택적인 `sharedId`와 파라미터별 `sourceTimeNs` keyframe을
저장한다. 공유 노드의 이름, 활성화, 혼합, 정적 파라미터와 곡선은 같은 `sharedId`를 가진 모든
클립에 하나의 타임라인 편집 명령으로 전파된다. 각 클립 인스턴스의 노드 ID와 keyframe은
보존하므로 한 샷의 애니메이션이 다른 샷으로 새지 않으며, 한 번의 undo/redo가 공유 편집 전체를
복원한다.

keyframe 시간은 시퀀스 시간이 아니라 트림과 재생 속도를 반영한 원본 미디어 시간이다. 공통
float 처리기는 인접 keyframe을 선형 보간한다. 이미지 시퀀스 프레임 서버는 이 시간을 미리보기와
최종 출력에 동일하게 전달한다. 일반 영상의 GES GPU 경로는 아직 프레임별 grade 갱신을 지원하지
않으므로 UI에서 keyframe 생성을 제공하지 않으며, 저장된 데이터가 있으면 출력 사전 검사에서
차단해 정적 LUT로 잘못 렌더하지 않는다.
FFmpeg 종료 코드 0 이후에도 FFprobe JSON으로 영상 스트림 존재 여부와 예상 타임라인
재생시간 오차를 검사한다. 검증 실패 파일은 삭제하며, 작업별 전체 stderr와 검증 JSON은
앱 데이터의 `logs/export-*.log`에 남긴다.

## 프로그램 모니터 컬러 스코프

Waveform, RGB Parade, Vectorscope, Histogram은 프로그램 모니터에 실제로 전달된
display-referred 프레임을 공통 `ScopeAnalyzer`로 분석한다. CPU BGRA, GPU RGBA와 float
입력은 채널 순서만 정규화하고 같은 누적기를 사용하므로 같은 픽셀은 같은 결과를 만든다.
D3D11 경로는 스코프용 `tee`나 보조 sink를 재생 그래프에 추가하지 않는다. Qt에 전달되는
같은 `GstSample`의 수명을 공유하고 최대 10fps만 작업 스레드에서 system-memory map하여
메인 appsink의 재생 시계, 프리롤과 프레임 전달률을 보존한다. 분석이 늦으면 대기열을
쌓지 않고 최신 프레임 하나로 교체한다. CPU 및 float 프레임은 이미 독립 복사된 픽셀을
재사용한다. 패널이 닫혀 있을 때는 GPU readback과 분석을 모두 중단한다.

## 편집 리비전과 작업 격리

성공한 구조 편집, undo와 redo는 `TimelineModel` 리비전을 증가시킨다. 컨트롤러는 GES
미리보기용 스냅샷과 출력용 스냅샷을 각각 작업 시작 시점에 고정한다. 따라서 미리보기
파이프라인 준비가 뒤처져도 최신 모델을 출력할 수 있고, 출력 도중 다음 편집을 하더라도
이미 시작한 작업의 클립 순서와 원본 범위는 변하지 않는다.

테스트용 GES 오디오 `fakesink`는 각 버퍼의 PTS와 duration을 직접 기록한다. seek의
영향을 제거한 전체 시퀀스 재생에서 이전 버퍼 끝과 다음 버퍼 시작의 양의 차이를
측정하므로, 재생 헤드가 단순히 끝에 도달한 것만으로 오디오 연속성을 통과시키지
않는다. 현재 CFR/VFR 혼합 4샷 기준 272개 버퍼의 최대 양의 gap은 0ns다.
