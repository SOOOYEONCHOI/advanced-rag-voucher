# 05. Database & Migration Plan (확정)

> **rev.2 (2026-09-30)** — `USER_DECISIONS.md` §1.6 반영: 검사항목 단일 테이블 통합,
> 공정·제품·보존정책·이관이력 테이블 제외. §1.6이 정본이다.

- 기준일: 2026-09-30
- 적용 Decision: DEC-002, DEC-004, DEC-010, DEC-011, DEC-012, DEC-016, DEC-017, DEC-025, §1.5 O-2·O-6

---

## 1. 기본 방침

| 항목 | 확정 |
|---|---|
| 대상 DB | **신규 PostgreSQL DB 1개** (`manufacturing_ai_platform`) |
| 기존 3개 DB | **보존**. `yest` / `aidatahub_v2` / `vision_inspection` 를 초기화하거나 수정하지 않는다 |
| 마이그레이션 | Django migrations. **`0001_initial` 하나로 시작** |
| Alembic | 사용하지 않음. vision 11테이블을 Django 모델로 재정의 |
| `migrate --fake` / `--fake-initial` / `django_migrations` 수동 수정 | **금지** |
| `DEFAULT_AUTO_FIELD` | `BigAutoField`. MES 계승 모델은 기존 `id = AutoField(primary_key=True)` 명시 유지 |
| `USE_TZ` | `False` → 컬럼 타입 `timestamp`(naive, KST). `/api/v1` 경계에서만 UTC 변환 |
| PG native enum | 사용 안 함 → `CharField(choices)` |
| 초기 데이터 | Seed 명령으로 생성(§6). 운영 데이터 이관은 §7 |

---

## 2. Table Mapping

### 2.1 MES → 유지 (이름 그대로)

| Source Model | Source Table | Target | Policy | 비고 |
|---|---|---|---|---|
| `django.contrib.auth.User` | `auth_user` | 동일 | KEEP | 커스터마이즈 없음 |
| `UserProfile` | `user_profile` | 동일 | **TRANSFORM** | `access_token`·`refresh_token` **삭제**(DEC-002 A′) |
| `UserGroup` | `user_group` | 동일 | KEEP | |
| `UserGroupMenu` | `user_group_menu` | 동일 | KEEP | |
| `MenuFolder` / `MenuItem` | `menu_folder` / `menu_item` | 동일 | KEEP | `MenuItem.MenuCode` = `gui_code` |
| `SystemCode` / `UserCode` | `sys_code` / `user_code` | 동일 | KEEP | |
| `LabelCode` / `LabelCodeLanguage` | `label_code` / `label_code_lang` | 동일 | KEEP | 인프라만(DEC-021) |
| `GridColumn` / `GridColumnLanguage` | `grid_col` / `grid_col_lang` | 동일 | KEEP | |
| `SystemOption` | `sys_option` | 동일 | KEEP | |
| `SystemLog` / `LoginLog` / `MenuUseLog` | `sys_log` / `login_log` / `menu_use_log` | 동일 | **TRANSFORM**(`login_log`) | `login_log`에 `ip_address`·`user_agent`·`fail_reason` 추가(DEC-018) |
| `Bookmark` | `bookmark` | 동일 | KEEP | |
| `PropertyMaster` / `PropertyData` | `prop_master` / `prop_data` | 동일 | KEEP | |
| `ClassMaster` / `ClassData` | `class_master` / `class_data` | 동일 | KEEP | |
| `AttachMaster` / `AttachFile` | `attach_master` / `attach_file` | 동일 | KEEP | |
| `SequenceMaker` | `seq_maker` | 동일 | KEEP | |
| `Factory` / `Company` / `Depart` / `Unit` | `factory` / `company` / `depart` / `unit` | 동일 | KEEP | `UserProfile` FK 대상 + 최소 기준정보 |
| `BatchLog` / `BatchQ` | `batch_log` / `batch_q` | — | **DROP** | `BackgroundJob`으로 대체(DEC-022). 배치로그 화면은 `BackgroundJob` 조회로 변경 |
| 그 외 MES 모델 ~150개 | 생산·재고·출하·HACCP·설비·DAS·MLOps 등 | — | **DROP** | DEC-023 Option B |

