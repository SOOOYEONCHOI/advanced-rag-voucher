# 검사 작업(수입)·입고 내역·양식 기준 품목 매핑 구현 계획

> 실행: superpowers:executing-plans(또는 subagent-driven-development)로 이 문서 순서대로 한다. 단계는 체크박스(`- [ ]`)로 표시한다.

**목표:** 품목 검사양식 매핑을 양식 기준 N:M 으로 바꾸고, 입고 조회를 기준정보 > 입고 내역으로 내리며, 수입 검사작성 작업 목록을 "검사 작업"(대기·작성 중·수기)으로 바꾼다.

**구조:** 대기 작업은 저장하지 않는다 — 매핑 (품번 × 양식코드) × 입고 중 그 양식코드·입고번호 작성건이 없는 것을 그때 센다(`domain/services/receipt.py`).
작성 중 작업은 지금 작성건(`dig_form_result`) 그대로다. 테이블 변경은 `mst_product_form` unique 하나(plan 1 Task 1 의 0019 에 들어 있다).

**설계:** [docs/superpowers/specs/2026-10-21-inspection-rework-design.md](../specs/2026-10-21-inspection-rework-design.md) §2-3·6·9(D12·D13·D15)

## 공통 제약

- 같은 worktree·브랜치(`.worktrees/inspection-rework`, `feat/inspection-rework`). [plan 1](2026-10-21-inspection-category.md) Task 0·1 이 먼저다(모델 변경이 그 마이그레이션에 있다)
- 테스트는 `--settings=configurations.test_settings`, 고친 범위만. e2e 는 0019 적용 뒤 8124 로, `E2E-` 데이터만
- 메뉴 이동은 `seed_initial` `MENU_TREE` 로(코드는 그대로 — 권한·즐겨찾기가 남는다). 반영은 담당자가 `seed_initial` 을 다시 돌린다
- 사용자 문구 `~합니다` 체, 값은 `.text()`, 조회 `getAsyncData`·변경 `postAsyncData`
- 판/가공품 행 N개·대분류 규칙 매핑은 하지 않는다

---

### Task 1: 검사 작업 계산 (서비스)

**Files:** `domain/services/receipt.py`, `tests/test_receipt_view.py`(서비스 테스트도 여기), `tests/test_receipt_jobs.py`(생성)

- `form_codes(part_nos)` → `{품번: [양식코드, ...]}`(N:M). 호출처 `app/views/system/product_form.py`(Task 2 에서 다시 씀)·`app/views/definition/receipt.py`(Task 3 에서 지움)
- `with_state` 는 `is_target` 만 남긴다(자재입고 검색 팝업의 검사 대상만). `has_done`·`has_working`·`state_of`·`STATE_FILTERS`·`STATE_LABELS`·`PENDING`·`pending_count` 는 Task 3·4 에서 호출처를 없앤 뒤 지운다
- 새 함수:

```python
def waiting_jobs(keyword='', form_code=''):
    """대기 작업 [(입고, 양식)] — 매핑 (품번, 양식코드) 의 입고 중 그 양식코드·입고번호로 쓴 작성건(상태 무관)이 없는 것.

    양식은 그 코드의 사용 중인 최신 버전(latest_forms) — 없으면 나오지 않는다. 입고일 최신순.
    """
    # ponytail: 매핑된 입고 전부를 메모리에서 맞춘다 — 입고가 수만 건이면 (품번, 양식코드) 조인 SQL 로
def job_counts():
    """검사 대기 배지 — {'waiting': 대기 작업 수, 'working': 매핑된 (입고, 양식코드) 중 작성 중이고 완료가 없는 수}."""
```

- 작성건 조회는 `DigFormResult.objects.filter(DigForm__FormType=INCOMING, WorkOrderNumber__in=입고번호들).values_list('DigForm__Code', 'WorkOrderNumber', 'State')`

- [ ] 실패하는 테스트 `tests/test_receipt_jobs.py`: 품번 하나에 양식 둘이면 대기 2 / 한 양식만 작성 중이면 대기 1·working 1 / 완료가 있으면 그 쌍은 없음 / 옛 버전으로 쓴 작성건도 같은 코드면 쓴 것 /
  최신 버전이 사용 중이 아니면 대기에 없음 / 매핑 없는 입고는 없음 / keyword(입고번호·품목코드·품목명)·form_code 필터 / `form_codes` 가 목록을 준다
- [ ] 구현 → 통과 → 커밋 `feat: 매핑된 입고와 양식으로 수입 검사 대기 작업을 센다`

### Task 2: 품목 검사양식 매핑 — 양식 기준 화면

