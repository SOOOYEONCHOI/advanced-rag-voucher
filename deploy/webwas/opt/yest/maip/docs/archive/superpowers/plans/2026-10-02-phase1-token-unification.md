# Phase 1 — 토큰 단일화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 서로 모르는 세 개의 CSS 토큰 네임스페이스(`--ct-*` · 데이터 계열 · `--wzg-*`)를 단일 원천에서 파생시키고, 손으로 쌓인 하드코딩 색 74종을 브랜드 램프로 접는다.

**Architecture:** `app/static/assets/css/tokens.css` 한 장을 새로 만들어 **모든 레이아웃의 스타일시트 맨 뒤**에 싣는다. 이 파일은 색을 다시 선언하지 않고 **브랜드 램프를 선언한 뒤 세 네임스페이스를 거기에 매핑**한다. 기존 CSS 는 하드코딩 리터럴을 `var()` 로 바꾸는 것 외에 구조를 건드리지 않는다. 레이아웃이 움직이지 않았다는 것은 눈이 아니라 **요소 바운딩 박스 전수 비교**로 증명한다.

**Tech Stack:** 순수 CSS 커스텀 프로퍼티(빌드 단계 없음) · Playwright(검증 하네스) · Python 3.12

**Spec:** [docs/09_UI_DESIGN_SYSTEM.md](../../09_UI_DESIGN_SYSTEM.md) — 특히 §4(접근) · §5(빨강의 역할 분리) · §6 Phase 1

---

## Global Constraints

스펙과 `AGENTS.md` 에서 그대로 옮긴다. 모든 Task 에 암묵적으로 적용된다.

- **`--brand-primary` 는 `#da2129`** 다. 로고(`docs/yest.png`)가 브랜드의 정본이고 CSS 의 기존 `#ea1b1b` 를 대체한다 (스펙 §3).
- **레이아웃을 바꾸지 않는다** (D-2). 이 Phase 의 합격 기준은 "색만 바뀌고 레이아웃이 움직이지 않는다" 이다 (§6 Phase 1).
- **넓은 면적의 채움에는 브랜드 빨강을 쓰지 않는다.** 선택 행 배경·연한 영역은 중립 또는 아주 낮은 채도의 틴트를 쓴다 (§5).
- **`app.min.css` 를 수정하지 않는다.** 벤더 테마는 오버라이드로만 다룬다 (§7).
- **WeZonGrid 내부를 수정하지 않는다.** `--wzg-*` 커스터마이즈 지점으로만 다룬다 (§7).
- **`app.css`(21,083줄)는 로드되지 않는다.** 거기를 고쳐도 반영되지 않는다 (§4).
- **다크 모드·반응형은 범위 밖** (§7).
- **모든 Git Commit 메시지는 한국어로 작성한다.** Conventional Commits 의 type 은 영문 유지.
- **테스트는 `--settings=configurations.test_settings` 로 돌린다.** 빼면 운영 PostgreSQL 에 테스트 DB 가 생긴다.
- 개발 서버는 `0.0.0.0:8123` 에 떠 있어야 한다. 검증 하네스가 `http://127.0.0.1:8123` 로 붙는다.
- pip 설치가 필요하면 `PIP_CONFIG_FILE=/dev/null` 를 붙인다. 전역 `~/.config/pip/pip.conf` 가 깨져 있다. **전역 설정은 고치지 않는다.**

---

## File Structure

| 파일 | 상태 | 책임 |
|---|---|---|
| `app/static/assets/css/tokens.css` | **신규** | 브랜드 램프 선언 + 세 네임스페이스 매핑. 이 Phase 의 단일 원천 |
| `app/templates/app/index.html` | 수정 | 셸. `tokens.css` 를 head 맨 뒤에 싣는다 |
| `app/templates/app/layout_page.html` | 수정 | MES 화면 셸. `wezongrid.css` **뒤에** 싣는다 |
| `app/templates/data/_base.html` | 수정 | 데이터 화면 셸. `layout.css` 뒤에 싣는다 |
| `app/templates/app/login_mes.html` | 수정 | 로그인. `SF-login.css` 뒤에 싣는다 |
| `app/static/assets/css/SF-Custom.css` | 수정 | `#ea1b1b` 25곳을 `var(--brand-primary)` 로 |
| `app/static/assets/css/SF-login.css` | 수정 | `#ea1b1b` 4곳을 `var(--brand-primary)` 로 |
| `app/static/data/aidatahub.css` | 수정 | `:root` 색 토큰 12개 제거(tokens.css 로 이동) + 하드코딩 색 치환 |
| `app/static/data/governance.css` | 수정 | 하드코딩 색 치환 |
| `app/static/data/layout.css` | 수정 | 하드코딩 색 치환 |
| `scripts/verify_layout_stable.py` | **신규** | 25화면 요소 바운딩 박스 캡처·비교. 레이아웃 불변의 증거 |
| `scripts/verify_tokens.py` | **신규** | 하드코딩 색·폰트 잔재 스캐너. 회귀 방지 |
| `AGENTS.md` | 수정 | 검증 명령 목록에 새 스크립트 2개 추가 |

**수정하지 않는 파일:** `app/static/wezongrid/wezongrid.css`, `wezongrid.min.css`, `app.min.css`, `app.css`, `vendor.min.css`.

---

## 토큰 설계

### 브랜드 램프 (단일 원천)

```
--brand-primary        #da2129   로고 기준. 주요 동작·강조
--brand-primary-hover  #b51a21   위를 어둡게
--brand-primary-light  #e8565d   그라디언트 끝·어두운 배경 위 강조
--brand-primary-tint   #fdeced   좁은 면적 전용(칩·배지). 넓은 면적 금지

--brand-danger         #bd5a4d   오류. 브랜드 빨강과 구분되는 둔한 벽돌색
--brand-danger-line    #e4b5ae
--brand-danger-tint    #fdf2f0

--brand-warning        #ffba00   채움 (MES 기존값)
--brand-warning-ink    #d98b27   텍스트 (데이터 기존값 — 대비 유지)
--brand-warning-line   #f0cfa0
--brand-warning-tint   #fff4e2

--brand-ink            #242424   본문  (= MES --ct-body-color)
--brand-ink-2          #2e2e31   제목·강조
--brand-muted          #666666   보조 텍스트
--brand-line           #d8d8d8   경계  (= MES --ct-border-color)
--brand-line-strong    #bcc1cc   강한 경계

--brand-surface-1      #ffffff   카드
--brand-surface-2      #f7f8f9   아주 연한 면
--brand-surface-3      #edeff1   연한 면 (= MES --ct-body-bg)
--brand-surface-4      #e2e5e8   칩 바탕

--row-select-bg        #edeff1   행 선택·호버. §5 에 따라 중립
```

### `--brand-danger` 를 브랜드 빨강과 분리하는 이유

데이터 계열의 빨강 11종은 **전부 오류 상태**다 — `.form-error`(`#b42318`) · `.toast.is-error`(`#d88980`) · `.queue-item.is-invalid`(`#e8b8b0`) · `.lease-expired-banner` · `.task-status.rework`. 청록을 브랜드 빨강으로 옮기면 브랜드와 오류가 같은 색이 된다. §5 는 버튼을 **형태**로 나누라고 했지만 토스트·배너·폼 오류에는 기댈 형태가 없다. 그래서 오류는 기존 데이터 계열 값(`#bd5a4d`, L52 S46)을 유지한다. 브랜드(`#da2129`, L49 S74)와는 채도로 구분된다.

### `--teal-soft` 를 둘로 쪼개는 이유

`--teal-soft`(18곳)는 서로 다른 두 일을 하고 있다.

| 쓰임 | 곳 | 면적 | 간 곳 |
|---|---|---|---|
| 행 선택·호버 배경 | `.image-item.selected` · `.label-class.selected` · `.queue-item.selected` · `.recent-data-item:hover` · `.user-row:hover` · `.crud-row:hover` · `.platform-member-list > div:hover` | **넓다** | `--row-select-bg` (중립) |
| 칩·배지·아이콘 바탕 | `.tool-button` · `.readiness.small` · `.user-row-meta em` · `.task-status.submitted` · `.queue-item-icon` · `.upload-symbol` · `.upload-tip > div > i` · `.home-project-thumb-empty` · `.outline-button:hover` · `.drop-zone.is-dragging` · `.text-button:hover` | 좁다 | `--teal-soft` → `--brand-primary-tint` |

