# Phase 3 — 버튼 역할↔형태 통일 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 버튼의 **형태가 역할을 말하게** 한다. 특히 되돌릴 수 없는 동작(삭제·API Key 재발급)이 지금은 비활성 버튼처럼 보이는 것을 고친다.

**Architecture:** 스펙 §5 의 4계층을 CSS 에서 **형태로** 구현한다. 새 클래스를 만들지 않고 기존 클래스(`btn-band`·`btn-input`·`btn-dell`·`outline-button`·`primary-button`·`danger-button`)의 선언을 계층에 맞춘다 — 템플릿 25화면을 건드리지 않아도 되고 diff 가 CSS 에 모인다. 예외는 검사 Client 의 맨 텍스트 버튼 2개로, 변형 클래스가 아예 없어 클래스를 더해야 한다. 치수(패딩·높이·테두리 굵기)는 바꾸지 않아 레이아웃이 움직이지 않는다.

**Tech Stack:** 순수 CSS 커스텀 프로퍼티 · Django Template · Playwright(검증)

**Spec:** [docs/09_UI_DESIGN_SYSTEM.md](../../09_UI_DESIGN_SYSTEM.md) §5(빨강의 역할 분리) · §6 Phase 3

---

## 범위 조정 (사용자 결정, 2026-10-02)

**형태만 통일한다. 치수는 손대지 않는다.** 따라서 Phase 1·2 와 같은 기준 —
`scripts/verify_layout_stable.py` 이동 **0건** — 을 그대로 쓴다.

Phase 1·2 에서 넘어온 항목 중 치수를 움직이는 것은 이번에도 하지 않는다.

| 항목 | 왜 미루나 |
|---|---|
| `--wzg-font-family: 'Malgun Gothic'` → Pretendard | `wezongrid.js:26713` 이 이 값으로 컬럼 폭을 **측정**한다 |
| 폼 높이 통일 (MES 32px ↔ 데이터 40–43px) | 25화면에서 아래 내용이 전부 밀린다 |
| `--crud-shell-height` 와 `--ct-topbar-height` 이중 높이 식 | 치수다 |
| 모달 헤더·푸터 **마크업** 골격 통일 | Phase 2 에서 동작은 맞췄다. 마크업은 네 계열 템플릿을 다시 써야 한다 |

**넘어온 항목 하나는 실체가 달랐다.** `SF-Custom.css:40` 의
`--ct-danger: #2e2e31` 는 **아무 효과가 없다** — `.text-danger` 와 `.btn-danger`
는 실측하면 벤더 분홍 `#fa5c7c` 로 렌더된다(`app.min.css` 가 `--ct-danger` 가
아닌 다른 경로로 색을 준다). 죽은 선언이므로 "진회색을 빨강으로 고친다"가
아니라 **실제로 분홍이 나오는 `.text-danger` 를 브랜드 오류색으로 맞추는 일**이
된다(Task 4).

---

## Global Constraints

- **레이아웃을 바꾸지 않는다.** `scripts/verify_layout_stable.py` 이동 0건. 패딩·높이·테두리 **굵기**·`border-radius` 를 건드리지 않는다. 바뀌는 것은 색뿐이다.
- **색 리터럴을 새로 쓰지 않는다.** 모든 색은 `tokens.css` 의 토큰을 거친다. `scripts/verify_tokens.py` 0건 유지.
- **새 버튼 클래스를 만들지 않는다.** 기존 클래스의 선언을 계층에 맞춘다. 템플릿 수정은 검사 Client 2줄뿐이다.
- **`app.min.css` 를 수정하지 않는다.** 벤더 테마는 오버라이드로만 다룬다(스펙 §7).
- **되돌릴 수 없는 동작은 빨강 외곽선 + 확인 단계**(스펙 §5). 확인 단계(`Alert.confirm`)는 이미 붙어 있다 — 형태만 맞춘다.
- **넓은 면적의 채움에 브랜드 빨강을 쓰지 않는다**(스펙 §5). 버튼은 좁은 면적이라 채움이 허용된다.
- **오류 상태색(`--brand-danger` `#bd5a4d`)과 되돌릴 수 없는 **동작**의 빨강(`--brand-primary` `#da2129`)은 다르다**(Phase 1 결정). 토스트·폼 오류는 전자, 삭제 버튼은 후자다.
- **모든 Git Commit 메시지는 한국어로 작성한다.** Conventional Commits 의 type 은 영문 유지.
- **테스트는 `--settings=configurations.test_settings` 로 돌린다.**
- **개발 서버는 `DB_CONN_MAX_AGE=0`** 이어야 한다(AGENTS.md [6]).
- 서버는 `http://127.0.0.1:8123` 에 떠 있어야 한다.

---

## 지금 상태 (전부 실측)

### §5 의 4계층 대 실제

| §5 역할 | 규정 형태 | MES 실제 | 데이터 실제 |
|---|---|---|---|
| 주요 동작 | 빨강 **채움** | `btn-search`(조회) `btn-band`(저장) — **맞다** | `primary-button` — **맞다** |
| 보조 동작 | 중립 **외곽선** | `btn-input`(등록) = `#2e2e31` **검정 채움** ✗ | `outline-button` — **맞다** |
| 되돌릴 수 없는 동작 | 빨강 **외곽선** | `btn-dell`(삭제) = `#9a9a9a` **회색 채움** ✗ | `danger-button` = 오류색 틴트 ✗ |
| 비활성 | 회색 채움 | `#dfdfe0` — 맞다 | 맞다 |

