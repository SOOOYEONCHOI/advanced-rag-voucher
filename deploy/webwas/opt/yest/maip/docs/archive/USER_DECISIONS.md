# 제조AI플랫폼 사용자 결정 사항

## 0. 문서 상태

- 분석 기준일: 2026-09-30
- 분석 대상 Commit/Branch: **확인 불가** — `C:\projects\yest`와 세 하위 프로젝트 모두 git 저장소가 아니다. 소스 스냅샷 기준으로 분석했다.
- 분석 근거 문서: `01_CURRENT_STATE_ANALYSIS.md`, `02_FEATURE_MAPPING.md`, `03_CONFLICT_ANALYSIS.md`
- 전체 결정 항목 수: **27**
- 미결정 항목 수: **0**
- Blocker 수: 8 → **전부 결정됨**
- 상태: `DECIDED` (2026-09-30)

### 결정 기록

- **2026-09-30 사용자 결정**: "의사결정 항목은 모두 추천안으로 진행" → **27건 전부 권장안(Option A 또는 명시된 권장 Option) 채택**.
- 같은 날 `ManufacturingAIPlatform_MES_Backbone_통합구축_프롬프트.md`(이하 **Backbone 프롬프트**)가 추가로 제시되었다. 이 문서는 일부 항목에서 기존 권장안을 **덮어쓴다.** 아래 §1.5에 덮어쓴 내역을 명시한다.
- **2026-09-30 사용자 추가 지시**: 검사항목 단일화, 검사 이미지의 접수 시점 자동 연계, 공정·제품·보존정책·이관기능 제거. 아래 **§1.6**에 정리했다.
- **권한 순서**: **§1.6 사용자 지시 > Backbone 프롬프트 > 기존 권장안.** 충돌 시 뒤의 것이 진다.
- 아래 §2의 각 DEC 블록 본문(선택지·권장 근거)은 **분석 근거로 원문 보존**한다. 각 블록의 `**결정 결과**` 칸은 일괄 확정되었으므로 개별 갱신하지 않았고, **확정 내역의 정본은 §1 요약표와 §1.5·§1.6**이다.
- **DEC-005·DEC-026은 폐기되었다.** §2의 해당 블록은 분석 기록으로만 남는다.

---

## 1. 의사결정 요약

| ID | 중요도 | 영역 | 결정 항목 | **최종 결정** | 상태 |
|---|---|---|---|---|---|
| DEC-001 | BLOCKER | Architecture | 통합 방식 | **Option A** — MES 트리를 복제해 골격으로 삼고 기능을 이식 | 결정됨 |
| DEC-002 | BLOCKER | Auth / DB | User·UserGroup·UserGroupMenu 정본 스키마 | **Option A′** — MES 스키마 정본 + `access_token`/`refresh_token` 제외 | 결정됨 |
| DEC-003 | BLOCKER | Auth | 권한 모델 범위 | **Option B** — MES 메뉴권한(1차) + 과제 역할·작업그룹(2차) 2단계 인가 | 결정됨 |
| DEC-004 | HIGH | DB / Architecture | 멀티테넌시·RLS 존치 | **Option B** — 단일 Tenant 고정, 스키마·RLS 유지 | 결정됨 |
| DEC-005 | BLOCKER | Domain | `Project`(검사 과제) 존치 | **폐기** (§1.6 O-8) — 검사항목 단일 테이블로 통합 | 폐기 |
| DEC-006 | BLOCKER | Architecture / GPU | GPU Server 정체성 | **범위 밖으로 변경** (Backbone §9) — §1.5 O-1 참조 | 결정됨(조정) |
| DEC-007 | BLOCKER | API / Client | Client 호환 전략 | **Option A** — Client 무변경, Django `/api/v1` 호환 계층 6종 | 결정됨 |
| DEC-008 | HIGH | Architecture / DB | 검사 이미지·결과 소유 | **Option A** — WEB 단독 소유·단독 Write. 추론 호출은 Stub | 결정됨(조정) |
| DEC-009 | HIGH | GPU / 범위 | MES `mlops_*` 관계 | **Option A** — 분리 유지, MES MLOps는 범위 제외 | 결정됨 |
| DEC-010 | HIGH | DB / API | 모델 참조 방식 | **Option B** — `model_code` + `model_version` 식별자 참조 + `threshold_override` | 결정됨(조정) |
| DEC-011 | BLOCKER | DB / Migration | 통합 DB 구성 | **Option A** — 신규 DB + 새 `0001_initial`. 기존 3개 DB 보존 | 결정됨 |
| DEC-012 | HIGH | DB / Migration | 데이터 이관 범위 | **Option A 잠정** — 신규 시작. N1 확인 후 Phase 8에서 재판정 | 결정됨(조건부) |
| DEC-013 | HIGH | UI | 표현 계층 규약 | **Option B** — MES 셸 + Canvas JS 모듈만 재사용. SPA Shell 미이관 | 결정됨 |
| DEC-014 | HIGH | Architecture / Security | API 라우팅·인가 | **Option A** — 동적 dispatch 유지 + `ApiModuleView` 인가 훅 추가 | 결정됨 |
| DEC-015 | HIGH | API / Security | WEB ↔ GPU 인증·장애 | **Option A(설계만)** — API Key 방식 확정, 구현은 Stub | 결정됨(조정) |
| DEC-016 | HIGH | DB / API | `USE_TZ` | **Option B** — `USE_TZ=False` + `/api/v1` 경계 UTC 변환 | 결정됨 |
| DEC-017 | HIGH | DB | PK 타입 | **Option A** — `BigAutoField` 기본, MES 모델은 명시 `AutoField` 유지 | 결정됨 |
| DEC-018 | HIGH | Auth | `admin_users` 처리 | **Option A** — 폐기 + throttle·세션 DB 재확인 이식 | 결정됨 |
| DEC-019 | HIGH | Operation | 파일 저장소 | **Option A** — 단일 `STORAGE_ROOT` + 권한 확인 View 전용 | 결정됨 |
| DEC-020 | HIGH | Operation | 배포 스택 | **Option A** — Ubuntu 24.04 + nginx + gunicorn + systemd | 결정됨 |
| DEC-021 | MEDIUM | UI | 다국어 | **Option A** — 1단계 한국어 고정, 라벨코드 인프라는 유지 | 결정됨 |
| DEC-022 | MEDIUM | Operation | 백그라운드 작업 | **Option A** — `BackgroundJob` + 워커 채택, 재시도·백오프 추가 | 결정됨 |
| DEC-023 | BLOCKER | 범위 | MES 이관 범위 | **Option B** — 시스템관리 + 최소 기준정보. MES와 **병행 운영** | 결정됨 |
| DEC-024 | MEDIUM | Security | 무인증 배포물 엔드포인트 | **Option A** — 현재 범위 제외 | 결정됨 |
| DEC-025 | HIGH | Domain | 네이밍 규칙 | **Option A** — 도메인 접두어 분리(`vision_*` / `vision_data_*` / `gpu_*`) | 결정됨 |
| DEC-026 | HIGH | Domain / API | 검사 결과 → 데이터셋 | **폐기** (§1.6 O-9) — 접수 시점 자동 연계로 대체 | 폐기 |
| DEC-027 | HIGH | GPU | 학습 범위 | **Option C로 변경** (Backbone §9) — 학습 전체 제외 | 결정됨(조정) |

상태 값: `결정됨` / `결정됨(조정)` = Backbone 프롬프트가 기존 권장안을 덮어씀 / `결정됨(조건부)`

---

## 1.5 Backbone 프롬프트에 의한 조정 (2026-09-30)

`ManufacturingAIPlatform_MES_Backbone_통합구축_프롬프트.md`가 기존 권장안을 덮어쓴 내역이다. **이 조정이 정본이다.**

### O-1. GPU Runtime 전면 제외 → DEC-006, DEC-008, DEC-015, DEC-027 변경

Backbone §9·§20-5의 지시:
> "이번 ManufacturingAIPlatform 통합 작업에서는 **GPU Server의 실제 AI Model Inference 구현은 제외한다.**"
> "`infrastructure/inference/*`, `DetectionInferencePort`, `AnomalyInferencePort` 등 AI Runtime 관련 코드는 ManufacturingAIPlatform으로 이동하지 않는다. 원본 vision-inspection 프로젝트 또는 향후 GPU Server 구현의 Reference Code로만 유지한다."

| 항목 | 기존 권장안 | **변경 후** |
|---|---|---|
| DEC-006 | vision Server를 GPU Server로 축소·개조 | **이번 범위에서 GPU Server를 만들지 않는다.** vision-inspection 프로젝트는 **손대지 않고 Reference로 보존**한다. ManufacturingAIPlatform에는 `GpuServerClient`(Stub)와 `InferenceGateway` 경계만 정의한다(Backbone §10) |
| DEC-008 | WEB 소유 + GPU에 이미지 전송 | **WEB 단독 소유는 유지.** 추론 호출부는 `InferenceGateway` Stub이 `GPU_INFERENCE_NOT_CONFIGURED`를 반환한다. 검사 요청은 이미지·행을 저장하고 `status: "RECEIVED"`로 응답한다(현재 vision Server가 ModelMapping 없을 때 하는 동작과 동일) |
| DEC-015 | API Key 인증 구현 | **설계·설정 항목만 정의**하고 실제 HTTP 호출은 구현하지 않는다. 장애 정책 표는 **향후 구현 시 적용할 계약**으로 문서에만 남긴다 |
| DEC-027 | Anomaly fit만 포함 | **Option C — 학습 전체 제외.** `fit-anomaly` API화도 하지 않는다 |
| 모델 아티팩트 업로드·검증 | GPU 소유 | **제외.** `infrastructure/inference/artifacts.py`가 `torch.load`를 쓰므로 GPU Runtime에 해당한다(소스 확인) |

**GPU 관련 Django App을 만들지 않는다**(Backbone §12): `ai/`, `ml/`, `gpu/`, `inference/` App 금지.

### O-2. 모델 관리 화면은 ManufacturingAIPlatform에 둔다 → DEC-009, DEC-010 보완

Backbone §8은 모델 **관리 UI**를 ManufacturingAIPlatform에 두라고 지시한다(모델 목록·Metadata·버전·활성 상태 조회, 검사항목↔모델 매핑, Threshold Override, 이력/상태). GPU Server가 없는 현재 단계에서는 **모델 메타데이터를 ManufacturingAIPlatform DB가 보유**해야 화면이 성립한다.

| 항목 | 확정 |
|---|---|
| `vision_model`(모델 메타데이터) 테이블 | **ManufacturingAIPlatform 소유** (vision `models` 테이블 이관). `name`, `inspection_type`, `version`, `artifact_path`, `runtime`, `threshold`, `active` |
| 모델 등록/수정/활성화 화면 | **이관**(vision `/admin/models` → `비전 검사 관리 > AI 모델`) |
| 모델 **아티팩트 파일 업로드·검증** | **제외**(O-1). 화면에서는 `artifact_path` 문자열만 입력받고 실제 파일 검증은 GPU Server 구현 시 추가 |
| `vision_item_model_mapping` | **ManufacturingAIPlatform 소유**, `model` FK로 `vision_model` 참조(같은 DB·같은 서비스이므로 이 단계에서는 FK 유지) + `threshold_override` 컬럼 추가 |
| 장래 GPU Server 분리 시 | `vision_model`의 소유권을 GPU로 옮기고 매핑은 `model_code`+`model_version` 식별자 참조로 전환한다(DEC-010 Option B). **그때 매핑 테이블 스키마만 바뀌도록** 지금부터 `model_code`·`model_version` 컬럼을 매핑 테이블에 **비정규화 저장**해 둔다 |
| MES `mlops_*` | DEC-009 그대로 **범위 제외**. 이름 충돌을 피하려 비전 모델 테이블은 `vision_model`로 명명 |

### O-3. 기존 테스트는 이관하지 않는다 → DEC-001 부기 사항 확정

Backbone §2·§19·§20-1·§20-2·§20-9:
> "세 프로젝트에 존재하는 기존 테스트 코드는 통합 프로젝트의 Acceptance Criteria로 사용하지 않는다." / "기존 Test를 통과시키기 위해 Architecture를 왜곡하지 않는다." / "기존 프로젝트 Test 통과 여부는 완료 조건이 아니다."

- AIDataHub 테스트 603건, vision Server 56파일, vision Client 37파일을 **이관하지 않는다.** 원본 프로젝트에 참고 자료로 남긴다.
- 특히 구조 고정 테스트(App Label·디렉터리 파일 집합·URL·Template Path·Service 위치·SPA 구조·Admin 구조)는 **무효화** 대상이다.
- ManufacturingAIPlatform 테스트는 최종 아키텍처 기준으로 **신규 작성**한다(Phase 10).
- 테스트 디렉터리: `tests/{system,data,vision,api,permissions,integration,e2e}/`

### O-4. 화면을 임의로 제외하지 않는다 → `02_FEATURE_MAPPING.md` 일부 수정

Backbone §4·§17·§20-7:
> "AIDataHub 및 vision-inspection Server가 현재 제공하는 업무 화면은 원칙적으로 모두 ManufacturingAIPlatform으로 이관한다. 화면 일부를 임의로 제외하지 않는다." / "기존 `[REMOVE]`는 신중하게 사용한다."

`02_FEATURE_MAPPING.md`에서 `[REMOVE]`/`[REPLACE]`로 표시했던 항목 중 **사용자 화면에 해당하는 것을 이관 대상으로 되돌린다.**

| 항목 | 기존 표기 | **변경 후** |
|---|---|---|
| vision Admin 대시보드 | `[REPLACE]` MES 대시보드 | **이관** — `비전 검사 관리 > 검사 현황`으로 재작성 |
| vision `GET /api/v1/history` + 검사 이력 화면 | `[ADAPT]` 또는 `[REMOVE]` | **이관 확정** — 화면과 API 모두 제공 |
| vision `/admin/migration`(이미지 내보내기) | `[REWRITE]` | **이관 확정** — DEC-026 내부 서비스 호출로 재작성 |
| vision `/admin/retention`(보존 정책) | `[ADAPT]` | **이관 확정** |
| AIDataHub 조직 관리 화면 | `[REMOVE]`/`[ADAPT]` | **미이관** — Backbone §5가 "사용자·권한·메뉴·로그인·공통 UI·시스템 관리는 MES로 대체"라고 명시. DEC-004 단일 Tenant 고정이므로 조직 관리 UI가 불필요 |
| AIDataHub 사용자·사용자그룹 관리 화면 | `[REPLACE]` | **미이관 유지** — Backbone §5 명시 |
| vision `/api/v1/licenses/sources`, `/client-packages` | `[REMOVE]` | **미이관 유지** — 업무 화면이 아니라 배포물 제공 경로(DEC-024) |

**처리 방식 분류를 Backbone §17 체계로 전환한다:**

```text
REUSE_LOGIC          전문 로직 그대로 재사용 (Annotation Geometry, Export, Quality, Overlay 계산, Client Contract)
ADAPT                로직 재사용 + MES 패턴에 맞게 조정
REWRITE              기능 개념만 유지하고 MES 구조로 재작성 (View/Template/URL/JS Wrapper)
REPLACE_WITH_MES     MES 공통 기능으로 대체 (사용자·권한·메뉴·로그인·공통 UI)
EXCLUDE_GPU_RUNTIME  GPU Runtime이라 이번 범위에서 제외
```

### O-5. 구현 순서를 Backbone §18의 Phase 0~11로 확정

기존 `01_CURRENT_STATE_ANALYSIS.md`가 참조한 원 프롬프트 §18의 Phase 0~9 대신 **Backbone §18의 Phase 0~11**을 사용한다. 상세는 `07_IMPLEMENTATION_PLAN.md`.

### O-6. DEC-012 조건부 확정

데이터 이관 범위는 N1(운영 데이터 규모) 확인이 선행되어야 한다. **Phase 8(DB Migration 및 Seed) 시작 전까지 확인**하고, 확인 결과에 따라 이관 스크립트를 Phase 8에 추가한다. 그때까지는 **Option A(신규 시작 + Seed)** 로 진행한다 — 개발·검증에 지장이 없고, 이관이 필요해져도 Phase 8에서만 작업이 늘어난다.

### O-7. Backbone 프롬프트에 대한 확인 요청 1건

Backbone §8은 모델 관리 화면을 ManufacturingAIPlatform에 두라고 하고, §9는 모델 아티팩트를 GPU Server 책임으로 둔다. 그 결과 **이번 단계의 모델 관리 화면은 "아티팩트 파일 없이 메타데이터만 등록하는 화면"**이 된다. 등록한 모델로 실제 검사를 돌릴 수는 없다(추론이 Stub이므로 일관된다).

→ 이 상태를 의도한 것으로 보고 진행한다. 만약 "모델 아티팩트 업로드까지는 이번에 포함"이 의도라면 알려주기 바란다. 그 경우 `torch` 의존성이 WEB에 들어오므로 O-1과 충돌한다.

---

## 1.6 사용자 요구사항에 의한 조정 — 검사항목 단일화 및 실시간 연계 (2026-09-30)

사용자가 Phase 0 완료 후 지시한 변경이다. **§1.5보다 이 절이 우선한다.**

### O-8. 검사항목을 단일 엔티티로 통합 → DEC-005 폐기

> "검사항목을 합쳐야 해. 비전검사에서의 공정 → 제품 → 검사항목 중 공정, 제품의 큰 분류는 없어도 된다."

공정·제품이 없어지면 vision `inspection_items`에 남는 필드가 전부 `Project`로 흡수되므로, **1:1 FK 연결(DEC-005)이 아니라 테이블 자체를 하나로 합친다.**

| vision `inspection_items` | 통합 후 `vision_data_item` |
|---|---|
| `name` | `name` |
| `description` | `description` |
| `inspection_type` (DETECTION/ANOMALY) | `task_type` (OBJECT_DETECTION/ANOMALY_DETECTION/CLASSIFICATION) |
| `active` | `status` (ACTIVE/PAUSED/DELETION_PENDING) |
| `code` | `code` **신규** — 전역 unique (Q8) |
| `display_order` | `display_order` **신규** |
| `product_id` | **삭제** |

- 테이블명: `vision_data_project` → **`vision_data_item`**. 이 한 테이블이 **검사항목이자 데이터 저장소**다.
- **`processes` · `products` 테이블과 화면을 만들지 않는다.**
- `vision_inspection`(검사 결과) · `vision_overlay` · `vision_item_model_mapping` 의 FK가 `vision_data_item` 을 가리킨다.
- `Dataset` · `LabelClass` · `ProjectAssignment` · `ProjectGroupAccess` · `ProjectDeletionRequest` · `QualityRun` · `ExportJob` 등 기존 `Project` 참조는 **관계 구조를 바꾸지 않고** 대상 모델명만 따라간다.
- **효과**: `05_DATABASE_MIGRATION_PLAN.md` §5의 "Vision 기준정보가 Data Management보다 먼저 생성되어야 한다"는 순서 제약과 `07_IMPLEMENTATION_PLAN.md` Task 4.2(FK 나중 활성화)가 **사라진다.**

### O-9. 검사 이미지 = 데이터관리 업로드 이미지 → DEC-026 폐기

> "클라이언트로부터 전송된 이미지는 데이터관리플랫폼 기준으로 업로드된 상태로 유지하고, 라벨링·검수 작업을 이어갈 수 있게 해야 한다."
> "클라이언트로부터 전송된 원본 이미지는 무조건 저장한다."

**AIDataHub에 이미 이 경로가 있다.** 새 연계 로직을 만드는 것이 아니라 기존 업로드 서비스를 Client 수신 경로에서 호출한다.

```text
AIDataHub/domain/services/dataset/image.py:55
  upload_images(project, files, actor, requires_labeling)
    → ProjectService.get_or_create_upload_dataset(project)   # 사용자가 데이터셋을 고르지 않는다
    → ImageAsset(status=UPLOADED, label_status=UNLABELED)
```

- **사후 batch(관리자 실행) → 접수 시점 자동**으로 방향이 바뀐다.
- `Dataset`은 검사항목당 1개(`version="v0.1"`, `name="일반 사용자 업로드"`)가 자동 생성되는 **내부 컨테이너**다. 화면에 노출하지 않는다. 사용자가 인지하는 "데이터셋 담기"는 Export 시점의 `DatasetVersion`(불변 스냅샷)이며 그것은 그대로 유지한다.
- **이미지 파일은 한 벌만 저장한다**(Q3). `vision_inspection.image_asset` FK로 참조하고 실체는 `ImageAsset.file`이 갖는다. `vision_inspection.image_path` 컬럼은 만들지 않는다.
- **sha256 중복을 거부하지 않는다**(Q4). `upload_images`의 중복 차단은 **Client 수신 경로에서만 우회**한다. 사람이 화면에서 올리는 업로드의 중복 차단은 그대로 둔다.
- **항상 라벨링 대상**(Q6) — `requires_labeling=True` 고정.
- **행위자는 Client 전용 계정**(Q5). `vision_client` 등록 시 전용 Django 사용자를 자동 생성하고, `upload_images(actor=...)` 와 `ActivityLog` 에 그 계정을 남긴다. 이 계정은 **웹 로그인이 불가능해야 한다**(`set_unusable_password()`).

### O-10. 이미지 보존 정책 제거

> "이미지 보존정책 삭제."

`retention_policies` 테이블, `retention.py` 서비스, `wm_vis_retention` 화면, 정리 command·timer를 **만들지 않는다.** 이미지는 삭제되지 않는다.

O-9에서 파일을 한 벌만 저장하기로 했으므로, 보존 정책이 남아 있었다면 "원본이 지워져 데이터셋이 깨지는" 충돌이 생겼을 것이다. 이 결정으로 그 충돌 자체가 없어진다.

### O-11. Client 계약은 합성 공정·제품으로 유지 (Q1 = A)

공정·제품을 DB에서 없애도 **Client는 계층을 강제한다.**

```python
# client/.../server_client.py:283   키가 없으면 KeyError
for process_row in data["processes"]:
    for product_row in process_row["products"]:
        ... product_row["inspection_items"]

# client/.../domain/models/inspection.py:101   0 이하면 예외
for name in ("process_id", "product_id", "inspection_item_id"):
    if getattr(self, name) <= 0: ...
```

| 항목 | 확정 |
|---|---|
| `GET /api/v1/catalog` | **고정 공정 1개 · 제품 1개를 합성**해 기존 응답 형태를 그대로 유지한다. `id=1`, `code="ALL"`, `name="전체"`, `display_order=0` |
| `POST /api/v1/inspections` metadata | `process_id` · `product_id` 를 **받되 값을 검증하지 않고 버린다.** `inspection_item_id` 만 사용한다 |
| Client | **무수정.** `base_url` 만 변경 |
| Client 화면 | 검사항목 드로어에 "전체" 탭 하나만 표시된다(외형 변화) |
| 검사항목 규모 | **초기 2~5개**(사용자 확인 2026-09-30). 평평한 목록으로 충분하다. 늘어나면 §1.7 **F-5**로 전환하며, 응답 스키마가 같아 **Client 수정이 필요 없다** |

합성 값은 DB에 두지 않고 **응답 생성 시점에 상수로 만든다.** 테이블을 만들면 O-8과 모순된다.

> Client가 캐시한 검사항목 ID는 통합 후 전부 새 값이 된다. 카탈로그 `version` 지문이 바뀌므로 Client가 자동으로 다시 받는다. 별도 조치는 필요 없다.

### O-12. 추론 경계 — 모델이 매핑돼 있을 때의 동작

> "검사항목에 연결된 AI모델이 있으면 실행 후 결과를 리턴해야 한다(현재 GPU 서버의 AI모델을 연결해야 하나, 아직 개발되지 않음)."

O-1(GPU Runtime 전면 제외)은 **유지된다.** 이번 범위에서 만드는 것은 호출 지점과 계약이고, 구현체는 Stub이다.

| 상황 | 이번 범위의 동작 | GPU Server 구현 후 |
|---|---|---|
| 검사항목에 모델 매핑 없음 | `status: "RECEIVED"` | 동일 |
| 검사항목에 모델 매핑 있음 | `status: "RECEIVED"` + 서버 로그에 `GPU_INFERENCE_NOT_CONFIGURED` 경고 | `status: "SUCCESS"` + 판정·좌표·점수 |
| 이미지 저장 | **두 경우 모두 무조건 저장** | 동일 |

- 매핑이 있는데 추론이 실행되지 않은 검사는 **검사 결과 화면에서 "추론 미실행(GPU 미구성)"으로 구분해 표시**한다. `RECEIVED`만 보고 "모델이 없구나"로 오해하지 않게 하기 위함이다.
- `FAILED`를 반환하지 않는 이유: Client가 매 촬영마다 오류 타일을 띄우게 되어 현장 검사가 사실상 막힌다. 검사 접수와 판정은 분리한다.
- `InferenceGateway` / `GpuServerClient`(Stub) 경계는 `04_TARGET_ARCHITECTURE.md` §9 그대로다.

### O-13. 명칭 통일 — 과제/프로젝트 → 검사항목

> "데이터관리플랫폼의 프로젝트보단 검사항목이라는 명칭을 사용하도록 해줘."

