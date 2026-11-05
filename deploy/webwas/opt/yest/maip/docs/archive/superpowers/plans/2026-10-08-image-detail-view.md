# 이미지 상세 보기(휠 확대·끌어 이동) + 대표 이미지 미리보기 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검사항목 편집 창에서 지금 대표 이미지를 보이고, 이미지를 크게 보이는 화면에서 마우스 휠로 커서 자리를 기준으로 확대하고 끌어서 옮겨 자세히 볼 수 있게 한다.

**Architecture:** 읽기 전용 이미지 칸(데이터 목록·검수 상세, 검사 결과/이력, Overlay 관리)은 공통 도우미 `ImageZoom.attach(viewport, target)` 하나가 `transform` 으로 확대·이동한다. 겹침(BBOX·Polygon)은 대상 안에 % 좌표로 있어 함께 커진다. 라벨링은 이미 "실제 px 크기 + 스크롤" 방식의 배율(50~400%)이 있으므로 그 위에 휠(커서 기준)과 끌어 이동(스크롤)만 더한다 — 그리기 좌표 계산(`getBoundingClientRect`)을 건드리지 않는다.

**Tech Stack:** Django Template + jQuery + 순수 JS(Pointer Events, `wheel`), Playwright e2e, Django TestCase

**Spec:** 사용자 요청(2026-10-08) — "편집 모달 정보에 대표 이미지 영역", "이미지가 크게 표시되는 화면에서 마우스 휠 + 끌어 이동으로 상세 보기, 라벨링·검수 필수"

## Global Constraints

- 새 라이브러리를 들이지 않는다(외부 줌 플러그인 금지). 순수 JS 로 만든다.
- 동기 Ajax 금지. 사용자 값은 `.text()`·속성으로 넣고 `.html()` 로 잇지 않는다(AGENTS [4]).
- 사용자에게 보이는 문구는 `~합니다` 체.
- 색은 `tokens.css` 토큰만(`scripts/verify_tokens.py`). 이번 CSS 는 색을 쓰지 않는다.
- 단위 테스트는 `--settings=configurations.test_settings`. e2e 는 실제 DB — `item` 픽스처(`E2E-` 검사항목)만 쓰고 지운다.
- 라벨링 좌표(BBOX·Polygon 저장 값)가 바뀌면 안 된다. 기존 `tests/e2e/test_image_fit.py` 가 계속 통과해야 한다.

## 조사 결과 — 이미지를 크게 보이는 화면

| 화면 | 템플릿 | 이미지 칸 | 이번 처리 |
|---|---|---|---|
| **라벨링 작업** | `data/labeling.html` | `#canvasHolder` > `#imageStage`(px 배율 + 스크롤, 50~400% 버튼) | **필수** — 휠·끌어 이동 추가(Task 4) |
| **검수 작업** 상세 | `data/review.html` | `AnnotationView.createAnnotationPreview(...)` | **필수** — 공통 도우미(Task 2) |
| 데이터 목록 상세 | `data/image.html` | 같은 `createAnnotationPreview` | Task 2 에서 함께 된다 |
| 검사 결과/이력 상세 | `vision/inspection.html` | `#inspImageBox` > `#inspImage` | Task 3 |
| Overlay 관리 상세 | `vision/overlay.html` | `#overlayImageBox` > `#overlayPreview` | Task 3 |
| 이미지 편집 창(전처리) | `data/image.html` `#preprocessStage` | 클릭으로 자르기 점을 찍는다 | **제외** — 클릭·끌기가 편집 동작과 겹친다. 필요하면 별도 작업 |
| 검사항목 홈 최근 데이터·목록 썸네일 | `data/item.html` 등 | 32~96px 썸네일 | 제외(크게 보이는 화면이 아니다) |

## 조작 규칙(결정 — 실행 전 확인)

| 동작 | 읽기 전용 칸(Task 2·3) | 라벨링(Task 4) |
|---|---|---|
| 휠 | 커서 자리를 기준으로 확대·축소(1~8배). 원래 크기에서 더 줄이면 화면이 스크롤된다 | 커서 자리를 기준으로 50~400% |
| 끌기 | 확대했을 때만 왼쪽 버튼으로 이동 | **왼쪽 버튼**: BBOX 를 그리지 않을 때(작업 전·Polygon·분류) 이동. **휠 버튼(가운데)**: 언제나 이동 |
| 원래대로 | 더블클릭 | 기존 −/+ 버튼(더블클릭은 Polygon 점 찍기와 겹쳐 쓰지 않는다) |

