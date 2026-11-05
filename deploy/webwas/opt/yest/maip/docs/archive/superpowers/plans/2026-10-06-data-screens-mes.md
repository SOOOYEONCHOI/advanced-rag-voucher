# 데이터 관리 화면 MES 전환 · 스냅샷 작업화 · 운영 결함 2건 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 데이터 관리 화면 6개를 비전검사 관리·시스템 관리와 같은 MES 화면·MES API 구조로 바꾼다. "검사항목 목록"은 "검사항목 관리"로 이름을 바꿔 시스템 관리로 옮긴다. 품질 점검을 없애고 "스냅샷 등록 → 워커가 그 시점 데이터셋 zip 생성 → 화면에서 다운로드"로 줄인다. 그 전에 운영 결함 2건(STATUS 우선순위 3)을 막는다.

**Architecture:**
- **화면:** `app/layout_page.html`(MES 셸) 위에 `제목 카드 → 검색 카드 → WeZonGrid → 상세 카드` 구조로 다시 쓴다.
- **API:** 데이터 REST(`/api/data/...`) 대신 MES 동적 dispatch `/api/item/<view>?action=...` 를 쓴다. 화면 하나에 모듈 하나(`app/views/item/<view>.py`)다.
- **`item` task 만 따로 두는 것:** 이 task 에서만 `ApiModuleView` 가 다음을 맡는다.
  - 요청 전체를 `tenant_atomic()` 으로 감싼다.
  - 읽기 action 이 아닌 요청은 POST 만 받는다.
  - `ItemApiError` 를 400 JSON 으로 바꾸고 롤백한다.
- **인가:** 메뉴 권한은 `gui.py` 매핑 한 곳, 검사항목 권한은 서비스 계층(`AuthorizationService`)이다.
- **스냅샷:** 등록할 때 manifest 를 동기로 고정하고 zip 생성만 워커가 한다.

**Tech Stack:** Django 5.0.4 · PostgreSQL 16(RLS) · jQuery · Bootstrap 5 · WeZonGrid(`dataMode:'server'`) · Playwright e2e

**Spec:**
- 사용자 요청과 결정(2026-10-06): 아래 "요청"·"결정" 절.
- 근거 문서:
  - `docs/STATUS.md` §3 우선순위 3·4, §2-1, §3-6
  - `docs/UI_GUIDE.md` §1·§4·§5·§8
  - `docs/DECISIONS.md` DEC-014·DEC-022
  - `docs/client/SERVER_REQUESTS.md` 3차(열린 요청 없음)

## Global Constraints

- **문구:** 사용자 문구는 `~합니다` 체로 쓴다(`~해 주세요` 포함). `~하세요`·`~할까요?` 는 그대로 둔다.
- **Ajax:** 동기 Ajax 를 쓰지 않는다. 조회는 MES `AjaxUtil.getAsyncData`, 변경은 `AjaxUtil.postAsyncData`·`postFileAsyncData` 다.
- **권한 매핑:** API 모듈을 더하면 `domain/gui.py` `taskview_menu_code_map()` 에도 등록한다. `scripts/verify_permission_map.py` 가 빠뜨린 것을 잡는다.
- **RLS:** RLS 를 우회하지 않는다. `item` task 는 dispatch 가 `tenant_atomic()` 으로 감싼다.
- **파일:** 파일은 권한을 확인하는 View 로만 내준다(`app/views/files/media.py`). 그대로 쓴다.
- **마이그레이션:** Django 로만 한다. `--fake` 는 쓰지 않는다.
- **설정 키:** 새 키는 `.env.example` 에 placeholder 와 함께 적는다.
- **테스트:**
  - 단위 테스트는 `--settings=configurations.test_settings` 로 돌린다. 이 설정은 `API_AUTHZ_MODE='enforce'` 다.
  - e2e 는 `E2E-`·`e2e-` 데이터만 만들고 끝나면 지운다.
- **`X_FRAME_OPTIONS`:** `'SAMEORIGIN'` 을 유지한다.
- **색:** 하드코딩 색을 쓰지 않고 `tokens.css` 토큰만 쓴다.
- **버튼:** 새 버튼 클래스를 만들지 않는다. 버튼 계층은 UI_GUIDE §4 를 따른다.
  - 주 동작: `btn-band`·`btn-search`
  - 보조: `btn-input`
  - 되돌릴 수 없는 동작: `btn-dell`
- **HTTP 상태줄:** 상태줄 사유 문구(`reason`)에 한글을 넣지 않는다.
- **커밋:** 메시지는 한국어로 쓴다. main 에 직접 커밋하지 않는다.

---

## 요청 (2026-10-06)

| # | 요청 |
|---|---|
| U-1 | 데이터 관리의 "검사항목 목록"·"검사항목 홈"·"데이터 목록"·"라벨링 작업"·"검수 작업"·"스냅샷 관리" 디자인과 화면 구조를 비전검사 관리·시스템 관리(MES) 디자인으로 맞춘다 |
| U-2 | "검사항목 목록"을 "검사항목 관리"로 바꾸고, 디자인을 보완한 뒤 시스템 관리 메뉴 아래로 옮긴다 |
| U-3 | 스냅샷 관리의 "데이터 품질 점검"을 없앤다. 스냅샷 생성 작업을 등록하면 워커가 그 시점 기준으로 데이터셋을 만들고, 끝나면 다운로드를 표시해 화면에서 받는다 |
| U-4 | STATUS 우선순위 3을 고친다: 검사 접수가 롤백되면 고아 파일이 남는 것, 워커가 강제 종료되면 작업이 `RUNNING` 으로 고착되는 것 |

- **Client 쪽:** `SERVER_REQUESTS.md` 3차는 "R10~R18 모두 종결, 열린 요청 없음"이다. Client 에 남은 일(0.1.6 전달, Overlay 3 통보)은 [2026-10-06-client-requests-followup.md](2026-10-06-client-requests-followup.md) Task 3·5 에서 그대로 기다린다.
- **`/api/v1`:** 이 계획은 `/api/v1` 응답을 바꾸지 않는다. Task 1 은 실패했을 때 파일을 정리하는 것뿐이라 계약 문서는 고치지 않는다.

## 결정 (2026-10-06 확정)

### 화면·API 구조

| # | 결정 | 이유 |
|---|---|---|
| D-1 | 데이터 화면 6개를 `app/layout_page.html` 로 옮긴다. `data/_base.html` 은 메뉴에서 내린 작업 대기열(`home.html`)만 쓴다 | MES 화면이 가진 것을 그대로 얻는다: 제목, 즐겨찾기, 쓰기 권한이 없으면 버튼 숨김(`y_write_auth`), WeZonGrid |
| D-2 | **데이터 API 를 MES 동적 dispatch 로 바꾼다** — `/api/item/<view>?action=...` | 화면은 MES `AjaxUtil` 과 `Alert` 하나로 통일되고, 권한 매핑도 `gui.py` 한 곳이 된다. 화면마다 자기 API 를 가지므로 "다른 메뉴의 API 를 불러 403" 문제가 사라진다(AGENTS [3]). DEC-014 의 근거("동적 dispatch 에는 권한을 붙일 지점이 없다")는 `ApiModuleView.dispatch` 인가 훅이 생기면서 더는 맞지 않는다 |
| D-3 | 모달: 입력 폼은 Bootstrap `.modal`(`vision/client.html` `#apiKeyModal` 방식), 확인은 `Alert.confirm`, 알림은 `Notify`·`Alert.alert` | MES 화면과 같은 방식이다. 데이터 화면에 한해 STATUS D-4 가 풀린다 |
| D-4 | 라벨링 작업은 셸·제목 카드·버튼·색만 MES 로 바꾼다. 3열 작업대(대기열·캔버스·주석 목록)는 그대로 둔다 | 캔버스 작업대는 그리드 화면이 될 수 없다 |
| D-5 | "검사항목 관리"는 시스템 관리 **맨 위**(사용자 앞)에 둔다. 메뉴 코드 `wm_data_item` 은 유지하고, 하위 메뉴가 없는 폴더는 메뉴 트리에 내보내지 않는다 | 코드를 바꾸면 검증 스크립트와 e2e 가 줄줄이 바뀐다. 작업자 화면에 빈 시스템 관리 폴더가 보이는 것도 막는다 |

### 스냅샷·품질 점검

| # | 결정 | 이유 |
|---|---|---|
| D-6 | `QualityRun`·`QualityFinding` 테이블, `DatasetVersion.readiness`, `BackgroundJob.JobType.QUALITY` 를 마이그레이션으로 지운다. 남은 QUALITY 작업 행도 지운다. RLS 대상은 20 → 18 테이블이 된다. `Dataset.Status.VALIDATED` 는 선택지로 남기고 더는 쓰지 않는다 | 기능을 없애면서 테이블을 남기지 않는다 |
| D-7 | 스냅샷 등록 모달에서 Export 형식을 하나 고른다(기본값은 검사항목 유형의 첫 형식). 등록은 manifest 고정(동기)과 Export 작업 적재로 이뤄진다. 승인 이미지가 0건이면 거절한다. 실패한 스냅샷은 "다시 만들기"로 같은 형식을 다시 적재한다. 같은 데이터셋의 동시 등록은 행 잠금으로 줄 세운다 | 요청한 흐름 그대로다. 품질 점검이 하던 Export 관문(`NOT_READY` 409)도 함께 걷는다 |

### 운영 결함·업로드

| # | 결정 | 이유 |
|---|---|---|
| D-8 | 워커는 작업을 집기 전에, `started_at` 이 `WORKER_STALE_SECONDS`(기본 3600)보다 오래된 `RUNNING` 을 `QUEUED` 로 되돌리고 `attempt_count` 를 1 올린다. 3번째에는 FAILED 로 끝내고 Export 도 FAILED 로 맞춘다. 실패 상태를 Export 에 맞추는 것, zip 고아 파일 정리, 접수·업로드 고아 파일 정리도 함께 한다 | 워커 2개 운영에서 "시작할 때 전부 초기화"는 다른 워커의 작업을 빼앗는다. 한계: 3600초보다 오래 도는 정상 작업은 두 번 돈다. 그때 heartbeat 를 더한다 |
| D-9 | 업로드 모달은 파일을 **20개씩** 나눠 차례로 보낸다. 서버는 21번째부터를 거절 목록에 넣는다 | 지금은 101개부터 400 이 나고, 21번째부터는 말없이 버린다 |

### 진행 방식

| # | 결정 | 이유 |
|---|---|---|
| D-10 | 3단계로 나눠 단계마다 main 에 병합한다: ① `fix/job-file-safety`(Task 1·2) ② `feat/snapshot-job`(Task 3·4·5) ③ `feat/data-screens-mes`(Task 6~11) | ②는 기존 스냅샷 화면을 깨므로 새 화면까지 한 번에 병합한다 |

### MES API 세부 (D-2)

| # | 결정 | 이유 |
|---|---|---|
| B-1 | task 이름은 `item` — `/api/item/<view>`, 모듈은 `app/views/item/<view>.py` | 전환하는 동안 `/api/data/` 는 기존 REST 와 미들웨어가 먼저 받는다. 데이터 관리는 검사항목 단위로 움직인다 |
| B-2 | 모듈 6개 — `item_admin`(→`wm_data_item`) · `item_home`(→`wm_data_item_detail`) · `image`(→`wm_data_image`) · `labeling`(→`wm_data_labeling`) · `review`(→`wm_data_review`) · `snapshot`(→`wm_data_snapshot`) | 화면 하나에 모듈 하나다. 각 모듈은 자기 화면에 필요한 조회(검사항목 이름·라벨 클래스 등)를 직접 가진다 |
| B-3 | `item` task 는 dispatch 가 `request.tenant = current_tenant()` 를 붙이고 함수 호출 전체를 `tenant_atomic()` 으로 감싼다 | 함수마다 걸게 하면 하나만 빠뜨려도 결과가 소리 없이 0건이 된다 |
| B-4 | 모듈은 `READ_ACTIONS` 를 선언한다. 거기에 없는 action 을 POST 가 아닌 메서드로 부르면 405 다 | MES 는 메서드로 R/W 를 판정한다. GET 으로 변경 action 을 부르면 읽기 권한만으로 통과한다. 선언을 빠뜨렸을 때 "열림"이 아니라 "막힘"이 되게 한다 |
| B-5 | 중첩 값(주석·편집 단계·배정 인원)은 `Q` 필드에 JSON 문자열로 보낸다(`make_parameter` 가 풀어 준다). 파일은 `postFileAsyncData` 로 보낸다 | 메뉴권한 화면이 이미 이 방식을 쓴다 |
| B-6 | 화면 Task 마다 그 화면의 MES 모듈과 테스트를 만들고, 쓰지 않게 된 REST 경로와 테스트를 지운다 | 단계마다 앱이 온전하다 |
| B-7 | 그대로 두는 것: `/media/...` 파일 View, 작업 대기열(`home.html`)의 REST 3경로(`labeling/queue`·`home/statistics`·`activity-log`)와 그것을 위한 미들웨어·`urls_data.py`, `/api/v1` | 작업 대기열은 STATUS 우선순위 8 에서 정한다. 그때 REST 를 완전히 지운다 |

