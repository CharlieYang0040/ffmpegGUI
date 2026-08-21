# 완료 감사 증거표

최종 갱신: 2026-08-20

이 문서는 개발 계획 R7의 요구사항별 증거다. 코드와 자동 테스트로 닫은 항목과,
이 환경에서 반복할 수 없어 릴리스 게이트로 남은 항목을 구분한다. 깨끗한 Windows PC,
Unreal Engine 5.5–5.8 뷰포트, 전체 실제 미디어 매트릭스가 끝나기 전에는 정식 릴리스나
완성 제품으로 표시하지 않는다.

## 기능

| 요구사항 | 상태 | 증거 | 남은 게이트 |
| --- | --- | --- | --- |
| 마그네틱 타임라인·VFR·undo | 코드 완료 | 코어 테스트, 프로젝트 v4 왕복 | 깨끗한 PC 실기 |
| 미리보기=출력 편집 모델 | 코드 완료 | 스냅샷 리비전, float 프레임 서버, Hald CLUT | Windows GES/FFmpeg 실기 |
| GradeGraph 공간 비의존 노드 | 코드 완료 | `apply_grade_graph_rgba32f`, 큐브 golden patch | GPU 셰이더 픽셀 장치 비교 |
| 시간 가변 grade | 코드 완료 | 원본 PTS 보간, 애니메이트 큐브, Hald 시퀀스 | Windows 미리보기/출력 실기 |
| 창작 Look LUT 전달 | 코드 완료 | 33³/65³ Cube, shaper, 공간·키프레임 거부 | ACEScct shaper는 OCIO 필요 |
| Unreal OCIO 패키지 | 코드 완료 | OCIO 2.2 `config.ocio`, `.ocioz` PK zip, CLF, `UNREAL.md`, `charts/expected.json` | Unreal 5.5–5.8 뷰포트 차트 |
| 이중 톤맵 방지 | 코드 완료 | `LutExportRequest::validate`가 Unreal+표시 변환을 거부 | 엔진 톤 매퍼 실기 |
| Qualifier / power window | 코드 완료 | HSV/루마 키, 타원·사각 마스크, 키프레임 트래킹 | 일반 영상 스택 중간 순서 |
| 일반 영상 공간 그레이드 출력 | 의도적 차단 | `spatial-grade-requires-float-frame-server` | 해당 없음 |
| 샷 스틸·wipe/split·매칭 | 코드 완료 | PNG 왕복, wipe/split, 평균 노출/채도, grade undo | GES 영상 위 스틸 오버레이 실기 |
| HDR10 출력 메타데이터 | 코드 완료 | Rec.2100 PQ, MaxCLL/MaxFALL FFmpeg 인자 | NVENC SEI Windows 파일 검증 |
| 창 HDR / 모니터 ICC | 코드 완료 | scRGB 우선, PQ 폴백, ICC 경로 | 실제 HDR 다중 모니터 |

## 컬러 정확도

| 요구사항 | 상태 | 증거 | 남은 게이트 |
| --- | --- | --- | --- |
| CPU float 기준 렌더 | 코드 완료 | 코어 테스트, 알파 분리, mix | Windows OCIO config 로드 |
| 큐브가 기준 경로와 같음 | 코드 완료 | golden patch, 공간 노드는 베이크에서 제외 | GPU LUT 샘플 장치 비교 |
| Look은 창작 grade만 | 코드 완료 | `bake_look_cube`가 표시 변환을 기본 제외 | Unreal Linear vs Look 뷰 |
| 이미지 시퀀스 공간 순서 | 코드 완료 | `process_color_frame(..., GradeSpatialMode::include)` | 실제 EXR 시퀀스 실기 |
| 일반 영상 미리보기 공간 | 타협 | CPU 필터가 큐브 뒤에 공간 노드만 적용 | 스택 중간 qualifier는 시퀀스 전용 |

## HDR·표시

| 요구사항 | 상태 | 증거 | 남은 게이트 |
| --- | --- | --- | --- |
| Display/View·bypass·비교 | 코드 완료 | 프로젝트 저장, float wipe | Windows 모니터 실기 |
| 스코프 기준점 | 코드 완료 | 그레이드 전/후/표시 후 | 일반 영상 그레이드 전은 근사 |
| scRGB/PQ 창 | 코드 완료 | `hdr_display` | 다중 HDR 모니터 이동 |

## 성능·안정성

| 요구사항 | 상태 | 증거 | 남은 게이트 |
| --- | --- | --- | --- |
| 그레이드 중 재생 유지 | 코드 완료 | 소스 LUT만 갱신, 재생 중 UI 억제 | 4K soak 재측정 |
| D3D 장치 제거 복구 | 코드 완료 | CPU 미리보기 폴백 | 실제 장치 제거 실기 |
| 독립 패키지 | 기존 기준선 | 배포 스크립트 | 깨끗한 Windows 11 x64 PC |

## 이 환경에서 실행하지 않은 것

OpenColorIO, GStreamer, Qt가 없는 클라우드 에이전트에서는 Windows `ctest`, GES GPU/CPU
3경로, 데스크톱 smoke, Unreal 뷰포트, HDR 모니터를 돌리지 않았다. 해당 항목은 릴리스
게이트로 남긴다.
