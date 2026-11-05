# 검사 관리 메뉴 정리 · 비전검사항목 내부 탭 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검사 관리 메뉴를 4개 화면(검사양식 관리·비전검사항목 관리·수입검사 품목 지정·판정 코드 관리)으로 정리하고, 비전검사항목을 메뉴에서 열면 한 탭 안의 내부 탭으로 하위 화면을 오가게 한다.

**Architecture:** 모델 변경 없음(시드·화면·API만). 검사양식 관리는 기존 `wm_dig_form_incoming_form` 코드를 구분 없는 화면 하나로 쓰고 `seed_initial` 이 품질 검사양식 메뉴 권한을 옮긴다. 비전검사항목 홈(`data/item.html`)은 머리 카드 + `nav-tabs nav-bordered` 내부 탭 컨테이너가 되고, 하위 화면은 `?embed=1` iframe 으로 처음 누를 때 싣는다. 모델 매핑은 `vision/model_mapping` 의 로직을 공개 함수로 바꿔 `item/item_admin` 이 재사용한다.

**Tech Stack:** Django 5.2 템플릿 · jQuery · Bootstrap 5 · WeZonGrid · Playwright e2e

**Spec:** 사용자 결정 2026-10-21(대화 E1–E10, 모두 추천안). 요약:
- E1 검사양식 관리 통합 — `wm_dig_form_incoming_form` 재사용, 품질 쪽 권한을 옮김(높은 권한), W 하나로 두 구분
- E2 목록 `구분` 열·검색 조건 `구분`, 등록 때 구분 선택(저장 뒤 고정), [작성]은 행 구분의 검사작성 탭
- E3 항목결과 코드관리 → **판정 코드 관리** / E4 품목 검사양식 매핑 → **수입검사 품목 지정** / E5 검사 분류 관리 → **비전검사항목 관리**
- E6 순서: 검사양식 관리 → 비전검사항목 관리 → 수입검사 품목 지정 → 판정 코드 관리
- E7 비전검사항목 상세에 AI 모델 칸 — [수정] 때만 Wezard 목록, 측정 항목 숨김, Wezard 불가 시 모델 칸만 막음, 기존 매핑 화면 유지
- E8 메뉴에서 비전검사항목 → 탭 하나(항목명), 안에 [홈|데이터 목록|라벨링 작업|검수 작업|스냅샷 관리](권한 있는 것만, 측정은 홈·데이터 목록), 처음 누를 때 싣고 상태 유지, 화면 버튼 제거. **디자인 구조상 어색함이 없게**
- E9 홈 설명은 기본 접힘, 펴고 접기, 상태 기억 안 함
- E10 규칙 "메뉴로 열 수 없는 화면을 두지 않는다" — DESIGN 체크리스트·AGENTS [4]·DECISIONS

## Global Constraints

- 공유 개발 DB 에 `seed_initial` 을 돌리지 않는다 — 병합 뒤 담당자
- 화면 문구 `~합니다` 체, 사용자 값은 `.text()`
- 색은 토큰(`tokens.css`), 새 hex 금지(`verify_tokens.py`)
- 테스트는 `--settings=configurations.test_settings`, 고친 범위만. e2e 는 작업 공간 서버(8124, `E2E_BASE_URL`)
- 커밋 메시지 한국어 Conventional Commits, AI 표시 없음

---

### Task 1: 검사양식 관리 통합 (E1·E2)

**Files:**
- Modify: `domain/gui.py` (DIG_FORM_SCREENS·DIG_FORM_MENU_CODES·menu_init·taskview map)
- Modify: `app/views/dig_form/dig_form.py:27-31` (`require_write`)
- Modify: `app/views/system/form_edit.py` (read 에 `form_type`·`form_type_label`)
- Modify: `app/templates/system/form_edit.html` (구분 검색·열·등록 선택·openWrite·save)
- Modify: `domain/management/commands/seed_initial.py` (MENU_TREE·권한 이전)
- Test: `tests/test_dig_form.py`

**Interfaces:**
- Produces: `domain.gui.DIG_FORM_EDIT_MENU = 'wm_dig_form_incoming_form'`; `DIG_FORM_SCREENS` 는 write·result 둘; `DIG_FORM_MENU_CODES = (DIG_FORM_EDIT_MENU,) + write/result × 구분`
- `require_write(user, form_types, kind)` — `kind == 'form'` 이면 `DIG_FORM_EDIT_MENU` 의 W 만 본다

