# UI 디자인 시스템 정리

세 프로젝트를 통합하면서 **화면의 디자인 언어는 통합되지 않았다.** 이 문서는
무엇이 어긋나 있는지와 어떤 순서로 맞출지를 정한다.

- 작성: 2026-10-02
- 근거: 전체 화면 25개 + 모달 8종 캡처 39장, CSS 실측
- 선행 결정: [USER_DECISIONS.md](USER_DECISIONS.md) §1.6 (검사항목 단일화)

## [1] 결정

| # | 결정 | 근거 |
|---|---|---|
| D-1 | **기준 디자인 언어는 MES(빨강)다.** 데이터 관리·비전 화면을 여기로 흡수한다 | 25화면 중 18개가 이미 MES 언어다. 셸·WeZonGrid 도 그렇다 |
| D-2 | **색·버튼·모달만 통일한다. 레이아웃은 건드리지 않는다** | 데이터 화면의 2단 목록+상세, 라벨링 캔버스는 작업 특성에 맞는 구조다. 그리드 패턴으로 바꾸면 템플릿·JS 를 다시 쓰는 일이 된다 |
| D-3 | **버그를 먼저 정리하고 디자인에 들어간다** | 버그 6건은 디자인 결정과 무관하다. 고쳐두면 디자인 작업의 기준 화면이 깨끗해진다 |
| D-4 | **브랜드는 YEST.** 펼친 상태는 `마크 + YEST` **가로 조합**, 접은 상태는 **마크만** | §3 |
| D-5 | **영문 kicker 를 한글로 바꾼다.** `프로젝트`/`PROJECT` 는 폐기 용어이고 `검사항목` 으로 간다 | `USER_DECISIONS.md` §1.6 과 일치시킨다 |
| D-6 | **라벨링 화면은 세로 스크롤 없이 가득 채운다.** 최소 사양 **1920 × 911** | §6 Phase 0 B-4 |

D-1 에 따르는 전제: **빨강의 역할을 분리한다.** 현재 `--ct-primary: #ea1b1b` 하나가
조회·저장·삭제·경고를 모두 맡고 있어 위험한 동작을 구분할 수단이 없다. §5 에서
형태로 분리한다.

## [2] 지금 상태

### 2.1 토큰 네임스페이스가 3개이고 서로 모른다

| 네임스페이스 | 선언 위치 | 개수 | 쓰는 곳 |
|---|---|---|---|
| `--ct-*` | `SF-Custom.css` `:root[data-bs-theme=light]` | 36 | MES 13화면 + 셸 (Bootstrap 테마 변수) |
| `--ink`·`--teal`·`--navy` 등 | `data/main.css` `:root` | 13 | 데이터 관리 7화면 |
| `--wzg-*` | `wezongrid.css` (문서화된 커스터마이즈 지점) | 76 | 모든 그리드 |

**세 계열 모두 이미 변수화되어 있다.** 연결만 안 돼 있다. 그래서 이 작업은
"토큰을 도입"하는 일이 아니라 **단일 원천을 두고 기존 세 네임스페이스가 거기서
파생되게 만드는 일**이다. 그만큼 범위가 작다.

실측 색:

```
MES   #ea1b1b (25회, --ct-primary) · #2e2e31 (13) · #242424 (9)
      #d8d8d8 / #d7d7d7 (27, 거의 같은 회색 둘) · #edeff1 (11) · #666 (11)
      #ffba00 (3) · #6451f3 (3, Bootstrap .btn-info/.text-info 오버라이드 — 미사용)
데이터 --teal #16a5a3 · --navy #17395f · --ink #172331 · --paper #f4f7f8
      --orange #d98b27 · --red #bd5a4d
```

`#d8d8d8`/`#d7d7d7`, `#fff`/`#ffffff` 처럼 거의 같은 값이 병존하는 것은 토큰
없이 손으로 쌓은 흔적이다.

### 2.2 타이포가 다르다

- MES: `--ct-font-sans-serif: 'Pretendard', 'Open Sans', ...`
- 데이터: `font-family: Inter, Pretendard, 'Noto Sans KR', ...` — **Inter 가 앞**

같은 제품에서 본문 서체가 화면마다 바뀐다.

**정정(Phase 1 구현 중 실측).** 위 두 번째 줄은 선언을 읽은 것이고 실제와
다르다. 그 선언은 `data/main.css` 의 `:root` 에 있는데 `app.min.css` 가
`body { font-family: ... }` 로 직접 잡아 상속을 이긴다. 즉 **데이터 화면은
Inter 도 Pretendard 도 아닌 벤더 기본 `Nunito` 로 그려지고 있었다.** 아무도
의도하지 않은 세 번째 서체다. Inter 는 `@font-face` 도 폰트 파일도 없어
어차피 적용될 수 없었다. 실측 방법은 선언이 아니라 `getComputedStyle(body)`
다. Phase 1 에서 양쪽 모두 Pretendard 로 맞췄다.

세 번째 서체가 하나 더 있다 — `--wzg-font-family: 'Malgun Gothic'`. 모든
그리드가 이걸 쓴다. Phase 1 에서는 건드리지 않았다(아래 Q-4 종결 참조).

### 2.3 모달이 3종 구현, 백드롭 동작이 3종

| 구현 | 쓰는 곳 | 백드롭 |
|---|---|---|
| 네이티브 `<dialog>` | 데이터 관리 6종 | **없음** — 뒤 화면이 그대로 보여 모달로 읽히지 않는다 |
| 자체 `modal.open()` | 그리드 컬럼설정, 내정보 | **없음** |
| Bootstrap Modal | 검사 Client API Key | **화면 전체가 빨갛게 덮인다** |

**정정(Phase 2 구현 중 실측).** 위 표의 "백드롭 없음" 두 줄은 셸 안에서 본
현상을 구현 탓으로 적은 것이다. 실제는 이렇다.

- 네이티브 `<dialog>` 는 `data/main.css` 에 `.form-dialog::backdrop` 이 있고
  색도 적절했다. **없는 것이 아니라 iframe 안만 덮는다**
- 자체 `modal.open()` 은 `SF-Custom.css` 가 `transparent !important` 로
  **강제로 지우고 있었다**. Phase 2 에서 되살렸다
