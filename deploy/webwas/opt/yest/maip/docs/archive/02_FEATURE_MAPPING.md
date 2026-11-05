# 02. Feature Mapping

> **rev.3 (2026-09-30)** — `USER_DECISIONS.md` **§1.6** 반영. 아래 내용 중 다음은 무효다.
> - vision 공정·제품 관련 항목 전부 (테이블·화면 모두 만들지 않음, O-8)
> - 검사 이미지 이관(`/admin/migration`) 관련 항목 전부 (접수 시점 자동 연계로 대체, O-9)
> - 이미지 보존 정책(`/admin/retention`) 관련 항목 전부 (O-10)
> - AIDataHub `Project`를 독립 엔티티로 다룬 항목 (검사항목에 통합, O-8·O-13)
>
> **정본은 `USER_DECISIONS.md` §1.6 · `SCREEN_MAPPING.md` rev.2 · `07_IMPLEMENTATION_PLAN.md` rev.2다.**

> ## ⚠ 개정 안내 (2026-09-30 rev.2)
>
> 이 문서는 **Stage 1 분석 시점의 후보안**이다. 이후 두 가지가 확정되면서 **일부 내용이 갱신되었다.**
>
> 1. 모든 `DEC-*`가 권장안으로 확정됨 → `USER_DECISIONS.md` §1
> 2. Backbone 프롬프트가 일부 권장안을 덮어씀 → `USER_DECISIONS.md` §1.5
>
> **충돌 시 우선순위**: `USER_DECISIONS.md` §1.5 > `SCREEN_MAPPING.md` > `04~07` 확정 문서 > 이 문서.
>
> ### 이 문서에서 무효가 된 내용
>
> | 원래 기재 | 확정 내용 | 근거 |
> |---|---|---|
> | §2.3 GPU Server 관련 전 항목(추론 이관·Training·Model Load 등) | **이번 범위 전면 제외.** `InferenceGateway` Stub만 정의 | §1.5 O-1 |
> | vision Admin 대시보드 `[REPLACE]` | **이관 확정**(`wm_vis_dashboard`) | §1.5 O-4 |
> | vision `history` API·화면 `[ADAPT]`/`[REMOVE]` | **이관 확정** | §1.5 O-4 |
> | AIDataHub 테스트 스위트 `[ADAPT]` | **이관하지 않는다.** 신규 작성 | §1.5 O-3 |
> | 모델 아티팩트 업로드·검증(GPU) | **제외**(`torch.load` 의존) | §1.5 O-1 |
> | `models` 테이블 GPU 소유 | 이번 단계는 **WEB 소유**(`vision_model`) | §1.5 O-2 |
> | NEW-03~09(Training·Model Version·Load/Unload·CLASSIFICATION 추론·자원 제어) | **범위 밖**. 향후 GPU Server 과제 | §1.5 O-1, DEC-027(C) |
>
> ### 처리 방식 분류 전환 (Backbone §17)
>
> ```text
> [REUSE]   → REUSE_LOGIC          전문 로직 그대로 재사용
> [ADAPT]   → ADAPT                로직 재사용 + MES 패턴 조정
> [REWRITE] → REWRITE              개념만 유지하고 MES 구조로 재작성
> [REPLACE] → REPLACE_WITH_MES     MES 공통 기능으로 대체
> [FUTURE]  → (유지)               현재 범위 제외
> [REMOVE]  → 신중 사용. 사용자 화면은 원칙적으로 제거하지 않는다
> ```
>
> **화면 단위의 확정 매핑은 `SCREEN_MAPPING.md`가 정본이다.** 이 문서는 기능·서비스·모델 수준의 분석 근거로 남긴다.

---

- 기준일: 2026-09-30 (rev.2 개정)
- 근거: `01_CURRENT_STATE_ANALYSIS.md`
- 처리 방식(원문): `[REUSE]` 그대로 재사용 / `[ADAPT]` 로직 재사용 + MES 패턴 적용 / `[REWRITE]` 개념만 유지하고 재작성 / `[REPLACE]` MES 공통 기능으로 대체 / `[REMOVE]` 통합 후 불필요 / `[FUTURE]` 현재 범위 제외
- Target Service: `WEB` = ManufacturingAIPlatform(Django) / `GPU` = GPU Server(**이번 범위 밖**) / `CLIENT` = VisionInspectionClient.exe

---

## 1. AIDataHub → 데이터 관리 (Data Management)