- [ ] **Step 1: 테스트를 바꾼다(RED)** — `wm_dig_form_outgoing_form` 권한 부여를 `wm_dig_form_incoming_form` 으로 바꾸고 기대값을 고친다
  - `FormEditVersionTest.setUp` 의 메뉴를 `wm_dig_form_incoming_form` 으로
  - `test_새_양식은_그_구분의_검사양식_쓰기_권한이_있어야_한다` → `test_새_양식은_검사양식_관리_쓰기_권한이_있어야_한다`: 권한을 `wm_dig_form_outgoing_write` 로 바꿔 두고 403
  - `test_칸_설정은_양식_구분의_검사양식_쓰기_권한이_있어야_한다` → 품질 양식도 검사양식 관리 W 로 고친다(200)
  - `SeedInitialDigFormTest`: 메뉴 6개 → 5개(`wm_dig_form_incoming_form: ('검사 관리', '검사양식 관리')`), 품질 검사양식 메뉴 권한이 있던 그룹은 이전 뒤 `wm_dig_form_incoming_form` 을 갖는다(R 만 있던 그룹에 RW 가 이기는 경우 포함)
  - `test_수입_품질_메뉴는…`: form 은 `('검사양식 관리', 'system/form_edit.html', {}, )` 구분 없음, `wm_dig_form_outgoing_form` 은 `None`
  - 읽기: `read` 행에 `form_type`·`form_type_label`('수입검사'/'품질검사')

```python
def test_품질_검사양식_권한은_검사양식_관리로_옮긴다(self):
    group = UserGroup.objects.create(Code='qc2', Name='품질2')
    UserGroupMenu.objects.create(UserGroup=group, MenuCode='wm_dig_form_outgoing_form', AuthCode='RW')
    UserGroupMenu.objects.create(UserGroup=group, MenuCode='wm_dig_form_incoming_form', AuthCode='R')
    call_command('seed_initial', stdout=io.StringIO())
    self.assertEqual(UserGroupMenu.objects.get(UserGroup=group, MenuCode='wm_dig_form_incoming_form').AuthCode, 'RW')
    self.assertFalse(UserGroupMenu.objects.filter(MenuCode='wm_dig_form_outgoing_form').exists())
```

- [ ] **Step 2: 돌려 실패를 본다** — `python manage.py test tests.test_dig_form --settings=configurations.test_settings`

- [ ] **Step 3: 구현**

```python
# domain/gui.py
DIG_FORM_TYPES = {'INCOMING': '수입', 'OUTGOING': '품질'}
DIG_FORM_TYPE_LABELS = {'INCOMING': '수입검사', 'OUTGOING': '품질검사'}
# 검사양식 관리 — 수입·품질 양식을 한 화면에서 다룬다. 코드는 수입 검사양식 관리 시절 그대로다(권한·즐겨찾기 유지, 2026-10-21)
DIG_FORM_EDIT_MENU = 'wm_dig_form_incoming_form'
DIG_FORM_SCREENS = (('write', '검사작성 작업', 'dig_form/dig_form_write.html'),
                    ('result', '검사결과 확인', 'dig_form/dig_form_result.html'))
DIG_FORM_MENU_CODES = (DIG_FORM_EDIT_MENU,) + tuple(dig_form_menu_code(t, kind) for t in DIG_FORM_TYPES for kind, _n, _t in DIG_FORM_SCREENS)
# menu_init: gui_dc[DIG_FORM_EDIT_MENU] = cls.gui_item('검사양식 관리', 'system/form_edit.html')
# taskview: m['system/form_edit'] = [DIG_FORM_EDIT_MENU]
```

```python
# app/views/dig_form/dig_form.py
def require_write(user, form_types, kind='write'):
    codes = [DIG_FORM_EDIT_MENU] if kind == 'form' else [dig_form_menu_code(t, kind) for t in form_types]
    if not any('W' in (AccountService.check_user_auth(user, code) or '') for code in codes):
        raise PermissionDenied
```