### 2.2 AIDataHub → 이관 (테이블명 유지)

`vision_data_*` 접두어를 그대로 쓴다(DEC-025, AIDataHub가 이미 통일해 둔 규칙).

| Source Model | Source/Target Table | Policy | 변경 내용 |
|---|---|---|---|
| `Tenant` | `vision_data_tenant` | **TRANSFORM** | 행 1개 고정 CheckConstraint 추가(DEC-004) |
| `TenantMembership` | `vision_data_tenantmembership` | MIGRATE | 전원 단일 Tenant 소속 |
| `Group` / `GroupMember` | `vision_data_group` / `..._groupmember` | MIGRATE | 작업그룹. 과제 접근권한용 |
| `Project` | **`vision_data_item`** | **TRANSFORM** | 검사항목으로 통합(§1.6 O-8). `code`(전역 unique)·`display_order` 추가, vision `inspection_items` 흡수. 모델명 `InspectionItem` |
| `ProjectAssignment` | `vision_data_itemassignment` | RENAME + MIGRATE | 검사항목 인원 배정 |
| `ProjectGroupAccess` | `vision_data_itemgroupaccess` | RENAME + MIGRATE | 검사항목 작업그룹 접근권한 |
| `ProjectDeletionRequest` | `vision_data_itemdeletionrequest` | RENAME + MIGRATE | 검사항목 삭제 승인 (§1.6 Q9 — 절차 유지) |
| `LabelClass` | `vision_data_labelclass` | MIGRATE | |
| `ActivityLog` | `vision_data_activitylog` | MIGRATE | |
| `Dataset` | `vision_data_dataset` | MIGRATE | |
| `ImageAsset` | `vision_data_imageasset` | **TRANSFORM** | `source_inspection_id`(null 허용) **추가** — 어느 검사에서 들어온 이미지인지 추적(§1.6 O-9). sha256 중복은 Client 경로에서 허용한다(Q4) |
| `Annotation` | `vision_data_annotation` | MIGRATE | |
| `StandardImage` | `vision_data_standardimage` | MIGRATE | |
| `LabelingTask` | `vision_data_labelingtask` | MIGRATE | 부분 unique 제약 유지 |
| `DataStandard` | `vision_data_datastandard` | MIGRATE | |
| `QualityRun` / `QualityFinding` | `vision_data_qualityrun` / `..._qualityfinding` | MIGRATE | |
| `DatasetVersion` | `vision_data_datasetversion` | MIGRATE | |
| `ExportJob` | `vision_data_exportjob` | MIGRATE | |
| `BackgroundJob` | `vision_data_backgroundjob` | **TRANSFORM** | `attempt_count`·`next_retry_at` 추가 / `error_message` 255 → `TextField`. `MIGRATION` 유형은 **추가하지 않는다**(§1.6 O-9) |
| `AuthenticationLog` | — | **DROP** | MES `login_log`로 대체(DEC-018) |
| `UserGroup` / `UserProfile` / `UserGroupMenu` | — | **DROP** | MES 스키마 사용(DEC-002) |

### 2.3 vision-inspection → 이관 (테이블명 변경)