| 기능 | Source 위치 | Target Service | Target Domain/App 후보 | 처리 방식 | DB 영향 | API 영향 | 관련 결정 |
|---|---|---|---|---|---|---|---|
| 조직(Tenant) 관리 | `app/views/system/organizations/*`, `domain/services/tenancy/*`, `Tenant`/`TenantMembership` | WEB | `system` | `[REMOVE]` 또는 `[ADAPT]` | `vision_data_tenant`, `vision_data_tenantmembership` 및 19테이블의 `tenant` FK·RLS 존폐 | 없음(내부 화면) | **DEC-004** |
| 작업그룹(Group) 관리 | `app/views/system/organizations/work_groups.py`, `Group`/`GroupMember`/`ProjectGroupAccess` | WEB | `system` | `[ADAPT]` 또는 `[REPLACE]`(MES `UserGroup`) | `vision_data_group*`, `vision_data_projectgroupaccess` | 없음 | **DEC-003** |
| 검사 과제(Project) 관리 | `app/views/project/home/api.py`, `domain/services/project/*`, `Project` | WEB | `data` | `[ADAPT]` | `vision_data_project`, `..._projectassignment`, `..._projectdeletionrequest` | 없음 | **DEC-005** |
| 과제 삭제 승인 워크플로 | `domain/services/project/deletion.py`, `ProjectDeletionRequest` | WEB | `data` | `[ADAPT]` | `vision_data_projectdeletionrequest` | 없음 | DEC-005 |
| Label Class 관리 | `Project` 화면 내, `LabelClass` | WEB | `data` | `[ADAPT]` | `vision_data_labelclass` | 없음 | — |
| 데이터 수집(이미지 업로드) | `app/views/project/data_manage/api.py:ImageUploadApiView`, `domain/services/dataset/image.py` | WEB | `data` | `[ADAPT]` | `vision_data_imageasset` | 없음 | DEC-013 |
| 데이터 목록/검색/상세 | `ImageListApiView`, `ImageDetailApiView` | WEB | `data` | `[ADAPT]` (그리드는 `[REWRITE]`) | 없음 | 없음 | DEC-013 |
| 썸네일 생성/backfill | `domain/services/dataset/image.py`, `management/commands` | WEB | `data` | `[REUSE]` | `vision_data_imageasset.thumbnail` | 없음 | — |
| 데이터 정제(회전·원근보정·크롭·리사이즈, 원본 보존) | `ImagePreprocessApiView`, `domain/services/dataset/preprocess.py` | WEB | `data` | `[ADAPT]` | `imageasset.original_file`, `.preprocess`(JSON) | 없음 | — |
| 이미지 권한 확인 서비스 | `PrivateImageView`, `PrivateImageThumbnailView`, `PrivateProjectCoverView`, `PrivateExportView` | WEB | `data` | `[ADAPT]` | 없음 | 없음 | **DEC-019** |
| 라벨링 — 분류 | `app/views/project/labeling/api.py`, `domain/services/dataset/labeling_task.py`, `annotation.py` | WEB | `data` | `[ADAPT]` + 화면 `[REWRITE]`/유지 | `vision_data_labelingtask`, `..._annotation` | 없음 | **DEC-013** |
| 라벨링 — 객체탐지(BBOX/POLYGON) | 위와 같음 | WEB | `data` | 위와 같음 | 위와 같음 | 없음 | DEC-013 |
| 라벨링 — 이상탐지(정상/이상 + 결함 POLYGON) | 위와 같음 | WEB | `data` | 위와 같음 | 위와 같음 | 없음 | DEC-013 |
| 라벨링 claim / heartbeat / draft / submit | `LabelingTask*ApiView`, `lease_token`·`lease_expires_at` | WEB | `data` | `[ADAPT]` | `vision_data_labelingtask`(부분 unique 제약 포함) | 없음 | — |
| 검수(승인 / 재작업) | `app/views/project/review/api.py`, `domain/services/dataset/review.py` | WEB | `data` | `[ADAPT]` | `imageasset.label_status`, `.rework_reason` | 없음 | — |
| 데이터 표준(DataStandard) + 표준 이미지 | `DataStandard`, `StandardImage` | WEB | `data` | `[ADAPT]` | `vision_data_datastandard`, `..._standardimage` | 없음 | — |
| 데이터 품질 점검 4종 | `QualityRunApiView`, `domain/services/workspace/quality.py` | WEB | `data` | `[ADAPT]` | `vision_data_qualityrun`, `..._qualityfinding` | 없음 | **DEC-022** |
| 스냅샷(불변 DatasetVersion + manifest) | `DatasetSnapshotApiView`, `domain/services/workspace/version.py` | WEB | `data` | `[ADAPT]` | `vision_data_datasetversion` | 없음 | — |
| Dataset Export — COCO | `domain/services/dataset/export/coco.py` | WEB | `data` | `[REUSE]` | `vision_data_exportjob` | 없음 | — |
| Dataset Export — YOLO | `.../export/yolo.py` | WEB | `data` | `[REUSE]` | 위 | 없음 | — |
| Dataset Export — ImageFolder | `.../export/imagefolder.py` | WEB | `data` | `[REUSE]` | 위 | 없음 | — |
| Dataset Export — Classification CSV / JSON | `.../export/classification.py` | WEB | `data` | `[REUSE]` | 위 | 없음 | — |
| Dataset Export — MVTec / Image+Mask / Anomaly JSON | `.../export/mvtec.py` | WEB | `data` | `[REUSE]` | 위 | 없음 | — |
| Export 포맷 레지스트리(과제유형↔포맷) | `.../export/registry.py` | WEB | `data` | `[REUSE]` | 없음 | 없음 | DEC-005 |
| 백그라운드 작업 큐(QUALITY/EXPORT) | `BackgroundJob`, `domain/services/dataset/job.py`, `management/commands/{run_worker,process_jobs}` | WEB | `core` | `[ADAPT]` 또는 `[REPLACE]`(MES `batch_q`) | `vision_data_backgroundjob` vs MES `batch_q`/`batch_log` | 없음 | **DEC-022** |
| 홈 통계 / 라벨링 대기열 / 최근 활동 | `app/views/home/api.py`, `domain/services/home/*` | WEB | `data` | `[ADAPT]` | 없음 | 없음 | — |
| 활동 로그(ActivityLog) | `domain/services/activity/{audit,query}.py` | WEB | `system` | `[ADAPT]` 또는 `[REPLACE]`(MES `sys_log`) | `vision_data_activitylog` | 없음 | DEC-018 |
| 데이터 접근 제어(capability) | `domain/services/access/authorization.py` `ACTION_CAPABILITIES`, `project/access.py` | WEB | `core` | `[ADAPT]` — **MES `ApiModuleView`에 인가 훅이 없으면 이식 불가** | 없음 | 없음 | **DEC-003**, **DEC-014** |
| PostgreSQL RLS 테넌트 격리 | `domain/tenancy.py`, `0001_initial` `TENANT_TABLES`, `scripts/verify_rls.py` | WEB | `core` | `[REMOVE]` 또는 `[REUSE]` | 19테이블 정책 | 없음 | **DEC-004** |
| 사용자 / 사용자그룹 / 메뉴권한 관리 | `app/views/system/{users,groups}/api.py`, `domain/services/account/*` | WEB | `system` | `[REPLACE]` — MES 것을 쓴다 | `user_profile`/`user_group`/`user_group_menu` 스키마 충돌 해소 필요 | 없음 | **DEC-002** |
| 로그인 / 로그아웃 / 비밀번호 변경 | `app/views/account/*` | WEB | `system` | `[REPLACE]` — MES 로그인 | `vision_data_authenticationlog` → MES `login_log` | 없음 | DEC-018 |
| 조직 선택(TenantMiddleware) | `domain/tenancy.py` | WEB | — | `[REMOVE]`(단일 조직 결정 시) | 없음 | 없음 | DEC-004 |
| 내비게이션 스냅샷 API | `app/views/common/navigation.py`, `domain/gui.py build_snapshot` | WEB | — | `[REPLACE]` — MES 메뉴 체계 | `menu_folder`/`menu_item`/`user_group_menu` | 없음 | DEC-013 |
| SPA 셸(`spa.js`, `#content-canvas`) | `app/static/js/spa.js`, `app/templates/app/layout.html` | WEB | — | `[REMOVE]` 또는 `[REUSE]` | 없음 | 없음 | **DEC-013** |
| 헬스체크 | `app/views/common/health.py` `/healthz/` | WEB | `core` | `[ADAPT]` | 없음 | 신규 `/healthz` | — |
| Request ID 미들웨어 | `configurations/middleware/request_id.py` | WEB | `core` | `[REUSE]` | 없음 | 상관관계 ID | — |
| 테스트 스위트(603건) | `tests/` | WEB | `tests` | `[ADAPT]` — 이식한 기능에 맞게 수정 | 없음 | 없음 | — |
| MVTecAD 데모 적재 / SaaS 데모 seed | `domain/management/commands/seed_*` | WEB | `data` | `[FUTURE]` 또는 `[ADAPT]` | 없음 | 없음 | — |
| htmx 관련 잔재 테스트 | `tests/test_htmx_*.py` | — | — | `[REMOVE]` | 없음 | 없음 | — |

