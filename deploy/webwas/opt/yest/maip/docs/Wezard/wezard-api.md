# Wezard API — 모델 목록·조회·추론

> 방향 ②(제조AI플랫폼 → Wezard) 계약의 정본입니다. Wezard가 관리합니다.
> 공통 규칙(인증·요청 추적·오류·재시도·페이지·시각)은 [통신 규약 v1](integration-protocol.md)에 있고, 이 문서는 엔드포인트만 적습니다.

## 접속 정보

| 항목 | 값 |
| --- | --- |
| Base URL | `http://10.10.10.20:8000` — 개발 장비(사내망, HTTP). 운영 주소는 정해지면 고쳐 전달합니다 |
| API 키 | 따로 전달합니다(`wz_…`). 환경 변수 `WEZARD_API_KEY`에만 둡니다 |

```bash
export WEZARD_BASE_URL=http://10.10.10.20:8000
export WEZARD_API_KEY='<따로 받은 API 키>'

# 연결 확인 — 200 과 {"items": [...]} 가 나오면 됩니다
curl -s -H "X-API-Key: $WEZARD_API_KEY" "$WEZARD_BASE_URL/api/v1/models?limit=1"
```

## 1. 한눈에 보기

| 목적 | 호출 |
| --- | --- |
| 추론에 쓸 모델 목록 | `GET /api/v1/models?deployed=true&status=READY` |
| 모델 정보 | `GET /api/v1/models/{model_id}` |
| 모델 입력 규격·기본 임계값 | `GET /api/v1/models/{model_id}/files/model.json` |
| 이미지 추론(동기) | `POST /api/v1/inference/{model_id}` |
| VL/LLM 질의(OpenAI 호환) | `POST /api/v1/chat/completions` |

외부에는 이 다섯 경로만 열려 있습니다.

권장 순서:

1. 검사항목 코드를 소문자로 바꾼 `model_name`(규약 §10)으로 목록을 조회합니다: `?model_name=<이름>&deployed=true&status=READY`. 첫 항목이 배포된 최신 버전입니다.
2. 그 `model_id`로 `POST /api/v1/inference/{model_id}`를 부르고 `task_type`에 맞게 `results`를 읽습니다.
3. `404`나 `409`(배포 해제·미준비)가 오면 1부터 다시 합니다. 재학습하면 `model_id`가 바뀌므로 저장해 두지 않습니다.

## 2. 공통 규칙

| 항목 | 내용 |
| --- | --- |
| 인증 | 헤더 `X-API-Key` 하나(규약 §3). 없거나 틀리면 `401 UNAUTHORIZED`. 키에는 권한 구분이 없으니 노출하지 않습니다 |
| 요청 ID | `X-Request-ID`(1~64자 `[A-Za-z0-9._-]`)를 응답 헤더와 오류 본문 `request_id`로 돌려주고 추론 이력에 남깁니다(규약 §4) |
| 목록 페이지 | `limit`(1~200, 기본 50), `offset`(기본 0). 응답 `{"items", "total", "limit", "offset"}`, 생성 최신순 |
| 시각 | ISO 8601 `+09:00`. 오류 본문 `timestamp`만 UTC |

## 3. 모델 목록 — `GET /api/v1/models`

예시 값은 개발 장비의 `fan-panel` v3(18장 시험 데이터셋)입니다.

쿼리 파라미터(모두 선택):

| 이름 | 값 | 설명 |
| --- | --- | --- |
| `model_name` | 문자열 | 정확히 일치 |
| `deployed` | `true` / `false` | 추론 대상은 `true` |
| `status` | `PENDING` / `RUNNING` / `READY` / `FAILED` / `CANCELED` | 추론 대상은 `READY` |
| `category` | `vision` / `vl` / `llm` | 이미지 추론 대상은 `vision` |
| `task_type` | `classification` / `detection` / `anomaly` / `vl` / `llm` | |
| `limit`, `offset` | 정수 | 페이지 |