### 가장 큰 문제

**삭제가 비활성처럼 보인다.** 활성 삭제 `#9a9a9a`, 비활성 `#dfdfe0` — 둘 다
회색이라 눌러도 되는지 알 수 없고, 반대로 진짜 비활성 버튼과 구분되지 않는다.
되돌릴 수 없는 동작인데 화면에서 가장 약하다.

**등록이 검정 채움이라 주요 동작보다 강해 보인다.** 상세정보 툴바에서
`등록`(검정) · `삭제`(회색) · `저장`(빨강)이 나란히 있는데, 시각적 무게가
역할과 어긋난다.

### 맨 텍스트 동작 버튼 4개 (스펙은 2개로 적었다)

```html
<button type="button" class="btn y_write_auth" id="btnReissue">API Key 재발급</button>
<button type="button" class="btn y_write_auth" id="btnToggle">사용/중지</button>
```

변형 클래스가 없어 배경·테두리가 투명하다(실측: `배경 rgba(0,0,0,0)`,
`테두리 1px` 이지만 색이 투명, `글자 #242424`). 빨간 버튼 둘(`등록`·`저장`)
사이에 맨 글씨로 끼어 있다. **`API Key 재발급` 은 되돌릴 수 없는 동작인데
화면에서 가장 안 보인다.**

**스펙 §2.5 는 이것을 검사 Client 의 2개로 적었으나 실제로는 4개다.**
하네스가 `vision/` 세 화면에서 전부 찾았다 — `매핑 해제`
(`wm_vis_model_mapping`)와 `표시/숨김`(`wm_vis_overlay`)도 같은 모양이다.

### 4계층에 넣지 않는 것

§5 의 4계층은 **동작 버튼**의 등급이다. 아래는 등급이 아니라 다른 종류라
그대로 둔다.

| 클래스 | 무엇인가 | 왜 두나 |
|---|---|---|
| `btn-icon` · `icon-button` · `btn-white` | 아이콘 버튼 | 글자가 없어 등급이 성립하지 않는다 |
| `text-button` | 텍스트 링크(`전체 보기` · `다음 작업 →`) | 동작 버튼이 아니라 이동이다 |
| `tool-button` | 라벨링 도구 토글(BBOX · Polygon) | 동작이 아니라 모드 선택이다 |
| `edit-button` | **상태** 표시 — `labeling.html:249` 가 `dirty` 일 때만 활성화한다 | 등급이 아니라 "저장하지 않은 변경이 있다"는 신호다 |

### 화면당 형태 종류 (스펙 §6 Phase 3 의 기준)

15화면을 실측하니 **13화면이 이미 3종 이하**다(초과 2개는 `wm_multi_language` 4종,
`wm_data_image` 4종). `wm_data_image` 의 4종은 주요·보조·위험·아이콘이라 정당하다.

**그래서 이 Phase 의 합격 기준을 "3종 이하"가 아니라 "형태가 역할에
대응하는가"로 바꾼다.** 개수는 이미 충족돼 있고, 줄이는 것이 목적이 아니다.

---

## File Structure

| 파일 | 상태 | 책임 |
|---|---|---|
| `app/static/assets/css/SF-Custom.css` | 수정 | MES 계열 3계층 — `.btn-input`(보조) · `.btn-dell`(위험) · `.text-danger`(오류 글자) |
| `app/static/data/aidatahub.css` | 수정 | 데이터 계열 위험 계층 — `.danger-button` |
| `app/templates/vision/client.html:29-30` | 수정 | 맨 텍스트 2개에 변형 클래스 부여 |
| `scripts/verify_buttons.py` | **신규** | 버튼의 역할↔형태 대응을 재고, 맨 텍스트 버튼을 잡는다 |
| `AGENTS.md` | 수정 | 검증 명령에 `verify_buttons.py` 추가 |
| `docs/09_UI_DESIGN_SYSTEM.md` | 수정 | §6 Phase 3 결과 기록, 합격 기준 정정, `--ct-danger` 정정 |

**수정하지 않는 파일:** `app.min.css`, `wezongrid.css`, 나머지 24화면 템플릿, `tokens.css`(이미 필요한 토큰이 전부 있다).

---

## 형태 규칙 (단일 정의)

치수는 건드리지 않는다. **색 세 개만** 바뀐다 — 배경·글자·테두리색.

| 계층 | 배경 | 글자 | 테두리 | 쓰는 클래스 |
|---|---|---|---|---|
| **주요 동작** | `var(--brand-primary)` | `#fff` | `1px solid var(--brand-primary)` | `.btn-band` `.btn-search` `.primary-button` |
| **보조 동작** | `transparent` | `var(--brand-ink-2)` | `1px solid var(--brand-line)` | `.btn-input` `.outline-button` `.btn-outline-light` |
| **되돌릴 수 없는 동작** | `transparent` | `var(--brand-primary)` | `1px solid var(--brand-primary)` | `.btn-dell` `.danger-button` |
| **비활성** | `#dfdfe0`(기존 `--ct-btn-disabled-bg`) | — | — | 전부 공통 |