---

## 2. vision-inspection Server → 비전 검사 관리 (WEB) / GPU Server (GPU)

### 2.1 Client 계약 API — `/api/v1/*`

| 기능 | Source 위치 | Target Service | Target Domain/App 후보 | 처리 방식 | Client 호환 분류 | 관련 결정 |
|---|---|---|---|---|---|---|
| `GET /api/v1/health` | `api/routes/health.py` | WEB | `api_v1` | `[ADAPT]` | **KEEP** | DEC-007 |
| `GET /api/v1/catalog` (통합) | `api/routes/catalog.py`, `application/services/catalog.py` | WEB | `api_v1` + `vision` | `[ADAPT]` | **KEEP** | DEC-007 |
| `POST /api/v1/inspections` | `api/routes/inspections.py`, `application/services/inspection.py` | WEB (추론만 GPU 위임) | `api_v1` + `vision` | `[ADAPT]` | **KEEP** | **DEC-007**, **DEC-008** |
| `GET /api/v1/inspections/by-request/{request_id}` | 위 | WEB | `api_v1` | `[ADAPT]` | **KEEP** | DEC-007 |
| `GET /api/v1/overlays/{id}` | `api/routes/overlays.py`, `application/services/overlay.py` | WEB | `api_v1` + `vision` | `[ADAPT]` | **KEEP** | DEC-007 |
| `GET /api/v1/overlays/{id}/image` | 위 | WEB | `api_v1` | `[ADAPT]` | **KEEP** | DEC-007, DEC-019 |
| Client 인증 (`X-Client-ID`/`X-API-Key`) | `api/dependencies/client_auth.py`, `application/services/client_auth.py`, `infrastructure/security/api_key.py` | WEB | `core` | `[REUSE]`(해시 규격) + `[ADAPT]`(Django 미들웨어/데코레이터화) | **KEEP** | **DEC-007** |
| Client별 rate limit (분당) | `api/dependencies/rate_limit.py` | WEB | `core` | `[ADAPT]` | KEEP | — |
| 공통 오류 봉투 (`{"error":{code,message,retryable}}`) | `api/schemas/errors.py`, `main.py` | WEB | `api_v1` | `[REUSE]`(규격) | **KEEP** — MES `{success,message}`와 다르므로 별도 경로 필요 | **DEC-007**, DEC-014 |
| UTC 시각 정규화 | `api/schemas/common.py` `UtcDatetime` | WEB | `api_v1` | `[REUSE]` | KEEP | **DEC-016** |
| Body size limit (413/411) | `middleware.py` | WEB | `core` | `[ADAPT]` | KEEP | — |
| `GET /api/v1/catalog/version` | `api/routes/catalog.py` | WEB | `api_v1` | `[ADAPT]` (Client 미사용, 계약상 유지) | COMPATIBILITY_LAYER | DEC-007 |
| `GET /api/v1/catalog/{processes,products,inspection-items}` | 위 | WEB | `api_v1` | `[ADAPT]` 또는 `[REMOVE]` — Client 미사용 | COMPATIBILITY_LAYER | DEC-007 |
| `GET /api/v1/inspections/{id}` | `api/routes/inspections.py` | WEB | `api_v1` | `[ADAPT]` | COMPATIBILITY_LAYER | DEC-007 |
| `GET /api/v1/inspections/{id}/result-image` | `application/services/result_image.py` | WEB | `api_v1` | `[ADAPT]` | COMPATIBILITY_LAYER | DEC-008 |
| `GET /api/v1/inspections/{id}/heatmap` | 위 | WEB | `api_v1` | `[ADAPT]` | COMPATIBILITY_LAYER | DEC-008 |
| `GET /api/v1/history` | `api/routes/history.py` | WEB | `vision` | `[ADAPT]` 또는 `[REMOVE]` — Client 미사용, 화면으로 대체 | COMPATIBILITY_LAYER | DEC-007 |
| `GET /api/v1/licenses/sources[/{file}]` | `api/routes/licenses.py`, `infrastructure/storage/distribution.py` | — | — | `[REMOVE]` — **무인증 공개 경로**. 공개 웹/WAS에 두면 안 된다 | REMOVE | **DEC-024** |
| `GET /api/v1/client-packages[/{file}]` | `api/routes/client_packages.py` | — | — | `[REMOVE]` 또는 인증 추가 후 `[ADAPT]` | REMOVE / MODIFY | **DEC-024** |