§5 의 "치환이 아니라 재설계가 필요한 지점"이 정확히 여기다. 넓은 쪽을 그대로 빨강 틴트로 두면 선택된 행 전체가 분홍 경고처럼 읽힌다.

### 치환표 — 데이터 계열 하드코딩 74종

`--brand-surface-1` ← `#ffffff`(35)

`--brand-surface-2` ← `#f8fafb`(5) `#fbfefe`(2) `#f7fbfa`(2) `#f5f8fa` `#f5fbfc` `#fbfdfd` `#f7fafb` `#fafcfc`

`--brand-surface-3` ← `#eef3f4`(4) `#edf4f5`(4) `#edf2f3`(2) `#e9f2f2`(2) `#eef2f3`(2) `#f4f7f8` `#e3f5f3` `#effaf8` `#f4f6f7` `#f3f6f7` `#e8f3f1` `#eef1f2` `#e9f0f1` `#eaf0f2` `#e7edef`

`--brand-surface-4` ← `#dde5e7`(3) `#dff4f1`(2) `#dce4e8` `#d7ecf2` `#dcebef` `#d7e2e5` `#d9edeb`

`--brand-line` ← `#a9d4d2`(5) `#b9ddda`(3) `#b9cbd4`(2) `#9ccbc8` `#c3cdd1` `#bdd4df` `#a7d4d1` `#b1c5ca` `#bccbd0` `#98cfcc`

`--brand-line-strong` ← `#8fcfca`

`--brand-muted` ← `#9aa8ae`(3) `#99a6ad`(2) `#8b989e`(2) `#9aa7ae` `#4b5563` `#405160` `#6e7b87` `#3f716d`

`--brand-primary` ← `#16a5a3`(5) `#087f78`(2) `#0e8f8d` `#176b66`

`--brand-primary-light` ← `#65d6cd`(4)

`--brand-ink` ← `#172331` `#102b49`(2)

`--brand-ink-2` ← `#17395f`(2)

`--brand-danger` ← `#c35c44`(2) `#bd5a4d` `#b42318`

`--brand-danger-line` ← `#e8b8b0` `#e4b5ae` `#d88980`

`--brand-danger-tint` ← `#fff8f6`(2) `#fff1ee`(2) `#fff1f0` `#fff5f3` `#ffece8`

`--brand-warning-ink` ← `#d98b27` `#d99920`

`--brand-warning-line` ← `#f0cfa0`

`--brand-warning-tint` ← `#fff0d8`(3) `#fff8ee`

`#3f716d`(`.stage-step.done` 글자색)는 "완료" 상태다. 브랜드 빨강으로 가면 완료가 경고처럼 읽히므로 `--brand-muted` 로 보낸다.

---

### Task 1: 레이아웃 불변 검증 하네스

이 Phase 전체의 안전망이다. **반드시 먼저 만들고, 실제로 실패하는 것을 눈으로 본 뒤** CSS 를 건드린다.

**Files:**
- Create: `scripts/verify_layout_stable.py`

**Interfaces:**
- Produces: CLI 두 가지. `python scripts/verify_layout_stable.py capture <출력폴더>` 는 25화면의 요소 바운딩 박스를 `<출력폴더>/<gui_code>.json` 으로 저장한다. `python scripts/verify_layout_stable.py compare <폴더A> <폴더B>` 는 두 폴더를 비교하고 0.5px 를 넘는 이동이 하나라도 있으면 종료코드 1 을 돌려준다.
- Consumes: `scripts/capture_ui.py` 의 `SCREENS` 목록과 로그인 절차를 그대로 쓴다(화면 25개, 뷰포트 1920×911, `.admin_pw`).

- [ ] **Step 1: 스크립트를 작성한다**

```python
#!/usr/bin/env python
"""화면 요소의 바운딩 박스를 떠서 두 시점을 비교한다.

디자인 작업이 "색만 바꿨다"는 것을 눈이 아니라 수치로 증명하기 위한 것이다.
스크린샷 비교는 색이 바뀌면 전부 달라져서 레이아웃 이동을 가려낼 수 없다.

    python scripts/verify_layout_stable.py capture /tmp/geo-before
    (CSS 수정)
    python scripts/verify_layout_stable.py capture /tmp/geo-after
    python scripts/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-after

운영 의존성이 아니다. playwright 가 필요하다(capture_ui.py 와 같다).
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8123'
VIEWPORT = {'width': 1920, 'height': 911}
TOLERANCE = 0.5     # 서브픽셀 반올림만 허용한다

SCREENS = [
    'wm_user', 'wm_user_group', 'wm_user_group_menu', 'wm_multi_language',
    'wm_menu_language', 'wm_prop_master', 'wm_login_log', 'wm_menu_log',
    'wm_system_log',
    'wm_data_item', 'wm_data_queue', 'wm_data_item_detail', 'wm_data_image',
    'wm_data_labeling', 'wm_data_review', 'wm_data_snapshot',
    'wm_vis_inspection', 'wm_vis_client', 'wm_vis_model',
    'wm_vis_model_mapping', 'wm_vis_overlay',
    'wm_code', 'wm_company', 'wm_depart', 'wm_unit',
]

# 요소마다 "구조상의 주소"를 만든다. class 는 상태에 따라 붙었다 떨어지므로
# 쓰지 않고 태그 + 형제 순번만으로 경로를 만든다.
COLLECT_JS = """
() => {
  const path = (el) => {
    const parts = [];
    while (el && el.nodeType === 1 && el !== document.documentElement) {
      const parent = el.parentNode;
      let idx = 1;
      if (parent) {
        for (const sib of parent.children) {
          if (sib === el) break;
          if (sib.tagName === el.tagName) idx++;
        }
      }
      parts.unshift(el.tagName.toLowerCase() + '[' + idx + ']');
      el = parent;
    }
    return parts.join('>');
  };
  const out = {};
  for (const el of document.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;   // 숨은 요소는 건너뛴다
    out[path(el)] = [
      Math.round(r.x * 100) / 100, Math.round(r.y * 100) / 100,
      Math.round(r.width * 100) / 100, Math.round(r.height * 100) / 100,
    ];
  }
  return out;
}
"""


def capture(out_dir):
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    password_file = ROOT / '.admin_pw'
    if not password_file.exists():
        print('.admin_pw 가 없다. seed_initial 을 먼저 돌려라.')
        return 2
    password = password_file.read_text(encoding='utf-8').strip()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport=VIEWPORT, locale='ko-KR')
        page = ctx.new_page()
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
            page.wait_for_timeout(2800)
            geo = page.evaluate(COLLECT_JS)
            (out / (code + '.json')).write_text(
                json.dumps(geo, sort_keys=True, indent=0), encoding='utf-8')
            print('CAP  {:28} 요소 {}개'.format(code, len(geo)))
        browser.close()
    return 0


def compare(dir_a, dir_b):
    a_root, b_root = pathlib.Path(dir_a), pathlib.Path(dir_b)
    moved = 0
    checked = 0
    for code in SCREENS:
        fa, fb = a_root / (code + '.json'), b_root / (code + '.json')
        if not fa.exists() or not fb.exists():
            print('SKIP {:28} 한쪽 캡처가 없다'.format(code))
            continue
        a = json.loads(fa.read_text(encoding='utf-8'))
        b = json.loads(fb.read_text(encoding='utf-8'))
        diffs = []
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                diffs.append((key, '요소 생성/소멸'))
                continue
            checked += 1
            for i, axis in enumerate(('x', 'y', 'w', 'h')):
                if abs(a[key][i] - b[key][i]) > TOLERANCE:
                    diffs.append((key, '{} {} → {}'.format(axis, a[key][i], b[key][i])))
        if diffs:
            moved += len(diffs)
            print('MOVE {:28} {}건'.format(code, len(diffs)))
            for key, why in diffs[:5]:
                print('       {}  {}'.format(key[-70:], why))
        else:
            print('OK   {:28} 이동 없음'.format(code))

    print('\n요소 {}개 대조 / 이동 {}건'.format(checked, moved))
    print('PASS' if moved == 0 else 'FAIL')
    return 0 if moved == 0 else 1


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == 'capture':
        return capture(sys.argv[2])
    if len(sys.argv) >= 4 and sys.argv[1] == 'compare':
        return compare(sys.argv[2], sys.argv[3])
    print('사용법:')
    print('  python scripts/verify_layout_stable.py capture  <출력폴더>')
    print('  python scripts/verify_layout_stable.py compare  <폴더A> <폴더B>')
    return 2


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 기준선을 뜬다**

서버가 떠 있어야 한다. 떠 있지 않으면 먼저 띄운다.

```bash
cd /home/yhan/projects/manufacturing_ai_platform
ss -tln | grep -q ':8123' || (nohup .venv/bin/python manage.py runserver 0.0.0.0:8123 --noreload > /tmp/server.log 2>&1 &)
sleep 4
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-before
```

Expected: 25줄 전부 `CAP ... 요소 N개`, N 은 화면마다 수백 단위.

- [ ] **Step 3: 하네스가 실제로 이동을 잡는지 확인한다 (RED)**

고장을 일부러 만들어 넣는다. 이 단계를 건너뛰면 "PASS" 가 무엇을 증명하는지 알 수 없다.

```bash
cp app/static/data/aidatahub.css /tmp/aidatahub.css.bak
printf '\n.crud-row { padding-left: 3px; }\n' >> app/static/data/aidatahub.css
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-probe
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-probe
```

Expected: 종료코드 1, `FAIL`, 데이터 화면에서 `MOVE` 가 나온다.

- [ ] **Step 4: 고장을 되돌리고 통과를 확인한다 (GREEN)**

```bash
cp /tmp/aidatahub.css.bak app/static/data/aidatahub.css
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-probe2
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-probe2
```

Expected: 종료코드 0, `PASS`, `요소 N개 대조 / 이동 0건`.

통과하지 않으면 **멈춘다.** 화면에 시간 의존 요소(애니메이션·시계)가 있어 매번 달라지는 것이므로, 그 요소를 `COLLECT_JS` 에서 제외하는 규칙을 더하고 다시 Step 2 부터 한다.

- [ ] **Step 5: 커밋**

```bash
git add scripts/verify_layout_stable.py
git commit -m "test: 화면 요소 바운딩 박스 비교로 레이아웃 불변을 검증하는 하네스 추가"
```

---

### Task 2: 하드코딩 색·폰트 스캐너

**Files:**
- Create: `scripts/verify_tokens.py`

**Interfaces:**
- Produces: `python scripts/verify_tokens.py`. 위반이 있으면 종료코드 1.
- Consumes: 없음(정적 스캔).

- [ ] **Step 1: 스캐너를 작성한다 (RED 가 될 테스트)**

```python
#!/usr/bin/env python
"""디자인 토큰을 거치지 않은 색·서체가 남아 있는지 찾는다.

Phase 1 에서 세 네임스페이스를 tokens.css 한 곳에 모았다. 그 뒤로 CSS 에
색 리터럴을 직접 쓰면 다시 흩어지므로 여기서 막는다.

    python scripts/verify_tokens.py

허용 예외는 ALLOW 에 이유와 함께 적는다. 이유 없이 늘리지 않는다.
"""
import colorsys
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 단일 원천. 여기서만 색 리터럴을 선언한다.
TOKENS = ROOT / 'app' / 'static' / 'assets' / 'css' / 'tokens.css'

