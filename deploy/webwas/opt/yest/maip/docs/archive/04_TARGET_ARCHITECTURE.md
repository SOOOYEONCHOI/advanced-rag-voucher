# 04. Target Architecture (확정)

- 기준일: 2026-09-30
- 적용된 Decision: DEC-001 ~ DEC-027 전부 (권장안 채택) + `USER_DECISIONS.md` §1.5 Backbone 조정 O-1 ~ O-7
- 상위 규범: `ManufacturingAIPlatform_MES_Backbone_통합구축_프롬프트.md`

---

## 1. 전체 Architecture

```text
현장 클라이언트                             관리/작업자
┌──────────────────────────┐              ┌──────────────┐
│ VisionInspectionClient.exe│              │ Web Browser  │
│  Camera · Overlay · Retry │              └──────┬───────┘
└────────────┬──────────────┘                     │
             │ HTTPS 443                          │ HTTPS 443
             │ X-Client-ID / X-API-Key            │ Session
             ▼                                    ▼
┌─────────────────────────────────────────────────────────────┐
│ Web/WAS Server  (Public Subnet, Ubuntu 24.04)               │
│ Nginx → gunicorn → ManufacturingAIPlatform (Django 5.0)     │
│                                                             │
│  /api/v1/*          Client 호환 계층 (vision 계약 그대로)   │
│  /gui/<code>/       업무 화면 (MES iframe 탭 셸)            │
│  /api/<task>/<view> 화면용 API (MES 동적 dispatch + 인가)   │
│  /page/<f>/<n>      팝업·모달                                │
│                                                             │
│  ├─ System Management                                       │
│  ├─ Data Management                                         │
│  └─ Vision Inspection Management                            │
│                                                             │
│  domain/services/gpu/gateway.py  ← InferenceGateway (Stub)  │
└───────────────┬─────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────┐
│ PostgreSQL  (Private Subnet) — 단일 통합 DB                  │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ GPU Server (Private Subnet)   ※ 이번 범위 밖                 │
│  - 미구현. Boundary/Interface만 정의                          │
│  - Reference: vision-inspection/server/infrastructure/       │
│               inference/{torchvision_adapter,patchcore_...}  │
└─────────────────────────────────────────────────────────────┘

워커 프로세스 (같은 호스트, systemd)
  manage.py run_worker          ← BackgroundJob (QUALITY / EXPORT)
  manage.py purge_vision_images ← systemd timer 03:30
```

**원칙**

- 외부 사용자와 Client는 ManufacturingAIPlatform만 접근한다.
- Client와 Browser는 GPU Server를 직접 호출하지 않는다(현재는 GPU Server 자체가 없다).
- 추론이 필요한 경로는 `InferenceGateway` Stub을 거치며, 현재는 항상 "미구성"을 반환한다.
- **GPU Runtime 코드는 ManufacturingAIPlatform에 존재하지 않는다.** `torch`·`torchvision`은 의존성에서 제외한다.

---

## 2. Infrastructure

| 구성 | 값 | 근거 |
|---|---|---|
| OS | Ubuntu 24.04 LTS | DEC-020 |
| 웹서버 | Nginx (HTTPS 443 종단, `/static/`만 직접 서비스) | DEC-020, DEC-019 |
| 앱서버 | gunicorn (sync worker) + systemd | DEC-020 |
| 워커 | `manage.py run_worker` × N (systemd) | DEC-022 |
| 정기 작업 | systemd timer — `purge_vision_images` 03:30 | DEC-022 |
| DB | PostgreSQL, 신규 단일 DB | DEC-011 |
| 파일 | `STORAGE_ROOT` 단일 루트, 권한 확인 View 전용 | DEC-019 |
| 비밀 | 전부 환경변수 (`SECRET_KEY`, DB, `STORAGE_ROOT`, `GPU_SERVER_BASE_URL`, `GPU_SERVICE_KEY`) | D2 수정 |
| Object Storage | **사용하지 않음** | 원 프롬프트 §1.1 |
| MQTT / DAS | **사용하지 않음** | DEC-023 |

### 저장소 레이아웃