### `item` 모듈 규약 (Task 4 이후 모든 모듈)

**응답**
- 조회 결과는 dict 다. 서버 페이징 목록이면 `{"rows": [...], "totalRows": n, ...}` 로, WeZonGrid `applyRemoteData` 가 그대로 받는 모양이다.
- 변경 결과는 `{"success": true, "message": "...", ...}` 다.

**실패**
- 사용자에게 보일 업무 오류는 `raise ItemApiError("문구")` 로 낸다. 응답은 400 `{"success": false, "message"}` 이고 트랜잭션이 롤백된다.
- 서비스가 사용자 문구로 던진 `ValueError` 는 모듈이 `ItemApiError` 로 바꿔 던진다. 다른 예외 문구는 내보내지 않는다.

**검사항목 문맥**
- 화면은 주소의 `?project=` 를 `item_id` 파라미터로 보낸다.
- 모듈은 `load_item(context, action)` 으로 검사항목을 읽고 권한을 확인한다. 없으면 404, 권한이 없으면 403 이다.

**권한**
- 메뉴 권한은 dispatch 가 본다.
- 검사항목 권한은 `AuthorizationService.require(context.request, "<action>", item=item)` 으로 본다. `PermissionDenied` 는 403 이 된다.

---

## 조사로 확인한 사실

| 사실 | 위치 | 계획에 미치는 것 |
|---|---|---|
| 품질 점검이 Export 의 관문이다 | `version.py:34-38`, `snapshot_api.py:214-215` | 관문을 함께 걷는다(Task 3) |
| 스냅샷은 지금 동기로 manifest(JSON)만 만든다. Export 는 현재 `ImageAsset.file` 을 읽는다. 스냅샷에 든 이미지는 삭제·편집이 막혀 있다 | `version.py`, `export/base.py:13-19`, `image.py:104-130`, `preprocess.py:25-37` | 등록할 때 manifest 를 고정하면 "그 시점"이 지켜진다 |
| 버전 태그가 `count+1` 이라 동시 생성하면 유니크 제약 500 이 난다 | `version.py:14` | 데이터셋 행을 잠근다 |
| 작업이 실패하면 `BackgroundJob` 은 FAILED 인데 `ExportJob` 은 롤백되어 QUEUED 로 남는다. Export zip 은 트랜잭션 안에서 저장된다 | `job.py:72-86`, `export/__init__.py:17-38` | Task 2 |
| `attempt_count`·`next_retry_at` 은 어디서도 쓰지 않는다. DATA_MODEL·DEC-022 는 재시도가 있다고 적었다 | `job.py`, `DATA_MODEL.md:100`, `DECISIONS.md:117` | Task 2 가 `attempt_count` 를 쓰고 문서를 고친다 |
| 검사 접수에서 파일을 쓴 뒤 savepoint 나 요청 트랜잭션이 롤백되면 파일이 남는다. 실패 시 새 파일을 지우는 정리 패턴은 `item_creation.py:52-128` 하나뿐이다 | `vision/inspection.py:69-102`, `image.py:68-92` | Task 1 |
| `upload_images` 는 `files[:20]` 만 처리하고 21번째부터는 말없이 버린다 | `image.py:69` | Task 8 |
| MES `ApiModuleView` 의 처리: dispatch 에서 메뉴 권한을 보고, `api_execute` 는 `PermissionDenied` 를 403, 그 밖의 예외를 500 으로 바꾼다. **`Http404` 는 따로 받지 않아 500 이 된다.** 함수는 `context.gparam`·`context.posparam`(`Q` 는 JSON 으로 풀린다)·`context.request` 를 받는다. 메서드는 GET·POST 만 있다 | `app/views/__init__.py:75-239` | Task 4 기반 |
| MES `AjaxUtil.failureCallback` 은 응답 JSON 의 `message` 를 `Alert.alert('Error', message)` 로 보인다 | `assets/js/common.js:1351-1363` | 400·403·404 문구가 그대로 화면에 뜬다 |
| WeZonGrid 서버 모드: `props.dataMode:'server'`, `rowIdField` 필수, `remoteDataSource.loadRows(query, ctx) → Promise<{rows, totalRows}>`. 프로젝트에서 쓰는 화면은 아직 없다 | `wezongrid.js:23168-23330`, `25300` | Task 4 에서 공용 함수를 만들고 Task 5 에서 시범 적용한다 |
| 작업자는 `/api/data/items/` 때문에 `wm_data_item` 권한을 갖는다. 검사항목 목록을 시스템 관리로 옮기면 작업자에게 빈 폴더가 보인다 | `seed_demo.py:44`, `menus.py:79-118` | Task 6(빈 폴더), Task 11(작업자 권한 정리) |
| 메뉴 행은 `seed_initial` 의 `MENU_TREE` 를 `update_or_create` 로 맞춘다. `--admin-password` 를 빼면 관리자 계정은 건드리지 않는다 | `seed_initial.py:19-131` | 메뉴 이동에 마이그레이션이 필요 없다 |
| 이 결정은 STATUS §2-1("데이터 화면은 별도 셸")·UI_GUIDE §1·§8·DEC-014·AGENTS [2]("API 규약은 셋")를 바꾼다 | | DEC-028 을 새로 쓰고 문서를 고친다(Task 4·11) |

---

## 파일 구조

| 파일 | 책임 | Task |
|---|---|---|
| `domain/services/data/image.py` | 실패 시 새 파일 삭제(`delete_files`), 20개 초과 거절 | 1·8 |
| `domain/services/vision/inspection.py` | 접수 실패 시 새 파일 삭제 | 1 |
| `domain/services/data/job.py` | 고착 복구, 실패를 Export 에 맞춤, QUALITY 제거 | 2·3 |
| `domain/services/data/export/__init__.py` | zip 저장 뒤 실패하면 파일 삭제 | 2 |
| `configurations/settings.py`, `.env.example` | `WORKER_STALE_SECONDS` | 2 |
| `domain/services/data/version.py` | 등록 = manifest 고정 + Export 적재 | 3 |
| `domain/models/data.py`, `domain/migrations/0011_remove_quality.py` | 품질 테이블·`readiness`·`QUALITY` 제거 | 3 |
| `app/views/__init__.py` (`ApiModuleView.api_execute`) | `item` task 의 테넌트·POST 강제·`ItemApiError`·`Http404` | 4 |
| `app/views/item/__init__.py` | `ItemApiError`, `load_item`, `page_params`, `paged` | 4 |
| `app/views/item/{snapshot,item_admin,item_home,image,review,labeling}.py` | 화면별 API | 4·6~10 |
| `domain/gui.py` | `item/*` 메뉴 매핑, 화면 이름 | 4·6~10 |
| `app/static/assets/js/common.js` | `AjaxUtil.gridRemoteSource(url, buildParams)` | 4 |
| `app/static/data/annotation.js` | 주석 오버레이·미리보기 그리기(`data/common.js` 에서 옮김) | 8 |
| `app/templates/data/*.html` | 화면별 MES 전환 | 5~10 |
| `app/views/data/*_api.py`, `configurations/urls_data.py` | 화면마다 REST 경로 삭제. 작업 대기열 3경로만 남는다 | 3·6~11 |
| `domain/management/commands/seed_initial.py`, `app/views/system/menus.py` | 메뉴 이동, 빈 폴더 | 6 |
| `domain/management/commands/seed_demo.py` | 작업자 `wm_data_item` 권한 삭제 | 11 |
| `scripts/verify_*.py`, `scripts/capture_ui.py` | 화면 목록, 모달 케이스, 기준 캡처 | 5~11 |
| 문서 | 각 Task 끝 + Task 11 | |

---

# 단계 ① `fix/job-file-safety` — 운영 결함 2건 (우선순위 3)

### Task 1: 검사 접수·화면 업로드가 실패하면 새로 쓴 파일을 지운다

**Files:**
- Modify: `domain/services/data/image.py` (`upload_images`, 새 `delete_files`)
- Modify: `domain/services/vision/inspection.py:69-105` (`receive_capture`)
- Test: `tests/test_client_api.py` (새 `ReceiveRollbackFilesTest`), `tests/test_data_services.py` (새 `UploadRollbackFilesTest`)

**Interfaces:**
- Produces: `ImageService.delete_files(names: list[str]) -> None`
  - 빈 이름은 건너뛴다.
  - `default_storage.delete` 가 실패해도 `logger.warning` 만 남긴다. 원래 예외를 가리지 않기 위해서다.

- [ ] **Step 1: 실패 테스트 — 검사 접수** (`tests/test_client_api.py` 끝)

```python
class ReceiveRollbackFilesTest(ClientApiTestCase):
    """접수가 중간에 실패하면 DB 행과 함께 이미지·썸네일 파일도 남지 않는다."""

    def setUp(self):
        super().setUp()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def _files(self):
        return [p for p in Path(settings.MEDIA_ROOT).rglob('*') if p.is_file()]

    def test_검사_행_저장이_실패하면_파일을_지운다(self):
        from django.db import IntegrityError
        with patch.object(VisionInspection.objects, 'create', side_effect=IntegrityError('x')):
            response = self._submit()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self._files(), [])

    def test_추론_단계가_실패해도_파일을_지운다(self):
        from domain.services.vision.inspection import InspectionService
        with patch.object(InspectionService, '_run_inference', side_effect=RuntimeError('x')):
            response = self._submit()
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self._files(), [])
```

- [ ] **Step 2: 실패 테스트 — 화면 업로드** (`tests/test_data_services.py` 끝)

```python
class UploadRollbackFilesTest(DataServiceTestCase):
    def setUp(self):
        import tempfile
        from django.test import override_settings
        super().setUp()
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)

    def test_업로드_트랜잭션이_실패하면_파일을_지운다(self):
        from pathlib import Path
        from unittest.mock import patch
        from django.conf import settings
        from domain.services.data.audit import AuditService

        with patch.object(AuditService, 'record', side_effect=RuntimeError('x')):
            with self.assertRaises(RuntimeError), tenant_atomic(self.tenant):
                ImageService.upload_images(self.item, [make_image()], actor=self.worker)
        self.assertEqual([p for p in Path(settings.MEDIA_ROOT).rglob('*') if p.is_file()], [])
```

- [ ] **Step 3: RED 확인**

Run: `.venv/bin/python manage.py test tests.test_client_api.ReceiveRollbackFilesTest tests.test_data_services.UploadRollbackFilesTest --settings=configurations.test_settings`
Expected: 3건 FAIL — 파일 2개(이미지·썸네일)가 남는다.

- [ ] **Step 4: 구현 — `image.py`**

```python
import logging
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

    @staticmethod
    def delete_files(names):
        """롤백된 행이 남긴 파일을 지운다. 원래 예외를 가리지 않게 실패는 로그만 남긴다."""
        for name in names:
            if not name:
                continue
            try:
                default_storage.delete(name)
            except OSError:
                logger.warning("롤백 뒤 파일 삭제 실패: %s", name, exc_info=True)
```

`upload_images` 는 `with transaction.atomic():` 블록을 감싼다. `created` 는 payload 만 담아 파일 이름이 없으므로 이름을 따로 모은다.

```python
        written = []
        try:
            with transaction.atomic():
                for index, uploaded in enumerate(files[:20]):
                    ...                                  # 기존 본문 그대로
                    asset = ImageAsset.objects.create(...)
                    written += [asset.file.name, asset.thumbnail.name]
                    ...
                if created:
                    AuditService.record(...)
        except Exception:
            cls.delete_files(written)
            raise
```

- [ ] **Step 5: 구현 — `receive_capture`**