| Source Table | Target Table | Policy | 변경 내용 |
|---|---|---|---|
| `inspection_items` | **`vision_data_item`에 흡수** | **MERGE** | `inspection_type` → `task_type`(`OBJECT_DETECTION`/`ANOMALY_DETECTION`/`CLASSIFICATION`), `active` → `status`. 별도 테이블을 만들지 않는다(§1.6 O-8) |
| `admin_users` | — | **DROP** | MES `auth_user`로 대체(DEC-018) |
| `clients` | `vision_client` | RENAME + MIGRATE | `api_key_hash` SHA-256 유지 |
| `models` | `vision_model` | **RENAME + TRANSFORM** | `inspection_type` enum→CharField. `artifact_path`는 **문자열 입력만**(업로드·검증 제외, §1.5 O-1) |
| `model_mappings` | `vision_item_model_mapping` | **RENAME + TRANSFORM** | `threshold_override`(null) **추가** / `model_code`·`model_version` 비정규화 컬럼 **추가**(DEC-010 장래 대비) / 활성 1개 부분 unique index 유지 |
| `overlays` | `vision_overlay` | **RENAME + TRANSFORM** | 死컬럼 `x`·`y`·`width`·`height` **삭제**(D16) |
| `inspections` | `vision_inspection` | **RENAME + MIGRATE** | `id`/`request_id` **`CharField(36)` 유지**(Client 계약) |

---

## 3. 주요 제약 / 인덱스

### 신규·변경 제약

```sql
-- DEC-004: Tenant 단일 행 강제
ALTER TABLE vision_data_tenant
  ADD CONSTRAINT ck_tenant_singleton CHECK (id = '00000000-0000-0000-0000-000000000001'::uuid);

-- DEC-010: 검사항목당 활성 매핑 1개 (vision 원본 유지)
CREATE UNIQUE INDEX uq_item_model_mapping_active
  ON vision_item_model_mapping (inspection_item_id) WHERE active;

-- vision 원본 유지
ALTER TABLE vision_inspection      ADD CONSTRAINT uq_vision_inspection_request_id UNIQUE (request_id);
ALTER TABLE vision_data_item       ADD CONSTRAINT uq_vision_data_item_code UNIQUE (code);   -- 전역 unique (§1.6 Q8)
ALTER TABLE vision_client          ADD CONSTRAINT uq_vision_client_client_id UNIQUE (client_id);
ALTER TABLE vision_overlay         ADD CONSTRAINT uq_vision_overlay_item UNIQUE (inspection_item_id);

-- DEC-005: 과제 ↔ 검사항목 연결 (검사항목당 과제 1개)
-- (삭제) 검사항목과 저장소가 한 테이블이므로 1:1 보장 인덱스가 필요 없다 (§1.6 O-8)
```

### RLS (DEC-004 — 유지)

AIDataHub `0001_initial`의 `TENANT_TABLES` **19개**에 대한 정책을 그대로 생성한다.

