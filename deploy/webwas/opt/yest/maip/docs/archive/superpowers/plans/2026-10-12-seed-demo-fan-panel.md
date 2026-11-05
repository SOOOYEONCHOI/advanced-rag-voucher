# seed_demo 냉각팬 패널 3종 검사항목 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 데모 검사항목을 `tmp/sample_data` 20장 기반의 냉각팬 패널 3종(분류·이상탐지·객체탐지)으로 바꾸고, 옛 데모 3종(SCRATCH·SURFACE·ASSEMBLY)은 코드와 개발 DB 에서 걷어 낸다.

**Architecture:** `seed_demo` 의 `ITEMS` 를 냉각팬 3종으로 바꾸고, 기본 실행과 `--samples` 실행이 같은 함수로 검사항목·라벨 클래스·배정을 만든다. `--samples` 는 3종 모두에 대표 이미지·Overlay·이미지 20장을 넣는다. 옛 3종 삭제는 개발 DB 에서 한 번만 하는 작업이라 seed_demo 에 넣지 않는다.

**Tech Stack:** Django 5.2 management command, `ImageService.upload_images`, `ItemPlatformService.delete_item`, Playwright e2e

## 사용자 결정 (2026-10-12)

| 항목 | 결정 |
|---|---|
| 옛 데모 3종 | seed_demo 에서 빼고 **개발 DB 에서도 삭제** |
| 분류·객체탐지 20장 | **이미지만 넣는다**(라벨을 미리 채우지 않는다) |
| 분류 클래스 | **정상 / 불량 2종** |

## 검사항목

| 코드 | 이름 | 유형 | 라벨 클래스 |
|---|---|---|---|
| `FAN-PANEL` (그대로) | 산업용 냉각팬 패널 단면(이상탐지) | 이상 탐지 | 지금 4종 그대로(스크래치·나사 누락·팬 그릴 변형·홀 위치 불량) |
| `FAN-PANEL-CLS` | 산업용 냉각팬 패널 단면(분류) | 분류 | `normal` 정상(`is_defect=False`) · `defect` 불량(`is_defect=True`) |
| `FAN-PANEL-DET` | 산업용 냉각팬 패널 단면(객체탐지) | 객체 탐지 | 이상탐지와 같은 결함 4종 |

- `FAN-PANEL` 은 코드를 바꾸지 않는다. Wezard 문서·`external_ref`(`maip:FAN-PANEL:…`)·스냅샷 #91 이 이 코드에 묶여 있다. 이름만 바뀐다(`update_or_create` 가 다시 돌 때 반영).
- 업로드 규칙은 지금 FAN-PANEL 과 같다. `SAMPLE_DEFECT_FILES`(2·3·12·13·14)는 라벨링 대상(`UNLABELED`), 나머지 15장은 라벨링 없이 검수 대기(`SUBMITTED`)다.
  - 분류: 정상 클래스가 하나라 업로드가 정상 주석을 자동으로 단다(`ImageService.normal_class`).
  - 객체탐지: 주석이 달리지 않는다(박스 없는 정상).
  - 이 자동 처리는 지금 업로드 화면과 같은 동작이다. 라벨을 미리 채우는 것이 아니다.
- 분류는 `/api/v1/catalog` 에 나오지 않는다(DECISIONS O-14). 비전검사 클라이언트에는 이상탐지·객체탐지 2종만 보인다.

## 영향 범위 (조사 결과)

| 대상 | 지금 | 바꾼 뒤 |
|---|---|---|
| e2e·검증 스크립트 | `?project=3`(SCRATCH)·`?project=4`(SURFACE)·`'표면 스크래치'` 고정 | 코드로 id 를 찾는다. 3 → `FAN-PANEL-DET`, 4 → `FAN-PANEL` |
| `tests/test_seed_demo_permissions.py` | `code='SCRATCH'` | `FAN-PANEL-DET` |
| `tests/e2e/test_workflow.py` "Client 전송 검사가 목록에 나온다" | 개발 DB 에 남은 SCRATCH 검사 5건에 기댄다 | 삭제하면 검사가 0건이 된다. `test_client_workflow` 가 같은 것을 보면 이 테스트를 지우고, 아니면 자기 검사를 보낸다 |
| 개발 DB SCRATCH(3)·SURFACE(4) | 클라이언트 검사 5·2건. `VisionInspection` 이 검사항목을 PROTECT 로 잡아 `delete_item` 이 거절한다 | 검사 기록을 먼저 지우고 삭제한다(Task 2) |
| SCRATCH Overlay | 클라이언트 쪽 "현장 PC 시험이 끝날 때까지 남겨 달라" 요청이 문서에 있다 | 사용자 결정으로 그 요청을 문서에서 지운다. Overlay 도 함께 사라진다(Task 4) |
| Wezard 실패 시험용 SCRATCH #52(FAILED) | Wezard 요청 프롬프트에 실패 처리 시험용으로 적었다 | 대신 FAN-PANEL-DET 로 실패 스냅샷을 만든다(Task 2) |
| 기본 `seed_demo` 다시 실행 | 작업자 비밀번호와 **CLIENT-001 API Key 를 다시 만든다** | 개발 DB 에서는 기본 실행을 하지 않고 `--samples` 만 돌린다. 그래서 `--samples` 도 검사항목을 만든다 |