주요와 위험이 **같은 빨강인데 채움/외곽선으로 갈린다.** §5 가 "색상(hue)으로
나누지 않고 형태로 나눈다"고 한 이유다 — 브랜드가 빨강인 이상 "덜 위험한
빨강"을 따로 만들어도 구분되지 않는다.

**보조 계층의 목표값은 데이터의 `outline-button` 과 정확히 같다**(실측:
배경 `rgba(0,0,0,0)`, 글자 `rgb(46,46,49)`, 테두리 `1px rgb(216,216,216)`).
두 계열이 한 형태로 만난다.

---

### Task 1: 버튼 검증 하네스

규칙을 코드로 적는다. 먼저 만들고 **실제로 실패하는 것을 본 뒤** 고친다.

**Files:**
- Create: `scripts/verify_buttons.py`

**Interfaces:**
- Produces: `python scripts/verify_buttons.py`. 위반이 하나라도 있으면 종료코드 1.
- Consumes: `.admin_pw`, 떠 있는 개발 서버, playwright.

- [ ] **Step 1: 하네스를 작성한다**

```python
#!/usr/bin/env python
"""버튼의 형태가 역할을 말하는지 본다.

스펙 §5 는 역할을 색상이 아니라 **형태**로 나눈다 — 주요는 빨강 채움,
되돌릴 수 없는 동작은 빨강 외곽선, 보조는 중립 외곽선. 클래스 이름으로
역할을 알 수 있으므로, 클래스마다 기대 형태를 적어 두고 실제 렌더링과 맞춘다.

    python scripts/verify_buttons.py

치수(패딩·높이·테두리 굵기)는 재지 않는다. Phase 3 은 색만 바꾸고,
레이아웃 불변은 scripts/verify_layout_stable.py 가 따로 본다.
"""
import pathlib
import re
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8123'
VIEWPORT = {'width': 1920, 'height': 911}

TRANSPARENT = (0, 0, 0, 0.0)
BRAND = (218, 33, 41)
WHITE = (255, 255, 255)
INK2 = (46, 46, 49)
LINE = (216, 216, 216)

# 계층별 기대 형태. (배경, 글자, 테두리색) — None 은 "보지 않는다".
TIERS = {
    '주요':   {'bg': BRAND,       'color': WHITE, 'border': BRAND},
    '보조':   {'bg': TRANSPARENT, 'color': INK2,  'border': LINE},
    '위험':   {'bg': TRANSPARENT, 'color': BRAND, 'border': BRAND},
}

# 클래스 → 계층. 여기 없는 클래스는 동작 버튼이 아니므로 보지 않는다
# (아이콘·텍스트 링크·토글·상태 표시). 근거는 계획의 "4계층에 넣지 않는 것".
CLASS_TIER = {
    'btn-band': '주요', 'btn-search': '주요', 'primary-button': '주요',
    'btn-input': '보조', 'outline-button': '보조', 'btn-outline-light': '보조',
    'btn-dell': '위험', 'danger-button': '위험',
}

# 맨 텍스트 버튼(배경도 테두리도 없는 동작 버튼)을 허용하는 클래스.
# 이동(링크)과 아이콘은 맨 텍스트여도 된다.
BARE_OK = {'text-button', 'icon-button', 'btn-icon', 'btn-white', 'btn-close',
           'btn-newpadge', 'tool-button', 'wzg-pager-btn', 'wzg-page-btn',
           'btn-check', 'btn-group'}

SCREENS = [
    'wm_user', 'wm_user_group', 'wm_user_group_menu', 'wm_multi_language',
    'wm_menu_language', 'wm_prop_master',
    'wm_data_item', 'wm_data_item_detail', 'wm_data_image', 'wm_data_snapshot',
    'wm_vis_inspection', 'wm_vis_client', 'wm_vis_model',
    'wm_vis_model_mapping', 'wm_vis_overlay',
    'wm_code', 'wm_company', 'wm_depart', 'wm_unit',
]

COLLECT_JS = """() => Array.from(document.querySelectorAll('button, a.btn'))
    .filter(b => b.offsetHeight > 0 && !b.disabled)
    .map(b => {
        const s = getComputedStyle(b);
        return {
            cls: (b.className || '').toString(),
            text: (b.textContent || '').trim().slice(0, 14),
            bg: s.backgroundColor,
            color: s.color,
            border: s.borderTopColor,
            bw: s.borderTopWidth,
        };
    })"""


def _rgba(value):
    nums = re.findall(r'[\d.]+', value or '')
    if len(nums) < 3:
        return None
    rgb = tuple(int(float(n)) for n in nums[:3])
    alpha = float(nums[3]) if len(nums) > 3 else 1.0
    return rgb + (alpha,)


def _same(actual, expected):
    """기대값이 4튜플(투명)이면 알파까지, 3튜플이면 rgb 만 본다."""
    got = _rgba(actual)
    if got is None:
        return False
    if len(expected) == 4:
        return got[3] == expected[3]
    return got[:3] == expected


def _is_bare(item):
    """배경도 테두리도 보이지 않는 버튼."""
    bg = _rgba(item['bg'])
    border = _rgba(item['border'])
    bg_invisible = bg is not None and bg[3] == 0.0
    border_invisible = (border is not None and border[3] == 0.0) or item['bw'] == '0px'
    return bg_invisible and border_invisible


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

        for code in SCREENS:
            url = '{}/gui/{}/{}'.format(
                BASE, code, '?project=3' if code.startswith('wm_data_') else '')
            page.goto(url, wait_until='domcontentloaded', timeout=25000)
            page.wait_for_timeout(2500)

            for item in page.evaluate(COLLECT_JS):
                classes = set(item['cls'].split())

                tier = None
                for cls in classes:
                    if cls in CLASS_TIER:
                        tier = CLASS_TIER[cls]
                        break

                if tier:
                    want = TIERS[tier]
                    for key, label in (('bg', '배경'), ('color', '글자'), ('border', '테두리')):
                        if not _same(item[key], want[key]):
                            violations.append((code, item['text'], '{} {} {} (기대 {})'.format(
                                tier, label, item[key], want[key])))
                    continue

                # 등급이 없는 버튼 중 맨 텍스트인 것은 허용 목록에 있어야 한다.
                if _is_bare(item) and not (classes & BARE_OK):
                    violations.append((code, item['text'],
                                       '맨 텍스트 버튼 (클래스: {})'.format(item['cls'][:40])))

        browser.close()

    for code, text, why in violations:
        print('위반  {:22} {:14} {}'.format(code, text, why))

    print('\n버튼 규칙 위반 {}건'.format(len(violations)))
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
.venv/bin/python scripts/verify_buttons.py
```