- 화면을 iframe 탭으로 띄우는 셸 구조상 **어떤 백드롭도 프레임 경계를 넘지
  못한다.** 모달이 열린 채 상단바·좌측 메뉴를 누를 수 있다(3계열 전부
  `elementFromPoint` 로 확인). 고치려면 부모 프레임과의 교차 프레임 연동이
  필요하다 → **범위 밖**(사용자 결정)

계열이 하나 더 있었다 — `Alert`/`Confirm`(`common.js`)이 Bootstrap Modal 을
쓰고 **호출 지점이 123곳**(`Alert.alert` 89 · `Alert.confirm` 34)이다. 제품에서
가장 자주 보이는 모달인데 위 표에 없었다.

### 2.4 버그 6건

디자인 이전의 문제다. Phase 0 에서 처리한다.

| # | 증상 | 위치 |
|---|---|---|
| B-1 | 내정보 모달이 **이중 프레임** — 빈 빨간 헤더바 안에 또 헤더바. 저장/닫기 버튼이 아래로 잘린다 | `page/account/myinfo.html` |
| B-2 | **응답 키가 `project` → `item` 으로 바뀌었는데 템플릿 8곳이 따라오지 않았다.** 검사항목 홈은 화면 전체가 빈다 | `data/` 5개 템플릿 |
| B-3 | 톱니바퀴 ↔ 컬럼설정 템플릿 **불일치**. 톱니바퀴는 그리드가 아니라 템플릿마다 손으로 넣는다. 7개는 짝이 맞고, `user.html` 은 버튼만 있어 눌러도 반응이 없고 `usergroup.html` 은 템플릿만 있어 도달할 수 없다 | `system/user.html`, `system/usergroup.html` |
| B-4 | 라벨링 화면이 **뷰포트 높이를 쓰지 않는다**. 작업 영역이 600px 에서 끝나고 하단 40% 가 빈다 | `data/labeling.html` |
| B-5 | 비밀번호 규칙 6개가 **입력 전부터 전부 빨간 ×** | `page/account/myinfo.html` |
| B-6 | 메뉴권한 화면이 진입 시 빈 화면. 그룹 콤보가 채워진 뒤 **재조회하지 않는다** | `system/usergroup_menu.html` |

B-6 은 빈 `group_id` 500 을 막은 가드(`app/views/system/usergroupmenu.py`)의 결과다.
가드는 맞고, 콤보를 채운 뒤 1회 재조회가 빠져 있다.

**B-2 는 처음 본 것보다 크다.** 처음에는 "통계 타일 4개가 빈다"로 적었으나,
추적해보니 §1.6 검사항목 단일화 때 **서버 응답 키를 `project` 에서 `item` 으로
바꾸면서 템플릿이 따라오지 않은 것**이었다. 서버는 6곳 전부 `item` 을 내보내고
`project` 를 내보내는 곳이 없다. 템플릿은 8곳(줄 기준)에서 `project` 를 읽는다.

| 위치 | 읽는 것 | 실제 증상 |
|---|---|---|
| `item.html:170` | `detail.project` | **검사항목 홈 전체가 빈다** — 이름·통계 4개·배정 인원·라벨 클래스·스냅샷·최근 데이터·편집 버튼 |
| `item_list.html:353` | `response.project.id` | 검사항목 추가 직후 **TypeError** |
| `labeling.html:751` | `response.project.task_type` | `isClassification`·`isAnomalyDetection` 가 항상 false → 분류·이상탐지 검사항목이 객체탐지 UI 로 뜬다 |
| `image.html:439-440` | `data.project` | 업로드 안내 누락, `skip_labeling_available` 가 항상 true 로 폴백 |
| `snapshot.html:469,494` | `response.project.task_type` | Export 포맷 분기에 `undefined` 가 들어간다 |
| `item.html:390` | `response.project.permissions` | 설정 저장 뒤 편집 창이 다시 열리지 않는다 |

`item.html:170` 은 키뿐 아니라 **봉투 언래핑도 빠졌다.** `render(response)` 로
`{ok, message, data}` 를 통째로 넘기고 `detail.project` 를 읽는다. 다른 화면이
쓰는 관용구는 `let data = response.data || response;` 다(`image.html:433`).

### 2.5 용어·브랜딩

- 셸 로고가 아직 **`We:ZON MES`**
- 데이터 화면 kicker 가 영문(`PROJECT HOME`·`DATA LIST`·`NEW PROJECT`)인데 스냅샷만 한글(`확정된 버전`)
- §1.6 에서 `검사항목` 으로 통일했으나 표시 문자열에 **`PROJECT` 가 남아 있다**
- 제목 자체가 혼종: **`데이터셋 Snapshot`**
- 어투 3종 혼재: `아직 표시한 곳이 없어요` / `데이터가 없습니다`
- 검사 Client 화면의 `API Key 재발급`·`사용/중지` 가 **버튼이 아니라 맨 텍스트**로 빨간 버튼 둘 사이에 있다

## [3] 브랜드 로고

원본 `docs/logo/yest_logo_original.png` 는 **세로 조합**이다. 실측하면 전체 99 × 100(거의 정사각),
그 안에서 마크 99 × 68 · 간격 8 · 워드마크 `YEST` 97 × 24 다.

셸의 로고 슬롯은 **높이 19px** 이다(`logo-dark.png` 153 × 19). 세로 조합을 그대로
19px 에 넣으면 폭도 19px 이 되고 워드마크는 4.5px 로 뭉개진다. 실제로 만들어
비교했다.

| 안 | 크기(19px 높이) | 판정 |
|---|---|---|
| 마크만 | 28 × 19 | 읽힌다. 다만 펼친 슬롯의 153px 폭을 버리고 사명이 사라진다 |
| **마크 + YEST 가로** | **88 × 19** | **둘 다 읽힌다. 채택** |
| 세로 조합을 욱여넣기 | 19 × 19 | `YEST` 가 판독 불가 |

셸에는 슬롯이 둘이므로 **양자택일이 아니다.**