```sql
ALTER TABLE vision_data_<t> ENABLE ROW LEVEL SECURITY;
CREATE POLICY vision_data_<t>_tenant_scope ON vision_data_<t>
  USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

- 애플리케이션은 `tenant_atomic(tenant)`로 `SET LOCAL app.tenant_id`를 건다.
- 워커도 동일 규칙을 따른다.
- `vision_*`(비전 검사)와 MES 계승 테이블에는 RLS를 적용하지 않는다(테넌트 소유 모델이 아니다).
- 검증: `scripts/verify_rls.py` 이식.

---

## 4. 시각 / 타입 변환 규칙

| 원본 | 통합 후 | 처리 |
|---|---|---|
| AIDataHub aware `DateTimeField` (`timestamptz`) | naive `timestamp`(KST) | `USE_TZ=False`이므로 모델 정의 그대로 두면 Django가 naive로 저장한다. 이관 시 `AT TIME ZONE 'Asia/Seoul'` 변환 |
| vision `DateTime(timezone=True)` (UTC 저장) | naive `timestamp`(KST) | 이관 시 UTC → KST 변환 |
| `/api/v1` 응답 | UTC `Z` | 직렬화 계층 `to_utc_z()` 한 곳에서 변환(DEC-016) |
| `inspection_type` PG enum | `varchar(16)` + choices | `DETECTION` / `ANOMALY` 값 그대로 |
| `Tenant.id` UUID | 유지 | |
| `vision_inspection.id`, `.request_id` | `varchar(36)` 유지 | **Client 계약** |
| AIDataHub int8 PK | int8 유지 | `BigAutoField` |
| MES int4 PK | int4 유지 | 모델에 명시된 `AutoField` |

---

## 5. Migration 순서

`0001_initial` 하나에 전부 담되, 파일 내 `operations` 순서를 다음으로 한다.

```text
 1. django.contrib.auth / contenttypes 의존 선언
 2. MES 시스템 테이블      factory, company, depart, unit, user_group, user_profile,
                           user_group_menu, menu_folder, menu_item, sys_code, user_code,
                           label_code(+lang), grid_col(+lang), sys_option, sys_log,
                           login_log, menu_use_log, bookmark, prop_master(+data),
                           class_master(+data), attach_master(+file), seq_maker
 3. Vision 기준정보        (공정·제품 없음 — §1.6 O-8)
                           → vision_overlay, vision_client, vision_model,
 4. Tenant                 vision_data_tenant (+ singleton CheckConstraint)
 5. Data Management        tenantmembership, group, groupmember,
                           vision_data_item(검사항목 = 저장소), itemassignment,
                           itemgroupaccess, itemdeletionrequest, labelclass,
                           datastandard, dataset, imageasset, annotation, standardimage,
                           labelingtask, qualityrun, qualityfinding, datasetversion,
                           exportjob, backgroundjob, activitylog
 6. 검사 결과              vision_inspection (→ vision_client, vision_data_item, vision_data_imageasset FK)
 7. 부분 unique index      RunSQL — 검사항목당 활성 모델 매핑 1개, 이미지당 활성 라벨링 작업 1개
 8. RLS                    RunSQL — TENANT_TABLES 19개 정책
```

> 순서 근거: 검사항목과 저장소를 한 테이블로 합치면서(§1.6 O-8) **Vision 기준정보 선행 제약이 사라졌다.** `vision_data_item` 이 데이터 관리 블록의 선두에 오고, 검사 결과가 그 뒤를 따른다.

---

## 6. Seed (Phase 8)

| 명령 | 내용 |
|---|---|
| `manage.py seed_platform_base` | Tenant 1행(고정 UUID), `user_group`(dev/admin/user), 관리자 계정 1개(비밀번호는 실행 시 입력), `sys_option`(LOGO_TITLE, main_menu) |
| `manage.py seed_menu` | `menu_folder` 3개(데이터관리/비전검사관리/시스템관리) + `menu_item` 약 30건. `gui.py` `GUI_ITEMS` 키와 1:1 일치를 검증 |
| `manage.py seed_vision_catalog` | vision `cli.py seed-catalog` 이식 — **샘플 검사항목만**(공정·제품 없음, §1.6 O-8). 검사항목 생성 시 업로드 데이터셋이 자동 생성되는지 함께 확인 |
| `manage.py seed_demo_data` *(선택)* | 개발용 검사항목·이미지 샘플 |

`seed_menu`는 **`gui.py`에 있는데 `menu_item`에 없는 코드**와 그 반대를 모두 오류로 보고한다(메뉴 누락 방지).

---

## 7. 운영 데이터 이관 (DEC-012 — 조건부)

**현재 방침: 신규 시작(Seed).** Phase 8 시작 전에 아래를 확인하고 재판정한다.

```sql
-- AIDataHub 10.10.10.20/aidatahub_v2
SELECT count(*) FROM vision_data_tenant;
SELECT count(*) FROM vision_data_item;
SELECT count(*) FROM vision_data_imageasset;
SELECT count(*) FROM vision_data_annotation;
SELECT count(*) FROM auth_user;
-- vision_inspection
SELECT count(*) FROM inspection_items;
SELECT count(*) FROM inspections;
SELECT count(*) FROM models;
SELECT count(*) FROM clients;
-- MES 10.10.10.230/yest
SELECT count(*) FROM auth_user;
SELECT count(*) FROM user_group;
```
파일 용량: AIDataHub `media/`, vision `storage_root`.

**판정 기준**: `vision_data_annotation` 이 수천 건 이상이면 이관한다(라벨링은 재현 비용이 가장 큰 자산).

### 이관이 결정될 경우의 절차

```text
T1. 사용자 매핑표 작성    (각 DB의 auth_user.id → 통합 DB auth_user.id)
                          username 기준 매칭. 중복 username 은 수동 판정