Polygon 은 클릭으로 점을 찍으므로 4px 넘게 움직였을 때만 이동으로 보고, 그 뒤 click 은 점을 찍지 않는다.

## 파일 구조

| 파일 | 책임 |
|---|---|
| Create `app/static/assets/js/image_zoom.js` | 읽기 전용 이미지 칸의 휠 확대·끌어 이동·더블클릭 원래대로 |
| Modify `app/static/assets/css/SF-Custom.css` | `.image-zoom-viewport` 커서·overflow 규칙 |
| Modify `app/static/data/annotation.js` | `createAnnotationPreview` 가 도우미를 붙인다 |
| Modify `app/templates/data/review.html`, `data/image.html`, `vision/inspection.html`, `vision/overlay.html` | 도우미 스크립트 싣기·붙이기 |
| Modify `app/templates/data/labeling.html`, `app/static/data/main.css` | 휠(커서 기준)·끌어 이동 |
| Modify `app/views/item/item_home.py`, `app/templates/data/item.html` | 편집 창 대표 이미지 미리보기, `cover_url` 캐시 갱신 |
| Create `tests/e2e/test_image_view.py` | 위 동작 e2e |
| Modify `tests/test_item_api.py` | `cover_url` 이 바뀐 이미지에서 달라지는지 |
| Modify `docs/FEATURES.md`, `docs/UI_GUIDE.md` | 조작 규칙 |

---

### Task 1: 검사항목 편집 창의 대표 이미지 미리보기

지금은 파일 선택칸만 있어 어떤 이미지가 등록돼 있는지 모른다. 같은 칸에 현재 이미지를 보이고, 파일을 고르면 저장 전 미리보기로 바꾼다.
또 `cover_url` 이 `/media/item-cover/<id>/` 로 늘 같아서 새 이미지로 바꿔도 브라우저가 옛 그림을 보일 수 있다 — `?v=<수정 시각>` 을 붙인다.
`_update` 는 `save(update_fields=['cover_image'])` 라 `updated_at` 이 안 바뀌므로 함께 저장한다.

**Files:**
- Modify: `app/views/item/item_home.py` (`_detail` 의 `cover_url`, `_update` 의 `save`)
- Modify: `app/templates/data/item.html:68-69`(마크업), `fillEdit()`(약 216행), `init` 이벤트(약 112행)
- Test: `tests/test_item_api.py` `ItemHomeApiTest`, `tests/e2e/test_image_view.py`

**Interfaces:**
- Produces: 응답 `cover_url` = `'/media/item-cover/<id>/?v=<int(updated_at.timestamp())>'` 또는 `''`. 화면 요소 `#infoCoverBox`·`#infoCoverPreview`·`#infoCoverEmpty`

- [ ] **Step 1: 실패하는 단위 테스트**

`tests/test_item_api.py` `ItemHomeApiTest` 에 추가:

```python
    def test_대표_이미지를_바꾸면_주소가_달라진다(self):
        def upload(name):
            response = self.http(self.manager).post('/api/item/item_home?action=update', {
                'item_id': self.item.id, 'name': 'API 검사', 'cover_image': make_image(name)}, **AJAX)
            self.assertEqual(response.status_code, 200, response.content.decode()[:200])
            return self._detail(self.manager).json()['cover_url']

        first = upload('a.png')
        time.sleep(1.1)  # ?v= 는 초 단위다
        second = upload('b.png')
        self.assertIn('?v=', first)
        self.assertNotEqual(first, second)
```

(`import time` 을 파일 위에 더한다.)

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python manage.py test tests.test_item_api.ItemHomeApiTest --settings=configurations.test_settings`
Expected: FAIL — `'?v=' not found in '/media/item-cover/1/'`

- [ ] **Step 3: 서버 구현**

`app/views/item/item_home.py` `_detail`:

```python
        'cover_url': (f"{reverse('private-item-cover', args=[item.id])}?v={int(item.updated_at.timestamp())}"
                      if item.cover_image else ''),
```

`_update` 의 저장 줄:

```python
        item.save(update_fields=['cover_image', 'updated_at'])
```

- [ ] **Step 4: 통과 확인** — 같은 명령, Expected: OK

- [ ] **Step 5: 화면 마크업** — `data/item.html` 68-69행을 바꾼다

```html
            <div class="mb-2"><label for="infoCover" class="form-label">대표 이미지(PNG·JPEG)</label>
              <div class="detail-image-box mb-2" id="infoCoverBox" style="height: 240px">
                <img id="infoCoverPreview" class="d-none" alt="대표 이미지 미리보기">
                <p class="text-muted mb-0" id="infoCoverEmpty">대표 이미지가 없습니다.</p>
              </div>
              <input type="file" class="form-control" id="infoCover" name="cover_image" accept="image/png,image/jpeg"></div>
