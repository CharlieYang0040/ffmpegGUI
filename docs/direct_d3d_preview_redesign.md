# 격리형 Direct D3D11 미리보기 재설계

## 목표

직접 D3D11 compositor의 GPU 합성 성능을 유지하면서 GStreamer의 장치·buffer pool 실패가
Qt Quick Scene Graph 장치까지 전파되지 않게 한다. CPU 다운로드는 허용하지 않고 최종 합성
결과를 공유 텍스처 슬롯으로 한 번 복사한다.

이 문서는 현재 안정 GPU 경로를 대체하는 즉시 전환 계획이 아니다. 새 경로는 독립된 feature
flag 아래 구현하고 모든 안정성·성능 게이트를 통과한 뒤에만 기본 GPU 경로 후보가 된다.

## 2026-08-26 구현 상태

첫 수직 경로가 `FFGUI_ENABLE_ISOLATED_DIRECT_D3D_PREVIEW=1` opt-in으로 구현됐다.

- Qt device의 adapter LUID를 읽어 같은 adapter에 별도 `GstD3D11Device`를 생성한다.
- compositor appsink texture를 NT-handle 공유 texture로 GPU 복사한다.
- 프레임에 pipeline generation과 device epoch를 기록한다.
- Qt render thread가 자기 device에서 shared resource를 열어 QSG texture로 표시한다.
- presentation frame은 원래 compositor sample을 즉시 반환하며 scope용 10Hz 복사만 sample을
  제한적으로 유지한다.
- 기존 CPU 복구 상태 머신과 결합한 장치 제거 시뮬레이션을 통과했다.

현재 구현은 안전한 소유권 경계를 먼저 검증하는 1단계다. 매 프레임 immutable shared texture를
만들고 producer GPU copy 완료를 event query로 확인한다. 따라서 고정 4-slot pool과 공유 GPU
fence가 구현되기 전에는 성능 완성본이나 기본 경로로 승격하지 않는다.

2026-08-27에는 4-slot keyed-mutex ring을 시험했다. 첫 두 프레임은 표시됐지만 producer 슬롯
반환과 Qt의 반복 샘플링 수명이 맞지 않아 UI/render 동기화가 2초 이상 정체됐다. 이 프로토타입은
제품 코드에서 제거했고 immutable 경로를 복원해 표시와 CPU 복구 회귀를 다시 통과했다. 고정
slot 최적화는 keyed mutex를 장시간 보유하는 방식이 아니라 producer/consumer 공유
`ID3D11Fence` 값으로 GPU 완료를 추적하는 방식으로만 다시 진행한다.

## 현재 실패 계약

현재 직접 경로는 Qt가 만든 `ID3D11Device`를 GStreamer가 `gst_d3d11_device_new_wrapped()`로
감싼다. decoder, source color shader, `d3d11compositor`, appsink와 Qt Scene Graph가 같은
장치 및 immediate context 수명에 묶인다.

seek 또는 컬러 파이프라인 갱신 중 compositor buffer pool이 폐기되는 시점과 Qt가 이전
texture를 표시하는 시점이 겹치면 다음 문제가 발생한다.

- 이전 pool의 texture가 Qt에 남아 있는 동안 producer가 pool을 해제할 수 있다.
- GStreamer 오류가 공유 device를 removed 상태로 만들면 Qt의 swap chain도 함께 잃는다.
- pipeline generation과 device generation이 프레임에 없어서 늦게 도착한 프레임을 구별하지
  못한다.
- UI, preview worker, GStreamer streaming thread와 Qt render thread 사이에 명시적인 GPU 완료
  계약이 없다.

직접 compositor가 장치 손실의 재현 조건이라는 점은 확인됐지만, 잘못된 GPU 명령인지 pool
수명 경쟁인지에 대한 최종 세부 원인은 D3D11 debug layer 검증 전까지 확정하지 않는다.

## 목표 구조

```text
Qt Quick device                 GStreamer preview device
      │                                  │
      │                         decode / color / compose
      │                                  │
      │                    CopySubresourceRegion 1회
      │                                  ▼
      │                     shareable preview slot[0..3]
      │                                  │
      └──── OpenSharedResource + shared GPU fences ────┘
                         │
                         ▼
                 QSGD3D11Texture 표시
```

두 장치는 같은 DXGI adapter LUID를 사용하지만 서로 다른 `ID3D11Device`다. GStreamer는 Qt
device에 명령을 제출하지 않으며 Qt도 GStreamer immediate context를 사용하지 않는다.

최종 compositor texture에서 공유 슬롯으로 GPU 복사 한 번만 수행한다. Qt는 공유 슬롯을 자기
device에서 열어 직접 샘플링하므로 CPU download와 두 번째 GPU texture copy가 없다.

## 구성 요소

### `PreviewD3DDevice`

`GesSequencePlayer`가 소유하는 GStreamer 전용 장치다.

- Qt device에서는 `IDXGIDevice::GetAdapter()`와 adapter LUID만 읽는다.
- 같은 adapter로 별도 `ID3D11Device`를 생성한다.
- `ID3D11Multithread::SetMultithreadProtected(TRUE)`를 적용한다.
- 생성한 장치를 `GstD3D11Device`로 감싸 pipeline 전체에 context로 전달한다.
- Qt device 또는 Qt immediate context를 GStreamer에 전달하지 않는다.