savepoint 부터 `_run_inference` 까지를 한 `try` 로 감싼다. 바깥 요청 트랜잭션(`ClientApiView.dispatch` 의 `tenant_atomic`)이 롤백되면 행도 사라지므로, 추론 단계 실패도 같은 정리 대상이다.

```python
        written = []
        try:
            try:
                with transaction.atomic():
                    result = ImageService.upload_images(...)          # 기존 그대로
                    if result['rejected']:
                        raise ValueError(...)
                    asset = (...).first()
                    written = [asset.file.name, asset.thumbnail.name] if asset else []
                    inspection = VisionInspection.objects.create(...)
            except IntegrityError:
                ImageService.delete_files(written)
                winner = VisionInspection.objects.filter(request_id=request_id).first()
                if winner is None:
                    raise
                return self._owned_retry(winner, client), False
            self._run_inference(inspection, item, image_bytes)
        except Exception:
            ImageService.delete_files(written)
            raise
        return inspection, True
```

`IntegrityError` 다음 `raise` 경로에서는 파일을 두 번 지우게 된다. 없는 파일을 지워도 `default_storage.delete` 는 조용하므로 그대로 둔다.

- [ ] **Step 6: GREEN 확인**

Run: Step 3 명령. Expected: 3건 OK
Run: `.venv/bin/python manage.py test tests --settings=configurations.test_settings`. Expected: 전부 OK

- [ ] **Step 7: 커밋**

```bash
git add domain/services/data/image.py domain/services/vision/inspection.py tests/test_client_api.py tests/test_data_services.py
git commit -m "fix: 검사 접수·업로드가 롤백되면 새로 쓴 이미지 파일을 지운다"
```

### Task 2: 워커 고착 작업을 되살리고 실패 상태를 Export 에 맞춘다

**Files:**
- Modify: `domain/services/data/job.py` (`run_pending`, 새 `requeue_stale`·`_fail_target`, `_run_claimed`)
- Modify: `domain/services/data/export/__init__.py` (`run`)
- Modify: `configurations/settings.py`, `.env.example`
- Test: `tests/test_jobs.py` (신규 — 작업 큐 단위 테스트는 지금 없다, STATUS §3-2)

**Interfaces:**
- Consumes: `JobService.enqueue_export(dataset_version, actor, export_format)` (기존)
- Produces:
  - `JobService.MAX_ATTEMPTS = 3`
  - `JobService.requeue_stale(tenant) -> int` — 처리한 건수를 돌려준다. `tenant_atomic` 안에서 부른다.
  - `settings.WORKER_STALE_SECONDS: int`

- [ ] **Step 1: 실패 테스트** (`tests/test_jobs.py`)

```python
"""작업 큐(JobService) — 워커가 죽거나 작업이 실패했을 때의 상태."""
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from domain.models.data import BackgroundJob, DatasetVersion, ExportJob, ImageAsset, InspectionItem
from domain.services.data.audit import AuditService
from domain.services.data.export import ExportService
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.job import JobService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_data_services import make_image


@override_settings(WORKER_STALE_SECONDS=60)
class JobRecoveryTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        self.user = User.objects.create_user('job-user', password='x')
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        with tenant_atomic(self.tenant):
            item = InspectionItem.objects.create(tenant=self.tenant, code='JOB', name='작업',
                                                 task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            ImageService.upload_images(item, [make_image()], actor=self.user)
            ImageAsset.objects.for_tenant(self.tenant).update(label_status=ImageAsset.LabelStatus.APPROVED)
            image = ImageAsset.objects.for_tenant(self.tenant).get()
            dataset = ItemService.get_or_create_upload_dataset(item)
            version = DatasetVersion.objects.create(
                tenant=self.tenant, dataset=dataset, version_tag='v1.0',
                manifest={'images': [{'id': image.id, 'sha256': image.sha256, 'width': image.width,
                                      'height': image.height, 'annotations': []}], 'image_count': 1})
            self.job, self.export = JobService.enqueue_export(version, self.user)

    def _stale(self, attempts):
        with tenant_atomic(self.tenant):
            BackgroundJob.objects.filter(pk=self.job.pk).update(
                status=BackgroundJob.Status.RUNNING, attempt_count=attempts,
                started_at=timezone.now() - timedelta(seconds=120))

    def _reload(self):
        with tenant_atomic(self.tenant):
            return BackgroundJob.objects.get(pk=self.job.pk), ExportJob.objects.get(pk=self.export.pk)

    def test_오래된_RUNNING_은_다시_대기열로_간다(self):
        self._stale(attempts=0)
        with tenant_atomic(self.tenant):
            self.assertEqual(JobService.requeue_stale(self.tenant), 1)
        job, _ = self._reload()
        self.assertEqual((job.status, job.attempt_count), (BackgroundJob.Status.QUEUED, 1))

    def test_최근_RUNNING_은_건드리지_않는다(self):
        with tenant_atomic(self.tenant):
            BackgroundJob.objects.filter(pk=self.job.pk).update(
                status=BackgroundJob.Status.RUNNING, started_at=timezone.now())
            self.assertEqual(JobService.requeue_stale(self.tenant), 0)

    def test_세_번째_고착이면_실패로_끝내고_Export_도_실패다(self):
        self._stale(attempts=JobService.MAX_ATTEMPTS - 1)
        with tenant_atomic(self.tenant):
            JobService.requeue_stale(self.tenant)
        job, export = self._reload()
        self.assertEqual(job.status, BackgroundJob.Status.FAILED)
        self.assertEqual(export.status, ExportJob.Status.FAILED)
        self.assertIn('워커가 중단', export.error_message)

    def test_작업이_예외로_실패하면_Export_도_실패다(self):
        with patch.object(ExportService, 'run', side_effect=RuntimeError('디스크 가득')):
            JobService.run_pending(limit=1)
        job, export = self._reload()
        self.assertEqual((job.status, export.status), (BackgroundJob.Status.FAILED, ExportJob.Status.FAILED))

    def test_run_pending_은_고착_작업을_다시_집는다(self):
        self._stale(attempts=0)
        self.assertEqual([j.pk for j in JobService.run_pending(limit=5)], [self.job.pk])

    def test_zip_저장_뒤_실패하면_zip_을_지운다(self):
        before = {p for p in Path(settings.MEDIA_ROOT).rglob('*.zip')}
        with patch.object(AuditService, 'record', side_effect=RuntimeError('x')):
            JobService.run_pending(limit=1)
        self.assertEqual({p for p in Path(settings.MEDIA_ROOT).rglob('*.zip')}, before)
```

이미지 manifest 형식은 `version.py` 의 `manifest_images` 항목과 같아야 한다. exporter 가 다른 키를 요구하면 `DatasetVersionService.create_snapshot` 으로 version 을 만든다. 단계 ①에서는 `readiness` 가 아직 있다. 기본값이 있어 생략할 수 있다.

- [ ] **Step 2: RED 확인**

Run: `.venv/bin/python manage.py test tests.test_jobs --settings=configurations.test_settings`
Expected: FAIL. 실패 내용은 세 가지다.
- `requeue_stale`·`MAX_ATTEMPTS` 가 없어 AttributeError
- Export 상태가 QUEUED 로 남는다(FAILED 여야 한다)
- zip 이 남는다

- [ ] **Step 3: 구현 — 설정**

`configurations/settings.py` 의 `LOG_RETENTION_DAYS` 옆:

```python
# RUNNING 으로 이만큼(초) 지난 작업은 워커가 죽은 것으로 보고 다시 대기열에 넣는다.
WORKER_STALE_SECONDS = env_int('WORKER_STALE_SECONDS', 3600)
```

`.env.example` 끝:

```
# 워커가 강제 종료돼 RUNNING 으로 남은 작업을 다시 집기까지 기다리는 시간(초).
# 가장 오래 걸리는 Export 보다 길게 둔다. 짧으면 정상 작업이 두 번 돈다.
WORKER_STALE_SECONDS=3600
```

- [ ] **Step 4: 구현 — `job.py`**

```python
from datetime import timedelta
from django.conf import settings

STALE_MESSAGE = "워커가 중단되어 작업을 마치지 못했습니다."


class JobService:
    MAX_ATTEMPTS = 3

    @classmethod
    def run_pending(cls, limit=20):
        processed = []
        for tenant in Tenant.objects.filter(status=Tenant.Status.ACTIVE):
            with tenant_atomic(tenant):
                cls.requeue_stale(tenant)
            while len(processed) < limit:
                ...                                   # 기존 그대로

    @classmethod
    def requeue_stale(cls, tenant):
        """오래된 RUNNING 을 되살린다. MAX_ATTEMPTS 번째면 실패로 끝낸다.

        ponytail: 시간 기준이라 WORKER_STALE_SECONDS 보다 오래 도는 정상 작업은 두 번 돈다.
        그런 작업이 생기면 실행 중 heartbeat(started_at 갱신)를 더한다.
        """
        cutoff = timezone.now() - timedelta(seconds=settings.WORKER_STALE_SECONDS)
        stale = list(BackgroundJob.objects.for_tenant(tenant)
                     .filter(status=BackgroundJob.Status.RUNNING, started_at__lt=cutoff))
        for job in stale:
            job.attempt_count += 1
            if job.attempt_count >= cls.MAX_ATTEMPTS:
                job.status, job.error_message, job.completed_at = BackgroundJob.Status.FAILED, STALE_MESSAGE, timezone.now()
                cls._fail_target(tenant, job, STALE_MESSAGE)
            else:
                job.status, job.started_at = BackgroundJob.Status.QUEUED, None
            job.save(update_fields=["status", "attempt_count", "started_at", "error_message", "completed_at"])
        return len(stale)

    @classmethod
    def _fail_target(cls, tenant, job, message):
        """본문이 롤백돼 QUEUED 로 남은 ExportJob 을 실패로 맞춘다. 화면은 ExportJob 을 본다."""
        export_job_id = job.payload.get("export_job_id")
        if export_job_id:
            ExportJob.objects.for_tenant(tenant).filter(pk=export_job_id).update(
                status=ExportJob.Status.FAILED, error_message=message[:255])
```

`_run_claimed` 의 `except` 블록 안에서 `job.save(...)` 다음에 `cls._fail_target(tenant, job, str(exc))` 를 부른다. 같은 `tenant_atomic` 안이다.

- [ ] **Step 5: 구현 — `export/__init__.py`**

```python
        export_job.file.save(..., save=False)
        try:
            ...  # 기존 l.33-38 (COMPLETED 저장 · 데이터셋 EXPORTED · 감사 기록)
        except Exception:
            # 파일은 저장소에 이미 써졌다. 행이 롤백되면 가리킬 곳이 없다.
            export_job.file.delete(save=False)
            raise
        return export_job
```

- [ ] **Step 6: GREEN 확인**

Run: `.venv/bin/python manage.py test tests.test_jobs --settings=configurations.test_settings`. Expected: OK
Run: 전체 단위 테스트. Expected: OK

- [ ] **Step 7: 문서**

- `docs/ARCHITECTURE.md:328-332` 작업 큐 절: `WORKER_STALE_SECONDS`·`MAX_ATTEMPTS` 동작과 한계(정상 작업이 두 번 돌 수 있다)
- `docs/DATA_MODEL.md:100`, `docs/DECISIONS.md:117`(DEC-022): `attempt_count` 는 고착 복구 횟수이고 `next_retry_at` 은 쓰지 않는다
- `docs/DEPLOYMENT.md` `.env` 표: `WORKER_STALE_SECONDS`
- `docs/STATUS.md`: §3-5 의 두 행 삭제, 우선순위 3 완료, 단위 테스트 건수

- [ ] **Step 8: 커밋 → 단계 ① 병합**

```bash
git add domain/services/data/job.py domain/services/data/export/__init__.py configurations/settings.py .env.example tests/test_jobs.py docs/
git commit -m "fix: 워커가 죽어 RUNNING 으로 남은 작업을 되살리고 실패를 Export 상태에 맞춘다"
```

서버를 띄우고 `.venv/bin/python -m pytest tests/e2e/test_write_paths.py -q` 가 통과하면 main 에 병합한다.

---

# 단계 ② `feat/snapshot-job` — 품질 점검 제거 · MES API 기반 · 스냅샷 화면

### Task 3: 품질 점검을 없애고 스냅샷 등록이 Export 작업을 적재한다 (서비스·모델)