# 유채색 리터럴을 한 점도 허용하지 않는 파일. Phase 1 이 전수 치환한 곳이다.
STRICT = [
    ROOT / 'app' / 'static' / 'data' / 'aidatahub.css',
    ROOT / 'app' / 'static' / 'data' / 'governance.css',
    ROOT / 'app' / 'static' / 'data' / 'layout.css',
]

# MES 계열은 Phase 1 의 범위가 "브랜드 빨강과 데이터 청록"뿐이다. 나머지
# 유채색(링크 파랑 등)은 Phase 3 에서 버튼 체계와 함께 본다. 그래서 전수
# 금지가 아니라 지목한 리터럴만 막는다.
BANNED = {
    '#ea1b1b': '브랜드 빨강은 var(--brand-primary)',
    '#16a5a3': '데이터 청록은 var(--brand-primary)',
    '#003597': '그리드 남색은 var(--brand-primary)',
}
BANNED_IN = [
    ROOT / 'app' / 'static' / 'assets' / 'css' / 'SF-Custom.css',
    ROOT / 'app' / 'static' / 'assets' / 'css' / 'SF-login.css',
]

HEX = re.compile(r'#[0-9a-fA-F]{3,8}\b')

# 흑·백은 토큰을 거칠 필요가 없다. 그 외의 유채색만 본다.
ALLOW = {'#ffffff', '#000000'}


def _norm(h):
    x = h.lstrip('#').lower()
    if len(x) == 3:
        x = ''.join(c * 2 for c in x)
    return '#' + x[:6]


def _chromatic(h):
    """회색 계열이면 False. 유채색만 토큰을 요구한다."""
    x = _norm(h).lstrip('#')
    r, g, b = (int(x[i:i + 2], 16) / 255 for i in (0, 2, 4))
    _, _, s = colorsys.rgb_to_hls(r, g, b)
    return s >= 0.08


def main():
    violations = []

    for path in STRICT:
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for raw in HEX.findall(line):
                if _norm(raw) in ALLOW or not _chromatic(raw):
                    continue
                violations.append(('색', rel, lineno, raw, line.strip()[:66]))
            # 서체는 tokens.css 의 --font-sans 한 곳으로 모은다.
            if ('font-family' in line
                    and 'var(--font-sans)' not in line
                    and 'monospace' not in line):
                violations.append(('서체', rel, lineno, 'font-family 직접 선언', ''))

    for path in BANNED_IN:
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            for raw in HEX.findall(line):
                why = BANNED.get(_norm(raw))
                if why:
                    violations.append(('금지', rel, lineno, raw, why))

    if not TOKENS.exists():
        violations.append(('없음', TOKENS.relative_to(ROOT), 0, 'tokens.css 가 없다', ''))

    for kind, rel, lineno, what, ctx in violations:
        print('{:4} {}:{}  {}  {}'.format(kind, rel, lineno, what, ctx))

    print('\n토큰을 거치지 않은 선언 {}건'.format(len(violations)))
    print('PASS' if not violations else 'FAIL')
    return 0 if not violations else 1


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 지금 돌려서 실패하는 것을 본다 (RED)**

```bash
cd /home/yhan/projects/manufacturing_ai_platform
.venv/bin/python scripts/verify_tokens.py | tail -20
```

Expected: `토큰을 거치지 않은 선언 148건` `FAIL`. 내역은 이렇게 나뉜다 — 실제로 미리 돌려 확인한 값이다.

| 종류 | 건수 | 없애는 Task |
|---|---|---|
| `색` 데이터 3파일의 유채색 리터럴 | 117 | Task 6 |
| `금지` `SF-Custom.css` 의 `#ea1b1b` 25 + `SF-login.css` 4 | 29 | Task 4 |
| `서체` `aidatahub.css:15` 의 `Inter` 선행 `font-family` | 1 | Task 5 |
| `없음` `tokens.css` 가 아직 없다 | 1 | Task 3 |

148 이 아닌 다른 수가 나오면 그동안 CSS 가 바뀐 것이다. 내역을 먼저 확인한다.

- [ ] **Step 3: 커밋**

```bash
git add scripts/verify_tokens.py
git commit -m "test: 토큰을 거치지 않은 색·서체 선언을 찾는 스캐너 추가"
```

---

### Task 3: tokens.css 신규 + MES 네임스페이스 매핑 + 4개 레이아웃에 로드

**Files:**
- Create: `app/static/assets/css/tokens.css`
- Modify: `app/templates/app/index.html`, `app/templates/app/layout_page.html`, `app/templates/data/_base.html`, `app/templates/app/login_mes.html`

