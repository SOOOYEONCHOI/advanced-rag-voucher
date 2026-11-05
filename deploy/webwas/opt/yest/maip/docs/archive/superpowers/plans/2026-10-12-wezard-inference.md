# Wezard 추론 연결(방향 ②) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 현장 검사(`POST /api/v1/inspections`)가 매핑된 Wezard 모델로 추론해 `SUCCESS`·판정을 돌려주게 한다.

**Architecture:** `get_inference_gateway()` 가 `WEZARD_BASE_URL`·`WEZARD_API_KEY` 가 있으면 `WezardGateway`(표준 라이브러리 `urllib`)를 돌려준다. 게이트웨이는 매핑의 `model_code`(= Wezard `model_name`)로 배포된 최신 모델을 찾고 `POST /api/v1/inference/{model_id}` 를 부른다. 매핑 화면은 Wezard 배포 모델 목록에서 고르고, 고른 이름을 로컬 `VisionModel`(version `latest`)로 맞춰 둔 뒤 매핑한다 — DB 구조는 바꾸지 않는다.

**Tech Stack:** Django 5.2, `urllib.request`(새 의존성 없음), Wezard API(`docs/Wezard/wezard-api.md`), 통신 규약 v1(`docs/Wezard/integration-protocol.md` §3·§4·§5·§10)

## 사용자 결정 (2026-10-12)

| 항목 | 결정 |
|---|---|
| 매핑 | 매핑 화면에서 Wezard 배포 모델을 고른다. 유형이 맞는 것만 보이고, 검사항목 코드 소문자와 같은 이름을 앞에 둔다. 이름을 저장하고 추론 때마다 최신 배포 모델을 찾는다 |
| 실패 | 구분 처리 — Wezard 미설정·배포 모델 없음은 `RECEIVED` + 사유, 시간 초과·연결 실패·Wezard 5xx 는 `FAILED`. 재시도 없음, 추론 타임아웃 15초 |
| health | 이번에 넣지 않는다(DEC-C15 그대로, 클라이언트와 따로 합의) |

## 동작

| 상황 | 검사 `status` | `error_message` |
|---|---|---|
| 매핑 없음 | `RECEIVED` | 없음 |
| 매핑 있음, Wezard 설정 없음 | `RECEIVED` | `GPU_INFERENCE_NOT_CONFIGURED`(지금과 같다) |
| 매핑 있음, 그 이름의 배포 모델 없음(목록 0건·추론 404/409) | `RECEIVED` | `WEZARD_MODEL_NOT_DEPLOYED` |
| 시간 초과·연결 실패·Wezard 401·5xx·그 밖의 오류 | `FAILED` | `<예외 이름>: <코드>`(화면 전용) |
| 추론 성공 | `SUCCESS` | 없음 |

- 이상 탐지: `abnormal = is_anomaly`, `anomaly_score`, `threshold`. 매핑 임계값 재지정이 있으면 `anomaly_threshold` 로 보낸다.
- 객체 탐지: `detections` → `Defect(class_name=label, confidence=score, bbox={x1,y1,x2,y2})`. bbox 는 정수(x1·y1 내림, x2·y2 올림)로 바꾸고 이미지 안으로 자른다. 넓이가 0 이면 버린다. `abnormal = 탐지 1건 이상`. 재지정은 `score_threshold`.
- `model_name`·`model_version` 은 Wezard 응답 값(실제 쓴 버전), `inference_ms` 는 응답 `elapsed_ms`.
- 헤더: `X-API-Key`, `X-Request-ID` = 검사 `request_id`(UUID 36자, 규약 §4 형식에 맞는다). 목록 조회는 새 32자리 hex.
- 타임아웃: 목록 조회 5초 + 추론 15초 — 검사 POST 20초 예산 안(DEC-C11).
- 분류 검사항목은 매핑하지 않는다(카탈로그에서 빠지고 클라이언트 유형이 없다, O-14).

---

### Task 1: WezardGateway

**Files:** Modify `domain/services/vision/gateway.py`, `configurations/settings.py` · Test `tests/test_wezard_gateway.py`

**Interfaces:**
- `ModelNotDeployedError(GpuNotConfiguredError)` — `code = 'WEZARD_MODEL_NOT_DEPLOYED'`
- `WezardError(Exception)` — `code`(Wezard `error.code` 또는 `TIMEOUT`·`UNREACHABLE`), `status`
- `WezardGateway(base_url, api_key)`:
  - `is_configured() -> True`
  - `list_models(task_type: str) -> list[dict]` — 배포·READY·vision, 그 task(`detection`·`anomaly`)
  - `infer(...)` — 기존 시그니처 그대로, `InferenceResult`
  - `_request(method, path, *, query=None, body=None, content_type=None, request_id=None, timeout) -> dict` — 테스트가 이것만 바꿔 끼운다
- `get_inference_gateway()` — 설정 둘 다 있으면 `WezardGateway`, 아니면 Stub
- settings `WEZARD_BASE_URL`·`WEZARD_API_KEY`(`env(..., '')`), test_settings 는 빈 값