**Files:**
- Modify: `domain/services/data/version.py`, `domain/services/data/job.py`, `domain/models/data.py`, `domain/services/data/item_platform.py:142`(홈 스냅샷 배지 → Export 상태)
- Modify (문구·주석): `run_worker.py` help, `domain/gui.py:52`, `seed_demo.py:40`
- Delete:
  - `domain/services/data/quality.py`
  - `tests/test_readiness_labels.py`
  - REST 스냅샷 API — `app/views/data/snapshot_api.py`, `urls_data.py` 의 `quality-runs`·`dataset-versions`·`exports` 경로, `DATA_API_MENUS` 의 같은 항목. 새 API 는 Task 4 이고 같은 단계에서 병합한다.
- Create: `domain/migrations/0011_remove_quality.py`
- Test: `tests/test_snapshot_job.py`(신규, 서비스 단위)

**Interfaces:**
- Produces:
  - `DatasetVersionService.create_snapshot(dataset, actor=None, export_format=None) -> tuple[DatasetVersion, ExportJob]`
  - `version.NO_APPROVED_MESSAGE = "검수 승인된 이미지가 없어 스냅샷을 만들 수 없습니다."`
  - `version.UNSUPPORTED_FORMAT_MESSAGE = "이 검사항목 유형에서 지원하지 않는 Export 포맷입니다."`
  - 두 경우 모두 `ValueError(<위 문구>)` 를 던진다.

- [ ] **Step 1: 실패 테스트** (`tests/test_snapshot_job.py`)

```python
"""스냅샷 등록 = 그 시점 manifest 고정 + Export 작업 적재."""
import tempfile

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from domain.models.data import BackgroundJob, DatasetVersion, ExportJob, ImageAsset, InspectionItem
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.services.data.version import NO_APPROVED_MESSAGE, DatasetVersionService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_data_services import make_image


class SnapshotJobTest(TestCase):
    def setUp(self):
        reset_tenant_cache()
        self.tenant = current_tenant()
        self.user = User.objects.create_superuser('snap-admin', password='x')
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        with tenant_atomic(self.tenant):
            self.item = InspectionItem.objects.create(tenant=self.tenant, code='SNAP', name='스냅샷',
                                                      task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            self.dataset = ItemService.get_or_create_upload_dataset(self.item)

    def approve_one(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image()], actor=self.user)
            ImageAsset.objects.for_tenant(self.tenant).update(label_status=ImageAsset.LabelStatus.APPROVED)

    def test_등록하면_manifest_를_고정하고_Export_작업을_적재한다(self):
        self.approve_one()
        with tenant_atomic(self.tenant):
            version, export = DatasetVersionService.create_snapshot(self.dataset, self.user, 'YOLO')
            self.assertEqual(version.manifest['image_count'], 1)
            self.assertEqual((export.format, export.status), ('YOLO', ExportJob.Status.QUEUED))
            self.assertTrue(BackgroundJob.objects.for_tenant(self.tenant)
                            .filter(payload__export_job_id=export.id).exists())

    def test_형식을_비우면_유형의_첫_형식이다(self):
        self.approve_one()
        with tenant_atomic(self.tenant):
            _, export = DatasetVersionService.create_snapshot(self.dataset, self.user)
        self.assertEqual(export.format, 'COCO')

    def test_승인_이미지가_없으면_만들지_않는다(self):
        with tenant_atomic(self.tenant):
            with self.assertRaisesMessage(ValueError, NO_APPROVED_MESSAGE):
                DatasetVersionService.create_snapshot(self.dataset, self.user)
            self.assertFalse(DatasetVersion.objects.for_tenant(self.tenant).exists())

    def test_지원하지_않는_형식은_거절한다(self):
        self.approve_one()
        with tenant_atomic(self.tenant), self.assertRaises(ValueError):
            DatasetVersionService.create_snapshot(self.dataset, self.user, 'MVTEC')
```

`'COCO'` 는 `registry.ITEM_EXPORT_FORMATS[OBJECT_DETECTION][0]` 이라고 가정했다. `registry.py:9-29` 를 읽어 실제 첫 값으로 맞춘다. `'MVTEC'` 도 OBJECT_DETECTION 이 지원하지 않는 형식인지 같은 파일에서 확인한다.

- [ ] **Step 2: RED 확인**

Run: `.venv/bin/python manage.py test tests.test_snapshot_job --settings=configurations.test_settings`
Expected: FAIL. 실패 내용은 두 가지다.
- import 오류(`NO_APPROVED_MESSAGE` 가 없다)
- 반환 형태가 다르다(튜플이 아니다)

- [ ] **Step 3: 구현 — `version.py`**

```python
"""스냅샷: 등록 시점의 검수 승인 이미지를 manifest 로 고정하고 zip 생성은 워커에 맡긴다."""
from django.db import transaction
from domain.models.data import Dataset, DatasetVersion, ImageAsset
from domain.services.data.audit import AuditService
from domain.services.data.annotation import AnnotationService
from domain.services.data.export import registry

NO_APPROVED_MESSAGE = "검수 승인된 이미지가 없어 스냅샷을 만들 수 없습니다."
UNSUPPORTED_FORMAT_MESSAGE = "이 검사항목 유형에서 지원하지 않는 Export 포맷입니다."


class DatasetVersionService:
    @classmethod
    def create_snapshot(cls, dataset, actor=None, export_format=None):
        from domain.services.data.job import JobService  # job → export 순환 import 회피

        tenant = dataset.tenant
        task_type = dataset.item.task_type
        supported = registry.ITEM_EXPORT_FORMATS.get(task_type, [])
        export_format = export_format or (supported[0] if supported else None)
        if export_format not in supported:
            raise ValueError(UNSUPPORTED_FORMAT_MESSAGE)
        with transaction.atomic():
            # 버전 태그를 count+1 로 정하므로 같은 데이터셋의 동시 등록을 줄 세운다.
            Dataset.objects.select_for_update().filter(pk=dataset.pk).first()
            sequence = ...                    # 기존 l.14 그대로
            ...                               # manifest_images·excluded_image_count 기존 그대로
            if not manifest_images:
                raise ValueError(NO_APPROVED_MESSAGE)
            version = DatasetVersion.objects.create(
                tenant=tenant, dataset=dataset, version_tag=f"v{sequence}.0",
                manifest={"dataset_id": dataset.id, "images": manifest_images,
                          "image_count": len(manifest_images), "excluded_image_count": excluded_image_count},
                created_by=actor)
            dataset.status = dataset.Status.CURATED
            dataset.save(update_fields=["status", "updated_at"])
            AuditService.record(...)          # 기존 그대로
            _, export_job = JobService.enqueue_export(version, actor, export_format=export_format)
            return version, export_job
```

- [ ] **Step 4: 구현 — 모델·마이그레이션**

`domain/models/data.py` 에서 지우는 것:
- `QualityRun`·`QualityFinding` 클래스
- `DatasetVersion.readiness`
- `BackgroundJob.JobType.QUALITY`

`job.py` 에서 `enqueue_quality`·QUALITY 분기·`quality` import 를 지운다. `quality.py` 와 `tests/test_readiness_labels.py` 를 지운다.

```bash
.venv/bin/python manage.py makemigrations domain -n remove_quality
```

생성된 `0011_remove_quality.py` 의 `operations` **맨 앞**에 남은 품질 작업 행 삭제를 넣는다.

```python
def delete_quality_jobs(apps, schema_editor):
    # RLS(FORCE) 테이블이라 테넌트 컨텍스트 없이 지우면 0건이다. FORCE 는 소유자에게도
    # 적용된다. 정책 조건은 0007 의 current_setting('app.tenant_id') — tenancy.py:53 과 같은 키.
    BackgroundJob = apps.get_model('domain', 'BackgroundJob')
    is_pg = schema_editor.connection.vendor == 'postgresql'
    for tenant_id in apps.get_model('domain', 'Tenant').objects.values_list('id', flat=True):
        if is_pg:
            with schema_editor.connection.cursor() as cursor:
                cursor.execute("select set_config('app.tenant_id', %s, true)", [str(tenant_id)])
        BackgroundJob.objects.filter(job_type='QUALITY').delete()

# operations = [migrations.RunPython(delete_quality_jobs, migrations.RunPython.noop), ...자동 생성분...]
```

- 테이블을 지우면 그 정책도 함께 사라진다. 0007 은 고치지 않는다.
- 확인 순서는 다음과 같다.
  1. `.venv/bin/python manage.py migrate --plan`
  2. 개발 DB `migrate`
  3. `psql` 로 `select count(*) from pg_policies where tablename like 'vision_data_quality%'` 가 0 인지 본다.

- [ ] **Step 5: 구현 — 부수 코드**

- REST 스냅샷 API 삭제(Files 참조). `verify_permission_map.py` 가 `urls_data` 와 `DATA_API_MENUS` 를 함께 보므로 둘을 같이 지운다.
- `item_platform.py:142`: `readiness_label` 대신 그 버전의 최신 ExportJob `status_label` 을 쓴다. `app/templates/data/item.html:228-229` 배지 문구도 맞춘다(Task 7 전까지 깨지지 않게).
- `activity_query.py:15` 의 `QUALITY_COMPLETED` 라벨은 **남긴다**. 과거 활동 기록을 표시하는 데 쓴다.
- `tests/test_seed_demo_permissions.py:37-45` 의 quality-runs 검사는 지우고, 같은 의미의 검사를 Task 4 에서 새 API 로 다시 쓴다.

- [ ] **Step 6: GREEN 확인**

Run: `.venv/bin/python manage.py test tests --settings=configurations.test_settings`. Expected: OK
Run: `.venv/bin/python scripts/verify_permission_map.py`. Expected: PASS
Run: `grep -rn "QualityRun\|quality_run\|quality-runs\|readiness" app domain configurations tests --include=*.py --include=*.html --include=*.js`
Expected: 마이그레이션 파일과 `activity_query.py` 말고 0건이다. 예외가 하나 있다. 단계 ② 안에서는 `snapshot.html` 이 Task 5 에서 다시 쓰이므로 남아 있어도 된다.

- [ ] **Step 7: 커밋**

```bash
git add domain/ app/views/data/ configurations/urls_data.py tests/ app/templates/data/item.html
git status    # 삭제 3파일·마이그레이션 1파일·수정 파일만 있는지 확인
git commit -m "feat: 품질 점검을 없애고 스냅샷 등록이 그 시점 데이터셋 zip 작업을 적재한다"
```

### Task 4: `item` task — MES API 기반과 `/api/item/snapshot`

**Files:**
- Modify: `app/views/__init__.py` (`ApiModuleView.api_execute`)
- Create: `app/views/item/__init__.py`, `app/views/item/snapshot.py`
- Modify: `domain/gui.py` (`m['item/snapshot'] = ['wm_data_snapshot']`)
- Modify: `app/static/assets/js/common.js` (`AjaxUtil.gridRemoteSource`)
- Modify: `docs/DECISIONS.md`(DEC-028, DEC-014 갱신), `docs/UI_GUIDE.md` §1·§8, `docs/STATUS.md` §2-1, `AGENTS.md` [2]
- Test: `tests/test_item_api.py`(신규), `tests/test_seed_demo_permissions.py`

**Interfaces:**
- Consumes: `DatasetVersionService.create_snapshot`, `NO_APPROVED_MESSAGE`·`UNSUPPORTED_FORMAT_MESSAGE`(Task 3), `JobService.enqueue_export`, `AuthorizationService.require`
- Produces (Task 6~10 이 쓴다):
  - `app.views.item.ItemApiError(message)` — dispatch 가 400 `{"success": false, "message"}` 로 바꾸고 롤백한다
  - `app.views.item.load_item(context, action) -> InspectionItem` — `gparam`·`posparam` 의 `item_id` 로 읽는다. 없으면 `Http404`, 권한이 없으면 `PermissionDenied` 다
  - `app.views.item.page_params(gparam, default_size=20) -> tuple[int, int]` — `(page, page_size)`, 크기는 최대 100
  - `app.views.item.paged(queryset, gparam, serialize, default_size=20) -> dict` — `{"rows": [...], "totalRows": n}`
  - 모듈 상수 `READ_ACTIONS: frozenset[str]`
  - 화면 JS `AjaxUtil.gridRemoteSource(url, buildParams) -> {loadRows(query): Promise<{rows,totalRows}>}`
  - `/api/item/snapshot` 의 action 은 아래 표와 같다.