**Interfaces:**
- Produces: `tokens.css` 의 `:root` 가 **브랜드 램프 전체**를 선언한다. 이름은 위 "토큰 설계" 표 그대로이고 Task 5·6·7 이 이 이름을 쓴다. 이 Task 에서는 `--ct-*`(MES) 매핑까지만 한다.
- Consumes: Task 1 의 `/tmp/geo-before`.

- [ ] **Step 1: tokens.css 를 만든다**

```css
/* 디자인 토큰 — 단일 원천.
 *
 * 이 파일의 일은 색을 새로 정하는 것이 아니라, 서로 모르던 세 네임스페이스를
 * 하나의 브랜드 램프에서 파생시키는 것이다.
 *
 *   --ct-*     SF-Custom.css      MES 계열 + 셸 (Bootstrap 테마 변수)
 *   --ink 등   data/aidatahub.css 데이터 관리 계열
 *   --wzg-*    wezongrid.css      모든 그리드
 *
 * 반드시 **모든 스타일시트 뒤에** 싣는다. 앞에 실으면 매핑이 덮인다.
 * 근거: docs/09_UI_DESIGN_SYSTEM.md §4
 */

:root {
    /* --- 브랜드 ------------------------------------------------------ */
    /* 로고(docs/yest.png)의 주색이다. CSS 가 쓰던 #ea1b1b 를 대체한다(§3). */
    --brand-primary:        #da2129;
    --brand-primary-hover:  #b51a21;
    --brand-primary-light:  #e8565d;
    /* 좁은 면적(칩·배지) 전용. 넓은 면적에 쓰면 분홍 경고로 읽힌다(§5). */
    --brand-primary-tint:   #fdeced;

    /* --- 오류 --------------------------------------------------------
     * 브랜드가 빨강이므로 오류를 같은 빨강으로 두면 구분되지 않는다.
     * 데이터 계열이 쓰던 둔한 벽돌색을 그대로 유지해 채도로 가른다. */
    --brand-danger:         #bd5a4d;
    --brand-danger-line:    #e4b5ae;
    --brand-danger-tint:    #fdf2f0;

    /* --- 경고 --------------------------------------------------------
     * 채움은 MES 값(#ffba00), 글자는 데이터 값(#d98b27). #ffba00 은
     * 흰 바탕 글자로 쓰면 대비가 모자란다. */
    --brand-warning:        #ffba00;
    --brand-warning-ink:    #d98b27;
    --brand-warning-line:   #f0cfa0;
    --brand-warning-tint:   #fff4e2;

    /* --- 중립 램프 ----------------------------------------------------
     * 넓은 면적은 전부 여기서 가져간다(§5). */
    --brand-ink:            #242424;
    --brand-ink-2:          #2e2e31;
    --brand-muted:          #666666;
    --brand-line:           #d8d8d8;
    --brand-line-strong:    #bcc1cc;
    --brand-surface-1:      #ffffff;
    --brand-surface-2:      #f7f8f9;
    --brand-surface-3:      #edeff1;
    --brand-surface-4:      #e2e5e8;

    /* 행 선택·호버. 브랜드 빨강을 쓰지 않는 자리다(§5). */
    --row-select-bg:        var(--brand-surface-3);

    /* --- 서체 --------------------------------------------------------
     * Inter 는 어디에도 @font-face 가 없어 OS 에 설치된 PC 에서만 적용됐다.
     * 같은 제품이 PC 마다 다른 서체로 보이던 원인이다. */
    --font-sans: 'Pretendard', 'Noto Sans KR', system-ui, -apple-system,
                 'Segoe UI', 'Open Sans', 'Helvetica Neue', sans-serif;
}

/* --- MES / 셸 (--ct-*) ------------------------------------------------
 * SF-Custom.css 의 :root[data-bs-theme=light] 와 같은 특정도여야 덮인다. */
:root[data-bs-theme=light] {
    --ct-primary:            var(--brand-primary);
    --ct-emphasis-color:     var(--brand-primary);
    --ct-link-hover-color:   var(--brand-primary);
    --ct-body-color:         var(--brand-ink);
    --ct-dark:               var(--brand-ink);
    --ct-border-color:       var(--brand-line);
    --ct-light:              var(--brand-line);
    --ct-body-bg:            var(--brand-surface-3);
    --ct-secondary-color:    var(--brand-muted);
    --ct-font-sans-serif:    var(--font-sans);
    --ct-font-monospace:     var(--font-sans);
}
```

- [ ] **Step 2: 네 레이아웃에 싣는다 — 반드시 맨 뒤에**

`layout_page.html` 만 순서가 까다롭다. `wezongrid.css` 가 `SF-Custom.css` 보다 **뒤에** 있으므로(64행) `tokens.css` 는 그보다 더 뒤여야 `--wzg-*` 를 덮을 수 있다.

```bash
cd /home/yhan/projects/manufacturing_ai_platform

# ① 셸 — SF-Custom.css 바로 뒤
sed -i 's|^\(\s*\)\(<link href="/static/assets/css/SF-Custom.css?v=26082105" rel="stylesheet" type="text/css" />\)$|\1\2\n\1<link href="/static/assets/css/tokens.css?v=20261002" rel="stylesheet" type="text/css" />|' \
  app/templates/app/index.html

# ② MES 화면 — wezongrid.css 뒤
sed -i 's|^\(\s*\)\(<link href="/static/wezongrid/wezongrid.css?v=20260408" rel="stylesheet" type="text/css" />\)$|\1\2\n\1<link href="/static/assets/css/tokens.css?v=20261002" rel="stylesheet" type="text/css" />|' \
  app/templates/app/layout_page.html

# ③ 데이터 화면 — layout.css 뒤
sed -i "s|^\(\s*\)\(<link rel=\"stylesheet\" href=\"{% static 'data/layout.css' %}\">\)$|\1\2\n\1<link rel=\"stylesheet\" href=\"{% static 'assets/css/tokens.css' %}\">|" \
  app/templates/data/_base.html

# ④ 로그인 — SF-login.css 뒤
sed -i 's|^\(\s*\)\(<link href="/static/assets/css/SF-login.css" rel="stylesheet" type="text/css"  />\)$|\1\2\n\1<link href="/static/assets/css/tokens.css?v=20261002" rel="stylesheet" type="text/css" />|' \
  app/templates/app/login_mes.html

grep -n 'tokens.css' app/templates/app/index.html app/templates/app/layout_page.html app/templates/data/_base.html app/templates/app/login_mes.html
```

Expected: 네 파일에서 각각 1줄씩, 총 4줄이 나온다. 하나라도 비면 그 파일의 원문을 직접 읽어 수동으로 넣는다 — sed 가 공백까지 맞아야 치환된다.

- [ ] **Step 3: 브라우저에서 토큰이 실제로 해석되는지 확인한다**

CSS 는 오타가 나도 조용히 무시되므로 파일 존재만으로는 증거가 되지 않는다. 계산값을 읽는다.

```bash
cat > /tmp/check_tokens.py <<'PY'
import pathlib
from playwright.sync_api import sync_playwright
BASE = 'http://127.0.0.1:8123'
pwd = pathlib.Path('.admin_pw').read_text(encoding='utf-8').strip()
JS = """() => {
  const s = getComputedStyle(document.documentElement);
  return {
    brand:   s.getPropertyValue('--brand-primary').trim(),
    ct:      s.getPropertyValue('--ct-primary').trim(),
    font:    s.getPropertyValue('--font-sans').trim().slice(0, 14),
  };
}"""
with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_context(viewport={'width':1920,'height':911}).new_page()
    p.goto(BASE + '/login/', wait_until='domcontentloaded')
    p.fill('#loginId','admin'); p.fill('#loginPwd',pwd); p.click('#login')
    p.wait_for_url(BASE + '/', timeout=15000); p.wait_for_timeout(1500)
    print('셸        ', p.evaluate(JS))
    p.goto(BASE + '/gui/wm_user/', wait_until='domcontentloaded'); p.wait_for_timeout(2000)
    print('MES 화면  ', p.evaluate(JS))
    p.goto(BASE + '/gui/wm_data_item/?project=3', wait_until='domcontentloaded'); p.wait_for_timeout(2000)
    print('데이터 화면', p.evaluate(JS))
    b.close()
PY
.venv/bin/python /tmp/check_tokens.py
```