Expected: `버튼 규칙 위반 73건` `FAIL`. 계획을 쓰며 실제로 돌려 얻은 수다.

| 없애는 Task | 내역 | 건수 |
|---|---|---|
| Task 2 | `btn-input`(등록·수정) 배경·글자·테두리 3개씩 | 39 |
| Task 2 | `btn-dell`(삭제) 배경·글자·테두리 3개씩 | 30 |
| Task 3 | `danger-button` — 기본 화면에 안 떠서 0건으로 잡힌다 | 0 |
| Task 4 | 맨 텍스트 버튼 | 4 |

`btn-band`·`btn-search`·`primary-button`·`outline-button` 에서는 **한 건도
나오지 않는다.** 이미 맞는 계층이 틀렸다고 나오면 규칙 쪽이 잘못된 것이므로
멈춘다.

**하네스가 계획보다 많이 찾았다.** 스펙 §2.5 는 맨 텍스트를 검사 Client 의
2개로 적었는데, 실제로는 `vision/` 세 화면에 **4개**다 — 전부
`<button type="button" class="btn y_write_auth" id="…">` 라는 같은 모양이다.

| 화면 | 버튼 | 되돌릴 수 있나 | 계층 |
|---|---|---|---|
| `wm_vis_client` | `API Key 재발급` | **아니다** — 기존 키가 즉시 무효가 되고 배포된 Client 가 끊긴다 | 위험 |
| `wm_vis_client` | `사용/중지` | 그렇다 (다시 누르면 복귀) | 보조 |
| `wm_vis_model_mapping` | `매핑 해제` | 그렇다 (다시 매핑) | 보조 |
| `wm_vis_overlay` | `표시/숨김` | 그렇다 | 보조 |

`danger-button` 은 `item_modal_edit.html` 안에만 있어 모달을 열지 않으면
잡히지 않는다. Task 3 은 하네스가 아니라 **직접 열어 확인**한다.

- [ ] **Step 3: 커밋**

```bash
git add scripts/verify_buttons.py
git commit -m "test: 버튼의 역할↔형태 대응을 재는 하네스 추가"
```

---

### Task 2: MES 계열 — 등록(보조)과 삭제(위험)

**Files:**
- Modify: `app/static/assets/css/SF-Custom.css:697-718`

**Interfaces:**
- Consumes: Phase 1 의 `--brand-primary` · `--brand-primary-hover` · `--brand-ink-2` · `--brand-line` · `--brand-surface-2`.
- Produces: 없음.

- [ ] **Step 1: `.btn-input`(등록)을 보조 계층으로 바꾼다**

`SF-Custom.css:697-706` 의 두 블록을 다음으로 바꾼다. **치수는 한 글자도
바꾸지 않는다** — `white-space: nowrap` 과 테두리 굵기 `1px` 이 그대로다.

```css
/* 등록 = 보조 동작. 입력 폼을 새로 여는 동작이고, 실제 반영은 저장이다.
   검정 채움(#2e2e31)이라 주요 동작(빨강)보다 무거워 보였다(09_UI_DESIGN_SYSTEM §5). */
.btn-input {
    color: var(--brand-ink-2);
    background: transparent;
    border: 1px solid var(--brand-line);
    white-space: nowrap;
}
.btn-input:hover, .btn-input:active  {
    color: var(--brand-ink-2);
    background: var(--brand-surface-2);
    border: 1px solid var(--brand-line-strong);
}
```

- [ ] **Step 2: `.btn-dell`(삭제)을 위험 계층으로 바꾼다**

`SF-Custom.css:708-718` 의 두 블록을 다음으로 바꾼다.

```css
/* 삭제 = 되돌릴 수 없는 동작. 빨강 외곽선이다(09_UI_DESIGN_SYSTEM §5).
   회색 채움(#9a9a9a)이던 것이 비활성(#dfdfe0)과 구분되지 않아, 화면에서
   가장 위험한 동작이 가장 약해 보였다. 채움을 쓰지 않는 이유는 주요
   동작(저장·조회)과 같은 빨강이기 때문이다 — 형태로 가른다. */
.btn-dell {
    color: var(--brand-primary);
    background: transparent;
    border: 1px solid var(--brand-primary);
    white-space: nowrap;
}
.btn-dell:hover, .btn-dell:active  {
    color: #fff;
    background: var(--brand-primary);
    border: 1px solid var(--brand-primary);
}
```