- [ ] 테스트(RED): 이상 탐지 결과 변환, 탐지 bbox 정수·자르기·0 넓이 버림, 재지정 임계값 필드 이름, 배포 모델 없음 → `ModelNotDeployedError`, 추론 409 `MODEL_NOT_DEPLOYED` → `ModelNotDeployedError`, 5xx·시간 초과 → `WezardError`, 설정 유무에 따른 `get_inference_gateway`, multipart 본문에 이미지·헤더에 키와 request_id
- [ ] 구현(GREEN) → 테스트 통과
- [ ] 커밋 `feat: Wezard 추론 게이트웨이(배포 모델 조회·추론·결과 변환)를 더한다`

### Task 2: 검사 상태와 화면 사유

**Files:** Modify `domain/services/vision/inspection.py`(필요하면), `app/views/vision/inspection.py` · Test `tests/test_client_api.py` 또는 새 `tests/test_inspection_inference.py`

- [ ] 테스트(RED): 가짜 게이트웨이로 — 배포 모델 없음 → `RECEIVED` + `WEZARD_MODEL_NOT_DEPLOYED`, `WezardError` → `FAILED`, 성공 → `SUCCESS`·판정 저장. 화면 상태 글: `GPU_INFERENCE_NOT_CONFIGURED` → "접수됨 (추론 미실행 · Wezard 미설정)", `WEZARD_MODEL_NOT_DEPLOYED` → "접수됨 (추론 미실행 · 배포 모델 없음)"
- [ ] 구현 — `ModelNotDeployedError` 는 `GpuNotConfiguredError` 하위라 서비스는 그대로 `RECEIVED` 로 받는다. 화면 글만 사유별로
- [ ] 커밋 `feat: 검사 결과 화면이 추론 미실행 사유(Wezard 미설정·배포 모델 없음)를 구분한다`

### Task 3: 매핑 화면 — Wezard 모델에서 고르기

**Files:** Modify `app/views/vision/model.py`, `app/templates/vision/model_mapping.html` · Test `tests/test_vision_model_mapping.py`(있으면 그곳)

- [ ] 테스트(RED):
  - `model_mapping?action=models&item_id=` → 그 검사항목 유형의 Wezard 배포 모델 이름 목록(이름별 하나), 코드 소문자와 같은 이름이 첫째, 분류 검사항목은 빈 목록과 안내
  - `save` 에 `model_name` → Wezard 목록에 있는지 확인 → `VisionModel(name, version='latest', runtime='wezard')` 를 맞추고 매핑. 목록에 없거나 유형이 다르면 거절
  - Wezard 설정이 없으면 목록이 비고 안내 문구
- [ ] 구현 — 화면: 행을 고를 때 그 검사항목의 모델 목록을 다시 읽어 `<option>` 을 `.text()` 로 채운다. 그리드 모델 칸은 `latest` 면 "fan-panel (최신 배포)"
- [ ] 화면 검증: `verify_screen_js`·`verify_modals`·`verify_buttons`, e2e `test_detail_form.py`(매핑 화면을 연다)
- [ ] 커밋 `feat: 검사항목 모델 매핑을 Wezard 배포 모델에서 고른다`

### Task 4: 실측과 문서

- [ ] 실측(개발 장비): FAN-PANEL → `fan-panel` 매핑 → 임시 `E2E-INFER-` 클라이언트로 결함(14.png)·정상(1.png) 검사 전송 → `SUCCESS`·`abnormal` true/false, Wezard 추론 이력에 그 `request_id`. 끝나면 임시 클라이언트·검사 기록·그 이미지를 지운다(매핑은 남긴다)
- [ ] 문서: ARCHITECTURE §7(Stub → Wezard, 표·바꿀 곳), DECISIONS(DEC-015 인증은 규약 §3 `X-API-Key` 로, O-12 사유 코드, F-2 완료, 새 결정 1행), FEATURES(매핑 화면), STATUS(4-1), 규약 §12 방향 ② 행, 클라이언트 계약 §17(개발 서버에서 판정이 나오기 시작함 — 응답 형식은 그대로)
- [ ] 커밋 `docs: Wezard 추론 연결을 반영한다`

## 하지 않는 것

- health `components.gpu`(사용자 결정)
- 재시도·모델 ID 캐시 — 추론마다 목록을 한 번 부른다. 지연이 문제 되면 짧은 캐시를 둔다
- heatmap 저장, 분류 추론
- 새 의존성(`requests` 등)

## 실행 기록 (2026-10-12)

- Task 1~4 완료. 실측: FAN-PANEL → `fan-panel` 매핑, 임시 클라이언트로 14.png(결함) `SUCCESS` · `abnormal: true` · 점수 48.39, 1.png(정상) `abnormal: false` · 22.21, 응답 0.2초. 임시 클라이언트·검사 4건·이미지 4장은 지웠고 매핑은 남겼다
- 계획에서 더한 것: 실측에서 응답 `model.version` 이 `latest` 로 나가 — 성공하면 Wezard 가 실제로 쓴 이름·버전을 기록하게 고쳤다(`inspection.py`, 테스트 추가)
- 매핑 화면 선택 칸 id 를 `model_id` → `model_name` 으로 바꿨다(값이 이름이다). e2e `test_write_paths`·`test_xss` 를 함께 고쳤다
- Wezard 추론 이력에 `request_id` 가 남는지는 Wezard 화면에서 직접 보지 않았다(Wezard 가 `wezard-api.md` §11.2 에서 확인)