### 2.2 기준정보 / 업무 (Admin) → WEB

| 기능 | Source 위치 | Target Service | Target Domain/App 후보 | 처리 방식 | DB 영향 | 관련 결정 |
|---|---|---|---|---|---|---|
| Process CRUD | `admin/routes/processes.py`, `application/services/catalog.py` | WEB | `vision` | `[ADAPT]` + 화면 `[REWRITE]` | `processes` → Django 모델. **MES `process`(공정) 테이블과 의미 충돌** | **DEC-025** |
| Product CRUD | `admin/routes/products.py` | WEB | `vision` | `[ADAPT]` + 화면 `[REWRITE]` | `products`. **MES `material`과 개념 중복 여부 판단 필요** | **DEC-025** |
| InspectionItem CRUD | `admin/routes/inspection_items.py` | WEB | `vision` | `[ADAPT]` + 화면 `[REWRITE]` | `inspection_items`, PG native enum `inspection_type` | DEC-025 |
| 검사 순서(`display_order`) | 위 모델 필드 | WEB | `vision` | `[ADAPT]` | 위 | — |
| 활성/비활성 토글 | `admin/routes/*` `post("/{id}/active")` | WEB | `vision` | `[ADAPT]` | 위 | — |
| **InspectionItem ↔ Model 매핑** | `admin/routes/inspection_items.py` `{get,post}("/{id}/model")`, `ModelMappingRow` | **WEB** | `system` | `[ADAPT]` | `model_mappings` → WEB 소유. `model_id`가 GPU 소유 `models`를 참조 → 참조 방식 결정 | **DEC-010** |
| Overlay 등록/삭제/이미지 | `admin/routes/inspection_items.py` `{get,post}("/{id}/overlay")`, `application/services/overlay.py` | WEB | `vision` | `[ADAPT]` + 화면 `[REWRITE]` | `overlays` (x/y/w/h 死컬럼 제거 검토) | DEC-019 |
| Client(장치) 등록 / API Key 발급·재발급 / 활성화 | `admin/routes/clients.py`, `application/services/client_admin.py` | WEB | `vision` | `[ADAPT]` + 화면 `[REWRITE]` | `clients` | DEC-007 |
| 검사 이력 목록/상세/삭제 | `admin/routes/inspections.py`, `admin/filters.py` | WEB | `vision` | `[ADAPT]` + 화면 `[REWRITE]` | `inspections` | — |
| 검사 결과 이미지 / Heatmap 조회(관리) | `admin/routes/inspections.py` `get("/{id}/image")`, `get("/{id}/heatmap")` | WEB | `vision` | `[ADAPT]` | 없음 | DEC-019 |
| 이미지 보존 정책 설정 | `admin/routes/retention.py`, `application/services/retention.py`, `cli.py purge-images` | WEB | `vision` | `[ADAPT]` | `retention_policies` | **DEC-022** |
| 검사 이미지 → 데이터 수집 시스템 전송 | `admin/routes/migration.py`, `application/services/image_migration.py`, `infrastructure/migration/local_export.py` | WEB | `vision` ↔ `data` | `[REWRITE]` — **통합 후에는 내부 호출**(검사 결과 → Dataset/ImageAsset/Annotation 생성) | `image_migrations` 유지 여부 | **DEC-026** |
| Admin 대시보드 | `admin/routes/dashboard.py` | — | — | `[REPLACE]` — MES 대시보드 | 없음 | — |
| Admin 로그인 / 세션 / CSRF / throttle | `admin/routes/auth.py`, `admin/dependencies/{auth,login_throttle}.py`, `admin_users` | — | — | `[REPLACE]` — MES 사용자/권한 | **`admin_users` 폐기** | **DEC-018** |
| Admin 템플릿 22개 / `admin.css`(`--vi-*` 토큰) / 아이콘 | `admin/templates/`, `admin/static/` | — | — | `[REWRITE]` — MES 템플릿 규약 | 없음 | DEC-013 |
| Admin 오류 화면 | `admin/routes` + `error.html` | — | — | `[REPLACE]` — MES `401/403/404/error.html` | 없음 | — |
| Security Headers 미들웨어 | `middleware.py` | WEB | `core` | `[ADAPT]` | 없음 | — |
| `cli.py create-admin` | `cli.py` | — | — | `[REMOVE]` — MES 사용자 관리로 대체 | 없음 | DEC-018 |
| `cli.py create-client` | `cli.py` | WEB | `vision` | `[REPLACE]` — Admin 화면 기능으로 이미 존재 | 없음 | — |
| `cli.py seed-catalog` | `cli.py` | WEB | `vision` | `[ADAPT]` → Django management command | 없음 | — |

