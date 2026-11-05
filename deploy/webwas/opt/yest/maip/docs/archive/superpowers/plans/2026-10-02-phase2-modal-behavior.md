# Phase 2 — 모달 동작 통일 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 모달 네 계열의 백드롭·키보드·버튼을 하나의 규칙으로 맞춘다. 구현체(기판)는 바꾸지 않는다.

**Architecture:** 백드롭은 `tokens.css` 의 단일 토큰 `--modal-backdrop` 에서 세 곳(네이티브 `::backdrop` · Bootstrap `.modal-backdrop` · `PopupDraggable` 의 투명 강제 해제)이 파생된다. 키보드는 `common.js` 의 `bootstrap.Modal` 생성 옵션 `keyboard: false` 를 `true` 로 돌려 Esc 를 연다(네이티브 `<dialog>` 는 이미 된다). 버튼 색·순서는 `common.js` 가 만드는 Alert/Confirm 마크업과 `SF-Custom.css` 의 `.btn-info`·`.text-info` 에서만 나온다.

**Tech Stack:** 순수 CSS 커스텀 프로퍼티 · jQuery · Bootstrap 5 Modal · 네이티브 `<dialog>` · Playwright(검증)

**Spec:** [docs/09_UI_DESIGN_SYSTEM.md](../../09_UI_DESIGN_SYSTEM.md) §2.3(모달 3종) · §5(빨강의 역할 분리) · §6 Phase 2

---

## 범위 조정 (사용자 결정, 2026-10-02)

스펙 §6 Phase 2 는 "기판을 네이티브 `<dialog>` 로 모은다"였다. 실측으로 전제가
어긋나는 것이 확인되어 두 가지를 사용자가 정했다.

| 결정 | 내용 | 이유 |
|---|---|---|
| **기판은 유지한다** | 백드롭·Esc·포커스·버튼만 공통 규칙으로 맞춘다 | `PopupDraggable` 은 드래그 기능이 있고 `columns_setting`(9화면)·`myinfo`(`parent.modal.close()`)가 교차 프레임 계약으로 쓴다. 기판 교체는 회귀 위험이 크고, 사용자가 느끼는 결함은 동작 통일로 전부 해소된다 |
| **셸 차단은 범위 밖** | 백드롭이 iframe 안만 덮는 현 상태를 수용한다 | 셸이 화면을 iframe 탭으로 띄우므로 백드롭이 프레임 경계를 넘을 수 없다. 넘기려면 부모 프레임과의 교차 프레임 연동이 필요한데 이번에 하지 않는다 |

**스펙의 사실 오류 두 가지도 이 Phase 에서 바로잡는다**(Task 5 문서 갱신).

1. §2.3 "네이티브 `<dialog>` 백드롭 **없음**" → 틀렸다. `aidatahub.css:209` 에
   `.form-dialog::backdrop` 이 있고 색도 적절하다. 실제 문제는 **범위**(iframe
   경계)다
2. §6 Phase 5 "`.btn-info`·`.text-info`(`#6451f3`) 는 템플릿에서 한 번도 쓰지
   않는다" → 틀렸다. `common.js` 가 Alert 마크업을 **동적 생성**하며 쓴다.
   알림 89곳의 확인 버튼과 아이콘이 이 보라색이다. 죽은 코드가 아니다

---

## Global Constraints

- **구현체(기판)를 바꾸지 않는다.** Bootstrap Modal → `<dialog>` 이전, `PopupDraggable` 제거 등은 이번 범위가 아니다.
- **레이아웃을 바꾸지 않는다.** `scripts/verify_layout_stable.py` 로 이동 0건을 유지한다(Phase 1 과 같은 기준).
- **`app.min.css` 를 수정하지 않는다.** 벤더 테마는 오버라이드로만 다룬다(스펙 §7).
- **색 리터럴을 새로 쓰지 않는다.** 모든 색은 `tokens.css` 의 토큰을 거친다. `scripts/verify_tokens.py` 가 0건을 유지해야 한다.
- **넓은 면적의 채움에 브랜드 빨강을 쓰지 않는다**(스펙 §5). 백드롭은 화면 전체를 덮으므로 중립이다.
- **주요 동작은 빨강 채움, 보조 동작은 중립 외곽선**(스펙 §5). 푸터는 **보조 → 주요** 순서다.
- **동기 Ajax 를 쓰지 않는다**(AGENTS.md).
- **모든 Git Commit 메시지는 한국어로 작성한다.** Conventional Commits 의 type 은 영문 유지.
- **테스트는 `--settings=configurations.test_settings` 로 돌린다.**
- **개발 서버는 `DB_CONN_MAX_AGE=0`** 이어야 한다. 0 보다 크면 `runserver` 가 커넥션을 누수해 화면이 500 을 낸다(AGENTS.md [6]).
- 서버는 `http://127.0.0.1:8123` 에 떠 있어야 한다.

---

## 지금 상태 (전부 실측)

### 모달 네 계열

| 계열 | 쓰는 곳 | 백드롭 | Esc | 포커스 |
|---|---|---|---|---|
| 네이티브 `<dialog>` | `data/` 6종 | `rgba(36,36,36,.45)` — **기준으로 삼는다** | **✓** | ✓ |
| 자체 `PopupDraggable` | 컬럼설정(9화면) · 패스워드 설정 · 내정보 · 다국어 4종 | **없음**(CSS 가 투명 강제) | ✗ | ✓ |
| Bootstrap `Alert`/`Confirm` | **123 호출** (`Alert.alert` 89 · `Alert.confirm` 34) | `#c9ced3` 0.32 | ✗ | ✓ |
| Bootstrap 단독 | API Key 1종 | **브랜드 빨강** 0.5 | ✗ | ✓ |

### 결함과 원인