하이브리드 GPU 시스템에서 같은 LUID를 만들 수 없으면 직접 경로를 시작하지 않고 안정 GPU
경로로 돌아간다.

### `SharedPreviewPool`

producer device에 4개의 고정 슬롯을 만든다. 재생 중 매 프레임 texture를 생성하지 않는다.

각 슬롯은 다음 자원을 가진다.

```cpp
struct SharedPreviewSlot {
    uint64_t device_epoch;
    uint32_t slot_index;
    ComPtr<ID3D11Texture2D> producer_texture;
    unique_handle texture_handle;
    uint64_t ready_fence_value;
    uint64_t consumed_fence_value;
};
```

texture는 compositor 출력과 같은 크기·형식을 사용하고 다음 공유 플래그를 갖는다.

- `D3D11_RESOURCE_MISC_SHARED_NTHANDLE`
- fence를 지원하지 않는 fallback에서만 `D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX`

기본 동기화는 공유 `ID3D11Fence` 두 개를 사용한다.

- producer fence: slot 복사가 끝난 값을 Qt에 알린다.
- consumer fence: Qt 렌더가 끝난 값을 producer에 알린다.

producer는 consumer fence가 완료된 빈 슬롯만 사용한다. 2ms 안에 빈 슬롯이 없으면 streaming
thread를 막지 않고 해당 프레임을 드롭한다. 재생 정확도보다 UI와 오디오 연속성을 우선한다.

### `SharedPreviewFrame`

`PreviewVideoFrame`의 동일-device raw pointer 계약을 다음 메타데이터 계약으로 교체한다.

```cpp
struct SharedPreviewFrame {
    uint64_t pipeline_generation;
    uint64_t device_epoch;
    uint32_t slot_index;
    uint32_t width;
    uint32_t height;
    DXGI_FORMAT format;
    HANDLE texture_handle;
    HANDLE producer_fence_handle;
    HANDLE consumer_fence_handle;
    uint64_t ready_value;
    uint64_t release_value;
};
```

OS handle의 실제 소유권은 pool에 있고 프레임은 참조 수명만 가진다. pipeline 또는 device epoch가
바뀌면 이전 프레임은 Qt에 제출하지 않는다.

### `SharedPreviewReceiver`

`VideoPreviewItem`의 render-thread 전용 수신기다.

- `sceneGraphInitialized()` 뒤 Qt device와 adapter LUID를 다시 확인한다.
- `(device_epoch, slot_index)`별로 shared texture와 fence를 한 번만 연다.
- `updatePaintNode()` 전에 Qt context에 producer fence wait를 삽입한다.
- 공유 texture를 `QSGD3D11Texture::fromNative()`로 감싸 표시한다.
- `afterRendering()`에서 consumer fence를 signal해 슬롯을 producer에 반환한다.
- 표시되지 않고 교체된 프레임도 명시적으로 반환한다.
- 모든 QSG wrapper와 열린 shared resource는 render thread에서만 폐기한다.

Qt가 scene graph를 재생성하면 receiver epoch를 올리고 기존 open resource를 모두 폐기한다.
producer pool 자체는 건강한 경우 유지할 수 있지만 새 Qt receiver가 슬롯과 fence를 다시 열기 전에는
프레임을 제출하지 않는다.

### `PreviewBackendCoordinator`

`EditorController`의 boolean 조합을 다음 상태 머신으로 교체한다.

```text
CpuSafe
StableGpu
DirectGpuStarting
DirectGpuRunning
DirectGpuQuiescing
DirectGpuRebuilding
DirectGpuRecovering
```

모든 상태 전이는 UI thread에서 시작하지만 GStreamer 명령은 하나의 preview worker에서 직렬화한다.
Qt render thread에서는 shared resource open/wait/signal/release만 수행한다.

## pipeline 재구축 규칙

구조 편집 때문에 rebuild가 필요할 때 다음 순서를 지킨다.

1. generation을 증가시키고 새 프레임 제출을 차단한다.
2. appsink에 flush를 보내고 streaming callback 진입이 끝날 때까지 기다린다.
3. Qt가 현재 슬롯의 consumer fence를 signal할 때까지 제한 시간 내에서 drain한다.
4. pipeline을 `NULL`로 만들고 state 완료를 확인한다.
5. compositor pad, buffer pool, color resource와 이전 pipeline을 폐기한다.
6. 동일한 건강한 device에서 새 pipeline을 만들고 `PAUSED` preroll을 완료한다.
7. 첫 GPU 프레임의 generation·epoch·fence를 확인한다.
8. 이전 재생 상태와 playhead를 복구한 뒤 제출을 재개한다.

컬러 휠·커브·LUT 파라미터 변경은 rebuild 사유가 아니다. shader constant와 LUT resource를
double-buffering하고 compositor 프레임 경계에서 교체한다.