| 슬롯 | 자산 | 쓰는 안 |
|---|---|---|
| `.logo-lg` (사이드바 펼침) | `logo-dark.png` 153 × 19 | 가로 조합 88 × 19 |
| `.logo-sm` (사이드바 접힘) | `logo-dark-sm.png` 37 × 19 | 마크만 28 × 19 |

가로 조합 비율은 마크를 슬롯 높이에, 워드마크를 그 **0.7배** 높이에 두고 간격
7px 일 때가 가장 읽힌다. 2배 자산(176 × 38)도 같이 낸다 — 원본 마크가 99px 폭
이라 손실 없이 뽑힌다.

**배경**: 로고 영역은 흰색(`#ffffff`, 실측)이라 워드마크의 어두운 자획
(`#323033`)이 성립한다. 사이드바(`#2e2e31`)에 로고를 올리게 되면 흰색 워드마크
변형이 따로 필요하다.

**브랜드 빨강이 다르다.** 로고의 주색은 `#da2129` 인데 CSS 는 `#ea1b1b` 을 쓴다.
`--brand-primary` 는 **로고 쪽(`#da2129`)을 따른다** — 로고가 브랜드의 정본이다.

## [4] 접근

**토큰 레이어 1장을 마지막에 얹는다.**

`app/static/assets/css/tokens.css` 를 새로 만들어 레이아웃 맨 뒤에 로드한다.
이 파일의 일은 **색을 다시 선언하는 것이 아니라 세 네임스페이스를 단일 원천에
매핑하는 것**이다.

```css
:root {
  --brand-primary: #da2129;   /* 로고 기준. CSS 의 기존 #ea1b1b 를 대체한다 */
  --brand-ink:     #242424;
  --brand-line:    #d8d8d8;
  --brand-paper:   #edeff1;
  --brand-muted:   #666666;
  --brand-warning: #ffba00;
  --font-sans: 'Pretendard', 'Noto Sans KR', system-ui, sans-serif;
}

:root[data-bs-theme=light] { --ct-primary: var(--brand-primary); /* … */ }
:root { --teal: var(--brand-primary); --ink: var(--brand-ink); /* … */ }
.wzg-container { --wzg-primary-color: var(--brand-primary); /* … */ }
```

채택하지 않은 안:

- **`SF-Custom.css` 안에 토큰을 넣는다** — 이미 1,812줄이라 무엇이 디자인 시스템인지 보이지 않게 된다
- **데이터 CSS 를 `SF-Custom.css` 로 흡수한다** — 712줄의 독립성을 잃고 diff 가 가장 크다. D-2 와도 어긋난다

**빌드 단계가 없다.** CSS 를 손으로 고쳐 그대로 서빙한다. 그리고 템플릿이 거는
것은 `app.min.css` 이고 `app.css`(21,083줄)는 **로드되지 않는다** — 거기를 고쳐도
반영되지 않는다. 벤더 테마는 수정 대상이 아니고, 오버라이드로만 다룬다.
`app.min.css` 와 특정도가 충돌하는 지점에서는 `!important` 가 몇 군데 필요하다.

## [5] 빨강의 역할 분리

색상(hue)으로 나누지 않고 **형태로 나눈다.** 브랜드가 빨강인 이상 "덜 위험한
빨강"을 따로 만들어도 구분되지 않기 때문이다.

| 역할 | 형태 | 예 |
|---|---|---|
| 주요 동작 | 빨강 **채움** | 조회, 저장, 등록 |
| 보조 동작 | 중립 외곽선 | 닫기, 초기화, 새로고침 |
| 되돌릴 수 없는 동작 | 빨강 **외곽선** + 확인 단계 | 삭제, API Key 재발급 |
| 비활성 | 회색 채움 | — |

데이터 관리 화면이 이미 이 방식이다(`데이터 추가` 채움 / `데이터 삭제` 외곽선).
그쪽 패턴을 MES 로 가져온다.

**넓은 면적의 채움에는 브랜드 빨강을 쓰지 않는다.** 선택 행 배경·연한 영역은
중립 또는 아주 낮은 채도의 틴트를 쓴다. 데이터 화면의 `--teal-soft`(`#e3f5f3`)를
같은 밝기의 빨강 틴트로 그대로 치환하면 분홍색 경고처럼 읽힌다. 이 자리는
**치환이 아니라 재설계가 필요한 지점**이고, Phase 1 의 실제 작업량은 대부분
여기에 있다.

## [6] 단계

각 단계는 **25화면 + 8모달 재캡처 → 직전과 비교**로 검증한다. 캡처 스크립트를
`scripts/capture_ui.py` 로 커밋해 반복 가능하게 둔다.

### Phase 0 — 버그 6건

§2.4 의 B-1 ~ B-6. 건마다 재현 → 수정 → 검증. 디자인 작업과 섞지 않는다.

**B-4(라벨링 높이)의 기준** — D-6. 1920 × 911 에서 실측한 현재 상태:

```
뷰포트 1920 × 911 · 세로 스크롤 없음(scrollHeight == clientHeight == 911)
body                841
main                520  (top 79 → 599)
그 아래             312px 가 빈다
--crud-shell-height  calc(100vh - 100px)   ← 라이브 계산값
```

문제는 스크롤이 아니라 **`main` 이 늘어나지 않는 것**이다. 서 있는 공간
762px(841 − 79) 중 520px 만 쓴다.

기준은 "세로 스크롤을 만들지 않으면서 남는 공간을 없앤다" 이고, **정확한 높이
식은 구현하면서 정한다.** 위 수치는 gui 페이지를 단독으로 연 것이고 실제 사용
경로는 셸의 iframe 탭(상단바 50px) 이므로, 검증은 **셸 탭 안에서** 한다.

`--crud-shell-height` 가 `calc(100vh - 100px)` 인데 MES 쪽은
`calc(100vh - var(--ct-topbar-height))`(50px) 를 쓴다. 높이 식이 두 벌이라는
것 자체가 Phase 1 에서 정리할 대상이다.

검증: 1920 × 911 셸 탭에서 세로 스크롤 없음 + 빈 영역 없음. 그 위 해상도에서도
스크롤이 생기지 않는지 확인. `node scripts/verify_screen_js.js` + 단위테스트.

### Phase 1 — 토큰 단일화