| # | 증상 | 원인 | 고치는 곳 |
|---|---|---|---|
| M-1 | API Key 모달의 백드롭이 **빨강** | `app.min.css` 가 `--ct-backdrop-bg: var(--ct-emphasis-color)` 로 두고, `--ct-emphasis-color` 는 브랜드 빨강이다 | `tokens.css` |
| M-2 | `PopupDraggable` 에 백드롭이 **없다** | `SF-Custom.css:1168-1178` 이 `background-color: transparent !important` 로 강제 | `SF-Custom.css` |
| M-3 | 백드롭 색이 계열마다 다르다 | 네이티브 `.45` 짙은 회색 / Alert `#c9ced3` `.32` / 단독 빨강 `.5` | `tokens.css` · `aidatahub.css` |
| M-4 | Alert 확인 버튼·아이콘이 **보라 `#6451f3`** | `SF-Custom.css:741,796` 의 `.btn-info`·`.text-info`. `common.js:744,746` 가 쓴다 | `common.js` · `SF-Custom.css` |
| M-5 | Confirm 확인 버튼이 **보라 `#727cf5`** | `app.min.css` 의 `.btn-primary{--ct-btn-bg:#727cf5}`. SF-Custom 에 오버라이드가 없다 | `SF-Custom.css` |
| M-6 | Alert·Confirm·PopupDraggable 이 **Esc 로 안 닫힌다** | `common.js:539,798,802` 의 `keyboard: false` | `common.js` |
| M-7 | Confirm 푸터가 **`확인 → 취소`** 순서 | `common.js:764-765` 마크업 순서 | `common.js` |

`.btn-info`·`.text-info`·`.btn-primary` 의 템플릿 사용은 0건이다. `app/index.html:1096` 의 `.btn-primary`("Buy Now")는 벤더 템플릿 잔재로 화면에 쓰이지 않는다 — Phase 5 죽은 코드 정리 대상이고 이번에 건드리지 않는다.

---

## File Structure

| 파일 | 상태 | 이 Phase 에서의 책임 |
|---|---|---|
| `app/static/assets/css/tokens.css` | 수정 | `--modal-backdrop` 신설 + `--ct-backdrop-bg` 매핑(M-1) |
| `app/static/assets/css/SF-Custom.css` | 수정 | `PopupDraggable` 투명 강제 해제(M-2) · Alert 백드롭 토큰화(M-3) · `.btn-info`/`.text-info` 탈보라(M-4) · `.btn-primary` 오버라이드 신설(M-5) |
| `app/static/data/aidatahub.css` | 수정 | `.form-dialog::backdrop` 을 토큰 참조로(M-3) |
| `app/static/assets/js/common.js` | 수정 | `keyboard: true` 3곳(M-6) · Alert/Confirm 마크업의 클래스·순서(M-4·M-7) |
| `scripts/verify_modals.py` | **신규** | 모달 4계열의 백드롭색·Esc·포커스·버튼 순서를 측정해 규칙 위반을 잡는다 |
| `AGENTS.md` | 수정 | 검증 명령에 `verify_modals.py` 추가 |
| `docs/09_UI_DESIGN_SYSTEM.md` | 수정 | §2.3·§6 Phase 2·Phase 5 정정, Phase 2 완료 기록 |

**수정하지 않는 파일:** `app.min.css`, `wezongrid.css`, `vision/client.html`(API Key 모달 마크업), `common/columns_setting.html`, `page/account/myinfo.html`, 데이터 6종 모달 템플릿.

---

## 백드롭 규칙 (단일 원천)

```
--modal-backdrop: rgba(36, 36, 36, .45)
```

네 계열이 전부 이 값을 쓴다. 근거:

- 네이티브 `<dialog>` 가 이미 쓰는 값이고 6종에서 검증돼 있다
- 불투명도 `.45` 는 뒤 내용을 읽을 수 없게 만들면서 화면 구조는 보이게 한다. Alert 의 `.32` 는 너무 옅어 모달로 읽히지 않고, 단독 모달의 `.5` 빨강은 §5 의 "넓은 면적에 브랜드 빨강을 쓰지 않는다" 를 어긴다
- 색 `#242424` 는 `--brand-ink` 다. 중립이므로 §5 를 지킨다

**중첩(모달 위에 모달)은 지금 동작을 유지한다.** `SF-Custom.css` 의
`:not(:last-of-type)` 규칙이 "가장 위 백드롭만 보인다" 를 만든다. 겹겹이
어두워지는 것을 막으므로 그대로 둔다.

---

### Task 1: 모달 검증 하네스

규칙을 코드로 적는다. 먼저 만들고 **실제로 실패하는 것을 본 뒤** 고친다.

**Files:**
- Create: `scripts/verify_modals.py`

**Interfaces:**
- Produces: `python scripts/verify_modals.py`. 규칙 위반이 하나라도 있으면 종료코드 1.
- Consumes: `.admin_pw`, 떠 있는 개발 서버(`http://127.0.0.1:8123`), playwright.

- [ ] **Step 1: 하네스를 작성한다**