### 2.3 AI 모델 / 추론 → GPU Server

| 기능 | Source 위치 | Target Service | Target Domain 후보 | 처리 방식 | 비고 | 관련 결정 |
|---|---|---|---|---|---|---|
| Model 등록/수정/활성화 (Registry) | `admin/routes/models.py`, `application/services/model_admin.py`, `ModelRow` | **GPU** | `model_registry` | `[ADAPT]` — REST API화 + WEB에 관리 화면 | `models` 테이블 GPU 소유 | **DEC-006**, **DEC-009** |
| 모델 아티팩트 업로드/검증 | `application/services/model_artifacts.py`, `infrastructure/inference/artifacts.py` | **GPU** | `model_registry` | `[ADAPT]` | `model_root` | DEC-006 |
| DETECTION 추론 | `infrastructure/inference/torchvision_adapter.py` | **GPU** | `inference` | `[ADAPT]` — `POST /inference/detection` | torch 2.14.0 / torchvision 0.29.0 | **DEC-006** |
| ANOMALY 추론 (PatchCore) | `infrastructure/inference/patchcore_adapter.py` | **GPU** | `inference` | `[ADAPT]` — `POST /inference/anomaly` | 위 | DEC-006 |
| CLASSIFICATION 추론 | **없음** | GPU | `inference` | **신규 개발** | AIDataHub는 CLASSIFICATION 과제를 지원하지만 검사 측에 없다 | **DEC-005**, DEC-006 |
| Heatmap 생성 | `application/services/result_image.py`(추정 경로) + patchcore 출력 | GPU 또는 WEB | `inference` / `vision` | `[ADAPT]` | 생성 위치가 이미지 소유권과 연동 | **DEC-008** |
| 결과 이미지(원본+BBox / 원본+Heatmap) 렌더 | `application/services/result_image.py` | WEB 또는 GPU | `vision` | `[ADAPT]` | 위와 같음 | DEC-008 |
| PatchCore fit (사실상 학습) | `cli.py fit-anomaly` | **GPU** | `training` | `[ADAPT]` → Training Job API | 현재 CLI 전용 | **DEC-027** |
| Detection 학습용 데이터 export | `cli.py export-detection` | GPU 또는 WEB | `training` | `[ADAPT]` — AIDataHub Export로 대체 가능 | 중복 기능 | DEC-026 |
| Training Job 생성/조회/취소 | **없음** | GPU | `training` | **신규 개발** | 프롬프트 §2.3 B 전체 | **DEC-027** |
| Model Version 관리 | `models.version`(문자열 컬럼만) | GPU | `model_registry` | **신규 개발**(버전 엔티티화) | | DEC-009 |
| Model Load / Unload / 활성 모델 관리 | **없음** | GPU | `model_registry` | **신규 개발** | 프롬프트 §13.1 `POST /models/{id}/load` | DEC-006 |
| Deployment / Runtime 상태 | **없음** | GPU | `model_registry` | **신규 개발** | | DEC-006 |
| Evaluation Result | **없음** | GPU | `training` | **신규 개발** | | DEC-027 |
| GPU Health | `api/routes/health.py`(웹 헬스만) | GPU | `core` | **신규 개발** — `GET /health` | | — |
| WEB ↔ GPU 인증 | **없음** | 양쪽 | `core` | **신규 개발** | 프롬프트 §16.3 | **DEC-015** |
| GPU 장애 처리(Timeout / OOM / 미로딩 / Invalid Model) | **없음** | 양쪽 | — | **신규 개발** | 프롬프트 §13.4 | DEC-015 |