**Files:** `app/views/system/product_form.py`(다시 씀), `app/templates/system/product_form.html`(다시 씀), `tests/test_product_form_view.py`, `tests/e2e/test_receipt.py`(매핑 테스트)

API(`WRITE_ACTIONS = frozenset({'add', 'remove'})`, POST 아니면 `PermissionDenied` 그대로):
- `forms` → `[{code, title, version, layout_type, item_count}]` — 수입 양식 중 사용 중인 최신 버전(`latest_forms`), 코드순
- `items`(form_code) → 그 양식에 매핑된 품번 `[{part_no, name, part_type, spec}]`(품번의 가장 나중 리비전 이름, 품번순)
- `products`(form_code, keyword) → 아직 그 양식에 매핑되지 않은 품번(가장 나중 리비전), 품번순 100건
- `add`(form_code, part_nos — JSON 배열) → 양식이 `latest_forms` 에 없으면 "사용 중인 수입검사 양식을 골라 주세요.", 없는 품번이 있으면 "품번을 찾을 수 없습니다: <품번>", 이미 있는 쌍은 건너뛴다. `{'success': True, 'message': '', 'added': n}`
- `remove`(form_code, part_no) → 지운다(없으면 성공)

화면: 왼쪽 양식 그리드(`#form-grid`: 코드·제목·버전·품목 수) → 고르면 오른쪽 품목 그리드(`#item-grid`: 품번·품목명·유형·규격·행 [삭제]), 목록 머리 [품목 추가] →
모달 `#productAddModal`(검색어 + 체크 그리드, [취소]·[추가]). 안내 문구의 "(검사 작업 > 입고 조회)" 를 "수입 검사작성 작업의 검사 작업"으로

- [ ] 실패하는 테스트(`ProductFormViewTest` 를 바꿈): forms 품목 수 / items / products 는 매핑된 것 제외 / add 여러 개·중복 건너뜀·거절 2가지 / remove / GET 으로 add 403 / 메뉴 매핑
- [ ] 구현 → 통과 → `verify_screen_js.js` → e2e(`test_receipt.py` 매핑 테스트를 바꿈): 양식 고르기 → [품목 추가] 로 E2E 품번 둘 → 목록에 보임 → [삭제]
- [ ] `verify_modals.py`·`verify_buttons.py` → 커밋 `feat: 품목 검사양식 매핑을 양식 기준 N:M 화면으로 바꾼다`

### Task 3: 입고 조회 → 기준정보 > 입고 내역

**Files:** `app/views/definition/receipt.py`, `app/templates/definition/receipt.html`, `app/templates/dig_form/dig_form_mat_in_popup.html`(65행 검사 상태 열·105–107행), `domain/gui.py`(100행 이름·주석), `domain/management/commands/seed_initial.py`(MENU_TREE),
`scripts/verify/verify_buttons.py`(63행 목록), `tests/test_receipt_view.py`, `tests/test_dig_form.py`(1071 SeedInitial), `tests/e2e/test_receipt.py`, `tests/e2e/test_menu.py`, `tests/e2e/test_workflow.py`(84–100 첫 잎)

- `gui_item('입고 내역', 'definition/receipt.html')`. MENU_TREE: 검사 작업에서 빼고 기준정보 `('wm_receipt', '입고 내역')`(품목·BOM 조회 다음)
- API: `list` 에서 `state` 필터·`form_code`/`form_id`/`form_title`/`state`/`state_label` 키를 뺀다. `target_only` 는 남긴다(팝업). `pending_count`·`can_write` action 을 지운다
- 매핑 `m['definition/receipt'] = ['wm_receipt', dig_form_menu_code('INCOMING', 'write')]` 는 그대로(팝업이 수입 검사작성 권한으로 부른다)
- 화면: 검색의 `#cboState`·`#targetOnly`, 그리드의 검사양식·검사 상태·[검사 작성] 열, `write()`·`can_write`·`refreshBadges()` 호출을 지운다
- 팝업: 검사 상태 열을 뺀다
- 이 Task 에서 `receipts.state_of`·`STATE_FILTERS`·`STATE_LABELS` 를 지운다(호출처가 없다 — grep 으로 확인)

- [ ] 실패하는 테스트: 응답에 검사 키가 없음 / `target_only` 는 매핑 품번만 / `pending_count`·`can_write` 는 오류 / `seed_initial` 뒤 `wm_receipt` 가 기준정보·"입고 내역"
- [ ] 구현 → 통과 → `verify_menu.py`·`verify_permission_map.py`·`verify_buttons.py` → e2e(`test_receipt.py` 상태·[검사 작성] 테스트를 지우고 입고 내역 조회 하나로, 팝업 테스트는 남김 / `test_menu.py` 폴더 기대값 / `test_workflow.py` 첫 잎)
- [ ] 커밋 `feat: 입고 조회를 기준정보 > 입고 내역으로 내리고 검사 정보를 뺀다`