---

### Task 1: seed_demo 를 냉각팬 3종으로 바꾼다

**Files:**
- Modify: `domain/management/commands/seed_demo.py`
- Test: `tests/test_seed_demo_samples.py`, `tests/test_seed_demo_permissions.py`

- [ ] **Step 1: 테스트를 먼저 고친다(RED)**
  - `test_seed_demo_samples.py`:
    - 3종이 모두 생긴다.
    - 각 검사항목에 이미지 20장, 대표 이미지, Overlay v1 이 있다.
    - 이상탐지 이름은 `산업용 냉각팬 패널 단면(이상탐지)` 이다.
    - 분류 클래스는 정상·불량이고, 정상 15장에 정상 주석이 있다.
    - 객체탐지 정상 15장은 `SUBMITTED` 이고 주석이 없다.
    - 다시 돌려도 늘지 않는다.
    - 파일이 빠지면 아무 검사항목도 만들지 않는다.
  - 기본 실행 테스트:
    - `SCRATCH`·`SURFACE`·`ASSEMBLY` 가 생기지 않는다.
    - 냉각팬 3종이 이미지 없이 생긴다.
  - `test_seed_demo_permissions.py`: `code='SCRATCH'` → `'FAN-PANEL-DET'`
  - 실행: `.venv/bin/python manage.py test tests.test_seed_demo_samples tests.test_seed_demo_permissions --settings=configurations.test_settings` → 실패를 확인한다
- [ ] **Step 2: 구현(GREEN)**
  - `ITEMS` 를 위 표의 3종으로 바꾸고 `SAMPLE_ITEM` 을 없앤다.
  - 검사항목·라벨 클래스·배정을 만드는 부분을 `_upsert_items(tenant, users)` 하나로 둔다. 기본 실행과 `_seed_samples` 가 함께 부른다(지금 두 곳에 같은 코드가 있다).
  - `_seed_samples` 는 3종마다 대표 이미지·Overlay·이미지 20장을 넣는다. 이미 있으면 건드리지 않는 지금 규칙을 따른다.
  - 출력은 검사항목마다 한 줄이다(`FAN-PANEL-CLS(id=…) 새로 20장, 건너뜀 0장`).
  - 모듈 docstring 의 `FAN-PANEL 검사항목만 더한다` 를 3종으로 고친다.
- [ ] **Step 3: 테스트 통과 확인** — Step 1 명령이 통과해야 한다
- [ ] **Step 4: 커밋** — `feat: seed_demo 데모 검사항목을 냉각팬 패널 분류·이상탐지·객체탐지 3종으로 바꾼다`

### Task 2: 개발 DB 정리 (사용자 확인 후 한 번 실행)

seed_demo 에 넣지 않는다. 검사 기록 삭제를 seed 명령에 두면 `--force` 로 운영 DB 에서 돌릴 때 사고가 난다.

- [ ] **Step 1: 지울 것 확인(읽기만)** — 3·4·5 의 검사 기록·이미지·스냅샷·Export·Overlay·모델 매핑 건수를 출력한다
- [ ] **Step 2: 삭제(사용자 확인 후)** — `manage.py shell`:
  - `tenant_atomic` 안에서 3·4 의 `VisionInspection` 을 지운다. 이 테이블을 PROTECT 로 잡는 테이블이 있으면 먼저 지운다 — 실행 전에 확인한다.
  - 그 뒤 `ItemPlatformService.delete_item(3|4|5)` 를 부른다. 이미지·Export 파일과 대표 이미지는 이 함수가 지운다.
- [ ] **Step 3: 표본 반영** — `.venv/bin/python manage.py seed_demo --samples tmp/sample_data --force`
  - 기본 실행은 하지 않는다. 기본 실행은 CLIENT-001 키를 다시 만든다.
  - FAN-PANEL 은 이름만 바뀐다. 이미지·스냅샷 #91 은 그대로 남는다.
  - CLS·DET 는 각각 20장이 생긴다.
- [ ] **Step 4: Wezard 실패 시험용 스냅샷**
  - 화면에서 FAN-PANEL-DET 의 정상 이미지 5장을 검수 승인한다.
  - 그 상태로 스냅샷을 만들고 워커를 돌린다. 학습용이 10장 미만이라 Wezard zip 이 `FAILED` 여야 한다.
  - 그 스냅샷 id 를 사용자에게 알린다. SCRATCH #52 를 대신한다.
- [ ] **Step 5: 확인** — 검사항목 목록에 냉각팬 3종만 보이는지, `/api/v1/catalog` 에 FAN-PANEL·FAN-PANEL-DET 만 나오는지 본다

### Task 3: e2e·검증 스크립트에서 고정 id 를 없앤다