---

## 3. vision-inspection Client → 유지

| 기능 | Source 위치 | Target | 처리 방식 | 변경 필요 | 관련 결정 |
|---|---|---|---|---|---|
| 카메라 제어 (Basler / OpenCV / Mock) | `infrastructure/camera/*` | CLIENT | `[REUSE]` | 없음 | — |
| Live View / Preview / Overlay 렌더 | presentation(PySide6) | CLIENT | `[REUSE]` | 없음 | — |
| Capture 및 원본 보존 | `application/use_cases/submit_inspection.py` | CLIENT | `[REUSE]` | 없음 | — |
| 서버 API 호출 | `infrastructure/api/server_client.py` | CLIENT | `[REUSE]` | **Base URL만 변경**(계약 유지 시) | **DEC-007** |
| Client ID / API Key 저장 | `infrastructure/config/credentials.py` | CLIENT | `[REUSE]` | 없음 | DEC-007 |
| retry 워커(`by-request` 선조회) | `workers/retry_worker.py` | CLIENT | `[REUSE]` | 없음 | — |
| pending 임시 저장 | Client 로컬 | CLIENT | `[REUSE]` | 없음 | — |
| 연결 테스트 | `infrastructure/api/connection_test.py` | CLIENT | `[REUSE]` | 없음 | — |
| 라이선스 소스 다운로드(LGPL 대응) | `/api/v1/licenses/sources` 호출 여부 | CLIENT | `[REUSE]` — Client 코드에서는 호출 안 함 | 없음 | **DEC-024** |
| Client 패키지 자동 배포 | `/api/v1/client-packages` | CLIENT | — | 없음 | DEC-024 |

---

## 4. MES → Backbone (계승 / 선별)

### 4.1 계승 대상 — 공통 골격

| 기능 | Source 위치 | 처리 방식 | 변경 필요 | 관련 결정 |
|---|---|---|---|---|
| Django 프로젝트 구조(`configurations`/`app`/`domain`) | 전체 | `[REUSE]` | 없음 | **DEC-001** |
| Settings | `configurations/settings.py` | `[ADAPT]` — **비밀값 환경변수화, `DEBUG` 분리 필수**(D2·D3) | 필수 | — |
| URL 디스패처 (`ApiModuleView` 등) | `app/views/__init__.py` | `[ADAPT]` — **인가 훅 추가 필수**(D1) | 필수 | **DEC-014** |
| GUI 정의 / 메뉴 (`GUIConfiguration`) | `domain/gui.py` | `[ADAPT]` — 항목 대폭 축소 | 필수 | **DEC-023** |
| 화면 권한 (`GUITemplatesView` + `check_user_auth`) | `app/views/__init__.py`, `domain/services/account.py` | `[REUSE]` | 없음 | — |
| View 작성 패턴(단일 함수 + `action`) | `app/views/**` | `[REUSE]` | 없음 | DEC-014 |
| Service 계층 + `DbUtil` raw SQL | `domain/services/**`, `sql.py` | `[ADAPT]` — MSSQL 분기 제거 | 권장 | — |
| `AbstractAuditModel` | `domain/models/system.py` | `[REUSE]` | 없음 | — |
| 로깅 (`LogWriter`, `sys_log`) | `domain/services/logging.py` | `[REUSE]` | 없음 | — |
| Decimal 컨텍스트 | `domain/services/common.py` `CommonUtil.decimal_context` | `[REUSE]` | 없음 | — |
| 공통 레이아웃 / 템플릿 (`layout_page.html`) | `app/templates/app/` | `[ADAPT]` — 동기 Ajax 제거(D9) | 권장 | **DEC-013** |
| iframe 탭 셸 (`index.html`, `index_page.js`) | `app/templates/app/` | `[ADAPT]` 또는 `[REMOVE]` | 결정 필요 | **DEC-013** |
| WeZonGrid | `app/static/wezongrid/` | `[REUSE]` | 없음 | DEC-013 |
| 공통 JS (`common.js`, `bscommUtil.js`, `grid.js`, `decimal-util.js`) | `app/static/assets/js/` | `[REUSE]` | 없음 | — |
| 그리드 컬럼 설정 | `system/grid_setting.py`, `grid_col`/`grid_col_lang` | `[REUSE]` | 없음 | DEC-021 |
| 첨부파일 (`attach_master`/`attach_file`, `files/` 뷰) | `domain/models/system.py`, `app/views/files/` | `[ADAPT]` | 권장 | DEC-019 |
| 시퀀스 생성기 | `domain/models/sequence.py`, `seq_maker` | `[REUSE]` | 없음 | — |
| 공통 팝업/모달 | `app/views/popup/`, `app/templates/page/popup/` | `[REUSE]` | 없음 | DEC-013 |
| 401/403/404/error 화면 | `app/templates/*.html` | `[REUSE]` | 없음 | — |

