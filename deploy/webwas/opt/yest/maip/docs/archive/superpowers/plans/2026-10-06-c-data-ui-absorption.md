# C — 데이터 화면 구조 흡수: 조사 결과와 재설계

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 데이터 화면의 확인 질문이 브라우저 기본 대화상자(`10.10.10.20:8123 내용:`)로 뜨는 결함을 없애고, 제품의 확인창(`Alert.confirm`)과 같은 모양으로 맞춘다.

**Architecture:** 처음 계획(C-1 `DataUI.confirm → Alert.confirm`, C-2 `DataUI.showMessage → Notify`, C-3 셸 교체)은 실측에서 전제가 깨졌다(§1). 확인창은 **네이티브 `<dialog>` 를 기판으로 유지하고 모양만 `Alert.confirm` 과 같게** 만든다. C-2·C-3 은 하지 않는 것을 권한다.

**Tech Stack:** jQuery + 네이티브 `<dialog>`, Playwright(e2e · `verify_modals.py`)

**근거 문서:** [09_UI_DESIGN_SYSTEM.md](../../09_UI_DESIGN_SYSTEM.md) §2.3·§6 Phase 2·E-2

## Global Constraints

- D-2: **레이아웃은 건드리지 않는다.** 레이아웃 이동 0건이 합격 기준이다(`verify_layout_stable.py`)
- 사용자에게 보이는 문구는 `~합니다` 체
- 모달 동작 규칙(Phase 2): 백드롭 `--modal-backdrop`(실효 알파 .45) · Esc 로 닫힘 · 열 때 포커스가 모달 안 · 푸터 **취소 → 확인** · 확인 버튼은 브랜드 빨강 채움(`rgb(218, 33, 41)`)
- 동기 Ajax 금지, 테스트는 `--settings=configurations.test_settings`

---

## 1. 실측으로 깨진 전제

### 1.1 `Alert.confirm` 은 열린 `<dialog>` 위로 올라오지 못한다

`showModal()` 로 연 네이티브 `<dialog>` 는 브라우저의 **최상위 레이어(top layer)**
에 놓이고 문서의 나머지를 **inert**(누를 수 없음)로 만든다. `Alert.confirm` 은
`body` 에 붙는 Bootstrap 모달이라 z-index 를 아무리 올려도 그 아래에 깔린다.

데이터 화면의 확인 질문 4곳 중 1곳이 **열린 대화상자 안에서** 뜬다.

| 확인 질문 | 위치 | 열린 `<dialog>` 안인가 |
|---|---|---|
| 검사항목 삭제 요청 | `item_modal_edit.html:24` (`#settingsDialog` 안의 폼) | **예** |
| 데이터 삭제 | `image.html:224` (상세 패널의 폼) | 아니오 |
| 미저장 이동 · 빈 제출 | `labeling.html:496,674` | 아니오 |
| 스냅샷 만들기 | `snapshot.html:505` | 아니오 |

그대로 `Alert.confirm` 으로 바꾸면 검사항목 삭제 요청은 **확인창이 뒤에 깔려
누를 수 없게 된다.** 지금의 `window.confirm` 보다 나빠진다. 기판이 같은
네이티브 `<dialog>` 여야 나중에 연 것이 위로 쌓인다.

### 1.2 `Notify` 도 같은 이유로 대화상자 안에서 보이지 않는다

`Notify` 는 `body` 의 `#commonToastContainer`(z-index 1200)에 붙는다. 데이터
화면의 토스트(`DataUI.showMessage`)는 이 문제를 이미 풀어 두었다 — 열린
대화상자가 있으면 **그 안으로 옮겨 붙고**, 없으면 `popover` 로 최상위 레이어에
올린다(`data/common.js` `showMessage`). 배정 인원 추가(`#addInspectionItemMemberDialog`
안)의 "배정 인원을 추가했습니다." 가 그 경로다. `Notify` 로 바꾸면 이 메시지들이
사라진다.

### 1.3 셸 교체(C-3)는 이름 충돌만이 아니다

`data/_base.html` 에 MES `assets/js/common.js` 를 싣는 순간 일어나는 일:

| 무엇 | 결과 |
|---|---|
| `let AjaxUtil`(MES) vs `window.AjaxUtil`(데이터) | 전역 `let` 이 이긴다. 데이터 화면 30곳이 MES 판을 부르게 되는데 **계약이 다르다** — MES 판은 Promise 를 돌려주지 않고(`home.html:289` 가 `return` 값을 쓴다), 실패 콜백에 `(req, status, error)` 를 넘기며(데이터 화면은 `error.message` 를 읽는다), `postJsonAsyncData`·`putJsonAsyncData`·`putAsyncData` 가 없다 |
| `Ajax.enableErrorHandler()` | 전역 Ajax 오류 처리기가 붙어 데이터 화면의 실패마다 **오류 창이 하나 더** 뜬다 |
| `i18n.holdReady()` · `initialize()` | 라벨 자원 두 건을 받아올 때까지 `ready` 를 붙잡는다 |
| `$.validator` 참조 | `jquery.validate` 를 함께 싣지 않으면 `ready` 에서 예외 |

얻는 것은 셸 코드가 한 벌이 되는 것뿐이고 사용자에게 보이는 차이는 없다. D-2 와
§4 가 이미 "데이터 CSS 를 흡수하지 않는다"로 정했고, 셸 JS 도 같은 판단이 맞다.

## 2. 재설계

| 단계 | 처음 계획 | 바꾼 계획 |
|---|---|---|
| C-1 | `DataUI.confirm → Alert.confirm` | **`#confirmDialog` 를 네이티브 `<dialog>` 로 만들고 `Alert.confirm` 마크업·클래스를 그대로 입힌다** |
| C-2 | `DataUI.showMessage → Notify` | **하지 않는다** (1.2) |
| C-3 | 셸 교체 | **하지 않는다** (1.3). 09 문서에 이유를 남긴다 |

C-1 은 새 기능이 아니라 **빠진 엘리먼트 하나**다. `confirmDialog()` 는 이미
`<dialog>` 를 열고 Promise 로 답하도록 짜여 있다(`data/common.js:399`). 없던 것은
`#confirmDialog` 마크업뿐이다 — 토스트(`getToast`)처럼 처음 쓸 때 만든다.

모양은 `Alert.confirm` 의 마크업(`common.js` `_ensureModalElements`)을 그대로 쓴다.
`.common-alert-modal .modal-header`(브랜드 빨강 띠)·`.modal-content`·`btn-light`/
`btn-primary` 는 `SF-Custom.css`·`app.min.css` 에 있고 데이터 셸도 두 파일을 싣는다.
더할 CSS 는 `<dialog>` 의 기본 테두리·여백을 지우고 폭을 `modal-sm`(300px)에
맞추는 것과 `::backdrop` 뿐이다.

경고 아이콘(`ri-alert-line`)은 뺀다. remixicon 을 데이터 셸이 싣지 않는다 —
아이콘 하나를 위해 글꼴 파일을 더 싣지 않는다.

---

## Task 1: 확인창 엘리먼트

**Files:**
- Modify: `app/static/data/common.js` (`confirmDialog` 위에 `getConfirmDialog` 추가, `confirmDialog` 첫 줄 교체)
- Modify: `app/static/data/main.css` (`.form-dialog::backdrop` 다음 줄에 4줄)
- Test: `tests/e2e/test_crud.py` (`TestDataConfirm` 클래스 추가)

**Interfaces:**
- Consumes: `DataUI.confirm(message) → Promise<boolean>` (기존, 바꾸지 않는다)
- Produces: `#confirmDialog` · `#confirmDialogMessage` · `#confirmDialogCancel` · `#confirmDialogOk` (Task 2 의 `verify_modals.py` 가 쓴다)

- [ ] **Step 1: 실패하는 e2e 를 쓴다**

`tests/e2e/test_crud.py` 끝에 추가한다.