```

(`.detail-image-box` 는 검사 결과/이력·Overlay 가 쓰는 칸이다 — 이미지는 비율을 지켜 담긴다. 그 화면에서는 옆 표 높이를 따르고 데스크톱 최소 높이가 120px 라, 표가 없는 편집 창에서는 높이를 240px 로 정한다.)

- [ ] **Step 6: 화면 스크립트** — `fillEdit()` 의 `$('#infoCover').val('');` 다음에 `this.showCover(item.cover_url);` 을 넣고, 클래스에 메서드를 더한다

```js
        // 편집 창의 대표 이미지. 파일을 고르면 저장 전 미리보기(blob 주소)로 바꾼다.
        showCover(url) {
            if (this.coverObjectUrl) { URL.revokeObjectURL(this.coverObjectUrl); this.coverObjectUrl = null; }
            $('#infoCoverPreview').attr('src', url || '').toggleClass('d-none', !url);
            $('#infoCoverEmpty').toggleClass('d-none', !!url);
        }
```

`init` 의 `$('#btnSaveInfo')...` 다음 줄:

```js
            $('#infoCover').on('change', function () {
                const file = this.files && this.files[0];
                if (!file) { _this.showCover(_this.item && _this.item.cover_url); return; }
                _this.showCover('');
                _this.coverObjectUrl = URL.createObjectURL(file);
                $('#infoCoverPreview').attr('src', _this.coverObjectUrl).removeClass('d-none');
                $('#infoCoverEmpty').addClass('d-none');
            });
```

- [ ] **Step 7: e2e** — `tests/e2e/test_image_view.py` 를 만들고 첫 테스트를 넣는다

```python
"""이미지 상세 보기 — 편집 창 대표 이미지, 휠 확대·끌어 이동.

실제 DB 를 쓴다. `item` 픽스처가 `E2E-` 검사항목을 만들고 지운다.
"""
import pytest

from tests.e2e.test_crud import mes
from tests.e2e.test_write_paths import item, open_gui, send, send_mes  # noqa: F401 — item 은 픽스처다

LARGE = 'e2e-zoom-large.png'


@pytest.fixture
def large_png(tmp_path):
    from PIL import Image
    path = tmp_path / LARGE
    Image.new('RGB', (1600, 1200), (180, 90, 60)).save(path)
    return str(path)


def test_편집_창에_대표_이미지가_보인다(page, base_url, item, large_png):
    page.goto(f'{base_url}/gui/wm_data_item_detail/?project={item["id"]}', wait_until='networkidle')
    page.click('#btnEdit')
    page.wait_for_selector('#itemEditModal.show')
    assert page.is_visible('#infoCoverEmpty') and not page.is_visible('#infoCoverPreview')
    page.set_input_files('#infoCover', large_png)
    assert page.get_attribute('#infoCoverPreview', 'src').startswith('blob:')
    send(page, lambda: page.click('#btnSaveInfo'))
    page.wait_for_timeout(1200)
    src = page.get_attribute('#infoCoverPreview', 'src')
    assert '/media/item-cover/' in src and '?v=' in src, src
    assert page.evaluate("() => document.getElementById('infoCoverPreview').naturalWidth") == 1600
```

Run: `.venv/bin/python -m pytest tests/e2e/test_image_view.py -q -k 대표` (서버 8123 필요) — Expected: 1 passed

- [ ] **Step 8: 커밋**

```bash
git add app/views/item/item_home.py app/templates/data/item.html tests/test_item_api.py tests/e2e/test_image_view.py
git commit -m "feat: 검사항목 편집 창에 대표 이미지 미리보기를 보인다"
```

---

### Task 2: 공통 도우미 `ImageZoom` + 데이터 목록·검수 상세

**Files:**
- Create: `app/static/assets/js/image_zoom.js`
- Modify: `app/static/assets/css/SF-Custom.css` (`.detail-image-box` 규칙 아래)
- Modify: `app/static/data/annotation.js` (`createAnnotationPreview`)
- Modify: `app/templates/data/review.html:42`, `app/templates/data/image.html:150` (스크립트 싣기)
- Test: `tests/e2e/test_image_view.py`

**Interfaces:**
- Produces: `window.ImageZoom.attach(viewport: Element, target: Element) -> {reset(): void, scale(): number}`. 같은 viewport 에 두 번 붙이면 처음 것을 돌려준다(`viewport.imageZoom`). 대상이 `IMG` 면 새 그림이 로드될 때 원래대로 돌아간다. viewport 에 `.image-zoom-viewport`, 확대 중 `.is-zoomed`, 끄는 중 `.is-dragging` 클래스를 단다.

- [ ] **Step 1: 실패하는 e2e** — `tests/e2e/test_image_view.py` 에 추가

```python
# 대상 요소(확대되는 것)의 화면 위 상자
BOX_JS = "s => { const r = document.querySelector(s).getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }"