1. `tokens.css` 신규 + 레이아웃 로드 순서 마지막에 추가
2. 세 네임스페이스를 단일 원천에 매핑
3. 데이터 계열 712줄의 하드코딩 색을 `var()` 로 치환 (전수 가능한 분량)
4. `SF-Custom.css` 의 `#ea1b1b` 25곳을 `var(--brand-primary)` 로 치환
5. 서체를 Pretendard 로 통일 (데이터 계열의 Inter 선행 제거)
6. §5 의 연한 영역 재설계

검증: 25화면 재캡처 비교. **색만 바뀌고 레이아웃이 움직이지 않아야 한다.**

### Phase 2 — 모달 동작 통일 (완료, 2026-10-02)

원안은 "기판을 네이티브 `<dialog>` 로 모은다"였다. 실측으로 전제가 어긋나는
것이 확인되어(위 §2.3 정정) **기판은 유지하고 동작만 통일**하기로 했다(사용자
결정). `PopupDraggable` 은 드래그 기능이 있고 `columns_setting`(9화면)·
`myinfo`(`parent.modal.close()`)가 교차 프레임 계약으로 쓴다. 기판 교체는 회귀
위험이 크고, 사용자가 느끼는 결함은 동작 통일로 전부 해소된다.

한 일:

1. **백드롭 통일** — `--modal-backdrop: rgba(36,36,36,.45)` 하나로 네 계열이
   모인다. API Key 의 빨간 백드롭과 `PopupDraggable` 의 `transparent
   !important` 강제를 걷어냈다. `--ct-backdrop-bg` 오버라이드는 `:root` 가
   아니라 `.modal-backdrop` 에 건다 — `app.min.css` 가 그 요소 자체에
   선언해서 커스텀 프로퍼티의 가까운 쪽이 이긴다
2. **보라 제거** — Alert 확인 버튼·아이콘(`#6451f3`), Confirm 확인
   버튼(`#727cf5`). 주요 동작은 브랜드 빨강 채움, 정보 아이콘은 중립
3. **Esc 통일** — 세 계열의 `keyboard: false` 를 `true` 로. `backdrop:
   'static'` 은 유지했다(백드롭 클릭으로 입력 중이던 폼이 사라지는 것을 막는다).
   Esc 가 확인 콜백을 부르지 않는 것을 실제로 눌러 확인했다
4. **푸터 순서** — 보조 → 주요(취소 → 확인)

검증: `scripts/verify_modals.py` 가 네 계열의 백드롭색(실효 알파)·Esc·포커스·
버튼 순서를 잰다. 위반 10건 → 0건. 레이아웃 이동 0건.

**남긴 것:** 백드롭이 셸(상단바·좌측 메뉴·탭바)을 덮지 못하는 문제. iframe
경계를 넘으려면 교차 프레임 연동이 필요하다. 모달 헤더·푸터 **마크업 골격**
통일도 하지 않았다 — 네 계열의 템플릿을 다시 써야 하고, 동작이 같아지면 체감
차이가 작다. Phase 3 버튼 체계와 함께 본다. B-1(내정보 이중 프레임)의 근본
해소는 기판 교체가 전제라 Phase 0 의 응급 처치가 유지된다.

### Phase 3 — 버튼 역할↔형태 통일 (완료, 2026-10-02)

**형태만 통일하고 치수는 손대지 않기로 했다**(사용자 결정). 그래서 Phase 1·2
와 같은 기준 — 레이아웃 이동 0건 — 을 그대로 썼다.

§5 의 4계층을 **기존 클래스의 선언을 맞추는 방식**으로 구현했다. 새 클래스를
만들지 않아 템플릿 25화면을 건드리지 않았다(예외는 검사 계열 4줄).

| 계층 | 형태 | 클래스 |
|---|---|---|
| 주요 동작 | 빨강 채움 | `.btn-band` `.btn-search` `.primary-button` |
| 보조 동작 | 중립 외곽선 | `.btn-input` `.outline-button` `.btn-outline-light` |
| 되돌릴 수 없는 동작 | 빨강 외곽선 | `.btn-dell` `.danger-button` |
| 비활성 | 회색 채움 `#dfdfe0` | 공통 |

주요와 위험이 같은 빨강인데 채움/외곽선으로 갈린다. §5 가 "색상(hue)으로
나누지 않고 형태로 나눈다"고 한 이유다 — 브랜드가 빨강인 이상 "덜 위험한
빨강"을 따로 만들어도 구분되지 않는다.

고친 것:

- **삭제가 비활성처럼 보이던 문제.** 활성 삭제 `#9a9a9a`, 비활성 `#dfdfe0`
  로 둘 다 회색이라 눌러도 되는지 알 수 없었다. 화면에서 가장 위험한 동작이
  가장 약했다
- **등록이 검정 채움**이라 주요 동작보다 무거워 보이던 것
- **데이터의 `danger-button` 이 오류색**을 쓰던 것. Phase 1 에서 오류
  '상태'(`--brand-danger`)와 되돌릴 수 없는 '동작'(`--brand-primary`)을
  갈랐고, 삭제는 동작이다
- **데이터의 `검색` 이 네이비 채움**이라 MES 의 `조회`(빨강 채움)와 같은
  역할인데 형태가 달랐다. 계획에 없던 항목으로 하네스가 찾았다
- **검사 계열의 맨 텍스트 4개.** `API Key 재발급`(위험) · `사용/중지` ·
  `매핑 해제` · `표시/숨김`(보조)

**스펙 §2.5 의 "맨 텍스트 2개"는 틀렸다 — 4개다.** `vision/` 세 화면에
`<button type="button" class="btn y_write_auth">` 라는 같은 모양으로 있다.

**합격 기준을 바꿨다.** 원안은 "화면당 버튼 색 3종 이하"였는데 실측하니
15화면 중 13화면이 이미 3종 이하였고, 초과한 `wm_data_image` 의 4종은
주요·보조·위험·아이콘이라 정당하다. 개수가 아니라 **형태가 역할에
대응하는가**를 본다 — `scripts/verify_buttons.py` 가 클래스별 기대 형태와
실제 렌더링을 맞춘다. 위반 73건 → 0건.