```text
$STORAGE_ROOT/
├─ datasets/{project_id}/{dataset_id}/...   데이터셋 이미지·썸네일·원본(편집 전)
├─ standards/{project_id}/...                데이터 표준 예시 이미지
├─ exports/{export_job_id}/...               Export zip
├─ inspections/{YYYY}/{MM}/{DD}/{id}/        검사 원본 · Heatmap
├─ overlays/{inspection_item_id}/            Overlay 이미지
├─ covers/{project_id}/                      과제 대표 이미지
└─ attachments/                              MES 공통 첨부
```

업로드 상한: 데이터셋 이미지 30MB/파일, 검사 이미지 10MB, Overlay 10MB. Export 다운로드는 스트리밍.

---

## 3. Web/WAS — 프로젝트 구조

MES 구조를 그대로 계승한다(DEC-001). Django App은 `app`·`domain` 2개를 유지하고, 업무 분리는 디렉터리로 한다.

```text
manufacturing_ai_platform/
├─ configurations/
│  ├─ settings.py              환경변수 기반. TEMPLATES를 if DEBUG 밖으로(D3)
│  ├─ urls.py                  MES 디스패처 + /api/v1/* 호환 계층
│  ├─ middleware/
│  │  ├─ response.py           MES RemoveCriticalResponseHeader
│  │  └─ request_id.py         상관관계 ID (AIDataHub 이식)
│  └─ wsgi.py
├─ app/
│  ├─ views/
│  │  ├─ __init__.py           MESBaseView / ApiModuleView(+인가 훅) / GUITemplatesView /
│  │  │                        TemplatePathView / FilesView / SystemDefaultRenderer
│  │  ├─ account.py            로그인·로그아웃 (+throttle, 세션 DB 재확인)
│  │  ├─ system/               사용자·그룹·메뉴권한·코드·로그·모델매핑
│  │  ├─ definition/           unit·company·depart·code  (최소 기준정보)
│  │  ├─ data/                 ★ 데이터 관리 (AIDataHub 이식)
│  │  ├─ vision/               ★ 비전 검사 관리 (vision Server 이식)
│  │  ├─ api_v1/               ★ VisionInspectionClient 호환 계층
│  │  ├─ files/                권한 확인 파일 제공
│  │  └─ popup/
│  ├─ templates/
│  │  ├─ app/                  index.html · layout_page.html · login.html
│  │  ├─ system/  definition/
│  │  ├─ data/                 ★ 데이터 관리 화면
│  │  ├─ vision/               ★ 비전 검사 관리 화면
│  │  └─ page/                 팝업·모달
│  └─ static/
│     ├─ assets/               MES 공통 (Hyper 테마·common.js·grid.js)
│     ├─ wezongrid/            MES 그리드
│     └─ data/                 ★ Canvas 모듈 (AIDataHub에서 추출)
│        ├─ annotation-canvas.js     BBox·Polygon·Mask 편집, Zoom·Pan
│        ├─ labeling-page.js         claim·heartbeat·draft·submit
│        ├─ review-page.js           승인·재작업
│        └─ preprocess-canvas.js     회전·원근보정·크롭·리사이즈
├─ domain/
│  ├─ models/
│  │  ├─ system.py user.py     MES 계승 (+ mes.py에서 Factory/Company/Depart/Unit만 추출)
│  │  ├─ data.py               ★ Tenant·Project·Dataset·ImageAsset·Annotation·LabelingTask 등
│  │  └─ vision.py             ★ VisionProcess·VisionProduct·InspectionItem·Overlay·
│  │                             VisionClient·VisionModel·ItemModelMapping·Inspection 등
│  ├─ services/
│  │  ├─ _common/ _form/ sql.py logging.py common.py date.py file.py combo.py   MES 계승
│  │  ├─ account.py system.py  MES 계승
│  │  ├─ data/                 ★ dataset·image·preprocess·annotation·labeling_task·
│  │  │                          review·quality·version·export/·job·ingest
│  │  ├─ vision/               ★ catalog·overlay·client_auth·client_admin·inspection·
│  │  │                          result_image·model_admin·ingest
│  │  └─ gpu/
│  │     └─ gateway.py         ★ InferenceGateway (Stub) + GpuServerClient (미구현)
│  ├─ gui.py                   GUI_ITEMS 정리 + apiPermissionMap 실사용
│  └─ migrations/0001_initial.py
├─ tests/                      ★ 신규 (system data vision api permissions integration e2e)
├─ scripts/
├─ manage.py
└─ requirements.txt            torch·scikit-learn·MQTT·pyodbc·wfastcgi 제외
```