호버에서 채움으로 바뀌는 것은 의도다 — 누르려는 순간에만 무게가 올라간다.

- [ ] **Step 3: 하네스로 MES 위반이 사라졌는지 본다**

```bash
.venv/bin/python scripts/verify_buttons.py
```

Expected: `btn-input`·`btn-dell` 위반이 사라지고 `danger-button` 과 맨 텍스트
위반만 남는다.

- [ ] **Step 4: 레이아웃이 움직이지 않았는지 본다**

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-p3-t2
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-base-font /tmp/geo-p3-t2
```

`/tmp/geo-base-font` 가 없으면 작업 전 커밋에서 먼저 기준선을 뜬다.

Expected: `PASS`, 이동 0건. 색만 바꿨다.

- [ ] **Step 5: 색 토큰을 확인한다**

```bash
.venv/bin/python scripts/verify_tokens.py | tail -2
```

Expected: `토큰을 거치지 않은 선언 0건` `PASS`.

- [ ] **Step 6: 눈으로 본다**

```bash
cat > /tmp/shot_btn_mes.py <<'PY'
import pathlib
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:8123'; PW=pathlib.Path('.admin_pw').read_text(encoding='utf-8').strip()
with sync_playwright() as pw:
    b=pw.chromium.launch(); p=b.new_context(viewport={'width':1920,'height':911}).new_page()
    p.goto(BASE+'/login/',wait_until='domcontentloaded')
    p.fill('#loginId','admin'); p.fill('#loginPwd',PW); p.click('#login')
    p.wait_for_url(BASE+'/',timeout=15000)
    p.goto(BASE+'/gui/wm_user/',wait_until='domcontentloaded'); p.wait_for_timeout(2600)
    # 행을 골라 삭제·저장을 활성화한다
    p.evaluate("() => { const r=document.querySelector('.wzg-row'); r && r.click(); }")
    p.wait_for_timeout(1200)
    p.screenshot(path='/tmp/p3-mes-buttons.png')
    b.close()
PY
.venv/bin/python /tmp/shot_btn_mes.py
```

`/tmp/p3-mes-buttons.png` 의 오른쪽 아래 툴바를 본다. 확인할 것:

1. `저장` 은 빨강 **채움**, `삭제` 는 빨강 **외곽선** — 한눈에 다르다
2. `등록` 은 중립 외곽선이고 `저장` 보다 가벼워 보인다
3. 비활성 버튼(연회색 채움)과 `삭제` 가 **구분된다**

- [ ] **Step 7: 커밋**

```bash
git add app/static/assets/css/SF-Custom.css
git commit -m "fix: MES 삭제 버튼을 빨강 외곽선으로, 등록을 중립 외곽선으로