Expected: 세 줄 모두 `brand: #da2129`, `ct: #da2129`, `font: 'Pretendard'`.
`ct` 가 `#ea1b1b` 로 나오면 **로드 순서가 틀린 것**이다. 해당 템플릿에서 `tokens.css` 가 `SF-Custom.css` 뒤에 있는지 확인한다.

- [ ] **Step 4: 레이아웃이 움직이지 않았는지 확인한다**

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-t3
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-t3
```

Expected: `PASS`, 이동 0건. 색만 바뀌었으므로 박스는 1px 도 움직이면 안 된다.

- [ ] **Step 5: 화면이 깨지지 않았는지 확인한다**

```bash
.venv/bin/python scripts/capture_ui.py /tmp/ui-t3
node scripts/verify_screen_js.js
```

Expected: `화면 25개 / 오류 0건` `PASS`, verify_screen_js 도 `PASS`.

- [ ] **Step 6: 커밋**

```bash
git add app/static/assets/css/tokens.css app/templates/app/index.html \
        app/templates/app/layout_page.html app/templates/data/_base.html \
        app/templates/app/login_mes.html
git commit -m "feat: 디자인 토큰 단일 원천 tokens.css 추가하고 MES 네임스페이스를 연결"
```

---

### Task 4: SF-Custom.css · SF-login.css 의 `#ea1b1b` 치환

**Files:**
- Modify: `app/static/assets/css/SF-Custom.css` (25곳), `app/static/assets/css/SF-login.css` (4곳)

**Interfaces:**
- Consumes: Task 3 의 `--brand-primary`.
- Produces: 없음(리터럴 제거만).

- [ ] **Step 1: 치환 전 개수를 센다**

```bash
cd /home/yhan/projects/manufacturing_ai_platform
grep -ic '#ea1b1b' app/static/assets/css/SF-Custom.css app/static/assets/css/SF-login.css
```

Expected: `SF-Custom.css:25`, `SF-login.css:4`.

- [ ] **Step 2: 치환한다**

`:root[data-bs-theme=light]` 블록 안의 선언 2곳(`--ct-primary`, `--ct-emphasis-color`, `--ct-link-hover-color`)은 Task 3 의 tokens.css 가 이미 덮으므로 함께 바꿔도 결과가 같다. 리터럴을 남기지 않는 쪽이 스캐너와 맞는다.

```bash
sed -i 's/#ea1b1b/var(--brand-primary)/gI' app/static/assets/css/SF-Custom.css
sed -i 's/#ea1b1b/var(--brand-primary)/gI' app/static/assets/css/SF-login.css
grep -ic '#ea1b1b' app/static/assets/css/SF-Custom.css app/static/assets/css/SF-login.css
grep -c 'var(--brand-primary)' app/static/assets/css/SF-Custom.css app/static/assets/css/SF-login.css
```

Expected: `#ea1b1b` 는 두 파일 모두 `0`, `var(--brand-primary)` 는 25 와 4.

- [ ] **Step 3: 레이아웃 불변 확인**

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-t4
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-t4
```

Expected: `PASS`, 이동 0건.

- [ ] **Step 4: 로그인 화면을 눈으로 확인한다**

로그인 화면은 25화면 캡처에 들어 있지 않다.

```bash
cat > /tmp/shot_login.py <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_context(viewport={'width':1920,'height':911}).new_page()
    p.goto('http://127.0.0.1:8123/login/', wait_until='domcontentloaded'); p.wait_for_timeout(1500)
    p.screenshot(path='/tmp/login-after.png'); b.close()
PY
.venv/bin/python /tmp/shot_login.py
```

`/tmp/login-after.png` 를 열어 빨강이 `#da2129` 로 바뀌었고 글자가 사라지거나 깨진 곳이 없는지 본다.

- [ ] **Step 5: 커밋**

```bash
git add app/static/assets/css/SF-Custom.css app/static/assets/css/SF-login.css
git commit -m "refactor: MES 계열의 빨강 리터럴 29곳을 브랜드 토큰 참조로 교체"
```

---

### Task 5: 데이터 네임스페이스 매핑 + `--teal-soft` 분리 + Inter 제거

**Files:**
- Modify: `app/static/assets/css/tokens.css` (데이터 매핑 블록 추가)
- Modify: `app/static/data/aidatahub.css:1-18` (`:root` 의 색 토큰 12개 제거, `font-family` 제거)
- Modify: `app/static/data/aidatahub.css`, `governance.css`, `layout.css` (행 선택 7곳을 `--row-select-bg` 로)

**Interfaces:**
- Consumes: Task 3 의 브랜드 램프와 `--row-select-bg`.
- Produces: 데이터 계열 토큰(`--ink` `--muted` `--line` `--paper` `--card` `--navy` `--navy-deep` `--teal` `--teal-soft` `--orange` `--red` `--shadow`)이 tokens.css 에서 선언된다. Task 6 이 이 이름을 쓴다.

- [ ] **Step 1: tokens.css 에 데이터 매핑을 더한다**

파일 끝에 붙인다.

```css
/* --- 데이터 관리 (--ink 외) -------------------------------------------
 * 원래 aidatahub.css :root 에 있던 선언을 여기로 옮겼다. 그쪽에는
 * --crud-shell-height 와 color/background 만 남는다. */
:root {
    --ink:        var(--brand-ink);
    --muted:      var(--brand-muted);
    --line:       var(--brand-line);
    --paper:      var(--brand-surface-3);
    --card:       var(--brand-surface-1);
    --navy:       var(--brand-ink-2);
    --navy-deep:  #1b1b1d;
    --teal:       var(--brand-primary);
    /* 좁은 면적(칩·배지)만 남았다. 넓은 면적은 --row-select-bg 로 갈라졌다. */
    --teal-soft:  var(--brand-primary-tint);
    --orange:     var(--brand-warning-ink);
    --red:        var(--brand-danger);
    --shadow:     0 18px 48px rgba(36, 36, 36, .08);

    font-family:  var(--font-sans);
}
```

- [ ] **Step 2: aidatahub.css 의 `:root` 에서 옮긴 선언을 지운다**

두 곳에 선언이 남으면 어느 쪽이 사는지 로드 순서에 의존하게 된다. 지운다.

`app/static/data/aidatahub.css` 의 1~18행을 다음으로 바꾼다.

```css
:root {
  /* 색·서체 토큰은 assets/css/tokens.css 로 옮겼다(단일 원천).
     여기에는 이 화면 계열만 쓰는 치수와 기본값만 남긴다. */
  --crud-shell-height: calc(100vh - 94px);
  color: var(--ink);
  background: var(--paper);
}
```

지워지는 것: `--ink` `--muted` `--line` `--paper` `--card` `--navy` `--navy-deep` `--teal` `--teal-soft` `--orange` `--red` `--shadow` 12줄과 `font-family` 1줄.

- [ ] **Step 3: 행 선택·호버 7곳을 중립으로 돌린다**

§5 의 "넓은 면적에 브랜드 빨강을 쓰지 않는다" 를 지키는 자리다. 테두리색도 같이 중립으로 간다 — 테두리만 청록으로 남으면 배경과 어긋난다.

```bash
cd /home/yhan/projects/manufacturing_ai_platform

# 배경: 넓은 면적 7곳
sed -i \
 -e 's|\(\.image-item:hover, \.image-item\.selected {[^}]*\)var(--teal-soft)|\1var(--row-select-bg)|' \
 -e 's|\(\.label-class:hover, \.label-class\.selected {[^}]*\)var(--teal-soft)|\1var(--row-select-bg)|' \
 app/static/data/governance.css

sed -i \
 -e 's|\(\.queue-item\.selected {[^}]*\)var(--teal-soft)|\1var(--row-select-bg)|' \
 -e 's|\(\.recent-data-item:hover {[^}]*\)var(--teal-soft)|\1var(--row-select-bg)|' \
 -e 's|\(\.user-row:hover, \.user-row\.selected {[^}]*\)var(--teal-soft)|\1var(--row-select-bg)|' \
 -e 's|\(\.crud-row:hover, \.crud-row\.selected {[^}]*\)var(--teal-soft)|\1var(--row-select-bg)|' \
 -e 's|\(\.platform-member-list > div:hover, \.platform-record-row:hover {[^}]*\)var(--teal-soft)|\1var(--row-select-bg)|' \
 app/static/data/aidatahub.css

grep -c 'var(--row-select-bg)' app/static/data/aidatahub.css app/static/data/governance.css
```