T2. 기준정보 이관         vision: processes/products/inspection_items/overlays/clients/models
                          → vision_* (id 유지. Client Catalog 캐시 키 보존을 위해 필수)
T3. Data Management 이관  tenant(단일 고정 UUID로 치환) → project → dataset → imageasset
                          → annotation → labelclass → labelingtask → qualityrun → ...
                          모든 tenant_id 를 고정 UUID 로 치환
T4. 파일 이관             media/tenants/{old}/... → $STORAGE_ROOT/datasets/{project}/...
                          vision storage_root/inspections/... → $STORAGE_ROOT/inspections/...
                          DB의 경로 컬럼을 새 경로로 UPDATE
T5. 시각 변환             UTC/aware → naive KST
T6. 시퀀스 재설정         SELECT setval(pg_get_serial_sequence('<t>','id'), max(id)) FROM <t>;
T7. 검증                  §8
```

**주의**: AIDataHub 원격 DB는 제약·인덱스 이름이 `ai_domain_` 접두어로 남아 있다. 이관 스크립트가 **제약 이름에 의존하면 안 된다**(C-03).

---

## 8. Verification

| # | 검증 | 방법 |
|---|---|---|
| V1 | 마이그레이션 일관성 | `manage.py makemigrations --check --dry-run` → No changes |
| V2 | 시스템 점검 | `manage.py check` 이슈 0건 |
| V3 | RLS 적용 | `scripts/verify_rls.py` PASS. `TENANT_TABLES` 19개 전부 정책 존재 |
| V4 | Tenant 단일성 | `SELECT count(*) FROM vision_data_tenant` = 1 |
| V5 | 메뉴 정합성 | `seed_menu --check` — `gui.py` ↔ `menu_item` 양방향 일치 |
| V6 | 인가 매핑 정합성 | `app/views/<task>/<view>.py` 전수 ↔ `apiPermissionMap` 양방향 일치(스크립트) |
| V7 | FK 무결성 | `vision_inspection.image_asset_id` → `vision_data_imageasset` 유효 (검사 1건 = 이미지 1건) |
| V8 | 부분 unique | 검사항목당 `active=true` 매핑이 최대 1개 |
| V9 | 파일 경로 | DB의 모든 이미지 경로가 `$STORAGE_ROOT` 아래 실제 파일과 일치(샘플 검사) |
| V10 | 시퀀스 | 각 테이블 `max(id)` < `nextval` |

---

## 9. Rollback

| 상황 | 조치 |
|---|---|
| 마이그레이션 실패 | 신규 DB를 **DROP 후 재생성**. 기존 3개 DB는 건드리지 않았으므로 원 시스템에 영향 없음 |
| Seed 오류 | `seed_*` 재실행(멱등 설계). 실패 시 DB 재생성 |
| 데이터 이관 실패 | 이관 스크립트를 트랜잭션 단위(T2/T3/T4)로 나누고, 각 단계 전 `pg_dump` 스냅샷 확보 |
| 파일 이관 실패 | 원본을 **이동이 아니라 복사**로 옮긴다. 원본은 검증 완료까지 삭제하지 않는다 |
| 전환 실패 | 기존 3개 시스템이 그대로 살아 있으므로 그쪽으로 복귀 |

---

## 10. Related Decision

DEC-002(A′) · DEC-004(B) · DEC-010(B) · DEC-011(A) · DEC-012(A 조건부) · DEC-016(B) · DEC-017(A) · DEC-018(A) · DEC-019(A) · DEC-022(A) · DEC-023(B) · DEC-025(A) · §1.5 O-1·O-2·O-6 · **§1.6 O-8~O-16**