```python
# seed_initial.handle — 메뉴 행을 만든 뒤, stale 정리 전에
# 품질 검사양식 관리는 검사양식 관리로 합쳤다(사용자 결정 2026-10-21) — 그 권한을 옮긴다. 둘 다 있으면 높은 쪽
for old in UserGroupMenu.objects.filter(MenuCode='wm_dig_form_outgoing_form'):
    merged, created = UserGroupMenu.objects.get_or_create(UserGroup=old.UserGroup, MenuCode=DIG_FORM_EDIT_MENU,
                                                          defaults={'AuthCode': old.AuthCode})
    if not created and 'W' in old.AuthCode and 'W' not in merged.AuthCode:
        merged.AuthCode = old.AuthCode
        merged.save(update_fields=['AuthCode'])
```

  - `form_edit.py` read SQL: `, f."FormType" as form_type` + 행마다 `form_type_label = DIG_FORM_TYPE_LABELS.get(...)`
  - `form_edit.html`:
    - 검색 카드에 `#cboFormType`(전체/수입검사/품질검사), `searchMainData` 가 `form_type: $('#cboFormType').val()`
    - 목록 그리드 `양식코드` 앞에 `{ dataField: 'form_type_label', headerText: '구분', width: 70, align: 'center' }`
    - 편집기 기본정보에 `#form_type` select(필수). 새 양식만 고를 수 있고 수정·새 버전은 `disabled`
    - save payload `form_type: $form.find('#form_type').val()`, 새 양식에서 비었으면 `'양식 구분을 골라 주세요.'`
    - `openWrite(row)` — `row.form_type` 으로 `wm_dig_form_<구분>_write`·제목
    - `{{ gparam.form_type }}` 를 남기지 않는다

- [ ] **Step 4: 돌려 통과를 본다** — 같은 명령 + `node scripts/verify/verify_screen_js.js`
- [ ] **Step 5: 커밋** — `feat: 수입·품질 검사양식 관리를 검사양식 관리 하나로 합치고 목록에 구분을 보인다`

### Task 2: 검사 관리 메뉴 이름·순서 (E3–E6)

**Files:**
- Modify: `domain/gui.py` (이름 3개), `domain/management/commands/seed_initial.py` (MENU_TREE 순서·이름·주석)
- Modify: `app/templates/system/product_form.html:7`(제목 → `{{ gui.gui_name }}`), `app/templates/dig_form/judge_code.html:18`(목록 제목 `판정 코드 목록`), `app/templates/system/form_edit.html:2633`(안내 문구 화면 이름)
- Modify: 모듈 docstring·주석의 옛 화면 이름(`product_form.py`·`judge_code.py`·`category.py`·`item_list.html`·`services/judge_code.py`)
- Test: `tests/test_dig_form.py`(SeedInitialDigFormTest), `tests/test_menu_tree.py`, `tests/e2e/test_menu.py`(TestItemAdminMenu)

- [ ] **Step 1: 테스트(RED)** — 시드 뒤 검사 관리 폴더의 메뉴 이름 순서가 정확히 아래와 같다

```python
names = list(MenuItem.objects.filter(MenuFolder__FolderName='검사 관리').order_by('_order')
             .values_list('MenuName', flat=True))
self.assertEqual(names, ['검사양식 관리', '비전검사항목 관리', '수입검사 품목 지정', '판정 코드 관리'])
```
  (정렬 필드 이름은 `MenuItem` 모델을 보고 맞춘다)
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현** — MENU_TREE 검사 관리:
```python
('검사 관리', 'uil-layer-group', [
    ('wm_dig_form_incoming_form', '검사양식 관리'),
    ('wm_data_item', '비전검사항목 관리'),
    ('wm_product_form', '수입검사 품목 지정'),
    ('wm_dig_form_judge_code', '판정 코드 관리'),
]),
```
  gui 이름도 같게. e2e `test_검사_분류_관리는…` → `test_검사_관리는_양식_비전검사항목_품목_판정_순서다`
- [ ] **Step 4: 통과 확인** + `python scripts/verify/verify_menu.py`(코드 목록만 보므로 DB 미반영이어도 코드 단위 OK) 
- [ ] **Step 5: 커밋** — `feat: 검사 관리 메뉴를 검사양식·비전검사항목·수입검사 품목 지정·판정 코드 순으로 정리하고 이름을 바꾼다`

### Task 3: 비전검사항목 상세에서 AI 모델 매핑 (E7)

**Files:**
- Modify: `app/views/vision/model_mapping.py` (`_deployed` → `deployed_models`, `_save_mapping` → `save_mapping`)
- Modify: `app/views/item/item_admin.py` (detail 에 `model_name`·`mappable`, READ action `models`, update 의 `model_name`)
- Modify: `app/templates/data/item_list.html` (상세 카드 `#model_name` select, [수정] 때 목록)
- Test: `tests/test_item_api.py` (또는 item_admin 테스트가 있는 모듈), `tests/test_vision_model_mapping.py`(이름만)