### 4.2 계승 대상 — 시스템 관리

| 기능 | Source 위치 | 처리 방식 | 관련 결정 |
|---|---|---|---|
| 사용자 관리 | `app/views/system/user.py`, `templates/system/user.html` | `[ADAPT]` — **초기 비밀번호 `'1'` 하드코딩 수정 필요** | **DEC-002** |
| 사용자그룹 관리 | `system/usergroup.py`, `usergroup.html` | `[REUSE]` | DEC-003 |
| 메뉴권한 관리 | `system/usergroupmenu.py`, `usergroup_menu.html` | `[REUSE]` | DEC-003 |
| 메뉴 설정 | `system/{menus,menu_setup,mobile_menu}.py`, `menu_folder`/`menu_item` | `[ADAPT]` | DEC-023 |
| 공통코드 | `system/{code,system_code,user_code,systemcode_setup}.py`, `sys_code`/`user_code` | `[REUSE]` | — |
| 시스템 옵션 | `system/system_option.py`, `sys_option` | `[REUSE]` | — |
| 로그인 로그 | `system/loginlog.py`, `login_log` | `[REUSE]` | DEC-018 |
| 메뉴 사용 로그 | `system/menulog.py`, `menu_use_log` | `[REUSE]` | — |
| 시스템 로그 | `system/systemlog.py`, `sys_log` | `[REUSE]` | — |
| 즐겨찾기 | `system/bookmark.py`, `bookmark` | `[REUSE]` | — |
| 공지 / 타이틀 공지 | `system/{notice,notice_setting,title_notice}.py`, `board` | `[REUSE]` 또는 `[FUTURE]` | DEC-023 |
| 다국어 (라벨코드 / 메뉴언어) | `system/{labelcode,menu_language}.py`, `label_code`/`label_code_lang` | `[ADAPT]` 또는 `[FUTURE]` — **AIDataHub 규약과 충돌** | **DEC-021** |
| 속성/분류 마스터 | `system/property_master.py`, `prop_master`/`class_master` | `[REUSE]` 또는 `[FUTURE]` | DEC-023 |
| 근무조 / 부서 | `system/{shift,depart}.py` | `[REUSE]` 또는 `[FUTURE]` | DEC-023 |
| 배치 로그 | `system/batch_log.py`, `batch_log`/`batch_q` | `[ADAPT]` — 백그라운드 작업 기반으로 쓸지 | **DEC-022** |
| DB 스키마 조회 | `system/db_schema.py` | `[FUTURE]` | — |
| 스토리보드 | `system/storyboard.py` | `[FUTURE]` | — |
| 스마트공장 1번가 로그(`SFLog`, `add_sf_log`) | `domain/services/logging.py`, `sf_log` | `[FUTURE]` — `SF_LOG_KEY` 미설정 | — |

### 4.3 계승 대상 — 기준정보 (선별)

| 기능 | Source | 처리 방식 | 판단 근거 |
|---|---|---|---|
| 공장(Factory) | `definition/`(모델 `mes.Factory`) | `[REUSE]` | `UserProfile.Factory` FK가 참조한다 |
| 거래처(Company) | `definition/company.py`, `mes.Company` | `[REUSE]` | `UserProfile.Company` FK |
| 부서(Depart) | `definition/depart.py`, `mes.Depart` | `[REUSE]` | `UserProfile.Depart` FK |
| 단위(Unit) | `definition/unit.py` | `[REUSE]` | MES 패턴 표준 예시. 경량 |
| 공정(Process) | `definition/process.py`, `mes.Process` | **결정 필요** | vision `processes`와 의미 충돌 → **DEC-025** |
| 자재/제품(Material) | `definition/material.py`, `mes.Material` | **결정 필요** | vision `products`와 개념 중복 → **DEC-025** |
| 불량유형(DefectType) | `definition/defect_type.py` | **결정 필요** | AIDataHub `LabelClass`와 개념 중복 → **DEC-025** |
| 설비 / 워크센터 / 창고 / BOM / 라우팅 / 금형 / 작업자 / 태그 등 | `definition/*` | `[FUTURE]` | 데이터관리·비전검사·시스템관리 3개 도메인에 불필요 |

### 4.4 현재 범위 제외 (`[FUTURE]`)