def upload(page, base_url, item_id, path):
    page.goto(f'{base_url}/gui/wm_data_image/?project={item_id}', wait_until='networkidle')
    page.get_by_role('button', name='데이터 추가').click()
    page.set_input_files('#imageFiles', [path])
    send(page, lambda: page.click('#startUpload'))
    page.wait_for_selector('#uploadModal', state='hidden', timeout=15000)


def assert_wheel_and_drag(page, viewport, target):
    """휠 → 커서 자리 기준 확대, 끌기 → 이동, 더블클릭 → 원래대로."""
    left, top, width, height = page.evaluate(BOX_JS, target)
    cx, cy = left + width * 0.25, top + height * 0.25
    page.mouse.move(cx, cy)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(200)
    l2, t2, w2, h2 = page.evaluate(BOX_JS, target)
    assert w2 > width * 1.5, (width, w2)
    # 커서 아래 점(대상의 왼쪽 위 1/4 지점)이 그 자리에 남는다
    assert abs((cx - l2) / w2 - 0.25) < 0.01 and abs((cy - t2) / h2 - 0.25) < 0.01
    page.mouse.down()
    page.mouse.move(cx + 80, cy + 40, steps=5)
    page.mouse.up()
    l3, t3, _, _ = page.evaluate(BOX_JS, target)
    assert abs((l3 - l2) - 80) <= 2 and abs((t3 - t2) - 40) <= 2, (l2, l3, t2, t3)
    page.dblclick(viewport)
    page.wait_for_timeout(100)
    assert abs(page.evaluate(BOX_JS, target)[2] - width) <= 1


def test_데이터_목록과_검수_상세에서_휠로_확대하고_끌어_옮긴다(page, base_url, item, large_png):
    item_id = item['id']
    upload(page, base_url, item_id, large_png)
    page.locator('#main-grid').get_by_text(LARGE, exact=True).click()
    page.wait_for_timeout(900)
    assert_wheel_and_drag(page, '.image-detail-preview', '.image-detail-coordinate-surface')

    queue = mes(page, f'/api/item/labeling?action=queue&item_id={item_id}')
    task = mes(page, '/api/item/labeling?action=claim', {'item_id': item_id, 'image_id': queue['images'][0]['id']})['task']
    mes(page, '/api/item/labeling?action=submit', {'item_id': item_id, 'task_id': task['id'], 'lease_token': task['lease_token']})
    page.goto(f'{base_url}/gui/wm_data_review/?project={item_id}', wait_until='networkidle')
    page.wait_for_timeout(800)
    page.locator('#main-grid').get_by_text(LARGE, exact=True).click()
    page.wait_for_timeout(900)
    assert_wheel_and_drag(page, '.image-detail-preview', '.image-detail-coordinate-surface')
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/python -m pytest tests/e2e/test_image_view.py -q -k 데이터_목록` — Expected: FAIL `assert w2 > width * 1.5`

- [ ] **Step 3: 도우미 작성** — `app/static/assets/js/image_zoom.js`

```js
/* 이미지 상세 보기 — 휠: 커서 자리를 기준으로 확대·축소, 끌기: 확대한 이미지 이동, 더블클릭: 원래 크기.
 * 대상(target)에 transform 을 건다. 겹침(BBOX·Polygon)은 대상 안에 % 좌표로 있어 함께 커진다.
 * 라벨링은 이것을 쓰지 않는다(px 배율 + 스크롤, data/labeling.html). */
