# Phase 0 — 화면 버그 6건 수정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 디자인 작업에 들어가기 전에, 화면이 깨져 보이거나 동작하지 않는 버그 6건을 고친다.

**Architecture:** 디자인 변경은 하지 않는다. 스타일 토큰·레이아웃은 건드리지 않고 동작만 고친다. 각 버그는 독립이라 작업 순서를 바꿔도 되지만, B-2 가 가장 크고 다른 화면의 기준이 되므로 먼저 둔다.

**Tech Stack:** Django 5.0.4 템플릿 + jQuery + Bootstrap 5 + WeZonGrid. 빌드 단계 없음.

**Spec:** [docs/09_UI_DESIGN_SYSTEM.md](../../09_UI_DESIGN_SYSTEM.md) §2.4 (B-1 ~ B-6), §6 Phase 0

## Global Constraints

- **테스트는 반드시 `--settings=configurations.test_settings` 로 돌린다.** 빼면 운영 PostgreSQL 에 테스트 DB 가 생긴다
- **동기 Ajax 를 쓰지 않는다.** 조회는 `AjaxUtil.getAsyncData`, 변경은 `postAsyncData`
- **Ajax 콜백 안에서 `this` 를 쓰지 않는다.** `let _this = this` 를 잡아 `_this` 로 쓴다. `node scripts/verify_screen_js.js` 가 잡는다
- **응답 봉투는 `{ok, message, data}` 다.** 템플릿 관용구는 `let data = response.data || response;`
- **검사항목 응답 키는 `item` 이다.** `project` 는 §1.6 에서 폐기된 용어다
- 커밋 메시지는 **한국어**, Conventional Commits 의 type 만 영문
- 개발 서버: `python manage.py runserver 127.0.0.1:8123 --noreload`, 관리자 계정은 `admin` / `.admin_pw`
- 최소 해상도 **1920 × 911**