**4계층에 넣지 않은 것:** 아이콘 버튼(`btn-icon`·`icon-button`), 텍스트
링크(`text-button`), 도구 토글(`tool-button`), 상태 표시(`edit-button` —
`labeling.html:249` 가 `dirty` 일 때만 활성화한다). 동작 등급이 아니다.

**하네스를 한 번 고쳤다.** `.primary-button` 은 `border: 0` 이라
`borderTopColor` 가 글자색을 돌려준다. 없는 테두리의 색을 재느라 거짓
위반 6건이 잡혔다. 굵기가 0 이면 색 검사를 건너뛰되, 외곽선이 형태인
계층(보조·위험)은 테두리가 없는 것 자체를 위반으로 잡는다.

**검증 중에 발견한 별개 결함:** `app/views/system/menu_language.py:28-37` 의
`menu_language_list` 는 **읽기 액션인데 없는 라벨 코드를 insert 한다.**
화면을 훑기만 해도 `label_code` 행이 늘어 `wm_multi_language` 그리드가
자란다. 레이아웃 기준선이 이 때문에 흔들렸다(CSS 는 무관함을 같은 데이터
비교로 확인했다). Phase 3 범위가 아니라 고치지 않았다.

**남긴 것:** 폼 높이 통일(MES 32px ↔ 데이터 40–43px), 그리드 서체, 이중 높이
식, 모달 마크업 골격. 전부 치수라 레이아웃이 움직인다.

### Phase 4 — 다국어 닫기·용어·브랜딩 (완료, 2026-10-02)

**다국어를 내부 기능으로 남기고 화면에는 한국어만 내보내기로 했다**(사용자
결정). 표·모델·API·관리자 화면은 그대로 두고 **고르는 수단**만 없앴다. 그래서
"시드를 먼저 돌려야 한다"는 전제가 사라졌다 — 한국어 전용이면 시드가 없어도
된다.

#### 4a — 언어 변경 수단 제거

살아 있던 경로는 **상단바 국기 드롭다운 하나뿐**이었다. 나머지는 이미 죽어
있었다.

| 지점 | 상태 |
|---|---|
| 상단바 국기 드롭다운 | 유일하게 살아 있었다 — 제거 |
| 로그인 화면 국기 드롭다운 | `data-lang-code` 도 핸들러도 없는 죽은 UI — 제거 |
| `#lang_select` · `input[name=language]` 핸들러 | 대상 요소가 없어 한 번도 돈 적 없다 — 제거 |
| `isChangeLang` | 서버가 읽지 않는다 — 제거 |
| `/page/account/language` | 여는 트리거가 없다. 되살릴 때를 위해 남겼다 |
| 라벨 우클릭 편집 | 이미 `group_code == 'admin'` 게이트 |

**사용자 언어 설정은 애초에 저장되지 않았다.** `UserProfile.lang_code` 는
`user.py:56` 이 읽기만 하고 저장하지 않으며, 관리 화면의 선택 필드는
`disabled` 이고 `userinfo` 전역에도 없다. 실제 단일 원천은
`sessionStorage['lang_code']` 하나이고 기본값이 `ko-KR` 이라, 드롭다운을
없애면 영원히 한국어다.

`scripts/verify_korean_only.py` 가 이 결정이 되돌아오지 않는지 지킨다.
위반 28 → 0건.

#### 4b — 브랜딩

로고를 `wezon|MES` 에서 YEST 로 바꿨다. 받은 자산이 세로 조합(1.23:1)이라
로고 영역(260×50)에 그대로는 안 들어가, 마크와 글자 파일을 **가로로 합성**해
148×34 조합을 만들었다. 접힌 사이드바는 마크만 쓴다.

파일은 2배로 내보내고 표시 높이를 CSS 로 34px 에 고정했다(기존 로고는 1배라
고해상도 화면에서 흐렸다). 로고 영역 높이가 50px 로 고정이라 20px → 34px 로
키워도 **레이아웃은 움직이지 않는다**.

**필요한 자산은 2개다**(스펙은 4개로 적었다). `logo.png`·`logo-sm.png` 는 흰
글씨 버전인데 호출하는 두 곳이 다 주석 처리돼 있어 쓰이지 않는다. `srcset` 도
`@2x` 파일도 저장소에 없다. 파일 이름의 `dark` 는 테마가 아니라 **로고 잉크
색**을 뜻한다 — 흰 배경에 올라가는 어두운 글씨 로고다.

제품명을 **제조AI플랫폼**으로 통일했다 — 탭 제목 3곳, 로그인 제목,
`system_title` 폴백 둘, 문서 제목줄 4곳. MES 시절 표어는 지웠다.

**원본 시스템을 가리키는 `MES` 는 그대로 둔다.** `MESBaseView`, "MES 동적
dispatch", 통합 당시의 원본 비교표가 그것이다. 제품은
제조AI플랫폼이고 뼈대는 MES 에서 왔다는 두 사실이 공존해야 하고, 바꾸면
AGENTS.md §2 가 설명하는 세 API 규약의 구분이 무너진다.

#### 4b — 용어: `.eyebrow` 를 걷어냈다

영문 kicker 를 한국어로 **옮기는 대신 없앴다.** `.eyebrow` 는 데이터 관리
계열에만 있던 디자인이다 — 벤더 테마에도 `SF-Custom.css` 에도 없고 `data/main.css` 에만
1줄 있었으며 `data/` 13개 템플릿만 썼다. MES·검사 계열은
`header-title` + `sub-tit` **두 단계**로만 단다.

내용도 대부분 바로 아래 제목을 영어로 반복했다 — `DATA UPLOAD`/데이터 업로드,
`LABEL CLASSES`/라벨 클래스, `WORK STATISTICS`/작업 통계. 템플릿 26곳과 JS 가
만들던 7곳을 지웠다.

하나만 남겼다 — labeling 의 `지금 표시하는 이미지`. 아래에 제목이 없어 파일명을
설명하는 유일한 라벨이다. 소제목이 아니라 값 라벨이므로 이 파일이 이미 쓰는
방식(`.drop-zone small`)대로 `.canvas-toolbar small` 로 바꿨다.

따라온 결과:

- **영문 kicker 22곳(스펙은 23곳)과 표시용 `PROJECT` 9곳이 전부 kicker 였어서
  함께 사라졌다.** 데이터 화면에 남은 영문 표시 문자열은 `BBOX` ·
  `Polygon mask` 뿐이고 기술 용어다
- `.eyebrow` 의 `letter-spacing: .16em` · `text-transform: uppercase` 가
  한국어에 맞지 않던 문제도 함께 없어졌다. 조판을 따로 고칠 일이 없다
- 좌측 메뉴는 `스냅샷 관리` 인데 화면 제목만 `데이터셋 Snapshot` 이라 같은 것을
  두 이름으로 부르던 것을 `데이터셋 스냅샷` 으로 맞췄다. 나머지 `Snapshot` 15곳은
  JS 식별자라 화면에 안 나온다
- 해요체 5곳(전부 labeling)을 나머지 122줄과 같은 합쇼체로 바꿨다
- `Client` · `Overlay` 는 영문을 유지한다. `Client` 는 `/api/v1` 계약 용어이고
  (`X-Client-ID`), `Overlay` 는 번역하면 오히려 모호해진다

**레이아웃은 의도적으로 움직인다** — kicker 한 줄(21px)이 빠져 아래 내용이
그만큼 올라간다. 이동 369건이 **데이터 화면 7개에만** 몰렸고 MES·검사·기준정보
화면은 0건이다. `.eyebrow` 가 데이터 화면에만 있었다는 사실과 일치한다.
기준선을 새로 떴다.

#### 4c — `menu_language` 의 읽기-쓰기 결함

`menu_language_list` 는 조회 액션인데 라벨 코드가 없으면 insert 했다. 관리자가
화면을 훑기만 해도 `label_code` 가 늘어 '다국어 설정' 그리드가 자랐고,
**레이아웃 회귀 비교의 기준선이 흔들렸다**(Phase 3 에서 이 때문에 CSS 를
의심했다). 행 생성은 `labellang_save` 가 이미 하므로 조회에서 뺐다.

**같은 쿼리의 두 번째 결함은 남겼다** — `system.py` 의 `left join` 이
`where lcl."LangCode" = ...` 때문에 `inner join` 으로 떨어져 번역이 없는 라벨이
응답에서 통째로 빠진다. 한국어 전용에서는 증상이 없고, 고치면 지금 안 보이던
행이 섞인다. **다국어를 다시 열 때 함께 본다.**

#### 넘긴 것

식별자(class·id·JS 변수)의 `project` 142곳은 화면에 안 나오므로 그대로 둔다.

### Phase 5 — 죽은 코드 정리 (완료, 2026-10-02)

**스펙의 "8,392줄"은 틀렸다.** 산출 근거가 적혀 있지 않았고, 실측하니
**2,421줄**이다.

지운 것:

| 대상 | 줄 | 근거 |
|---|---|---|
| `SF-exhibition.css` · `select2-mes.css` · `index_page.js` | 1,060 | 어떤 템플릿도 싣지 않는다 |
| `index.html` 의 벤더 테마 설정 패널 | 841 | 여는 버튼이 없어 닿지 못한다 |
| `SF-Custom.css` 죽은 규칙 | 496 | 아래 |
| `index.html` 주석 처리된 상단바 로고 | 12 | 주석 |
| `common.js` 의 `getGUITextDefault` | 12 | 호출처 0곳 |

`SF-Custom.css` 496줄의 내역: `mes-chatbot-*`(NL2SQL 제거됨) · `tech-pc`
(터치 PC 레이아웃) · `mes-wizard-*` · `h-180`~`h-740` 높이 유틸 · 생산
상태색(`background-defect` · `working-status` 등) · `table-canvasRight` ·
`body-nature-*` · `input-in-icon`. **`offcanvas` 오버라이드**도 테마 패널을
지우면서 쓰는 곳이 하나도 안 남아 함께 지웠다.

테마 패널은 `coderthemes.com` 으로 가는 "Buy Now" 링크를 제품 안에 남기고
있었다. `app.js` 의 `ThemeCustomizer` 가 이 요소들을 널 가드로 접근하므로
지워도 안전하고, 햄버거 버튼(`.button-toggle-menu`)은 패널 **밖**이라 남겼다
— 토글이 도는 것을 확인했다.

**남긴 것과 그 이유:**

- **`app.css`(21,083줄).** `app.min.css` 와 **같은 테마**다(클래스 2,913개
  전부 일치). 죽은 파일이 아니라 **살아 있는 파일의 읽을 수 있는 쌍둥이**이고,
  벤더 테마를 읽을 수 있는 유일한 파일이다. 오버라이드를 쓰려면 벤더가 뭘
  하는지 읽어야 하는데 `app.min.css` 는 6줄짜리 압축본이라 grep 조차 어렵다
- **`select2-container--default` · `simplebar-scrollable-y`.** 벤더 JS 가
  `'select2-container--' + 테마명` 처럼 **런타임에 이어 붙여** 만들어 grep 으로
  잡히지 않는다. 실제로 쓰인다(`company.html` 의 `select2()`, 좌측 메뉴
  SimpleBar). **Phase 2 의 `.btn-info` 와 같은 함정이다**
- **`valid-feedback` 외 3개.** `:not()` 제외 목록에 이름만 나오고 규칙 자체는
  `.input-group` 을 겨눈다
- ~~**`data/main.css` 47개 · `layout.css` 13개.** 같은 오탐 검토를 아직 안
  했다~~ → **E-2 에서 했다(아래).**

**레이아웃 이동 0건**(요소 2,710개 대조). 살아 있는 규칙을 지웠다면 여기서
잡혔을 것이다 — 이것이 이 Phase 의 안전망이다.

### E-2 — 데이터 화면 CSS 의 죽은 규칙 (완료, 2026-10-06)

`data/main.css` · `layout.css` · `governance.css` **135개 규칙**을 지웠다
(727줄 → 574줄). 셋 다 `data/_base.html` 만 싣는다.

**판정은 두 축을 모두 통과해야 한다.** 한 축만으로는 둘 다 틀린다.

1. **브라우저 실측** — 7개 데이터 화면에서 기본 선택자가 `querySelectorAll`
   로 하나도 걸리지 않는가. grep 이 못 보는 런타임 조립을 본다