(function (window) {
  "use strict";

  var MAX_SCALE = 8;
  var WHEEL_RATE = 0.002; // deltaY 1 당 지수 배율. 마우스 휠 한 칸(100) ≈ 1.22배

  function attach(viewport, target) {
    if (viewport.imageZoom) { return viewport.imageZoom; }
    var state = { scale: 1, x: 0, y: 0 };
    var drag = null;
    viewport.classList.add("image-zoom-viewport");
    viewport.title = "휠로 확대·축소하고, 끌어서 옮기고, 더블클릭하면 원래 크기로 돌아갑니다.";
    target.style.transformOrigin = "0 0";

    // 확대한 그림이 원래 칸을 늘 덮게 이동 범위를 막는다(빈 곳으로 밀려나지 않는다).
    function apply() {
      var w = target.offsetWidth, h = target.offsetHeight;
      state.x = Math.min(0, Math.max(w * (1 - state.scale), state.x));
      state.y = Math.min(0, Math.max(h * (1 - state.scale), state.y));
      target.style.transform = state.scale === 1 ? "" : "translate(" + state.x + "px, " + state.y + "px) scale(" + state.scale + ")";
      viewport.classList.toggle("is-zoomed", state.scale > 1);
    }

    function reset() {
      state = { scale: 1, x: 0, y: 0 };
      drag = null;
      viewport.classList.remove("is-dragging");
      apply();
    }

    viewport.addEventListener("wheel", function (event) {
      var next = Math.min(MAX_SCALE, Math.max(1, state.scale * Math.exp(-event.deltaY * WHEEL_RATE)));
      if (next === state.scale) {
        if (state.scale > 1) { event.preventDefault(); } // 최대에서 더 키우려는 휠은 삼킨다
        return; // 원래 크기에서 줄이는 휠은 화면 스크롤에 맡긴다
      }
      event.preventDefault();
      // 커서 아래 점(대상 기준 좌표 u)이 확대 뒤에도 커서 아래 남도록 x' = 커서 - 원위치 - u·s'
      var rect = target.getBoundingClientRect();
      var ux = (event.clientX - rect.left) / state.scale, uy = (event.clientY - rect.top) / state.scale;
      var originX = rect.left - state.x, originY = rect.top - state.y;
      state.x = event.clientX - originX - ux * next;
      state.y = event.clientY - originY - uy * next;
      state.scale = next;
      apply();
    }, { passive: false });

    viewport.addEventListener("pointerdown", function (event) {
      if (state.scale === 1 || event.button !== 0) { return; }
      event.preventDefault();
      drag = { id: event.pointerId, x: event.clientX - state.x, y: event.clientY - state.y };
      viewport.setPointerCapture(event.pointerId);
      viewport.classList.add("is-dragging");
    });
    viewport.addEventListener("pointermove", function (event) {
      if (!drag || event.pointerId !== drag.id) { return; }
      state.x = event.clientX - drag.x;
      state.y = event.clientY - drag.y;
      apply();
    });
    function endDrag(event) {
      if (!drag || event.pointerId !== drag.id) { return; }
      drag = null;
      viewport.classList.remove("is-dragging");
    }
    viewport.addEventListener("pointerup", endDrag);
    viewport.addEventListener("pointercancel", endDrag);
    viewport.addEventListener("dblclick", reset);
    viewport.addEventListener("dragstart", function (event) { event.preventDefault(); });
    if (target.tagName === "IMG") { target.addEventListener("load", reset); }

    viewport.imageZoom = { reset: reset, scale: function () { return state.scale; } };
    return viewport.imageZoom;
  }

  window.ImageZoom = { attach: attach };
}(window));
```

- [ ] **Step 4: CSS** — `SF-Custom.css` 의 `.detail-image-box > p {...}` 규칙 다음에 추가

```css
/* 이미지 상세 보기(assets/js/image_zoom.js). 확대한 그림은 칸 밖으로 나가지 않는다 */
.image-zoom-viewport { overflow: hidden; cursor: zoom-in; }
.image-zoom-viewport.is-zoomed { cursor: grab; touch-action: none; }
.image-zoom-viewport.is-dragging { cursor: grabbing; }
.image-zoom-viewport img { user-select: none; -webkit-user-drag: none; }
```

- [ ] **Step 5: 미리보기에 붙이기** — `annotation.js` `createAnnotationPreview` 의 `preview.appendChild(surface);` 다음

```js
    // 휠 확대·끌어 이동(assets/js/image_zoom.js 가 실려 있을 때). 칸 크기가 바뀌면 원래 크기로 돌린다.
    var zoom = window.ImageZoom ? window.ImageZoom.attach(preview, surface) : null;