```json
{
  "items": [
    {
      "model_id": "f2fc9d5a71ba4e38b5902a4815a56e17",
      "model_name": "fan-panel",
      "version": 3,
      "task_type": "anomaly",
      "category": "vision",
      "invoke": "inference",
      "status": "READY",
      "deployed": true,
      "class_names": ["good", "defect"],
      "metrics": {"image_auroc": 1.0, "pixel_auroc": 0.99, "threshold": 33.26, "f1": 1.0, "precision": 1.0, "recall": 1.0},
      "dataset_external_ref": "maip:FAN-PANEL:v2.0#106",
      "serving_state": null,
      "...": "그 밖의 필드는 참고용(arch, params, files, created_at 등)"
    }
  ],
  "total": 1, "limit": 50, "offset": 0
}
```

| 필드 | 설명 |
| --- | --- |
| `model_id` | 추론 호출에 쓰는 ID(32자리 hex). 재학습마다 새로 생깁니다 |
| `model_name`, `version` | 이름과 그 안의 버전(1부터) |
| `task_type` | `classification` / `detection` / `anomaly`. 추론 결과 형식을 정합니다 |
| `category`, `invoke` | `vision` → `inference`(§5), `vl`·`llm` → `chat_completions`(§5.4) |
| `status`, `deployed` | `READY`이고 `deployed=true`여야 부를 수 있습니다. VL/LLM의 `deployed`는 지금 실행 중인지입니다 |
| `class_names` | 결과 `label`에 나오는 클래스 |
| `metrics` | 검증 지표. 분류 `accuracy`·`macro_f1` 등, 검출 `map50`·`map50_95`, 이상 탐지 `image_auroc`·`threshold`·`f1` |
| `dataset_external_ref` | 학습 데이터셋 출처 `maip:<검사항목 코드>:<버전>#<스냅샷 id>`, 없으면 `null` |
| `serving_state` | VL/LLM 실행 상태(`STOPPED`/`STARTING`/`RUNNING`/`FAILED`), vision은 `null` |

## 4. 모델 정보

- `GET /api/v1/models/{model_id}`: 목록 항목과 같은 객체. 없으면 `404 MODEL_NOT_FOUND`.
- `GET /api/v1/models/{model_id}/files/model.json`: 입력 규격과 기본 임계값. 외부에서 받을 수 있는 파일은 이것 하나입니다.

```json
{
  "format": "wezard-model/v1",
  "model_id": "f2fc9d5a71ba4e38b5902a4815a56e17", "model_name": "fan-panel", "version": 3, "task_type": "anomaly",
  "class_names": ["good", "defect"],
  "input": {"size": [256, 256], "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]},
  "thresholds": {"anomaly": 33.26}
}
```

- `thresholds`: 검출 `score`(기본 0.25), 이상 탐지 `anomaly`, 분류는 `{}`.
- 리사이즈·정규화는 서버가 합니다. 원본 이미지를 그대로 보내면 됩니다.

## 5. 추론 — `POST /api/v1/inference/{model_id}`

`multipart/form-data`. 서버가 요청 안에서 추론해 바로 돌려줍니다.

| 필드 | 형식 | task | 설명 |
| --- | --- | --- | --- |
| `files` | 파일, 반복 | 전체 | 한 요청 최대 16장, 장당 최대 20MB(운영 설정 `INFER_MAX_IMAGES`·`INFER_IMAGE_MAX_MB`) |
| `topk` | 정수 1~100 | classification | 상위 몇 개 클래스. 기본 3 |
| `score_threshold` | 실수 0~1 | detection | 이 점수 미만 박스 제외. 기본 `thresholds.score` |
| `anomaly_threshold` | 실수 | anomaly | 이 점수 이상이면 이상. 기본 `thresholds.anomaly` |
| `return_heatmap` | `true` / `false` | anomaly | `true`면 이미지별 히트맵 PNG(base64). 기본 `false` |

- 다른 task의 옵션은 무시합니다.
- 이미지는 PNG·JPEG·BMP·TIFF 등. 읽지 못하면 `415 INVALID_IMAGE`(모델 확인보다 먼저).
- 좌표와 `width`·`height`는 EXIF 방향을 적용한 원본 픽셀 기준입니다.
- `Content-Length` 헤더가 필요합니다(대부분의 클라이언트가 자동으로 넣습니다).