2. **이름 대조** — 선택자의 클래스·id 가 **그 문서에 마크업을 넣을 수 있는
   곳**(`templates/data/*.html` · `static/data/*.js` · 응답을 만드는 파이썬)에
   없는가. 상호작용 뒤에만 나타나는 상태가 죽은 것으로 보이는 것을 막는다

1번만 쓰면 모달 안·선택 후에만 붙는 규칙이 전부 죽은 것이 되고, 2번만 쓰면
**다른 문서에 있는 이름** 때문에 죽은 규칙을 살아 있다고 본다 — 이것이
`layout.css` 에서 실제로 일어났다.

**지운 것의 정체:** 통합 전 독립 실행하던 때의 **자기 로그인·계정·사용자
관리·테넌트 화면과 자기 셸**이다. 그 화면들은 MES 쪽(`login_mes.html` ·
`wm_user` · `wm_user_group`)으로 대체됐고 셸은 `app/index.html` 이 그린다.
`layout.css` 의 `.leftside-menu`·`.navbar-custom` 규칙 23개가 특히 그렇다 —
**부모 프레임은 이 파일을 싣지 않으므로** 이름이 맞아도 닿지 않는다.

**오탐으로 걸러낸 것(지우지 않았다):**

| 규칙 | 왜 살아 있나 |
|---|---|
| `.readiness.not_ready` 2개 | `item.html:228`·`snapshot.html:191,331` 이 `'readiness small ' + readiness.toLowerCase()` 로 만든다. 서버 enum 이 `NOT_READY` 다 |
| `.task-status.in-progress` | `home.html:267` 의 `label_status.toLowerCase().replace('_','-')`. 서버 enum 은 `IN_PROGRESS` |
| `.toast:not(.show)` | `data/common.js:245` 가 토스트를 **그때 만든다**. 화면 로드 시점의 DOM 에는 없다. `:not()` 안의 이름은 *없을수록* 규칙이 걸린다 — 있어야 한다고 보면 거꾸로다 |

**레이아웃 이동 0건**(화면 22개 / 요소 2,862개 대조). 이것이 안전망이다.

**곁다리로 드러난 것:** `#confirmDialog` 엘리먼트가 **어느 템플릿에도 없다.**
`DataUI.confirm` 은 `document.getElementById("confirmDialog")` 가 비면 곧바로
`window.confirm()` 으로 떨어진다(`data/common.js:401`). 그래서 데이터 화면의
확인 질문 4곳(라벨링 2 · 스냅샷 1 · `data/common.js` 의 폼 제출 1)은 **브라우저
기본 대화상자**로 뜬다. 실제로 확인했다. `.confirm-dialog*` 4개는 그 대화상자의
스타일이었고 함께 지웠다. ~~되살릴 자리는 C(구조 흡수)의 `Alert.confirm` 이다.~~
**C 에서 바로잡았다(아래)** — `Alert.confirm` 은 열린 `<dialog>` 위로 뜨지 못한다.

~~같이 정리할 것: `SF-Custom.css` 의 `.btn-info`·`.text-info`(`#6451f3`).~~
**취소(Phase 2 에서 확인).** 템플릿에는 없지만 `common.js` 가 Alert 마크업을
동적 생성하며 쓴다 — 알림 89곳의 확인 버튼과 아이콘이 이 색이었다. 템플릿만
grep 해서 "미사용"으로 판단한 것이 틀렸다. 죽은 코드가 아니다.

### C — 데이터 화면 구조 흡수 (C-1 완료 · C-2·C-3 하지 않음, 2026-10-06)

처음 계획은 셋이었다 — C-1 확인창을 `Alert.confirm` 으로, C-2 토스트를 `Notify`
로, C-3 데이터 셸(`data/_base.html`)을 `layout_page.html` 로. 실측에서 셋 다
전제가 깨졌다. 계획과 근거: [plans/2026-10-06-c-data-ui-absorption.md](superpowers/plans/2026-10-06-c-data-ui-absorption.md)

**Bootstrap 모달·토스트는 열린 `<dialog>` 위로 올라오지 못한다.** `showModal()`
로 연 `<dialog>` 는 최상위 레이어(top layer)에 놓이고 나머지 문서를 inert 로
만든다. `body` 에 붙는 `Alert.confirm`·`Notify` 는 z-index 와 무관하게 그 아래에
깔린다. 검사항목 삭제 요청(`#settingsDialog` 안)이 그 경우이고, 배정 인원 추가
알림(`#addInspectionItemMemberDialog` 안)도 그렇다. 데이터 토스트는 이것을 이미
풀어 두었다 — 열린 대화상자 안으로 옮겨 붙고, 없으면 `popover` 로 올린다.

**C-1 (완료).** `DataUI.confirm` 은 원래 `<dialog>` 를 열게 짜여 있었고 빠진 것은
`#confirmDialog` 엘리먼트였다. 처음 쓸 때 만들고(`data/common.js`
`getConfirmDialog`) `Alert.confirm` 의 마크업·클래스를 그대로 입혔다 — 빨강 머리띠,
취소 → 확인, 확인은 브랜드 빨강 채움. 경고 아이콘(`ri-alert-line`)만 없다.
데이터 셸은 remixicon 을 싣지 않는다. `verify_modals.py` 의 다섯 번째 계열로 잰다.

**C-2 (하지 않음).** 위 이유로 `Notify` 로 바꾸면 대화상자 안의 알림이 사라진다.
데이터 토스트는 위치(상단 중앙)·형태가 `Notify`(우하단)와 다르게 남는다.

**C-3 (하지 않음).** MES `common.js` 를 데이터 셸에 싣는 순간:

| 무엇 | 결과 |
|---|---|
| `let AjaxUtil`(MES) | `window.AjaxUtil`(데이터)을 가린다. 계약이 다르다 — Promise 를 돌려주지 않고, 실패 콜백 인자가 `(req, status, error)` 이고, `postJsonAsyncData`·`putJsonAsyncData`·`putAsyncData` 가 없다. 데이터 화면 30곳이 깨진다 |
| `Ajax.enableErrorHandler()` | 실패마다 오류 창이 하나 더 뜬다 |
| `i18n.holdReady()` | 라벨 자원 두 건이 올 때까지 `ready` 가 멈춘다 |
| `$.validator` | `jquery.validate` 없이는 `ready` 에서 예외 |