```

그리고 ResizeObserver 콜백의 `fitSurface(surface, preview, image);` 다음 줄에 `if (zoom) { zoom.reset(); }` 를 넣는다.

- [ ] **Step 6: 스크립트 싣기** — `review.html` 42행, `image.html` 150행의 `data/annotation.js` 줄 **앞**에

```html
<script src="{% static 'assets/js/image_zoom.js' %}"></script>
```

- [ ] **Step 7: 통과 확인** — Step 2 명령, Expected: 1 passed. `node scripts/verify_screen_js.js` PASS

- [ ] **Step 8: 커밋**

```bash
git add app/static/assets/js/image_zoom.js app/static/assets/css/SF-Custom.css app/static/data/annotation.js app/templates/data/review.html app/templates/data/image.html tests/e2e/test_image_view.py
git commit -m "feat: 데이터 목록·검수 상세 이미지를 휠로 확대하고 끌어 옮긴다"
```

---

### Task 3: 검사 결과/이력·Overlay 관리 상세

**Files:**
- Modify: `app/templates/vision/overlay.html` (69행 스크립트 블록, `init()` 72행)
- Modify: `app/templates/vision/inspection.html` (74행 스크립트 블록, `init()` 77행)
- Test: `tests/e2e/test_image_view.py`

**Interfaces:**
- Consumes: `ImageZoom.attach(viewport, target)` (Task 2). `#overlayPreview`·`#inspImage` 는 `src` 가 바뀌면 `load` 때 원래대로 돌아간다(도우미가 처리).

- [ ] **Step 1: 실패하는 e2e**

```python
def test_Overlay_상세에서_휠로_확대한다(page, base_url, item, large_png):
    open_gui(page, base_url, 'wm_vis_overlay')
    page.locator('#main-grid').get_by_text(item['name'], exact=True).first.click()
    page.wait_for_timeout(800)
    page.click('#btnEdit')
    page.set_input_files('#image', large_png)
    send_mes(page, lambda: page.click('#btnSave'), 'overlay?action=save')
    page.wait_for_timeout(1200)
    assert_wheel_and_drag(page, '#overlayImageBox', '#overlayPreview')
```

(`#overlayPreview` 는 칸 전체를 차지하고 `object-fit: contain` 으로 그림을 담는다 — 요소 상자가 커지는지로 본다.)

- [ ] **Step 2: 실패 확인** — `-k Overlay_상세에서`, Expected: FAIL `assert w2 > width * 1.5`

- [ ] **Step 3: 구현** — 두 템플릿의 `{% block scripts %}` 바로 다음 줄에

```html
<script src="{% static 'assets/js/image_zoom.js' %}"></script>
```

(`{% load static %}` 이 파일 위에 없으면 함께 더한다.)

`overlay.html` `init()` 첫 줄:

```js
            ImageZoom.attach(document.getElementById('overlayImageBox'), document.getElementById('overlayPreview'));
```

`inspection.html` `init()` 첫 줄:

```js
            ImageZoom.attach(document.getElementById('inspImageBox'), document.getElementById('inspImage'));
```

- [ ] **Step 4: 통과 확인** — Step 2 명령 1 passed. 검사 결과/이력은 e2e 가 검사 기록을 만들 수 없어(Client API Key 필요) 개발 서버에서 직접 본다: 목록에서 CLIENT-001 행 → 이미지에 휠 → 확대·끌기·더블클릭

- [ ] **Step 5: 기존 상세 높이 테스트 회귀 확인**

Run: `.venv/bin/python -m pytest tests/e2e/test_detail_form.py -q` — Expected: 전부 passed(이미지 칸 높이 = 표 높이 유지)

- [ ] **Step 6: 커밋**

```bash
git add app/templates/vision/overlay.html app/templates/vision/inspection.html tests/e2e/test_image_view.py
git commit -m "feat: 검사 결과/이력·Overlay 상세 이미지를 휠로 확대하고 끌어 옮긴다"
```

---

### Task 4: 라벨링 — 휠(커서 기준)·끌어 이동

라벨링은 이미 `zoom`(50~400%) 이 이미지의 실제 px 크기를 바꾸고 `#canvasHolder` 가 스크롤한다. 휠은 그 배율을 바꾸되 커서 아래 점이 남도록 스크롤을 옮기고, 끌기는 스크롤을 옮긴다.

**Files:**
- Modify: `app/templates/data/labeling.html` — `<img id="annotationImage">`(92행), `zoomBy`(648행), `onPointerDown`(980행), `onImageClick`(1034행), 이벤트 연결(1107-1124행)
- Modify: `app/static/data/main.css`
- Test: `tests/e2e/test_image_view.py`

**Interfaces:**
- Produces: `page.setZoom(value: number, anchor?: {clientX, clientY})`. `zoomBy(delta)` 는 `setZoom(this.zoom + delta)` 로 남는다(버튼은 그대로).

- [ ] **Step 1: 실패하는 e2e**