```bash
curl -s -H "X-API-Key: $WEZARD_API_KEY" -H "X-Request-ID: <검사 request_id>" \
  -F "files=@a.png" "$WEZARD_BASE_URL/api/v1/inference/<model_id>"
```

응답 공통:

```json
{
  "model_id": "…", "model_name": "…", "version": 1, "task_type": "…",
  "results": [{"filename": "a.png", "width": 1448, "height": 1086, "...": "task별 필드"}],
  "elapsed_ms": 38
}
```

`results`는 보낸 `files` 순서와 같습니다.

### 5.1 분류 (classification)

```json
{"filename": "a.png", "width": 64, "height": 64, "label": "ok", "score": 0.75,
 "topk": [{"label": "ok", "score": 0.75}, {"label": "ng", "score": 0.25}]}
```

| 필드 | 설명 |
| --- | --- |
| `label`, `score` | 1순위 클래스와 확률(0~1) |
| `topk` | 상위 k개 `{label, score}`, 점수 내림차순 |

### 5.2 객체 검출 (detection)

```json
{"filename": "a.jpg", "width": 1920, "height": 1080,
 "detections": [{"label": "scratch", "score": 0.93, "bbox": [412.0, 220.5, 530.2, 301.0]}]}
```

| 필드 | 설명 |
| --- | --- |
| `detections` | 임계값 이상 박스. 없으면 `[]` |
| `bbox` | `[x1, y1, x2, y2]` 원본 픽셀(실수) |

### 5.3 이상 탐지 (anomaly)

```json
{"filename": "a.png", "width": 1448, "height": 1086,
 "anomaly_score": 51.10, "threshold": 33.26, "is_anomaly": true}
```

| 필드 | 설명 |
| --- | --- |
| `anomaly_score` | 이상 점수. 0~1 확률이 아니고 모델마다 범위가 다릅니다 |
| `threshold`, `is_anomaly` | 이번 요청에 쓴 임계값, `anomaly_score >= threshold` |
| `heatmap_png_base64` | `return_heatmap=true`일 때만. EXIF 방향을 적용한 원본 크기의 jet 컬러맵 PNG(RGB, 불투명). 색 기준은 이번 응답의 `threshold`(T) 고정입니다: 0.5T 이하 파랑, T 초록, 1.5T 이상 빨강(값은 `anomaly_score`와 같은 단위, 이미지마다 다시 맞추지 않음). 정상 이미지는 대부분 파랑, 결함 부위는 노랑~빨강입니다. 원본 위에 반투명으로 겹쳐 보여 주면 됩니다 |

### 5.4 VL/LLM 질의 — `POST /api/v1/chat/completions`

요청·응답은 **OpenAI Chat Completions 형식 그대로**입니다. 스트리밍은 지원하지 않습니다.

- `model`: 목록에서 `invoke=chat_completions`이고 `deployed=true`인 항목의 `model_name`.
- 본문에 `model`과 비어 있지 않은 `messages`가 있어야 합니다. 이미지는 `{"type": "image_url", "image_url": {"url": "data:image/png;base64,…"}}`.
- 본문 크기 상한은 운영 설정 `CHAT_MAX_BODY_MB`, `Content-Length` 헤더가 필요합니다.

```bash
curl -s -H "X-API-Key: $WEZARD_API_KEY" -H "Content-Type: application/json" "$WEZARD_BASE_URL/api/v1/chat/completions" \
  -d '{"model": "qwen3-vl-8b", "max_tokens": 80, "temperature": 0, "messages": [{"role": "user", "content": "한 문장으로 답하세요: 불량 검사에 VL 모델을 쓰는 장점?"}]}'
```

OpenAI SDK를 쓰면 인증을 `default_headers={"X-API-Key": …}`로 넣습니다(`base_url`은 `<Base URL>/api/v1`).

## 6. 오류 코드

본문 형식(규약 §5):

```json
{"ok": false, "error": {"code": "MODEL_NOT_DEPLOYED", "message": "model is not deployed", "detail": null, "retryable": false},
 "request": {"method": "POST", "path": "/api/v1/inference/…"}, "request_id": "…", "timestamp": "…+00:00"}
```

HTTP 상태, `error.code`, `error.retryable`, `request_id`만 읽습니다. `retryable`이 `true`인 것은 아래 표의 500·502·503·504뿐이고, 그때만 재시도합니다(규약 §6).