> **`ai/`·`ml/`·`gpu/`·`inference/` Django App을 만들지 않는다**(Backbone §12). GPU 경계는 `domain/services/gpu/` 모듈 하나로 둔다.

---

## 4. Domain 책임

```text
ManufacturingAIPlatform
│
├── System Management  (MES 계승)
│   ├─ 사용자 / 사용자그룹 / 메뉴권한
│   ├─ 메뉴(menu_folder · menu_item)
│   ├─ 공통코드 · 단위 · 업체 · 부서 · 공장
│   ├─ 다국어 라벨코드 · 그리드 설정
│   ├─ 로그(로그인 · 메뉴 · 시스템 · 배치)
│   └─ 검사항목 ↔ 모델 매핑        ← vision에서 이관
│
├── Data Management  (AIDataHub 이식)
│   ├─ 검사 과제(Project) · 인원 배정 · 삭제 승인
│   ├─ 데이터셋(Dataset) · 라벨 클래스 · 데이터 표준
│   ├─ 이미지 수집(업로드) · 정제(전처리) · 조회
│   ├─ 라벨링(분류 / 탐지 / 이상) · 검수
│   ├─ 데이터 품질 점검 · 스냅샷(불변 버전)
│   ├─ Export 8포맷
│   └─ 작업 대기열 · 활동 이력
│
└── Vision Inspection Management  (vision Server 이식)
    ├─ 검사 현황(대시보드)
    ├─ 검사 Client(장치) · API Key 발급
    ├─ 검사 공정 · 검사 대상 제품 · 검사 항목 · 검사 순서
    ├─ Overlay 관리
    ├─ AI 모델(메타데이터)            ← Runtime은 GPU Server 책임
    ├─ 검사 요청 수신 · 결과 저장 · 이력 조회
    ├─ 이미지 보존 정책
    └─ 검사 이미지 → 데이터셋 이관     ← Data Management와 연결

GPU Server  (이번 범위 밖)
    └─ Model Artifact · Load/Unload · GPU Memory · Runtime · Inference
```

### Data ↔ Vision 연결

```text
vision_data_item  = 검사항목이자 데이터 저장소 (단일 엔티티, §1.6 O-8)
   ├─1:N─ vision_data_dataset ─1:N─ vision_data_imageasset ─1:N─ vision_data_annotation
   ├─1:N─ vision_inspection (검사 1건 ─1:1─ imageasset)
   ├─1:0..1─ vision_overlay
   └─1:N─ vision_item_model_mapping ─N:1─ vision_model
                                        │
vision_inspection(검사 결과) ──이관──> vision_data_imageasset + annotation  (DEC-026)
                                        │
vision_data_labelclass  ←매핑→  vision_model이 내는 class_name          (운영 규칙: 이름 일치)
```

---

## 5. Database 기준

| 항목 | 값 | 근거 |
|---|---|---|
| DB | 신규 단일 PostgreSQL DB | DEC-011 |
| 마이그레이션 | Django migrations, `0001_initial` 하나로 시작 | DEC-011 |
| 기존 3개 DB | **보존**(초기화하지 않음) | DEC-011 |
| `DEFAULT_AUTO_FIELD` | `BigAutoField`. MES 계승 모델은 명시 `AutoField` 유지 | DEC-017 |
| `USE_TZ` | `False`, `TIME_ZONE='Asia/Seoul'`. `/api/v1` 경계에서만 UTC 변환 | DEC-016 |
| 테이블 접두어 | MES 계승은 기존 이름 / 데이터관리 `vision_data_*` / 비전검사 `vision_*` / (장래) GPU `gpu_*` | DEC-025 |
| 멀티테넌시 | `Tenant` 행 1개 고정(CheckConstraint), RLS 정책 유지 | DEC-004 |
| PG native enum | 사용하지 않음. `CharField(choices)` | DEC-011 |
| 연결 | `CONN_MAX_AGE=60`, `CONN_HEALTH_CHECKS=True` | AIDataHub 계승 |