```python
def test_라벨링에서_휠은_커서_기준으로_키우고_끌면_스크롤한다(page, base_url, item, large_png):
    item_id = item['id']
    upload(page, base_url, item_id, large_png)
    page.goto(f'{base_url}/gui/wm_data_labeling/?project={item_id}', wait_until='networkidle')
    page.wait_for_timeout(1000)
    page.locator('#imageQueue .image-item', has_text=LARGE).click()
    page.wait_for_timeout(600)
    left, top, width, height = page.evaluate(BOX_JS, '#annotationImage')
    cx, cy = left + width * 0.75, top + height * 0.75
    page.mouse.move(cx, cy)
    page.mouse.wheel(0, -400)
    page.wait_for_timeout(200)
    assert int(page.inner_text('#zoomValue').rstrip('%')) > 150
    l2, t2, w2, h2 = page.evaluate(BOX_JS, '#annotationImage')
    assert abs((cx - l2) / w2 - 0.75) < 0.02 and abs((cy - t2) / h2 - 0.75) < 0.02, (cx, l2, w2)

    # 작업 전(그리기 없음)에는 왼쪽 버튼으로 끌면 스크롤이 옮겨진다
    before = page.evaluate("() => [canvasHolder.scrollLeft, canvasHolder.scrollTop]")
    page.mouse.down()
    page.mouse.move(cx - 60, cy - 30, steps=5)
    page.mouse.up()
    after = page.evaluate("() => [canvasHolder.scrollLeft, canvasHolder.scrollTop]")
    assert abs((after[0] - before[0]) - 60) <= 2 and abs((after[1] - before[1]) - 30) <= 2, (before, after)
```

- [ ] **Step 2: 실패 확인** — `-k 라벨링에서`, Expected: FAIL (`zoomValue` 가 100%)

- [ ] **Step 3: 배율 함수** — `zoomBy` 를 다음으로 바꾼다

```js
        // 확대·축소(50~400%). anchor({clientX, clientY})가 있으면 그 자리의 이미지 점이 그대로 남게 스크롤을 옮긴다(휠).
        setZoom(value, anchor) {
            let zoom = this.clamp(Math.round(value), 50, 400);
            if (zoom === this.zoom) return;
            let holder = document.getElementById('canvasHolder');
            let before = this.imageElement.getBoundingClientRect();
            this.zoom = zoom;
            this.updateZoom();
            if (!anchor || !this.activeImage) return;
            let after = this.imageElement.getBoundingClientRect();
            let ratio = after.width / before.width;
            holder.scrollLeft += (anchor.clientX - before.left) * ratio - (anchor.clientX - after.left);
            holder.scrollTop += (anchor.clientY - before.top) * ratio - (anchor.clientY - after.top);
        }

        // 버튼: 25%씩
        zoomBy(delta) {
            this.setZoom(this.zoom + delta);
        }

        // 끌어서 이동. 가운데 버튼은 언제나, 왼쪽 버튼은 BBOX 를 그리지 않을 때.
        // 4px 넘게 움직여야 이동으로 본다(Polygon 점 찍기 클릭과 구분) — 이동했으면 뒤따르는 click 은 점을 찍지 않는다.
        onPanStart(event) {
            if (!this.activeImage || (this.drawing && this.drawing.mode === 'BBOX')) return;
            if (event.button !== 0 && event.button !== 1) return;
            if (event.button === 1) event.preventDefault(); // 가운데 버튼 자동 스크롤 막기
            let holder = document.getElementById('canvasHolder');
            this.pan = { id: event.pointerId, x: event.clientX, y: event.clientY,
                         left: holder.scrollLeft, top: holder.scrollTop, moved: false };
        }

        onPanMove(event) {
            if (!this.pan || event.pointerId !== this.pan.id) return;
            let holder = document.getElementById('canvasHolder');
            let dx = event.clientX - this.pan.x;
            let dy = event.clientY - this.pan.y;
            if (!this.pan.moved && Math.hypot(dx, dy) < 4) return;
            if (!this.pan.moved) {
                this.pan.moved = true;
                holder.setPointerCapture(event.pointerId);
                holder.classList.add('is-panning');
            }
            holder.scrollLeft = this.pan.left - dx;
            holder.scrollTop = this.pan.top - dy;
        }

        onPanEnd(event) {
            if (!this.pan || event.pointerId !== this.pan.id) return;
            this.panMoved = this.pan.moved;
            this.pan = null;
            document.getElementById('canvasHolder').classList.remove('is-panning');
        }
```

- [ ] **Step 4: 그리기와 나누기**