| HTTP | `error.code` | 상황 | 처리 |
| --- | --- | --- | --- |
| 400 | `USE_CHAT_COMPLETIONS` | VL/LLM 모델로 이미지 추론 | `category=vision` 모델 사용 |
| 400 | `MODEL_NOT_CHAT` | chat `model`이 비전 모델 | 이미지 추론 API 사용 |
| 400 | `STREAM_NOT_SUPPORTED` | chat `stream: true` | `stream` 빼기 |
| 400 | `UPSTREAM_BAD_REQUEST` | 모델 서버가 거부(`detail.message`) | 요청 수정 |
| 401 | `UNAUTHORIZED` | 키 없음·틀림 | 키 확인, 재시도 금지 |
| 404 | `MODEL_NOT_FOUND` | 없는 `model_id`·chat `model` | 목록 다시 조회 |
| 409 | `MODEL_NOT_READY` | 학습 미완료·실패 모델 | 다른 모델 |
| 409 | `MODEL_NOT_DEPLOYED` | 배포 해제·VL/LLM 미실행 | 목록 다시 조회 |
| 411 | `LENGTH_REQUIRED` | `Content-Length` 없음 | 클라이언트 설정 |
| 413 | `PAYLOAD_TOO_LARGE` | 크기·장수 초과(`detail`) | 줄여서 보내기 |
| 415 | `INVALID_IMAGE` | 이미지로 읽을 수 없음(`detail.filename`) | 파일 확인 |
| 422 | `VALIDATION_ERROR` | `files` 없음, 옵션 범위, chat 본문 형식 | `detail` 보고 수정 |
| 500 | `INTERNAL_ERROR` | 서버 내부 오류 | 재시도, 계속되면 `request_id`로 문의 |
| 502 | `UPSTREAM_UNAVAILABLE` | 모델 서버 연결 실패 | 재시도 |
| 503 | `GPU_OUT_OF_MEMORY` | 추론 GPU 메모리 부족 | 재시도, 장수 줄이기 |
| 504 | `UPSTREAM_TIMEOUT` | 모델 응답 시간 초과 | 재시도, `max_tokens` 줄이기 |

## 7. 운영 참고

- **타임아웃:** 조회 10초, 추론 60초 권장(규약 §6). 배포 직후·재시작 뒤 첫 추론은 모델을 올리느라 느립니다.
- **동시성:** 같은 모델 요청은 한 번에 하나씩 처리합니다. 처리량이 필요하면 여러 장을 한 요청(최대 16장)에 묶습니다.
- **추론 기록:** 모든 추론은 이력이 남습니다. 운영 설정 `PREDICT_SAVE`(`all`·`failed`·`off`)에 따라 요청·응답·입력 이미지·결과 이미지를 Wezard 서버에 `PREDICT_RETENTION_DAYS`일(기본 30일) 보관하고 관리자 화면에서만 봅니다. 운영 값은 연동 전에 함께 정합니다.

## 8. 변경 이력

| 날짜 | 내용 |
| --- | --- |
| 2026-10-12 | v1 — 모델 목록·정보·`model.json`·이미지 추론·chat, `dataset_external_ref`, `error.retryable`, `X-Request-ID` 규칙(통신 규약 v1) |
| 2026-10-12 | 추론 상세 보관(`PREDICT_SAVE`, §7). API 요청·응답은 그대로 |
| 2026-10-13 | 문서를 API 호출에 필요한 내용으로 줄임(연동 적용 결과·Python 예시·운영 점검 목록 삭제). 계약 내용은 그대로 |
| 2026-10-13 | 이상 탐지 `heatmap_png_base64` 색 기준을 이미지별 최솟값~최댓값에서 응답 `threshold` 고정(0.5T 파랑 ~ T 초록 ~ 1.5T 빨강)으로 바꿈(§5.3). 요청·응답 필드는 그대로 |
| 2026-10-13 | 예시를 `fan-panel` v3 실제 값으로 바꿈(이상 탐지 AUROC 계산 오류 수정·임계값을 정상·결함 점수 사이 가운데로 산정한 재학습 모델). 계약 내용은 그대로 |