삭제가 회색 채움(#9a9a9a)이라 비활성(#dfdfe0)과 구분되지 않았다. 되돌릴 수
없는 동작인데 화면에서 가장 약했다. 09_UI_DESIGN_SYSTEM §5 대로 빨강
외곽선으로 바꾼다 — 주요 동작(저장)과 같은 빨강이지만 채움/외곽선으로
갈린다.

등록은 검정 채움이라 주요 동작보다 무거워 보였다. 입력 폼을 새로 여는
보조 동작이므로 중립 외곽선으로 내린다.

치수는 건드리지 않았다. 레이아웃 이동 0건."
```

---

### Task 3: 데이터 계열 — `danger-button`

**Files:**
- Modify: `app/static/data/aidatahub.css:321-323`

**Interfaces:**
- Consumes: Phase 1 의 `--brand-primary`.
- Produces: 없음.

`danger-button` 은 지금 **오류색**(`--brand-danger` `#bd5a4d` 계열)을 쓴다.
Phase 1 에서 오류 **상태**와 되돌릴 수 없는 **동작**을 갈랐다 — 토스트·폼
오류는 `#bd5a4d`, 삭제 버튼은 브랜드 빨강이다. 이 버튼은 후자다.

- [ ] **Step 1: 위험 계층으로 바꾼다**

`aidatahub.css:321-323` 의 세 줄을 다음으로 바꾼다. `display`·`min-height`·
`padding`·`border-radius`·`gap` 은 **원문 그대로 유지한다** — 색 세 개만 바뀐다.

```css
/* 되돌릴 수 없는 동작 = 빨강 외곽선(09_UI_DESIGN_SYSTEM §5). 오류색
   (--brand-danger #bd5a4d)은 토스트·폼 오류 같은 '상태'용이고, 삭제는
   '동작'이라 브랜드 빨강을 쓴다. Phase 1 에서 둘을 갈랐다. */
.danger-button { display: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 40px; padding: 0 17px; border: 1px solid var(--brand-primary); border-radius: 4px; color: var(--brand-primary); background: transparent; font-size: 14px; font-weight: 700; }
.danger-button:hover { color: #fff; background: var(--brand-primary); border-color: var(--brand-primary); }
.danger-button:disabled { cursor: not-allowed; opacity: .46; }
```

**주의:** 위 첫 줄의 `font-size`·`font-weight` 는 원문과 같아야 한다. 고치기
전에 원문을 읽어 `display` 부터 `border-radius` 까지가 일치하는지 확인한다.

```bash
grep -n '^\.danger-button {' app/static/data/aidatahub.css
```

- [ ] **Step 2: 하네스로 확인한다**

```bash
.venv/bin/python scripts/verify_buttons.py
```

Expected: `danger-button` 위반이 사라지고 **맨 텍스트 2건만 남는다**.

- [ ] **Step 3: 레이아웃과 토큰을 확인한다**

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-p3-t3
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-base-font /tmp/geo-p3-t3
.venv/bin/python scripts/verify_tokens.py | tail -2
```

Expected: 레이아웃 `PASS` 이동 0건, 토큰 `PASS`.

`danger-button` 이 `item_modal_edit.html` 안에만 있어 기본 화면 캡처에는
나오지 않는다 — 레이아웃 비교에 영향이 없는 것이 정상이다.

- [ ] **Step 4: 커밋**

```bash
git add app/static/data/aidatahub.css
git commit -m "fix: 데이터 계열 삭제 버튼을 오류색에서 브랜드 빨강 외곽선으로

Phase 1 에서 오류 '상태'(#bd5a4d)와 되돌릴 수 없는 '동작'(브랜드 빨강)을
갈랐는데 이 버튼이 전자를 쓰고 있었다. 삭제는 동작이다.
치수는 그대로다."
```

---

### Task 4: 검사 Client 의 맨 텍스트 2개 승격

**Files:**
- Modify: `app/templates/vision/client.html:29-30`
- Modify: `app/templates/vision/model_mapping.html:28`
- Modify: `app/templates/vision/overlay.html:28`
- Modify: `app/static/assets/css/SF-Custom.css` (`.text-danger` 오버라이드 신설)

**Interfaces:**
- Consumes: Task 2 가 고친 `.btn-dell`(위험) · `.btn-input`(보조).
- Produces: 없음.

- [ ] **Step 1: 네 버튼에 계층 클래스를 준다**

세 템플릿이다. `y_write_auth` 는 쓰기 권한에 따라 JS 가 숨기는 클래스다.
**지우면 권한 제어가 사라진다 — 반드시 남긴다.**

```bash
cd /home/yhan/projects/manufacturing_ai_platform
sed -i 's|<button type="button" class="btn y_write_auth" id="btnReissue">|<button type="button" class="btn btn-dell y_write_auth" id="btnReissue">|' app/templates/vision/client.html
sed -i 's|<button type="button" class="btn y_write_auth" id="btnToggle">|<button type="button" class="btn btn-input y_write_auth" id="btnToggle">|' app/templates/vision/client.html
sed -i 's|<button type="button" class="btn y_write_auth" id="btnDeactivate">|<button type="button" class="btn btn-input y_write_auth" id="btnDeactivate">|' app/templates/vision/model_mapping.html
sed -i 's|<button type="button" class="btn y_write_auth" id="btnToggle">|<button type="button" class="btn btn-input y_write_auth" id="btnToggle">|' app/templates/vision/overlay.html
grep -n 'btn-dell y_write_auth\|btn-input y_write_auth' app/templates/vision/*.html
```

Expected: 4줄이 나온다 (client 2 · model_mapping 1 · overlay 1).
하나라도 비면 그 파일의 원문을 직접 읽어 수동으로 고친다.

배정 근거:

- `API Key 재발급` → `btn-dell`(**위험**). 기존 키가 즉시 무효가 되고 배포된
  Client 가 끊긴다. 되돌릴 수 없다
- `사용/중지` · `매핑 해제` · `표시/숨김` → `btn-input`(**보조**). 전부 다시
  눌러 되돌릴 수 있는 토글이다

- [ ] **Step 2: 확인 단계가 붙어 있는지 본다**

§5 는 되돌릴 수 없는 동작에 **빨강 외곽선 + 확인 단계**를 요구한다. 형태는
Step 1 에서 붙었으니 확인 단계가 있는지 읽는다.

```bash
grep -n -A12 'reissue()\s*{' app/templates/vision/client.html | grep -E 'Alert.confirm'
```

Expected: `client.html:117` 근처에서
`Alert.confirm('확인', '기존 키가 즉시 무효가 된다…')` 가 나온다 — **계획을
쓰며 이미 확인했다.** 나오지 않으면 멈추고 보고한다.

보조로 분류한 셋은 되돌릴 수 있으므로 §5 가 확인 단계를 요구하지 않는다.
`deactivate()` 에 확인이 없는 것은 의도대로다.

- [ ] **Step 3: `.text-danger` 를 브랜드 오류색으로 맞춘다**

같은 화면의 `지금만 확인할 수 있다…` 문구가 `.text-danger` 인데, 실측하면
벤더 분홍 `#fa5c7c` 로 렌더된다. `SF-Custom.css:40` 의 `--ct-danger: #2e2e31`
는 이 색을 만들지 않아 **죽은 선언**이다.

`SF-Custom.css` 의 `.text-info` 정의 바로 뒤에 다음을 더한다.

```css
/* app.min.css 의 .text-danger 는 벤더 분홍(#fa5c7c)으로 렌더된다.
   SF-Custom 의 --ct-danger 오버라이드는 이 색에 닿지 않는 죽은 선언이다.
   오류 글자는 Phase 1 에서 정한 --brand-danger 로 모은다. */
.text-danger {
    color: var(--brand-danger) !important;
}
```

- [ ] **Step 4: 하네스가 전부 통과하는지 본다 (GREEN)**

```bash
.venv/bin/python scripts/verify_buttons.py
```

Expected: `버튼 규칙 위반 0건` `PASS`.

- [ ] **Step 5: 화면 오류와 레이아웃을 본다**

템플릿을 고쳤으므로 JS 검사도 돌린다.

```bash
node scripts/verify_screen_js.js | tail -2
.venv/bin/python scripts/verify_tokens.py | tail -2
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-p3-t4
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-base-font /tmp/geo-p3-t4
```

Expected: 전부 `PASS`.

**레이아웃 이동이 나오면 멈춘다.** 맨 텍스트였던 버튼에 테두리색이 생기는
것은 치수를 바꾸지 않아야 한다(`border-width` 는 이미 `1px` 이었다). 이동이
나오면 `.btn-dell`·`.btn-input` 의 패딩이 `.btn` 기본과 다른 것이므로 그
차이를 먼저 확인한다.

- [ ] **Step 6: 눈으로 본다**

```bash
cat > /tmp/shot_client.py <<'PY'
import pathlib
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:8123'; PW=pathlib.Path('.admin_pw').read_text(encoding='utf-8').strip()
with sync_playwright() as pw:
    b=pw.chromium.launch(); p=b.new_context(viewport={'width':1920,'height':911}).new_page()
    p.goto(BASE+'/login/',wait_until='domcontentloaded')
    p.fill('#loginId','admin'); p.fill('#loginPwd',PW); p.click('#login')
    p.wait_for_url(BASE+'/',timeout=15000)
    p.goto(BASE+'/gui/wm_vis_client/',wait_until='domcontentloaded'); p.wait_for_timeout(2600)
    p.evaluate("() => { const r=document.querySelector('.wzg-row'); r && r.click(); }")
    p.wait_for_timeout(1200); p.screenshot(path='/tmp/p3-client.png')
    b.close()
PY
.venv/bin/python /tmp/shot_client.py
```

`/tmp/p3-client.png` 의 상세정보 툴바를 본다. 확인할 것:

1. `API Key 재발급` 이 빨강 외곽선이라 **눈에 띈다**
2. `사용/중지` 가 중립 외곽선이다
3. 네 버튼(`등록`·`API Key 재발급`·`사용/중지`·`저장`)의 무게가 역할 순이다
4. 맨 텍스트가 없다

- [ ] **Step 7: 커밋**

```bash
git add app/templates/vision/client.html app/static/assets/css/SF-Custom.css
git commit -m "fix: 검사 Client 의 맨 텍스트 동작 2개를 버튼으로 승격

API Key 재발급과 사용/중지가 변형 클래스 없이 <button class=\"btn\"> 이라
배경도 테두리도 없는 맨 글씨였다. 빨간 버튼 둘 사이에 끼어 있어 되돌릴 수
없는 동작(재발급)이 화면에서 가장 안 보였다.

재발급은 위험(빨강 외곽선), 사용/중지는 보조(중립 외곽선)로 준다.
y_write_auth 는 권한 제어 클래스라 그대로 둔다.

같은 화면의 .text-danger 가 벤더 분홍(#fa5c7c)으로 나오던 것도
--brand-danger 로 맞췄다. SF-Custom 의 --ct-danger 오버라이드는 이 색에
닿지 않는 죽은 선언이었다."
```

---

### Task 5: 전수 검증 + 문서 갱신

**Files:**
- Modify: `AGENTS.md` ([6] 검증 명령 목록)
- Modify: `docs/09_UI_DESIGN_SYSTEM.md` (§6 Phase 3 결과, 합격 기준 정정, `--ct-danger` 정정)

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
.venv/bin/python scripts/verify_buttons.py | tail -2
```

Expected: 단위테스트 64 OK, 검증 스크립트 7종 전부 `PASS`.

- [ ] **Step 2: 레이아웃 불변을 확인한다**

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-p3-final
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-base-font /tmp/geo-p3-final
```

Expected: `PASS`, 이동 0건.

- [ ] **Step 3: 25화면 캡처와 e2e 를 돌린다**

e2e 전에 DB 커넥션을 확인한다(AGENTS.md [6]).

```bash
.venv/bin/python scripts/capture_ui.py /tmp/ui-p3 2>&1 | tail -3
.venv/bin/python -m pytest tests/e2e -q --tb=line 2>&1 | tail -4
```

Expected: `화면 25개 / 오류 0건` `PASS`, `58 passed`.

- [ ] **Step 4: 캡처를 눈으로 본다**

`/tmp/ui-p3/01-system/wm_user.png` · `/tmp/ui-p3/03-vision/wm_vis_client.png` ·
`/tmp/ui-p3/04-basic/wm_code.png` 를 연다. 확인할 것:

1. 빨강 채움은 **주요 동작에만** 있다(조회·저장·추가)
2. 빨강 외곽선은 **되돌릴 수 없는 동작에만** 있다(삭제·재발급)
3. 중립 외곽선이 보조 동작이다(등록·사용/중지·닫기)
4. 검정 채움 버튼이 **한 개도 없다**
5. 글자가 사라지거나 대비가 무너진 곳이 없다

- [ ] **Step 5: `AGENTS.md` 의 검증 목록에 더한다**

`[6] 실행` 의 검증 블록에서 `verify_modals.py` 줄 바로 뒤에 더한다.

```bash
python scripts/verify_buttons.py                 # 버튼 역할 ↔ 형태 (서버 필요)
```

- [ ] **Step 6: 스펙을 갱신한다**

`docs/09_UI_DESIGN_SYSTEM.md` 의 `### Phase 3 — 버튼·폼 체계` 절 본문을
다음으로 바꾼다.

```markdown
### Phase 3 — 버튼 역할↔형태 통일 (완료, 2026-10-02)

**형태만 통일하고 치수는 손대지 않기로 했다**(사용자 결정). 그래서 Phase 1·2
와 같은 기준 — 레이아웃 이동 0건 — 을 그대로 썼다.

§5 의 4계층을 **기존 클래스의 선언을 맞추는 방식**으로 구현했다. 새 클래스를
만들지 않아 템플릿 25화면을 건드리지 않았다(예외는 검사 Client 2줄).

| 계층 | 형태 | 클래스 |
|---|---|---|
| 주요 동작 | 빨강 채움 | `.btn-band` `.btn-search` `.primary-button` |
| 보조 동작 | 중립 외곽선 | `.btn-input` `.outline-button` `.btn-outline-light` |
| 되돌릴 수 없는 동작 | 빨강 외곽선 | `.btn-dell` `.danger-button` |
| 비활성 | 회색 채움 `#dfdfe0` | 공통 |

고친 것:

- **삭제가 비활성처럼 보이던 문제.** 활성 삭제 `#9a9a9a`, 비활성 `#dfdfe0`
  로 둘 다 회색이라 눌러도 되는지 알 수 없었다. 화면에서 가장 위험한 동작이
  가장 약했다
- **등록이 검정 채움**이라 주요 동작보다 무거워 보이던 것
- **데이터의 `danger-button` 이 오류색**(`#bd5a4d`)을 쓰던 것. Phase 1 에서
  오류 '상태'와 되돌릴 수 없는 '동작'을 갈랐고, 삭제는 동작이다
- **검사 Client 의 맨 텍스트 2개.** `API Key 재발급`(위험) ·
  `사용/중지`(보조)

**합격 기준을 바꿨다.** 원안은 "화면당 버튼 색 3종 이하"였는데 실측하니
15화면 중 13화면이 이미 3종 이하였고, 초과한 `wm_data_image` 의 4종은
주요·보조·위험·아이콘이라 정당하다. 개수가 아니라 **형태가 역할에
대응하는가**를 본다 — `scripts/verify_buttons.py` 가 클래스별 기대 형태와
실제 렌더링을 맞춘다.

**4계층에 넣지 않은 것:** 아이콘 버튼(`btn-icon`·`icon-button`), 텍스트
링크(`text-button`), 도구 토글(`tool-button`), 상태 표시(`edit-button` —
`labeling.html:249` 가 `dirty` 일 때만 활성화한다). 동작 등급이 아니다.

**남긴 것:** 폼 높이 통일(MES 32px ↔ 데이터 40–43px), 그리드 서체, 이중 높이
식, 모달 마크업 골격. 전부 치수라 레이아웃이 움직인다.
```

같은 문서의 §6 Phase 5 절에서 `--ct-danger` 를 언급한 곳이 있으면 다음을 더한다.

```markdown
**`--ct-danger: #2e2e31`(`SF-Custom.css:40`)은 죽은 선언이다.** 실측하면
`.text-danger`·`.btn-danger` 는 벤더 분홍 `#fa5c7c` 로 렌더된다 — 이 변수가
그 색에 닿지 않는다. Phase 3 에서 `.text-danger` 를 `--brand-danger` 로
직접 덮었다. 변수 자체는 제거 대상이다.
```

- [ ] **Step 7: 커밋**

```bash
git add AGENTS.md docs/09_UI_DESIGN_SYSTEM.md
git commit -m "docs: Phase 3 버튼 역할↔형태 통일 결과와 합격 기준 정정 반영"
```

- [ ] **Step 8: 브랜치를 마무리한다**

**REQUIRED SUB-SKILL:** superpowers:finishing-a-development-branch 를 쓴다.

---

## 범위 밖

| 항목 | 왜 | 언제 |
|---|---|---|
| 폼 높이 통일 (MES 32px ↔ 데이터 40–43px) | 25화면에서 아래 내용이 밀린다 | 치수를 손대기로 할 때 |
| `--wzg-font-family` → Pretendard | `wezongrid.js:26713` 이 컬럼 폭 측정에 쓴다 | 〃 |
| `--crud-shell-height` 와 `--ct-topbar-height` 이중 높이 식 | 치수다 | 〃 |
| 모달 헤더·푸터 마크업 골격 통일 | 네 계열 템플릿을 다시 써야 한다. Phase 2 에서 동작은 이미 맞췄다 | 미정 |
| `--ct-danger` 변수 제거 | 죽은 선언이지만 지우는 것 자체는 효과가 없다 | Phase 5 |
| `app/index.html:1096` 의 `.btn-primary`("Buy Now") | 벤더 템플릿 잔재 | Phase 5 |