`onPointerDown` 첫 줄 앞에 `if (event.originalEvent.button !== 0) return; // 가운데 버튼은 이동` 을 넣는다.
`onImageClick` 첫 줄 앞에:

```js
            if (this.panMoved) { this.panMoved = false; return; } // 끌어서 옮긴 뒤의 click 은 점이 아니다
```

`<img id="annotationImage" alt="라벨링 대상 이미지">` 에 `draggable="false"` 를 더한다(브라우저 기본 이미지 끌기가 이동을 끊는다).

- [ ] **Step 5: 이벤트 연결** — `$('#zoomOut')...` 줄 다음에

```js
        // 휠: 커서 자리를 기준으로 확대·축소. 작은 휠 입력(트랙패드)도 1%는 움직인다.
        document.getElementById('canvasHolder').addEventListener('wheel', function (event) {
            if (!page.activeImage) return;
            event.preventDefault();
            let next = page.zoom * Math.exp(-event.deltaY * 0.002);
            next = event.deltaY < 0 ? Math.max(next, page.zoom + 1) : Math.min(next, page.zoom - 1);
            page.setZoom(next, event);
        }, { passive: false });
        $('#canvasHolder')
            .on('pointerdown', function (event) { page.onPanStart(event.originalEvent); })
            .on('pointermove', function (event) { page.onPanMove(event.originalEvent); })
            .on('pointerup pointercancel', function (event) { page.onPanEnd(event.originalEvent); })
            .attr('title', '휠로 확대·축소하고, 끌어서 옮깁니다. BBOX 를 그릴 때는 휠 버튼을 누른 채 끌어 옮깁니다.');
```

(이미지의 `pointerdown`(그리기)이 먼저 불려 `this.drawing` 을 세우므로 BBOX 그리기 중에는 이동이 시작되지 않는다.)

- [ ] **Step 6: CSS** — `app/static/data/main.css` 끝(미디어쿼리 밖)에

```css
.canvas-holder.is-panning, .canvas-holder.is-panning img { cursor: grabbing; }
```

- [ ] **Step 7: 통과·회귀 확인**

Run: `.venv/bin/python -m pytest tests/e2e/test_image_view.py tests/e2e/test_image_fit.py -q` — Expected: 전부 passed
라벨링 그리기 회귀: `.venv/bin/python -m pytest tests/e2e -q -k "labeling or 라벨링"` — Expected: passed

- [ ] **Step 8: 커밋**

```bash
git add app/templates/data/labeling.html app/static/data/main.css tests/e2e/test_image_view.py
git commit -m "feat: 라벨링 이미지를 휠로 커서 기준 확대하고 끌어 옮긴다"
```

---

### Task 5: 문서·전체 검증

**Files:**
- Modify: `docs/FEATURES.md` — 라벨링 작업 행(262행)과 데이터 목록·검수·검사 결과·Overlay 상세 설명에 조작 한 줄
- Modify: `docs/UI_GUIDE.md` — 이미지 칸 규칙 절에 "읽기 전용 이미지 칸은 `ImageZoom.attach` 를 붙인다. 휠 확대(1~8배)·끌기 이동·더블클릭 원래대로. 편집 칸(전처리·라벨링)에는 붙이지 않는다"

- [ ] **Step 1: 문서 갱신** — 위 두 곳에 한 줄씩(같은 내용을 두 문서에 반복하지 않는다 — 규칙은 UI_GUIDE, 화면별 사실은 FEATURES)

- [ ] **Step 2: 전체 검증** (AGENTS [5])

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
.venv/bin/python -m pytest tests/e2e -q
node scripts/verify_screen_js.js
.venv/bin/python scripts/verify_tokens.py
.venv/bin/python scripts/verify_modals.py
.venv/bin/python scripts/verify_buttons.py
.venv/bin/python scripts/verify_korean_only.py
.venv/bin/python scripts/verify_links.py
.venv/bin/python scripts/verify_naming.py
```

CSS 를 고쳤으므로 `scripts/verify_layout_stable.py`(DEVELOPMENT §4 절차)로 레이아웃이 움직이지 않았는지 본다.

- [ ] **Step 3: 직접 확인** — FAN-PANEL(`?project=604`)로 라벨링(Polygon 점 찍기 + 끌어 이동), 검수, 검사 결과/이력 화면을 열어 휠·끌기·더블클릭을 본다

- [ ] **Step 4: 커밋**

```bash
git add docs/FEATURES.md docs/UI_GUIDE.md
git commit -m "docs: 이미지 상세 보기(휠 확대·끌어 이동) 조작을 적는다"
```