**Interfaces:**
- `deployed_models(item) -> (list[{name, version, dataset_external_ref, recommended}], message: str)`
- `save_mapping(posparam: dict) -> {'success': bool, 'message'?: str, 'id'?: int}`
- `/api/item/item_admin?action=models&item_id=` → `{'models': [...], 'message': str}` (GET)
- `update` — `model_name` 키가 있고 지금 활성 매핑 이름과 다를 때만 `save_mapping`; 실패면 `ItemApiError(message)` 로 전체 저장을 되돌린다

- [ ] **Step 1: 테스트(RED)** — Wezard 가짜 게이트웨이(`patch('app.views.vision.model_mapping.get_inference_gateway')`)로
  - detail: 매핑 없으면 `model_name == ''`, `mappable` True; 측정 항목은 `mappable` False
  - models: `wz-det` 이 목록에 있다
  - update(model_name='wz-det') → 활성 매핑 `wz-det`; update(model_name 없음) → 매핑 그대로·Wezard 호출 없음; update(model_name='') → 해제
  - update(model_name='없는모델') → 400, 설명도 저장되지 않는다
- [ ] **Step 2: 실패 확인**
- [ ] **Step 3: 구현**

```python
# item_admin._update 안, item.save 앞
if 'model_name' in context.posparam and _mappable(item):
    name = (context.posparam.get('model_name') or '').strip()
    if name != _active_model(item):
        result = model_mappings.save_mapping({'item_id': item.id, 'model_name': name})
        if not result.get('success'):
            raise ItemApiError(result.get('message') or '모델을 저장하지 못했습니다.')
```
  화면: 상세 카드에 `AI 모델` select(`#model_name`, DetailForm fields 에 추가). 조회 때는 현재 이름 한 줄 옵션, [수정]을 누르면 `models` 를 읽어 채운다(`(매핑 없음)` + 목록, 추천 표시). message 가 있으면 select 를 막고 칸 아래에 안내. 측정 항목은 칸을 숨기고 `model_name` 을 보내지 않는다
- [ ] **Step 4: 통과 확인** — `tests.test_item_api tests.test_vision_model_mapping`
- [ ] **Step 5: 커밋** — `feat: 비전검사항목 관리 상세에서 AI 모델 매핑을 고친다`

### Task 4: 비전검사항목 내부 탭 · 설명 접기 (E8·E9)

**Files:**
- Modify: `app/templates/app/layout_page.html` (`<body>` 에 `embedded` 클래스 — `request.GET.embed == '1'`)
- Modify: `app/static/assets/css/SF-Custom.css` (`.embedded` 규칙)
- Modify: `app/templates/data/item.html` (머리 카드 + 내부 탭 + 홈 패널 + 설명 접기)
- Modify: `app/views/system/menus.py`·`app/views/item/item_home.py` docstring(버튼 → 탭)
- Test: `tests/e2e/test_menu.py`(TestItemSubtree), `tests/e2e/test_write_paths.py`(설명), 필요하면 `tests/test_item_api.py`

**디자인:**
```
┌ card mb-2 ───────────────────────────────────────────────────────────┐
│ [대표] 항목명  유형 · 상태  ☆                       [비전검사항목 편집]* │  card-header (* 홈 탭에서만)
│ 홈 │ 데이터 목록 │ 라벨링 작업 │ 검수 작업 │ 스냅샷 관리                 │  ul.tab_links.nav.nav-tabs.nav-bordered (카드 아래 변에 붙음)
└──────────────────────────────────────────────────────────────────────┘
 홈 패널: [설명 ▾](접힘 카드) → 요약 카드 → 배정 인원·라벨 클래스 → 최근 스냅샷 → 최근 데이터
 다른 패널: iframe /gui/<code>/?inspection_item=<id>&embed=1 — 처음 누를 때 src, 이후 그대로(상태 유지)
```
- 하위 화면은 `embedded` 일 때 자기 제목 줄(`.header-title`: 화면 이름·항목명·별)을 감추고, 제목뿐인 `card-header` 는 통째로 감춘다. 라벨링처럼 머리에 버튼이 있는 화면은 버튼만 남는다. `.ifram-wrapper` 패딩 0(머리 카드와 왼쪽 선이 맞는다)
- iframe 높이 = 창 높이 − iframe 위치 − 아래 여백(12px). 탭 전환·창 크기 변경 때 다시 맞추고, 전환 때 바깥 스크롤을 맨 위로. 라벨링은 iframe 안에서 세로 스크롤 없이 채운다(DESIGN §1)
- 홈의 [전체 보기]·최근 데이터 썸네일은 해당 내부 탭으로 전환하고 그 주소(예: `image_id`)로 iframe 을 바꾼다
- 홈 탭으로 돌아오면 요약을 다시 읽는다(다른 탭에서 작업한 결과)
- 탭 머리 = `홈` + `item.screens`(서버가 권한·측정 여부로 거른 목록) — 그대로 쓴다
- 셸 탭 제목은 항목명 하나(이미 `_leaf` 의 tabTitle)