Expected: `aidatahub.css:5`, `governance.css:2`. 합 7. 다르면 해당 셀렉터 줄을 직접 읽어 수동으로 고친다.

- [ ] **Step 4: 남은 `--teal-soft` 가 좁은 면적만인지 확인한다**

```bash
grep -n 'var(--teal-soft)' app/static/data/*.css
```

Expected: 11줄. 전부 `.tool-button` `.readiness.small` `.user-row-meta em` `.task-status.submitted` `.queue-item-icon` `.upload-symbol` `.upload-tip > div > i` `.home-project-thumb-empty` `.outline-button:hover` `.drop-zone.is-dragging` `.text-button:hover` 중 하나다. 행·카드 단위 셀렉터가 남아 있으면 Step 3 으로 돌아간다.

- [ ] **Step 5: 레이아웃 불변 + 화면 확인**

`font-family` 가 바뀌었다. 이 PC 에는 Inter 가 설치돼 있지 않으므로(`fc-list | grep -ci inter` → 0) 여기서는 이동이 0 이어야 한다. Inter 가 깔린 PC 에서는 글자 폭이 달라진다 — 그것이 이 변경의 목적이다.

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-t5
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-t5
.venv/bin/python scripts/capture_ui.py /tmp/ui-t5
```

Expected: 둘 다 `PASS`.

- [ ] **Step 6: 데이터 화면 7장을 눈으로 본다**

이 Task 가 §5 의 재설계다. 수치로는 증명되지 않으므로 반드시 본다.

`/tmp/ui-t5/02-data/` 의 7장을 연다. 확인할 것:

1. 선택된 행·호버 행이 **분홍색이 아니다** (중립 회색이다)
2. 칩·배지(`제출됨` 같은 상태 표시)는 **연한 빨강 틴트 + 빨강 글자**다
3. 오류 표시(토스트·폼 오류)가 브랜드 빨강과 **구분된다**
4. 글자가 사라지거나 대비가 무너진 곳이 없다

하나라도 어긋나면 멈추고 보고한다.

- [ ] **Step 7: 커밋**

```bash
git add app/static/assets/css/tokens.css app/static/data/aidatahub.css \
        app/static/data/governance.css app/static/data/layout.css
git commit -m "refactor: 데이터 계열 토큰을 브랜드 램프에 연결하고 넓은 면적용 선택색을 분리

--teal-soft 하나가 행 선택 배경(넓은 면적)과 칩 바탕(좁은 면적)을 겸하고
있었다. 브랜드가 빨강으로 바뀌면 선택된 행 전체가 분홍 경고처럼 읽히므로
넓은 쪽을 --row-select-bg(중립)로 가른다. 근거: 09_UI_DESIGN_SYSTEM.md §5"
```

---

### Task 6: 데이터 계열 하드코딩 74종 치환

**Files:**
- Modify: `app/static/data/aidatahub.css`, `app/static/data/governance.css`, `app/static/data/layout.css`

**Interfaces:**
- Consumes: Task 3 의 브랜드 램프 이름 전부.
- Produces: 없음(리터럴 제거만). 끝나면 `scripts/verify_tokens.py` 가 PASS 한다.

- [ ] **Step 1: 치환 스크립트를 쓴다 (일회용 — 저장소에 넣지 않는다)**

74종을 손으로 고치면 빠뜨린다. 매핑을 명시한 일회용 스크립트로 한 번에 바꾸고, 결과는 `git diff` 로 검토한다.

```bash
cd /home/yhan/projects/manufacturing_ai_platform
cat > /tmp/phase1_map.py <<'PY'
"""데이터 계열 CSS 의 색 리터럴을 브랜드 토큰 참조로 바꾼다. 일회용."""
import pathlib, re

MAP = {
    # 면
    '#ffffff': 'var(--brand-surface-1)',
    '#f8fafb': 'var(--brand-surface-2)', '#fbfefe': 'var(--brand-surface-2)',
    '#f7fbfa': 'var(--brand-surface-2)', '#f5f8fa': 'var(--brand-surface-2)',
    '#f5fbfc': 'var(--brand-surface-2)', '#fbfdfd': 'var(--brand-surface-2)',
    '#f7fafb': 'var(--brand-surface-2)', '#fafcfc': 'var(--brand-surface-2)',
    '#eef3f4': 'var(--brand-surface-3)', '#edf4f5': 'var(--brand-surface-3)',
    '#edf2f3': 'var(--brand-surface-3)', '#e9f2f2': 'var(--brand-surface-3)',
    '#eef2f3': 'var(--brand-surface-3)', '#f4f7f8': 'var(--brand-surface-3)',
    '#e3f5f3': 'var(--brand-surface-3)', '#effaf8': 'var(--brand-surface-3)',
    '#f4f6f7': 'var(--brand-surface-3)', '#f3f6f7': 'var(--brand-surface-3)',
    '#e8f3f1': 'var(--brand-surface-3)', '#eef1f2': 'var(--brand-surface-3)',
    '#e9f0f1': 'var(--brand-surface-3)', '#eaf0f2': 'var(--brand-surface-3)',
    '#e7edef': 'var(--brand-surface-3)',
    '#dde5e7': 'var(--brand-surface-4)', '#dff4f1': 'var(--brand-surface-4)',
    '#dce4e8': 'var(--brand-surface-4)', '#d7ecf2': 'var(--brand-surface-4)',
    '#dcebef': 'var(--brand-surface-4)', '#d7e2e5': 'var(--brand-surface-4)',
    '#d9edeb': 'var(--brand-surface-4)',
    # 선
    '#a9d4d2': 'var(--brand-line)', '#b9ddda': 'var(--brand-line)',
    '#b9cbd4': 'var(--brand-line)', '#9ccbc8': 'var(--brand-line)',
    '#c3cdd1': 'var(--brand-line)', '#bdd4df': 'var(--brand-line)',
    '#a7d4d1': 'var(--brand-line)', '#b1c5ca': 'var(--brand-line)',
    '#bccbd0': 'var(--brand-line)',
    '#98cfcc': 'var(--brand-line-strong)', '#8fcfca': 'var(--brand-line-strong)',
    # 보조 글자
    '#9aa8ae': 'var(--brand-muted)', '#99a6ad': 'var(--brand-muted)',
    '#8b989e': 'var(--brand-muted)', '#9aa7ae': 'var(--brand-muted)',
    '#4b5563': 'var(--brand-muted)', '#405160': 'var(--brand-muted)',
    '#6e7b87': 'var(--brand-muted)',
    # .stage-step.done — "완료"다. 빨강으로 가면 경고로 읽힌다.
    '#3f716d': 'var(--brand-muted)',
    # 본문 글자
    '#172331': 'var(--brand-ink)', '#102b49': 'var(--brand-ink)',
    '#17395f': 'var(--brand-ink-2)',
    # 브랜드
    '#16a5a3': 'var(--brand-primary)', '#087f78': 'var(--brand-primary)',
    '#0e8f8d': 'var(--brand-primary-hover)', '#176b66': 'var(--brand-primary)',
    '#65d6cd': 'var(--brand-primary-light)',
    # 오류
    '#c35c44': 'var(--brand-danger)', '#bd5a4d': 'var(--brand-danger)',
    '#b42318': 'var(--brand-danger)',
    '#e8b8b0': 'var(--brand-danger-line)', '#e4b5ae': 'var(--brand-danger-line)',
    '#d88980': 'var(--brand-danger-line)',
    '#fff8f6': 'var(--brand-danger-tint)', '#fff1ee': 'var(--brand-danger-tint)',
    '#fff1f0': 'var(--brand-danger-tint)', '#fff5f3': 'var(--brand-danger-tint)',
    '#ffece8': 'var(--brand-danger-tint)',
    # 경고
    '#d98b27': 'var(--brand-warning-ink)', '#d99920': 'var(--brand-warning-ink)',
    '#f0cfa0': 'var(--brand-warning-line)',
    '#fff0d8': 'var(--brand-warning-tint)', '#fff8ee': 'var(--brand-warning-tint)',
    # 청록 rgba — 포커스 링·오버레이
    'rgba(22,165,163,.28)': 'rgba(218,33,41,.28)',
    'rgba(22,165,163,.18)': 'rgba(218,33,41,.18)',
    'rgba(22,165,163,.12)': 'rgba(218,33,41,.12)',
    'rgba(22,165,163,.08)': 'rgba(218,33,41,.08)',
    'rgba(22,165,163,.7)':  'rgba(218,33,41,.7)',
    'rgba(22, 165, 163, 0.15)': 'rgba(218, 33, 41, 0.15)',
    'rgba(101,214,205,.5)': 'rgba(232,86,93,.5)',
    'rgba(23,57,95,.14)':   'rgba(36,36,36,.14)',
    'rgba(23,57,95,.1)':    'rgba(36,36,36,.1)',
    'rgba(16,43,73,.45)':   'rgba(36,36,36,.45)',
    'rgba(16,43,73,.2)':    'rgba(36,36,36,.2)',
    'rgba(24, 46, 68, .08)': 'rgba(36, 36, 36, .08)',
}