**Files:**
- Modify:
  - `tests/e2e/conftest.py`(코드 → id 헬퍼)
  - e2e: `tests/e2e/test_data_screens.py`, `test_crud.py`, `test_workflow.py`, `test_grid_common.py`, `test_detail_form.py`
  - 스크립트: `scripts/verify_modals.py`, `verify_buttons.py`, `verify_layout_stable.py`, `capture_ui.py`

- [ ] **Step 1: id 를 찾는 헬퍼**
  - 로그인한 세션으로 검사항목 목록 API 를 불러 코드로 id 를 찾는다. 응답 모양은 구현 때 `app/views/item/item_admin.py` 에서 확인한다.
  - e2e 는 conftest 픽스처로 둔다.
  - 스크립트 4개는 지금 `'?project=3'` 한 줄씩이다. 이미 공유하는 로그인 코드가 있으면 거기에 둔다. 없으면 각 스크립트에서 한 번 찾는다.
- [ ] **Step 2: 고정 id 교체**
  - `?project=3` → `FAN-PANEL-DET`, `?project=4` → `FAN-PANEL`
  - `'표면 스크래치'` → `'산업용 냉각팬 패널 단면(객체탐지)'`
  - `test_workflow` 의 `'SCRATCH'` 검사는 위 영향 범위 표대로 처리한다
  - `test_data_screens.py` docstring 의 3·4·5 설명을 고친다
- [ ] **Step 3: 실행(고친 범위만, AGENTS [5])**
  - e2e: `.venv/bin/python -m pytest tests/e2e/test_data_screens.py tests/e2e/test_crud.py tests/e2e/test_workflow.py tests/e2e/test_grid_common.py tests/e2e/test_detail_form.py -q`
  - 스크립트: `verify_modals.py`, `verify_buttons.py`, `verify_layout_stable.py`
- [ ] **Step 4: 커밋** — `test: e2e·화면 검증이 데모 검사항목을 고정 id 대신 코드로 찾는다`

### Task 4: 문서

- [ ] **`docs/DATA_MODEL.md` seed 표:**
  - 검사항목 3개(`SCRATCH`·`SURFACE`·`ASSEMBLY`) → 냉각팬 3종
  - `--samples` 가 3종 모두에 20장을 넣는다
- [ ] **`docs/DEVELOPMENT.md`:** seed_demo 설명(50·58행)과 e2e 가 쓰는 데모 검사항목을 고친다
- [ ] **`docs/client/SERVER_API_CONTRACT.md`:**
  - 576행 "지금 등록된 Overlay"에서 SCRATCH 를 남겨 둔다는 내용을 지운다(사용자 결정 2026-10-12). Overlay 시험은 FAN-PANEL·FAN-PANEL-DET 로 한다.
  - §17 변경 이력에 남긴다.
  - 224행 카탈로그 예시는 형식 설명용이므로 그대로 둔다.
- [ ] **`docs/client/SERVER_REQUESTS.md` 331·332행:** "남겨 달라" 요청 행을 지운다. ASSEMBLY 행은 "삭제함(2026-10-12)"으로 바꾼다
- [ ] **`app/views/system/menus.py:8` 주석:** 예시 `표면 스크래치` → 냉각팬 검사항목 이름
- [ ] **Wezard 문서(`maip-api.md` 87행 SCRATCH #52 예시):** 실측 예시이므로 Task 2 Step 4 의 새 실패 스냅샷 응답으로 바꾼다
- [ ] 정적 검증: `verify_links.py`, `verify_naming.py`, `verify_korean_only.py`
- [ ] 커밋 — `docs: 데모 검사항목을 냉각팬 패널 3종으로 바꾼 것을 반영한다`

## 하지 않는 것

- 분류·객체탐지 라벨 미리 채우기(사용자 결정)
- 옛 3종을 지우는 seed_demo 옵션 — 한 번뿐인 개발 DB 정리다
- 전체 단위·전체 e2e — 고친 범위만 돌린다. 필요해지면 이유를 밝혀 묻는다

## 실행 기록 (2026-10-12)

- Task 1·3·4 완료. Task 2: 개발 DB 에서 SCRATCH(3)·SURFACE(4)·ASSEMBLY(5)와 검사 기록 7건·Overlay 파일을 지우고 `--samples` 를 돌렸다 — FAN-PANEL-CLS 961, FAN-PANEL 604(이름만 변경), FAN-PANEL-DET 962. 카탈로그는 604·962 만
- 계획에서 벗어난 것:
  - Task 2 Step 4(Wezard 실패 시험 스냅샷)는 하지 않았다. Wezard 가 #52 로 실패 경로를 이미 확인했고(`wezard-api.md` §11.1), 만들면 FAN-PANEL-DET 에 승인 스냅샷이 남는다. 그래서 `maip-api.md` 의 #52 예시는 그대로 둔다
  - 검사 이력 e2e 3건이 SCRATCH·CLIENT-001 실측 기록에 기대고 있어, conftest 에 `inspection` 픽스처(E2E-INSP- 기록 하나, 끝나면 삭제)를 더했다