### Task 4: 수입 검사작성 작업 = 검사 작업 목록·배지

**Files:** `app/views/dig_form/dig_form.py`, `app/templates/dig_form/dig_form_write.html`, `app/templates/app/left_menu_class.html`(92–109·88·1512행), `domain/services/receipt.py`(남은 상태 함수 정리), `tests/test_dig_form.py`, `tests/test_receipt_jobs.py`, `tests/e2e/test_receipt.py` → `tests/e2e/test_inspection_jobs.py`(이름 바꿈), `tests/e2e/test_dig_form.py`

API(`dig_form.py`):
- `job_list`(form_type=INCOMING 만, 그 밖은 오류) — 파라미터 `keyword`(입고번호·품목), `form_code`, `kind`(`''`·`WAITING`·`WORKING`). 행 키:
  `kind`·`kind_label`(대기·작성 중)·`receipt_no`·`receipt_date`·`item_code`·`item_name`·`qty`·`vendor_name`·`form_id`·`form_code`·`form_title`·`form_version`·
  `result_id`(작성 중)·`round`·`value_count`·`input_count`·`writer_name`·`created`. 대기 먼저(입고일 최신순), 이어서 작성 중(지금 `result_search` 순서, 입고 아닌 수기 작성 포함 — 입고 칸은 빈 값)
- `job_count` → `{'count': waiting + working}`(`receipts.job_counts()`), 수입 검사작성 메뉴 권한
- `save` 새 작성 규칙(395–399행): `DigForm_id=form.id` → `DigForm__Code=form.Code` 로(같은 양식 코드·입고번호의 작성 중이 있으면 거절, 메시지 그대로)
- 품질(OUTGOING) 화면은 지금 `result_search` 목록 그대로

화면(`dig_form_write.html`, `FORM_TYPE == 'INCOMING'` 일 때만):
- 조회 카드: 양식(코드 단위 — `form_list latest_only=Y`), 입고번호/품목, 상태(전체·대기·작성 중)
- 그리드 `#workingGrid` 를 작업 그리드로: 첫 열 버튼 — 대기 [작성](`page.start(form_id, receipt_no)`), 작성 중 [열기](지금 `openResult`) — 이어서 상태·입고번호·입고일·품목코드·품목명·수량·양식·차수·입력 수·작성자·작성일
- [신규 작성] 은 그대로(수기). 저장·완료·삭제 뒤 목록과 배지를 다시 읽는다(372행 `refreshBadges`)

배지(`left_menu_class.html`): `refreshBadges()` 의 대상 `data-mid="wm_receipt"` → `wm_dig_form_incoming_write`, 호출 `/api/dig_form/dig_form` `action: 'job_count'`. 주석의 "입고 조회" 를 바꾼다

- [ ] 실패하는 테스트: job_list 대기·작성 중·수기·필터·kind / 품질 구분 거절 / job_count / 옛 버전 작성 중이 있으면 새 버전으로 같은 입고번호 새 작성 거절(규칙 변경)
- [ ] 구현 → 통과 → `receipts` 의 남은 `has_done`·`has_working`·`PENDING`·`pending_count` 를 grep 해 호출처가 없으면 지운다 → 테스트 재실행
- [ ] `verify_screen_js.js` → e2e `test_inspection_jobs.py`(`test_receipt.py` 의 `receipt_flow` 픽스처를 옮김): 매핑한 E2E 입고가 대기로 나옴 → [작성] → 저장하면 작성 중 → [완료] 하면 목록에서 빠짐 /
  배지가 수입 검사작성 작업 옆 / 상태 필터 / 품질 검사작성은 지금 목록 그대로(`test_dig_form.py` 기존 테스트 통과)
- [ ] 커밋 `feat: 수입 검사작성 작업 목록을 검사 작업(대기·작성 중)으로 바꾸고 배지를 옮긴다`

### Task 5: 문서

**Files:** `docs/FEATURES.md`(§1 메뉴 트리 16–50·§8 386행·§9.3 437–448), `docs/DATA_MODEL.md`(89행 N:M), `docs/DECISIONS.md`(사용자 결정 2026-10-21 행: 검사 작업·입고 내역·양식 기준 N:M — D12·D13·D15. 2026-10-19 입고 행(38)·메뉴 행(40)과 어긋나는 문장은 새 행이 이긴다고 적는다), `docs/STATUS.md`, `app/templates/definition/work_order.html`(64행 주석)

- [ ] 문서 → `verify_links.py`·`verify_korean_only.py` → 커밋 `docs: 검사 작업·입고 내역·양식 기준 품목 매핑을 문서에 적는다`