# #fff 같은 3자리 축약도 같은 값으로 본다.
def norm(h):
    x = h.lstrip('#').lower()
    if len(x) == 3:
        x = ''.join(c * 2 for c in x)
    return '#' + x[:6]

HEX = re.compile(r'#[0-9a-fA-F]{3,8}\b')
missed = []
for name in ['aidatahub.css', 'governance.css', 'layout.css']:
    p = pathlib.Path('app/static/data') / name
    t = p.read_text(encoding='utf-8')
    for src, dst in MAP.items():
        if src.startswith('rgba'):
            t = t.replace(src, dst)
    def sub(m):
        key = norm(m.group(0))
        if key in MAP:
            return MAP[key]
        missed.append((name, m.group(0)))
        return m.group(0)
    t = HEX.sub(sub, t)
    p.write_text(t, encoding='utf-8')
    print('치환', name)

if missed:
    print('\n매핑에 없는 색:')
    for name, h in sorted(set(missed)):
        print('   {}  {}'.format(name, h))
else:
    print('\n모든 색 리터럴이 매핑되었다.')
PY
.venv/bin/python /tmp/phase1_map.py
```

Expected: `모든 색 리터럴이 매핑되었다.`
"매핑에 없는 색" 이 나오면 그 색의 사용처를 `grep` 으로 보고 위 표의 규칙(용도 → 토큰)에 따라 `MAP` 에 더한 뒤 `git checkout app/static/data/` 로 되돌리고 다시 돌린다.

- [ ] **Step 2: 스캐너가 통과하는지 본다 (GREEN)**

```bash
.venv/bin/python scripts/verify_tokens.py
```

Expected: `토큰을 거치지 않은 선언 0건` `PASS`.

- [ ] **Step 3: diff 를 읽는다**

기계 치환이므로 사람이 한 번 본다.

```bash
git diff --stat app/static/data/
git diff app/static/data/governance.css
```

셀렉터·치수·속성 이름이 바뀐 곳이 **한 줄도 없어야 한다.** 색 값만 바뀌어야 한다.

- [ ] **Step 4: 레이아웃 불변 + 화면 확인**

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-t6
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-t6
.venv/bin/python scripts/capture_ui.py /tmp/ui-t6
node scripts/verify_screen_js.js
```

Expected: 전부 `PASS`.

- [ ] **Step 5: 데이터 화면 7장을 다시 본다**

Task 5 Step 6 과 같은 4가지를 다시 확인한다. 이번에는 하드코딩이 전부 사라졌으므로 청록이 **한 점도** 남아 있으면 안 된다.

- [ ] **Step 6: 커밋**

```bash
rm -f /tmp/phase1_map.py
git add app/static/data/
git commit -m "refactor: 데이터 계열 CSS 의 색 리터럴 74종을 브랜드 토큰 참조로 교체

눈으로 구분되지 않는 값이 따로 선언돼 있었다(#eef3f4·#edf4f5·#edf2f3·
#eef2f3·#eef1f2 가 모두 같은 자리). 용도별 램프로 접었다."
```

---

### Task 7: WeZonGrid 네임스페이스 매핑

**Files:**
- Modify: `app/static/assets/css/tokens.css` (매핑 블록 추가)

**Interfaces:**
- Consumes: Task 3 의 브랜드 램프.
- Produces: 없음.

그리드는 모든 MES 화면에 있고 지금 **남색(`#003597`)** 이다. 셸은 빨강인데 그리드만 파랑이라 같은 화면에 두 브랜드가 있다.

**`--wzg-font-family` 는 건드리지 않는다.** `wezongrid.js:26713` 이 이 값으로 컬럼 폭을 측정하므로 바꾸면 레이아웃이 움직인다. Phase 1 의 합격 기준과 충돌한다. 스펙 §6 Phase 1 의 서체 항목도 "데이터 계열의 Inter 선행 제거"만 말한다. 그리드 서체는 Phase 3 으로 넘긴다.

- [ ] **Step 1: tokens.css 에 그리드 매핑을 더한다**

파일 끝에 붙인다.

```css
/* --- WeZonGrid (--wzg-*) ----------------------------------------------
 * wezongrid.css 는 수정하지 않는다(§7). 문서화된 커스터마이즈 지점인
 * 커스텀 프로퍼티만 덮는다. layout_page.html 에서 tokens.css 가
 * wezongrid.css 보다 뒤에 실려야 이 블록이 산다.
 *
 * --wzg-font-family 는 손대지 않는다. wezongrid.js 가 이 값으로 컬럼 폭을
 * 측정하므로 바꾸면 레이아웃이 움직인다. Phase 3 에서 다룬다. */
:root {
    --wzg-primary-color:   var(--brand-primary);
    --wzg-primary-hover:   var(--brand-primary-hover);
    --wzg-primary-light:   var(--brand-primary-tint);

    --wzg-text:            var(--brand-ink);
    --wzg-text-secondary:  var(--brand-muted);
    --wzg-border:          var(--brand-line);
    --wzg-border-light:    #e7e7e7;

    --wzg-header-bg:       var(--brand-surface-3);
    --wzg-header-text:     var(--brand-ink);
    --wzg-header-hover:    var(--brand-surface-4);

    /* 행 전체를 덮는 넓은 면적이다. 빨강을 쓰지 않는다(§5). */
    --wzg-row-hover-bg:        var(--brand-surface-2);
    --wzg-row-selected-bg:     var(--row-select-bg);
    --wzg-row-selected-text:   var(--brand-ink);
    --wzg-row-selected-soft-tint: rgba(36, 36, 36, .06);

    /* 셀 단위는 좁으므로 브랜드로 표시한다. */
    --wzg-cell-edit-border:    var(--brand-primary);
    --wzg-cell-selected-border: var(--brand-primary);
    --wzg-cell-selected-bg:    var(--brand-primary-tint);
    --wzg-cell-error-border:   var(--brand-danger);
    --wzg-cell-error-bg:       var(--brand-danger-tint);

    --wzg-footer-bg:       var(--brand-surface-3);
    --wzg-footer-text:     var(--brand-ink);
    --wzg-pager-active-bg: var(--brand-primary);
    --wzg-pager-border:    var(--brand-line);

    --wzg-sort-icon-color:     var(--brand-primary);
    --wzg-copy-border:         var(--brand-primary);
    --wzg-resize-handle-color: rgba(218, 33, 41, .3);
    --wzg-tree-icon-color:     var(--brand-primary);

    --wzg-status-edited:   var(--brand-warning);
    --wzg-status-deleted:  var(--brand-danger);
}
```