**매 작업 공통 검증** (커밋 전 반드시):

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
node scripts/verify_screen_js.js
```

---

### Task 1: 검사항목 응답 키 `project` → `item` (B-2)

§1.6 에서 서버 응답 키를 `item` 으로 바꿀 때 템플릿 8곳이 따라오지 않았다.
서버는 `item` 만 내보낸다(`item_api.py:46,66,140` · `item_admin_api.py:56` ·
`image_api.py:143` · `snapshot_api.py:185`). 검사항목 홈은 화면 전체가 빈다.

**Files:**
- Modify: `app/templates/data/item.html:170`, `:390`
- Modify: `app/templates/data/item_list.html:353`
- Modify: `app/templates/data/labeling.html:751`
- Modify: `app/templates/data/image.html:439-440`
- Modify: `app/templates/data/snapshot.html:469`, `:494`
- Create: `scripts/verify_response_keys.py`

**Interfaces:**
- Consumes: 없음 (첫 작업)
- Produces: `scripts/verify_response_keys.py` — 인자 없이 실행, 위반 0건이면 exit 0 / `PASS` 출력, 아니면 exit 1 / `FAIL`. Task 7 의 최종 검증에서 다시 호출한다

- [ ] **Step 1: 재발 방지 검사 스크립트를 먼저 쓴다 (실패하는 테스트 역할)**

`scripts/verify_response_keys.py` 를 만든다. 데이터 관리 템플릿이 폐기된
`project` 키를 읽는 곳을 찾는다.

```python
#!/usr/bin/env python
"""데이터 관리 템플릿이 폐기된 응답 키 `project` 를 읽는 곳을 찾는다.

§1.6 에서 검사항목 응답 키는 `item` 으로 통일했다. 서버는 `item` 만 내보내므로
`response.project` / `data.project` 는 항상 undefined 이고, 화면이 조용히 빈다.
문법상 유효해서 verify_screen_js.js 로는 잡히지 않는다.

    python scripts/verify_response_keys.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'app' / 'templates' / 'data'

# response.project / data.project / detail.project / payload.project
PATTERN = re.compile(r'\b(?:response|data|detail|payload|result)\.project\b')

def main():
    hits = []
    for path in sorted(TEMPLATES.rglob('*.html')):
        for lineno, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if PATTERN.search(line):
                hits.append((path.relative_to(ROOT), lineno, line.strip()))

    for rel, lineno, text in hits:
        print('KEY  {}:{}  {}'.format(rel, lineno, text[:90]))

    print('\n데이터 템플릿 폐기 키(project) {}건'.format(len(hits)))
    print('PASS' if not hits else 'FAIL')
    return 0 if not hits else 1

if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 검사를 돌려 실패를 확인한다**

Run: `.venv/bin/python scripts/verify_response_keys.py`
Expected: **FAIL**, 8건이 나온다. `item.html:170`, `item.html:390`,
`item_list.html:353`, `labeling.html:751`, `image.html:439`, `image.html:440`,
`snapshot.html:469`, `snapshot.html:494` 가 포함되어야 한다.

- [ ] **Step 3: `item.html` 의 검사항목 홈 렌더를 고친다**

`render(detail)` 은 `AjaxUtil.getAsyncData` 콜백에서 **봉투째** 넘어온다
(`item.html:389` 의 `_this.render(response)`). 키 오류와 언래핑 누락이 둘 다 있다.

`app/templates/data/item.html:170` 을 바꾼다.

```javascript
// 이전
let project = detail.project || {};

// 이후 — 봉투 언래핑 + 폐기 키(project) → item
let project = (detail.data || detail).item || {};
```

`app/templates/data/item.html:390` 을 바꾼다.

```javascript
// 이전
let project = response.project || (response.data && response.data.project) || {};

// 이후
let project = (response.data || response).item || {};
```

- [ ] **Step 4: `item_list.html` 의 추가 직후 TypeError 를 고친다**

`app/templates/data/item_list.html:353` 을 바꾼다. 현재는 `response.project` 가
undefined 라 `.id` 접근에서 터진다.

```javascript
// 이전
page.state.selectedId = response.project.id;

// 이후
page.state.selectedId = ((response.data || response).item || {}).id;
```

- [ ] **Step 5: `labeling.html` 의 검사유형 분기를 고친다**

`app/templates/data/labeling.html:751` 을 바꾼다. 현재는 `task_type` 이 항상
undefined 라 분류·이상탐지 검사항목이 객체탐지 UI 로 뜬다.

```javascript
// 이전
let project = response.project || {};

// 이후
let project = (response.data || response).item || {};
```

- [ ] **Step 6: `image.html` 의 안내·스킵 플래그를 고친다**

`app/templates/data/image.html:439-440` 을 바꾼다. 이 파일은 이미 바로 위에서
`let data = response.data || response;` 로 봉투를 풀었으므로 키만 고친다.

```javascript
// 이전
_this.renderGuidance(data.project || {});
_this.skipLabelingAvailable = (data.project || {}).skip_labeling_available !== false;

// 이후
_this.renderGuidance(data.item || {});
_this.skipLabelingAvailable = (data.item || {}).skip_labeling_available !== false;
```

- [ ] **Step 7: `snapshot.html` 의 Export 포맷 분기를 고친다**

`app/templates/data/snapshot.html` 의 `:469` 와 `:494` 두 곳을 바꾼다. 두 곳은
같은 문자열이므로 하나씩 확인하며 바꾼다.

```javascript
// 이전
response.project && response.project.task_type,

// 이후
(response.data || response).item && (response.data || response).item.task_type,
```

- [ ] **Step 8: 검사를 다시 돌려 통과를 확인한다**

Run: `.venv/bin/python scripts/verify_response_keys.py`
Expected: **PASS**, `폐기 키(project) 0건`

- [ ] **Step 9: 검사항목 홈이 실제로 채워지는지 브라우저로 확인한다**

서버를 띄운다.

```bash
.venv/bin/python manage.py runserver 127.0.0.1:8123 --noreload &
```

`http://127.0.0.1:8123/gui/wm_data_item_detail/?project=3` 에 admin 으로 접속해
아래를 **눈으로 확인**한다. 고치기 전에는 전부 비어 있었다.

| 확인 | 기대값 (seed_demo 기준) |
|---|---|
| 검사항목 이름 | `표면 스크래치` |
| 작업 유형 | `객체 탐지` |
| 전체 이미지 | `2` |
| 검사항목 배정 인원 | 3명이 나온다 (`없습니다` 가 아니다) |
| 라벨 클래스 | 2개가 나온다 |
| `검사항목 편집` 버튼 | 보인다 (이전에는 `hidden`) |

- [ ] **Step 10: 공통 검증과 커밋**

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
node scripts/verify_screen_js.js
.venv/bin/python scripts/verify_response_keys.py

git add app/templates/data/item.html app/templates/data/item_list.html \
        app/templates/data/labeling.html app/templates/data/image.html \
        app/templates/data/snapshot.html scripts/verify_response_keys.py
git commit -m "$(cat <<'MSG'
fix: 폐기된 응답 키 project 를 읽어 화면이 비던 8곳 수정

§1.6 검사항목 단일화 때 서버 응답 키를 project 에서 item 으로 바꿨으나
템플릿이 따라오지 않았다. 서버는 item 만 내보내므로 response.project 는
항상 undefined 였고, 화면이 오류 없이 조용히 비었다.

검사항목 홈은 화면 전체가 비어 있었다(이름·통계·배정 인원·라벨 클래스·
스냅샷·최근 데이터·편집 버튼). item.html:170 은 키뿐 아니라 봉투 언래핑도
빠져 있어 둘 다 고쳤다.

그 밖에 고친 것:
- 검사항목 추가 직후 response.project.id 접근에서 나던 TypeError
- 라벨링 화면의 검사유형 분기가 항상 객체탐지로 떨어지던 문제
- 데이터 목록의 업로드 안내 누락과 skip_labeling_available 폴백
- 스냅샷 Export 포맷 분기에 undefined 가 들어가던 문제

scripts/verify_response_keys.py 로 재발을 막는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 2: 내정보 모달 이중 프레임·버튼 잘림 (B-1)

`modal.open()` 이 자체 헤더(제목 + 닫기)를 그리는데, iframe 으로 뜨는
`myinfo.html` 도 자기 `<header>` 를 그려 프레임이 두 겹이 된다. 그리고
`height: 500` 이 고정이라 저장/닫기 버튼이 아래로 잘린다.

**Files:**
- Modify: `app/templates/page/account/myinfo.html:6-10`
- Modify: `app/templates/app/index.html:1230-1238`

**Interfaces:**
- Consumes: 없음
- Produces: 없음

- [ ] **Step 1: 고치기 전 상태를 눈으로 확인한다**

서버를 띄우고 admin 으로 로그인한 뒤 우측 상단 톱니바퀴 → `내정보` 를 연다.
**빨간 헤더바가 두 겹**이고 아래쪽 `저장`·`닫기` 버튼이 **잘려 있다**는 것을
확인한다. 이 상태가 기준이다.

- [ ] **Step 2: 안쪽 페이지의 중복 헤더를 지운다**

`app/templates/page/account/myinfo.html` 의 6~10행에서 `<header>` 블록만
지운다. 바깥 `modal.open()` 이 제목과 닫기 버튼을 제공한다.

```html
<!-- 이전 -->
<div class="ifarm-popup">
  <header class="d-flex justify-content-between align-items-center">
    <h4 data-commonCd="내정보">내정보</h4>
    <button type="button" class="btn-close" id="modal-close" data-bs-dismiss="modal" aria-label="Close"></button>
  </header>
    <div class="table_box">

<!-- 이후 -->
<div class="ifarm-popup">
    <div class="table_box">
```

- [ ] **Step 3: 바깥 모달에 제목을 주고 높이를 늘린다**

`app/templates/app/index.html:1230` 의 `modal.open` 호출을 바꾼다.
`modal.open` 은 `title` 을 받아 `_resolveTitle()` 로 i18n 처리한 뒤
`<h5 class="modal-title">` 에 넣는다(`common.js:465`).

높이 500 은 폼 + 비밀번호 규칙 6줄 + 버튼을 담지 못한다. 640 으로 올린다.

```javascript
// 이전
modal.open({
    width: 400,
    height: 500,
    iframe: {

// 이후
modal.open({
    width: 400,
    height: 640,
    title: '내정보',
    iframe: {
```

- [ ] **Step 4: 삭제한 헤더의 닫기 버튼을 참조하는 JS 가 남아 있는지 확인한다**

`myinfo.html:128` 이 `#modal-close` 를 셀렉터에 포함한다. 그 요소는 이제 없다.
jQuery 는 없는 셀렉터에 바인딩해도 조용히 넘어가므로 동작은 깨지지 않지만,
`#modal-close-button`(푸터의 닫기)은 남아 있어야 한다. 아래를 확인한다.

Run: `grep -n "modal-close" app/templates/page/account/myinfo.html`
Expected: `#modal-close-button` 만 남고(60~61행 푸터 + 128행 핸들러),
`id="modal-close"` 를 가진 요소는 없다.

핸들러의 셀렉터에서 쓰지 않는 `#modal-close, ` 부분을 지운다.

```javascript
// 이전
$('#modal-close, #modal-close-button, [data-bs-dismiss="modal"]').on('click', function (e) {

// 이후
$('#modal-close-button, [data-bs-dismiss="modal"]').on('click', function (e) {
```

- [ ] **Step 5: 브라우저로 확인한다**

서버를 다시 띄우고 `내정보` 를 연다.

| 확인 | 기대 |
|---|---|
| 헤더바 | **한 겹**. 제목이 `내정보` |
| 저장·닫기 버튼 | 잘리지 않고 전부 보인다 |
| 닫기 버튼 | 눌러서 모달이 닫힌다 |
| 우측 상단 × | 눌러서 모달이 닫힌다 |

- [ ] **Step 6: 공통 검증과 커밋**

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
node scripts/verify_screen_js.js

git add app/templates/page/account/myinfo.html app/templates/app/index.html
git commit -m "$(cat <<'MSG'
fix: 내정보 모달의 이중 헤더와 잘리던 버튼 수정

modal.open() 이 자체 헤더(제목 + 닫기)를 그리는데 iframe 으로 뜨는
myinfo.html 도 자기 header 를 그려 빨간 헤더바가 두 겹으로 보였다.
안쪽 중복 헤더를 지우고 바깥 모달에 title 을 넘긴다.

높이 500 은 폼과 비밀번호 규칙 6줄, 버튼을 담지 못해 저장·닫기 버튼이
아래로 잘려 있었다. 640 으로 올렸다.

지운 헤더의 #modal-close 를 참조하던 셀렉터도 함께 정리했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 3: 비밀번호 규칙이 입력 전부터 전부 × (B-5)

규칙 6줄을 그릴 때 아이콘을 `uil-times`(×, 빨강)로 **하드코딩**한다. 그래서
창을 열자마자 아무것도 입력하지 않았는데 6줄이 전부 빨간 ×로 보인다.

**Files:**
- Modify: `app/templates/page/account/myinfo.html:250-280` (목록 생성), `:290-310` (상태 갱신)
- Modify: `app/static/assets/css/SF-Custom.css` (중립 상태 스타일 추가)

**Interfaces:**
- Consumes: Task 2 가 같은 파일을 고친다. **Task 2 를 먼저 끝내고 시작한다**
- Produces: 없음

- [ ] **Step 1: 고치기 전 상태를 눈으로 확인한다**

`내정보` 를 연다. 비밀번호 칸에 **아무것도 입력하지 않은 상태**에서 규칙 6줄이
전부 빨간 ×로 표시되는 것을 확인한다.

- [ ] **Step 2: 목록을 중립 상태로 그린다**

`app/templates/page/account/myinfo.html` 의 `criteriaList.append(...)` 6곳에서
`uil-times` 를 `uil-minus criteria-idle` 로 바꾼다. 6줄 모두 바꾼다.

```javascript
// 이전 (6곳)
criteriaList.append(`<li id="lengthCriteria"><i class="uil uil-times"></i> 비밀번호는 최소 ${passOption.length[0]}자 이상이어야 합니다.</li>`);
criteriaList.append('<li id="lowerCriteria"><i class="uil uil-times"></i> 최소 한 개의 소문자를 포함해야 합니다.</li>');
criteriaList.append('<li id="upperCriteria"><i class="uil uil-times"></i> 최소 한 개의 대문자를 포함해야 합니다.</li>');
criteriaList.append('<li id="numericCriteria"><i class="uil uil-times"></i> 최소 한 개의 숫자를 포함해야 합니다.</li>');
criteriaList.append('<li id="specialCriteria"><i class="uil uil-times"></i> 최소 한 개의 특수문자를 포함해야 합니다.</li>');
criteriaList.append('<li id="matchCriteria"><i class="uil uil-times"></i> 비밀번호가 일치해야 합니다.</li>');

// 이후 — uil-times 를 uil-minus criteria-idle 로 (6곳 모두)
criteriaList.append(`<li id="lengthCriteria"><i class="uil uil-minus criteria-idle"></i> 비밀번호는 최소 ${passOption.length[0]}자 이상이어야 합니다.</li>`);
criteriaList.append('<li id="lowerCriteria"><i class="uil uil-minus criteria-idle"></i> 최소 한 개의 소문자를 포함해야 합니다.</li>');
criteriaList.append('<li id="upperCriteria"><i class="uil uil-minus criteria-idle"></i> 최소 한 개의 대문자를 포함해야 합니다.</li>');
criteriaList.append('<li id="numericCriteria"><i class="uil uil-minus criteria-idle"></i> 최소 한 개의 숫자를 포함해야 합니다.</li>');
criteriaList.append('<li id="specialCriteria"><i class="uil uil-minus criteria-idle"></i> 최소 한 개의 특수문자를 포함해야 합니다.</li>');
criteriaList.append('<li id="matchCriteria"><i class="uil uil-minus criteria-idle"></i> 비밀번호가 일치해야 합니다.</li>');
```

- [ ] **Step 3: 입력이 비어 있으면 중립을 유지하도록 갱신 함수를 고친다**

갱신 함수(`updateCriteria` 류, `:290` 부근)는 현재 아이콘 클래스를
`removeClass('uil-times uil-check')` 후 둘 중 하나를 붙인다. 중립 클래스를
목록에 더하고, **입력이 비었으면 중립으로 되돌린다.**

함수 본문 맨 앞에 아래를 넣는다. `password` 는 그 함수가 이미 쓰는 변수명이다.

```javascript
let $icons = $('.password-criteria li i');
if (!password) {
    $icons.removeClass('uil-times uil-check').addClass('uil-minus criteria-idle');
    return;
}
$icons.removeClass('uil-minus criteria-idle');
```

그리고 기존의 각 `removeClass('uil-times uil-check')` 호출을
`removeClass('uil-times uil-check uil-minus criteria-idle')` 로 바꾼다.
해당 줄은 `:297`, `:300`, `:303` 등 6곳이다. 아래처럼 한 번에 찾는다.

Run: `grep -n "removeClass('uil-times uil-check')" app/templates/page/account/myinfo.html`

- [ ] **Step 4: 중립 상태 스타일을 더한다**

`app/static/assets/css/SF-Custom.css` 맨 뒤에 붙인다. 기존 규칙은 건드리지
않는다.

```css
/* 비밀번호 규칙 — 아직 입력하지 않은 상태. 빨간 ×로 보이면 오류로 읽힌다. */
.password-criteria .criteria-idle {
    color: #a9a9a9;
}
```

- [ ] **Step 5: 브라우저로 확인한다**

| 상태 | 기대 |
|---|---|
| 창을 연 직후 | 6줄 전부 **회색 `-`**. 빨간 × 가 없다 |
| `a` 한 글자 입력 | 소문자 규칙만 ✓, 나머지는 빨간 × |
| `Abcd1234!` 입력 | 일치 규칙을 뺀 5줄이 ✓ |
| 확인란에 같은 값 입력 | 6줄 전부 ✓ |
| 입력을 전부 지움 | 6줄 전부 회색 `-` 로 되돌아간다 |

- [ ] **Step 6: 공통 검증과 커밋**

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
node scripts/verify_screen_js.js

git add app/templates/page/account/myinfo.html app/static/assets/css/SF-Custom.css
git commit -m "$(cat <<'MSG'
fix: 비밀번호 규칙이 입력 전부터 전부 빨간 X 로 보이던 문제 수정

규칙 6줄을 그릴 때 아이콘을 uil-times(X)로 하드코딩해, 창을 열자마자
아무것도 입력하지 않은 상태에서 6줄이 전부 오류처럼 보였다.

아직 평가하지 않은 상태를 회색 - 로 따로 두고, 입력이 비면 그 상태로
되돌아가게 했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 4: 죽은 톱니바퀴와 도달 불가 템플릿 (B-3)

톱니바퀴는 그리드가 만드는 것이 아니라 템플릿마다 손으로 넣는다. 9개 화면 중
7개는 톱니바퀴와 `columns_setting.html` include 가 짝을 이루는데, `user.html` 은
버튼만 있어 눌러도 반응이 없고 `usergroup.html` 은 include 만 있어 도달할 수 없다.

**Files:**
- Modify: `app/templates/system/user.html` (include 추가)
- Modify: `app/templates/system/usergroup.html` (톱니바퀴 추가)

**Interfaces:**
- Consumes: 없음
- Produces: 없음

- [ ] **Step 1: 짝이 맞는 화면의 생김새를 본다**

기준으로 삼을 화면을 읽는다. 톱니바퀴 버튼 마크업과 include 위치를 그대로
따른다.

```bash
grep -n "uil-cog" -B3 -A3 app/templates/system/login_log.html
grep -n "columns_setting" app/templates/system/login_log.html
```

- [ ] **Step 2: 고치기 전 상태를 확인한다**

- `http://127.0.0.1:8123/gui/wm_user/` — 그리드 우상단 톱니바퀴를 누른다.
  **아무 일도 일어나지 않는다**
- `http://127.0.0.1:8123/gui/wm_user_group/` — 톱니바퀴가 **없다**

- [ ] **Step 3: `user.html` 에 컬럼설정 템플릿을 include 한다**

`app/templates/system/user.html` 의 `{% block content %}` 끝(닫는
`{% endblock %}` 바로 앞)에 넣는다. `login_log.html:59` 와 같은 자리다.

```django
{% include '../common/columns_setting.html' %}
```

- [ ] **Step 4: `usergroup.html` 에 톱니바퀴를 더한다**

`app/templates/system/usergroup.html` 의 그리드 제목줄 우측 버튼 묶음에,
`login_log.html` 에서 본 것과 같은 마크업으로 톱니바퀴를 넣는다. 엑셀
내보내기 버튼이 이미 있으면 그 **뒤**에 둔다(다른 7개 화면의 순서와 같게).

```html
<button type="button" class="btn rounded-pill btn-icon">
    <i class="uil uil-cog"></i>
</button>
```

> 버튼의 클래스·아이콘은 Step 1 에서 읽은 `login_log.html` 의 것을 그대로
> 쓴다. 이 블록과 다르면 **읽은 쪽을 따른다.**

- [ ] **Step 5: 두 화면에서 컬럼설정이 열리는지 확인한다**

| 화면 | 기대 |
|---|---|
| `wm_user` | 톱니바퀴 → `컬럼 설정` 모달이 열리고 사용자목록 컬럼이 나온다 |
| `wm_user_group` | 톱니바퀴가 보이고, 눌러 모달이 열린다 |

모달 안에서 컬럼 하나의 `표시` 토글을 끄고 `저장` → 그리드에서 그 컬럼이
사라지는지까지 확인한다.

- [ ] **Step 6: 톱니바퀴와 include 가 짝이 맞는지 전수 확인한다**

```bash
diff <(grep -rl "uil-cog" app/templates --include=*.html | sort) \
     <(grep -rl "columns_setting.html" app/templates --include=*.html | sort)
```

Expected: **출력 없음** (두 목록이 같다)

- [ ] **Step 7: 공통 검증과 커밋**

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
node scripts/verify_screen_js.js

git add app/templates/system/user.html app/templates/system/usergroup.html
git commit -m "$(cat <<'MSG'
fix: 눌러도 반응 없던 사용자 관리 컬럼설정과 도달 불가하던 사용자그룹 템플릿

컬럼설정 톱니바퀴는 그리드가 만드는 것이 아니라 템플릿마다 손으로 넣는다.
9개 화면 중 7개는 톱니바퀴와 columns_setting.html include 가 짝을 이루는데
사용자 관리는 버튼만, 사용자그룹은 include 만 있었다.

사용자 관리에 include 를, 사용자그룹에 톱니바퀴를 더해 짝을 맞췄다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 5: 메뉴권한 화면이 진입 시 비어 있다 (B-6)

화면이 뜰 때 `fillSelectOptions` 로 그룹 콤보를 **비동기로** 채우는데, 채운 뒤
조회를 하지 않는다. `change` 핸들러는 사용자가 직접 바꿔야만 돈다. 그래서
콤보에는 `관리자` 가 선택돼 보이는데 그리드는 `데이터가 없습니다` 다.

**Files:**
- Modify: `app/templates/system/usergroup_menu.html:115`

**Interfaces:**
- Consumes: 없음
- Produces: 없음

- [ ] **Step 1: 고치기 전 상태를 확인한다**

`http://127.0.0.1:8123/gui/wm_user_group_menu/` 에 들어간다.
**사용자 그룹에 `관리자` 가 선택돼 있는데 그리드는 비어 있다.** 조회 버튼을
누르면 그제야 나온다. 이 상태가 기준이다.

- [ ] **Step 2: 콤보를 채운 뒤 1회 조회하도록 고친다**

`AjaxUtil.fillSelectOptions` 는 8번째 인자로 완료 콜백 `fn_done` 을 받는다
(`common.js:1595`).

```javascript
fillSelectOptions: function ($combo, combo_type, null_option, selected_value,
                            condition1, condition2, condition3, fn_done)
```

`app/templates/system/usergroup_menu.html:115` 를 바꾼다. 쓰지 않는 조건 인자
3개는 `null` 로 채운다.

```javascript
// 이전
AjaxUtil.fillSelectOptions($('#cboUserGroup'), 'user_group', '', '');
AjaxUtil.fillSelectOptions($('#cboMenuFolder'), 'menu_folder', 'all', '');

// 이후 — 그룹 콤보가 채워진 뒤에 한 번 조회한다.
// 메뉴폴더 콤보도 조회에 쓰이므로 그 쪽이 먼저 채워지고 나서 조회한다.
AjaxUtil.fillSelectOptions($('#cboMenuFolder'), 'menu_folder', 'all', '', null, null, null, function () {
    AjaxUtil.fillSelectOptions($('#cboUserGroup'), 'user_group', '', '', null, null, null, function () {
        _this.searchDataBind();
    });
});
```

> `_this` 는 이 함수가 이미 잡아 둔 변수다. 없다면 함수 맨 앞에
> `let _this = this;` 를 넣는다 — Ajax 콜백 안에서 `this` 를 쓰면 안 된다
> (Global Constraints).

- [ ] **Step 3: 빈 `group_id` 가드가 여전히 동작하는지 확인한다**

`app/views/system/usergroupmenu.py` 의 가드는 **그대로 둔다.** 콤보가 채워지기
전에 다른 경로로 빈 값이 들어올 수 있다.

```bash
# 빈 값 → 200 + 빈 목록 (500 이 아니다)
curl -sS -b <쿠키> -o /dev/null -w "%{http_code}\n" \
  "http://127.0.0.1:8123/api/system/usergroupmenu?action=read&group_id=&folder_id="
```

Expected: `200`

- [ ] **Step 4: 브라우저로 확인한다**

`wm_user_group_menu` 에 다시 들어간다.

| 확인 | 기대 |
|---|---|
| 진입 직후 | 그리드에 **메뉴 트리가 보인다** (`데이터가 없습니다` 가 아니다) |
| 사용자 그룹 변경 | 선택한 그룹의 권한으로 다시 그려진다 |
| 읽기·쓰기 체크 | 눌러서 토글된다 |
| 서버 로그 | 500 이 없다 |

- [ ] **Step 5: 공통 검증과 커밋**

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
node scripts/verify_screen_js.js

git add app/templates/system/usergroup_menu.html
git commit -m "$(cat <<'MSG'
fix: 메뉴권한 화면이 진입 직후 비어 있던 문제 수정

화면이 뜰 때 그룹 콤보를 비동기로 채우고 나서 조회를 하지 않았다.
change 핸들러는 사용자가 직접 바꿔야만 돌기 때문에, 콤보에는 관리자가
선택돼 보이는데 그리드는 비어 있었다.

fillSelectOptions 의 완료 콜백으로 콤보 두 개가 채워진 뒤 한 번 조회한다.
빈 group_id 가드는 다른 경로로 빈 값이 들어올 수 있어 그대로 둔다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 6: 라벨링 화면이 뷰포트 높이를 쓰지 않는다 (B-4)

1920 × 911 에서 실측하면 세로 스크롤은 이미 없고, `main` 이 설 수 있는
762px 중 **520px 만 써서 312px 가 빈다.** 작업 툴 화면인데 가장 아깝다.

**Files:**
- Modify: `app/static/data/layout.css` 또는 `app/static/data/aidatahub.css` (Step 2 에서 결정)

**Interfaces:**
- Consumes: 없음
- Produces: 없음

- [ ] **Step 1: 셸 탭 안에서 현재 수치를 측정한다**

**단독 페이지가 아니라 셸의 iframe 탭에서 잰다.** 실제 사용 경로가 그쪽이고
상단바 50px 이 더 빠진다.

브라우저를 1920 × 911 로 두고 admin 으로 로그인한 뒤, 좌측 메뉴에서
`데이터 관리` → 검사항목 → `라벨링 작업` 으로 들어간다. DevTools 콘솔에서:

```javascript
const d = document.documentElement;
console.log({
  viewport: [innerWidth, innerHeight],
  yScroll: d.scrollHeight > d.clientHeight,
  body: Math.round(document.body.getBoundingClientRect().height),
  main: (() => { const e = document.querySelector('main');
                 const r = e.getBoundingClientRect();
                 return { h: Math.round(r.height), top: Math.round(r.top) }; })(),
  crudShell: getComputedStyle(d).getPropertyValue('--crud-shell-height').trim(),
});
```

측정값을 적어 둔다. 단독 페이지 기준 참고값: `main` 520px / `top` 79 /
`--crud-shell-height: calc(100vh - 100px)`.

- [ ] **Step 2: 높이 식을 정한다**

높이 식이 두 벌이다 — 데이터 쪽 `--crud-shell-height: calc(100vh - 100px)`,
MES 쪽 `calc(100vh - var(--ct-topbar-height))`(50px). **이 작업에서 통합하지
않는다**(Phase 1 범위). 라벨링 화면만 남는 공간을 채우게 한다.

`main` 이 `top` 아래 남는 높이를 전부 차지하도록 `flex` 로 늘린다. 선택한
파일과 셀렉터는 Step 1 에서 읽은 실제 DOM 에 맞춘다. 기본 방향:

```css
/* 라벨링 작업 화면 — 작업 영역이 남는 세로 공간을 모두 차지한다.
   세로 스크롤은 만들지 않는다(최소 사양 1920x911). */
.labeling-page main {
    flex: 1 1 auto;
    min-height: 0;   /* flex 자식이 넘칠 때 줄어들 수 있게 한다 */
}
```

> `min-height: 0` 이 없으면 flex 자식이 콘텐츠 크기 아래로 줄지 않아 스크롤이
> 생긴다. 이 한 줄이 핵심이다.

- [ ] **Step 3: 1920 × 911 에서 확인한다**

Step 1 의 측정을 다시 돌린다.

| 확인 | 기대 |
|---|---|
| `yScroll` | `false` |
| `main` 높이 | 남는 공간을 모두 차지한다 (빈 영역 없음) |
| 좌측 이미지 목록 | 잘리지 않는다 |
| 가운데 캔버스 | 커진 영역만큼 넓어진다 |
| 우측 결함 패널 | 잘리지 않는다 |

- [ ] **Step 4: 더 높은 해상도에서도 스크롤이 생기지 않는지 확인한다**

브라우저를 2560 × 1440 으로 바꿔 같은 화면을 연다.

Expected: 세로 스크롤 없음, 빈 영역 없음

- [ ] **Step 5: 다른 데이터 화면이 틀어지지 않았는지 확인한다**

같은 CSS 파일을 쓰는 화면들을 눈으로 확인한다.

```
/gui/wm_data_item/?project=3
/gui/wm_data_item_detail/?project=3
/gui/wm_data_image/?project=3
/gui/wm_data_review/?project=3
/gui/wm_data_snapshot/?project=3
/gui/wm_data_queue/
```

Expected: 레이아웃 변화 없음. 셀렉터가 라벨링 화면에만 걸렸는지 확인한다.

- [ ] **Step 6: 공통 검증과 커밋**

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
node scripts/verify_screen_js.js

git add app/static/data/layout.css
git commit -m "$(cat <<'MSG'
fix: 라벨링 작업 화면이 세로 공간을 절반만 쓰던 문제 수정

1920x911 에서 재면 세로 스크롤은 없는데 main 이 설 수 있는 762px 중
520px 만 써서 312px 가 비어 있었다. 작업 툴 화면이라 가장 아까운 자리다.

main 을 flex 로 늘려 남는 세로 공간을 채운다. min-height: 0 이 없으면
flex 자식이 콘텐츠 크기 아래로 줄지 않아 스크롤이 생기므로 함께 둔다.

높이 식이 데이터 쪽(calc(100vh - 100px))과 MES 쪽(topbar 50px)으로 두 벌인
것은 그대로 뒀다. 토큰 통합(Phase 1) 범위다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

### Task 7: Phase 0 전체 회귀 확인

6건을 각각 고쳤으니 서로 깨뜨리지 않았는지 전체로 확인한다.

**Files:**
- Create: `scripts/capture_ui.py` (캡처 하네스를 저장소로 들인다)

**Interfaces:**
- Consumes: Task 1 의 `scripts/verify_response_keys.py`
- Produces: `scripts/capture_ui.py` — `python scripts/capture_ui.py <출력폴더>` 로 **25화면**을 캡처하고 4xx·5xx·JS 오류를 함께 센다. Phase 1~4 의 회귀 비교에 쓴다. 모달은 화면마다 여는 방법이 달라(네이티브 `<dialog>` · 자체 `modal.open()` · Bootstrap) 이 스크립트에 넣지 않는다 — 모달 단일화(Phase 2) 뒤에 더한다

- [ ] **Step 1: 캡처 하네스를 저장소에 들인다**

Phase 1 이후 모든 단계가 "직전과 비교"로 검증하므로 스크립트가 저장소에
있어야 한다. `scripts/capture_ui.py` 를 만든다. `playwright` 는 운영 의존성이
아니므로 `requirements.txt` 에 넣지 않는다 — 스크립트 docstring 에 설치법을
적는다.

```python
#!/usr/bin/env python
"""전체 화면·모달을 캡처한다. 디자인 작업의 회귀 비교용.