| action | 메서드 | 입력 | 응답 |
|---|---|---|---|
| `list` | GET | `item_id`, `q`, `page`, `page_size` | `{"rows":[{id, version_tag, created_at, image_count, excluded_image_count, export:{id, format, format_label, status, status_label, file_url, error_message}|null}], "totalRows", "item":{id,name,task_type}, "can_create", "formats":[{value,label}]}` |
| `detail` | GET | `item_id`, `version_id` | `{"version":{…list 행과 같다}, "analysis": _analyze_manifest(...)}` |
| `create` | POST | `item_id`, `format` | `{"success": true, "message": "스냅샷을 등록했습니다. 완료되면 목록에서 받을 수 있습니다.", "version_id", "export_job_id"}` |
| `rebuild` | POST | `item_id`, `version_id` | 그 버전의 최신 ExportJob 과 같은 형식으로 다시 적재. `{"success": true, "message": "다시 만들기를 등록했습니다."}` |

권한은 다음과 같다.
- `list`·`detail`: `item.read`
- `create`: `dataset.snapshot.create`
- `rebuild`: `dataset.export`

- [ ] **Step 1: 실패 테스트** (`tests/test_item_api.py`)

```python
"""`/api/item/*` — 데이터 화면의 MES API. 테넌트·POST 강제·오류 응답·스냅샷."""
import tempfile

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from domain.models.data import (DatasetVersion, ImageAsset, InspectionItem, ItemAssignment)
from domain.models.system import SystemOption
from domain.models.user import UserGroup, UserGroupMenu
from domain.services.data.image import ImageService
from domain.services.data.item import ItemService
from domain.tenancy import current_tenant, reset_tenant_cache, tenant_atomic
from tests.test_data_services import make_image

PASSWORD = 'correct-horse-battery-staple'
AJAX = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'}


@override_settings(API_AUTHZ_MODE='enforce')
class ItemApiTestCase(TestCase):
    def setUp(self):
        cache.clear()
        reset_tenant_cache()
        self.tenant = current_tenant()
        SystemOption.objects.create(Code='LOGO_TITLE', Value='테스트')
        media = tempfile.TemporaryDirectory()
        self.addCleanup(media.cleanup)
        override = override_settings(MEDIA_ROOT=media.name)
        override.enable()
        self.addCleanup(override.disable)
        group = UserGroup.objects.create(Code='worker', Name='작업자')
        UserGroupMenu.objects.create(UserGroup=group, MenuCode='wm_data_snapshot', AuthCode='RW')
        self.manager = self._user('item-manager', group)
        self.worker = self._user('item-worker', group)
        with tenant_atomic(self.tenant):
            self.item = InspectionItem.objects.create(tenant=self.tenant, code='API', name='API 검사',
                                                      task_type=InspectionItem.TaskType.OBJECT_DETECTION)
            ItemAssignment.objects.create(tenant=self.tenant, item=self.item, user=self.manager,
                                          role=ItemAssignment.Role.ITEM_MANAGER)
            ItemAssignment.objects.create(tenant=self.tenant, item=self.item, user=self.worker,
                                          role=ItemAssignment.Role.WORKER)

    def _user(self, name, group):
        user = User.objects.create_user(name, password=PASSWORD)
        user.userprofile.UserGroup = group
        user.userprofile.save()
        return user

    def http(self, user):
        client = Client()
        client.login(username=user.username, password=PASSWORD)
        return client

    def approve_one(self):
        with tenant_atomic(self.tenant):
            ImageService.upload_images(self.item, [make_image()], actor=self.manager)
            ImageAsset.objects.for_tenant(self.tenant).update(label_status=ImageAsset.LabelStatus.APPROVED)


class ItemDispatchTest(ItemApiTestCase):
    def test_변경_action_은_GET_으로_부르면_405_이고_아무것도_만들지_않는다(self):
        self.approve_one()
        response = self.http(self.manager).get('/api/item/snapshot',
                                               {'action': 'create', 'item_id': self.item.id}, **AJAX)
        self.assertEqual(response.status_code, 405)
        with tenant_atomic(self.tenant):
            self.assertFalse(DatasetVersion.objects.for_tenant(self.tenant).exists())

    def test_조회는_테넌트_컨텍스트_안에서_돈다(self):
        self.approve_one()
        self.http(self.manager).post(f'/api/item/snapshot?action=create',
                                     {'item_id': self.item.id}, **AJAX)
        body = self.http(self.manager).get('/api/item/snapshot',
                                           {'action': 'list', 'item_id': self.item.id}, **AJAX).json()
        self.assertEqual(body['totalRows'], 1)   # RLS 밖이면 0 이다

    def test_업무_오류는_400_과_문구이고_롤백한다(self):
        response = self.http(self.manager).post('/api/item/snapshot?action=create',
                                                {'item_id': self.item.id}, **AJAX)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {'success': False,
                                           'message': '검수 승인된 이미지가 없어 스냅샷을 만들 수 없습니다.'})

    def test_없는_검사항목은_404(self):
        response = self.http(self.manager).get('/api/item/snapshot',
                                               {'action': 'list', 'item_id': 999999}, **AJAX)
        self.assertEqual(response.status_code, 404)

    def test_메뉴_권한이_없으면_403(self):
        outsider = User.objects.create_user('no-menu', password=PASSWORD)
        response = self.http(outsider).get('/api/item/snapshot',
                                           {'action': 'list', 'item_id': self.item.id}, **AJAX)
        self.assertEqual(response.status_code, 403)


class SnapshotApiTest(ItemApiTestCase):
    def test_작업자는_스냅샷을_등록할_수_없다(self):
        self.approve_one()
        response = self.http(self.worker).post('/api/item/snapshot?action=create',
                                               {'item_id': self.item.id}, **AJAX)
        self.assertEqual(response.status_code, 403)

    def test_목록은_버전마다_Export_상태를_준다(self):
        self.approve_one()
        self.http(self.manager).post('/api/item/snapshot?action=create',
                                     {'item_id': self.item.id, 'format': 'YOLO'}, **AJAX)
        body = self.http(self.manager).get('/api/item/snapshot',
                                           {'action': 'list', 'item_id': self.item.id}, **AJAX).json()
        row = body['rows'][0]
        self.assertEqual((row['export']['format'], row['export']['status']), ('YOLO', 'QUEUED'))
        self.assertNotIn('readiness', row)
        self.assertTrue(body['can_create'])
```

`tests/test_seed_demo_permissions.py` 의 지운 quality-runs 검사 자리에 같은 의미의 검사를 다시 쓴다. 관리자의 `POST /api/item/snapshot?action=create` 는 400 이어야 한다(메뉴·검사항목 권한은 통과했고 승인 이미지가 없다). 작업자는 403 이어야 한다.

- [ ] **Step 2: RED 확인**

Run: `.venv/bin/python manage.py test tests.test_item_api tests.test_seed_demo_permissions --settings=configurations.test_settings`
Expected: FAIL — 매핑이 없어 403 이 나거나(enforce), 모듈이 없어 404 가 난다.

- [ ] **Step 3: 구현 — `app/views/item/__init__.py`**

```python
"""데이터 관리 화면의 MES API(`/api/item/<view>?action=...`).

`ApiModuleView` 가 이 task 를 특별히 다룬다:
- 요청 전체를 `tenant_atomic()` 으로 감싼다(RLS — 밖에서 읽으면 0건).
- 모듈의 `READ_ACTIONS` 에 없는 action 은 POST 로만 받는다(MES 는 메서드로 R/W 를 판정한다).
- `ItemApiError` 는 400 `{"success": false, "message"}` 로 바꾸고 롤백한다.
"""
from django.http import Http404

from domain.models.data import InspectionItem
from domain.services.data.authorization import AuthorizationService
from domain.services.data.item import ItemService


class ItemApiError(Exception):
    """화면에 그대로 보일 업무 오류. 문구는 ~합니다 체."""


def _param(context, key):
    return context.posparam.get(key) or context.gparam.get(key)


def load_item(context, action):
    try:
        item = ItemService.get_item(context.request.tenant, _param(context, 'item_id'))
    except (InspectionItem.DoesNotExist, ValueError, TypeError) as exc:
        raise Http404('검사항목을 찾을 수 없습니다.') from exc
    AuthorizationService.require(context.request, action, item=item)
    return item


def page_params(gparam, default_size=20):
    try:
        page = max(int(gparam.get('page') or 1), 1)
        size = min(max(int(gparam.get('page_size') or default_size), 1), 100)
    except ValueError:
        page, size = 1, default_size
    return page, size


def paged(queryset, gparam, serialize, default_size=20):
    page, size = page_params(gparam, default_size)
    start = (page - 1) * size
    return {'rows': [serialize(row) for row in queryset[start:start + size]],
            'totalRows': queryset.count()}
```

`ItemService.get_item(tenant, item_id)` 의 실제 시그니처와 예외는 `domain/services/data/item.py` 를 읽고 맞춘다.

- [ ] **Step 4: 구현 — `ApiModuleView.api_execute`**

```python
from django.http import Http404, JsonResponse
from domain.tenancy import current_tenant, tenant_atomic

TENANT_TASKS = {'item'}   # app/views/item/__init__.py 참조

    def api_execute(self, request, *args, **kwargs):
        task_name = kwargs.get('task_name', None)
        view_name = kwargs.get('view_name', None)
        data = None
        try:
            module = importlib.import_module('app.views.{}.{}'.format(task_name, view_name))
            func = getattr(module, view_name, None)
            if not func:
                ...  # 기존 404 그대로
            if task_name in TENANT_TASKS:
                return self._execute_item(request, module, func)
            data = func(self)
        except PermissionDenied:
            ...  # 기존 그대로
        except Exception as ex:
            ...  # 기존 그대로
        return self.make_json_response(data)

    def _execute_item(self, request, module, func):
        from app.views.item import ItemApiError

        action = self.gparam.get('action', '')
        if action not in getattr(module, 'READ_ACTIONS', frozenset()) and request.method != 'POST':
            return JsonResponse({'success': False, 'message': 'POST 로 요청해야 하는 기능입니다.'}, status=405)
        request.tenant = current_tenant()
        try:
            with tenant_atomic(request.tenant):
                return self.make_json_response(func(self))
        except ItemApiError as exc:
            return JsonResponse({'success': False, 'message': str(exc)}, status=400,
                                json_dumps_params={'ensure_ascii': False})
        except Http404 as exc:
            return self.response404(request, str(exc) or '대상을 찾을 수 없습니다.')
```

`PermissionDenied` 와 그 밖의 예외는 바깥 `except` 가 지금처럼 403·500 으로 바꾼다. `tenant_atomic` 을 빠져나가며 이미 롤백된 상태다. `ImportError`(모듈 없음)는 지금 동작 그대로 둔다.

- [ ] **Step 5: 구현 — `app/views/item/snapshot.py`**

```python
"""스냅샷 관리(`wm_data_snapshot`). 등록하면 그 시점 manifest 를 고정하고 워커가 zip 을 만든다."""
from collections import Counter

from django.urls import reverse

from app.views.item import ItemApiError, load_item, paged
from domain.models.data import Dataset, DatasetVersion, ExportJob
from domain.services.data.export import registry
from domain.services.data.item_access import ItemAccessService
from domain.services.data.job import JobService
from domain.services.data.version import DatasetVersionService

READ_ACTIONS = frozenset({'list', 'detail'})


def snapshot(context):
    """api/item/snapshot"""
    action = context.gparam.get('action', 'list')
    handler = {'list': _list, 'detail': _detail, 'create': _create, 'rebuild': _rebuild}.get(action)
    if handler is None:
        raise ItemApiError('지원하지 않는 기능입니다.')
    return handler(context)
```

함수별 내용은 다음과 같다. 옮겨 올 원본은 Task 3 에서 지운 `app/views/data/snapshot_api.py` 이므로 `git show HEAD~1:app/views/data/snapshot_api.py` 로 본다.

- `_list`
  - `load_item(context, 'item.read')` 로 검사항목을 읽는다.
  - 데이터셋은 `Dataset.objects.for_tenant(...).filter(item=item).order_by('-updated_at', '-id').first()` 이다.
  - 버전 목록에 `q`(version_tag icontains)를 걸고 `paged(..., serialize_version)` 로 내보낸다.
  - 최신 Export 는 페이지의 버전 id 로 `ExportJob` 을 한 번만 읽어(`dataset_version_id__in`) 버전마다 최신 하나를 고른다.
  - `file_url` 은 `reverse('private-export', args=[job.id])` 이다(파일이 있을 때만).
  - `item`·`can_create`(`ItemAccessService.can_manage_item`)·`formats`(`registry.ITEM_EXPORT_FORMATS`)를 함께 준다.
- `_detail`: 원본의 `_analyze_manifest`·`_label_name` 을 그대로 옮겨 쓴다.
- `_create`
  - `load_item(context, 'dataset.snapshot.create')` 다음 `ItemService.get_or_create_upload_dataset(item)` 을 부른다.
  - `try: create_snapshot(...) except ValueError as exc: raise ItemApiError(str(exc))` — 이 두 문구만 사용자 문구다.
- `_rebuild`
  - `load_item(context, 'dataset.export')` 를 부른다.
  - 버전은 `DatasetVersion.objects.for_tenant(...).get(pk=..., dataset__item=item)` 로 읽고, 없으면 `Http404` 다.
  - 최신 ExportJob 형식으로 `JobService.enqueue_export` 를 부른다.

- [ ] **Step 6: 매핑과 JS 공용 함수**

`domain/gui.py` `taskview_menu_code_map()` 의 비전 검사 블록 아래:

```python
        # 데이터 관리 — 화면 하나에 모듈 하나(app/views/item/). 검사항목 권한은 모듈이 본다.
        m['item/snapshot'] = ['wm_data_snapshot']
```

`app/static/wezongrid/wezongrid.js` 에서 `_emitRemoteQueryChange` 가 만드는 `query` 의 페이지 키 이름과 기준(0/1)을 **읽고** 아래 두 줄을 맞춘다.

```js
    // WeZonGrid 서버 모드(dataMode:'server')의 remoteDataSource. 응답은 {rows, totalRows}.
    gridRemoteSource: function (url, buildParams) {
        return {
            loadRows: function (query) {
                const params = $.extend({}, buildParams ? buildParams() : {},
                    { page: query.page, page_size: query.pageSize });   // ← 실제 키로
                return new Promise(function (resolve, reject) {
                    AjaxUtil.getAsyncData(url, params, resolve, function (req, status, error) {
                        AjaxUtil.failureCallback(req, status, error);
                        reject(error);
                    });
                });
            }
        };
    },
```

이 함수는 `app/static/assets/js/common.js` 의 `AjaxUtil` 객체 안, `postFileAsyncData` 다음에 넣는다.

- [ ] **Step 7: GREEN 확인**

Run: `.venv/bin/python manage.py test tests --settings=configurations.test_settings`. Expected: OK
Run: `.venv/bin/python scripts/verify_permission_map.py`. Expected: PASS(`item/snapshot` 이 매핑된다)
Run: `node scripts/verify_screen_js.js`. Expected: OK

- [ ] **Step 8: 결정 기록**

`docs/DECISIONS.md` 에 추가한다.

> **DEC-028 (2026-10-06) 데이터 화면을 MES 셸·MES API 로 옮긴다.**
> - **화면:** 데이터 관리 화면도 `app/layout_page.html` 위에 제목 카드 → 검색 카드 → WeZonGrid → 상세 카드 구조로 쓴다. 모달은 Bootstrap `.modal`·`Alert`·`Notify` 다. 라벨링 작업대는 3열 구조를 유지한다.
> - **API:** 화면 API 는 MES 동적 dispatch `/api/item/<view>?action=` 이다. 화면 하나에 모듈 하나이고 메뉴 매핑은 `gui.py` 에 둔다.
> - **`item` task 의 dispatch:** 요청 전체를 `tenant_atomic()` 으로 감싼다. `READ_ACTIONS` 에 없는 action 은 POST 만 받는다. `ItemApiError` 는 400 으로 바꾼다.
> - **대체하는 것:** 이전 판단 "데이터 화면은 별도 셸, 합치지 않는다"(STATUS §2-1, UI_GUIDE §8)와 DEC-014 의 데이터 REST 부분을 대체한다.

DEC-014 의 근거 칸("동적 dispatch 에는 데코레이터로 권한을 붙일 지점이 없다")에는 "dispatch 인가 훅으로 해소, DEC-028" 을 덧붙인다.

AGENTS.md [2] 표에 `/api/item/<view>` 행을 더한다. 데이터 REST 행은 "작업 대기열 3경로만 남음(전환 중)"으로 바꾼다.

UI_GUIDE §1·§8 과 STATUS §2-1 의 해당 행은 "DEC-028 로 전환 중"으로 고친다.

- [ ] **Step 9: 커밋**

```bash
git add app/views/__init__.py app/views/item/ domain/gui.py app/static/assets/js/common.js tests/test_item_api.py tests/test_seed_demo_permissions.py docs/ AGENTS.md
git commit -m "feat: 데이터 화면용 MES API(item task)와 스냅샷 API 를 만든다"
```

### Task 5: 스냅샷 관리 화면을 MES 구조로 다시 쓴다 (첫 화면, 서버 페이징 시범)

**Files:**
- Rewrite: `app/templates/data/snapshot.html`
- Create: `app/templates/data/snapshot_modal_create.html`
- Modify:
  - e2e `tests/e2e/test_write_paths.py:35-40,208-224`, `tests/e2e/test_crud.py:183-197`
  - `scripts/verify_buttons.py`, `scripts/verify_modals.py`, `scripts/capture_ui.py`, `scripts/verify_layout_stable.py` 의 `wm_data_snapshot` 항목

**Interfaces:**
- Consumes: `/api/item/snapshot`(Task 4), `AjaxUtil.gridRemoteSource`
- Produces: **MES 데이터 화면 골격**. Task 6~10 이 같은 골격을 쓴다.

**화면 골격 (Task 6~10 공통):**

```html
{% extends "app/layout_page.html" %}
{% load static %}
{% block content %}
<div class="card">
  <div class="d-flex card-header justify-content-between align-items-center">
    <h4 class="header-title"><span>스냅샷 관리</span>
      <small class="text-muted ms-2" id="itemName"></small>
      <a href="javascript:void(0);"><i class="uil uil-favorite favorite-off"></i></a></h4>
  </div>
  <div class="card-body py-2">
    <form id="searchForm" class="d-flex align-items-center gap-2" autocomplete="off" onsubmit="return false">
      <input type="text" class="form-control" id="q" placeholder="버전명" style="max-width:240px">
      <button type="button" class="btn btn-search" id="btnSearch">조회</button>
    </form>
  </div>
</div>
<div class="d-flex justify-content-between align-items-center upper-wezongrid">
  <div class="sub-tit"><span class="right_align rpt">스냅샷 목록</span></div>
  <div class="flex-wrap gap-2"><button type="button" class="btn btn-input y_write_auth d-none" id="btnNew">스냅샷 등록</button></div>
</div>
<div id="main-grid"></div>
<div class="card mb-0 mt-2 p-15" id="detailCard">
  <div class="d-flex justify-content-between align-items-center mb-2">
    <div class="sub-tit">상세 정보</div>
    <div class="flex-wrap gap-2"><button type="button" class="btn btn-input y_write_auth d-none" id="btnRebuild">다시 만들기</button></div>
  </div>
  <div id="detailBody"><p class="text-muted mb-0">목록에서 스냅샷을 선택합니다.</p></div>
</div>
{% include "data/snapshot_modal_create.html" %}
{% endblock %}
{% block scripts %}
<script>
const ITEM_ID = new URLSearchParams(location.search).get('project');
class Page {
  init() {
    const _this = this;
    this.grid = WeZonGrid.create('#main-grid', {
      columnLayout: [ /* 아래 표 */ ],
      props: { height: 360, selectionMode: 'singleRow', enablePaging: true, dataMode: 'server', rowIdField: 'id',
               remoteDataSource: AjaxUtil.gridRemoteSource('/api/item/snapshot',
                   () => ({ action: 'list', item_id: ITEM_ID, q: $('#q').val() })) }
    });
    this.grid.on('cellClick', e => _this.showDetail(e.item));
    $('#btnSearch').on('click', () => _this.searchMainData());
    $('#btnNew').on('click', () => _this.openCreate());
    $('#btnRebuild').on('click', () => _this.rebuild());
    this.searchMainData();
  }
  /* searchMainData · showDetail · openCreate · create · rebuild · schedulePoll */
}
let page = new Page();
$(document).ready(() => page.init());
</script>
{% endblock %}
```

- 화면 골격은 `vision/client.html` 과 `system/user.html` 을 따른다.
- 서버 모드에서 "다시 조회"를 부르는 메서드 이름(재조회·첫 페이지 이동)은 `wezongrid.js` 에서 `_emitRemoteQueryChange` 를 부르는 공개 메서드를 찾아 쓴다.
- `item`·`can_create` 처럼 목록 응답에 함께 오는 값은 `remoteLoadSuccess` 이벤트나 `loadRows` 안에서 받아 둔다. 둘 중 무엇을 쓰는지는 Step 2 에서 정하고, 정한 방법을 Task 6 이후에도 그대로 쓴다.

**스냅샷 화면 내용:**

| 영역 | 내용 |
|---|---|
| 그리드 열 | 버전 · 등록일 · 이미지 수 · 제외 이미지 수 · 형식 · 상태 · 다운로드 |
| 상태 열 | 실패는 `text-danger` 로 표시한다 |
| 다운로드 열 | html renderer. `file_url` 이 있으면 `<a href=… data-spa-ignore>받기</a>` |
| 상세 카드 | `detail` 의 분포 분석을 `table table-bordered` 로 보인다. 실패면 `error_message` 를 보이고 "다시 만들기" 버튼을 보인다(`can_create`) |
| 등록 모달 | Bootstrap `.modal`. 형식 `<select>`(`formats`)와 안내 "검수 승인된 이미지로 지금 시점의 데이터셋을 만듭니다. 완료되면 목록에서 받을 수 있습니다." |
| 모달 버튼 | `취소`(`btn-input`) → `등록`(`btn-band`) 순서 |
| 권한 | `can_create` 일 때만 `#btnNew` 를 보인다 |
| 폴링 | 현재 페이지에 `QUEUED`·`RUNNING` 이 있으면 3초마다 다시 조회하고, 없으면 멈춘다. `beforeunload` 에서 타이머를 지운다 |
| 오류 | 400·403·404 는 `AjaxUtil.failureCallback` 이 `Alert` 로 보인다. 성공은 `Notify.success(res.message)` |