### Table Ownership

이번 단계는 **단일 서비스(Web/WAS)가 모든 테이블을 소유·Write**한다. GPU Server가 없기 때문이다.

| Domain / Table | Read: Web/WAS | Write: Web/WAS | Read: GPU | Write: GPU | 최종 Owner |
|---|:-:|:-:|:-:|:-:|---|
| `auth_user`, `user_profile`, `user_group`, `user_group_menu` | O | O | - | - | Web/WAS |
| `menu_folder`, `menu_item`, `sys_code`, `sys_option`, `label_code*` | O | O | - | - | Web/WAS |
| `factory`, `company`, `depart`, `unit` | O | O | - | - | Web/WAS |
| `login_log`, `menu_use_log`, `sys_log` | O | O | - | - | Web/WAS |
| `vision_data_*` (과제·데이터셋·이미지·어노테이션·라벨링·품질·스냅샷·Export·Job) | O | O | - | - | Web/WAS |
| `vision_data_item`(검사항목 = 저장소), `vision_overlay` | O | O | (장래 R) | - | Web/WAS |
| `vision_client` | O | O | - | - | Web/WAS |
| `vision_inspection` (검사 결과) | O | O | - | - | Web/WAS |
| `vision_item_model_mapping` (+`threshold_override`) | O | O | (장래 R) | - | Web/WAS |
| `vision_model` (모델 메타데이터) | O | O | (장래 R/W) | - | **Web/WAS (잠정)** → 장래 GPU 이관 |
| ~~`vision_retention_policy`, `vision_image_migration`~~ | — | — | — | — | **제외**(§1.6 O-9·O-10) |
| (장래) `gpu_model_version`, `gpu_training_job`, `gpu_evaluation_result` | (R via API) | - | O | O | GPU Server |

**장래 GPU 분리 대비**: `vision_item_model_mapping`은 `model` FK와 함께 `model_code`·`model_version` 문자열을 **비정규화 저장**한다. GPU 분리 시 FK만 제거하면 된다(DEC-010).

---

## 6. Client (VisionInspectionClient.exe)

- **코드 변경 없음.** 설정 파일의 `base_url`만 ManufacturingAIPlatform으로 바꾼다(DEC-007).
- 사용하는 API 6종의 계약·응답 봉투·오류 코드·UTC 시각·이미지 URL prefix(`/api/v1` 하위 상대경로)를 그대로 유지한다.
- 상세는 `06_API_COMPATIBILITY_PLAN.md`.

---

## 7. Web Browser / 표현 계층

| 항목 | 확정 |
|---|---|
| 셸 | MES `app/index.html` + `.page-tabs` + iframe. **AIDataHub SPA Shell 미사용**(Backbone §20-3) |
| 업무 화면 base | MES `app/layout_page.html` (`{% block content %}` / `{% block scripts %}`) |
| 그리드 | WeZonGrid |
| Ajax | `AjaxUtil` 비동기. **`getSyncData` 사용 금지**(공통 셸의 기존 동기 호출도 비동기로 교체) |
| 모달 | MES `modal.open({iframe:{...}})` |
| `X_FRAME_OPTIONS` | `SAMEORIGIN` |
| Canvas 화면 | 라벨링·검수·정제 — **AIDataHub Canvas JS 모듈을 `app/static/data/`로 추출해 재사용**(Backbone §6). MES 템플릿 안에서 동작하며 `spa.js` 의존을 제거한다 |
| 화면 문구 | 한국어 직접 작성(DEC-021) |
| 응답 규약(화면용 API) | MES 규약 — 조회는 행 리스트, 변경은 `{success, message}` |

### Canvas 모듈 이식 경계

```text
가져오는 것  BBox·Polygon·Mask 편집, Zoom·Pan, 좌표 변환, 어노테이션 상태 표현,
             claim/heartbeat/draft/submit 호출 시퀀스, 검수 승인·재작업 흐름
버리는 것    spa.js, #content-canvas 교체, destroy() 재진입 대응, layout.html,
             AjaxUtil {ok,data} 규약(→ MES 규약 래퍼로 감쌈)
```

---

## 8. 인증 / 권한

### 8.1 Web 사용자 (MES 기준)