얻는 것은 셸 코드가 한 벌이 되는 것뿐이고 사용자에게 보이는 차이는 없다.
§4 가 데이터 CSS 를 흡수하지 않은 것과 같은 판단이다.

## [7] 범위 밖

- **레이아웃 변경** (D-2). 데이터 화면의 2단 구조와 라벨링 캔버스는 유지한다
- **`app.min.css` 수정.** 벤더 테마는 오버라이드로만 다룬다
- **WeZonGrid 내부 수정.** `--wzg-*` 커스터마이즈 지점으로만 다룬다
- **다크 모드.** 요청에 없다
- **반응형/모바일.** 현장 PC 기준 제품이다
- **`/api/v1` 관련 화면 계약.** [06_API_COMPATIBILITY_PLAN.md](06_API_COMPATIBILITY_PLAN.md) 참조

## [8] 남은 판단

처음 열어둔 질문 3건은 D-4 · D-5 · D-6 으로 모두 닫혔다. 구현에 들어가며 정할
것만 남는다.

| # | 판단할 것 | 시점 |
|---|---|---|
| Q-1 | 라벨링 화면의 정확한 높이 식. 셸 탭(상단바 50px) 기준으로 `--crud-shell-height` 를 고칠지, 라벨링 전용 식을 둘지 | Phase 0 B-4, 구현 중 |
| Q-2 | 영문 kicker 23곳의 한글 문구. 라벨 테이블로 뺄지 템플릿에 둘지는 i18n 시드 실행 뒤 결정 | Phase 4 |
| Q-3 | 식별자(class·id·JS)의 `project` 142곳을 같이 바꿀지 | Phase 4, 선택 |

사이드바에 로고를 올리게 되면 흰색 워드마크 변형이 추가로 필요하다(§3).

**Q-4 종결(2026-10-02). Phase 1 완료.** `--brand-primary` 를 로고 기준
`#da2129` 로 옮겼다. 22화면 2,686개 요소의 바운딩 박스를 대조해 **색 작업
전 구간에서 레이아웃 이동 0건**을 확인했다(`scripts/verify_layout_stable.py`).
하드코딩 색 스캐너는 148건 → 0건이다(`scripts/verify_tokens.py`).

구현하며 정한 것:

- **오류색을 브랜드 빨강과 분리한다.** 데이터 계열의 빨강 11종은 전부 오류
  상태였다(`.form-error` · `.toast.is-error` · `.queue-item.is-invalid` ·
  `.task-status.rework`). 브랜드가 빨강인 이상 오류를 같은 빨강으로 두면
  구분되지 않는다. §5 는 버튼을 **형태**로 나누라고 했지만 토스트·배너·폼
  오류에는 기댈 형태가 없다. 기존 값 `#bd5a4d` 를 `--brand-danger` 로
  유지해 채도로 가른다. 실측으로 오류 계열이 `#bd5a4d`, 주요 동작이
  `#da2129` 로 갈리는 것을 확인했다
- **`--teal-soft` 를 둘로 쪼갰다.** 한 토큰이 행 선택 배경(넓은 면적) 7곳과
  칩·배지 바탕(좁은 면적) 11곳을 겸하고 있었다. 넓은 쪽을
  `--row-select-bg`(중립)로 가른다. §5 의 "치환이 아니라 재설계가 필요한
  지점"이 정확히 여기였다
- **색 74종을 램프로 접었다.** 데이터 계열은 74종 중 48종이 딱 한 번만
  쓰였고, `#eef3f4`·`#edf4f5`·`#edf2f3`·`#eef2f3`·`#eef1f2` 처럼 눈으로
  구분되지 않는 값이 따로 선언돼 있었다. 용도별(면 4단·선 2단·보조글자·
  강조)로 줄였다
- **`--ct-*` 매핑은 `:root` 와 `:root[data-bs-theme=light]` 둘 다에 건다.**
  `data-bs-theme` 는 템플릿이 아니라 벤더 JS 가 런타임에 붙인다. 데이터
  화면(`data/_base.html`)은 그 JS 를 싣지 않아 속성이 끝까지 없고, 한쪽만
  쓰면 그 화면들의 `--ct-*` 가 Bootstrap 기본 보라(`#727cf5`)로 남는다
- **WeZonGrid 의 서체는 바꾸지 않았다.** `--wzg-font-family: 'Malgun Gothic'`
  인데 `wezongrid.js:26713` 이 이 값으로 컬럼 폭을 **측정**한다. 바꾸면
  레이아웃이 움직여 이 Phase 의 합격 기준과 충돌한다 → **Phase 3 으로 넘긴다**

Phase 1 에서 다루지 않고 남긴 것:

| 항목 | 왜 | 언제 |
|---|---|---|
| `--wzg-font-family` 를 Pretendard 로 | 컬럼 폭 측정값이라 레이아웃이 움직인다 | Phase 3 |
| `--ct-danger: #2e2e31` — `.text-danger`·`.btn-danger` 는 이 변수가 아닌 경로로 벤더 분홍이 나온다(Phase 3 에서 확인). `.text-danger` 를 `--brand-danger` 로 직접 덮었다. **정정(2026-10-06): 죽은 선언이 아니다.** 벤더의 `var(--ct-danger)` 40곳(입력 오류 말풍선·알림 점·`btn-soft-danger`)이 이 값을 받는다. 지우면 그곳들이 벤더 분홍(`#fa5c7c`)으로 바뀐다 | 지우지 않는다 | Phase 3 완료 |
| `--crud-shell-height: calc(100vh - 94px)` 와 `--ct-topbar-height: 50px` 의 이중 높이 식 | 치수라 레이아웃이 움직인다 | Phase 3 |
| 로고 PNG 속 빨강(`#ea1b1b`) | 이미지 자산이라 CSS 로 안 바뀐다 | Phase 4 |
| `.btn-info`·`.text-info`(`#6451f3`) | 템플릿이 한 번도 쓰지 않는 죽은 코드 | Phase 5 |