- [ ] **Step 1: e2e 를 먼저 새 흐름으로 고친다 (RED)**

`test_write_paths.py` 스냅샷 단계는 다음 순서로 바꾼다. 품질 점검 클릭 단계는 지운다.
1. `#btnNew` 를 누른다.
2. 모달에서 형식을 고르고 `등록` 을 누른다.
3. `run_worker_once()` 를 부른다.
4. 그리드 첫 행 상태가 "완료"이고, 받기 링크 `href` 가 `/media/export/` 로 시작하는지 본다.
5. 그 링크를 `page.request.get` 으로 받아 200 · `application/zip` 인지 본다.

`test_crud.py:183-197` 은 "등록 모달이 열리고 Esc 로 닫힘"으로 바꾼다.

Run(서버 필요): `.venv/bin/python -m pytest tests/e2e/test_write_paths.py tests/e2e/test_crud.py -q -k snapshot`
Expected: FAIL(`#btnNew` 가 없다)

- [ ] **Step 2: 화면 구현** — 골격과 표대로 다시 쓴다.

- [ ] **Step 3: GREEN**

Step 1 명령이 OK 인지 본다. 그리고 다음을 돌린다.

```bash
node scripts/verify_screen_js.js
.venv/bin/python scripts/verify_buttons.py      # 서버 필요. 스냅샷 화면을 MES 버튼 계열로 본다
.venv/bin/python scripts/verify_modals.py       # 서버 필요. 등록 모달 케이스를 더한다(열림·백드롭·포커스·Esc)
.venv/bin/python scripts/verify_korean_only.py
```

- [ ] **Step 4: 눈으로 비교**

Playwright 로 `/gui/wm_data_snapshot/?project=<id>` 와 `/gui/wm_vis_client/` 를 같은 창 크기(1920×911)로 캡처한다. 나란히 놓고 같은 계열인지 본다.
- 제목 카드
- 버튼
- 그리드 머리·행 높이
- 상세 카드 여백

어긋나면 고친다.

- [ ] **Step 5: 문서·커밋 → 단계 ② 병합**

고칠 문서:
- `docs/FEATURES.md`: §4.6 품질 점검 삭제, §4.7·§4.8 을 새 흐름으로, l.92 권한 행, l.155 흐름도, l.278 화면 표
- `docs/DATA_MODEL.md`: 품질 테이블·`readiness` 삭제, RLS 대상 18개
- `AGENTS.md`:
  - [4] "데이터 관리 테이블 20개" → 18
  - [5] `run_worker` 주석 "품질 점검·Export" → "스냅샷 zip"