- [ ] **Step 2: 그리드가 실제로 빨강이 되었는지 확인한다**

```bash
cat > /tmp/check_grid.py <<'PY'
import pathlib
from playwright.sync_api import sync_playwright
BASE = 'http://127.0.0.1:8123'
pwd = pathlib.Path('.admin_pw').read_text(encoding='utf-8').strip()
with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_context(viewport={'width':1920,'height':911}).new_page()
    p.goto(BASE + '/login/', wait_until='domcontentloaded')
    p.fill('#loginId','admin'); p.fill('#loginPwd',pwd); p.click('#login')
    p.wait_for_url(BASE + '/', timeout=15000)
    p.goto(BASE + '/gui/wm_user/', wait_until='domcontentloaded'); p.wait_for_timeout(2500)
    print(p.evaluate("""() => {
      const s = getComputedStyle(document.documentElement);
      return { primary: s.getPropertyValue('--wzg-primary-color').trim(),
               selected: s.getPropertyValue('--wzg-row-selected-bg').trim(),
               font: s.getPropertyValue('--wzg-font-family').trim().slice(0,16) };
    }"""))
    p.screenshot(path='/tmp/grid-after.png'); b.close()
PY
.venv/bin/python /tmp/check_grid.py
```

Expected: `primary` 가 `var(--brand-primary)` 또는 `#da2129`, `selected` 가 중립(`var(--row-select-bg)` / `#edeff1`), `font` 는 **여전히 `'Malgun Gothic'`** 이다.

- [ ] **Step 3: 레이아웃 불변 확인 — 여기가 가장 위험하다**

그리드는 컬럼 폭을 JS 로 계산한다. 색만 바꿨어도 측정에 영향이 없는지 반드시 본다.

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-t7
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-t7
```

Expected: `PASS`, 이동 0건.
이동이 나오면 **멈춘다.** `--wzg-header-font-weight` 나 `--wzg-cell-padding` 같은 치수 토큰을 건드린 것이다. 위 블록에는 색만 있어야 한다.

- [ ] **Step 4: 그리드가 있는 화면을 본다**

```bash
.venv/bin/python scripts/capture_ui.py /tmp/ui-t7
```

`/tmp/ui-t7/01-system/wm_user.png` 와 `/tmp/ui-t7/04-basic/wm_code.png` 를 연다. 헤더·푸터·페이저의 파랑이 사라지고 선택 행이 중립 회색인지 본다.

- [ ] **Step 5: 커밋**

```bash
git add app/static/assets/css/tokens.css
git commit -m "refactor: WeZonGrid 색을 브랜드 토큰에 연결 (서체·치수는 유지)

그리드가 남색(#003597)이라 셸의 빨강과 한 화면에 두 브랜드가 있었다.
--wzg-font-family 는 wezongrid.js 가 컬럼 폭 측정에 쓰므로 제외한다."
```

---

### Task 8: 전수 검증 + 문서 갱신

**Files:**
- Modify: `AGENTS.md` ([6] 검증 명령 목록)
- Modify: `docs/09_UI_DESIGN_SYSTEM.md` (§8 Q-4 종결, Phase 1 완료 기록)

**Interfaces:**
- Consumes: 앞 Task 전부.

- [ ] **Step 1: 검증 전부를 돌린다**

```bash
cd /home/yhan/projects/manufacturing_ai_platform
.venv/bin/python manage.py test tests --settings=configurations.test_settings 2>&1 | tail -5
node scripts/verify_screen_js.js | tail -3
.venv/bin/python scripts/verify_menu.py | tail -3
.venv/bin/python scripts/verify_permission_map.py | tail -3
.venv/bin/python scripts/verify_response_keys.py | tail -3
.venv/bin/python scripts/verify_tokens.py | tail -3
```

Expected: 단위테스트 64 OK, 나머지 5개 전부 `PASS`.

- [ ] **Step 2: 레이아웃 불변을 최종 확인한다**

```bash
.venv/bin/python scripts/verify_layout_stable.py capture /tmp/geo-final
.venv/bin/python scripts/verify_layout_stable.py compare /tmp/geo-before /tmp/geo-final
```

Expected: `PASS`, **이동 0건**. 이것이 Phase 1 의 합격 기준이다(§6).

- [ ] **Step 3: e2e 를 돌린다**

서버가 떠 있어야 한다. 약 4분 걸린다.

```bash
.venv/bin/python -m pytest tests/e2e -q 2>&1 | tail -5
```

Expected: `58 passed`.

- [ ] **Step 4: 25화면을 전후로 나란히 본다**

```bash
.venv/bin/python scripts/capture_ui.py /tmp/ui-final
```

Expected: `화면 25개 / 오류 0건` `PASS`.

`/tmp/ui-final` 과 Phase 0 직후의 캡처를 화면별로 비교한다. 확인할 것:

1. 청록이 한 점도 남아 있지 않다
2. 남색 그리드가 없다
3. 선택 행·연한 영역이 분홍이 아니다
4. 오류 표시가 브랜드 빨강과 구분된다
5. 글자가 사라지거나 대비가 무너진 곳이 없다

- [ ] **Step 5: AGENTS.md 의 검증 목록을 갱신한다**

`[6] 실행` 의 검증 블록에 두 줄을 더한다.

```bash
python scripts/verify_tokens.py                  # CSS ↔ 디자인 토큰 (하드코딩 색·서체)
python scripts/verify_layout_stable.py capture <폴더>   # 화면 요소 바운딩 박스 (디자인 작업 전후 비교)
```

- [ ] **Step 6: 스펙에 Phase 1 완료를 기록한다**

`docs/09_UI_DESIGN_SYSTEM.md` §8 의 Q-4 행을 지우고, 표 아래에 다음을 더한다.

```markdown
**Q-4 종결(2026-10-02).** `--brand-primary` 를 `#da2129` 로 옮겼다. 25화면
재캡처에서 레이아웃 이동 0건을 확인했다. 함께 정한 것:

- 오류색은 브랜드 빨강과 분리해 `#bd5a4d` 를 유지한다. 브랜드가 빨강인 이상
  오류를 같은 빨강으로 두면 구분되지 않는다
- `--teal-soft` 를 `--row-select-bg`(중립, 넓은 면적)와
  `--brand-primary-tint`(좁은 면적)로 쪼갰다. §5 의 "재설계가 필요한 지점"이
  여기였다
- WeZonGrid 의 서체(`--wzg-font-family: 'Malgun Gothic'`)는 바꾸지 않았다.
  `wezongrid.js` 가 이 값으로 컬럼 폭을 측정해 레이아웃이 움직인다 →
  **Phase 3 으로 넘긴다**
```

- [ ] **Step 7: 커밋**

```bash
git add AGENTS.md docs/09_UI_DESIGN_SYSTEM.md
git commit -m "docs: Phase 1 토큰 단일화 결과와 검증 명령 2개를 문서에 반영"
```

- [ ] **Step 8: 브랜치를 마무리한다**

**REQUIRED SUB-SKILL:** superpowers:finishing-a-development-branch 를 쓴다.

---

## 남는 것 (Phase 1 범위 밖)

| 항목 | 왜 미뤘나 | 언제 |
|---|---|---|
| `--wzg-font-family` 를 Pretendard 로 | `wezongrid.js` 가 컬럼 폭 측정에 쓴다. 레이아웃이 움직여 Phase 1 의 합격 기준과 충돌한다 | Phase 3 |
| `--ct-danger: #2e2e31` (빨강이 아니라 진회색) | 버튼 체계와 함께 봐야 한다 | Phase 3 |
| `.btn-info`·`.text-info`(`#6451f3`) 제거 | 템플릿에서 한 번도 쓰이지 않는 죽은 코드 | Phase 5 |
| `--crud-shell-height: calc(100vh - 94px)` 와 `--ct-topbar-height: 50px` 의 이중 높이 식 | 스펙 §6 Phase 0 이 정리 대상으로 지목했으나 치수라 레이아웃이 움직인다 | Phase 3 |
| 사이드바용 흰색 워드마크 | 로고 자산 작업과 묶인다 | Phase 4 |