운영 의존성이 아니다. 쓰기 전에 받는다:

    .venv/bin/pip install playwright
    .venv/bin/python -m playwright install chromium

서버가 떠 있어야 하고 seed_demo 가 돌아 있어야 한다.

    python scripts/capture_ui.py /tmp/ui-before
    python scripts/capture_ui.py /tmp/ui-after
"""
import pathlib
import sys

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASE = 'http://127.0.0.1:8123'

SCREENS = [
    ('01-system', 'wm_user'), ('01-system', 'wm_user_group'),
    ('01-system', 'wm_user_group_menu'), ('01-system', 'wm_multi_language'),
    ('01-system', 'wm_menu_language'), ('01-system', 'wm_prop_master'),
    ('01-system', 'wm_login_log'), ('01-system', 'wm_menu_log'),
    ('01-system', 'wm_system_log'),
    ('02-data', 'wm_data_item'), ('02-data', 'wm_data_queue'),
    ('02-data', 'wm_data_item_detail'), ('02-data', 'wm_data_image'),
    ('02-data', 'wm_data_labeling'), ('02-data', 'wm_data_review'),
    ('02-data', 'wm_data_snapshot'),
    ('03-vision', 'wm_vis_inspection'), ('03-vision', 'wm_vis_client'),
    ('03-vision', 'wm_vis_model'), ('03-vision', 'wm_vis_model_mapping'),
    ('03-vision', 'wm_vis_overlay'),
    ('04-basic', 'wm_code'), ('04-basic', 'wm_company'),
    ('04-basic', 'wm_depart'), ('04-basic', 'wm_unit'),
]


def main():
    if len(sys.argv) < 2:
        print('사용법: python scripts/capture_ui.py <출력폴더>')
        return 2
    out = pathlib.Path(sys.argv[1])
    password = (ROOT / '.admin_pw').read_text(encoding='utf-8').strip()

    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        ctx = browser.new_context(viewport={'width': 1920, 'height': 911},
                                  locale='ko-KR')
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.on('console',
                lambda m: errors.append(m.text) if m.type == 'error' else None)
        page.on('response',
                lambda r: errors.append('HTTP {} {}'.format(r.status, r.url))
                if r.status >= 400 else None)

        page.goto(BASE + '/login/', wait_until='domcontentloaded')
        page.fill('#loginId', 'admin')
        page.fill('#loginPwd', password)
        page.click('#login')
        page.wait_for_url(BASE + '/', timeout=15000)
        page.wait_for_timeout(1200)

        for group, code in SCREENS:
            errors.clear()
            url = '{}/gui/{}/{}'.format(
                BASE, code, '?project=3' if code.startswith('wm_data_') else '')
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=25000)
                page.wait_for_timeout(2800)
            except Exception as ex:
                print('FAIL {:28} {}'.format(code, str(ex)[:60]))
                failures += 1
                continue
            (out / group).mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out / group / (code + '.png')))
            if errors:
                failures += 1
                print('ERR  {:28} {}'.format(code, errors[0][:70]))
            else:
                print('OK   {}'.format(code))

        browser.close()

    print('\n화면 {}개 / 오류 {}건'.format(len(SCREENS), failures))
    print('PASS' if failures == 0 else 'FAIL')
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: 25화면을 캡처해 오류 0건을 확인한다**

서버를 띄운 상태에서:

```bash
.venv/bin/python scripts/capture_ui.py /tmp/ui-phase0-after
```

Expected: **PASS**, `오류 0건`. 4xx·5xx 와 JS 오류가 하나도 없어야 한다. 모달은 이 스크립트가 다루지 않으므로 B-1(내정보)·B-3(컬럼설정)은 Task 2·4 의 눈 확인으로 대신한다.

- [ ] **Step 3: 전체 검증을 돌린다**

```bash
.venv/bin/python manage.py test tests --settings=configurations.test_settings
node scripts/verify_screen_js.js
.venv/bin/python scripts/verify_menu.py
.venv/bin/python scripts/verify_permission_map.py
.venv/bin/python scripts/verify_response_keys.py
```

Expected: 전부 **PASS / OK**

- [ ] **Step 4: e2e 를 돌린다**

3분 30초쯤 걸린다.

```bash
.venv/bin/python -m pytest tests/e2e -q
```

Expected: **58 passed**

- [ ] **Step 5: 서버 로그에 500 이 없는지 확인한다**

e2e 를 돌리는 동안 쌓인 서버 로그를 본다.

```bash
grep -cE "Traceback|\" 500 " <서버로그>
```

Expected: `0`

- [ ] **Step 6: AGENTS.md 의 검증 명령 목록에 새 스크립트를 더한다**

`AGENTS.md` §6 의 검증 블록에 한 줄 넣는다.

```bash
python scripts/verify_response_keys.py        # 템플릿 ↔ 응답 키
```

- [ ] **Step 7: 커밋**

```bash
git add scripts/capture_ui.py AGENTS.md
git commit -m "$(cat <<'MSG'
chore: 화면 캡처 하네스를 저장소에 들이고 검증 목록 갱신

Phase 1 이후 모든 단계가 직전 캡처와 비교하는 방식으로 검증하므로
스크립트가 저장소에 있어야 반복할 수 있다. playwright 는 운영 의존성이
아니라 requirements.txt 에 넣지 않고 docstring 에 설치법을 적었다.

AGENTS.md 검증 명령에 verify_response_keys.py 를 더했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
MSG
)"
```

---

## 완료 기준

- [ ] 25화면 캡처에서 4xx·5xx·JS 오류 **0건**
- [ ] 단위테스트 통과, e2e 58건 통과
- [ ] `verify_screen_js` · `verify_menu` · `verify_permission_map` · `verify_response_keys` 전부 PASS
- [ ] 검사항목 홈에 이름·통계·배정 인원·라벨 클래스가 **보인다**
- [ ] 내정보 모달의 헤더가 **한 겹**이고 버튼이 잘리지 않는다
- [ ] 비밀번호 규칙이 입력 전 회색 `-` 다
- [ ] `wm_user`·`wm_user_group` 둘 다 컬럼설정이 열린다
- [ ] 메뉴권한 화면이 진입 직후 트리를 보여준다
- [ ] 라벨링 화면이 1920 × 911 에서 세로 스크롤 없이 가득 찬다