- 그 밖에: `README.md:16,26,45`, `docs/ARCHITECTURE.md:5,35,43,314-332`, `docs/DEPLOYMENT.md:17-19,407`, `docs/DEVELOPMENT.md:59,125`, `docs/STATUS.md:15,74,101`

```bash
git add app/templates/data/snapshot.html app/templates/data/snapshot_modal_create.html tests/e2e scripts docs AGENTS.md README.md
git commit -m "feat: 스냅샷 관리를 MES 화면으로 바꾸고 등록·완료·다운로드 흐름으로 줄인다"
```

병합 전에 AGENTS [5] 의 전부(단위 · e2e 전체 · 검증 스크립트 10개)를 통과시킨다.

---

# 단계 ③ `feat/data-screens-mes` — 나머지 화면

Task 6~10 은 모두 Task 4 의 **`item` 모듈 규약**과 Task 5 의 **화면 골격**을 따르고, 같은 순서로 진행한다.

1. **API 테스트(RED)** — `tests/test_item_api.py` 에 그 모듈의 클래스를 더한다. 최소 범위는 다음과 같다.
   - action 마다 정상 응답 1건
   - 변경 action 마다 GET 이면 405
   - 다른 메뉴 권한만 있는 사용자는 403
   - 배정되지 않은 검사항목은 403
2. **모듈 구현(GREEN)** — `app/views/item/<view>.py` 와 `gui.py` 매핑을 만든다. 로직은 표에 적은 REST View 에서 옮기고, 서비스 호출은 그대로 쓴다.
3. **e2e 선택자를 새 구조로 고친다(RED).**
4. **화면 구현(GREEN)** — `verify_screen_js`·`verify_buttons`·`verify_modals`·`verify_korean_only` 를 돌린다.
5. **옛 REST 를 지운다** — 그 화면만 쓰던 REST 경로·View·`DATA_API_MENUS` 항목·REST 테스트. 지운 뒤 `verify_permission_map.py` 가 PASS 여야 한다.
6. **눈으로 비교** — `vision/client.html` 과 나란히 캡처한다.
7. **문서·커밋** — `docs/FEATURES.md` 의 그 화면 절을 고치고 커밋한다.

### Task 6: 검사항목 관리 — MES 전환 · 시스템 관리로 이동 · 이름 변경 (U-2)

**Files:**
- Create: `app/views/item/item_admin.py`
- Rewrite: `app/templates/data/item_list.html`, `item_modal_create.html`, `item_modal_add_member.html`(Bootstrap `.modal`)
- Modify: `domain/gui.py`(`m['item/item_admin'] = ['wm_data_item']`, l.54 이름), `seed_initial.py` `MENU_TREE`, `app/views/system/menus.py`
- Delete: `app/views/data/item_admin_api.py`, `urls_data.py` 의 `admin/items*` 4경로, `DATA_API_MENUS['admin/items']`
- Test:
  - `tests/test_item_api.py`(`ItemAdminApiTest`), `tests/test_menu_tree.py`(신규)
  - `tests/test_item_admin_routes.py`·`tests/test_single_org.py:75`(REST → MES 로 옮긴다)
  - e2e `test_menu.py:104,183-188`, `test_crud.py:135-137,153,237,299,327-376`, `test_write_paths.py:44,55,60,68`
  - `scripts/verify_modals.py:34-52,203`

**`/api/item/item_admin`** — 모든 action 에서 먼저 `user_is_platform_admin(request.user)` 를 확인한다. 아니면 `PermissionDenied('플랫폼 관리자만 사용할 수 있습니다.')` 를 던진다.

| action | 메서드 | 원본(REST) |
|---|---|---|
| `list` (`q`·`status`·`page`·`page_size`, 서버 페이징) | GET | `PlatformInspectionItemDirectoryApiView.get` |
| `detail` (`item_id`) | GET | 같은 View 의 `item_id` 분기 |
| `members` (`item_id`) · `candidates` (`item_id`, `q`) | GET | `admin/items/<id>/members/` GET |
| `create` (폼 + 파일) | POST | `PlatformInspectionItemCommandApiView` `create` — 생성 후 코드 `ITEM-<id>` 는 그대로 |
| `toggle_status` · `approve_delete` · `reject_delete` (`item_id`) | POST | 같은 View 의 각 action |
| `add_member` (`item_id`, `user_id`, `role`) · `change_role` · `remove_member` | POST | members POST · DELETE |

**화면:**

| 영역 | 내용 |
|---|---|
| 제목 | "검사항목 관리" |
| 검색 카드 | 시스템 관리 방식(라벨 + 입력, `collapse show` + `floder-close`). 검색어 · 상태 · 조회 |
| 그리드 | 서버 페이징. 열은 `list` 가 주는 키로만 만든다: 코드 · 이름 · 유형 · 상태 · 배정 인원 · 등록일 |
| 그리드 바 | `등록`(`btn-input y_write_auth`) → 생성 모달(지금 필드·대표 이미지·원본 파일 그대로) |
| 상세 카드 | 필드를 보인다. 버튼은 사용/일시 중지(`btn-input`)이고, 삭제 요청 상태면 반려(`btn-input`)·삭제 승인(`btn-dell`, `Alert.confirm`) |
| 배정 인원 | 상세 카드 아래 두 번째 그리드(메뉴명 설정의 세로 마스터-상세 방식). 바에 `인원 추가`(모달)·`제외`(`btn-dell`). 역할은 셀 `select` 를 바꾸면 `change_role` 을 부른다 |

**메뉴 이동:**

- [ ] **빈 폴더 테스트(RED)** — `tests/test_menu_tree.py`

메뉴 트리 SQL 은 PostgreSQL 전용이라 단위 테스트가 닿지 않는다(AGENTS [6]). 폴더 정리 부분을 함수로 떼어 그 함수만 시험한다.

```python
from django.test import SimpleTestCase
from app.views.system.menus import drop_empty_folders


class DropEmptyFoldersTest(SimpleTestCase):
    def test_하위가_없는_폴더는_내보내지_않는다(self):
        tree = [{'objId': 'f1', 'nodes': []},
                {'objId': 'f2', 'nodes': [{'objId': 'wm_user', 'nodes': []}]}]
        self.assertEqual([f['objId'] for f in drop_empty_folders(tree)], ['f2'])
```

- [ ] **구현** — `menus.py`

```python
def drop_empty_folders(folders):
    """메뉴가 하나도 남지 않은 폴더를 뺀다. 플랫폼 관리자 전용 메뉴만 있는 폴더가 작업자에게 빈 채로 보이지 않게."""
    return [f for f in folders if f['nodes']]
```

함수 끝의 `return menu_items` 를 `return drop_empty_folders(menu_items)` 로 바꾼다. docstring(l.8)과 주석(l.28·92)의 "검사항목 목록"도 고친다.

- [ ] **`MENU_TREE`**
  - 데이터 관리 목록에서 `wm_data_item` 튜플을 뺀다.
  - 시스템 관리 목록 **맨 앞**에 이름을 "검사항목 관리"로 바꿔 넣는다(나머지 값은 그대로).
  - `gui.py:54` 이름도 같이 바꾼다.
  - 개발 DB 에 `.venv/bin/python manage.py seed_initial` 을 **비밀번호 인자 없이** 다시 돌린다. 인자가 없으면 관리자 계정은 건드리지 않고 메뉴만 맞춘다(`seed_initial.py:77,130-131`).

- [ ] **e2e**
  - `test_menu.py:104`: 데이터 관리 첫 항목 기대값을 검사항목 노드로 바꾼다.
  - `183-188`: 시스템 관리 아래 "검사항목 관리"를 확인하게 바꾼다.
  - `174`(작업자에게 시스템 관리가 없다)는 **고치지 않고 통과해야 한다.**

- [ ] **문서**: `docs/FEATURES.md:24,49,69-70,138,273`, `docs/DECISIONS.md:52`(O-13), `docs/STATUS.md:16`

```bash
git commit -m "feat: 검사항목 목록을 검사항목 관리로 바꿔 시스템 관리에 MES 화면으로 옮긴다"
```

### Task 7: 검사항목 홈

**Files:**
- Create: `app/views/item/item_home.py`(`m['item/item_home'] = ['wm_data_item_detail']`)
- Rewrite: `app/templates/data/item.html`, `item_modal_edit.html`, `item_modal_assignment.html`
- Delete: `app/views/data/item_api.py` 의 화면 전용 View 와 `items/<id>/*` 경로. 다른 화면이 아직 `items/` 를 부르면 그 화면 Task 에서 지운다. `grep -rn "/api/data/items" app/templates` 로 확인한다.
- Test: `tests/test_item_api.py`(`ItemHomeApiTest`), e2e `test_crud.py:200-202,246-291`, `test_write_paths.py:105`

**`/api/item/item_home`**

| action | 메서드 | 원본(REST) |
|---|---|---|
| `detail` (`item_id`) | GET | `InspectionItemDetailApiView.get` — 요약 수치, 배정 인원, 라벨 클래스, 최근 스냅샷 5개(Export 상태·받기 링크), 최근 이미지 썸네일 |
| `candidates` (`item_id`, `q`) | GET | `items/<id>/members/` GET |
| `update_info` · `update_assignment` · `update_labels` (`Q`=JSON) | POST | `InspectionItemCommandApiView` 의 각 command |

**화면:**

| 영역 | 내용 |
|---|---|
| 제목 카드 | 대표 이미지 작은 썸네일(높이 48) · 검사항목 이름 · 상태 배지 · 유형. 오른쪽에 `검사항목 편집`(`btn-input y_write_auth`, 관리자만) |
| 요약 카드 줄 | `vision/inspection.html` `#summaryCards` 방식으로 카드 4개(지금 quick-stat 값 그대로) |
| 2열 카드 | 배정 인원 그리드 · 라벨 클래스 그리드(높이 240, 페이징 없음) |
| 스냅샷 카드 | 최근 스냅샷 그리드 + "전체 보기"(→ `/gui/wm_data_snapshot/?project=`) |
| 데이터 카드 | 최근 썸네일 줄 + "전체 보기"(→ `/gui/wm_data_image/?project=`) |
| 편집 모달 | Bootstrap `.modal` + `nav-tabs`(정보 · 배정 · 라벨 클래스) — 지금 세 폼 그대로 |

```bash
git commit -m "feat: 검사항목 홈을 MES 카드·그리드 구조로 바꾼다"
```

### Task 8: 데이터 목록 (+ 업로드 20개씩, D-9)

**Files:**
- Create: `app/views/item/image.py`(`m['item/image'] = ['wm_data_image']`), `app/static/data/annotation.js`
- Rewrite: `app/templates/data/image.html`, `image_modal_upload.html`, `image_modal_preprocess.html`
- Modify: `domain/services/data/image.py:69`, `app/static/data/common.js`(옮긴 함수 삭제 — `home.html` 이 쓰는 것은 남긴다)
- Delete: `app/views/data/image_api.py` 의 화면 전용 View 와 `images/*` 경로. 라벨링·검수 화면이 아직 부르면 Task 9·10 에서 지운다.
- Test: `tests/test_data_services.py`(`UploadLimitTest`), `tests/test_item_api.py`(`ImageApiTest`), e2e `test_workflow.py:122`, `test_write_paths.py:152-180`

**`/api/item/image`**

| action | 메서드 | 원본(REST) |
|---|---|---|
| `list` (`item_id`·`q`·`status`·`label`·`date_from`·`date_to`·`page`·`page_size`) | GET | `ImageListApiView.get` |
| `detail` (`item_id`, `image_id`) | GET | `ImageDetailApiView.get` |
| `filters` (`item_id`) | GET | 라벨 클래스 목록(검색 콤보용) |
| `upload` (파일 `files` 여러 개, `requires_labeling`) | POST | `ImageUploadApiView.post` |
| `delete` (`image_id`) | POST | `ImageDetailApiView.delete` |
| `preprocess` (`image_id`, `Q`=단계 JSON) | POST | `ImagePreprocessApiView.put` |