| 대상 | 변경 |
|---|---|
| 화면 문구 | "과제" · "프로젝트" → **"검사항목"** (AIDataHub 템플릿에 과제 11곳 · 프로젝트 5곳 이상) |
| 메뉴 | `wm_data_project`(과제 관리) + `wm_vis_item`(검사 항목) → **`wm_data_item`(검사항목)** 1개 |
| 테이블 | `vision_data_project` → `vision_data_item` |
| 코드 식별자 | Django 모델명은 `InspectionItem`, 관련 서비스·뷰도 `item` 기준으로 명명 |

메뉴 위치는 **데이터 관리** 폴더의 첫 항목이다. 데이터셋·라벨링·검수·품질·Export가 전부 여기에 매달리므로 데이터 관리가 주(主)이고, 비전 검사 관리 메뉴에서는 이 화면으로 링크만 건다.

### O-14. 분류(CLASSIFICATION) 유형의 Client 노출은 보류 (Q2)

> "아직 미정이야. 분류는 단순히 정상/이상과 같은 예측된 분류 클래스를 출력하도록 하려 한다."

Client `InspectionType` enum은 `DETECTION` · `ANOMALY` 2종뿐이다(`client/.../domain/enums/inspection_type.py`). 분류를 추가하려면 **Client 수정과 현장 재배포가 필요하다.**

- 이번 범위: `GET /api/v1/catalog` 는 `task_type` 이 `OBJECT_DETECTION` · `ANOMALY_DETECTION` 인 검사항목만 내보낸다.
- `CLASSIFICATION` 검사항목은 **데이터 수집·라벨링 전용**으로 생성할 수 있고 Client에는 보이지 않는다.
- **향후 확장 항목으로 등록**(§1.7 **F-1**). 사용자 확인(2026-09-30): "분류 항목은 향후 확장 항목으로 기록".

### O-15. Q1~Q9 확정 결과

| # | 질의 | 확정 |
|---|---|---|
| Q1 | 공정·제품 제거 시 Client 계약 | **A** — 서버가 고정 공정·제품 1개 합성, Client 무수정 |
| Q2 | CLASSIFICATION 검사항목의 Client 노출 | **보류** — 카탈로그에서 제외, 수집·라벨링 전용 |
| Q3 | 이미지 이중 저장 | **한 벌만 저장** — `ImageAsset`이 보유 |
| Q4 | 동일 sha256 재전송 | **중복 허용** — Client 경로에서만 중복 차단 우회 |
| Q5 | 업로드 행위자 | **Client 전용 계정** — `vision_client` 등록 시 자동 생성 |
| Q6 | 라벨링 대상 여부 | **항상 대상** |
| Q7 | 기존 vision DB에 쌓인 검사 이미지 | **버린다** — 이관하지 않음 |
| Q8 | 검사항목 코드 | **전역 unique** |
| Q9 | 검사항목 삭제 | **승인 절차를 탄다** — `ProjectDeletionRequest` 유지. `DELETION_PENDING` 검사항목은 카탈로그에서 자동 제외(`access.py:56` 기존 동작) |

### O-16. 이번 변경으로 무효가 되는 계획 내용

| 문서 | 무효 항목 |
|---|---|
| `USER_DECISIONS.md` | **DEC-005 폐기**(1:1 FK → 단일 테이블), **DEC-026 폐기**(수동 batch 이관 → 접수 시점 자동) |
| `SCREEN_MAPPING.md` | `wm_vis_process` · `wm_vis_product` · `wm_vis_retention` · `wm_vis_migration` 삭제, `wm_vis_item` 은 `wm_data_item` 으로 흡수. 비전 검사 관리 **10화면 → 5화면** |
| `04_TARGET_ARCHITECTURE.md` | ER의 `vision_inspection_item ──1:0..1── vision_data_project` 관계 삭제, `BackgroundJob` 의 `MIGRATION` 작업 유형 삭제 |
| `05_DATABASE_MIGRATION_PLAN.md` | `processes` · `products` · `retention_policies` · `image_migrations` 매핑 행 삭제, `uq_project_inspection_item` 인덱스 삭제, §5 생성 순서의 Vision 선행 제약 삭제 |
| `06_API_COMPATIBILITY_PLAN.md` | `/api/v1/catalog` 에 **합성 계층 규칙 추가**, 추론 미구성 시 응답 규칙 명문화 |
| `07_IMPLEMENTATION_PLAN.md` | Task 2.2의 `Project.inspection_item` FK 정의 삭제, **Task 4.2 삭제**, Task 4.6의 `MigrationService`·`retention` 삭제, **Task 5.6 삭제**, Task 5.x 의 공정·제품 화면 삭제, Task 4.x 에 **검사 수신 → `upload_images` 연계** 신설 |

> 화면 삭제는 §1.5 O-4("화면을 임의로 제외하지 않는다")의 유일한 예외다. 근거는 "임의 판단"이 아니라 **사용자 지시 + 기능의 존재 이유 소멸**이다. 이관 기능의 원본 docstring이 그 목적을 명시한다 — *"쌓인 검사 이미지를 **외부** 데이터 수집/관리 시스템으로 옮긴다."* 통합으로 "외부"가 사라진다.

---

## 1.65 Client 작업 요청 R1~R9 대응 (2026-10-03)

Client 담당이 전달한 [요청서](client/SERVER_REQUESTS.md) 9건 중 **서버 코드로 고칠
5건(R5~R9)** 을 처리한 결정이다. 회신은 [SERVER_API_CONTRACT.md](client/SERVER_API_CONTRACT.md) §15 에 합쳤다.

| # | 결정 | 근거 |
|---|---|---|
| DEC-C1 | `/api/v1` 신규 코드는 **`app/views/api_v1.py` 한 파일**에 둔다 | 사용자 지시. 부수 이득 — `verify_permission_map.py` 는 `app/views/` **하위 디렉터리만** 훑으므로 최상위 모듈인 이 파일은 권한 매핑 등록 대상이 아니다 |
| DEC-C2 | `/api/v1` 응답 필드·오류 코드는 **서버 현 구조를 정본**으로 두고 Client 가 맞춘다 | 사용자 지시. 0.1.4 는 R6 때문에 배포 보류 중이고 사내 베타 0.1.0~0.1.3 은 구 서버 `:8005` 를 쓴다 → **현장에 `:8123` 응답을 파싱하는 배포본이 없다.** §1.6 O-11 의 "Client 를 수정하지 않는다"는 이 지점에서 완화됐다 |
| DEC-C3 | health 는 **계약 형식으로 되돌린다** | DEC-C2 의 예외. `components`·`version` 은 서버가 알려줄 가치가 있는 정보이고 Client 연결 테스트 화면이 그것을 읽는다 |
| DEC-C4 | HTTP Range 를 **Django 뷰에서 직접 구현**한다 | Django 5.0.4 에는 Range 처리가 **전혀 없다**(`HTTP_RANGE`·`Content-Range` 가 패키지 전체에 없음). nginx 에 맡기면 개발·운영 동작이 갈린다. 다중 범위는 지원하지 않는다 |
| DEC-C5 | heatmap 은 **라우트만** 만든다. 저장 컬럼·마이그레이션 없음 | GPU 가 Stub 이라 heatmap 이 생기지 않는다. 응답에 `heatmap_url` 을 넣지 않으므로 Client 는 호출하지 않는다. 라우트는 "경로가 비어 404 HTML" 을 없애기 위한 것 |
| DEC-C6 | 배포물은 **저장소 루트 `distribution/`**(운영은 `DISTRIBUTION_ROOT`)에 둔다 | `app/static/` 은 앱 static 디렉터리라 `collectstatic` 이 1.07GB 를 `STATIC_ROOT` 로 복사하고 whitenoise 가 `/static/distribution/...` 으로 같은 파일을 두 번째 경로로 내보낸다. `.gitignore` 는 `distribution/` 한 줄이 아니라 **확장자**로 막는다 — 한 줄로 막으면 `SHA256SUMS.txt` 와 README 까지 사라진다 |
| DEC-C7 | `:8123` 은 **개발 서버로 유지.** TLS·`DEBUG=False` 는 별도 운영 인스턴스의 과제 | 사용자 결정. 현재 구성(개발 서버 모드·단일 프로세스)이 운영 전제를 만족하지 않는다 |
| DEC-C8 | rate limit(429)·`meta.count`·`CLIENT_VERSION_UNSUPPORTED` 는 **미제공으로 확정** | 요청서에 없고 Client 는 없어도 동작한다. `retryable: true` 는 `500 INTERNAL_ERROR` 하나로 닫힌다 |
| DEC-C9 | `RECEIVED` 무한 폴링은 **회신으로만** 알린다 | GPU 미연결 상태에서 `RECEIVED` 는 종결 상태다. 구분 필드를 늘리면 Client 도 바꿔야 하므로 GPU 연결 시 함께 설계한다 |
| DEC-C10 | `APP_VERSION = '1.0.0'`, 운영 반입 경로 `/var/lib/manufacturing-ai-platform/distribution` | 사용자 결정. 프로젝트에 버전 문자열이 아무 곳에도 없었다 |

**되돌려 보낸 질문**(인프라·법무 결정이 필요해 서버 개발이 답할 수 없다): R1 인증서
방식과 컷오버 일정·Key 재발급·rate limit·CORS, R3 3년 보존 정책의 반영 주체와 사외
공개 여부. [SERVER_API_CONTRACT.md](client/SERVER_API_CONTRACT.md) §16 에 있다.

---

## 1.66 Client 작업 요청 R10~R18 대응 (2026-10-06)

요청서 2차분이다. 회신은 [SERVER_API_CONTRACT.md](client/SERVER_API_CONTRACT.md) §15 "2차 회신"에 있다.

| # | 결정 | 근거 |
|---|---|---|
| DEC-C11 | `RECEIVED` 는 **영구히 "추론하지 않음"** 이다(R12 A안). 추론은 POST 안에서 끝내고 서버 타임아웃 20초. 비동기가 필요해지면 `PROCESSING` 을 신설하고 배포 전에 계약으로 알린다 | Client 0.1.5 는 `RECEIVED` 를 종결로 처리하고 이미지를 지운다. 뜻을 바꾸면 추론 결과를 버린다. 20초는 Client 읽기 timeout 30초보다 먼저 끝내기 위한 값 |
| DEC-C12 | `metadata` 는 **이미지 저장 전에** 검증하고, 길이 초과는 **자르지 않고** 422 로 거절한다 | 컬럼 길이 초과가 PostgreSQL `DataError` → 500 `retryable: true` 로 나가 Client 가 재시도했다(R16). `request_id` 를 자르면 보낸 값으로 재조회할 수 없다. 파일 쓰기는 DB 롤백 대상이 아니라 늦게 거절하면 파일만 남는다 |
| DEC-C13 | 추론 `bbox` 는 `{x1, y1, x2, y2}` 원본 Pixel 정수(R11 수락) | Client 가 이미 해석하는 형식. 구현체가 없는 지금 바꾸면 비용이 없다 |
| DEC-C14 | 숨긴 Overlay(`visible: false`)는 **없는 것과 같은 모양**으로 낸다 — 카탈로그 `version: null`, 이미지 경로도 404 | `version` 만 나가면 Client 캐시 키가 보이지 않는 Overlay 를 가리킨다. 이미지 경로가 200 이면 숨긴 가이드가 그대로 나간다 |
| DEC-C15 | health `components.gpu` 는 **추론 연결 때** 함께 넣는다 | 지금 넣으면 늘 `not_configured` 인데 집계가 "전부 ok" 라 health 가 계속 503 이 된다 |
| DEC-C16 | 실측 데이터는 Client 요청대로 지우고, DB 가 참조하지 않는 저장소 파일도 지운다 | R17. 파일 2,206개는 테스트 누출(`test_settings` 의 `MEDIA_ROOT` 미격리)·검사항목 삭제 누락(편집 원본·대표 이미지)·R16 의 500 이 남긴 것이었다. 세 원인은 모두 코드로 막았다 |

TLS·운영 주소·LGPL 사외 공개·rate limit(§16 질문 1~4)은 **운영 서버를 세울 때** 정한다.

---

## 1.7 향후 확장 항목 (이번 범위 밖)

이번 통합에서 **의도적으로 제외했지만 버린 것이 아닌** 항목이다. 요구가 확정되면 각각 별도 과제로 잡는다.
"나중에 하기로 했다"는 사실이 시간이 지나면 잊히므로 여기에 모아 둔다.

| # | 항목 | 이번에 하지 않는 이유 | 나중에 할 때 필요한 것 | 근거 |
|---|---|---|---|---|
| F-1 | **분류(CLASSIFICATION) 검사항목의 Client 노출** | Client `InspectionType` enum이 `DETECTION`·`ANOMALY` 2종뿐이다. 내보내면 Client 파싱이 깨진다. 요구도 아직 미확정("정상/이상 같은 예측 클래스를 출력하려 한다") | Client enum 확장 + 결과 표시 UI + **현장 재배포**. 서버는 카탈로그 필터 한 줄만 푼다 | §1.6 O-14, 사용자 확인(2026-09-30) |
| F-2 | **GPU Server의 실제 추론 구현** | Backbone §9가 명시적으로 제외 | `GpuServerClient`(Stub)를 HTTP 구현체로 교체. 호출 지점·계약·오류 코드는 이번에 다 만든다 | §1.5 O-1, §1.6 O-12 |
| F-3 | **모델 아티팩트 파일 업로드·검증** | 원본 `artifacts.py`가 `torch.load`를 쓴다. WEB에 torch를 들이지 않는다 | GPU Server 구현 시 그쪽에 둔다. 이번 화면은 `artifact_path` 문자열만 받는다 | §1.5 O-1·O-7 |
| F-4 | **모델 메타데이터 소유권을 GPU Server로 이전** | 지금은 GPU Server가 없어 화면이 성립하지 않는다 | `vision_item_model_mapping`의 FK를 끊고 `model_code`+`model_version` 식별자 참조로 전환. **그래서 지금부터 두 컬럼을 비정규화 저장해 둔다** | §1.5 O-2, DEC-010(B) |
| F-5 | **검사항목 분류 체계(Client 드로어 그룹)** | 초기 검사항목이 **2~5개**라 평평한 목록으로 충분하다. 쓰지도 않을 계층을 미리 만들지 않는다 | 검사항목에 nullable `group_name` 1개 추가 + 카탈로그 합성 로직이 `processes` 배열에 N건을 넣는다. **응답 형태가 같으므로 Client 무수정** | §1.6 O-11, 사용자 확인(2026-09-30) |
| F-6 | **AI 학습(Training) 기능** | Backbone §9 — 학습 전체 제외 | 별도 학습 파이프라인 과제 | DEC-027 → §1.5 O-1 |
| F-7 | **RAG / Chatbot / VectorDB / Object Storage** | 원 프롬프트가 현재 범위에서 명시적으로 제외 | 별도 과제 | v3 프롬프트 |

> **F-5 보충** — A안(고정 1건)과 C안(분류별 N건)은 `GET /api/v1/catalog` **응답 스키마가 동일하다.**
> Client 파서(`server_client.py:283`)는 `processes` 배열의 길이를 따지지 않고 순회할 뿐이다.
> 따라서 A로 시작해도 C로 가는 데 잠금이 없다. 서버 변경 + nullable 컬럼 1개가 전부다.

---

## 2. 상세 결정 사항

### DEC-001. 통합 방식 — 어떤 골격 위에 통합하는가

**중요도**
- **BLOCKER**

**관련 영역**
- Architecture / Django / Migration