drain 또는 preroll이 제한 시간을 넘으면 같은 직접 pipeline을 반복 재시도하지 않고 안정 GPU
경로로 강등한다.

## 장치 손실 규칙

모든 D3D HRESULT 실패에서 `GetDeviceRemovedReason()`을 한 번 기록하고 `device_epoch`를 즉시
무효화한다.

1. producer frame callback 차단
2. Qt receiver의 QSG wrapper와 open shared resource 폐기
3. GStreamer pipeline, pool, fences와 producer device 전체 폐기
4. 같은 adapter에서 새 producer device 생성 1회 시도
5. 직접 GPU preroll 성공 시 복구
6. 실패 또는 Qt device도 손실된 경우 안정 GPU 또는 CPU 안전 경로로 강등

removed device에서 만든 texture, fence, context 또는 `GstD3D11Device`는 하나도 재사용하지 않는다.
복구 완료는 상태 변경 시점이 아니라 첫 새 epoch 프레임의 실제 Qt 제출 시점이다.

## 구현 단계

### 1단계: 관측성과 계약

- [x] `PreviewVideoFrame`에 pipeline generation과 device epoch 추가
- 모든 rebuild·frame submit·drop·resource release 로그에 generation/epoch 추가
- D3D11 debug layer와 InfoQueue를 Debug에서 선택적으로 활성화
- 현재 직접 경로에서 최초 device removal 이전 오류 메시지 수집

### 2단계: 분리 장치와 pool

- [x] `PreviewD3DDevice` 및 동일 LUID 검증 구현
- [x] 4-slot `SharedPreviewPool`과 producer/consumer shared `ID3D11Fence` 구현
- [x] 1단계 immutable resource 방식으로 appsink compositor 결과 GPU copy
- [x] 고정 slot 반환을 실제 Qt offscreen 표시 및 강제 장치 제거 smoke로 검증

### 3단계: Qt receiver

- [x] render thread에서 immutable shared resource open 및 QSG 표시
- [x] 고정 slot shared texture/fence resource cache 구현
- [x] producer ready signal과 Qt render-context wait, 이전 표시 frame의 consumer release signal 연결
- [x] skipped frame은 lease 소멸 시 producer context에서 반환하고 scene graph invalidation 시 현재 slot 반환
- 기존 동일-device texture 경로와 별도 feature flag로 공존

### 4단계: coordinator와 rebuild

- rebuild를 quiesce/drain/preroll 트랜잭션으로 변경
- 컬러 연속 변경을 pipeline rebuild 없이 resource swap으로 제한
- 시간 제한과 StableGpu/CPU 강등 연결

### 5단계: 기본 경로 승격 판단

다음 게이트를 모두 통과하기 전에는 `FFGUI_ENABLE_ISOLATED_DIRECT_D3D_PREVIEW=1` opt-in으로
유지한다.

## 검증 게이트

### 정확성과 안정성

- Debug build와 CTest
- CFR/VFR, H.264/HEVC, 1x/2x 재생과 source-alpha 디졸브
- seek 1,000회 및 JKL 방향 전환 300회
- 재생 중 컬러 휠·커브·LUT 변경 10분
- pipeline rebuild 100회
- 최소화·복원, 창 resize, 모니터 이동
- D3D11 debug layer error/corruption 메시지 0건
- `dxcap -forcetdr` 뒤 CPU 또는 새 GPU epoch로 복구
- 종료 후 device, shared handle과 process 잔류 0건

### 성능

같은 4K H.264/HEVC 타임라인에서 CPU 안전, 안정 GPU, 격리형 직접 GPU를 비교한다.

- seek 후 첫 프레임 p50/p95
- 60초 재생 dropped frame과 최대 frame gap
- CPU process 사용률
- GPU Video Decode/3D/Copy 사용률
- private memory와 dedicated/shared VRAM
- color+transition 활성 상태의 compositor 처리량

격리형 직접 GPU는 안정 GPU보다 다음 조건을 동시에 만족해야 기본 후보가 된다.

- device loss와 D3D debug error 0건
- 4K color+transition 재생의 CPU 사용률 감소
- p95 frame gap 악화 없음
- GPU copy 1회, CPU download 0회
- CPU 강등 후 첫 프레임 2초 이내

## feature flag와 롤백

- `FFGUI_ENABLE_D3D_PREVIEW=1`: 현재 안정 GPU
- `FFGUI_ENABLE_ISOLATED_DIRECT_D3D_PREVIEW=1`: 새 격리형 직접 GPU
- `FFGUI_ENABLE_ISOLATED_D3D_FENCE_POOL=1`: 격리형 직접 GPU의 실험적 4-slot fence 풀
- `FFGUI_ENABLE_DIRECT_D3D_COMPOSITOR=1`: 기존 동일-device 진단 경로, 개발 전용
- `FFGUI_FORCE_CPU_PREVIEW=1`: 모든 GPU 선택보다 우선

새 경로의 오류는 현재 안정 GPU로 먼저 강등하고, 동일 세션에서 다시 실패하면 CPU 안전으로
강등한다. 기능 승격 후에도 최소 한 릴리스 동안 안정 GPU 경로를 롤백 수단으로 유지한다.