- [ ] **Step 1: e2e 를 바꾼다(RED)**
  - `test_비전검사항목을_누르면_홈이_열리고_버튼으로_라벨링을_연다` → `…내부_탭으로_라벨링을_연다`: 홈 프레임에서 `#itemTabs [data-screen="wm_data_labeling"]` 클릭 → 셸 탭은 그대로 1개(항목명), 홈 프레임 안 iframe 의 `.labeling-layout` 항목 id 확인, 라벨링 프레임의 `.header-title` 이 보이지 않는다, 바깥 문서에 세로 스크롤이 없다
  - 설명: 기본 접힘(`#itemDescCollapse` 에 `show` 없음), 토글 뒤 `둘째 줄` 보임
- [ ] **Step 2: 8124 서버로 실패 확인**
- [ ] **Step 3: 구현** (위 디자인)
- [ ] **Step 4: e2e 통과 + 스크린샷(1920×911, 1366) 으로 어색한 곳(이중 여백·이중 테두리·제목 중복·스크롤 두 개) 확인**
- [ ] **Step 5: 커밋** — `feat: 비전검사항목을 한 탭 안의 내부 탭(홈·데이터 목록·라벨링·검수·스냅샷)으로 열고 홈 설명을 접는다`

### Task 5: 메뉴 도달 규칙 · 문서 (E10)

**Files:**
- Modify: `DESIGN.md` §9.1(체크리스트 한 줄)·§1 원칙(필요하면), `AGENTS.md` [4](한 줄), `docs/DECISIONS.md`(2026-10-21 결정 행), `docs/FEATURES.md`(메뉴 트리·검사양식·비전검사항목 관리·홈), `docs/STATUS.md`, `docs/ARCHITECTURE.md`(권한 매핑 설명이 있으면)
- 규칙 문구: "메뉴로 열 수 없는 화면을 두지 않는다. 모든 화면은 좌측 메뉴 항목이거나 메뉴 화면 안의 탭이다. 다른 화면의 버튼·링크로만 열리는 화면은 두지 않는다(팝업·모달, 메뉴에서 내린 화면 제외)."
- [ ] **Step 1: 문서 수정** — 옛 이름(`항목결과 코드관리`·`품목 검사양식 매핑`·`검사 분류 관리`·`수입/품질 검사양식 관리`)을 현행 문서에서 바꾼다(`docs/archive/`·`docs/superpowers/` 제외)
- [ ] **Step 2: `python scripts/verify/verify_links.py`·`verify_korean_only.py`·`verify_naming.py`**
- [ ] **Step 3: 커밋** — `docs: 검사 관리 메뉴 정리·비전검사항목 내부 탭·메뉴 도달 규칙을 적는다`

### Task 6: 검증

- [ ] 단위: `tests.test_dig_form tests.test_menu_tree tests.test_item_api tests.test_vision_model_mapping tests.test_product_form_view tests.test_inspection_category`
- [ ] 정적: verify_screen_js·menu·permission_map·response_keys·tokens·korean_only·links·naming
- [ ] 8124 서버 e2e: `test_menu.py test_dig_form.py test_inspection_category.py test_write_paths.py test_crud.py test_data_screens.py test_grid_common.py test_workflow.py`
- [ ] 화면: verify_modals·verify_buttons·verify_dig_form_width·verify_layout_stable(main 8123 대비)
- [ ] 권한·공용 레이아웃(`layout_page.html`·`SF-Custom.css`)을 고쳤으므로 전체 단위 테스트는 사용자 승인 뒤