**확인된 사실**
- MES와 AIDataHub는 최상위 Python 패키지 이름이 **둘 다** `configurations` / `app` / `domain` 이다. `settings.py`, `urls.py`, `app/views/__init__.py`, `domain/gui.py`, `domain/models/user.py`가 양쪽에 같은 경로로 존재하고 내용이 다르다. (`03_CONFLICT_ANALYSIS.md` C-01)
- Django App Label: MES `app`/`domain`, AIDataHub `app`/**`ai_domain`**. 한 프로젝트에 라벨 `app`이 둘일 수 없다. AIDataHub `domain/models/labeling.py`는 FK를 `"ai_domain.DataStandard"` 문자열로 참조한다. (C-02)
- AIDataHub는 `test_v2_architecture`가 앱 라벨을 `assertEqual`로 고정하고, `test_view_layout`/`test_template_layout`/`test_service_layout`이 **디렉터리의 파일 집합 전체**를 고정한다.
- vision-inspection Server는 FastAPI + SQLAlchemy + Alembic이다. Django로 이관하려면 재작성이다. (C-06)
- 규모: MES 뷰 363 / 템플릿 409 / 서비스 101 / 테이블 179 / GUI 374. AIDataHub 뷰 34 / 템플릿 33 / 서비스 46 / 모델 25 / 화면 10. vision Server src 77 파일 / 테이블 11.

**문제/충돌**
"세 프로젝트를 통합한다"를 **파일 병합으로 수행할 수 없다.** 골격을 하나 정하고 나머지를 그 규약으로 옮겨 쓰는 작업이며, 어느 것을 골격으로 두느냐에 따라 재작성 분량이 10배 차이난다.

**선택지**

#### Option A — MES 트리 복제 후 기능 이식 (권장)
- 내용: `MES/`를 `manufacturing_ai_platform/`으로 복제해 골격으로 삼는다. AIDataHub와 vision Server의 **기능을** MES의 `app/views/<업무>/` + `domain/services/<업무>/` + `domain/models/` 규약으로 **이식(재작성)** 한다. AIDataHub 트리를 Django App으로 끌어오지 않는다.
- 장점: 프롬프트 §4·§11과 일치. MES 시스템관리·UI·WeZonGrid 자산을 그대로 쓴다. App Label 충돌이 발생하지 않는다.
- 단점: AIDataHub 화면 10개 + 서비스 46개 + 테스트 603건을 MES 규약으로 재작성해야 한다. AIDataHub 테스트 자산이 대부분 무효화된다.
- 영향 범위: 신규 리포지토리 1개. AIDataHub·vision은 참조용 원본으로 남긴다(수정하지 않음).
- Migration 영향: 새 `0001_initial` 하나로 시작(→ DEC-011).
- 운영 영향: MES 배포 절차를 기준으로 하되 OS는 DEC-020에 따름.

#### Option B — 신규 Django 프로젝트 + 양쪽을 App으로 편입
- 내용: `manufacturing_ai_platform/` 을 새로 만들고, MES를 `mes_core` 앱으로, AIDataHub를 `ai_data` 앱으로 패키지·라벨을 rename해 편입한다.
- 장점: 두 코드베이스를 모두 "유지"하는 형태다. AIDataHub 코드 수정량이 Option A보다 작다.
- 단점: AIDataHub의 모든 import 경로(수백 곳)와 FK 문자열 참조, 파일목록 고정 테스트가 깨진다. MES도 `app.views.<task>.<view>` 동적 import 경로가 전부 바뀐다(`ApiModuleView`의 `module_path` 조립부). **양쪽 다 깨진다.**
- 영향 범위: 세 프로젝트 전부.
- Migration 영향: 라벨이 바뀌므로 `django_content_type`·`auth_permission` 재매핑 필요.
- 운영 영향: 배포 구조 전면 신규.

#### Option C — AIDataHub 골격 + MES 시스템관리 이식
- 내용: AIDataHub를 골격으로 두고 MES 시스템관리·기준정보를 AIDataHub 규약으로 이식한다.
- 장점: 인가 구조·테스트·보안 설정·배포가 이미 건전하다. 재작성 분량이 가장 적다(MES에서 가져올 것이 시스템관리+최소 기준정보뿐이므로 — DEC-023 Option B 전제).
- 단점: **프롬프트 §4 "MES 구조와 코딩 패턴을 통합 프로젝트의 기본 규칙으로 우선 적용"에 정면으로 어긋난다.** MES UI 자산(WeZonGrid·Hyper 테마·409 템플릿·다국어 라벨코드)을 버린다.
- 영향 범위: AIDataHub 트리 + 신규 이식 코드.
- Migration 영향: AIDataHub `0001_initial`에 MES 시스템관리 테이블 추가.
- 운영 영향: AIDataHub 배포 구조 유지(Linux + nginx).

**권장안**
- **Option A**
- 권장 근거: 프롬프트가 MES Backbone을 명시적·반복적으로 지시하며(§0-4, §4, §11, §15, §23-9·11), Option B는 양쪽 코드베이스를 동시에 깨뜨려 가장 위험하다. Option C는 기술적으로 가장 안전하지만 지시에 어긋나므로, **지시를 바꿀 의사가 있을 때만** 선택 가능하다.
- 단, Option A를 택하면 **AIDataHub 테스트 603건의 손실**이 확정된다. 이는 기능 회귀를 막는 유일한 장치였으므로, 구현 계획 Phase 0에 **이식 대상 기능의 테스트 재작성**을 반드시 포함한다.

**사용자 결정**
- [ ] Option A — MES 트리 복제 후 기능 이식
- [ ] Option B — 신규 프로젝트 + 양쪽 App 편입
- [ ] Option C — AIDataHub 골격 + MES 시스템관리 이식
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §1·§3, `07_IMPLEMENTATION_PLAN.md` Phase 0~1

---

### DEC-002. User / UserGroup / UserGroupMenu 정본 스키마

**중요도**
- **BLOCKER**

**관련 영역**
- Auth / DB / Migration

**확인된 사실**
- MES와 AIDataHub **모두** `AUTH_USER_MODEL`을 커스터마이즈하지 않고 `django.contrib.auth.models.User`(`auth_user`)를 쓴다. → 이 부분은 충돌이 없다.
- 그러나 양쪽이 `user_group` / `user_profile` / `user_group_menu` **세 테이블을 같은 이름·다른 컬럼으로** 정의한다. (C-04 상세 표)
- MES `UserProfile`은 AIDataHub 것의 **상위집합**이다: AIDataHub에 없는 `Factory`·`Company`·`Depart`·`CompCode`·`access_token`·`refresh_token` + 감사 컬럼 5개를 갖는다.
- MES의 세 모델은 `AbstractAuditModel`을 상속해 `_status`/`_created`/`_modified`/`_creater_id`/`_modifier_id`를 갖고, **`_created`는 `auto_now_add=True`로 NOT NULL**이다. AIDataHub 모델에는 이 컬럼이 없다.
- `UserGroupMenu.AuthCode`: MES는 `CharField(10)` + choices 없음(`"R" in code` / `"W" in code`로 판정), AIDataHub는 `choices=[("R",...),("RW",...)]`. 값 집합은 실질 호환.
- AIDataHub는 사용자 속성을 반드시 `domain/models/user.py`의 `user_is_platform_admin` / `user_display_name` / `set_user_display_name` / `set_user_group` / `platform_admin_q` 로만 다루는 것이 규약이다. → **함수 경계가 있어 어댑터화가 쉽다.**
- 관리자 판정이 다르다: MES `is_superuser` 또는 `UserGroup.Code in ('dev','admin')`, AIDataHub `UserGroup.Code == 'admin'` **만**(`is_staff`/`is_superuser`는 관리자가 아니라고 명시).

**문제/충돌**
같은 테이블 이름으로 두 스키마가 공존할 수 없다. 하나를 정본으로 택해야 하고, 택하지 않은 쪽의 코드를 정본 위에서 동작하게 고쳐야 한다.

**선택지**

#### Option A — MES 스키마를 정본으로 (권장)
- 내용: MES `UserProfile`/`UserGroup`/`UserGroupMenu`를 그대로 쓴다. AIDataHub의 사용자 함수 5개를 MES 모델 위에서 동작하도록 어댑터화한다. 관리자 판정은 MES 규칙(`is_superuser` 또는 `Code in ('dev','admin')`)을 따른다.
- 장점: 데이터 손실이 없다(MES가 상위집합). MES 사용자·사용자그룹·메뉴권한 화면 3개를 그대로 쓴다. AIDataHub 측 변경이 함수 5개 + `menu_auth.py`에 국한된다.
- 단점: `Factory`/`Company`/`Depart` FK가 따라오므로 해당 기준정보 테이블도 가져와야 한다(→ DEC-023에 이미 포함). AIDataHub의 "`is_staff`/`is_superuser`는 관리자가 아니다"는 안전장치가 느슨해진다.
- 영향 범위: AIDataHub `domain/services/account/*`(5파일), `domain/gui.py`, `app/views/system/{users,groups}/api.py`.
- Migration 영향: MES `0001_initial`의 정의를 그대로 사용. AIDataHub 기존 사용자 데이터는 컬럼 매핑 후 INSERT(→ DEC-012).
- 운영 영향: 사용자 관리 화면은 MES 것 하나.

#### Option B — 최소 공통 스키마로 재정의
- 내용: 양쪽에서 실제로 쓰이는 컬럼만 남긴 새 스키마를 정의한다(감사 컬럼은 유지, `access_token`/`refresh_token`/`CompCode`는 제거 — PDA가 범위 밖이므로).
- 장점: 死컬럼이 사라진다. `access_token`/`refresh_token`을 DB에 두는 것은 보안상 바람직하지 않다.
- 단점: MES 사용자 화면·서비스의 SQL(`AccountService.get_user_list`/`get_user_detail`이 컬럼명을 하드코딩)을 수정해야 한다. MES 기존 데이터 이관 시 컬럼 삭제가 된다.
- 영향 범위: MES `system/user.py`, `domain/services/account.py`, `templates/system/user.html` + AIDataHub 함수 5개.
- Migration 영향: 새 정의.
- 운영 영향: 동일.

#### Option C — AIDataHub 스키마를 정본으로
- 내용: AIDataHub의 최소 스키마를 쓰고 MES 쪽을 맞춘다.
- 장점: 스키마가 단순하다.
- 단점: **MES `UserProfile.Factory`/`Company`/`Depart`를 참조하는 코드가 깨진다**(`WebUserInfo`, 사용자 화면, 공장별 데이터 필터). 데이터 손실.
- 영향 범위: MES 광범위.
- Migration 영향: 컬럼 삭제.
- 운영 영향: 공장·업체 단위 사용자 구분 기능 상실.

**권장안**
- **Option A**
- 권장 근거: MES가 상위집합이라 무손실이고, 프롬프트 §16.1 "MES 인증/권한을 기준으로 한다"·§23-11 "User/Auth/Permission은 MES를 기준으로 한다"에 부합한다. AIDataHub가 사용자 접근을 함수 5개로 캡슐화해 둔 덕분에 어댑터 비용이 작다.
- 단, `access_token`/`refresh_token` 컬럼은 **PDA가 범위 밖이므로 이관 대상에서 빼는 것**을 함께 권한다(Option A + 이 두 컬럼 제외). 이 변형을 원하면 "기타"에 적어 주기 바란다.

**사용자 결정**
- [ ] Option A — MES 스키마 정본
- [ ] Option A' — MES 스키마 정본 + `access_token`/`refresh_token` 제외
- [ ] Option B — 최소 공통 스키마 재정의
- [ ] Option C — AIDataHub 스키마 정본
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §12, `05_DATABASE_MIGRATION_PLAN.md` §User Mapping

---

### DEC-003. 권한 모델 범위 — 과제 역할·작업그룹 권한을 살리는가

**중요도**
- **BLOCKER**

**관련 영역**
- Auth / Architecture / Domain

**확인된 사실**
- MES 권한은 **단일 축**이다: `UserGroup` → `UserGroupMenu(MenuCode, AuthCode)` → 화면 단위 R/W. 판정은 `AccountService.check_user_auth(user, gui_code)`.
- AIDataHub 권한은 **4중**이다:
  1. `is_staff`/`is_superuser` (플랫폼 관리자가 아님)
  2. 플랫폼 관리자 = `UserProfile.UserGroup.Code == "admin"`
  3. 시스템 메뉴 권한 = `UserGroupMenu` R/RW (MES와 같은 축)
  4. 조직·과제 권한 = `TenantMembership` + `ProjectAssignment.role`(`PROJECT_MANAGER` / `WORKER`) + `ProjectGroupAccess`(`can_view`/`can_upload`/`can_label`) + PostgreSQL RLS
- 작업→capability 매핑은 `domain/services/access/authorization.py`의 `ACTION_CAPABILITIES` **한 곳**에만 있고, 어떤 역할이 그 capability를 갖는지는 `ProjectAccessService`만 정한다. 등록하지 않은 작업은 **403**이다.
- 화면 권한은 `gui_item()` 옵션으로 선언한다: `project`(capability, 없으면 404), `manager_only`(403), `redirect_home`, `menu_auth`, `admin_only`.
- 메뉴 구성이 과제 단위로 만들어진다(`gui.py` `_project_menu`: 과제별로 하위 메뉴 트리 생성, 역할에 따라 "검수 작업" 메뉴 노출/숨김).
- MES에는 "화면 단위 R/W"보다 세밀한 권한 개념이 **없다.**

**문제/충돌**
"작업자는 배정된 과제의 라벨링만 할 수 있고, 과제 관리자는 그 과제의 검수를 할 수 있다"는 규칙은 **화면 단위 R/W로 표현할 수 없다.** 같은 `/dataset/labeling/` 화면에서 대상 과제에 따라 허용/거부가 갈리기 때문이다. MES 권한 모델만 쓰면 이 기능이 사라진다.

**선택지**

#### Option A — MES 권한만 채택 (과제 역할 폐기)
- 내용: `UserGroupMenu` R/W만 쓴다. `ProjectAssignment`·`ProjectGroupAccess`·capability 검사를 제거한다. 과제는 전원 공용으로 보이고, 라벨링·검수는 사용자그룹으로만 구분한다.
- 장점: 권한 모델이 하나다. MES 패턴 그대로. 구현·운영이 단순하다.
- 단점: **"어떤 작업자가 어떤 과제를 라벨링하는가"를 통제할 수 없다.** AIDataHub의 라벨링 작업 배정·검수 분리 기능이 사실상 무력화된다. `ProjectAssignment`를 남겨도 인가가 아니라 단순 기록이 된다.
- 영향 범위: AIDataHub `access/authorization.py`, `project/access.py`, `gui_item` 옵션 4종, 화면 10개의 권한 분기.
- Migration 영향: `vision_data_projectassignment`·`..._projectgroupaccess` 유지 여부 결정.
- 운영 영향: 라벨링 작업 분담을 시스템이 아니라 사람이 관리해야 한다.

#### Option B — MES 메뉴권한 + 과제 역할 유지 (권장)
- 내용: 1차 관문은 MES `UserGroupMenu`(화면 접근), 2차 관문은 `ProjectAssignment.role` + `ProjectGroupAccess` capability(대상 과제별 허용). 조직(Tenant)은 DEC-004에 따름.
- 장점: 라벨링·검수 분담 기능을 보존한다. MES 권한 축을 정본으로 두므로 프롬프트 §16.1과 충돌하지 않는다(MES 위에 **추가** 축을 얹는 것).
- 단점: 권한 축이 둘이다. **MES `ApiModuleView`에 인가 훅이 없으면 2차 관문을 걸 지점이 없다** → DEC-014와 묶여 있다. 운영자가 두 곳에서 권한을 관리한다.
- 영향 범위: `ApiModuleView` 인가 훅, `GUITemplatesView`의 gui 옵션 확장, AIDataHub `ACTION_CAPABILITIES`/`ProjectAccessService` 이식.
- Migration 영향: `vision_data_projectassignment`·`..._projectgroupaccess` 유지.
- 운영 영향: 사용자그룹 메뉴권한 화면 + 과제별 인원 배정 화면 둘 다 필요.

#### Option C — AIDataHub 4중 권한을 그대로 유지
- 내용: Tenant + 과제 역할 + 작업그룹 + RLS + 메뉴권한 전부 유지.
- 장점: 검증된 구현(테스트 603건)을 최대한 살린다.
- 단점: MES 사용자에게 "조직" 개념이 새로 생긴다. MES 시스템관리 화면과 AIDataHub 조직 관리 화면이 공존해 혼란스럽다. DEC-004가 자동으로 "유지"로 정해진다.
- 영향 범위: 전체.
- Migration 영향: 19테이블 tenant FK + RLS 유지.
- 운영 영향: 조직 선택 단계가 로그인 후 들어간다.

**권장안**
- **Option B**
- 권장 근거: 프롬프트 §4.3은 "로그인/사용자/역할/권한/메뉴/메뉴권한"을 MES 기준으로 재사용하라고 하지만, 라벨링 작업 배정은 **MES에 대응 기능이 없는 신규 업무 요구**다. MES 권한을 대체하지 않고 그 아래 계층으로 얹으면 두 지시가 모두 충족된다.
- Option B는 **DEC-014(인가 훅 추가)가 함께 승인되어야 성립한다.** DEC-014를 "현행 유지(인가 훅 없음)"로 결정하면 Option B는 구현 불가이며 Option A로 강제된다.

**사용자 결정**
- [ ] Option A — MES 권한만
- [ ] Option B — MES 메뉴권한 + 과제 역할·작업그룹
- [ ] Option C — AIDataHub 4중 권한 유지
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §12, `07_IMPLEMENTATION_PLAN.md` Phase 2

---

### DEC-004. 멀티테넌시(Tenant) / PostgreSQL RLS 존치

**중요도**
- HIGH

**관련 영역**
- DB / Architecture / Migration / Operation

**확인된 사실**
- AIDataHub `TenantOwnedModel`(추상)이 `tenant = FK(Tenant, on_delete=PROTECT)` **NOT NULL**을 강제하고, 업무 모델 대부분이 이를 상속한다. `Tenant.id`는 **UUID**.
- `0001_initial`의 `TENANT_TABLES` **19개 테이블**에 RLS 정책(`vision_data_<모델>_tenant_scope`)이 걸려 있다. `scripts/verify_rls.py`로 검증한다.
- 거의 모든 unique 제약·index가 `tenant`를 **첫 컬럼**으로 포함한다(예: `unique_dataset_version_in_tenant_project`, `image_list_dataset_label_idx`).
- `tenant_atomic(tenant)`가 `SET LOCAL app.tenant_id`를 걸고, **백그라운드 워커도 같은 규칙을 따른다.**
- `TenantMiddleware`가 로그인·테넌트 선택을 모든 요청에서 먼저 확인한다.
- `AGENTS.md`: "RLS를 임의로 제거·우회하지 않는다. 성능 문제도 RLS를 끄는 방식으로 풀지 않는다."
- 파일 저장 경로도 테넌트별이다(`domain/storage.py`: `tenants/{tenant_id}/...`).
- MES·vision Server에는 테넌트 개념이 **없다.** MES `UserProfile.Factory`가 유사하지만 인가 경계로 쓰이지 않는다.
- `seed_saas_demo`가 조직 2개를 만든다 → 다중 조직 운영을 전제한 설계다.
- **실제 운영 DB에 조직이 몇 개 있는지는 확인하지 못했다** (`01_...md` N9).

**문제/충돌**
프롬프트의 목표 구조에는 조직(테넌트) 개념이 없다. 단일 공장/단일 조직을 전제로 보인다. 그러나 AIDataHub 데이터 도메인 전체가 `tenant` NOT NULL에 묶여 있어 제거 비용이 매우 크다.

**선택지**

#### Option A — Tenant 제거
- 내용: 19테이블에서 `tenant` 컬럼 삭제, 모든 unique/index 재정의, RLS 정책 삭제, `TenantOwnedModel`·`TenantScopedManager`·`tenant_atomic`·`TenantMiddleware` 제거, 저장 경로에서 테넌트 세그먼트 제거.
- 장점: 스키마가 단순해진다. GPU Server가 같은 DB에 직접 접근할 때 RLS 문제(O-6)가 사라진다. MES 사용자에게 없던 개념이 생기지 않는다.
- 단점: **변경량이 매우 크다.** 서비스 46개 전부에서 `tenant` 인자와 `tenant_atomic`을 제거해야 하고, 테스트 603건 대부분이 테넌트 픽스처를 쓴다. 이관 대상 기능의 버그 유입 위험이 가장 높다.
- 영향 범위: AIDataHub 전체.
- Migration 영향: 19테이블 스키마 변경 + 제약·인덱스 재생성. 기존 데이터가 있으면 이관 중 수행.
- 운영 영향: 조직 선택 화면 제거. 조직 관리 메뉴 제거.

#### Option B — 단일 Tenant 고정, 스키마 유지 (권장)
- 내용: `Tenant` 행을 1개만 만들고 시스템 전역 고정값으로 쓴다. `TenantMiddleware`를 "고정 테넌트 주입"으로 축소한다. 조직 선택 화면과 조직 관리 메뉴는 제거한다. RLS·`tenant` 컬럼·`tenant_atomic`은 그대로 둔다.
- 장점: **스키마와 서비스 코드를 건드리지 않는다** → 이식 위험이 가장 낮다. RLS가 남아 있어 나중에 다조직이 필요해지면 되살릴 수 있다. 이식 중 버그 유입이 최소다.
- 단점: 사용자에게 보이지 않는 UUID FK와 RLS 정책이 영구히 남는다(불필요한 복잡도). GPU Server가 같은 DB에 직접 접근하면 **RLS 때문에 데이터를 못 읽는다** → DEC-008에서 "GPU는 이미지/데이터셋 테이블에 직접 접근하지 않는다"를 함께 결정해야 한다. `Tenant` 행이 실수로 여러 개 생기면 데이터가 갈린다(제약으로 막아야 한다).
- 영향 범위: `domain/tenancy.py`, 조직 관리 화면 4개, `gui.py` 메뉴.
- Migration 영향: **없음**(스키마 그대로) + 초기 데이터로 Tenant 1행 생성.
- 운영 영향: 로그인 후 조직 선택 단계 없음.

#### Option C — 다조직 유지
- 내용: 현재 구조 그대로 운영한다.
- 장점: 검증된 구현 전체를 살린다. 여러 사업장/고객사를 한 인스턴스로 운영할 수 있다.
- 단점: MES에는 없는 축이 추가된다. MES `Factory`(공장)와 `Tenant`(조직)가 의미상 겹쳐 혼란스럽다. GPU Server의 RLS 문제가 그대로 남는다.
- 영향 범위: 전체.
- Migration 영향: 없음.
- 운영 영향: 조직 선택 단계 유지. 조직 관리 화면 유지.

**권장안**
- **Option B**
- 권장 근거: 프롬프트 §23-16 "분석 중 코드를 대규모로 수정하지 않는다", §18 "Big Bang Merge를 피한다"의 정신에 맞는 최소 변경 경로다. Option A는 통합 1단계에서 가장 위험한 대규모 스키마 수술이고, Option C는 프롬프트의 목표 구조에 없는 개념을 사용자에게 노출한다. Option B는 **나중에 A로도 C로도 갈 수 있는 유일한 선택**이다.
- 단, Option B를 택하면 `Tenant` 테이블에 "행이 하나임"을 강제하는 제약을 두는 것을 권한다(vision `retention_policies.id=1` CheckConstraint와 같은 방식).
- **결정 전 확인 권장**: 현재 `10.10.10.20/aidatahub_v2`의 `vision_data_tenant` 행 수. 2개 이상 실사용 중이면 Option C를 재검토해야 한다(N9).

**사용자 결정**
- [ ] Option A — Tenant 제거
- [ ] Option B — 단일 Tenant 고정, 스키마 유지
- [ ] Option C — 다조직 유지
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §5·§11, `05_DATABASE_MIGRATION_PLAN.md` §Ownership

---

### DEC-005. AIDataHub `Project`(검사 과제) 존치와 vision 계층 연결

> **[폐기됨 — §1.6 O-8]** 공정·제품을 없애기로 하면서 두 엔티티를 1:1로 연결할 이유가 사라졌다.
> 검사항목과 저장소를 `vision_data_item` 단일 테이블로 통합한다. 아래는 분석 기록이다.

**중요도**
- **BLOCKER**

**관련 영역**
- Domain / DB / UI

**확인된 사실**
- 프롬프트 §5는 "`Project`는 목표 Architecture의 필수 Domain으로 미리 확정하지 않는다"며 실제 필요성을 판단하라고 지시한다.
- `Project` FK를 **NOT NULL로** 갖는 모델: `Dataset`, `LabelClass`, `DataStandard`, `StandardImage`, `LabelingTask`, `ProjectAssignment`, `ProjectGroupAccess`. null 허용: `ProjectDeletionRequest`, `ActivityLog`. 간접 종속: `ImageAsset`(→`dataset.project`), `Annotation`(→`image`·`label_class`).
- `Project.task_type`(`OBJECT_DETECTION`/`CLASSIFICATION`/`ANOMALY_DETECTION`)이 **라벨링 화면 분기와 Export 포맷 결정의 축**이다(`PROJECT_EXPORT_FORMATS`, `get_exporter_class`가 `task_type`으로 조회).
- 메뉴 트리도 과제 단위로 생성된다(`gui.py` `_project_menu`).
- vision 계층은 `Process → Product → InspectionItem`이고 `InspectionItem.inspection_type`은 `DETECTION`/`ANOMALY` **2종**(PostgreSQL native enum). **`CLASSIFICATION`에 대응하는 검사 유형이 없다.**
- **`Project`와 `InspectionItem`을 잇는 관계가 양쪽 어디에도 없다.**
- `LabelClass.name`(과제별 라벨 클래스)과 검사 응답의 `defects[].class_name`(모델 출력 클래스명)도 **연결되어 있지 않다** — 별개의 문자열이다.
- MES에 `Project`에 대응하는 상위 업무 단위는 없다(고객사 프로젝트는 소스 파생 개념).

**문제/충돌**
프롬프트 §5의 판단 기준에 대입한 결과:

| 기준 | 판단 |
|---|---|
| Dataset과 Project가 강하게 결합되어 있는가? | **예.** `Dataset.project`가 NOT NULL이고 `task_type`이 라벨링·Export 분기의 축이다 |
| Multi-project 분리가 실제 업무상 필요한가? | **확인 필요** — 검사항목 단위로 데이터셋을 관리하면 대체 가능할 수도 있다 |
| MES에 유사한 상위 업무 단위가 존재하는가? | **없다** |
| 중복 개념을 하나로 통합할 수 있는가? | `Project` ↔ `InspectionItem`(또는 `Product`)이 사실상 같은 대상을 가리킬 가능성이 있다 |

즉 "필수는 아니지만 제거 비용이 매우 크고, vision 계층과 개념이 겹친다"는 상태다.

**선택지**

#### Option A — `Project` 유지 + `InspectionItem` 연결 필드 추가 (권장)
- 내용: `Project`를 그대로 두고 `Project.inspection_item`(FK, null 허용) 또는 `InspectionItem.project`(FK, null 허용) 중 한 방향으로 연결 필드를 추가한다. 검사 결과를 학습 데이터로 보낼 때 이 연결로 대상 과제를 찾는다(→ DEC-026).
- 장점: AIDataHub 데이터 도메인을 무수정으로 이식할 수 있다. 검사항목과 무관한 데이터 수집 과제(예: 사전 데이터 확보)도 만들 수 있다.
- 단점: 사용자가 "검사항목"과 "검사 과제"를 둘 다 등록해야 한다(연결 작업 추가). 개념이 둘이라 설명 비용이 든다.
- 영향 범위: `Project` 모델에 필드 1개 + 과제 생성/편집 화면에 선택 항목 1개.
- Migration 영향: 컬럼 1개 추가.
- 운영 영향: 과제 등록 시 대상 검사항목 지정.

#### Option B — `Project`를 `InspectionItem`에 1:1 종속
- 내용: 검사항목을 만들면 과제가 자동 생성되고 이름·유형이 검사항목에서 파생된다. 과제를 독립적으로 만들 수 없다.
- 장점: 사용자가 관리할 개념이 하나다. 검사항목 ↔ 데이터셋 대응이 명확하다.
- 단점: `CLASSIFICATION` 과제를 만들 수 없다(`inspection_type`에 없음) → AIDataHub 분류 라벨링·Export 3포맷이 사용 불가가 된다. 또는 `inspection_type`에 `CLASSIFICATION`을 추가해야 하는데 **PG native enum `ALTER TYPE ADD VALUE`가 필요**하고(C-26), GPU에 CLASSIFICATION 추론이 없어 검사 실행은 불가하다(NEW-07).
- 영향 범위: `Project` 생성 경로, 라벨링 화면 분기, Export 레지스트리.
- Migration 영향: 컬럼 추가 + enum 값 추가 + 기존 과제 매핑.
- 운영 영향: 검사항목 등록이 곧 과제 생성.

#### Option C — `Project` 제거, `Dataset`을 `InspectionItem`에 직접 연결
- 내용: `Project`를 없애고 `Dataset.inspection_item` FK로 바꾼다. `LabelClass`·`DataStandard`·`LabelingTask`도 `InspectionItem`에 붙인다. `task_type`은 `inspection_type`으로 대체한다.
- 장점: 개념이 하나로 통일된다. 계층이 가장 단순하다.
- 단점: **AIDataHub 데이터 관리 기능 전체를 재작성해야 한다**(모델 9개 FK 변경, 서비스 46개 중 대부분, 화면 10개, Export 레지스트리). `CLASSIFICATION` 문제는 Option B와 동일. 과제 관리자/작업자 배정(`ProjectAssignment`)의 대상이 사라져 DEC-003 Option B가 불가능해진다.
- 영향 범위: 전체.
- Migration 영향: 대규모.
- 운영 영향: 검사항목 하나에 데이터셋 여러 개.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §5의 첫 기준("Dataset과 Project가 강하게 결합되어 있는가")에 명확히 "예"이므로, 제거는 §23-8("기존 구현이 존재하면 새 구현을 먼저 제안하지 않는다")·§23-16에 어긋난다. Option A는 컬럼 1개 추가로 두 계층을 잇는 최소 변경이다.
- **연결 방향 권장**: `Project.inspection_item`(null 허용). 이유 — 검사항목 없이 먼저 데이터를 모으는 과제를 허용해야 하고(초기 데이터 확보 단계), 한 검사항목에 과제가 여러 개일 필요는 없어 보인다. 반대 의견이 있으면 메모에 적어 주기 바란다.
- `CLASSIFICATION`을 검사 유형으로 지원할지는 **DEC-027(학습 범위)과 함께** 판단이 필요하다. 현재는 "데이터 관리에서는 분류 과제를 만들 수 있지만 검사 실행은 DETECTION/ANOMALY만"이 자연스러운 절충이다.

**사용자 결정**
- [ ] Option A — `Project` 유지 + `InspectionItem` 연결 필드
- [ ] Option B — `Project`를 `InspectionItem`에 1:1 종속
- [ ] Option C — `Project` 제거, `Dataset`을 `InspectionItem`에 직접 연결
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §8, `05_DATABASE_MIGRATION_PLAN.md`, `07_IMPLEMENTATION_PLAN.md` Phase 2·3

---

### DEC-006. GPU Server — 신규 개발인가, vision-inspection Server 개조인가

**중요도**
- **BLOCKER**

**관련 영역**
- Architecture / GPU / API / Operation

**확인된 사실**
- vision-inspection Server는 **이미 FastAPI**이고, 한 프로세스 안에 다음을 모두 갖고 있다: Client API(`/api/v1`), Admin Web(`/admin`, Jinja2 22템플릿), Catalog(Process/Product/InspectionItem), Overlay, Client 인증, Inspection 수신·저장·조회, **Model Registry(`models`)**, **ModelMapping**, **추론 어댑터(torchvision Detection / PatchCore Anomaly)**, 이미지 저장소, 보존 정책, 이미지 내보내기.
- 계층이 헥사고날로 분리되어 있다: `api/` `admin/` → `application/` → `domain/`(기술 독립) ← `infrastructure/`. `domain/`은 FastAPI·SQLAlchemy·AI 라이브러리를 import하지 않는다.
- 추론 어댑터는 `infrastructure/inference/`에 격리되어 있고 `domain/ports.py`의 `DetectionInferencePort`/`AnomalyInferencePort` Protocol로 주입된다 → **분리 지점이 이미 설계되어 있다.**
- 테스트 56개 파일이 있다.
- 없는 것: Training Job API, Model Version 엔티티, Model Load/Unload API, Deployment/Runtime 상태, Evaluation Result, GPU 자원 관리, CLASSIFICATION 추론.
- 프롬프트 §11은 "Django에 `ai/` App을 기본적으로 만들지 않는다", §2.3은 GPU Server가 "AI 모델 관리 / AI 학습 / AI 추론"을 담당한다고 정한다.

**문제/충돌**
목표 아키텍처의 GPU Server는 "신규 시스템"처럼 서술되어 있지만, 실제로는 **vision Server에서 업무 기능(Catalog·Admin·Client API·검사 저장)을 떼어내고 AI 부분만 남긴 것**과 거의 같다. 어느 쪽으로 보는지에 따라 작업 성격과 위험이 완전히 달라진다.

**선택지**

#### Option A — vision Server를 GPU Server로 축소·개조 (권장)
- 내용: vision Server를 GPU Server로 전환한다. 제거: `api/routes/{catalog,overlays,inspections,history,licenses,client_packages}`, `admin/` 전체, `application/services/{catalog,overlay,client_auth,client_admin,admin_auth,retention,image_migration}`, 테이블 `clients`·`admin_users`·`processes`·`products`·`inspection_items`·`overlays`·`inspections`·`model_mappings`·`retention_policies`·`image_migrations`. 유지: `models`, `infrastructure/inference/*`, `model_artifacts`, 모델용 `storage`, `security`. 추가: `/models` CRUD·`/models/{id}/load`·`/inference/{detection,anomaly}`·`/training/jobs`, Service 인증(DEC-015).
- 장점: 추론 어댑터·모델 아티팩트 검증·헥사고날 경계·FastAPI 조립·배포(systemd·offline wheelhouse)를 **그대로 쓴다.** 가장 검증된 코드를 가장 많이 보존한다. Port Protocol이 이미 있어 API화가 자연스럽다.
- 단점: 제거 분량이 크고(파일 절반 이상), 테스트 56건 중 Admin·Catalog·Client API 테스트 대부분이 삭제 대상이다. 리포지토리·패키지명(`vision_inspection_server`) 변경 여부도 결정해야 한다.
- 영향 범위: vision-inspection Server 전체 + Django `/api/v1` 호환 계층 신규.
- Migration 영향: GPU 소유 테이블만 남긴 새 기준선(→ DEC-011).
- 운영 영향: 기존 `SERVER_DEPLOYMENT.md`를 축소해 재사용.

#### Option B — GPU Server 신규 작성 + vision Server 폐기
- 내용: 빈 FastAPI 프로젝트를 새로 만들고 추론 어댑터 코드만 복사해 온다.
- 장점: 목표 구조에 딱 맞는 최소 서비스. 死코드가 없다. Training·Model Version·Load/Unload를 처음부터 설계에 넣는다.
- 단점: `model_artifacts` 검증, PatchCore/torchvision 어댑터의 전처리·후처리 세부, Heatmap 생성, `inference_ms` 측정, 비블로킹 처리(`test_inference_does_not_block.py`가 지키던 것)를 **다시 만들며 놓칠 위험**이 크다. 배포 절차도 새로.
- 영향 범위: 신규 리포지토리 + vision Server 폐기.
- Migration 영향: `models` 재정의 + 모델 아티팩트 재등록.
- 운영 영향: 배포 절차 신규.

#### Option C — vision Server를 그대로 두고 Django를 프록시로
- 내용: vision Server를 현 기능 그대로 Private Subnet에 두고 Django가 중계한다.
- 장점: vision Server 수정이 거의 없다. 가장 빠르게 동작한다.
- 단점: **프롬프트 §2.2·§3과 어긋난다** — 검사 기준정보·검사 결과가 Django 소유가 아니어서 DB Ownership을 정의할 수 없다. Django가 단순 프록시가 되어 "통합 플랫폼"이 아니다. 검사 결과와 데이터셋이 다른 DB에 있어 학습 데이터 연결(DEC-026)이 다시 외부 연계가 된다. 검사이력·Overlay 화면의 조회·검색 성능이 API에 제약된다.
- 영향 범위: Django 신규 화면 + 프록시 계층.
- Migration 영향: 없음(DB 3개 유지).
- 운영 영향: 서비스 3개 운영.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §23-8("기존 구현이 존재하면 새 구현을 먼저 제안하지 않는다")과 §13("기존 Contract가 있으면 유지/확장/호환계층/폐기를 먼저 판단한다")에 부합한다. 추론 어댑터는 이 프로젝트에서 가장 재현하기 어려운 자산이고 Port Protocol로 이미 분리되어 있어 API화 비용이 낮다. Option C는 통합의 정의 자체를 훼손한다.
- 실행 시 권장: **삭제 전에 vision Server 현재 상태를 백업**한다(git 저장소가 아니므로 디렉터리 복사라도 — C-28).

**사용자 결정**
- [ ] Option A — vision Server를 GPU Server로 축소·개조
- [ ] Option B — GPU Server 신규 작성, vision Server 폐기
- [ ] Option C — vision Server 유지 + Django 프록시
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §4, `06_API_COMPATIBILITY_PLAN.md` §GPU, `07_IMPLEMENTATION_PLAN.md` Phase 5

---

### DEC-007. VisionInspectionClient 호환 전략

**중요도**
- **BLOCKER**

**관련 영역**
- API / Client / Auth

**확인된 사실**
- Client가 실제로 호출하는 엔드포인트는 **6개뿐**이다: `GET /api/v1/health`, `GET /api/v1/catalog`, `POST /api/v1/inspections`, `GET /api/v1/inspections/by-request/{request_id}`, `GET /api/v1/overlays/{id}`, `GET /api/v1/overlays/{id}/image`. (`server_client.py` 전체 확인)
- docstring: "화면에서 쓰지 않는 Endpoint(catalog/version, 단계별 catalog 조회, history, result-image)는 부르지 않는다."
- 인증은 헤더 `X-Client-ID` + `X-API-Key`, SHA-256 해시 비교. 누락 401 `AUTH_REQUIRED`, 불일치/비활성 401 `AUTH_INVALID`.
- 응답 봉투: 성공 `{"data":{...}}`, 실패 `{"error":{"code","message","retryable"}}`. Client가 `error.code`와 `retryable`로 retry를 판단한다.
- **Client는 응답에 담긴 이미지 경로가 `/api/v1` 아래 상대경로가 아니면 거부한다**(`logger.warning("Refused image path outside /api/v1")`). `result_image_url`·`heatmap_url`·`overlay.image_url` prefix를 바꾸면 이미지를 못 받는다. (A-9)
- 타임아웃 connect 3s / read 30s. 응답 이미지 본문 상한 32MB.
- retry 워커는 재전송 전 **항상** `by-request/{request_id}`를 먼저 호출한다.
- `inspection_id`는 UUID 문자열이고 API에 노출된다. 서버 응답의 모든 시각은 **UTC(`Z`) 고정**.
- `docs/API.md`가 계약의 정본이고 통합 테스트가 이를 검증한다.
- MES API 규약은 전혀 다르다(응답이 리스트 또는 `{success,message}`, status 항상 200). (C-09)
- Client 배포본이 `client/deploy/VisionInspectionClient-0.1.3-beta-20260917/`, `client/dist/`에 존재한다 → 빌드·배포 이력이 있다.
- **MES `urls.py`에 `api/v1/token/{login,autologin,logout,refresh}` 4개가 이미 등록되어 있다** → `/api/v1` URL 공간이 겹친다.

**문제/충돌**
MES 패턴을 그대로 적용하면 `/api/v1` 계약을 지킬 수 없다. 계약을 지키려면 MES 응답 규약과 다른 별도 뷰 계층이 Django 안에 생긴다. 또 현장 Client를 재배포할 수 있는지가 전략을 좌우한다(N5 미확인).

**선택지**

#### Option A — Client 무변경, Django에 `/api/v1` 호환 계층 (권장)
- 내용: Django에 `/api/v1/*` 6개를 **계약 그대로** 구현한다. `ApiModuleView`를 쓰지 않고 별도 뷰 계층(`app/views/api_v1/`)을 둔다. 응답 봉투 `{data}`/`{error}`, HTTP status 규약, UTC 시각, `X-Client-ID`/`X-API-Key` 인증, CSRF 면제, 이미지 URL은 `/api/v1` 하위 상대경로를 유지한다. Client는 **설정 파일의 base_url만 변경**한다.
- 장점: 현장 Client 재배포 불필요(설정만). 계약 문서와 통합 테스트를 Contract Test로 이식해 회귀를 막는다. 프롬프트 §6.1 "Client 변경은 최소화"에 정확히 부합.
- 단점: Django 안에 응답 규약이 2종 공존한다. `/api/v1/token/*`(MES PDA)과 URL 공간이 겹친다.
- 영향 범위: Django `app/views/api_v1/` 신규, `configurations/urls.py`, Client 설정 파일.
- Migration 영향: 없음.
- 운영 영향: Client 설정 배포 1회.

#### Option B — 계약 유지 + prefix 변경(`/api/vision/v1`)
- 내용: 응답 스키마·인증·오류 코드는 그대로 두고 URL prefix만 바꾼다.
- 장점: MES `/api/v1/token/*`과 겹치지 않는다. Django URL 체계가 깔끔하다.
- 단점: **Client 코드 변경이 필요하다.** 경로 하드코딩 + 이미지 경로 검증이 `/api/v1` 문자열에 묶여 있다. 재빌드·재배포·현장 설치가 따라온다.
- 영향 범위: Client 6개 경로 + 이미지 경로 검증 + 재빌드/배포.
- Migration 영향: 없음.
- 운영 영향: 현장 Client 전량 교체.

#### Option C — Client를 MES 규약으로 맞춤
- 내용: `/api/inspection/<view>` 형태와 `{success,message}` 응답으로 통일하고 Client를 전면 수정한다.
- 장점: 플랫폼 전체가 한 규약.
- 단점: Client의 retry·idempotency·오류 분류가 `error.code`/`retryable`에 의존하는데 MES 규약에는 그 정보가 없다. **재설계 수준**이고 Client 테스트 37건도 재작성. 검사 실패를 200으로 돌려주는 규약은 장치 통신에 부적합하다.
- 영향 범위: Client 전체 + 서버 계약 재정의 + 문서 재작성.
- Migration 영향: 없음.
- 운영 영향: 현장 Client 전량 교체 + 검증.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §6.1이 Client 변경 최소화를 지시하고 §2.1은 "Client는 GPU Server와 직접 통신하지 않는다"만 요구하므로 경로를 바꿀 이유가 없다. 응답 규약 2종(+GPU용 3종) 공존은 **의도적 설계로 문서화**하면 관리 가능하다.
- `/api/v1/token/*` 충돌 처리 권장: PDA가 현재 범위 밖(DEC-023)이므로 **해당 4개 경로를 이관하지 않는다.** PDA를 살려야 하면 PDA 쪽을 `/api/pda/token/*`으로 옮긴다.

**사용자 결정**
- [ ] Option A — Client 무변경, `/api/v1` 호환 계층
- [ ] Option B — 계약 유지 + prefix 변경(Client 수정)
- [ ] Option C — Client를 MES 규약으로 전면 수정
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `06_API_COMPATIBILITY_PLAN.md` §Client, `07_IMPLEMENTATION_PLAN.md` Phase 6

---

### DEC-008. 검사 이미지·결과의 소유와 추론 호출 방향

**중요도**
- HIGH

**관련 영역**
- Architecture / DB / API / Operation

**확인된 사실**
- 현재 vision Server 처리 순서: metadata 파싱 → idempotency 확인 → 카탈로그 정합성 검증 → 이미지 decode 검증 → **원본 저장** → `inspections` 행 생성(**commit**) → ModelMapping 조회 → 추론 → 결과 컬럼 갱신. **트랜잭션이 저장과 추론 사이에서 끊긴다.**
- 활성 ModelMapping이 없으면 추론하지 않고 `status:"RECEIVED"`. 추론 실패도 행을 남기고 `status:"FAILED"` + `error_message`.
- 결과는 별도 테이블 없이 `inspections` 행의 컬럼이다(`abnormal`, `defects` JSON, `anomaly_score`, `threshold`, `heatmap_path`, `inference_ms`, `model_name`, `model_version`, `error_message`).
- `model_name`/`model_version`은 **문자열 스냅샷**(FK 아님) → 모델이 삭제돼도 기록이 남는다.
- Result Image(원본+BBox / 원본+Heatmap)는 `application/services/result_image.py`가 만든다. Heatmap 색은 **응답의 `threshold` 기준**이다.
- 보존 정책은 이미지 파일만 지우고 행은 남긴다(DETECTION 원본 90일, ANOMALY Heatmap 30일 기본).
- 프롬프트 §3: "동일 Table을 두 서비스가 임의로 수정하는 구조를 피한다", "Transaction Boundary를 명확히 한다."
- DEC-004에서 RLS를 유지하면 GPU Server의 DB 사용자는 테넌트 테이블을 읽을 수 없다(O-6).

**문제/충돌**
`inspections` 행은 WEB이 만들고 추론 결과로 같은 행이 갱신된다. 갱신 주체에 따라 **같은 행에 두 서비스가 Write**할 수 있다. 원본 이미지를 GPU에 어떻게 전달할지도 결정 사항이다.

**선택지**

#### Option A — WEB 소유, GPU는 stateless 추론 (권장)
- 내용: `inspections` 행과 이미지 파일은 **WEB 단독 소유·단독 Write**. WEB이 원본을 저장하고 행을 만든 뒤 GPU에 `POST /inference/{detection|anomaly}`로 **이미지 바이트를 multipart 전송**한다. GPU는 DB에 쓰지 않고 결과 JSON(+Heatmap 이미지)만 반환한다. WEB이 결과를 갱신하고 Result Image를 만든다.
- 장점: Ownership이 명확하다. GPU가 stateless가 되어 수평 확장·재시작이 쉽다. RLS 문제(O-6)가 발생하지 않는다. 보존 정책·파일 관리가 한 곳에 있다. 현재 흐름과 구조가 같아 이식이 직선적이다.
- 단점: 이미지가 네트워크를 한 번 더 지난다. Client read timeout 30s 안에 들어와야 한다. Heatmap PNG를 응답에 실으면 응답이 커진다.
- 영향 범위: WEB `api_v1` + GPU 클라이언트 계층, GPU `/inference/*`.
- Migration 영향: `inspections` 테이블 WEB 소유로 이관.
- 운영 영향: 내부망 대역폭, 타임아웃 예산 설계(DEC-015).

#### Option B — 공유 스토리지 경로 전달
- 내용: WEB이 원본을 공유 볼륨에 저장하고 GPU에 **파일 경로만** 전달한다. GPU가 읽어 추론하고 Heatmap도 공유 볼륨에 쓴다. DB Write는 WEB만.
- 장점: 이미지가 네트워크를 지나지 않아 빠르다. 응답이 작다.
- 단점: WEB과 GPU가 **같은 파일시스템을 공유**해야 한다. 프롬프트 §1.1은 Public/Private Subnet 분리 + Object Storage 제외이므로 서브넷을 넘는 공유 볼륨은 인프라 추가다. GPU가 WEB 소유 디렉터리에 쓴다. 경로 주입 검증이 필요하다.
- 영향 범위: 인프라(공유 볼륨) + 양쪽 저장 계층.
- Migration 영향: 없음.
- 운영 영향: NFS 운영·권한·장애 처리 추가.

#### Option C — GPU가 이미지와 결과를 소유
- 내용: 현재 vision Server처럼 GPU가 이미지를 저장하고 `inspections`도 GPU가 쓴다. WEB은 조회만.
- 장점: 현재 코드 변경이 가장 적다.
- 단점: **프롬프트 §2.2·§3에 어긋난다** — 검사 결과는 업무 데이터다. WEB이 검사 이력 화면·통계를 만들려면 GPU DB를 읽어야 하고 Ownership 원칙이 무너진다. 데이터셋 연결(DEC-026)도 서비스 경계를 넘는다.
- 영향 범위: 적음.
- Migration 영향: 없음.
- 운영 영향: GPU가 대용량 이미지 저장소를 관리.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §3의 Ownership 원칙과 §1.1의 서브넷 분리를 동시에 만족하는 유일한 안이다. GPU를 stateless로 두면 GPU OOM·재시작·모델 교체가 업무 데이터에 영향을 주지 않는다.
- **Heatmap 생성 위치(하위 결정)** 권장: **GPU가 완성된 Heatmap PNG를 반환**한다 — 현재 PatchCore 어댑터가 그렇게 만들고 있고 색 기준이 `threshold`에 묶여 있어 GPU가 갖는 것이 자연스럽다. Result Image(원본+BBox 합성)는 WEB이 만든다.
- **타임아웃 예산(하위 결정)** 권장: Client read 30s 안에서 `WEB 처리 + GPU 호출 ≤ 20s`, GPU 호출 타임아웃 15s, 초과 시 `status:"FAILED"` + `error.retryable=true`.

**사용자 결정**
- [ ] Option A — WEB 소유, GPU stateless 추론(이미지 전송)
- [ ] Option B — 공유 스토리지 경로 전달
- [ ] Option C — GPU가 이미지·결과 소유
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §10·§11, `06_API_COMPATIBILITY_PLAN.md` §GPU, `07_IMPLEMENTATION_PLAN.md` Phase 5

---

### DEC-009. MES `mlops_*` 와 GPU Model Registry의 관계

**중요도**
- HIGH

**관련 영역**
- GPU / DB / 범위

**확인된 사실**
- MES에 **이미** AI 모델 관리 화면 7개가 있다: `wm_mlops_model_master`(모델 마스터 관리), `_config`(모델 설정), `_data`(모델 데이터), `_train`(모델 학습 관리), `_eval`(모델 성능 평가), `wm_mlops_predict_monitor`(예측 모니터링), `_report`(모델 성능 리포트).
- 대응 테이블 5개(`domain/models/mlops.py`, 전부 `managed=False`): `mlops_model`, `mlops_model_config`, `mlops_train_dataset`, `mlops_train_run`, `mlops_prediction`. `mlops_train_run`은 `accuracy`/`precision_val`/`recall_val`/`f1_score`/`mape`/`rmse`/`duration_sec`를 갖는다.
- **그러나 도메인이 비전이 아니다.** `app/views/ai/ai_analysis.py` docstring: "AI 분석 API - 수요예측, 불량예측, 원자재소요량 예측 (scikit-learn 기반)". `LinearRegression`/`Ridge`/`GradientBoostingRegressor`를 쓰고, `mlops_model.target_material_id`·`target_column`·`label_type`이 **tabular 컬럼**을 가리킨다.
- vision `models`는 비전 모델이다(`inspection_type`, `artifact_path`, `runtime`, `threshold`).
- `mlops_*`는 `managed=False`이고 **DDL 원본이 `domain/_sql/`에 없다**(N11).
- 프롬프트 §17은 RAG·AI Chatbot·Vector DB를 명시 제외하지만 tabular MLOps는 언급하지 않는다. §22는 "AI Model Management가 Web/WAS와 GPU에 중복 구현되는 문제"를 핵심 위험으로 든다.

**문제/충돌**
이름은 둘 다 "모델 관리"인데 도메인이 완전히 다르다. 합치면 잘못된 통합이고, 둘 다 가져오면 사용자가 "AI 모델 관리" 메뉴를 두 개 보게 된다.

**선택지**

#### Option A — 분리 유지 + MES MLOps는 현재 범위 제외 (권장)
- 내용: `mlops_*` 테이블과 화면 7개, `ai_analysis.py`를 **이관하지 않는다**(`[FUTURE]`). GPU Registry는 비전 모델 전용으로 신규 설계하고 이름을 `gpu_model`/`gpu_model_version` 등으로 구분한다.
- 장점: 중복 메뉴가 생기지 않는다. 통합 범위가 명확해진다. 나중에 MLOps를 가져올 때 이름이 겹치지 않는다. `managed=False` DDL 부재 문제(N11)를 피한다.
- 단점: 통합 플랫폼에 tabular ML 기능이 없다(MES가 계속 별도로 운영되면 기능 상실은 아니다).
- 영향 범위: 이관 목록에서 제외.
- Migration 영향: 없음.
- 운영 영향: 통합 플랫폼에 tabular ML 기능 없음.

#### Option B — 통합 Registry로 합치기
- 내용: `mlops_model`과 vision `models`를 한 테이블로 합치고 `model_kind`(TABULAR/VISION)로 구분한다.
- 장점: "모델 관리"가 한 곳이다.
- 단점: 두 도메인의 필드가 거의 겹치지 않아 nullable 컬럼이 절반씩 비는 테이블이 된다. tabular 모델은 GPU를 쓰지 않는데 GPU Server가 소유하게 된다. 프롬프트 §22가 경고한 혼동을 키운다.
- 영향 범위: 양쪽 모델·화면.
- Migration 영향: 대규모 통합 + 데이터 변환.
- 운영 영향: 화면 통합 필요.

#### Option C — MES MLOps도 이관하되 별도 도메인으로 유지
- 내용: `mlops_*`와 화면 7개를 가져오되 메뉴를 "생산 데이터 분석"처럼 구분한다.
- 장점: MES 사용자가 쓰던 기능이 통합 플랫폼에도 있다.
- 단점: 현재 3개 도메인에 없는 네 번째 도메인이 생긴다. `managed=False` DDL 확보 필요(N11). scikit-learn·lightgbm·xgboost·pandas·matplotlib 의존성이 WEB에 따라온다(C-24).
- 영향 범위: 화면 7개 + 서비스 + 의존성.
- Migration 영향: DDL 확보 후 Django 모델 재정의.
- 운영 영향: 의존성 증가.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §0-5 "현재 구축 범위와 향후 확장 기능을 혼합하지 않는다"와 §2.2가 정의한 3개 도메인에 부합한다. tabular ML은 목표 아키텍처의 어느 박스에도 들어가지 않는다(GPU Server는 Classification / Object Detection / Anomaly Detection 추론으로 명시).
- **명명 규칙 함께 권장**: GPU Registry 테이블을 `gpu_model`, `gpu_model_version`, `gpu_training_job`, `gpu_evaluation_result`로 둔다. vision의 일반적인 `models` 이름을 그대로 쓰면 MES 합류 시 충돌 여지가 크다(DEC-025).

**사용자 결정**
- [ ] Option A — 분리 유지 + MES MLOps 범위 제외
- [ ] Option B — 통합 Registry
- [ ] Option C — MES MLOps도 이관(별도 도메인)
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §4·§8, `02_FEATURE_MAPPING.md` §4.4

---

### DEC-010. `검사항목 ↔ 모델 매핑`의 모델 참조 방식

**중요도**
- HIGH

**관련 영역**
- DB / API / GPU

**확인된 사실**
- 현재 `model_mappings`: `inspection_item_id` FK → `inspection_items.id`, `model_id` FK → `models.id`, `active`. **검사항목당 활성 매핑 1개**를 부분 unique index(`WHERE active`)로 강제하고, 과거 매핑은 `active=false`로 남겨 이력을 보존한다.
- 프롬프트 §2.2 C·§10·§23-13: `검사항목 ↔ 모델 매핑`은 **WEB 책임**. §2.3 A·§23-12: `Model Registry`는 **GPU 책임**. → 매핑(WEB)이 모델(GPU)을 FK로 가리키는 구조가 된다.
- `models.threshold`(GPU 소유)가 판정 기준이고 API 응답의 `threshold`로 나가며 `abnormal` 판정에 직접 쓰인다.
- `inspections.model_name`/`model_version`은 문자열 스냅샷이다(FK 아님) → **느슨한 참조 선례가 이미 있다.**
- Model Version 엔티티가 생기면(NEW-05) 매핑이 `model_version_id`를 가리켜야 할 수 있다.
- 프롬프트 §3: "동일 Table을 두 서비스가 임의로 수정하는 구조를 피한다", "DB 직접 접근과 REST API 접근 중 어느 방식을 사용할지 Domain별로 구분한다."

**문제/충돌**
DB FK를 유지하면 서비스 경계를 무시하는 강결합이 되고, FK를 버리면 참조 무결성을 애플리케이션이 책임져야 한다.

**선택지**

#### Option A — 같은 DB에 FK 유지
- 내용: `vision_item_model_mapping.model_id` FK → `gpu_model.id`.
- 장점: 유령 참조가 불가능하다. 구현이 단순하다. 현재 구조와 같다.
- 단점: 마이그레이션 소유권이 꼬인다(WEB Django migration이 GPU 테이블을 알아야 FK를 건다 — DEC-011). GPU가 모델을 삭제할 때 `on_delete`에 따라 WEB 매핑이 막히거나 지워진다. GPU를 나중에 다른 DB로 분리할 수 없다. GPU 스키마 변경이 WEB 마이그레이션에 영향을 준다.
- 영향 범위: 마이그레이션 소유권 설계.
- Migration 영향: 한 migration이 양쪽 테이블을 만들거나 FK만 별도 migration.
- 운영 영향: 배포 순서 결합.

#### Option B — FK 없는 식별자 참조 (권장)
- 내용: 매핑이 `model_code` + `model_version` 문자열을 갖는다. DB FK를 걸지 않는다. WEB이 매핑을 저장할 때 GPU `GET /models`로 존재·활성 여부를 확인한다. 검사 실행 시 GPU가 못 찾으면 `MODEL_NOT_FOUND`를 반환하고 WEB은 `status:"FAILED"`로 기록한다.
- 장점: 서비스 독립성 유지. GPU 테이블을 GPU가 단독 소유·마이그레이션한다. 나중에 GPU를 별도 DB로 분리할 수 있다. `inspections`의 문자열 스냅샷과 일관된다.
- 단점: 유령 참조가 생길 수 있다 → 검사 시점 오류와 관리 화면 경고로 대응한다. 정합성 검사 로직이 추가된다.
- 영향 범위: 매핑 모델·서비스·화면 + GPU `GET /models` 호출.
- Migration 영향: `model_id` → `model_code` + `model_version` 컬럼.
- 운영 영향: 모델 삭제 전 매핑 확인 절차 필요.

#### Option C — 매핑을 GPU가 소유
- 내용: `model_mappings`를 GPU Server에 둔다. WEB은 GPU API로 조회·변경한다.
- 장점: 모델 관련 테이블이 한 서비스에 모인다. FK 유지 가능.
- 단점: **프롬프트 §2.2 C·§23-13에 정면으로 어긋난다.** `inspection_item_id`가 WEB 소유 테이블을 가리켜 반대 방향 cross-service FK가 생긴다. 매핑 변경 이력·감사가 GPU에 남아 업무 감사와 갈린다. 업무 설정 변경이 GPU 가용성에 의존한다.
- 영향 범위: 매핑 화면이 전부 GPU API 경유.
- Migration 영향: 매핑 테이블 GPU 소유.
- 운영 영향: GPU 장애 시 업무 설정 변경 불가.

**권장안**
- **Option B**
- 권장 근거: 프롬프트 §3의 "동일 Table을 두 서비스가 임의로 수정하는 구조를 피한다"와 서비스 경계를 동시에 지킨다. FK 하나를 포기하는 대가로 두 서비스의 마이그레이션·배포·DB를 독립시킨다.
- **`threshold` 소유(하위 결정)** 권장: `gpu_model.threshold`를 기본값으로 두고 **WEB 매핑에 `threshold_override`(null 허용)** 를 둔다. 현장 판정 기준 조정은 업무 설정이다. GPU는 요청에 threshold가 오면 그것을, 없으면 모델 기본값을 쓴다.
- **Model Version 참조(하위 결정)** 권장: 매핑이 `model_code` + `model_version`을 **둘 다** 갖고, `model_version`이 null이면 "활성 버전 사용"으로 해석한다. 버전 고정과 자동 추종을 모두 표현할 수 있다.

**사용자 결정**
- [ ] Option A — 같은 DB에 FK 유지
- [ ] Option B — FK 없는 식별자 참조(`model_code` + `model_version`)
- [ ] Option C — 매핑을 GPU가 소유
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §8·§11, `05_DATABASE_MIGRATION_PLAN.md`, `06_API_COMPATIBILITY_PLAN.md` §GPU

---

### DEC-011. 통합 DB 구성과 마이그레이션 기준

**중요도**
- **BLOCKER**

**관련 영역**
- DB / Migration / Operation

**확인된 사실**
- DB 인스턴스가 3개다: MES `10.10.10.230/yest`(search_path `public,das,ai`), AIDataHub `10.10.10.20/aidatahub_v2`, vision `vision_inspection`(기본값).
- 마이그레이션: MES Django 4개(`0001_initial` 4952줄), AIDataHub Django 1개(2026-09-30 재작성 통합본), vision Alembic 13개.
- AIDataHub `AGENTS.md`: 기존 원격 DB의 **FK 제약·자동 인덱스 이름이 `ai_domain_` 접두어로 남아 있고**, "그 전의 migration 파일로 만든 DB는 이어서 쓸 수 없으니 빈 DB에서 다시 `migrate`한다."
- AIDataHub는 `migrate --fake`, `--fake-initial`, `django_migrations` 수동 수정을 **금지**한다.
- MES `domain/_sql/database.sql`은 7줄(DB·사용자·스키마 `das`·`ai` 생성만)이고 **179 테이블의 DDL이 어디에도 없다.** 실제 스키마는 Django 마이그레이션이 만든다(AGENTS.md 서술과 불일치 — C-29).
- MES `mlops_*` 5테이블은 `managed=False`이고 DDL 원본이 없다(N11).
- vision `inspection_type`은 **PostgreSQL native enum 타입**이다(C-26).
- 프롬프트 §23-10: "기존 DB를 삭제하거나 Migration을 초기화하는 방식을 기본안으로 제안하지 않는다."

**문제/충돌**
한 DB에 두 Django 프로젝트의 `django_migrations` 이력을 넣을 수 없고(app label 충돌 — C-03), Alembic → Django 자동 변환 수단도 없다. 반면 프롬프트는 기존 DB 초기화를 기본안으로 삼지 말라고 한다.

**선택지**

#### Option A — 신규 통합 DB + 새 `0001_initial` 하나 (권장)
- 내용: 새 PostgreSQL DB를 만들고 통합 플랫폼의 Django 마이그레이션을 `0001_initial` 하나로 시작한다. **기존 3개 DB는 그대로 둔다**(초기화하지 않는다). 데이터가 필요하면 별도 이관 스크립트로 옮긴다(→ DEC-012). GPU 소유 테이블은 DEC-010 Option B 전제 하에 GPU가 자기 마이그레이션으로 만든다.
- 장점: 제약·인덱스 이름이 일관된다. app label 충돌이 없다. 기존 DB를 파괴하지 않으므로 프롬프트 §23-10을 위반하지 않는다. 롤백이 쉽다(기존 시스템이 그대로 살아 있다).
- 단점: 데이터 이관 스크립트를 따로 만들어야 한다. AIDataHub 기존 DB의 `ai_domain_` 접두어 제약명과 달라져 이관 스크립트가 이름에 의존할 수 없다.
- 영향 범위: 신규 DB 1개(+ GPU 테이블 소유 방식).
- Migration 영향: 통합 `0001_initial` 신규 작성. vision 11테이블을 Django 모델로 재정의(`inspection_type`은 `CharField`+choices로).
- 운영 영향: 기존 3개 시스템과 병행 운영 가능(전환 기간).

#### Option B — MES DB(`yest`)에 추가
- 내용: MES DB를 그대로 쓰고 데이터관리·비전검사 테이블을 추가한다.
- 장점: MES 데이터가 이미 있다면 이관이 불필요하다.
- 단점: MES 179테이블 + 현재 범위 밖 테이블이 모두 따라온다(DEC-023과 모순). MES 마이그레이션 이력 위에 새 이력을 얹어야 해 통합 플랫폼의 `0001`이 MES `0001~0004`에 의존한다. **기존 운영 DB에 직접 스키마 변경**이라 위험하다. `das`·`ai` 스키마의 미지 내용도 따라온다(N8).
- 영향 범위: MES 운영 DB.
- Migration 영향: MES 이력 연장.
- 운영 영향: MES 운영에 직접 영향. 롤백이 어렵다.

#### Option C — 신규 DB + PostgreSQL 스키마 분리
- 내용: 신규 DB를 만들되 `public`(시스템관리) / `vision_data`(데이터관리) / `vision`(비전검사) / `gpu`(GPU 소유) 로 PostgreSQL 스키마를 나눈다.
- 장점: Ownership이 스키마 단위로 가시화된다. GPU DB 사용자에게 `gpu` 스키마 권한만 줄 수 있다. MES가 이미 `search_path` 다중 스키마를 쓰므로 낯설지 않다.
- 단점: Django는 다중 스키마를 1급으로 지원하지 않는다(`db_table = 'schema"."table'` 같은 편법 또는 `search_path` 의존). 마이그레이션·테스트에서 다루기 번거롭다. AIDataHub RLS 정책도 스키마를 넘나든다.
- 영향 범위: 전체 모델 `Meta.db_table`.
- Migration 영향: 스키마 생성 + 권한 부여 마이그레이션 추가.
- 운영 영향: 권한 관리가 명확해진다.

**권장안**
- **Option A**
- 권장 근거: 기존 3개 DB를 파괴하지 않으면서 깨끗한 기준선을 얻는 유일한 안이다. Option B는 프롬프트 §23-10의 취지(기존 DB 보호)와 반대로 오히려 운영 DB를 직접 건드린다. Option C의 스키마 분리는 Ownership 표현에는 좋지만 Django에서 비용이 크고, DEC-010 Option B(FK 없는 참조)를 택하면 GPU 테이블을 **별도 DB로 두는 것도 가능**해져 스키마 분리의 필요가 줄어든다.
- **하위 권장**: GPU 소유 테이블은 통합 DB 안에 두되 **GPU 전용 DB 사용자**를 만들고 해당 테이블에만 권한을 준다. RLS 테이블(DEC-004 Option B)에는 권한을 주지 않는다(O-6 회피).
- **하위 권장**: `inspection_type` PG native enum은 `CharField(choices)`로 바꾼다. API 응답 문자열은 동일하므로 Client 계약에 영향이 없고, `CLASSIFICATION` 추가 시 `ALTER TYPE`이 필요 없어진다.

**사용자 결정**
- [ ] Option A — 신규 통합 DB + 새 `0001_initial`
- [ ] Option B — MES DB에 추가
- [ ] Option C — 신규 DB + PostgreSQL 스키마 분리
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `05_DATABASE_MIGRATION_PLAN.md` 전체, `07_IMPLEMENTATION_PLAN.md` Phase 0·4

---

### DEC-012. 기존 운영 데이터 이관 범위

**중요도**
- HIGH

**관련 영역**
- DB / Migration / Operation

**확인된 사실**
- **세 DB에 운영 데이터가 있는지, 얼마나 있는지 소스에서 확인할 수 없다** (`01_...md` N1). 이 항목은 확인 없이 결정할 수 없다.
- 확인된 정황:
  - AIDataHub `docs/PROJECT_STATUS.md`는 2026-09-23에 원격 `10.10.10.20/aidatahub_v2`(PostgreSQL 16.14)에 대고 `migrate`·`seed_saas_demo`·`seed_mvtecad_demo`·전체 테스트를 실행한 기록을 남겼다 → **최소한 데모 데이터는 있다.**
  - AIDataHub `AGENTS.md`: "원격 DB(`10.10.10.20/aidatahub_v2`)의 migrate·seed·데이터 변경은 사용자 확인 후에만 실행한다. … 운영 데이터다."
  - MES는 "SF사업부 MES 최종버전 솔루션의 기준소스(Baseline)"이고 `10.10.10.230/yest`는 개발 DB로 보인다(`USER='yest_dev'`, `application_name='yest_dev_web_app'`) `[INFERENCE]`.
  - vision Server `settings.py`의 `database_url`은 `127.0.0.1` 기본값이며 실제 값은 `config/.env`에 있다(N12).
- AIDataHub 기존 DB는 제약·인덱스 이름이 `ai_domain_` 접두어로 남아 있어 새 DB와 이름이 다르다.
- 이관이 필요한 데이터에는 **파일도 포함된다**: AIDataHub `MEDIA_ROOT`의 이미지·썸네일·원본·Export zip, vision `storage_root`의 검사 원본·Heatmap·Overlay, `model_root`의 모델 아티팩트.

**문제/충돌**
데이터 이관 여부가 Migration Plan 전체의 복잡도를 결정한다. 무이관이면 스키마만 만들면 되고, 전량 이관이면 컬럼 매핑·사용자 매핑·파일 이동·검증 절차가 모두 필요하다.

**선택지**

#### Option A — 데이터 이관 없음 (신규 시작)
- 내용: 통합 플랫폼을 빈 DB로 시작한다. 기준정보(공정·제품·검사항목·사용자)는 새로 입력하거나 seed 명령으로 넣는다. 기존 3개 시스템은 그대로 두고 필요하면 조회용으로 유지한다.
- 장점: Migration Plan이 단순해진다. 이관 중 데이터 손상 위험이 없다. 구축 속도가 가장 빠르다.
- 단점: 기존 라벨링 데이터·검사 이력이 통합 플랫폼에 없다. 이미 라벨링한 이미지가 많다면 큰 손실이다.

#### Option B — 부분 이관 (기준정보 + 데이터셋/라벨만)
- 내용: 사용자·사용자그룹·권한, vision 기준정보(Process/Product/InspectionItem/Overlay/Client), AIDataHub 과제·데이터셋·이미지·어노테이션까지 이관한다. **검사 이력(`inspections`)과 결과 이미지는 이관하지 않는다**(기존 시스템에서 조회).
- 장점: 재입력 비용이 큰 것(라벨링 데이터)을 보존하면서 이관량을 줄인다. 검사 이력은 시간이 지나면 가치가 떨어지고 보존 정책상 어차피 이미지가 지워진다.
- 단점: 검사 이력 조회를 위해 기존 시스템을 당분간 유지해야 한다. 이관 스크립트가 여전히 필요하다.

#### Option C — 전량 이관
- 내용: 세 시스템의 모든 데이터와 파일을 옮긴다.
- 장점: 기존 시스템을 완전히 폐기할 수 있다.
- 단점: 가장 복잡하고 위험하다. `inspections`는 UUID PK라 충돌은 없으나 이미지 파일이 대량일 수 있다. MES 데이터는 범위 밖 테이블(생산·재고·HACCP)까지 포함되어 DEC-023과 모순된다.

**권장안**
- **확인 후 결정** — 이 항목만은 권장안을 확정하지 않는다.
- 판단에 필요한 값(사용자 확인 후 실행할 쿼리):
  ```sql
  -- AIDataHub (10.10.10.20/aidatahub_v2)
  SELECT count(*) FROM vision_data_tenant;
  SELECT count(*) FROM vision_data_project;
  SELECT count(*) FROM vision_data_imageasset;
  SELECT count(*) FROM vision_data_annotation;
  SELECT count(*) FROM auth_user;
  -- vision-inspection
  SELECT count(*) FROM inspection_items;
  SELECT count(*) FROM inspections;
  SELECT count(*) FROM models;
  SELECT count(*) FROM clients;
  -- MES (10.10.10.230/yest)
  SELECT count(*) FROM auth_user;
  SELECT count(*) FROM user_group;
  ```
  그리고 파일 크기: AIDataHub `media/`, vision `storage_root`·`model_root`.
- 잠정 권장: **어노테이션이 수천 건 이상이면 Option B, 데모 수준이면 Option A.** 라벨링은 재현 비용이 가장 큰 자산이기 때문이다.
- 프롬프트 §12.2("기존 데이터가 있는 경우 데이터 손실 없는 Migration 전략을 작성한다")에 따라, Option B/C를 택하면 사용자 FK 재매핑 전략(`auth_user.id`가 시스템마다 다르다)이 Migration Plan의 핵심 항목이 된다.

**사용자 결정**
- [ ] Option A — 데이터 이관 없음
- [ ] Option B — 부분 이관(기준정보 + 데이터셋/라벨)
- [ ] Option C — 전량 이관
- [ ] 먼저 위 쿼리를 실행해 값을 확인한 뒤 결정
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `05_DATABASE_MIGRATION_PLAN.md` 전체

---

### DEC-013. 표현 계층 규약 — MES 셸과 AIDataHub 화면의 공존 방식

**중요도**
- HIGH

**관련 영역**
- UI / Architecture

**확인된 사실**
- MES: iframe 탭 셸(`index.html` + `.page-tabs`, 업무 화면은 `/gui/<code>/`를 iframe으로), `X_FRAME_OPTIONS='SAMEORIGIN'`, 자체 그리드 `WeZonGrid`, 모달도 iframe, **동기 Ajax 사용**(`layout_page.html`의 즐겨찾기 로드), 템플릿 409개.
- AIDataHub `AGENTS.md`가 이 4가지를 **명문으로 금지**한다: 동적 import dispatch / iframe 탭 셸 / 자체 그리드 위젯 / 동기 Ajax. `X_FRAME_OPTIONS='DENY'`. SPA는 `spa.js`가 `#content-canvas`만 교체.
- AIDataHub 화면 스크립트 규약: 최상위 선언은 `var`만(SPA 재진입 시 재선언 SyntaxError 방지), `destroy()` 필수, `test_per_page_scripts`가 강제. 인라인 `<script>`·JS 안 `{{ var }}`·임의 DB 문자열 `|safe`를 `test_source_boundaries`가 금지.
- AIDataHub 화면 10개 중 **라벨링·검수 화면은 BBOX/POLYGON 좌표 편집 캔버스**다. 그리드로 대체할 수 없다.
- 프롬프트 §4.2·§15: MES UI/UX와 Template 구조를 Backbone으로 하고, "AIDataHub와 vision-inspection 화면을 그대로 옮기기보다 MES UI 패턴에 맞춰 이관한다."

**문제/충돌**
프롬프트는 MES UI 패턴 우선을 지시하지만, 라벨링 캔버스는 MES 패턴(WeZonGrid 목록/폼)으로 표현할 수 있는 화면이 아니다. 전면 재작성은 가장 어려운 기능을 다시 만드는 일이다.

**선택지**

#### Option A — MES 셸 전면 채택 (AIDataHub 화면 10개 전량 재작성)
- 내용: 모든 화면을 MES `layout_page.html` + WeZonGrid + `{% block scripts %}` 규약으로 재작성한다. 라벨링 캔버스도 MES 템플릿 안에 새로 구현한다.
- 장점: 플랫폼 전체가 한 규약이다. 프롬프트 §4.2·§15에 완전히 부합. 개발자가 규약을 하나만 익힌다.
- 단점: **라벨링·검수 캔버스를 처음부터 다시 만든다** — BBOX 드래그·POLYGON 편집·줌/팬·claim/heartbeat/draft/submit 연동·이상탐지 마스크 등. 가장 위험한 재작성이다. AIDataHub 화면 테스트(Playwright)를 전부 잃는다.
- 영향 범위: 화면 10개 + 템플릿 33개 + 화면 스크립트 전부.
- 운영 영향: 일관된 UI.

#### Option B — MES 셸 + 캔버스 화면만 이식 (권장)
- 내용: 공통 셸·메뉴·권한·목록/검색/CRUD 화면은 MES 규약(iframe 탭 + WeZonGrid). **라벨링·검수 캔버스 화면만 AIDataHub 구현을 MES iframe 페이지로 이식**한다(`/gui/<code>/`가 렌더하는 페이지 안에서 기존 캔버스 스크립트를 그대로 쓴다). `X_FRAME_OPTIONS='SAMEORIGIN'` 전역.
- 장점: 재작성 위험이 가장 큰 부분을 피한다. 나머지는 MES 규약이므로 프롬프트 취지를 대체로 따른다. iframe 안에서는 부모 셸과 독립적이라 스크립트 규약 차이가 격리된다.
- 단점: 한 플랫폼에 두 화면 규약이 공존한다. `spa.js` 의존을 걷어내고 iframe 단일 페이지로 동작하게 고치는 작업이 필요하다(`destroy()`·재진입 대응은 iframe에서는 불필요해진다). `X_FRAME_OPTIONS`가 `SAMEORIGIN`이 되어 AIDataHub가 `DENY`로 막던 표면이 넓어진다.
- 영향 범위: 화면 8개 재작성 + 캔버스 화면 2개 이식.
- 운영 영향: 화면에 따라 조작감이 다를 수 있다.

#### Option C — AIDataHub SPA 셸 채택
- 내용: `spa.js` + `#content-canvas` 셸을 쓰고 MES 화면을 이 규약으로 옮긴다.
- 장점: 현대적이고 보안 설정이 엄격하다(`DENY`). AIDataHub 화면·테스트를 그대로 쓴다.
- 단점: **프롬프트 §4.2·§15에 정면으로 어긋난다.** MES 시스템관리·기준정보 화면(DEC-023 범위)을 전부 재작성해야 하고 WeZonGrid를 버린다.
- 영향 범위: 이관하는 MES 화면 전부.
- 운영 영향: MES 사용자에게 낯선 UI.

**권장안**
- **Option B**
- 권장 근거: 프롬프트 §15는 "그대로 옮기기보다 MES UI 패턴에 맞춰 이관한다"이지 "예외 없이 재작성한다"가 아니다. 라벨링 캔버스는 MES에 대응 패턴이 없는 신규 화면 유형이므로, MES 패턴을 적용할 대상 자체가 없다. iframe 셸이라는 MES 구조가 오히려 이종 화면을 담기에 유리하다.
- **함께 권장**: MES `layout_page.html`의 동기 Ajax(`AjaxUtil.getSyncData`)는 이관 시 비동기로 바꾼다(D9). 이는 결정이 아니라 명백한 개선이다.

**사용자 결정**
- [ ] Option A — MES 셸 전면 채택(전량 재작성)
- [ ] Option B — MES 셸 + 캔버스 화면만 이식
- [ ] Option C — AIDataHub SPA 셸 채택
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §7, `07_IMPLEMENTATION_PLAN.md` Phase 7

---

### DEC-014. API 라우팅과 인가 방식

**중요도**
- HIGH

**관련 영역**
- Architecture / Security / API

**확인된 사실**
- MES `/api/<task_name>/<view_name>` → `ApiModuleView`가 `app.views.<task>.<view>` 모듈을 `importlib`로 로드해 동명 함수를 호출한다.
- **`ApiModuleView`에 인가 검사가 없다.** 클래스 docstring: `'''권한 처리여부 결정할 것'''`. 로그인(`request.user.is_anonymous`)만 확인한다.
- `check_user_auth`는 `GUITemplatesView.get()` 한 곳에서만 호출된다(`app/views/__init__.py:240`).
- `GUIConfiguration.taskview_menu_code_map()`이 만드는 `apiPermissionMap`(약 200개 `task/view → [menu_code]`)을 읽는 `get_menu_code_by_taskview()`는 **프로젝트 전체에서 호출되지 않는다**(정의 1곳, 호출 0곳). 즉 **인가 의도는 있었으나 연결되지 않은 死코드**다.
- `TemplatePathView`(`/page/<folder>/<name>`)에도 인가 검사가 없다.
- AIDataHub는 URL 명시 등록 + 뷰별 capability 검사 + RLS를 쓴다. "메뉴 숨김은 UX일 뿐 인가 경계가 아니다"가 규약.
- 프롬프트 §22는 "공유 DB의 Owner 부재"를 위험으로 들지만 API 인가 공백은 언급하지 않는다.

**문제/충돌**
MES 패턴을 그대로 계승하면 통합 플랫폼의 모든 업무 API가 로그인한 누구에게나 열린다. 동시에 DEC-003 Option B(과제 역할 권한)를 구현할 지점도 없다.

**선택지**

#### Option A — MES 동적 dispatch 유지 + 인가 훅 추가 (권장)
- 내용: `/api/<task>/<view>` 형태를 그대로 두고, `ApiModuleView.dispatch()`에 인가 단계를 넣는다. `apiPermissionMap`을 살려 `get_menu_code_by_taskview(task, view)`로 메뉴 코드를 찾고 `check_user_auth`로 R/W를 판정한다. GET은 R, POST는 W를 요구한다. 매핑에 없는 `task/view`는 **기본 거부**(현재 빈 문자열 `''`로 등록된 항목들의 처리 방침을 함께 정해야 한다). 그 위에 DEC-003 Option B의 capability 검사를 얹는다. `TemplatePathView`에도 같은 검사를 건다.
- 장점: MES 구조·파일 배치·View 작성 패턴을 그대로 유지하면서 공백만 메운다(프롬프트 §4.2 준수). 이미 작성된 `apiPermissionMap` 200건을 활용한다. 변경이 디스패처 1곳에 집중된다.
- 단점: **기존 MES 화면 중 매핑이 누락된 것이 있으면 즉시 403이 난다** — 전수 점검이 필요하다(DEC-023으로 범위를 줄이면 부담이 준다). 빈 문자열(`['']`)로 등록된 약 20건(`files/upload`, `system/combo`, `popup/*` 등)은 "권한 검사 없음"을 의도한 것으로 보이는데, 이를 명시적 화이트리스트로 재정의해야 한다.
- 영향 범위: `app/views/__init__.py`, `domain/gui.py`, 이관하는 모든 `task/view`의 매핑 등록.
- API 영향: 권한 없는 호출이 403으로 바뀐다(현재는 200).
- 운영 영향: 메뉴권한 설정이 API까지 실제로 통제한다.

#### Option B — 명시 URL 등록으로 전환
- 내용: AIDataHub처럼 `configurations/urls.py`에 모든 엔드포인트를 명시 등록하고 뷰마다 권한 데코레이터를 붙인다.
- 장점: 라우팅이 명시적이고 권한 지점이 분명하다. AIDataHub 규약과 일치.
- 단점: **MES View 작성 패턴이 근본적으로 바뀐다**(프롬프트 §4.2 위반). 이관하는 MES 화면 수만큼 URL 등록이 필요하다. MES 개발자에게 낯설다.
- 영향 범위: 전체 라우팅.
- API 영향: URL은 같게 유지 가능하나 등록 방식이 바뀐다.
- 운영 영향: 동일.

#### Option C — 현행 유지(인가 훅 없음)
- 내용: MES 그대로 둔다. 화면 권한만으로 통제하고 API는 로그인만 확인한다.
- 장점: 변경이 없다. 이관 중 403 문제가 생기지 않는다.
- 단점: **로그인한 모든 사용자가 모든 업무 API를 호출할 수 있다.** 검사 결과 삭제·사용자 정보 조회·데이터셋 Export 등이 메뉴 권한과 무관하게 실행된다. DEC-003 Option B가 구현 불가가 되어 라벨링 작업 배정 통제가 사라진다. 통합 플랫폼이 외부(Public Subnet)에 노출되는 구조에서 특히 위험하다.
- 영향 범위: 없음.
- API 영향: 없음.
- 운영 영향: 보안 사고 시 책임 소재가 불명확하다.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §4.2는 MES의 "View 작성 패턴"을 계승하라고 하지 인가 공백까지 계승하라고 하지 않는다. `apiPermissionMap`이 이미 작성되어 있다는 사실 자체가 **MES 개발진의 원래 설계 의도가 Option A였음**을 보여준다(docstring `'''권한 처리여부 결정할 것'''`). 연결만 하면 된다.
- **단계적 적용 권장**: 1단계는 매핑 누락 시 **경고 로그만 남기고 통과**시켜 전수 점검을 마친 뒤, 2단계에서 기본 거부로 전환한다. 그러지 않으면 이관 중 화면이 무더기로 깨진다.
- Option C를 선택하는 경우, **DEC-003이 Option A(MES 권한만)로 강제**되며 이 문서에 그 사실을 기록해야 한다.

**사용자 결정**
- [ ] Option A — 동적 dispatch 유지 + 인가 훅 추가
- [ ] Option B — 명시 URL 등록으로 전환
- [ ] Option C — 현행 유지(인가 훅 없음)
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §12, `07_IMPLEMENTATION_PLAN.md` Phase 1·2

---

### DEC-015. WEB ↔ GPU 서비스 간 인증과 장애 정책

**중요도**
- HIGH

**관련 영역**
- API / Security / Operation / GPU

**확인된 사실**
- **현재 WEB ↔ GPU 연계 코드는 세 프로젝트 어디에도 없다.** 전부 신규다(NEW-01, NEW-02, NEW-08).
- 프롬프트 §1.1: GPU Server는 Private Subnet, 외부 직접 공개 금지, Web/WAS ↔ GPU는 내부망 REST.
- 프롬프트 §16.3: "내부망이라도 서비스 간 인증 필요성을 검토한다. 후보: Service API Key / JWT / mTLS / Private Network + API Key. 현재 인프라·운영 복잡도를 고려하여 권장안을 제시한다."
- 프롬프트 §13.4가 요구하는 장애 처리: GPU Timeout / 모델 미로딩 / GPU OOM / Invalid Model / Invalid Request / Training Failure / Inference Failure / DB Failure / Network Failure.
- 참고할 수 있는 기존 구현: vision Client 인증(`X-Client-ID` + `X-API-Key`, SHA-256 해시 보관, 누락/불일치 구분 없이 401, Client별 분당 rate limit). 같은 패턴을 서비스 간에 재사용할 수 있다.
- Client read timeout이 30s다 → WEB이 GPU를 기다릴 수 있는 시간의 상한이 여기서 나온다.
- vision Server `session_secret` 기본값이 `"dev-only-insecure-secret"`이다(D18) → 기본값 방치 위험이 실재한다.

**문제/충돌**
인증 방식과 장애 정책은 API Contract와 함께 확정되어야 하는데 참고할 구현이 없다. 과하게 잡으면 운영 복잡도가 오르고, 없으면 Private Subnet 침해 시 GPU가 무방비다.

**선택지**

#### Option A — Private Subnet + Service API Key (권장)
- 내용: GPU Server는 Private Subnet에서만 listen한다. WEB → GPU 요청에 `X-Service-Key` 헤더를 붙이고 GPU가 해시 비교로 검증한다. 키는 환경변수로 주입하고 소스·로그에 남기지 않는다. 요청마다 `X-Request-ID`(Client `request_id` 또는 신규 UUID)를 전파한다.
- 장점: 구현이 단순하고 vision의 API Key 패턴(`infrastructure/security/api_key.py`)을 그대로 재사용한다. 네트워크 격리 + 애플리케이션 인증의 2중 방어. 운영 부담이 가장 작다.
- 단점: 키 로테이션 절차를 따로 만들어야 한다. 평문 HTTP면 내부망 도청 시 키가 노출된다(내부망 전제에 의존).
- 영향 범위: WEB GPU 클라이언트 계층 + GPU 인증 dependency.
- 운영 영향: 환경변수 1개 관리, 로테이션 절차 문서화.

#### Option B — mTLS
- 내용: WEB과 GPU가 상호 인증서를 검증한다.
- 장점: 전송 암호화 + 상호 인증이 동시에 해결된다. 키 유출 위험이 낮다.
- 단점: 인증서 발급·배포·만료 관리가 필요하다. NCP VPC 내부망에서 운영 부담이 크다. 세 프로젝트에 선례가 없다.
- 영향 범위: 인프라 + 양쪽 HTTP 계층.
- 운영 영향: 인증서 수명주기 관리.

#### Option C — 인증 없음 (네트워크 격리만)
- 내용: Private Subnet 격리와 Security Group만으로 통제한다.
- 장점: 구현·운영이 없다.
- 단점: WEB이 침해되면 GPU가 무방비다. 내부 다른 호스트에서 GPU를 직접 호출할 수 있다. 프롬프트 §16.3이 "필요성을 검토한다"고 한 취지에 못 미친다.
- 영향 범위: 없음.
- 운영 영향: Security Group 규칙에 전적으로 의존.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §16.3이 "현재 인프라/운영 복잡도를 고려"하라고 명시했고, vision에 검증된 API Key 구현이 있어 재사용 가능하다. mTLS는 운영 성숙도가 갖춰진 뒤 단계적으로 올리는 것이 맞다.

**함께 결정할 장애 정책(권장값)**

| 상황 | GPU 응답 | WEB 처리 | Client 응답 |
|---|---|---|---|
| GPU 연결 실패 / Timeout(15s 초과) | — | `inspections.status='FAILED'`, `error_message` 기록 | 200 + `status:"FAILED"`, `error.retryable=true` 힌트 |
| 모델 미로딩 | 503 `MODEL_NOT_LOADED` | 로딩 요청 1회 후 재시도 1회 | 실패 시 `FAILED` |
| 매핑된 모델 없음(GPU에 존재하지 않음) | 404 `MODEL_NOT_FOUND` | `FAILED` + 관리 화면 경고 | `FAILED`, retryable=false |
| GPU OOM | 503 `GPU_RESOURCE_EXHAUSTED` | `FAILED` | retryable=true |
| Invalid Model(아티팩트 손상) | 500 `MODEL_INVALID` | `FAILED` + 모델 비활성화 제안 | retryable=false |
| Invalid Request | 422 | **WEB 버그** — 500 로그 + `FAILED` | retryable=false |
| 추론 실패(기타) | 500 `INFERENCE_FAILED` | `FAILED` | retryable=true |
| DB 실패 | — | 500, 이미지 저장 롤백 | 503, retryable=true |

- **공통 원칙**: 추론이 실패해도 **원본과 검사 행은 남긴다**(현재 vision 동작과 동일). Client에게는 항상 `request_id`로 조회 가능한 상태를 보장한다.
- **재시도**: WEB → GPU는 **연결 실패와 503에만** 1회 재시도(지수 백오프 없이 즉시). 추론 결과가 나온 뒤의 실패는 재시도하지 않는다(중복 추론 비용).
- **Health**: WEB이 GPU `GET /health`를 주기 점검하고 결과를 WEB `/api/v1/health`의 `components`에 포함한다(Client가 이미 이 필드를 읽는다).

**사용자 결정**
- [ ] Option A — Private Subnet + Service API Key
- [ ] Option B — mTLS
- [ ] Option C — 인증 없음(네트워크 격리만)
- [ ] 기타
- 장애 정책 표: [ ] 권장값 승인  [ ] 수정 요청(메모)

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §12, `06_API_COMPATIBILITY_PLAN.md` §GPU

---

### DEC-016. `USE_TZ` 와 시각 저장·표현 기준

**중요도**
- HIGH

**관련 영역**
- DB / API

**확인된 사실**
- MES: `USE_TZ = False`, `TIME_ZONE = 'Asia/Seoul'`. 179테이블의 모든 datetime이 naive다. SQL에서 `to_char(..., 'yyyy-mm-dd hh24:mi')`로 직접 포맷하는 코드가 다수 있다(`AccountService.get_user_list` 등).
- AIDataHub: `USE_TZ = True`, `TIME_ZONE = 'Asia/Seoul'`. 모델의 `created_at`/`updated_at`이 aware.
- vision Server: SQLAlchemy `DateTime(timezone=True)`, **응답 경계에서 UTC(`Z`)로 정규화**. `docs/API.md` §8: "DB(timestamptz)는 세션 TimeZone에 따라 offset을 바꿔 돌려주므로 응답 경계에서 UTC로 정규화한다. 그렇지 않으면 DB 호스트 설정에 따라 같은 API가 다른 형식을 낸다."
- Client는 offset이 있는 시각을 보내고(`capture_timestamp`는 KST 가능) 서버가 UTC로 변환해 저장한다.
- 한 Django 프로젝트에 `USE_TZ`는 하나다.

**문제/충돌**
`USE_TZ=True`로 바꾸면 MES의 naive datetime 코드 전반에서 경고·변환 문제가 생기고, `USE_TZ=False`로 두면 AIDataHub 모델과 vision API의 UTC 계약을 애플리케이션이 수동으로 맞춰야 한다.

**선택지**

#### Option A — `USE_TZ = True` (AIDataHub·vision 기준)
- 내용: 프로젝트 전역 aware. MES에서 이관하는 코드의 datetime 처리를 점검해 수정한다.
- 장점: `/api/v1` UTC 계약과 AIDataHub 모델이 자연스럽다. DB에 `timestamptz`로 저장되어 표준적이다.
- 단점: 이관하는 MES 코드에서 naive/aware 혼용 시 `RuntimeWarning`과 비교 오류가 난다. MES raw SQL의 `to_char` 포맷이 UTC 기준으로 나와 화면에 9시간 어긋날 수 있다 — **SQL 전수 점검이 필요하다**(`domain/services/**`에 SQL이 광범위하다).
- 영향 범위: 이관하는 MES 서비스의 SQL·datetime 처리 전부.
- DB 영향: 컬럼 타입이 `timestamptz`.

#### Option B — `USE_TZ = False` + API 경계 UTC 변환 (권장)
- 내용: MES 기준을 유지한다. DB는 naive KST. `/api/v1/*` 응답 직렬화 시점에 KST → UTC 변환해 `Z`로 내보내고, 요청의 offset 있는 시각은 KST naive로 변환해 저장한다. 변환은 `api_v1` 계층의 공통 직렬화 함수 한 곳에 둔다(vision `api/schemas/common.py`의 `UtcDatetime`과 같은 역할).
- 장점: MES 코드와 SQL을 건드리지 않는다(프롬프트 §4.2 계승, §23-16 최소 변경). Client 계약은 그대로 지켜진다. 변환 지점이 한 곳이라 검증이 쉽다.
- 단점: DB에 naive가 저장되어 서버 시간대가 바뀌면 해석이 흔들린다(단일 국내 사이트 전제에서는 실질 위험이 낮다). AIDataHub 모델 정의에서 `auto_now_add` 등이 naive를 만들게 되어 원 코드와 미세하게 달라진다. 서머타임 없는 KST라 실무 문제는 적다.
- 영향 범위: `api_v1` 직렬화 계층 + AIDataHub 모델 이관 시 datetime 필드 확인.
- DB 영향: 컬럼 타입이 `timestamp`(naive).

#### Option C — `USE_TZ = True` + MES 이관 코드에 KST 강제
- 내용: aware로 가되 MES 계열 화면에는 `localtime` 변환을 일괄 적용한다.
- 장점: 표준을 따르면서 MES 화면 표시를 맞춘다.
- 단점: Option A의 SQL 전수 점검 부담이 그대로 남는다(raw SQL은 Django의 `localtime`을 거치지 않는다).

**권장안**
- **Option B**
- 권장 근거: 프롬프트 §4가 MES 패턴 우선을 지시하고 §23-16이 대규모 수정을 경계한다. MES의 raw SQL 기반 조회가 101개 서비스 모듈에 퍼져 있어 `USE_TZ` 전환의 회귀 위험이 매우 크고, 이를 검증할 MES 테스트가 없다(D6). 반면 UTC 변환은 API 경계 한 곳에서 해결된다.
- 단, **GPU Server는 계속 aware/UTC로 두는 것**을 권한다(FastAPI·SQLAlchemy 그대로). WEB↔GPU 경계에서도 UTC 문자열로 주고받는다.
- 이 결정은 되돌리기 어렵지 않다(나중에 `USE_TZ=True`로 전환 가능). 다만 전환 시점에 데이터 재해석이 필요하다.

**사용자 결정**
- [ ] Option A — `USE_TZ = True`
- [ ] Option B — `USE_TZ = False` + API 경계 UTC 변환
- [ ] Option C — `USE_TZ = True` + MES 이관 코드 KST 강제
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §5, `06_API_COMPATIBILITY_PLAN.md`

---

### DEC-017. `DEFAULT_AUTO_FIELD` / PK 타입

**중요도**
- HIGH

**관련 영역**
- DB / Migration

**확인된 사실**
- MES: `DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'`(int4). 다만 **모델마다 `id = models.AutoField(primary_key=True)`를 명시**하므로 전역 설정을 바꿔도 기존 MES 모델은 영향받지 않는다.
- AIDataHub: `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'`(int8). 모델에 `id`를 명시하지 않는다. 예외로 `Tenant.id`는 **UUID**.
- vision: 전부 `BigInteger` PK. 예외 — `inspections.id`/`request_id`는 **`String(36)` UUID 문자열**(API에 `inspection_id`로 노출), `retention_policies.id`는 `Integer` 고정값 1, `image_migrations.inspection_id`는 `String(36)` PK/FK.
- `inspections.id`를 바꾸면 Client 계약(`inspection_id`, `by-request` 응답, 이미지 URL)이 깨진다.

**문제/충돌**
한 프로젝트에 `DEFAULT_AUTO_FIELD`는 하나다. 이관하는 AIDataHub·vision 모델이 이 설정을 따르게 되므로, MES 기준(int4)으로 가면 기존 int8 데이터가 범위를 넘을 수 있다.

**선택지**

#### Option A — `BigAutoField`(int8) 통일, MES 모델은 명시 유지 (권장)
- 내용: `DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'`. 이관하는 MES 모델은 `id = models.AutoField(primary_key=True)` 명시를 그대로 두어 int4를 유지한다. 신규·이관 모델은 int8. `inspections.id`는 `CharField(36)` PK 유지. `Tenant.id`는 UUID 유지(DEC-004에 따라).
- 장점: AIDataHub 데이터 이관 시 PK 범위 문제가 없다. Django 4+ 권장값이다. MES 모델은 명시 PK라 그대로 동작한다.
- 단점: 테이블마다 PK 타입이 섞인다(int4 / int8 / char(36) / uuid). FK 타입도 그에 맞춰 섞인다.

#### Option B — `AutoField`(int4) 통일
- 내용: MES 기준으로 맞추고 AIDataHub 이관 모델도 int4로 바꾼다.
- 장점: MES 기준 일관. 인덱스가 약간 작다.
- 단점: AIDataHub 기존 데이터의 int8 값이 int4 범위를 넘으면 이관 불가(N1 확인 필요). 이미지 테이블은 행이 빠르게 늘어나 21억 한계가 현실적 제약이 될 수 있다. Django 4+ 권장에 역행한다.

#### Option C — 전 테이블 PK 재설계(UUID 등)
- 내용: 신규 테이블 PK를 UUID로 통일한다.
- 장점: 시스템 간 병합·분산에 유리하다.
- 단점: 범위 밖의 대규모 재설계. MES 모델 전부 변경. 성능·인덱스 크기 불리. 프롬프트 §23-16 위반.

**권장안**
- **Option A**
- 권장 근거: MES 모델이 PK를 명시하고 있어 전역 설정 변경의 영향이 없다는 사실이 결정적이다. 즉 "MES 패턴 유지"와 "이관 데이터 안전" 사이에 충돌이 실제로는 없다.
- 하위 권장: 신규 테이블의 FK 타입은 참조 대상에 맞춘다. MES 기준정보(int4)를 참조하는 신규 테이블의 FK는 int4가 된다 — 정상이다.

**사용자 결정**
- [ ] Option A — `BigAutoField` 통일, MES 모델은 명시 유지
- [ ] Option B — `AutoField`(int4) 통일
- [ ] Option C — 전 테이블 PK 재설계
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `05_DATABASE_MIGRATION_PLAN.md`

---

### DEC-018. vision `admin_users` 폐기와 로그인 보안 기능 이식

**중요도**
- HIGH

**관련 영역**
- Auth / Security / Migration

**확인된 사실**
- vision Server는 `admin_users` 테이블(`username` unique, `password_hash` PBKDF2, `active`, `last_login_at`)과 자체 세션(itsdangerous 서명 쿠키, 기본 8시간)을 쓴다. Admin 권한 등급은 **1개**다.
- `require_admin`은 세션 확인 + **DB 재확인**(계정이 비활성화되면 기존 세션도 즉시 무효) + CSRF를 한다. `login_throttle` 의존성이 있고 `test_admin_login_hardening.py`·`test_admin_session_revocation.py`가 이를 검증한다.
- `cli.py create-admin`으로 계정을 만든다.
- MES 로그인: Django 세션(`mes25-1`). **로그인 시도 제한(throttle)이 없다.** 신규 사용자 초기 비밀번호가 `'1'`로 하드코딩되어 있다(`system/user.py`).
- AIDataHub: Django 세션(`aidatahub-v2`) + `AuthenticationLog`(LOGIN/LOGOUT, ip, user_agent).
- MES에는 `login_log` 테이블이 있다.
- 프롬프트 §16.1: MES 인증/권한을 기준으로 한다. §16.2: 사용자 로그인과 Client 인증을 혼합하지 않는다.

**문제/충돌**
`admin_users`를 폐기하는 것은 방향이 명확하지만, 그러면 vision이 갖고 있던 로그인 하드닝(throttle·세션 DB 재확인)이 사라진다. MES에는 그 기능이 없기 때문이다.

**선택지**

#### Option A — `admin_users` 폐기 + 보안 기능 이식 (권장)
- 내용: vision Admin 계정을 폐기하고 MES `auth_user` + `UserGroupMenu`로 통합한다. 동시에 **`login_throttle`과 세션 DB 재확인을 MES 로그인에 이식**한다. `AuthenticationLog` 대신 MES `login_log`를 쓰되 실패 사유·IP·User-Agent를 기록하도록 보강한다. 초기 비밀번호 `'1'` 하드코딩을 제거한다.
- 장점: 계정이 한 곳이다. 보안 후퇴가 없고 오히려 MES가 개선된다. vision Admin 화면의 권한이 1등급에서 메뉴별 R/W로 세분화된다.
- 단점: MES 로그인 흐름을 수정해야 한다(현재 MES에 테스트가 없어 회귀 확인이 어렵다 — D6). vision Admin 기능별 메뉴 코드와 권한 매핑을 새로 설계해야 한다.
- 영향 범위: MES `AccountLoginView`, `domain/services/account.py`, `login_log` 스키마, `gui.py` 메뉴 등록.
- Migration 영향: `admin_users` 테이블 제외. 기존 vision 관리자는 MES 사용자로 재생성(비밀번호 재설정).
- 운영 영향: vision 관리자 계정 재발급 안내 필요.

#### Option B — `admin_users` 폐기, 보안 기능 미이식
- 내용: MES 로그인을 그대로 쓰고 throttle·세션 재확인은 가져오지 않는다.
- 장점: MES 변경이 없다. 가장 빠르다.
- 단점: **보안 후퇴다.** 통합 플랫폼은 Public Subnet에 있어 vision(내부망 전용)보다 노출이 크다. 무차별 대입 방어가 없어진다.
- 영향 범위: 없음.
- Migration 영향: 동일.
- 운영 영향: 보안 수준 하락.

#### Option C — `admin_users` 유지(이중 계정)
- 내용: vision Admin 기능을 GPU Server에 남기고 별도 관리자로 운영한다.
- 장점: vision Admin 코드를 그대로 쓴다.
- 단점: DEC-006 Option A(Admin 제거)와 모순된다. 관리자 계정이 두 곳이고 감사가 갈린다.
- 영향 범위: DEC-006과 충돌.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §4.3이 "로그인/인증"을 MES 기준으로 재사용하라고 하면서도 §4 말미에 "MES에 기술 부채나 구조적 문제가 확인되면 분리하여 제시한다"고 한다. 로그인 throttle 부재는 명백한 부채이고, 이식할 검증된 구현이 바로 옆에 있다.

**사용자 결정**
- [ ] Option A — 폐기 + throttle·세션 재확인 이식
- [ ] Option B — 폐기, 보안 기능 미이식
- [ ] Option C — `admin_users` 유지
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §12, `07_IMPLEMENTATION_PLAN.md` Phase 2

---

### DEC-019. 파일 저장소 레이아웃과 이미지 제공 방식

**중요도**
- HIGH

**관련 영역**
- Operation / Security / API

**확인된 사실**
- MES: `FILE_UPLOAD_PATH='c:\temp\mes21\'` 등 **Windows 절대경로 5개 하드코딩**, 부팅 시 `os.makedirs`. 파일 제공은 `app/views/files/`(`/api/files/<view_name>`, CSRF 면제).
- AIDataHub: `MEDIA_ROOT = BASE_DIR/media`, 테넌트별 경로(`tenants/{tenant_id}/...`), `FILE_UPLOAD_PERMISSIONS = 0o640`. **규약: "공개 `MEDIA_URL`로 파일 서비스, nginx가 `/media/`를 직접 서비스"를 금지.** 권한 확인 View 4종(`PrivateImageView`, `PrivateImageThumbnailView`, `PrivateProjectCoverView`, `PrivateExportView`)만 제공.
- vision: `storage_root`(원본·heatmap·overlay), `model_root`(모델 아티팩트), `migration_export_root`, `distribution_root`(**무인증 공개**). 검사 원본 경로는 `inspections/{YYYY}/{MM}/{DD}/{inspection_id}/original.{ext}`.
- 업로드 상한: MES 미설정(Django 기본 2.5MB 메모리), AIDataHub 30MB/35MB, vision은 경로별 Body size limit 미들웨어(413/411).
- Client는 이미지 URL이 `/api/v1` 하위 상대경로가 아니면 거부한다(A-9).
- 보존 정책: 이미지 파일만 삭제(원본 90일 / Heatmap 30일 기본, 초기 상태 꺼짐), 행은 유지. CLI `purge-images` + systemd timer 03:30.
- 프롬프트 §1.1: "서버 내부 저장 디렉터리 구조는 본 Architecture의 핵심 설계 대상이 아니다", "Object Storage는 현재 구성 범위에서 제외한다."

**문제/충돌**
프롬프트는 저장 구조를 핵심 설계 대상이 아니라고 하지만, **권한 확인 여부·보존 정책·검사 이미지의 데이터셋 재사용(DEC-026)이 모두 저장 설계에 걸린다.** Windows/Linux 경로 혼재로 DEC-020과도 묶인다.

**선택지**

#### Option A — 단일 루트 + 권한 확인 View 전용 (권장)
- 내용: 환경변수 `STORAGE_ROOT` 하나 아래 용도별 하위 디렉터리를 둔다.
  ```text
  $STORAGE_ROOT/
  ├─ datasets/     데이터셋 이미지·썸네일·원본(편집 전)
  ├─ standards/    데이터 표준 예시 이미지
  ├─ exports/      Export zip
  ├─ inspections/  검사 원본·Heatmap  (YYYY/MM/DD/{inspection_id}/)
  ├─ overlays/     Overlay 이미지
  ├─ covers/       과제 대표 이미지
  └─ attachments/  MES 공통 첨부
  ```
  **모든 이미지·파일은 권한 확인 View로만 제공한다.** nginx는 `/static/`만 직접 서비스한다. Client용 이미지 URL은 `/api/v1/...` 경로를 유지한다(A-9).
- 장점: AIDataHub의 검증된 보안 규약을 채택한다. 경로가 하나라 백업·용량 관리가 쉽다. 검사 이미지와 데이터셋 이미지가 같은 루트에 있어 DEC-026 연결 시 파일 이동/링크가 쉽다.
- 단점: 모든 이미지가 Django를 거쳐 성능 부담이 있다(썸네일 목록 화면에서 특히). 필요 시 `X-Accel-Redirect`(nginx) 도입을 검토해야 한다.
- 영향 범위: MES `files/` 뷰 + AIDataHub Private View 4종 + vision 이미지 라우트 통합.
- 운영 영향: 단일 백업 대상, 용량 모니터링 1곳.

#### Option B — 용도별 분리 + 일부 직접 서비스
- 내용: 데이터셋 이미지는 권한 확인 View, 검사 결과 이미지는 nginx 직접 서비스(경로가 UUID라 추측 불가).
- 장점: 성능이 좋다.
- 단점: **UUID 경로는 인가가 아니다.** URL이 유출되면 누구나 본다. AIDataHub 규약 위반. 검사 이미지에는 불량 사진이 담긴다.
- 영향 범위: nginx 설정 + 일부 View 생략.
- 운영 영향: 성능 유리, 보안 불리.

#### Option C — 현행 3종 경로 유지
- 내용: MES·AIDataHub·vision의 경로 체계를 각각 유지한다.
- 장점: 이관 시 경로 관련 변경이 없다.
- 단점: Windows 경로가 Linux 배포에서 동작하지 않는다(DEC-020). 백업·용량 관리 대상이 3곳. 검사 이미지 ↔ 데이터셋 연결이 복잡해진다.

**권장안**
- **Option A**
- 권장 근거: AIDataHub가 "공개 MEDIA_URL 금지"를 규약으로 둔 이유(권한 확인 우회 방지)가 통합 플랫폼에서 더 중요해진다 — Public Subnet에 노출되기 때문이다. 프롬프트가 저장 구조를 핵심 설계 대상이 아니라고 한 것은 디렉터리 이름 논의를 줄이라는 뜻으로 읽는 것이 자연스럽다.
- **함께 권장**: 업로드 상한을 경로별로 명시한다 — 데이터셋 업로드 30MB/파일, 검사 이미지 10MB, Overlay 10MB(현재 vision 값), Export 다운로드는 스트리밍.

**사용자 결정**
- [ ] Option A — 단일 루트 + 권한 확인 View 전용
- [ ] Option B — 용도별 분리 + 일부 직접 서비스
- [ ] Option C — 현행 3종 경로 유지
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §2, `07_IMPLEMENTATION_PLAN.md` Phase 0

---

### DEC-020. 배포 OS / 웹서버 / 앱서버

**중요도**
- HIGH

**관련 영역**
- Operation / Architecture

**확인된 사실**
- MES: Windows + **IIS + wfastcgi**. `requirements.txt`에 `wfastcgi==3.0.0`, `pyodbc`. 파일 경로가 Windows 절대경로. `whitenoise` + `STATIC_ROOT` + `collectstatic`.
- AIDataHub: Linux + **nginx + waitress**. `STATIC_ROOT`를 두지 않고 nginx가 `app/static/`을 직접 읽는다(2026-09-21 결정). systemd 워커.
- vision Server: **Ubuntu 24.04 LTS + nginx + uvicorn + systemd**. offline wheelhouse 배포, systemd timer.
- vision Client: Windows 11 + PyInstaller EXE.
- 프롬프트 §1: Web/WAS Server는 **Nginx → Django**. §1.1: NCP VPC, Public Subnet(Web/WAS), Private Subnet(GPU, DB).
- GPU Server는 CUDA 때문에 Linux가 사실상 필수다 `[INFERENCE]`.
- **NCP 대상 OS는 확인되지 않았다**(N4).

**문제/충돌**
프롬프트가 Nginx를 명시하므로 Linux가 자연스럽지만, MES는 IIS 전제로 만들어졌고 Windows 절대경로가 코드에 박혀 있다.

**선택지**

#### Option A — Ubuntu 24.04 + nginx + gunicorn/waitress + systemd (권장)
- 내용: WEB과 GPU 모두 Ubuntu. WEB은 nginx + gunicorn(또는 waitress) + systemd. GPU는 uvicorn + systemd.
- 장점: 프롬프트 §1의 Nginx 구성과 일치. GPU와 OS가 같아 운영 표준이 하나. vision Server의 배포 문서·offline wheelhouse·systemd unit을 재사용할 수 있다. AIDataHub 배포 경험도 그대로 쓴다.
- 단점: MES의 Windows 경로 5개와 IIS 배포 절차를 버려야 한다(환경변수화로 해결 — DEC-019). MES 운영팀에게 새로운 환경이다. `wfastcgi`·`pyodbc` 제거 필요.
- 영향 범위: MES 설정·경로·requirements.
- 운영 영향: 배포·모니터링 절차 신규 작성.

#### Option B — Windows + IIS + wfastcgi (MES 기준 계승)
- 내용: WEB을 Windows/IIS로 배포하고 GPU만 Linux.
- 장점: MES 운영팀의 기존 경험을 그대로 쓴다. MES 경로 변경이 최소다.
- 단점: **프롬프트 §1이 명시한 Nginx 구성과 어긋난다.** AIDataHub 배포 자산을 못 쓴다. 백그라운드 워커(DEC-022)를 Windows 서비스로 다시 만들어야 한다. OS가 둘이라 운영 표준이 갈린다.
- 영향 범위: 워커·정적파일·경로.
- 운영 영향: 이종 OS 운영.

#### Option C — 컨테이너(Docker) 기반
- 내용: WEB·GPU를 컨테이너로 배포한다.
- 장점: 환경 재현성이 높다.
- 단점: 세 프로젝트 어디에도 Dockerfile이 없다 — 전부 신규. GPU는 NVIDIA Container Toolkit 필요. 인터넷 차단 환경에서 이미지 배포 절차를 새로 만들어야 한다. 프롬프트 범위에 없다.
- 영향 범위: 배포 전반 신규.
- 운영 영향: 컨테이너 운영 역량 필요.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §1이 `Nginx → Django`를 아키텍처에 명시했고 GPU Server가 Linux여야 하므로 OS를 하나로 맞추는 편이 운영이 단순하다. vision Server가 이미 Ubuntu 24.04 + nginx + systemd 배포 문서를 갖고 있어 재사용 가능하다.
- **앱서버 세부**: `gunicorn`과 `waitress` 중 운영팀 선호를 따르면 된다(기능 차이가 결정적이지 않다).
- **확인 필요**: MES 코드에 Windows 전용 API 의존이 더 있는지 이관 시점에 점검한다(현재까지 발견된 것은 파일 경로뿐).

**사용자 결정**
- [ ] Option A — Ubuntu 24.04 + nginx + gunicorn/waitress + systemd
- [ ] Option B — Windows + IIS + wfastcgi
- [ ] Option C — 컨테이너(Docker) 기반
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §2, `07_IMPLEMENTATION_PLAN.md` Phase 0·9

---

### DEC-021. 다국어 적용 범위

**중요도**
- MEDIUM

**관련 영역**
- UI / Operation

**확인된 사실**
- MES: `label_code` / `label_code_lang` / `grid_col_lang` 테이블 + `static/lang/` 리소스 + 관리 화면 2개(`wm_multi_language`, `wm_menu_language`). ko / en / zh / vi 4언어. `UserProfile.lang_code`(기본 `ko-KR`). `domain/services/lang.py.deprecated`가 남아 있다.
- AIDataHub: "화면 문구는 템플릿에 한국어로 직접 쓴다. 기존 `data-commonCd`·`data-labelCd` 속성은 그대로 두고 **새로 늘리지 않는다. 라벨 API 기반 i18n은 도입하지 않는다.** 다국어가 필요해지면 별도 스펙으로 다룬다." 단 `UserProfile.lang_code` 필드는 갖고 있다.
- vision Server Admin·Client: 한국어 고정.
- 프롬프트는 다국어를 요구하지도, 제외하지도 않았다.

**문제/충돌**
MES 기준으로 가면 이관·신규 화면 전부에 라벨코드를 등록해야 한다(데이터관리 10화면 + 비전검사 9화면 + 신규). 상당한 부수 작업이고 AIDataHub 코드에는 라벨코드 속성이 거의 없다.

**선택지**

#### Option A — 1단계 한국어 고정 (권장)
- 내용: MES 라벨코드 인프라(테이블·관리 화면)는 **유지**하되 신규·이관 화면에는 적용하지 않는다. 이관한 MES 시스템관리 화면은 기존 라벨코드를 그대로 쓴다. 다국어는 별도 Phase로 분리한다.
- 장점: 이관 작업량이 크게 준다. AIDataHub 화면을 수정 없이 옮길 수 있다. 인프라가 남아 있어 나중에 적용 가능하다.
- 단점: 화면에 따라 다국어 지원 여부가 다르다. 소급 적용하려면 화면을 다시 손대야 한다.

#### Option B — 전 화면 라벨코드 적용
- 내용: 모든 이관·신규 화면에 `data-labelCd`를 붙이고 4언어 라벨을 등록한다.
- 장점: 일관된 다국어 지원.
- 단점: 화면당 수십 개 라벨 등록 + 4언어 번역. 이관 일정이 늘어난다. 현재 요구사항인지 불명확하다.

#### Option C — 라벨코드 인프라 제거
- 내용: MES 다국어 기능을 이관하지 않고 한국어 전용으로 간다.
- 장점: 가장 단순하다.
- 단점: 이관하는 MES 시스템관리 화면이 라벨코드에 의존하면 수정이 필요하다. 나중에 다국어가 필요해지면 처음부터 만든다.

**권장안**
- **Option A**
- 권장 근거: 프롬프트가 다국어를 요구하지 않았고 §0-5("현재 구축 범위와 향후 확장 기능을 혼합하지 않는다")에 따라 범위를 늘리지 않는 편이 맞다. 인프라를 제거하지 않는 것은 MES 화면을 수정 없이 이관하기 위해서다.
- **확인 필요**: 사용자가 국내 단일 사이트인지. 해외 사업장이 대상이면 Option B를 처음부터 검토해야 한다.

**사용자 결정**
- [ ] Option A — 1단계 한국어 고정(인프라 유지)
- [ ] Option B — 전 화면 라벨코드 적용
- [ ] Option C — 라벨코드 인프라 제거
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `07_IMPLEMENTATION_PLAN.md` Phase 7

---

### DEC-022. 백그라운드 작업 처리 기반

**중요도**
- MEDIUM

**관련 영역**
- Operation / Architecture

**확인된 사실**
- AIDataHub: `BackgroundJob`(`job_type` QUALITY/EXPORT, `status` QUEUED/RUNNING/COMPLETED/FAILED, `payload`/`result` JSON) + `manage.py run_worker`(상주) / `process_jobs`(1회). 특징:
  - `_claim_next`가 **`FOR UPDATE SKIP LOCKED`** 로 원자적 claim, claim과 본문을 **별도 트랜잭션**으로 분리.
  - API는 202로 즉시 반환, 화면이 폴링(Export 3초×20회, 품질점검 1.5초×10회).
  - 다중 워커 실측 검증(워커 2개 × 대기 20건 → 11/9 분배, 중복 0건, 2026-09-24).
  - 실패는 `FAILED` + `error_message`(255자 절단). **재시도·백오프 없음**(알려진 미비점 D10).
  - `payload`에는 식별자만 넣는다. 작업 본문은 `tenant_atomic(tenant)` 안에서 실행.
- MES: `batch_q` / `batch_log` 테이블과 `system/batch_log.py` 화면이 있으나 **워커 구현이 소스에서 명확하지 않다** `[NEEDS_CONFIRMATION]`.
- vision: 웹 프로세스와 분리된 CLI + systemd timer(`purge-images` 03:30). 이유가 문서화되어 있다 — "단일 Worker에서 대량 삭제를 돌리면 검사 요청이 밀린다."
- 통합 후 필요한 작업: 데이터 품질 점검, Export 생성, 이미지 보존 정리, (DEC-026) 검사 이미지 → 데이터셋 이관, (DEC-027) 학습 Job 폴링.

**문제/충돌**
세 방식이 공존한다. 하나를 고르지 않으면 신규 작업마다 방식이 달라진다.

**선택지**

#### Option A — AIDataHub `BackgroundJob` + 워커 채택 (권장)
- 내용: `BackgroundJob`과 `run_worker`/`process_jobs`를 이식해 표준 큐로 쓴다. 보존 정책 정리는 vision 방식대로 별도 management command + systemd timer로 둔다(정기·대량 작업이라 큐에 넣지 않는다). MES `batch_q`는 이관하지 않는다.
- 장점: 가장 검증된 구현이다(행 잠금·트랜잭션 분리·다중 워커 실측). 작업 종류 추가 지점이 `JobService._execute` 한 곳으로 문서화되어 있다. Export·품질점검을 큰 변경 없이 옮긴다.
- 단점: 워커 프로세스를 별도 운영해야 한다(systemd unit 추가). **재시도·백오프가 없다.** `error_message` 255자 절단을 늘리는 것이 좋다.
- 영향 범위: `BackgroundJob` 모델 + `JobService` + management command 2개 + systemd unit.
- 운영 영향: 워커 모니터링 필요("대기 중이 안 풀린다"는 문의 시 워커 상태부터 확인).

#### Option B — MES `batch_q` 기반으로 통일
- 내용: MES 배치 테이블·화면을 쓰고 워커를 여기에 맞춘다.
- 장점: MES 배치 로그 화면을 재사용한다. MES 패턴 계승.
- 단점: **워커 구현을 확인하지 못했다.** 행 잠금·다중 워커·트랜잭션 분리 여부가 불명이다. AIDataHub Export·품질점검 서비스를 재작성해야 한다. 검증된 구현을 버리고 미검증 구현을 택하는 셈이다.
- 영향 범위: AIDataHub 작업 서비스 재작성.
- 운영 영향: MES 배치 로그 화면 사용.

#### Option C — 동기 실행(큐 없음)
- 내용: 품질점검·Export를 요청 처리 중에 끝낸다.
- 장점: 워커 프로세스가 필요 없다.
- 단점: **AIDataHub가 명시적으로 금지한 방식이다** — "응답이 길어지고 워커 경로와 동작이 갈린다." Export는 이미지 수천 장을 zip으로 묶으므로 웹 요청 타임아웃이 난다.
- 영향 범위: 서비스 재작성.
- 운영 영향: 타임아웃 사고.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §23-8("기존 구현이 존재하면 새 구현을 먼저 제안하지 않는다"). AIDataHub 구현은 실측 검증 기록까지 있는 반면 MES 배치는 동작을 확인하지 못했다. 배치 로그 **화면**만 MES 것을 쓰고 싶다면 `BackgroundJob`을 조회하도록 뷰를 고치면 된다.
- **함께 권장**: 재시도·백오프를 추가한다(`attempt_count`, `next_retry_at`). GPU 학습 Job 폴링(DEC-027)처럼 실패가 흔한 작업을 큐에 넣으려면 필요하다.

**사용자 결정**
- [ ] Option A — AIDataHub `BackgroundJob` + 워커 채택
- [ ] Option B — MES `batch_q` 기반으로 통일
- [ ] Option C — 동기 실행
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §3, `07_IMPLEMENTATION_PLAN.md` Phase 3

---

### DEC-023. MES에서 가져올 범위

**중요도**
- **BLOCKER**

**관련 영역**
- 범위 / Architecture / DB / Operation

**확인된 사실**
- MES 규모: 뷰 모듈 363 / 템플릿 409 / 서비스 101 / `db_table` 선언 179 / 등록 GUI 374.
- 업무 영역: 기준정보, 영업/수주, 생산계획, 생산실적, 재고/LOT, 품질(검사·부적합·SPC), 출하, 설비보전, HACCP, 인원/위생, 시스템, AI(NL2SQL·챗봇·MLOps), 모바일/PDA, 설비연계(DAS/MQTT).
- 프롬프트 §2.2는 ManufacturingAIPlatform의 Domain을 **3개로 한정**한다: 데이터 관리 / 비전 검사 관리 / 시스템 관리.
- 프롬프트 §17은 RAG·AI Chatbot·Vector DB·문서관리·지식베이스·Object Storage·2~3차년도 확장을 **명시 제외**한다.
- 고객사 전용 코드가 기준소스에 섞여 있다(`_junshi`, `_snp`, `_woori`, `_sejun`, `_gs`, `_pzas` 등). 전시회/데모 코드도 있다(`wm_dashboard_exhibition_*`, `public/exhibition/`, `dt_main.html` — 이 화면은 주석에 "데이터 BLOCKED"라고 적혀 있다).
- `UserProfile`이 `Factory`·`Company`·`Depart` FK를 갖는다 → 이 3개 기준정보 테이블은 사용자 모델을 위해 필수다(DEC-002 Option A 전제).
- MES 기준정보 중 vision 도메인과 의미가 겹치는 것: `process`(공정), `material`(자재/제품), `defect_type`(불량유형) — DEC-025.
- MQTT(`MOSQUITTO_HOST=10.10.10.231`)와 DAS 설비연계는 브로커·설비 의존을 동반한다.

**문제/충돌**
"MES를 Backbone으로 한다"를 "MES 전체를 가져온다"로 읽으면 통합 플랫폼이 MES의 복제본 + 데이터관리·비전검사가 된다. 프롬프트가 정의한 3개 도메인과 맞지 않고, 이관·테스트·운영 부담이 10배가 된다. 반대로 너무 줄이면 시스템관리 화면이 참조하는 기준정보가 없어 동작하지 않는다.

**선택지**

#### Option A — MES 전체 이관 후 메뉴 권한으로 숨김
- 내용: MES 374 GUI·179 테이블을 모두 가져오고 사용하지 않는 메뉴는 `UserGroupMenu`로 숨긴다.
- 장점: 나중에 생산·재고 기능이 필요해지면 바로 켤 수 있다. MES 코드를 선별하는 판단 비용이 없다.
- 단점: **범위가 3개 도메인을 크게 벗어난다.** 고객사 전용·전시회 코드까지 따라온다. MQTT·DAS·MLOps·NL2SQL 의존성(paho-mqtt, scikit-learn, lightgbm, xgboost, torch, matplotlib, pyodbc, basyx-python-sdk)이 전부 설치된다(C-24). DEC-014의 인가 훅 적용 시 374개 화면의 권한 매핑을 전수 점검해야 한다. 숨긴 메뉴의 API는 인가가 없으면 여전히 호출 가능하다(C-05).
- 영향 범위: 전체.
- 운영 영향: 배포 이미지·취약점 표면이 크다.

#### Option B — 시스템관리 + 최소 기준정보 (권장)
- 내용: 다음만 이관한다.
  - **공통 골격**: `configurations`, `app/views/__init__.py`(디스패처), `domain/gui.py`, 공통 서비스(`sql.py`, `logging.py`, `common.py`, `date.py`, `file.py`, `combo.py`, `_common`, `_form`), 공통 템플릿·static(WeZonGrid 포함), 401/403/404/error 화면, `AbstractAuditModel`, `seq_maker`, 첨부파일(`attach_master`/`attach_file`).
  - **시스템관리**: 사용자, 사용자그룹, 메뉴권한, 메뉴 설정, 공통코드(`sys_code`/`user_code`), 시스템옵션, 로그 4종(login/menu_use/sys/batch), 즐겨찾기, 그리드 설정(`grid_col`), 다국어(DEC-021에 따라 인프라만), 속성/분류 마스터.
  - **최소 기준정보**: `factory`, `company`, `depart`, `unit`(+ DEC-025 결과에 따라 `process`/`material`/`defect_type`).
  - 제외: 영업/수주, 생산계획, 생산실적, 재고/LOT, 출하, 품질(test/check/spc), HACCP 전체, 설비보전, 인원/위생, DAS/MQTT/HMI, 대시보드/요약, 모바일/PDA, AI(NL2SQL/챗봇/MLOps/ai_analysis), 전시회·디지털트윈, 고객사 전용 모듈, 샘플 화면.
- 장점: 프롬프트 §2.2의 3개 도메인과 정확히 일치한다. 의존성이 대폭 준다(paho-mqtt·pyodbc·scikit-learn 계열·torch·시각화 라이브러리 제거). 인가 매핑 전수 점검 대상이 수십 건으로 줄어든다. 테스트를 처음부터 만들기 현실적인 규모다.
- 단점: 이관 대상을 하나씩 판단해야 한다(특히 공통 서비스의 의존 추적). 나중에 생산 기능이 필요하면 다시 가져와야 한다. MES와 통합 플랫폼이 별도 시스템으로 병행 운영된다.
- 영향 범위: 선별 이관.
- 운영 영향: 두 시스템 병행(MES는 계속 운영).

#### Option C — Option B + 생산/품질 일부
- 내용: Option B에 더해 품질(`test_*`)·생산실적 일부를 가져와 비전 검사 결과와 연계한다.
- 장점: 비전 검사 결과를 MES 품질 데이터와 이을 수 있다.
- 단점: `test_*`와 비전 `inspections`의 "검사" 용어 충돌이 실제 문제가 된다(C-12). 생산실적을 가져오면 작업지시·LOT·자재가 연쇄로 따라온다. 프롬프트 범위를 벗어난다.
- 영향 범위: Option B + 품질·생산 도메인.
- 운영 영향: 범위 확대.

**권장안**
- **Option B**
- 권장 근거: 프롬프트 §0-5("현재 구축 범위와 향후 확장 기능을 혼합하지 않는다")와 §2.2의 3개 도메인 정의가 명확하다. Option A는 "Backbone으로 사용한다"를 "전부 복사한다"로 오독한 결과가 되고, 프롬프트 §19("단순 Copy/Paste는 기본 전략으로 사용하지 않는다")에도 어긋난다.
- **중요**: Option B를 택하면 **MES는 폐기되지 않고 계속 별도 운영**된다는 뜻이다. 생산·재고·HACCP 사용자는 기존 MES를 쓴다. 이 전제가 맞는지 확인이 필요하다 — 만약 "MES를 대체한다"가 목표라면 범위가 완전히 달라진다.
- 이관 목록의 상세는 `02_FEATURE_MAPPING.md` §4에 있다. 결정 후 그 표를 확정본으로 삼는다.

**사용자 결정**
- [ ] Option A — MES 전체 이관 후 메뉴로 숨김
- [ ] Option B — 시스템관리 + 최소 기준정보
- [ ] Option C — Option B + 생산/품질 일부
- [ ] 기타

**추가 확인 질문**
- ManufacturingAIPlatform이 **MES를 대체**하는가, **MES와 병행**하는가?
  - [ ] 병행(MES 계속 운영)
  - [ ] 대체(장기적으로 MES 기능 흡수)

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `02_FEATURE_MAPPING.md` §4, `04_TARGET_ARCHITECTURE.md` §3, `07_IMPLEMENTATION_PLAN.md` Phase 1

---

### DEC-024. vision 무인증 배포물 엔드포인트 처리

**중요도**
- MEDIUM

**관련 영역**
- Security / API / Operation

**확인된 사실**
- vision Server에 `GET /api/v1/licenses/sources[/{filename}]`(LGPL 대응 소스)와 `GET /api/v1/client-packages[/{filename}]`(Client 배포 zip)가 있다.
- `settings.py` 주석: "API로 내려주는 배포물 위치 … **이 아래 파일은 인증 없이 공개된다** — 내부망 한정은 방화벽이 지킨다(SERVER_DEPLOYMENT.md §41). 공개해도 되는 파일만 넣는다."
- **VisionInspectionClient는 이 두 엔드포인트를 호출하지 않는다**(`server_client.py` 확인).
- 목표 아키텍처에서 ManufacturingAIPlatform은 **Public Subnet**에 있고 외부 사용자가 HTTPS 443으로 접근한다(프롬프트 §1.1). vision Server는 내부망 전용 전제였다.
- LGPL 대응 소스 제공은 `client/docs/LICENSE_COMPLIANCE.md`의 라이선스 의무와 연결되어 있다 `[INFERENCE]`.

**문제/충돌**
그대로 이관하면 **공개 인터넷에 무인증 파일 다운로드 경로가 열린다.** 동시에 LGPL 소스 제공 의무를 어디서 이행할지는 별도로 답이 필요하다.

**선택지**

#### Option A — 현재 범위에서 제외 (권장)
- 내용: 두 엔드포인트를 이관하지 않는다. Client 배포와 LGPL 소스 제공은 웹 플랫폼 밖의 경로(사내 파일서버·공유 폴더)로 분리한다.
- 장점: 공개 노출 위험이 없다. 통합 범위가 줄어든다.
- 단점: Client 배포 경로를 별도로 마련해야 한다. LGPL 소스 제공 방법을 운영 절차로 문서화해야 한다.
- 영향 범위: 이관 목록에서 제외.
- 운영 영향: 배포물 제공 절차 별도 수립.

#### Option B — 인증을 붙여 이관
- 내용: 두 엔드포인트를 이관하되 로그인 사용자(또는 Client API Key)만 접근 가능하게 한다.
- 장점: 한 곳에서 배포물을 관리한다. Client 자동 업데이트를 나중에 붙일 여지가 있다.
- 단점: LGPL 소스 제공 의무는 "요청자에게 제공"이 요건인데 로그인 뒤에 두면 제공 방식 검토가 필요하다 `[NEEDS_CONFIRMATION]` — 법무 판단 영역이다. 구현·운영 부담이 추가된다.
- 영향 범위: 엔드포인트 2개 + 인증.
- 운영 영향: 배포물 업로드 절차 필요.

#### Option C — 무인증 그대로 이관
- 내용: 현재대로 인증 없이 제공한다.
- 장점: 변경이 없다.
- 단점: **Public Subnet에 무인증 다운로드 경로가 생긴다.** 디렉터리에 잘못된 파일이 들어가면 즉시 유출이다. 권장하지 않는다.

**권장안**
- **Option A**
- 권장 근거: 프롬프트 §1.1의 "외부 사용자는 Web/WAS만 접근한다"는 구조에서 무인증 파일 제공은 공격 표면을 늘릴 뿐 통합 목표에 기여하지 않는다. 배포물 제공은 웹 애플리케이션의 책임이 아니다.
- **법무 확인 필요**: LGPL 소스 제공 의무의 현재 이행 방식과, 경로를 옮겨도 되는지. `client/docs/LICENSE_COMPLIANCE.md`를 담당자가 확인해야 한다.

**사용자 결정**
- [ ] Option A — 현재 범위 제외(별도 경로로 분리)
- [ ] Option B — 인증을 붙여 이관
- [ ] Option C — 무인증 그대로 이관
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `02_FEATURE_MAPPING.md` §2.1, `06_API_COMPATIBILITY_PLAN.md`

---

### DEC-025. 용어·테이블 네이밍 규칙

**중요도**
- HIGH

**관련 영역**
- Domain / DB / UI

**확인된 사실** — 같은 이름, 다른 의미 (`03_CONFLICT_ANALYSIS.md` C-12)

| 용어 | MES | AIDataHub | vision |
|---|---|---|---|
| 검사 | `test_*`(품질검사), `check_*`(설비점검) | — | `inspections`(비전 검사 실행 기록) |
| 공정 | `process`(제조 공정, Factory FK, 라우팅 단위, `OutSourcingYN`) | — | `processes`(검사 공정 그룹, code/name/display_order만) |
| 제품 | `material`(자재·반제품·제품 통합 품목 마스터, BOM·재고·LOT의 축) | — | `products`(검사 대상 제품, process FK) |
| 모델 | `mlops_model`(tabular ML) | — | `models`(비전 AI) |
| 프로젝트 | — | `Project`(검사 과제) | — |
| 클라이언트 | `company`(거래처) | — | `clients`(검사 PC 장치) |
| 라벨 | `label_code`(다국어 UI 라벨) | `LabelClass`(어노테이션 클래스), `label_status` | — |
| 그룹 | `UserGroup`(권한 그룹), `mat_grp`·`equ_grp` | `UserGroup` + **`Group`(작업그룹)** | — |
| 버전 | — | `DatasetVersion`, `Dataset.version` | `models.version`, `overlays.version`, `catalog.version` |
| 작업 | `batch_q`, `job_res`(작업지시 실적) | `BackgroundJob`, `LabelingTask` | — |

- DEC-023 Option B를 택하면 MES `process`/`material`/`defect_type`을 가져올지가 결정 대상이 된다.
- vision `products`를 MES `material`에 매핑할 수 있는지는 업무 판단이다 — 검사 대상 "제품"이 MES 품목 마스터의 어떤 행인지 대응이 있어야 한다.

**문제/충돌**
같은 이름이 다른 뜻으로 한 데이터베이스·한 화면 체계에 들어오면 개발자와 사용자 모두 혼동한다. 특히 "검사"는 MES 품질검사 메뉴와 비전 검사 메뉴가 나란히 놓인다.

**선택지**

#### Option A — 도메인 접두어로 분리 (권장)
- 내용: 통합 플랫폼의 신규/이관 테이블에 도메인 접두어를 붙인다.
  ```text
  비전 검사    vision_process / vision_product / vision_inspection_item
               vision_overlay / vision_inspection / vision_client
               vision_item_model_mapping
  데이터 관리  (기존 vision_data_* 유지: dataset / imageasset / annotation / project ...)
  GPU          gpu_model / gpu_model_version / gpu_training_job / gpu_evaluation_result
  MES 계승     기존 이름 유지(process / material / user_group / sys_code ...)
  ```
  화면 명칭도 구분한다: "검사 공정"(vision) vs "공정"(MES), "검사 대상 제품"(vision) vs "품목"(MES), "검사 과제"(data) vs "검사 항목"(vision).
- 장점: 이름 충돌이 원천 차단된다. 테이블만 봐도 소유 도메인이 보인다(DB Ownership 문서화에 유리). AIDataHub `vision_data_*` 접두어 규칙과 일관된다(이미 그렇게 통일해 둔 선례가 있다).
- 단점: vision Server 테이블명이 전부 바뀌므로 이관 스크립트가 필요하다(DEC-012에 따라). 기존 vision 개발자에게 낯설다. 이름이 길어진다.
- 영향 범위: vision 11테이블 + GPU 신규 테이블 + 화면 명칭.
- Migration 영향: 테이블명 변경(신규 DB이므로 `RENAME`이 아니라 처음부터 새 이름 — DEC-011 Option A 전제).

#### Option B — 현재 이름 유지 + 용어 사전만 문서화
- 내용: 테이블명은 그대로 두고 Glossary 문서로 구분한다.
- 장점: 이관 시 이름 변경이 없다.
- 단점: `process`(MES)와 `processes`(vision)가 한 DB에 공존한다 — 단수/복수 차이만으로 구분되어 사고가 나기 쉽다. `models`처럼 일반적인 이름은 나중에 다른 용도와 충돌할 여지가 크다.
- 영향 범위: 문서만.

#### Option C — 통합 (같은 개념으로 합치기)
- 내용: vision `processes`를 MES `process`에, `products`를 `material`에 합친다.
- 장점: 기준정보가 한 곳이다. 검사 공정이 제조 공정과 연결되어 MES 연계 시 유리하다.
- 단점: 의미가 실제로 같은지 **업무 확인이 필요하다.** MES `process`는 Factory FK·`OutSourcingYN`을 갖는 제조 공정이고 vision `processes`는 검사 대상 분류에 가깝다. 억지로 합치면 검사 기준정보에 불필요한 필드가 붙고, MES 기준정보를 바꾸면 검사가 영향을 받는다. DEC-023 Option B에서 MES `process`/`material`을 가져오지 않기로 하면 성립하지 않는다.
- 영향 범위: 기준정보 전반 + Catalog API(`process_id`/`product_id`가 Client 계약에 노출되어 있다 — 값이 바뀌면 Client 캐시가 깨진다).

**권장안**
- **Option A**
- 권장 근거: AIDataHub가 2026-09-30에 `ai_domain_*` → `vision_data_*`로 테이블명을 통일한 선례가 있다 — 접두어 규칙의 가치를 이미 인정한 것이다. Option C는 업무 확인 없이 선택할 수 없고, 무엇보다 `process_id`/`product_id`가 **Client Catalog 계약에 노출된 식별자**라 값이 바뀌면 Client 캐시·Overlay 캐시 키가 전부 무효가 된다(DEC-007 위험).
- **추가 확인 질문**: vision `products`(검사 대상 제품)가 MES `material`(품목)의 부분집합인가? 답이 "예"이면 `vision_product`에 `material_id` 참조 필드를 두는 절충이 가능하다(합치지 않고 잇기).

**사용자 결정**
- [ ] Option A — 도메인 접두어로 분리
- [ ] Option B — 현재 이름 유지 + 용어 사전만
- [ ] Option C — 통합(같은 개념으로 합치기)
- [ ] 기타

**추가 확인 질문**
- vision `products`는 MES `material`(품목 마스터)의 부분집합인가?
  - [ ] 예 — `vision_product.material_id` 참조 필드를 둔다
  - [ ] 아니오 — 독립 마스터로 둔다
  - [ ] 확인 필요

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §8, `05_DATABASE_MIGRATION_PLAN.md` §Table Mapping

---

### DEC-026. 검사 결과 → 학습 데이터셋 연결 방식

> **[폐기됨 — §1.6 O-9]** 이관 기능 자체가 범위에서 빠졌다. 검사 이미지는 접수 시점에
> `upload_images()` 로 자동 연계된다. 아래는 분석 기록이다.

**중요도**
- HIGH

**관련 영역**
- Domain / API / Operation

**확인된 사실**
- vision Server `application/services/image_migration.py` docstring: "쌓인 검사 이미지를 **외부 데이터 수집/관리 시스템**으로 옮긴다. … 전송 내용은 원본 이미지와 **판정 결과·탐지 좌표**다. 수집 시스템이 AI 학습 데이터로 쓰므로 라벨이 이미지와 함께 가야 한다. Heatmap은 원본·모델·임계값으로 다시 만들 수 있어 보내지 않는다."
- 현재 구현은 **로컬 디렉터리 내보내기**(`infrastructure/migration/local_export.py`). `settings.py` 주석: "대상 시스템의 API 규격이 확정되면 **HTTP 어댑터로 바꾼다**."
- 실행 방식: **검사항목 단위로 관리자가 직접 실행**, batch(기본 50, 최대 500)로 끊는다. 이유가 문서화되어 있다 — "수천 건을 한 요청에서 보내면 웹 요청이 타임아웃되고, 중간에 끊기면 어디까지 갔는지 알 수 없다."
- `image_migrations` 테이블에 건별 이력(`status` SENT/FAILED/NO_IMAGE, `external_id`, `attempts`). `NO_IMAGE`는 재전송 불가로 진행률에서 제외한다.
- Admin 화면 `/admin/migration`(목록 + 항목별 실행)이 있다.
- **즉 "검사 이미지 → 학습 데이터" 파이프라인의 대상 시스템이 AIDataHub라는 의도가 이미 코드에 있다.** 통합 후에는 같은 Django 프로세스 안의 호출이 된다.
- 받는 쪽 구조: `Dataset`(project FK) → `ImageAsset`(dataset FK, `sha256` 테넌트·데이터셋 내 unique) → `Annotation`(image FK, `label_class` FK, `geometry_type`, `geometry` JSON).
- **모델이 내는 `defects[].class_name`과 `LabelClass.name`이 연결되어 있지 않다**(G-7). 자동 변환하려면 매핑이 필요하다.
- `ImageAsset.label_status`에 `APPROVED`(검수 완료)가 있고, 데이터 품질 점검·스냅샷은 **검수 승인 이미지만 대상**이다(2026-09-29).

**문제/충돌**
검사 결과를 그대로 학습 데이터로 넣으면 **모델이 만든 라벨을 그 모델의 학습 데이터로 다시 쓰는 순환**이 된다. 어떤 상태로 넣을지(미라벨 / 자동 라벨 초안 / 승인 완료)가 데이터 품질을 좌우한다.

**선택지**

#### Option A — 자동 연결(검사 즉시 데이터셋에 적재)
- 내용: 검사가 끝나면 원본과 결과를 곧바로 대상 데이터셋에 `ImageAsset` + `Annotation`으로 만든다.
- 장점: 수동 작업이 없다. 데이터가 실시간으로 쌓인다.
- 단점: 검사 트랜잭션이 길어진다(Client 응답 지연). 불량이 아닌 정상 이미지까지 무제한 쌓여 저장 용량이 폭증한다. 모델 출력을 검증 없이 라벨로 쓰면 품질이 나빠진다.

#### Option B — 수동 실행 + 내부 서비스 호출 (권장)
- 내용: 현재 `image_migration`의 **검사항목 단위·batch·이력 구조를 그대로 유지**하되, `ImageMigrationPort` 구현을 로컬 디렉터리 대신 **내부 서비스 호출**로 바꾼다(`DatasetIngestService`). 관리자가 "이 검사항목의 검사 이미지를 이 데이터셋으로 보내기"를 실행한다. 적재되는 이미지는 `label_status = UNLABELED` 또는 `SUBMITTED`(자동 라벨 초안)로 두고, **검수를 거쳐야 `APPROVED`가 된다.**
- 장점: 검증된 batch·이력·재실행 구조를 그대로 쓴다(`image_migrations` 테이블 유지). 검사 트랜잭션에 영향이 없다. 사람이 언제 무엇을 보낼지 통제한다. 기존 검수 흐름이 품질 게이트가 된다.
- 단점: 관리자가 주기적으로 실행해야 한다. `class_name` → `LabelClass` 매핑을 설정해야 한다(없으면 라벨 없이 이미지만 적재).
- 영향 범위: `ImageMigrationPort` 구현 교체 + 대상 데이터셋 지정 UI + 클래스 매핑 설정.
- API 영향: 없음(내부 호출).

#### Option C — 연결하지 않음(현재 범위 제외)
- 내용: 검사 이미지와 학습 데이터셋을 잇지 않는다. 학습 데이터는 별도로 업로드한다.
- 장점: 구현이 없다. 범위가 가장 작다.
- 단점: **통합의 핵심 가치 하나를 포기한다** — 검사에서 나온 실제 불량 이미지가 학습으로 돌아가는 순환이 이 플랫폼을 하나로 묶는 이유다. vision 코드에 이미 그 의도가 있다.

**권장안**
- **Option B**
- 권장 근거: 프롬프트 §23-8("기존 구현이 존재하면 새 구현을 먼저 제안하지 않는다"). vision 개발진이 batch·이력·`NO_IMAGE` 처리까지 설계해 둔 구조가 있고, 남은 일은 Port 구현을 바꾸는 것뿐이다. Option A는 품질과 성능 양쪽에서 위험하다.
- **하위 권장 — 적재 시 라벨 상태**: `defects`가 있는 이미지는 `Annotation`을 만들되 `label_status = SUBMITTED`(검수 대기)로 둔다. 정상 판정 이미지는 `UNLABELED`로 둔다. 이렇게 하면 기존 검수 화면이 그대로 게이트가 된다.
- **하위 권장 — 클래스 매핑**: `vision_item_model_mapping`에 `class_name → LabelClass` 매핑 테이블을 두거나, `LabelClass.name`을 모델 클래스명과 같게 등록하도록 운영 규칙을 정한다. 후자가 단순하다.
- **하위 권장 — 대상 데이터셋**: DEC-005 Option A의 `Project.inspection_item` 연결을 따라 자동으로 찾는다.

**사용자 결정**
- [ ] Option A — 자동 연결(검사 즉시 적재)
- [ ] Option B — 수동 실행 + 내부 서비스 호출
- [ ] Option C — 연결하지 않음
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §9, `07_IMPLEMENTATION_PLAN.md` Phase 3·6

---

### DEC-027. AI 학습(Training)을 현재 범위에 포함하는가

**중요도**
- HIGH

**관련 영역**
- GPU / 범위 / Operation

**확인된 사실**
- **세 프로젝트 어디에도 Training Job API가 없다.** vision `cli.py`에 `fit-anomaly`(PatchCore fit)와 `export-detection`만 있다.
- Training Job / Evaluation Result / Model Version / Deployment 상태 테이블이 **없다**(NEW-03 ~ NEW-06).
- 추론은 웹 프로세스 안에서 돈다 → **학습을 같은 서버에서 돌리면 추론이 밀린다**(D15, G-1). 프롬프트 §21도 "Training / Inference 자원 충돌"을 운영 검토 항목으로 든다.
- AIDataHub Export 8포맷이 이미 학습 데이터 산출물을 만든다(COCO / YOLO / ImageFolder / CSV / Classification JSON / MVTec / Image+Mask / Anomaly JSON). Export zip은 `ExportJob.file`로 저장된다.
- 프롬프트 §2.3 B는 GPU Server의 AI 학습 범위를 상세히 정의한다: Dataset Loading, Training Job 생성/실행, 모델 학습, Checkpoint, 평가·검증, 학습 상태 관리, 학습 결과 저장, 오류·중단 처리.
- 프롬프트 §13.1의 최소 API 후보에 `POST /training/jobs`, `GET /training/jobs/{job_id}`, `POST /training/jobs/{job_id}/cancel`이 있다.
- 프롬프트 §17의 제외 목록에 학습은 없다 → 범위 안으로 읽힌다.
- **GPU 하드웨어 스펙·CUDA·torch 버전이 확인되지 않았다**(N6).

**문제/충돌**
학습은 프롬프트가 명시적으로 요구하지만 구현이 전무하고, 분량이 가장 크며(Job 관리·Checkpoint·평가·자원 제어), 추론 가용성과 자원을 다툰다. 통합 1단계에 함께 넣으면 다른 모든 Phase가 밀릴 위험이 크다.

**선택지**

#### Option A — 전체 Training 포함
- 내용: 프롬프트 §2.3 B 전부를 이번 범위에 넣는다. Training Job API, Checkpoint, Evaluation Result, 학습·추론 자원 제어(큐 또는 별도 프로세스/디바이스 분리)를 구현한다.
- 장점: 프롬프트 요구를 완전히 충족한다. 데이터 → 학습 → 배포 → 추론 → 데이터의 순환이 처음부터 닫힌다.
- 단점: 신규 개발량이 가장 크다(NEW-03~06, 09). 학습 파이프라인은 모델 유형(Detection/Anomaly/Classification)마다 다르고, CLASSIFICATION은 추론조차 없다(NEW-07). 검증에 실제 GPU와 데이터가 필요해 일정 예측이 어렵다. **통합 자체(Phase 1~4)가 끝나기 전에 여기서 막히면 전체가 지연된다.**

#### Option B — Anomaly fit만 포함, 일반 Training은 다음 단계 (권장)
- 내용: 이번 범위에는 **`fit-anomaly`를 API화**한 것만 넣는다(`POST /training/anomaly-fit`, 상태 조회, 취소). 입력은 AIDataHub Export의 MVTec/ImageFolder zip이다. Detection 학습과 Classification 학습, Checkpoint·Evaluation Result 관리는 다음 단계로 분리한다. Model Registry와 Model Version은 이번에 만든다(학습 없이도 모델 등록·배포에 필요하므로).
- 장점: 실제로 존재하는 구현(`fit-anomaly`)을 API화하는 것이라 위험이 낮다. 학습 → 등록 → 매핑 → 추론의 **한 바퀴를 실제로 돌려 볼 수 있다** — 아키텍처 검증에 충분하다. 통합 본체의 일정을 지킨다.
- 단점: Detection 모델은 여전히 외부에서 학습해 아티팩트를 업로드해야 한다. 프롬프트 §2.3 B를 부분적으로만 충족한다.
- 영향 범위: GPU `/training/anomaly-fit` + Job 상태 테이블(최소) + WEB 학습 요청 화면.

#### Option C — Training 전체 제외
- 내용: 이번 범위에서 학습을 다루지 않는다. 모델은 외부에서 학습해 아티팩트를 등록한다(현재 vision Admin 방식 그대로).
- 장점: 범위가 가장 작다. 통합 본체에 집중한다.
- 단점: 프롬프트 §2.3 B 전체를 미이행한다. GPU Server의 세 기능(모델 관리/학습/추론) 중 하나가 빈다.

**권장안**
- **Option B**
- 권장 근거: 프롬프트 §18이 "Big Bang Merge를 피한다"고 하고 Phase 6에 GPU 연계를 두었다. 학습은 통합의 **결과로 가능해지는 기능**이지 통합의 전제가 아니다. `fit-anomaly`라는 실제 구현이 있는 부분만 API화하면 "학습이 되는가"를 실증하면서도 일정 위험을 통제할 수 있다.
- **자원 충돌 처리(하위 결정)** 권장: 학습은 **추론과 다른 프로세스**에서 실행한다(systemd로 별도 유닛, 또는 학습 전용 큐 워커). 동시에 도는 학습 Job은 1개로 제한한다. GPU가 1장이면 학습 중 추론 지연을 감수할지, 학습을 야간으로 제한할지 운영 정책이 필요하다 — **N6(GPU 스펙) 확인 후 확정**한다.
- **Option A를 선택하는 경우**: `07_IMPLEMENTATION_PLAN.md`에 학습을 독립 Phase로 분리하고 통합 본체(Phase 1~4)의 완료 조건에 넣지 않을 것을 권한다. 그러지 않으면 통합 전체가 학습 구현에 묶인다.

**사용자 결정**
- [ ] Option A — 전체 Training 포함
- [ ] Option B — Anomaly fit만 포함, 일반 Training은 다음 단계
- [ ] Option C — Training 전체 제외
- [ ] 기타

**사용자 메모**
>

**결정 결과**
- 상태: 미결정
- 최종 결정:
- 결정일:
- 반영 대상: `04_TARGET_ARCHITECTURE.md` §4, `06_API_COMPATIBILITY_PLAN.md` §GPU, `07_IMPLEMENTATION_PLAN.md` Phase 5

---

## 3. 결정 완료 후 적용될 변경 요약

사용자 결정이 입력되면 이 표를 채운다. 현재는 **권장안 기준의 예상값**이며 확정이 아니다.

| Decision ID | 최종 결정 | Architecture 영향 | DB 영향 | API 영향 | Client 영향 |
|---|---|---|---|---|---|
| DEC-001 | (미결정) | 프로젝트 골격 확정 | — | — | 없음 |
| DEC-002 | (미결정) | 사용자 모델 확정 | `user_profile`·`user_group`·`user_group_menu` 스키마 확정 | — | 없음 |
| DEC-003 | (미결정) | 인가 계층 수 결정 | `projectassignment`·`projectgroupaccess` 존폐 | 403 응답 추가 | 없음 |
| DEC-004 | (미결정) | 테넌트 축 존폐 | 19테이블 `tenant` FK·RLS 존폐 | — | 없음 |
| DEC-005 | (미결정) | 데이터 도메인 계층 확정 | `Project` 연결 필드 | — | 없음 |
| DEC-006 | (미결정) | GPU Server 정체성 확정 | GPU 소유 테이블 확정 | GPU API 신규 | 없음 |
| DEC-007 | (미결정) | `/api/v1` 계층 위치 | — | `/api/v1` 6개 구현 | **Base URL 변경** |
| DEC-008 | (미결정) | 추론 호출 방향 | `inspections` Owner 확정 | GPU `/inference/*` | 없음 |
| DEC-009 | (미결정) | AI 도메인 경계 | `mlops_*` 제외 | — | 없음 |
| DEC-010 | (미결정) | 매핑 Ownership | `model_id` FK 존폐 | GPU `GET /models` 호출 | 없음 |
| DEC-011 | (미결정) | DB 구성 | 신규 DB + `0001_initial` | — | 없음 |
| DEC-012 | (미결정) | — | 데이터 이관 범위 | — | 없음 |
| DEC-013 | (미결정) | 표현 계층 규약 | — | — | 없음 |
| DEC-014 | (미결정) | 인가 지점 | — | 권한 없는 호출 403 | 없음 |
| DEC-015 | (미결정) | 서비스 간 신뢰 경계 | — | `X-Service-Key` | 없음 |
| DEC-016 | (미결정) | 시각 기준 | 컬럼 타입(`timestamp`/`timestamptz`) | UTC 변환 지점 | 없음(계약 유지) |
| DEC-017 | (미결정) | — | PK 타입 확정 | — | 없음 |
| DEC-018 | (미결정) | 관리자 계정 단일화 | `admin_users` 제외 | — | 없음 |
| DEC-019 | (미결정) | 저장소 구조 | — | 이미지 제공 경로 | **이미지 URL prefix 유지 필수** |
| DEC-020 | (미결정) | 배포 스택 | — | — | 없음 |
| DEC-021 | (미결정) | — | `label_code` 적용 범위 | — | 없음 |
| DEC-022 | (미결정) | 비동기 처리 기반 | `BackgroundJob` vs `batch_q` | 202 응답 | 없음 |
| DEC-023 | (미결정) | 플랫폼 범위 | 이관 테이블 수 | — | 없음 |
| DEC-024 | (미결정) | 공개 표면 | — | 엔드포인트 2개 제외 | 없음 |
| DEC-025 | (미결정) | 도메인 경계 명시 | **테이블명 전반** | `process_id`/`product_id` 값 유지 필요 | 값이 바뀌면 캐시 무효 |
| DEC-026 | (미결정) | 데이터 순환 경로 | `image_migrations` 유지 | 없음(내부 호출) | 없음 |
| DEC-027 | (미결정) | GPU 기능 범위 | Training Job 테이블 | GPU `/training/*` | 없음 |

---

## 4. 미해결 Blocker

현재 **8건 전부 미결정**이다.

| ID | 제목 | 왜 Blocker인가 |
|---|---|---|
| DEC-001 | 통합 방식 | 골격이 정해지지 않으면 어떤 파일을 어디에 두는지 한 줄도 정할 수 없다 |
| DEC-002 | User 스키마 | 같은 이름의 테이블 3개가 충돌한 채로는 `0001_initial`을 쓸 수 없다 |
| DEC-003 | 권한 모델 범위 | 데이터 관리 기능의 인가 설계 전체가 여기에 달려 있다 |
| DEC-005 | `Project` 존치 | 데이터 도메인 모델 9개의 FK 구조가 결정된다 |
| DEC-006 | GPU Server 정체성 | vision Server를 고칠지 버릴지가 정해져야 작업 목록이 나온다 |
| DEC-007 | Client 호환 전략 | Client 재배포 여부가 Phase 6 전체와 일정에 직결된다 |
| DEC-011 | DB 구성 | Migration Plan을 시작할 수 없다 |
| DEC-023 | MES 이관 범위 | 이관 대상이 30개 화면인지 374개인지에 따라 계획 규모가 10배 차이난다 |

**추가로, 결정 전에 확인이 필요한 사실**(`01_CURRENT_STATE_ANALYSIS.md` §10)

| # | 확인 항목 | 영향받는 결정 |
|---|---|---|
| N1 | 세 DB의 운영 데이터 유무·규모 | **DEC-012**, DEC-017 |
| N2 | MES 운영 Django 버전 | (C-30 수정 방식) |
| N4 | NCP 대상 OS | **DEC-020** |
| N5 | 현장 Client 설치 대수·재배포 가능 여부 | **DEC-007** |
| N6 | GPU 하드웨어·CUDA·torch 버전 | **DEC-027**, DEC-006 |
| N8 | MES `das`·`ai` 스키마 내용 | DEC-011, DEC-023 |
| N9 | AIDataHub `Tenant` 행 수 | **DEC-004** |
| N11 | `mlops_*` DDL 원본 | DEC-009 |

---

## 5. 다음 단계

모든 BLOCKER와 구현에 필요한 HIGH 항목 결정 후:

1. 결정 내용 검증 (상충 여부 점검 — 아래 의존 관계 참고)
2. `04_TARGET_ARCHITECTURE.md` 확정
3. `05_DATABASE_MIGRATION_PLAN.md` / `06_API_COMPATIBILITY_PLAN.md` 작성
4. `07_IMPLEMENTATION_PLAN.md` 작성
5. 사용자 승인 후 구현 시작

### 결정 간 의존 관계

```text
DEC-023 (MES 범위)  ─┬─> DEC-001 (골격)  ──> DEC-011 (DB) ──> DEC-012 (데이터 이관)
                     │                                  │
DEC-002 (User) ──────┼─> DEC-003 (권한) <─── DEC-014 (인가 훅)   [DEC-014=C면 DEC-003=A 강제]
                     │        │
                     │        └─> DEC-004 (테넌시)
                     │
DEC-005 (Project) ───┴─> DEC-026 (데이터 순환)
                              │
DEC-006 (GPU) ──┬─> DEC-008 (이미지·결과 소유) ──> DEC-015 (인증·장애)
                ├─> DEC-009 (Registry 경계)
                ├─> DEC-010 (모델 참조) ──> DEC-025 (네이밍)
                └─> DEC-027 (학습 범위)

DEC-007 (Client) ──> DEC-019 (저장소) ──> DEC-020 (배포 OS)
DEC-013 (표현 계층) ──> DEC-021 (다국어)
DEC-016 / DEC-017 / DEC-018 / DEC-022 / DEC-024 : 비교적 독립
```

### 알려진 상충 규칙

- **DEC-014 = Option C(인가 훅 없음)** 이면 **DEC-003 = Option A(MES 권한만)** 로 강제된다. 인가를 걸 지점이 없기 때문이다.
- **DEC-004 = Option C(다조직 유지)** 이면 **DEC-003 = Option C**에 가까워진다(테넌트 선택이 인가 흐름에 들어온다).
- **DEC-011 = Option B(MES DB에 추가)** 이면 **DEC-023 = Option A**로 기울어진다(MES 테이블이 이미 다 있으므로).
- **DEC-006 = Option C(프록시)** 이면 **DEC-008·DEC-010·DEC-011**의 전제(단일 DB Ownership)가 무너진다 → 해당 결정들을 다시 설계해야 한다.
- **DEC-025 = Option C(기준정보 통합)** 이면 `process_id`/`product_id` 값이 바뀔 수 있어 **DEC-007의 "Client 무변경"이 깨진다**(Catalog 캐시·Overlay 캐시 키 무효).

### 이 시점의 작업 상태

```text
Stage 1 소스 분석        완료
Stage 2 USER_DECISIONS   완료
                          ↓
                    사용자 결정 대기  ← 현재 여기
                          ↓
Stage 3 계획 수립        미시작 (결정 후)
Stage 4 구현             미시작 (계획 승인 후)
```

`07_IMPLEMENTATION_PLAN.md`는 **작성하지 않았다.** 프롬프트 §A.2 / §26.1에 따라 결정 완료 전에는 구현 Task와 실행 순서를 확정하지 않는다.