| 영역 | Source | 제외 근거 |
|---|---|---|
| 영업/수주 | `app/views/sales/` | 프롬프트 §2.2가 정의한 3개 도메인 밖 |
| 생산계획 / 생산실적 / 작업지시 | `app/views/{schedule,production}/` | 위와 같음 |
| 재고 / LOT / 입출고 | `app/views/{inventory,lot}/` | 위와 같음 |
| 출하 | `app/views/shipment/` | 위와 같음 |
| 품질검사(`test`) / 점검(`check`) / SPC | `app/views/{test,check,spc}/` | 위와 같음. **단 "검사"라는 용어가 비전검사와 충돌** → `03_CONFLICT_ANALYSIS.md` C-12 |
| HACCP 전체 | `app/views/{haccp,haccp_std,hcp_*}/` | 위와 같음 |
| 설비보전 | `app/views/maintenance/` | 위와 같음 |
| 인원/위생 | `app/views/person/` | 위와 같음 |
| DAS 설비연계 / MQTT / HMI | `app/views/{das,tagdata}/`, `domain/services/mqtt.py`, `MOSQUITTO_*` | 3개 도메인 밖. 브로커 의존이 따라온다 → **DEC-023** |
| 대시보드 / 요약 | `app/views/{dashboard,summary}/` | Phase 후반 또는 제외 |
| 모바일 / PDA | `mobile.py`, `app/views/pda/`, `PDAView` | 프롬프트 범위 밖. JWT 설정 결함(D4) |
| AI 자연어검색(NL2SQL) / MES 챗봇 | `app/views/ai/nl2sql*.py`, `mes_chatbot_sse.py`, `domain/services/ai/` | **프롬프트 §17 명시 제외**(RAG / AI Chatbot) |
| MLOps 화면 7개 + `mlops_*` 테이블 | `app/views/ai/ai_analysis.py`, `templates/ai/mlops_*.html`, `domain/models/mlops.py` | 생산데이터 tabular ML. 비전 Model Registry와 도메인이 다르다 → **DEC-009** |
| AI 분석(수요예측/불량예측/소요량예측) | `app/views/ai/ai_analysis.py` | 위와 같음 |
| 전시회 / 데모 / 디지털트윈 | `wm_dashboard_exhibition_*`, `public/exhibition/`, `dt_main.html`, `DTResourceView` | 파생 목적 코드 |
| 고객사 전용 모듈 | `*_junshi`, `*_snp`, `*_woori`, `*_sejun`, `*_gs`, `*_pzas`, `*_epolytec`, `*_newtech` | 기준소스 정책상 사이트별 코드 |
| 샘플 / 테스트용 화면 | `app/views/sample*`, `templates/samples/` | 불필요 |
| Object Storage 전환 | — | **프롬프트 §1.1 / §17 명시 제외** |
| Vector DB / 문서관리 / 지식베이스 | — | **프롬프트 §17 명시 제외** |

---

## 5. 신규 개발 항목 (세 프로젝트에 구현이 없는 것)

| # | 항목 | Target | 근거 | 관련 결정 |
|---|---|---|---|---|
| NEW-01 | WEB ↔ GPU Internal REST 계약 및 클라이언트 계층 | WEB + GPU | 세 프로젝트 어디에도 없다 | **DEC-006**, DEC-015 |
| NEW-02 | WEB ↔ GPU 서비스 간 인증 | WEB + GPU | 없다 | **DEC-015** |
| NEW-03 | Training Job API (생성 / 조회 / 취소 / 상태) | GPU | `cli.py fit-anomaly`만 존재 | **DEC-027** |
| NEW-04 | Evaluation Result 저장·조회 | GPU | 없다 | DEC-027 |
| NEW-05 | Model Version 엔티티 / Deployment / Runtime 상태 | GPU | `models.version` 문자열 컬럼만 | DEC-009 |
| NEW-06 | Model Load / Unload / 활성 모델 관리 API | GPU | 없다 | DEC-006 |
| NEW-07 | CLASSIFICATION 추론 | GPU | DETECTION / ANOMALY만 있다 | **DEC-005** |
| NEW-08 | GPU 장애 처리(Timeout / OOM / 미로딩 / Invalid) 및 WEB 측 오류 매핑 | WEB + GPU | 없다 | DEC-015 |
| NEW-09 | GPU 자원 경합 제어(학습 ↔ 추론) | GPU | 없다. 현재는 웹과 같은 프로세스 | DEC-027 |
| NEW-10 | 검사 결과 → 학습 데이터셋 연결(내부 파이프라인) | WEB | vision `image_migration`은 로컬 디렉터리 내보내기 수준 | **DEC-026** |
| NEW-11 | MES Backbone 회귀 테스트 스위트 | WEB | MES에 테스트가 없다 | — |
| NEW-12 | 통합 DB 마이그레이션 (SQLAlchemy/Alembic → Django migrations) | WEB | vision 스키마 13 마이그레이션을 Django로 재정의 | **DEC-011** |
| NEW-13 | `ApiModuleView` 인가 계층 | WEB | MES에 없다 | **DEC-014** |
| NEW-14 | 통합 설정/비밀 관리(환경변수) | WEB + GPU | MES는 평문 하드코딩 | — |
| NEW-15 | 상관관계 ID(Request ID) 전파: Client → WEB → GPU | 전체 | AIDataHub `request_id` 미들웨어만 존재 | — |