**`annotation.js`** — `data/common.js` 의 `renderAnnotationOverlay`·`createAnnotationPreview` 와, 그 둘이 쓰는 내부 함수를 `window.AnnotationView` 로 옮긴다. MES 화면은 `data/common.js` 를 싣지 않는다. 두 파일 모두 `window.AjaxUtil` 을 정의하므로 같이 싣으면 충돌한다. `verify_screen_js.js` 의 `DataUI` 이름 검사에 `AnnotationView` 내보내기 검사를 더한다.

- [ ] **서버 초과분 거절 (RED → GREEN)**

```python
class UploadLimitTest(DataServiceTestCase):
    def test_21번째부터는_거절_목록에_들어간다(self):
        files = [make_image(f'{i}.png', color=(i, 0, 0)) for i in range(21)]
        with tenant_atomic(self.tenant):
            result = ImageService.upload_images(self.item, files, actor=self.worker)
        self.assertEqual(len(result['uploaded']), 20)
        self.assertEqual(result['rejected'], [{'name': '20.png', 'reason': '한 번에 20개까지 올릴 수 있습니다.'}])
```

`image.py` 의 구현:
- `MAX_FILES_PER_REQUEST = 20` 을 두고 루프는 `files[:MAX_FILES_PER_REQUEST]` 만 돈다.
- 루프 뒤에 `rejected += [{"name": f.name, "reason": "한 번에 20개까지 올릴 수 있습니다."} for f in files[MAX_FILES_PER_REQUEST:]]` 를 더한다.

**화면:**

| 영역 | 내용 |
|---|---|
| 검색 카드 | 검색어 · 상태 · 라벨(`filters`) · 기간(daterangepicker, 로그 화면 방식) · 조회 |
| 그리드 | 서버 페이징. 미리보기(html renderer `<img src="{thumbnail_url}" height="40">`) · 파일명 · 상태 · 라벨 상태 · 수정일 |
| 그리드 바 | `데이터 추가`(`btn-input y_write_auth`) |
| 상세 카드 | 미리보기 + 주석 오버레이(`AnnotationView.createAnnotationPreview`) · 필드 표 · `이미지 편집`(`btn-input`) · `삭제`(`btn-dell`, `Alert.confirm`) |
| 업로드 모달 | 아래 항목 참조 |
| 편집 모달 | 회전·원근·크롭·크기 조정은 그대로 두고 껍데기만 `.modal` 로 바꾼다 |

업로드 모달의 동작:
- 고른 파일을 **20개씩** `AjaxUtil.postFileAsyncData('/api/item/image?action=upload', formData, ...)` 로 차례로 보낸다.
- 보내는 동안 "n / 전체" 진행을 보인다.
- 묶음 하나가 실패해도 다음 묶음을 계속 보낸다.
- 끝나면 올라간 수와 거절 목록을 한 번에 보인다.

- [ ] **e2e** — `E2E-` 검사항목에 25장을 올리는 시나리오를 더한다. 25장이 모두 올라가고 거절이 0 이어야 한다. 끝나면 지운다.

- [ ] **문서**
  - `docs/STATUS.md` §3-5 의 "데이터 업로드 파일 수" 행을 지우고 우선순위 4 를 완료로 표시한다.
  - `docs/DEPLOYMENT.md` 의 nginx `client_max_body_size` 안내를 "한 묶음(20장) 합계" 기준으로 고친다.

```bash
git commit -m "feat: 데이터 목록을 MES 화면으로 바꾸고 업로드를 20개씩 나눠 보낸다"
```

### Task 9: 검수 작업

**Files:**
- Create: `app/views/item/review.py`(`m['item/review'] = ['wm_data_review']`)
- Rewrite: `app/templates/data/review.html`
- Delete: `app/views/data/review_api.py`, `review/*` 경로
- Test: `tests/test_item_api.py`(`ReviewApiTest`), e2e `test_write_paths.py` 검수 단계

**`/api/item/review`**

| action | 메서드 | 원본(REST) |
|---|---|---|
| `list` (`item_id`, 페이지) — 검수 대기(SUBMITTED)만 | GET | 화면이 부르던 `images/?…` 조회. 이 모듈 안에 둔다. 작업자에게 `wm_data_image` 권한이 없어도 된다 |
| `detail` (`image_id`) — 이미지·주석 | GET | `ImageDetailApiView.get` 일부 |
| `approve` · `rework` (`image_id`, `comment`) | POST | `DatasetReviewApiView.post` |

**화면:**

| 영역 | 내용 |
|---|---|
| 검색 카드 | "검수 대기" 안내 · 조회 |
| 그리드 | 서버 페이징. 미리보기 · 파일명 · 제출자 · 제출일 |
| 상세 카드 | 큰 미리보기 + 주석 오버레이 + 주석 목록 표. 버튼은 `재작업 요청`(`btn-input`) · `승인`(`btn-band`). 처리하면 다음 행을 자동으로 고른다 |

```bash
git commit -m "feat: 검수 작업을 MES 그리드·상세 카드 구조로 바꾼다"
```

### Task 10: 라벨링 작업 (D-4 — 셸·제목·버튼만)

**Files:**
- Create: `app/views/item/labeling.py`(`m['item/labeling'] = ['wm_data_labeling']`)
- Modify: `app/templates/data/labeling.html`, `app/static/data/governance.css`, `app/static/data/layout.css`(`body.labeling-screen` 규칙)
- Delete: `labeling_api.py` 의 claim·draft·submit·heartbeat View 와 경로. **`labeling/queue`(작업 대기열)는 남긴다**(B-7).
- Test: `tests/test_item_api.py`(`LabelingApiTest`), e2e `test_workflow.py:154`, `test_write_paths.py` 라벨링 단계

**`/api/item/labeling`**

| action | 메서드 | 원본(REST) |
|---|---|---|
| `queue` (`item_id`) — 좌측 이미지 목록(전체, `all=1` 과 같다) | GET | 화면이 부르던 `images/?item_id&all=1` |
| `image` (`image_id`) — 캔버스용 이미지·주석·라벨 클래스 | GET | `ImageDetailApiView.get` 일부 |
| `claim` (`image_id`) · `heartbeat` (`task_id`) · `draft` (`task_id`, `Q`=주석 JSON) · `submit` (`task_id`, `Q`) | POST | `LabelingTask*ApiView` |

`draft` 는 지금 PUT 이다. MES 에서는 POST 다. 주석 배열은 `Q` 로 보낸다(B-5).

**화면:**

| 영역 | 내용 |
|---|---|
| 셸 | `layout_page.html`. `.ifram-wrapper` 안에서 작업대가 창 높이를 채우게 높이 체인을 다시 잡는다. 지금의 `body.labeling-screen` + `.content-page{height:100vh}` 대신 `layout_page` 의 `.autoheight-div` 크기 조정을 쓰거나 `calc(100vh - 제목 카드 높이)` 를 쓴다 |
| 제목 카드 | "라벨링 작업" + 진행 지표(지금 상태 바의 수치) |
| 제목 카드 버튼 | `작업 시작`(`btn-input`) · `임시 저장`(`btn-input`) · `작업 완료`(`btn-band`) · `다음 작업`(`btn-input`) |
| 작업대 | 3열·캔버스·도구·단축키는 그대로. 좌우 패널을 `card` + `sub-tit` 머리로 바꾼다 |

위험: 높이 체인이 틀리면 캔버스 좌표가 어긋난다. 먼저 e2e 가 BBOX 를 그리고 저장한 뒤 좌표를 검증하는지 읽는다. 검증하지 않으면 "그리기 → 임시 저장 → 다시 열기 → 같은 좌표" 단계를 더한다.

```bash
git commit -m "feat: 라벨링 작업대를 MES 셸·API 로 옮긴다"
```

### Task 11: 정리 · 권한 · 검증 기준 · 문서

**Files:** `app/static/data/main.css`·`layout.css`·`common.js`, `data/_base.html`, `configurations/urls_data.py`, `app/views/data/`, `domain/management/commands/seed_demo.py`, `scripts/verify_*.py`·`capture_ui.py`, 문서

- [ ] **Step 1: 남은 REST 확인**
  - `urls_data.py` 에는 작업 대기열 3경로(`labeling/queue`·`home/statistics`·`activity-log`)만 남아야 한다.
  - `app/views/data/` 에는 `base.py`·`home_api.py`(+ queue View)만 남아야 한다.
  - `grep -rn "/api/data/" app/templates app/static` 의 결과는 `home.html` 뿐이어야 한다.
- [ ] **Step 2: 작업자 권한 정리**
  - 데이터 화면이 `wm_data_item` 을 더는 부르지 않는다.
  - `seed_demo.py` `WORKER_MENUS` 에서 `wm_data_item` 을 지운다.
  - `tests/test_seed_demo_permissions.py` 를 고친다.
  - 개발 DB 의 `user` 그룹 `wm_data_item` 권한도 지운다(사용자에게 알린다).
- [ ] **Step 3: 쓰지 않는 CSS·JS 삭제**
  - 대상 예: `crud-*`·`admin-search*`·`section-heading`·`.form-dialog`·`.upload-dialog`·`.project-settings-dialog`·`project-home*`·데이터 `.pagination`·`.quality-summary*`
  - 지우기 전마다 `grep -rn "<클래스>" app/templates app/static --include=*.html --include=*.js` 로 0건인지 확인한다.
  - `home.html`·`labeling.html` 이 쓰는 것은 남긴다.
  - `data/common.js` 에서 `home.html` 이 쓰지 않는 함수를 지운다.
- [ ] **Step 4: `data/_base.html`** — `home.html` 만 쓰는지 확인하고 남긴다.
- [ ] **Step 5: 검증 스크립트 기준 갱신**
  - `verify_buttons.py`: 데이터 버튼 계열(`.primary-button` 등)의 대상 화면 목록을 정리한다.
  - `verify_modals.py`: 데이터 `<dialog>` 케이스를 정리한다.
  - `verify_permission_map.py`:
    - `NOT_DISPATCHED`·docstring 은 "작업 대기열만"으로 고친다.
    - 데이터 화면이 MES 로 바뀌었으므로 `check_data_api` 는 남은 3경로만 본다.
  - `verify_layout_stable.py`: 기준 캡처를 **새로 찍는다**. 데이터 화면을 의도적으로 바꿨다는 사실을 커밋 메시지에 적는다.
- [ ] **Step 6: 문서**
  - `docs/UI_GUIDE.md`
    - §4 버튼 표의 데이터 열 → "작업 대기열만"
    - §5 데이터 `<dialog>` 계열을 줄인다
    - §8 에서 대체된 항목을 지운다
  - `docs/STATUS.md`
    - §2-1 "데이터 화면은 별도 셸" 행을 지운다.
    - §3-6 의 D-1·D-3·D-4 를 "데이터 화면은 DEC-028 로 해소, 작업 대기열만 남음"으로 고친다. D-2 는 그대로 둔다.
    - 우선순위 표를 갱신하고, 우선순위 8 에 "작업 대기열·데이터 REST 잔여 3경로"를 적는다.
  - `docs/ARCHITECTURE.md`: API 규약 절(`/api/item` 추가, 데이터 REST 잔여), 기반 템플릿 설명(l.228)
  - `AGENTS.md`
    - [2] API 규약 표
    - [3] "자기 메뉴의 API 에 필요한 액션을 둔다" 문장은 `item` 모듈 규약을 가리키게 고친다
- [ ] **Step 7: 전체 검증** — AGENTS [5] 의 전부(단위 · e2e · 검증 스크립트 10개)
- [ ] **Step 8: 커밋 → 단계 ③ 병합**

```bash
git commit -m "refactor: MES 전환으로 쓰지 않게 된 데이터 화면 자원·권한·검증 기준을 정리한다"
```

---

## 범위 밖

- `/api/v1` 계약 변경은 없다.
- 작업 대기열(`home.html`)과 데이터 REST 잔여 3경로는 STATUS 우선순위 8 이다. 그때 REST·미들웨어·`urls_data.py` 를 완전히 지운다.
- 식별자 `project`(`?project=`·class·JS 변수) 이름은 바꾸지 않는다. 메뉴 트리 링크와 함께 바꿔야 한다.
- D-2 WeZonGrid 서체는 바꾸지 않는다. 그리드 폭 측정이 바뀐다.
- PostgreSQL 통합 테스트(우선순위 5)는 하지 않는다. 메뉴 트리·RLS 는 이번에도 e2e 로만 본다.
- Client 0.1.6 반입·Overlay 3 삭제는 [2026-10-06-client-requests-followup.md](2026-10-06-client-requests-followup.md) Task 3·5 에서 다룬다.