```text
auth_user ──1:1── user_profile ──FK── user_group ──1:N── user_group_menu(MenuCode, AuthCode)
```

- 관리자 판정: `is_superuser` 또는 `user_group.Code in ('dev','admin')`.
- `user_profile`에서 `access_token`·`refresh_token` 컬럼 제외(DEC-002 A′).
- 로그인에 **throttle + 세션 DB 재확인**을 추가한다(vision에서 이식, DEC-018).
- `login_log`에 IP·User-Agent·실패 사유를 기록한다.

### 8.2 2단계 인가 (DEC-003, DEC-014, Backbone §14)

```text
[1차] 메뉴 권한   user_group_menu(MenuCode=gui_code).AuthCode ∈ {R, RW}
                  GET  → R 필요 / POST → W 필요
                  적용 지점: GUITemplatesView (화면)  +  ApiModuleView (API, 신규)
                             TemplatePathView (팝업, 신규)
        ↓
[2차] 과제 권한   project_assignment.role(PROJECT_MANAGER|WORKER)
                  project_group_access(can_view|can_upload|can_label)
                  적용 지점: data/* 뷰의 capability 검사 (ACTION_CAPABILITIES 이식)
                  대상 과제를 볼 수 없으면 404, 관리자 전용이면 403
```

**`ApiModuleView` 인가 훅**

```text
dispatch()
  ├─ 로그인 확인                      (기존)
  ├─ get_menu_code_by_taskview(task, view)   ← 死코드였던 apiPermissionMap 실사용
  │    ├─ 매핑 없음  → [1단계] 경고 로그 후 통과 / [2단계] 403 기본 거부
  │    └─ 매핑 있음  → check_user_auth(user, menu_code) 로 R/W 판정
  ├─ ANONYMOUS_WHITELIST 확인          (files/upload, system/combo, popup/* 등 명시 화이트리스트)
  └─ 뷰 함수 실행
```

### 8.3 VisionInspectionClient 인증

- `X-Client-ID` + `X-API-Key`. 서버는 SHA-256 해시 비교(vision 구현 이식).
- 누락 → 401 `AUTH_REQUIRED`, 불일치/비활성 → 401 `AUTH_INVALID`.
- Client별 분당 요청 한도(기본 120). CSRF 면제.
- **사용자 세션과 혼합하지 않는다**(원 프롬프트 §16.2).

### 8.4 Web/WAS ↔ GPU Server

- 방식 확정: **Private Subnet + `X-Service-Key` 헤더**(DEC-015).
- **이번 범위에서는 구현하지 않는다.** `GpuServerClient`에 헤더 조립 코드와 설정 키(`GPU_SERVER_BASE_URL`, `GPU_SERVICE_KEY`)만 정의하고 호출부는 Stub이다.

---

## 9. GPU Server Integration Boundary

```python
# domain/services/gpu/gateway.py
class GpuNotConfiguredError(Exception):
    """GPU Server가 구성되지 않았다. 검사는 RECEIVED로 저장되고 추론은 실행되지 않는다."""
    code = "GPU_INFERENCE_NOT_CONFIGURED"


class InferenceGateway:
    """검사 추론 경계. 이번 범위에서는 항상 미구성을 반환한다.

    GPU Server 구현 시 GpuServerClient 로 교체하며,
    이 시그니처를 유지하면 Vision Domain 을 다시 설계하지 않아도 된다.
    """

    def is_configured(self) -> bool:
        return False

    def infer(self, *, inspection_type, model_code, model_version,
              threshold, image_bytes, request_id) -> "InferenceResult":
        raise GpuNotConfiguredError()


class GpuServerClient(InferenceGateway):
    """미구현. 향후 HTTP 구현체. Reference: vision-inspection/server/
    infrastructure/inference/{torchvision_adapter,patchcore_adapter}.py
    """
```

**호출 지점은 단 한 곳**: `domain/services/vision/inspection.py` 의 `receive_capture()`. 이미지 저장·검사 행 생성까지 수행한 뒤 게이트웨이를 호출하고, `GpuNotConfiguredError`면 `status='RECEIVED'`로 확정한다. 이는 **현재 vision Server가 ModelMapping이 없을 때 하는 동작과 동일**하므로 Client 계약을 위반하지 않는다.