```python
class TestDataConfirm:
    """데이터 화면의 확인 질문은 브라우저 기본 창이 아니라 제품 확인창으로 뜬다.

    `#confirmDialog` 가 어느 템플릿에도 없어 `DataUI.confirm` 이 `window.confirm`
    으로 떨어지고 있었다(09 §6 E-2).
    """

    def test_스냅샷_확인은_브라우저_기본_창이_아니다(self, page, base_url, admin_password):
        native = []
        page.on('dialog', lambda d: (native.append(d.message), d.dismiss()))
        open_screen(page, base_url, admin_password, 'wm_data_snapshot')

        page.click('#createSnapshot')
        page.wait_for_selector('#confirmDialog[open]', timeout=5000)

        assert native == []
        order = page.eval_on_selector_all('#confirmDialog button', 'bs => bs.map(b => b.id)')
        assert order == ['confirmDialogCancel', 'confirmDialogOk']
        page.click('#confirmDialogCancel')
        page.wait_for_selector('#confirmDialog', state='hidden', timeout=3000)

    def test_대화상자_안의_확인창은_그_위에_뜬다(self, page, base_url, admin_password):
        open_screen(page, base_url, admin_password, 'wm_data_item_detail')
        page.click('#projectHomeEdit')
        page.wait_for_selector('#settingsDialog[open]', timeout=5000)

        page.click('#projectSettingsDeleteButton')
        page.wait_for_selector('#confirmDialog[open]', timeout=5000)

        # 최상위 레이어의 맨 위에 있어야 누를 수 있다.
        on_top = page.evaluate("""() => {
            const b = document.getElementById('confirmDialogCancel').getBoundingClientRect();
            return document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2).id;
        }""")
        assert on_top == 'confirmDialogCancel'
        page.click('#confirmDialogCancel')
        assert page.evaluate("() => document.getElementById('settingsDialog').open")
```

`open_screen` 은 `/gui/<code>/` 로 연다. 상세 화면이 검사항목 선택을 요구하면
`?project=3`(seed_demo 의 검사항목)을 붙인다 — Step 2 에서 실패 이유로 확인한다.

- [ ] **Step 2: 실패를 확인한다**

Run: `python -m pytest tests/e2e/test_crud.py -k TestDataConfirm -q`
Expected: 두 건 모두 FAIL — `#confirmDialog[open]` 대기 시간 초과(기본 창이 뜨고 `native` 에 메시지가 쌓인다)

- [ ] **Step 3: 엘리먼트를 처음 쓸 때 만든다**

`data/common.js` 의 `var activeConfirm = null;` 바로 위에 추가한다.

```js
  // 제품 확인창(`Alert.confirm`)과 같은 마크업이다. 기판만 네이티브 <dialog> 다 —
  // 열린 대화상자 안에서 묻는 경우(검사항목 삭제 요청)가 있고, Bootstrap 모달은
  // 최상위 레이어 아래에 깔려 누를 수 없다.
  function getConfirmDialog() {
    var dialog = document.getElementById("confirmDialog");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "confirmDialog";
    dialog.className = "common-alert-modal confirm-dialog";
    dialog.setAttribute("aria-labelledby", "confirmDialogTitle");
    dialog.innerHTML = '<div class="modal-content">'
      + '<div class="modal-header"><h5 class="modal-title" id="confirmDialogTitle">확인</h5></div>'
      + '<div class="modal-body p-4"><div class="text-center">'
      + '<p class="mt-3 mb-4" id="confirmDialogMessage"></p>'
      + '<div class="d-flex justify-content-center gap-2">'
      + '<button type="button" class="btn btn-light" id="confirmDialogCancel">취소</button>'
      + '<button type="button" class="btn btn-primary" id="confirmDialogOk">확인</button>'
      + '</div></div></div></div>';
    document.body.appendChild(dialog);
    return dialog;
  }
```

`confirmDialog` 의 첫 줄을 바꾼다.

```js
    var dialog = getConfirmDialog();
```

그 다음 줄의 `!dialog ||` 는 지운다(엘리먼트가 항상 있다). `showModal` 이 없는
브라우저에서 `window.confirm` 으로 떨어지는 분기는 남긴다.

- [ ] **Step 4: `<dialog>` 기본 모양을 지운다**

`data/main.css` 의 `.form-dialog::backdrop` 줄 다음에 추가한다.

```css
.confirm-dialog { width: 300px; max-width: calc(100vw - 32px); padding: 0; border: 0; border-radius: 10px; background: transparent; }
.confirm-dialog::backdrop { background: var(--modal-backdrop); }
.confirm-dialog p { white-space: pre-line; }
```

`white-space: pre-line` 은 `Alert` 가 `\n` 을 `<br>` 로 바꾸는 것과 같은 효과다
(`textContent` 로 넣으므로 `<br>` 는 못 쓴다).

- [ ] **Step 5: 통과를 확인한다**

Run: `python -m pytest tests/e2e/test_crud.py -k TestDataConfirm -q`
Expected: 2 passed

- [ ] **Step 6: 커밋**

```bash
git add app/static/data/common.js app/static/data/main.css tests/e2e/test_crud.py
git commit -m "fix: 데이터 화면 확인 질문이 브라우저 기본 창으로 뜨던 문제를 고친다"
```

## Task 2: 모달 규칙 검사에 다섯 번째 계열을 넣는다

**Files:**
- Modify: `scripts/verify_modals.py` (`CASES` 에 한 항목, 푸터 순서·확인 버튼 색 검사에 한 블록)

- [ ] **Step 1: 케이스를 더한다**

`CASES` 의 첫 항목(네이티브 dialog) 다음에 추가한다.

```python
    {
        # 데이터 화면의 확인창. Alert.confirm 과 모양은 같고 기판은 <dialog> 다.
        'label': '데이터 확인창 (DataUI.confirm)',
        'url': '/gui/wm_data_item/?project=3',
        'open': "() => { DataUI.confirm('본문'); }",
        'is_open': "() => { const d = document.getElementById('confirmDialog'); return !!d && d.open; }",
        'root': '#confirmDialog',
        'backdrop': ("() => { const d = document.getElementById('confirmDialog');"
                     " if (!d) return null; const s = getComputedStyle(d, '::backdrop');"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': "() => document.getElementById('confirmDialog').close()",
    },
```

- [ ] **Step 2: 순서·색 검사를 더한다**

`# 푸터 순서와 주요 버튼 색은 Confirm/Alert 에서 본다.` 블록 **앞에** 추가한다.

```python
        page.goto(BASE + '/gui/wm_data_item/?project=3', wait_until='domcontentloaded', timeout=25000)
        page.wait_for_timeout(2600)
        page.evaluate("() => { DataUI.confirm('본문'); }")
        page.wait_for_timeout(600)
        order = page.evaluate("() => Array.from(document.querySelectorAll('#confirmDialog button')).map(b => b.id)")
        if order != ['confirmDialogCancel', 'confirmDialogOk']:
            violations.append(('데이터 확인창', '푸터 순서 {} (기대 취소 → 확인)'.format(order)))
        ok_bg = page.evaluate(
            "() => getComputedStyle(document.getElementById('confirmDialogOk')).backgroundColor")
        if _norm(ok_bg) != _norm(BRAND):
            violations.append(('데이터 확인창', '확인 버튼 {} (기대 {})'.format(ok_bg, BRAND)))
        page.evaluate("() => document.getElementById('confirmDialog').close()")
```

- [ ] **Step 3: 돌린다**

Run: `python scripts/verify_modals.py`
Expected: `모달 규칙 위반 0건` / `PASS`. 확인 버튼 색이 다르면 `data/main.css` 의
`button` 규칙이 `btn-primary` 를 덮는 것이다 — `.confirm-dialog .btn-primary` 로
`var(--brand-primary)` 를 걸어 맞춘다.

- [ ] **Step 4: 커밋**

```bash
git add scripts/verify_modals.py
git commit -m "test: 모달 규칙 검사에 데이터 화면 확인창을 넣는다"
```

## Task 3: 회귀 확인과 문서

- [ ] **Step 1: 레이아웃** — `verify_layout_stable.py capture` 를 Task 1 전(`main`)과 후에 떠서 `compare`. 확인창은 열 때만 생기므로 이동 0건이어야 한다
- [ ] **Step 2: 나머지 검증** — 단위 테스트, `verify_screen_js.js`, `capture_ui.py`, e2e 전체
- [ ] **Step 3: 문서** — `09_UI_DESIGN_SYSTEM.md` E-2 의 "되살릴 자리는 C 의 `Alert.confirm`" 을 바로잡고, C 절을 새로 둬 §1 의 세 사실(최상위 레이어 · `Notify` · 셸 JS 충돌)과 C-2·C-3 을 하지 않은 이유를 남긴다. `IMPLEMENTATION_STATUS.md` 에 한 줄
- [ ] **Step 4: 커밋**

```bash
git add docs/09_UI_DESIGN_SYSTEM.md docs/IMPLEMENTATION_STATUS.md
git commit -m "docs: 데이터 확인창 기판과 셸 교체를 하지 않는 이유를 남긴다"
```