```python
#!/usr/bin/env python
"""모달 네 계열이 같은 규칙을 지키는지 본다.

계열마다 구현체가 다르다(네이티브 <dialog> · 자체 PopupDraggable ·
Bootstrap Modal). Phase 2 는 구현체를 통일하지 않고 **동작**을 통일했으므로,
구현체가 아니라 결과를 잰다 — 백드롭색·Esc·포커스·푸터 버튼 순서.

    python scripts/verify_modals.py

운영 의존성이 아니다. playwright 가 필요하다(capture_ui.py 와 같다).
"""
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8123'
VIEWPORT = {'width': 1920, 'height': 911}

# 단일 백드롭 규칙. tokens.css 의 --modal-backdrop 과 같은 값이어야 한다.
#
# background-color 만 재면 안 된다. Bootstrap 은 .modal-backdrop 에 opacity
# 레이어를 따로 두고 그걸로 농도를 조절한다(네이티브 ::backdrop 은 opacity 가
# 1 이고 색의 알파로만 조절한다). 두 곳에 알파가 있으면 곱해지므로, 실제로
# 눈에 보이는 농도인 **실효 알파**(색의 알파 × opacity)를 잰다.
EXPECT_RGB = (36, 36, 36)
EXPECT_ALPHA = 0.45
ALPHA_TOLERANCE = 0.02

# 계열마다 여는 법이 다르다. (라벨, 화면 URL, 여는 JS, 열렸는지 보는 JS,
# 모달 루트 셀렉터, 백드롭 셀렉터, 닫는 JS)
CASES = [
    {
        'label': '네이티브 dialog (검사항목 추가)',
        'url': '/gui/wm_data_item/?project=3',
        'open': "() => document.getElementById('createInspectionItemDialog').showModal()",
        'is_open': "() => document.getElementById('createInspectionItemDialog').open === true",
        'root': '#createInspectionItemDialog',
        # ::backdrop 은 getComputedStyle 의 두 번째 인자로 읽는다.
        'backdrop': ("() => { const d = document.getElementById('createInspectionItemDialog');"
                     " if (!d) return null; const s = getComputedStyle(d, '::backdrop');"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': "() => document.getElementById('createInspectionItemDialog').close()",
    },
    {
        'label': 'Alert (알림)',
        'url': '/gui/wm_user/',
        'open': "() => { Alert.init(); Alert.alert('제목', '본문'); }",
        'is_open': ("() => { const e = document.getElementById('commonAlertModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#commonAlertModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': "() => Alert._alertModal && Alert._alertModal.hide()",
    },
    {
        'label': 'Confirm (확인)',
        'url': '/gui/wm_user/',
        'open': "() => Alert.confirm('제목', '본문', () => {}, () => {})",
        'is_open': ("() => { const e = document.getElementById('commonConfirmModal');"
                    " return !!e && e.classList.contains('show'); }"),
        'root': '#commonConfirmModal',
        'backdrop': ("() => { const e = document.querySelector('.modal-backdrop');"
                     " if (!e) return null; const s = getComputedStyle(e);"
                     " return [s.backgroundColor, s.opacity]; }"),
        'close': "() => Alert._confirmModal && Alert._confirmModal.hide()",
    },
    {
        'label': 'PopupDraggable (컬럼 설정)',
        'url': '/gui/wm_user/',
        'open': "() => document.getElementById('btnGridSetting').click()",
        'is_open': "() => !!document.querySelector('.modal.show')",
        'root': '.modal.show',
        'backdrop': ("() => { const l = document.querySelectorAll('.modal-backdrop');"
                     " const e = l[l.length - 1]; if (!e) return null;"
                     " const s = getComputedStyle(e); return [s.backgroundColor, s.opacity]; }"),
        'close': "() => page.popColSetting && page.popColSetting.modal.close()",
    },
]

# 푸터의 보조→주요 순서는 Confirm 에서만 기계로 잴 수 있다. 나머지 계열은
# 버튼이 하나뿐이라 순서라는 것이 없다.
CONFIRM_ORDER_JS = """() => Array.from(
    document.querySelectorAll('#commonConfirmModal .modal-footer button,'
                            + '#commonConfirmModal .d-flex button')
).map(b => b.id)"""

# Alert 의 확인 버튼은 주요 동작이다 — 브랜드 빨강 채움이어야 한다(§5).
BRAND = 'rgb(218, 33, 41)'


def _norm(color):
    """rgb(a) 표기를 비교 가능한 모양으로 맞춘다."""
    if not color:
        return ''
    return color.replace(' ', '')


def _effective(pair):
    """(background-color, opacity) → (rgb 3튜플, 실효 알파).

    눈에 보이는 농도는 색의 알파와 요소 opacity 의 곱이다. 둘 중 하나만
    보면 Bootstrap 계열과 네이티브 계열을 같은 잣대로 비교할 수 없다.
    """
    if not pair:
        return None, None
    color, opacity = pair
    nums = re.findall(r'[\d.]+', color or '')
    if len(nums) < 3:
        return None, None
    rgb = tuple(int(float(n)) for n in nums[:3])
    alpha = float(nums[3]) if len(nums) > 3 else 1.0
    try:
        alpha *= float(opacity)
    except (TypeError, ValueError):
        pass
    return rgb, alpha


def main():
    password_file = ROOT / '.admin_pw'
    if not password_file.exists():
        print('.admin_pw 가 없다. seed_initial 을 먼저 돌려라.')
        return 2
    password = password_file.read_text(encoding='utf-8').strip()

    violations = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_context(viewport=VIEWPORT, locale='ko-KR').new_page()
        page.goto(BASE + '/login/', wait_until='domcontentloaded')
        page.fill('#loginId', 'admin')
        page.fill('#loginPwd', password)
        page.click('#login')
        page.wait_for_url(BASE + '/', timeout=15000)
        page.wait_for_timeout(1200)

        current = None
        for case in CASES:
            if case['url'] != current:
                page.goto(BASE + case['url'], wait_until='domcontentloaded', timeout=25000)
                page.wait_for_timeout(2600)
                current = case['url']

            page.evaluate(case['open'])
            page.wait_for_timeout(900)
            if not page.evaluate(case['is_open']):
                violations.append((case['label'], '열리지 않았다'))
                continue

            rgb, alpha = _effective(page.evaluate(case['backdrop']))
            if rgb != EXPECT_RGB or alpha is None or abs(alpha - EXPECT_ALPHA) > ALPHA_TOLERANCE:
                violations.append((case['label'], '백드롭 rgb={} 실효알파={} (기대 {} / {})'.format(
                    rgb, None if alpha is None else round(alpha, 3), EXPECT_RGB, EXPECT_ALPHA)))

            focused = page.evaluate(
                "(sel) => { const m = document.querySelector(sel);"
                " return !!m && m.contains(document.activeElement); }", case['root'])
            if not focused:
                violations.append((case['label'], '열 때 포커스가 모달 밖에 있다'))

            page.keyboard.press('Escape')
            page.wait_for_timeout(700)
            if page.evaluate(case['is_open']):
                violations.append((case['label'], 'Esc 로 닫히지 않는다'))
                page.evaluate(case['close'])
                page.wait_for_timeout(500)

        # 푸터 순서와 주요 버튼 색은 Confirm/Alert 에서 본다.
        page.goto(BASE + '/gui/wm_user/', wait_until='domcontentloaded', timeout=25000)
        page.wait_for_timeout(2600)

        page.evaluate("() => Alert.confirm('제목', '본문', () => {}, () => {})")
        page.wait_for_timeout(800)
        order = page.evaluate(CONFIRM_ORDER_JS)
        if order[:2] != ['commonConfirmModalCancel', 'commonConfirmModalOk']:
            violations.append(('Confirm', '푸터 순서 {} (기대 취소 → 확인)'.format(order)))
        ok_bg = page.evaluate(
            "() => getComputedStyle(document.getElementById('commonConfirmModalOk')).backgroundColor")
        if _norm(ok_bg) != _norm(BRAND):
            violations.append(('Confirm', '확인 버튼 {} (기대 {})'.format(ok_bg, BRAND)))
        page.evaluate("() => Alert._confirmModal && Alert._confirmModal.hide()")
        page.wait_for_timeout(600)

        page.evaluate("() => { Alert.init(); Alert.alert('제목', '본문'); }")
        page.wait_for_timeout(800)
        alert_bg = page.evaluate(
            "() => getComputedStyle(document.getElementById('commonAlertModalOk')).backgroundColor")
        if _norm(alert_bg) != _norm(BRAND):
            violations.append(('Alert', '확인 버튼 {} (기대 {})'.format(alert_bg, BRAND)))
        icon = page.evaluate(
            "() => { const e = document.querySelector('#commonAlertModal .modal-body i');"
            " return e ? getComputedStyle(e).color : null; }")
        # 보라(#6451f3)가 남아 있으면 안 된다. 다른 색이면 설계 판단에 맡긴다.
        if _norm(icon) == _norm('rgb(100, 81, 243)'):
            violations.append(('Alert', '아이콘이 아직 보라(#6451f3)다'))

        browser.close()

    for label, why in violations:
        print('위반  {:28} {}'.format(label, why))

    print('\n모달 규칙 위반 {}건'.format(len(violations)))
    print('PASS' if not violations else 'FAIL')
    return 0 if not violations else 1


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 지금 돌려서 실패를 본다 (RED)**

```bash
cd /home/yhan/projects/manufacturing_ai_platform
ss -tln | grep -q ':8123' || (nohup .venv/bin/python manage.py runserver 0.0.0.0:8123 --noreload > /tmp/server.log 2>&1 &)
sleep 4
.venv/bin/python scripts/verify_modals.py
```

Expected: `모달 규칙 위반 10건` `FAIL`. 계획을 쓰며 실제로 돌려 얻은 출력이다.

```
위반  Alert (알림)              백드롭 rgb=(201, 206, 211) 실효알파=0.32 (기대 (36, 36, 36) / 0.45)
위반  Alert (알림)              Esc 로 닫히지 않는다
위반  Confirm (확인)            백드롭 rgb=(201, 206, 211) 실효알파=0.32 (기대 (36, 36, 36) / 0.45)
위반  Confirm (확인)            Esc 로 닫히지 않는다
위반  PopupDraggable (컬럼 설정)  백드롭 rgb=(0, 0, 0) 실효알파=0.0 (기대 (36, 36, 36) / 0.45)
위반  PopupDraggable (컬럼 설정)  Esc 로 닫히지 않는다
위반  Confirm                 푸터 순서 ['commonConfirmModalOk', 'commonConfirmModalCancel'] (기대 취소 → 확인)
위반  Confirm                 확인 버튼 rgb(114, 124, 245) (기대 rgb(218, 33, 41))
위반  Alert                   확인 버튼 rgb(100, 81, 243) (기대 rgb(218, 33, 41))
위반  Alert                   아이콘이 아직 보라(#6451f3)다
```

| 없애는 Task | 건수 |
|---|---|
| Task 2 — 백드롭 | 3 |
| Task 3 — 색·순서 | 4 |
| Task 4 — Esc | 3 |

**네이티브 `dialog` 에서는 위반이 한 건도 나오지 않는다.** 기준으로 삼은 계열이
규칙을 스스로 만족한다는 뜻이고, 규칙이 타당하다는 증거다. 여기서 위반이
나오면 멈춘다 — 규칙 쪽이 틀린 것이다.

- [ ] **Step 3: 커밋**

```bash
git add scripts/verify_modals.py
git commit -m "test: 모달 네 계열의 백드롭·Esc·포커스·버튼을 재는 하네스 추가"
```

---

### Task 2: 백드롭 통일 (M-1 · M-2 · M-3)

**Files:**
- Modify: `app/static/assets/css/tokens.css` (파일 끝에 블록 추가)
- Modify: `app/static/assets/css/SF-Custom.css:1151-1178`
- Modify: `app/static/data/aidatahub.css:209`

**Interfaces:**
- Consumes: Phase 1 의 `--brand-ink`(`#242424`).
- Produces: `--modal-backdrop`. Task 1 의 하네스가 이 값을 기대하고, Task 5 의 문서가 이 이름을 적는다.

- [ ] **Step 1: `tokens.css` 에 백드롭 토큰을 더한다**

파일 끝에 붙인다.

```css
/* --- 모달 백드롭 ------------------------------------------------------
 * 네 계열(네이티브 <dialog> · PopupDraggable · Alert/Confirm · Bootstrap
 * 단독)이 전부 이 값을 쓴다. 네이티브 <dialog> 6종이 이미 쓰던 값을
 * 기준으로 삼았다.
 *
 * 화면 전체를 덮는 넓은 면적이므로 브랜드 빨강을 쓰지 않는다(§5).
 * app.min.css 가 --ct-backdrop-bg 를 --ct-emphasis-color(브랜드 빨강)로
 * 두고 있어, 그대로 두면 Bootstrap 단독 모달의 백드롭이 빨개진다. */
:root {
    --modal-backdrop: rgba(36, 36, 36, .45);

    /* 농도는 --modal-backdrop 의 알파 한 곳에서만 쓴다. Bootstrap 은
       .modal-backdrop 에 opacity 레이어를 따로 두는데, 거기에도 값을 주면
       두 번 곱해져 (0.45 × 0.45 = 0.20) 눈에 띄게 옅어진다. */
    --ct-backdrop-bg: var(--modal-backdrop);
    --ct-backdrop-opacity: 1;
}
```

- [ ] **Step 2: `SF-Custom.css` 의 Alert 백드롭을 토큰으로 바꾼다**

`app/static/assets/css/SF-Custom.css:1151-1156` 의 블록을 다음으로 바꾼다.

```css
body.common-alert-mask .modal-backdrop {
    /* 계열마다 다르던 값을 --modal-backdrop 하나로 모았다. 이전 값
       (#c9ced3 / 0.32)은 너무 옅어 모달로 읽히지 않았다.
       농도는 --modal-backdrop 의 알파 한 곳에서만 쓴다. Bootstrap 의
       opacity 레이어를 그대로 두면 0.45 × 0.45 = 0.20 으로 두 번 곱해진다. */
    background-color: var(--modal-backdrop);
    z-index: 1075;
}
body.common-alert-mask .modal-backdrop.show {
    opacity: 1;
}
```

- [ ] **Step 3: `PopupDraggable` 의 투명 강제를 푼다**

`app/static/assets/css/SF-Custom.css:1168-1178` 의 세 블록을 다음으로 바꾼다.
중첩 모달에서 **가장 위 백드롭만 보이게 하는 규칙(`:not(:last-of-type)`)은
건드리지 않는다** — 겹겹이 어두워지는 것을 막는 장치다.

```css
body.popup-draggable-mask:not(.common-alert-mask) .modal-backdrop {
    /* 이전에는 transparent !important 로 백드롭을 지워, 컬럼설정·내정보가
       뒤 화면 위에 그냥 떠 있는 것처럼 보였다. 다른 계열과 같은 값을 준다. */
    background-color: var(--modal-backdrop) !important;
}
body.popup-draggable-mask:not(.common-alert-mask) .modal-backdrop.show {
    opacity: 1 !important;
}
body.popup-draggable-mask:not(.common-alert-mask) .modal-backdrop.fade {
    transition: none !important;
}
```

- [ ] **Step 4: 네이티브 `::backdrop` 을 토큰 참조로 바꾼다**

`app/static/data/aidatahub.css:209` 를 다음으로 바꾼다. 값은 같고 출처만 옮긴다.

```css
.form-dialog::backdrop { background: var(--modal-backdrop); }
```

- [ ] **Step 5: 하네스로 백드롭 위반이 사라졌는지 본다**

```bash
.venv/bin/python scripts/verify_modals.py
```

Expected: 백드롭 관련 위반이 **전부 사라진다**. Esc·버튼 위반은 그대로 남는다(Task 3·4 몫).

`PopupDraggable` 에서 `rgba(0, 0, 0, 0)` 이 계속 나오면 `.show` 의
`opacity: 0 !important` 가 남아 있는 것이다 — Step 3 을 다시 본다.

- [ ] **Step 6: 색 리터럴이 새로 생기지 않았는지 본다**

```bash
.venv/bin/python scripts/verify_tokens.py | tail -2
```

Expected: `토큰을 거치지 않은 선언 0건` `PASS`.

- [ ] **Step 7: 레이아웃이 움직이지 않았는지 본다**

백드롭은 `position: fixed` 라 흐름에 영향이 없어야 한다.

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-p2-t2
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-base-font /tmp/geo-p2-t2
```

`/tmp/geo-base-font` 가 없으면(세션이 바뀌었으면) 작업 전 커밋에서 먼저 기준선을 뜬다.

Expected: `PASS`, 이동 0건.

- [ ] **Step 8: 눈으로 본다**

컬럼 설정 모달에 백드롭이 생겼는지, API Key 모달이 더 이상 빨갛지 않은지 본다.

```bash
cat > /tmp/shot_backdrop.py <<'PY'
import pathlib
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:8123'; PW=pathlib.Path('.admin_pw').read_text(encoding='utf-8').strip()
with sync_playwright() as pw:
    b=pw.chromium.launch(); p=b.new_context(viewport={'width':1920,'height':911}).new_page()
    p.goto(BASE+'/login/',wait_until='domcontentloaded')
    p.fill('#loginId','admin'); p.fill('#loginPwd',PW); p.click('#login')
    p.wait_for_url(BASE+'/',timeout=15000)
    p.goto(BASE+'/gui/wm_user/',wait_until='domcontentloaded'); p.wait_for_timeout(2600)
    p.click('#btnGridSetting'); p.wait_for_timeout(1400)
    p.screenshot(path='/tmp/p2-popupdraggable.png')
    p.goto(BASE+'/gui/wm_vis_client/',wait_until='domcontentloaded'); p.wait_for_timeout(2600)
    p.evaluate("() => new bootstrap.Modal(document.getElementById('apiKeyModal')).show()")
    p.wait_for_timeout(1200); p.screenshot(path='/tmp/p2-apikey.png')
    b.close()
PY
.venv/bin/python /tmp/shot_backdrop.py
```

`/tmp/p2-popupdraggable.png` 와 `/tmp/p2-apikey.png` 를 연다. 확인할 것:

1. 컬럼 설정 뒤 화면이 **어둡게 가려진다**
2. API Key 뒤 화면이 **빨갛지 않고 어둡다**
3. 모달 본문 자체는 가려지지 않았다

- [ ] **Step 9: 커밋**

```bash
git add app/static/assets/css/tokens.css app/static/assets/css/SF-Custom.css \
        app/static/data/aidatahub.css
git commit -m "fix: 모달 백드롭을 네 계열 공통값으로 통일

계열마다 달랐다 — 네이티브 dialog 는 어두운 회색 .45, Alert 는 #c9ced3 .32
로 너무 옅었고, Bootstrap 단독(API Key)은 app.min.css 가 --ct-backdrop-bg 를
브랜드 빨강으로 두어 화면이 빨갛게 덮였다. PopupDraggable(컬럼설정·내정보)은
CSS 가 transparent 로 강제해 백드롭이 아예 없었다.

네이티브 dialog 가 쓰던 값을 --modal-backdrop 으로 올려 넷이 공유한다.
화면 전체를 덮는 넓은 면적이라 브랜드 빨강을 쓰지 않는다(09_UI_DESIGN_SYSTEM
§5). 중첩 시 가장 위 백드롭만 보이게 하는 :not(:last-of-type) 규칙은 그대로
두었다."
```

---

### Task 3: Alert·Confirm 의 색과 순서 (M-4 · M-5 · M-7)

**Files:**
- Modify: `app/static/assets/js/common.js:734-770` (Alert/Confirm 마크업)
- Modify: `app/static/assets/css/SF-Custom.css:741-752, 796-798` (`.btn-info`, `.text-info`)
- Modify: `app/static/assets/css/SF-Custom.css` (`.btn-primary` 오버라이드 신설)

**Interfaces:**
- Consumes: Phase 1 의 `--brand-primary`(`#da2129`) · `--brand-primary-hover` · `--brand-muted` · `--brand-line`.
- Produces: 없음. 호출부 123곳은 그대로 둔다 — `Alert.alert` / `Alert.confirm` 의 시그니처를 바꾸지 않는다.

- [ ] **Step 1: `.btn-info` 와 `.text-info` 에서 보라를 걷어낸다**

`SF-Custom.css:741-752` 와 `:796-798` 을 다음으로 바꾼다. 클래스 이름은
`common.js` 가 쓰므로 **지우지 않는다**(스펙이 죽은 코드라고 적은 것은 틀렸다).

```css
/* Alert 의 확인 버튼이 이 클래스를 쓴다(common.js 가 마크업을 동적 생성).
   원래 #6451f3 보라였다 — 빨강 브랜드 제품에서 알림 89곳이 보라 버튼이었다.
   주요 동작이므로 브랜드 빨강 채움이다(09_UI_DESIGN_SYSTEM §5). */
.btn-info {
    background: var(--brand-primary);
    border: 1px solid var(--brand-primary);
    color: #fff;
    box-shadow: none;
    white-space: nowrap;
}
.btn-info:hover, .btn-info:active, .btn-info:focus {
    background: var(--brand-primary-hover);
    border: 1px solid var(--brand-primary-hover);
}
```

```css
/* Alert 의 정보 아이콘. 빨강으로 두면 단순 안내가 오류로 읽히므로 중립이다. */
.text-info {
    color: var(--brand-muted) !important;
}
```

- [ ] **Step 2: `.btn-primary` 오버라이드를 더한다**

`SF-Custom.css` 에는 `.btn-primary` 오버라이드가 없어 `app.min.css` 의 벤더
보라(`#727cf5`)가 그대로 나온다. `.btn-info` 정의 바로 뒤에 붙인다.

```css
/* app.min.css 가 .btn-primary{--ct-btn-bg:#727cf5} 로 보라를 하드코딩한다.
   --ct-primary 를 따르지 않으므로 여기서 덮는다. Confirm 의 확인 버튼이
   이 클래스를 쓴다. */
.btn-primary {
    --ct-btn-bg: var(--brand-primary);
    --ct-btn-border-color: var(--brand-primary);
    --ct-btn-hover-bg: var(--brand-primary-hover);
    --ct-btn-hover-border-color: var(--brand-primary-hover);
    --ct-btn-active-bg: var(--brand-primary-hover);
    --ct-btn-active-border-color: var(--brand-primary-hover);
}
```

- [ ] **Step 3: Confirm 의 푸터 순서를 보조 → 주요로 바꾼다**

`common.js` 의 Confirm 마크업에서 버튼 두 줄의 순서를 맞바꾼다. 아래 두 줄이

```javascript
            '            <button type="button" class="btn btn-primary" id="commonConfirmModalOk">확인</button>' +
            '            <button type="button" class="btn btn-light" id="commonConfirmModalCancel">취소</button>' +
```

다음이 되게 한다. **id 와 클래스는 그대로 둔다** — `_setButtonText` 와 이벤트
바인딩이 id 로 찾는다.

```javascript
            // 푸터는 보조 → 주요 순서다(09_UI_DESIGN_SYSTEM §5).
            '            <button type="button" class="btn btn-light" id="commonConfirmModalCancel">취소</button>' +
            '            <button type="button" class="btn btn-primary" id="commonConfirmModalOk">확인</button>' +
```

- [ ] **Step 4: 하네스로 색·순서 위반이 사라졌는지 본다**

```bash
.venv/bin/python scripts/verify_modals.py
```

Expected: 색·순서 위반이 전부 사라지고 **Esc 위반 3건만 남는다**(Task 4 몫).

- [ ] **Step 5: 템플릿 JS 문법과 색 토큰을 확인한다**

`common.js` 를 손댔으므로 문법을 본다.

```bash
node -e "new Function(require('fs').readFileSync('app/static/assets/js/common.js','utf8'))" \
  && echo 'common.js 문법 OK'
node scripts/verify_screen_js.js | tail -2
.venv/bin/python scripts/verify_tokens.py | tail -2
```

Expected: `common.js 문법 OK`, verify_screen_js `PASS`, verify_tokens `PASS`.

- [ ] **Step 6: 눈으로 본다**

```bash
cat > /tmp/shot_alert.py <<'PY'
import pathlib
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:8123'; PW=pathlib.Path('.admin_pw').read_text(encoding='utf-8').strip()
with sync_playwright() as pw:
    b=pw.chromium.launch(); p=b.new_context(viewport={'width':1920,'height':911}).new_page()
    p.goto(BASE+'/login/',wait_until='domcontentloaded')
    p.fill('#loginId','admin'); p.fill('#loginPwd',PW); p.click('#login')
    p.wait_for_url(BASE+'/',timeout=15000)
    p.goto(BASE+'/gui/wm_user/',wait_until='domcontentloaded'); p.wait_for_timeout(2600)
    p.evaluate("() => { Alert.init(); Alert.alert('제목','본문 메시지'); }")
    p.wait_for_timeout(900); p.screenshot(path='/tmp/p2-alert.png')
    p.reload(wait_until='domcontentloaded'); p.wait_for_timeout(2600)
    p.evaluate("() => Alert.confirm('제목','본문', ()=>{}, ()=>{})")
    p.wait_for_timeout(900); p.screenshot(path='/tmp/p2-confirm.png')
    b.close()
PY
.venv/bin/python /tmp/shot_alert.py
```

`/tmp/p2-alert.png` · `/tmp/p2-confirm.png` 를 연다. 확인할 것:

1. 확인 버튼이 **브랜드 빨강 채움**이다 (보라가 아니다)
2. Alert 의 정보 아이콘이 **중립 회색**이다
3. Confirm 의 버튼이 **취소 → 확인** 순서다
4. 백드롭이 어둡다 (Task 2 의 결과가 유지된다)

- [ ] **Step 7: 커밋**

```bash
git add app/static/assets/js/common.js app/static/assets/css/SF-Custom.css
git commit -m "fix: 알림·확인 모달의 보라 버튼을 브랜드 색으로 바꾸고 푸터 순서 정리

Alert 의 확인 버튼과 아이콘이 #6451f3 보라였다(.btn-info/.text-info).
Confirm 의 확인 버튼은 app.min.css 의 벤더 보라 #727cf5 였다 — SF-Custom 에
.btn-primary 오버라이드가 없어 --ct-primary 를 따르지 않았다. 호출 지점이
123곳이라 제품에서 가장 자주 보이는 모달이 브랜드와 어긋나 있었다.

09_UI_DESIGN_SYSTEM.md 는 .btn-info/.text-info 를 '템플릿에서 한 번도 쓰지
않는 죽은 코드'로 보고 Phase 5 제거 대상에 넣었으나, common.js 가 마크업을
동적 생성하며 쓴다. 클래스는 남기고 색만 바꿨다.

정보 아이콘은 중립으로 둔다 — 빨강이면 단순 안내가 오류로 읽힌다.
푸터는 보조 → 주요(취소 → 확인) 순서로 맞췄다(§5)."
```

---

### Task 4: Esc 로 닫기 (M-6)

**Files:**
- Modify: `app/static/assets/js/common.js:538-541` (`PopupDraggable`)
- Modify: `app/static/assets/js/common.js:797-803` (Alert · Confirm)

**Interfaces:**
- Consumes: 없음.
- Produces: 없음.

세 계열 모두 `bootstrap.Modal` 을 쓰고 생성 옵션이 `keyboard: false` 다. `true` 로
바꾸면 Bootstrap 이 Esc 를 처리한다. 네이티브 `<dialog>` 는 이미 된다.

`backdrop: 'static'` 은 **유지한다** — 백드롭을 눌러 닫히면 입력 중이던
폼(컬럼 설정·검사항목 추가)이 실수로 사라진다. Esc 는 의도적인 동작이라 다르다.

- [ ] **Step 1: `PopupDraggable` 의 Esc 를 연다**

`common.js:538-541` 을 다음으로 바꾼다.

```javascript
            this.bsModal = bootstrap.Modal.getOrCreateInstance(this.$modal.get(0), {
                backdrop: 'static',
                // Esc 로 닫는다. 백드롭 클릭은 막아 둔다 — 입력 중이던 폼이
                // 실수로 사라지는 것과 의도적인 Esc 는 다르다.
                keyboard: true
            });
```

- [ ] **Step 2: Alert 과 Confirm 의 Esc 를 연다**

`common.js:797-803` 을 다음으로 바꾼다.

```javascript
        this._alertModal = bootstrap.Modal.getOrCreateInstance(alertElement, {
            backdrop: 'static',
            keyboard: true
        });
        this._confirmModal = bootstrap.Modal.getOrCreateInstance(confirmElement, {
            backdrop: 'static',
            keyboard: true
        });
```

- [ ] **Step 3: Esc 로 닫은 Confirm 이 "취소"로 처리되는지 확인한다**

Esc 는 취소다. 확인 콜백이 돌면 안 된다. 실제로 눌러 본다.

```bash
cat > /tmp/check_esc_confirm.py <<'PY'
import pathlib
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:8123'; PW=pathlib.Path('.admin_pw').read_text(encoding='utf-8').strip()
with sync_playwright() as pw:
    b=pw.chromium.launch(); p=b.new_context(viewport={'width':1920,'height':911}).new_page()
    p.goto(BASE+'/login/',wait_until='domcontentloaded')
    p.fill('#loginId','admin'); p.fill('#loginPwd',PW); p.click('#login')
    p.wait_for_url(BASE+'/',timeout=15000)
    p.goto(BASE+'/gui/wm_user/',wait_until='domcontentloaded'); p.wait_for_timeout(2600)
    p.evaluate("""() => { window.__yes = 0; window.__no = 0;
        Alert.confirm('제목','본문', () => { window.__yes++; }, () => { window.__no++; }); }""")
    p.wait_for_timeout(800)
    p.keyboard.press('Escape'); p.wait_for_timeout(900)
    print('Esc 뒤 →', p.evaluate("() => ({확인콜백: window.__yes, 취소콜백: window.__no, 열림: document.getElementById('commonConfirmModal').classList.contains('show')})"))
    b.close()
PY
.venv/bin/python /tmp/check_esc_confirm.py
```

Expected: `확인콜백: 0`, `열림: False`.
**확인콜백이 0 이 아니면 멈춘다** — Esc 가 저장·삭제를 실행시키는 것이고, 지금보다 나쁜 상태다. 그 경우 `hidden.bs.modal` 핸들러가 확인 콜백을 부르고 있는지 `common.js` 에서 확인한다.

`취소콜백` 은 0 이어도 1 이어도 받아들인다 — Bootstrap 의 `hide()` 경로에 따라 달라지고, 둘 다 "아무 일도 일어나지 않는다" 로 안전하다.

- [ ] **Step 4: 하네스가 전부 통과하는지 본다 (GREEN)**

```bash
.venv/bin/python scripts/verify_modals.py
```

Expected: `모달 규칙 위반 0건` `PASS`.

- [ ] **Step 5: 문법과 회귀를 본다**

```bash
node -e "new Function(require('fs').readFileSync('app/static/assets/js/common.js','utf8'))" \
  && echo 'common.js 문법 OK'
node scripts/verify_screen_js.js | tail -2
.venv/bin/python manage.py test tests --settings=configurations.test_settings 2>&1 | tail -3
```

Expected: 문법 OK, verify_screen_js `PASS`, 단위테스트 64 OK.

- [ ] **Step 6: 커밋**

```bash
git add app/static/assets/js/common.js
git commit -m "fix: 알림·확인·자체 모달이 Esc 로 닫히지 않던 문제 수정

세 계열 모두 bootstrap.Modal 을 keyboard: false 로 만들고 있었다. 네이티브
<dialog> 6종만 Esc 가 되어 같은 제품에서 키보드 동작이 갈렸다.

backdrop: 'static' 은 유지한다 — 백드롭 클릭으로 닫히면 컬럼 설정처럼 입력
중이던 폼이 실수로 사라진다. Esc 는 의도적인 동작이라 다르다.

Esc 로 닫은 Confirm 이 확인 콜백을 부르지 않는 것을 실제로 눌러 확인했다."
```

---

### Task 5: 전수 검증 + 문서 갱신

**Files:**
- Modify: `AGENTS.md` ([6] 검증 명령 목록)
- Modify: `docs/09_UI_DESIGN_SYSTEM.md` (§2.3 정정 · §6 Phase 2 결과 · Phase 5 정정)

**Interfaces:**
- Consumes: Task 1~4 전부.

- [ ] **Step 1: 검증 전부를 돌린다**

```bash
cd /home/yhan/projects/manufacturing_ai_platform
.venv/bin/python manage.py test tests --settings=configurations.test_settings 2>&1 | tail -3
node scripts/verify_screen_js.js | tail -2
.venv/bin/python scripts/verify_menu.py | tail -2
.venv/bin/python scripts/verify_permission_map.py | tail -2
.venv/bin/python scripts/verify_response_keys.py | tail -2
.venv/bin/python scripts/verify_tokens.py | tail -2
.venv/bin/python scripts/verify_modals.py | tail -2
```

Expected: 단위테스트 64 OK, 검증 스크립트 6종 전부 `PASS`.

- [ ] **Step 2: 레이아웃 불변을 확인한다**

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-p2-final
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-base-font /tmp/geo-p2-final
```

Expected: `PASS`, 이동 0건. 이 Phase 는 색과 키보드만 바꿨다.

- [ ] **Step 3: 25화면 캡처와 e2e 를 돌린다**

e2e 전에 DB 커넥션을 확인한다. 100 에 가까우면 개발 서버를 재기동한다(AGENTS.md [6]).

```bash
.venv/bin/python scripts/capture_ui.py /tmp/ui-p2 2>&1 | tail -3
.venv/bin/python -m pytest tests/e2e -q --tb=line 2>&1 | tail -4
```

Expected: `화면 25개 / 오류 0건` `PASS`, `58 passed`.

- [ ] **Step 4: 모달 네 계열을 눈으로 본다**

Task 2 Step 8 과 Task 3 Step 6 의 스크린샷 네 장(`/tmp/p2-popupdraggable.png`,
`/tmp/p2-apikey.png`, `/tmp/p2-alert.png`, `/tmp/p2-confirm.png`)을 다시 연다.
확인할 것:

1. 네 계열의 백드롭이 **같은 어둡기**다
2. 보라가 한 점도 없다
3. Confirm 이 **취소 → 확인** 순서다
4. 모달 본문·헤더가 깨지거나 잘린 곳이 없다

- [ ] **Step 5: `AGENTS.md` 의 검증 목록에 더한다**

`[6] 실행` 의 검증 블록에서 `verify_tokens.py` 줄 바로 뒤에 더한다.

```bash
python scripts/verify_modals.py                  # 모달 백드롭·Esc·포커스·버튼 (서버 필요)
```

- [ ] **Step 6: 스펙을 갱신한다**

`docs/09_UI_DESIGN_SYSTEM.md` 의 §2.3 표 아래에 다음을 더한다.

```markdown
**정정(Phase 2 구현 중 실측).** 위 표의 "백드롭 없음" 두 줄은 셸 안에서 본
현상을 구현 탓으로 적은 것이다. 실제는 이렇다.

- 네이티브 `<dialog>` 는 `aidatahub.css` 에 `.form-dialog::backdrop` 이 있고
  색도 적절했다. **없는 것이 아니라 iframe 안만 덮는다**
- 자체 `modal.open()` 은 `SF-Custom.css` 가 `transparent !important` 로
  **강제로 지우고 있었다**. Phase 2 에서 되살렸다
- 화면을 iframe 탭으로 띄우는 셸 구조상 **어떤 백드롭도 프레임 경계를 넘지
  못한다.** 모달이 열린 채 상단바·좌측 메뉴를 누를 수 있다(3계열 전부 확인).
  고치려면 부모 프레임과의 교차 프레임 연동이 필요하다 → **범위 밖**(사용자
  결정)

계열이 하나 더 있었다 — `Alert`/`Confirm`(`common.js`)이 Bootstrap Modal 을
쓰고 **호출 지점이 123곳**이다. 제품에서 가장 자주 보이는 모달인데 §2.3 의
표에 없었다.
```

`§6 Phase 2` 절의 본문을 다음으로 바꾼다.

```markdown
### Phase 2 — 모달 동작 통일 (완료, 2026-10-02)

**기판을 바꾸지 않기로 했다**(사용자 결정). `PopupDraggable` 은 드래그 기능이
있고 `columns_setting`(9화면)·`myinfo`(`parent.modal.close()`)가 교차 프레임
계약으로 쓴다. 기판 교체는 회귀 위험이 크고, 사용자가 느끼는 결함은 동작
통일로 전부 해소된다.

한 일:

1. **백드롭 통일** — `--modal-backdrop: rgba(36,36,36,.45)` 하나로 네 계열이
   모인다. API Key 의 빨간 백드롭(`app.min.css` 의
   `--ct-backdrop-bg: var(--ct-emphasis-color)`)과 `PopupDraggable` 의
   `transparent !important` 강제를 걷어냈다
2. **보라 제거** — Alert 확인 버튼·아이콘(`#6451f3`), Confirm 확인
   버튼(`#727cf5`). 주요 동작은 브랜드 빨강 채움, 정보 아이콘은 중립
3. **Esc 통일** — 세 계열의 `keyboard: false` 를 `true` 로. `backdrop:
   'static'` 은 유지했다(백드롭 클릭으로 폼이 사라지는 것을 막는다)
4. **푸터 순서** — 보조 → 주요(취소 → 확인)

검증: `scripts/verify_modals.py` 가 네 계열의 백드롭색·Esc·포커스·버튼 순서를
재고, 레이아웃 이동 0건을 함께 확인했다.

**남긴 것:** 백드롭이 셸(상단바·좌측 메뉴·탭바)을 덮지 못하는 문제. iframe
경계를 넘으려면 교차 프레임 연동이 필요하다.
```

`§6 Phase 5` 의 마지막 문단(`.btn-info`·`.text-info` 를 같이 정리한다는 내용)을
다음으로 바꾼다.

```markdown
~~같이 정리할 것: `SF-Custom.css` 의 `.btn-info`·`.text-info`(`#6451f3`).~~
**취소.** 템플릿에는 없지만 `common.js` 가 Alert 마크업을 동적 생성하며 쓴다.
템플릿만 grep 해서 "미사용"으로 판단한 것이 틀렸다. Phase 2 에서 색만 브랜드로
바꾸고 클래스는 남겼다.
```

- [ ] **Step 7: 커밋**

```bash
git add AGENTS.md docs/09_UI_DESIGN_SYSTEM.md
git commit -m "docs: Phase 2 모달 동작 통일 결과와 스펙 정정 반영"
```

- [ ] **Step 8: 브랜치를 마무리한다**

**REQUIRED SUB-SKILL:** superpowers:finishing-a-development-branch 를 쓴다.

---

## 범위 밖 (이 Phase 에서 하지 않는 것)

| 항목 | 왜 | 언제 |
|---|---|---|
| 백드롭이 셸을 덮게 하기 | iframe 경계를 넘으려면 교차 프레임 연동이 필요하다. 사용자가 범위 밖으로 결정했다 | 미정 |
| 기판을 네이티브 `<dialog>` 로 통일 | 드래그 기능 상실 + `columns_setting`(9화면)·`myinfo` 의 교차 프레임 호출 계약을 다시 써야 한다. 사용자가 기판 유지로 결정했다 | 미정 |
| 내정보 모달의 이중 프레임 근본 해소(B-1) | 기판 교체가 전제다. Phase 0 의 응급 처치가 유지된다 | 기판 통일을 하게 되면 |
| 모달 헤더·푸터 마크업 골격 통일 | 네 계열의 템플릿을 다시 써야 한다. 동작이 같아지면 체감 차이가 작다 | Phase 3 버튼 체계와 함께 |
| `app/index.html:1096` 의 `.btn-primary`("Buy Now") | 벤더 템플릿 잔재. 화면에 쓰이지 않는다 | Phase 5 |