**이번 범위에 없는 것**: torch/torchvision 의존성, 모델 아티팩트 load·검증, Heatmap 생성, Result Image 중 bbox·heatmap 합성(결과가 없으므로 404 `RESULT_IMAGE_NOT_AVAILABLE`), Training, Model Load/Unload.

---

## 10. 검사 요청 End-to-End 흐름 (현 단계)

```text
Industrial Camera
   ↓
VisionInspectionClient.exe   request_id 생성(UUID4)
   ↓ HTTPS  POST /api/v1/inspections  multipart(image, metadata)
   ↓        X-Client-ID / X-API-Key
ManufacturingAIPlatform
   │
   ├─ 1. Client 인증 (해시 비교, active 확인, last_seen 갱신)
   ├─ 2. rate limit 확인
   ├─ 3. metadata 파싱·길이 검증        실패 → 422 METADATA_INVALID (이미지 미저장)
   ├─ 4. idempotency: request_id 조회    기존 있음 → 같은 Client면 200 기존 결과 / 다른 Client면 409
   ├─ 5. 카탈로그 정합성 검증            item.active / item.product_id / product.process_id
   ├─ 6. 이미지 decode 검증 (Pillow)
   ├─ 7. 원본 저장  $STORAGE_ROOT/inspections/YYYY/MM/DD/{id}/original.{ext}
   ├─ 8. vision_inspection 행 생성 (status=RECEIVED) · commit
   ├─ 9. 활성 ModelMapping 조회
   │      ├─ 없음                      → status 유지 RECEIVED
   │      └─ 있음 → InferenceGateway.infer()
   │                 └─ GpuNotConfiguredError → status 유지 RECEIVED
   │                    (error_message 에 GPU_INFERENCE_NOT_CONFIGURED 기록)
   └─ 10. 응답  200 {"data": {..., "status": "RECEIVED", ...}}
   ↓ HTTPS
VisionInspectionClient.exe   결과 표시 (판정 없음 = 추론 미실행)

[재전송]  Client retry → GET /api/v1/inspections/by-request/{request_id} 선조회 → 동일 결과 반환
```

**GPU Server 연결 후 바뀌는 곳은 9단계뿐이다.** 1~8, 10과 Client 계약은 그대로다.

---

## 11. 백그라운드 처리

```text
요청 → JobService.enqueue_*() → BackgroundJob(QUEUED) → 202 응답
                                        ↓
                        run_worker: _claim_next (FOR UPDATE SKIP LOCKED, 짧은 트랜잭션)
                                        ↓
                        _run_claimed  (본문은 별도 트랜잭션, tenant_atomic 안)
                                        ↓
                        COMPLETED / FAILED(+error_message, attempt_count, next_retry_at)
```

| JobType | 내용 | 화면 폴링 |
|---|---|---|
| `QUALITY` | 데이터 품질 점검 4종 | 1.5초 × 10회 |
| `EXPORT` | Dataset Export 8포맷 | 3초 × 20회 |
| ~~`MIGRATION`~~ | **제외**(§1.6 O-9) — 검사 이미지는 접수 시점에 동기 연계된다 | — |

- 재시도·백오프를 추가한다(AIDataHub 원본에 없던 것, DEC-022).
- `error_message` 길이를 255자에서 확대한다.
- 보존 정책 정리는 큐가 아니라 `manage.py purge_vision_images` + systemd timer.

---

## 12. 적용된 Decision ID

| 영역 | Decision |
|---|---|
| 프로젝트 골격·범위 | DEC-001, DEC-023, §1.5 O-3 |
| 인증·권한 | DEC-002, DEC-003, DEC-014, DEC-018 |
| 데이터 도메인 | DEC-004, DEC-005, DEC-026 |
| 비전 도메인·모델 | DEC-009, DEC-010, §1.5 O-2 |
| GPU 경계 | DEC-006, DEC-008, DEC-015, DEC-027, §1.5 O-1 |
| Client 계약 | DEC-007 |
| DB | DEC-011, DEC-012, DEC-016, DEC-017, DEC-025 |
| UI | DEC-013, DEC-021, §1.5 O-4 |
| 운영 | DEC-019, DEC-020, DEC-022, DEC-024 |
