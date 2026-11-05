# 디자인 규칙

제조AI플랫폼 화면이 따르는 디자인 규칙과, 화면을 더하거나 고칠 때 보는 체크리스트다.
색·글꼴·로고·컴포넌트(화면 골격·버튼·요약 카드·패널·차트·그리드·상세 영역·모달)·문구·데이터 표기·한국어 전용을 다룬다.
값의 정본은 코드다 — 색·서체는 `app/static/assets/css/tokens.css`, 치수는 `SF-Custom.css`.
브랜드 표현(빨강·선·모서리·숫자 표기)은 고객사 웹(`yest.co.kr`)을, 차트는 데이터 시각화 규칙(§5.9)을 따른다 — 사용자 결정 2026-10-23.

규칙마다 검사 스크립트가 있으면 함께 적었다.

| 규칙 | 검사 |
|---|---|
| 색·서체는 토큰을 거친다 | `verify_tokens.py` |
| 버튼 형태가 역할과 맞는다 | `verify_buttons.py` |
| 모달 동작이 같다 | `verify_modals.py` |
| 언어 변경 수단을 노출하지 않는다 | `verify_korean_only.py` |
| 문구 어조 | 없음 — 사람이 지킨다 |
| CSS 를 고쳐도 레이아웃이 움직이지 않는다 | `verify_layout_stable.py` |

스크립트가 무엇을 보고 무엇이 필요한지(서버·`.admin_pw`·seed_demo·playwright)는 DEVELOPMENT §3, 레이아웃 회귀 비교 절차는 DEVELOPMENT §4 에 있다.

## 1. 원칙

근거: DECISIONS DEC-021, DEC-028.

| 원칙 | 근거 |
|---|---|
| 디자인 언어는 MES 쪽 하나다. 데이터 관리·비전 화면도 같은 색·버튼·모달을 쓴다 | 셸·WeZonGrid·대부분의 화면이 이미 MES 언어다 |
| **데이터 화면도 MES 화면 구조다**(제목 카드 → 검색 카드 → 그리드 → 상세 카드). 라벨링 작업대는 3열 구조를 유지한다 | 같은 제품 안에서 화면 구조가 둘이면 쓰는 사람이 화면마다 다시 익혀야 한다 |
| 브랜드는 YEST 다. 제품 이름은 **제조AI플랫폼** 하나다 | 로고가 브랜드 색의 정본이다(§4) |
| 빨강의 역할은 **색상이 아니라 형태로** 가른다 — 주요 동작은 빨강 채움, 되돌릴 수 없는 동작은 빨강 외곽선 | 브랜드가 빨강이라 "덜 위험한 빨강"을 따로 만들어도 구분되지 않는다(§5.2) |
| 넓은 면적(행 선택·영역 바탕·백드롭)의 채움에는 브랜드 빨강을 쓰지 않는다 | 행 선택·연한 영역을 빨강 틴트로 칠하면 분홍 경고로 읽힌다 |
| 화면 기준은 **1920 × 911** 이고 1366 폭에서도 잘리지 않는지 본다. 라벨링 화면은 세로 스크롤 없이 화면을 채운다. **디지털 전환 화면(검사양식 관리·수입·품질검사 작성·검사결과)은 1024 폭에서도 가로 스크롤이 없다**(양식 편집기 제외 — 탭 폭 930px) | 캡처·검증 스크립트도 1920 × 911 로 연다. 1024 는 `scripts/verify/verify_dig_form_width.py` 가 본다. `GridUtil.fitWidth` 는 칸을 늘리기만 하므로 1024 대상 그리드는 칸 정의 폭 합을 탭 폭 안으로 둔다 |
| 화면에는 한국어만 내보낸다. 영문은 기술 용어·계약 식별자만 남긴다(§5.7, §6) | 다국어는 내부 기능으로 남겼다 |
| **면은 1px 선으로 나누고 그림자로 띄우지 않는다.** 카드·입력칸·버튼의 모서리는 2px 다 | 고객사 웹이 그림자 없이 선과 각진 모서리로 면을 나눈다. 그림자는 떠 있는 것(드롭다운·모달)에만 남긴다 |
| **크게 보이는 것은 화면마다 한 곳이다.** 대시보드는 요약 띠의 숫자다(§5.3) | 강조를 여러 곳에 두면 어느 것도 강조되지 않는다 |
| **색은 의미가 있을 때만 쓴다**(§2.3). 상태를 색만으로 보이지 않고 글자를 함께 둔다 | 장식으로 쓴 색은 상태로 읽힌다 |

## 2. 색

### 2.1 토큰

새 색은 hex 가 아니라 아래 토큰으로 쓴다. 필요한 색이 없으면 `tokens.css` 에 토큰을 더한다. 값은 `tokens.css` 가 정본이다.

| 토큰 | 값 | 쓰는 곳 |
|---|---|---|
| `--brand-primary` | `#da2129` | 주요 동작 채움, 되돌릴 수 없는 동작의 외곽선, 강조, 그리드 페이저·정렬 아이콘. 로고의 주색이다(§4) |
| `--brand-primary-hover` | `#b51a21` | 주요 동작 hover |
| `--brand-primary-light` | `#e8565d` | 밝은 강조 |
| `--brand-primary-tint` | `#fdeced` | **좁은 면적(칩·배지·선택 셀) 전용** |
| `--brand-danger` | `#bd5a4d` | 오류 **상태** — 토스트·폼 오류·오류 셀·`.text-danger`(판정 "이상") |
| `--brand-danger-line` · `-tint` | `#e4b5ae` · `#fdf2f0` | 오류 상태의 선·바탕 |
| `--brand-warning` | `#ffba00` | 경고 채움. 흰 바탕 글자로는 대비가 모자라 쓰지 않는다 |
| `--brand-warning-ink` · `-line` · `-tint` | `#b45309` · `#f0cfa0` · `#fff4e2` | 경고·할 일 글자(흰 바탕 5.0:1)·선·바탕. 글자는 옛 `#d98b27`(2.7:1)이 명암비 미달이라 진하게 했다 |
| `--brand-ink` · `--brand-ink-2` | `#242424` · `#2e2e31` | 본문 글자 · 보조 버튼 글자 |
| `--brand-muted` | `#666666` | 보조 글자, 소제목(`.sub-tit`), 알림 정보 아이콘 |
| `--brand-line` · `--brand-line-strong` | `#d8d8d8` · `#bcc1cc` | 선 · 강한 선 |
| `--brand-surface-1` ~ `-4` | `#ffffff` `#f7f8f9` `#edeff1` `#e2e5e8` | 면 4단. 넓은 면적은 여기서 가져간다. 카드 1, 그리드 행 hover 2, 화면 바탕·그리드 머리·행 선택 3 |
| `--row-select-bg` | `--brand-surface-3` | 행 선택·호버 배경. 빨강을 쓰지 않는 자리다 |
| `--sidebar-hover-bg` | `rgba(255, 255, 255, .08)` | 어두운 좌측 메뉴의 hover 바탕(흰색을 옅게 겹친다) |
| `--modal-backdrop` | `rgba(36, 36, 36, .45)` | 모든 모달의 백드롭(§5.6) |
| `--chart-1` ~ `--chart-4` | `#2a78d6` `#1baf7a` `#6250d6` `#e87ba4` | **차트 계열 색 전용**(§5.9). 이 순서로만 쓰고 차트 밖(글자·배지·상태)에는 쓰지 않는다 |
| `--radius` | `2px` | 카드·입력칸·버튼·모달 모서리(`--ct-border-radius` 가 이것을 받는다) |

**오류 상태와 되돌릴 수 없는 동작은 다른 빨강이다.** 삭제 버튼은 동작이므로 `--brand-primary`,
토스트·폼 오류는 상태이므로 `--brand-danger` 다. 오류 표시에는 기댈 형태가 없어 채도로 가른다.
판정·결과 강조는 Bootstrap 유틸리티로 한다 — 이상은 `text-danger fw-bold`, 정상은 색 없이.

### 2.2 단일 원천

`tokens.css` 한 파일이 색·서체의 원천이다. 이 파일은 새 색을 정하지 않고,
따로 놀던 세 네임스페이스를 브랜드 토큰에서 파생시킨다.

| 네임스페이스 | 원래 선언 | 쓰는 곳 |
|---|---|---|
| `--ct-*` | `SF-Custom.css` (Bootstrap 테마 변수) | MES 계열 화면 · 셸 |
| `--ink`·`--teal`·`--navy` 등 | `data/main.css` | 라벨링 작업대(`data/main.css`·`governance.css`), 데이터 미리보기(`preview.css`) |
| `--wzg-*` | `wezongrid/wezongrid.css` (공식 커스터마이즈 지점) | 모든 그리드 |

`tokens.css` 는 **모든 스타일시트 뒤에** 싣는다. 앞에 실으면 매핑이 덮인다. 지금 싣는 곳은 셋이다.

| 템플릿 | 비고 |
|---|---|
| `app/templates/app/index.html` | 셸 |
| `app/templates/app/layout_page.html` | MES 계열 화면. `wezongrid.css` 보다 뒤여야 `--wzg-*` 매핑이 산다 |
| `app/templates/app/login_mes.html` | 로그인 |

### 2.3 색의 역할 — 상태색은 예약한다

근거: 사용자 결정 2026-10-23.

| 의미 | 색 | 예 |
|---|---|---|
| 동작 | `--brand-primary` | 주요 버튼 채움, 되돌릴 수 없는 동작 외곽선, 링크 hover |
| 이상·오류(상태) | `--brand-danger` — `text-danger fw-bold` | 판정 "이상", 폼 오류, 토스트 오류 |
| 할 일·대기·경고(상태) | `--brand-warning-ink` | 대시보드의 할 일 숫자, 저장 안 한 작업 |
| 정상·완료·실적 | 색 없음(`--brand-ink`) | 판정 "정상", 이번 달 완료 수 |
| 보조·비활성·없음 | `--brand-muted` | 설명, 단위, 빈 칸 `-` |
| 데이터 계열 | `--chart-1` ~ `--chart-4` | 차트의 계열(§5.9) |

- 위 상태색(빨강·주황)은 차트 계열 색으로 쓰지 않고, 차트 색은 상태로 쓰지 않는다 — 같은 색이 두 뜻을 가지면 둘 다 읽히지 않는다.
- 상태는 색만으로 보이지 않는다. 글자(`이상`·`대기`)나 이름(`작업해야 할 검사`)을 함께 둔다.

### 2.4 명암비

글자는 흰 바탕(`--brand-surface-1`)에서 **4.5:1**(18.66px 굵게·24px 이상은 3:1) 이상이다. 토큰을 바꾸면 이 표를 다시 계산한다(WCAG 2.1 상대 휘도).

| 글자 / 바탕 | 비율 |
|---|---|
| `--brand-ink` / 흰 | 15.5 |
| `--brand-muted` / 흰 · `--brand-surface-3` | 5.74 · 4.98 |
| `--brand-primary` / 흰 (흰 글자 / 주요 버튼도 같다) | 4.96 |
| `--brand-warning-ink` / 흰 | 5.02 |
| `--brand-danger` / 흰 | 4.44 — 굵게(`fw-bold`)로만 쓴다 |

차트 계열 색은 글자가 아니므로 이 표가 아니라 §5.9 의 팔레트 검증을 따른다.

### 2.5 하드코딩 금지 — `verify_tokens.py` 가 보는 것

| 대상 파일 | 규칙 |
|---|---|
| `data/main.css` · `data/governance.css` · `data/preview.css` | 유채색 hex 리터럴 0개(채도 0.08 이상). 흑·백·회색은 허용. `font-family` 는 `var(--font-sans)` 또는 `monospace` 만 |
| `assets/css/SF-Custom.css` · `assets/css/SF-login.css` | 지목한 리터럴 금지 — `#ea1b1b`(옛 브랜드 빨강) · `#16a5a3`(옛 데이터 청록) · `#003597`(옛 그리드 남색). 전부 `var(--brand-primary)` 로 쓴다 |
| `tokens.css` | 존재해야 한다 |

MES 계열 CSS 는 전수 검사가 아니어서 다른 리터럴이 남아 있다. **새로 쓰는 색은 어디서든 토큰을 쓴다.**
예외는 스크립트의 `ALLOW` 에 이유와 함께만 더한다.

## 3. 글꼴

| 항목 | 값 |
|---|---|
| 본문 서체 | `--font-sans` = `'Pretendard', 'Noto Sans KR', system-ui, …`. Pretendard 는 `assets/css/font/pretendard/` 에 들어 있어 PC 마다 같게 보인다 |
| 그리드 서체 | `--wzg-font-family`(`'Malgun Gothic'`). **바꾸지 않는다** — `wezongrid.js` 가 이 서체로 컬럼 폭을 재므로 바꾸면 그리드 레이아웃이 움직인다 |
| 고정폭 | `monospace` 만 허용(ID·해시 등) |
| 숫자 서체 | `--font-figure` = `'Space Grotesk'` → `--font-sans`. **요약 띠의 큰 숫자에만** 쓴다(§5.3). 고객사 웹의 수치 표기 서체다. 숫자·영문만 들어 있어 단위(`건`)는 Pretendard 로 보인다. `assets/css/font/space-grotesk/`(OFL) |

| 쓰임 | 크기 · 굵기 | 클래스 |
|---|---|---|
| 본문·입력칸·라벨 | 14px · 400(라벨 500) | 기본, `.form-label` |
| 화면 제목 | 16px · 500 | `.card .header-title` |
| 소제목(목록·상세 머리) | 14px · 500 · `#666` | `.sub-tit` |
| 요약 카드 이름 / 값 | 12px `text-muted` / 20px `fw-bold` | 요약 카드(§5.3) |
| 요약 띠 이름 / 값 / 단위 / 구성 | 13px · 500 / 32px · 700 `--font-figure` / 14px `--brand-muted` / 13px `--brand-muted` | 요약 띠(§5.3) |

글자 크기는 **12 · 13 · 14 · 16 · 20px** 단계에서 고르고, 요약 띠 숫자만 32px 다. 표 안의 숫자는 자리 폭을 맞춘다(`font-variant-numeric: tabular-nums`). 큰 단독 숫자(요약 띠)는 기본 폭 그대로 둔다.

입력칸·선택칸 높이는 32px(`.form-control`·`.form-select`)이다. 서체는 선언이 아니라 계산값으로 확인한다(§8).
여러 줄 입력칸(`textarea.form-control`)도 이 32px 에 묶여 한 줄로 보이므로 `h-auto lh-base py-1` 을 붙여 `rows` 만큼 높인다(비전검사항목 설명).

## 4. 로고

### 4.1 원본 — `docs/logo/`

정본은 `yest_logo_original.png`(270 × 149, 마크 + `YEST` 세로 조합)다. **브랜드 색의 정본**이다(같은 폴더에 고해상도판·마크만·워드마크만 파일이 더 있다).

`yest_logo_original.png` 의 주색은 `#da2129` 다. `--brand-primary` 는 이 값을 따른다. 브랜드 색을
바꿔야 하면 로고를 먼저 확인하고 토큰을 맞춘다 — 반대 방향으로 바꾸지 않는다.

### 4.2 화면에 쓰는 자산 — `app/static/assets/images/`

| 파일 | 크기(px) | 내용 | 쓰는 곳 |
|---|---|---|---|
| `logo-dark.png` | 297 × 68 | 마크 + `YEST` **가로** 조합 | 셸 `.logo-lg`(사이드바 펼침), 로그인 `.brand-logo` |
| `logo-dark-sm.png` | 99 × 68 | 마크만 | 셸 `.logo-sm`(사이드바 접힘) |
| `werag-logo.png` | 202 × 48 | We.RAG 워드마크(다른 시스템) | 상단 바 `.topbar-werag` — `WERAG_URL` 을 새 탭으로 연다. 표시 높이 24px(`SF-Custom.css`), `alt` 는 `We.RAG` |

- 셸 로고 영역은 높이 50px 고정이라 마크와 워드마크를 가로로 합성했다.
- 파일은 **2배 해상도**다. 표시 높이는 CSS 가 **34px** 로 고정한다 — 셸은 `SF-Custom.css` 의 `.logo img`,
  로그인은 `SF-login.css` 의 `.brand-logo`. 고정하지 않으면 자연 크기 68px 로 떠서 영역을 넘는다.
- 파일 이름의 `dark` 는 테마가 아니라 **로고 잉크 색**이다(흰 배경에 올라가는 어두운 글씨 로고). 어두운 사이드바에 올리려면 흰 워드마크 변형을 새로 만들어야 한다.
- `<img>` 의 `alt` 는 `제조AI플랫폼` 이다.

## 5. 컴포넌트

### 5.1 화면 골격

근거: DECISIONS 사용자 결정 2026-10-21.

목록이 있는 화면은 위에서부터 이 순서다. 라벨링 작업대(3열)와 메뉴 권한 화면은 이 구조를 쓰지 않는다.

```
제목 카드   .card > .card-header > h4.header-title (+ 즐겨찾기 아이콘)
            └ 검색 카드 .card-body > form.row.g-2 — 라벨은 칸 위, [조회]는 마지막 col-auto align-self-end
요약 카드   (있을 때) .row.g-2.mb-2#summaryCards
목록       .upper-wezongrid > .sub-tit "○○ 목록" + 오른쪽 위 [등록]·화면 동작 버튼 / WeZonGrid
상세 카드   .card.mb-0.mt-2.p-15 > .sub-tit "상세 정보" + [수정]·[삭제] / 이미지 칸 · 표
```

- **[등록]은 목록 머리 오른쪽 위**다(§5.5). 화면 동작 버튼(배포본 받기 등)은 그 오른쪽에 둔다. 목록 머리에 그리드 엑셀 다운로드·컬럼 설정 아이콘 버튼은 두지 않는다.
- 화면 제목은 메뉴 이름과 같다. 제목은 `header-title` + `sub-tit` 두 단계이고, 제목 위 영문 kicker(소제목)를 달지 않는다.
- 조회 조건이 있으면 라벨을 칸 **위**에 두고 `row g-2` 로 늘어놓는다. [조회]는 마지막 `col-auto align-self-end` 다(비전 검사 이력·데이터 목록).
- 검색 카드에 입력 칸이 없으면 [조회]는 카드 오른쪽 끝이다(`justify-content-end`, 안내 글이 있으면 `justify-content-between`).
  비전 검사의 조회 조건 없는 화면(비전검사 클라이언트 관리·비전검사 Overlay 관리)과 대시보드는 왼쪽에 화면 요약 한 줄(`#screenDescription`, `text-muted`)을 둔다.

**화면 안 내부 탭**(지금은 비전검사항목 하나 — `data/item.html`). 한 대상에 딸린 화면 여럿을 셸 탭 하나에 묶을 때 쓴다.

```
머리 카드   .card.mb-2 > .card-header(대상 이름·속성·즐겨찾기 + 그 대상의 동작 버튼)
            └ ul.tab_links.nav.nav-tabs.nav-bordered — 카드 아래 변에 붙인다. 첫 탭 글자는 제목 왼쪽 선에 맞춘다
패널       홈은 그 화면 내용, 나머지는 iframe(/gui/<code>/?…&embed=1) — 처음 누를 때 싣고 그 뒤로는 감췄다 보이기만 한다
```

- 하위 화면은 손대지 않고 그대로 싣는다. `embed=1` 이면 `layout_page.html` 이 `body.embedded` 를 달고, 화면은 자기 제목 줄(화면 이름·즐겨찾기)을 감추고
  바깥 패딩을 없앤다(제목뿐인 머리는 통째로, 버튼이 있는 머리는 제목만). 그래서 하위 화면 카드가 머리 카드와 같은 좌우 선에 선다.
- iframe 은 남은 높이를 채우고 바깥은 스크롤하지 않는다(스크롤은 하위 화면 안에서). 탭을 바꿔도 머리 카드 높이가 그대로여야 탭 줄이 움직이지 않는다 —
  홈에서만 쓰는 버튼은 다른 탭에서 `invisible` 로 자리만 남긴다.
- 탭은 메뉴 권한이 있는 화면만 만든다. 셸 탭 제목은 대상 이름 하나다(하위 화면 이름을 붙이지 않는다).

### 5.2 버튼 — 역할 ↔ 형태

#### 네 계층

| 계층 | 형태 | 클래스 | 예 |
|---|---|---|---|
| 주요 | 빨강 **채움**, 흰 글자 | `.btn-band` `.btn-search` | 조회, 저장, 검색 |
| 보조 | **중립 외곽선**(`--brand-line`), 투명 바탕, `--brand-ink-2` 글자 | `.btn-input` `.btn-outline-light` | 등록, 수정, 취소, 닫기, 초기화 |
| 되돌릴 수 없는 동작 | 빨강 **외곽선**, 투명 바탕, 빨강 글자 | `.btn-dell` | 삭제, API Key 재발급 |
| 비활성 | 회색 | `--ct-btn-disabled-*`(회색 채움). 라벨링 작업대의 도구 버튼은 `opacity: .46` | — |

- **등록은 보조다.** 입력 폼을 여는 동작이고 실제 반영은 저장이 한다.
- 목록 머리(`.upper-wezongrid`) 안의 보조 버튼은 **흰 바탕**(`--brand-surface-1`, hover 는 `--brand-surface-2`)이다 — 회색 화면 바탕 위에서 버튼으로 보이게 한다(`SF-Custom.css`).
- 되돌릴 수 없는 동작은 **빨강 외곽선 + 확인 단계**다. 누르면 확인창(§5.6)을 거친다. hover 때만 빨강으로 채워진다.
- 주요와 위험은 같은 `--brand-primary` 이고 채움/외곽선으로만 갈린다. 위험 버튼에 `--brand-danger` 를 쓰지 않는다.
- **새 버튼 클래스를 만들지 않는다.** 위 클래스 중 역할에 맞는 것을 쓴다.
- 모달·확인창 푸터는 **보조 → 주요** 순서다(취소 → 확인).

#### 계층에 넣지 않는 것

동작 등급이 아니라 따로 둔다. 배경도 테두리도 없는 "맨 텍스트" 버튼은 아래 클래스일 때만 허용된다.

| 클래스 | 용도 |
|---|---|
| `.btn-icon` `.icon-button` `.btn-white` | 아이콘 버튼 |
| `.tool-button` | 도구 토글 |
| `.btn-close` `.btn-newpadge` `.btn-check` `.btn-group` | 닫기·배지·체크 |
| `.wzg-pager-btn` `.wzg-page-btn` | 그리드 페이저 |

#### `verify_buttons.py` 가 보는 것

네 계층의 클래스가 붙은 버튼은 계층별 기대값과 맞아야 한다.

| 계층 | 배경 | 글자 | 테두리 |
|---|---|---|---|
| 주요 | `rgb(218, 33, 41)` | 흰색 | 빨강 (굵기 0 이면 건너뛴다) |
| 보조 | 투명 | `rgb(46, 46, 49)` | `rgb(216, 216, 216)` — **없으면 위반** |
| 위험 | 투명 | `rgb(218, 33, 41)` | 빨강 — **없으면 위반** |

- 계층 클래스가 없는데 맨 텍스트인 버튼은 "계층에 넣지 않는 것"의 클래스가 없으면 위반이다.
- 치수(패딩·높이·굵기)는 보지 않는다. 채움 계층은 테두리 색을 보지 않는다.

대상 화면·재는 방식은 DEVELOPMENT §3 에 있다.

### 5.3 요약 카드

근거: DECISIONS 사용자 결정 2026-10-21.

숫자 몇 개로 화면 상태를 보일 때 쓴다(비전검사항목 홈). 대시보드는 아래 요약 띠(`.summary-band`)를 쓴다. 목록 화면(비전 검사 이력)에는 두지 않는다 — 목록이 바로 보이게 한다.

```js
$('<div>', { 'class': 'col-6 col-lg' }).append($('<div>', { 'class': 'card mb-0 p-2 text-center' }).append(
    $('<div>', { 'class': 'text-muted', style: 'font-size:12px' }).text(이름),
    $('<div>', { 'class': 'fw-bold', style: 'font-size:20px' }).text(값)));
```

- 카드 이름에 **범위**를 적는다. 조회 조건과 무관한 숫자면 그렇게 쓴다(예: `작업 완료(검수 대기)`).
- 값이 없으면 `-` 다. 0 으로 바꿔 쓰지 않는다.

**요약 띠**(대시보드, 사용자 결정 2026-10-23): 고객사 웹의 "숫자로 보는 예스티" 형식이다. 같은 카드를 여러 장 늘어놓지 않고
**카드 한 장 안을 세로 1px 선으로 나눈다**. 칸마다 이름 → 숫자(+작은 단위) → 구성 순이다.

```
┌ .card.summary-band ─────────────────────────────────────────────────────┐
│ 작업해야 할 검사   │ 이번 달 검사 완료  │ …                              │
│ 3 건               │ 4 건               │   ← 숫자 32px --font-figure, 단위 14px 회색
│ 수입검사   2건     │ 수입검사   2건     │   ← 구성은 이름·값 쌍 한 줄씩(가운뎃점으로 잇지 않는다)
│ 품질검사   1건     │ 품질검사   2건     │
└─────────────────────────────────────────────────────────────────────────┘
```

- 숫자 색은 의미로 가른다 — 할 일은 `--brand-warning-ink`, 실적은 `--brand-ink`, 0 은 `--brand-muted`(§2.3).
- 권한이 없는 칸은 빼고 남은 칸이 폭을 나눈다. 칸은 누를 수 없다(이동은 패널의 목록·링크가 한다).

**좌측 메뉴 건수 배지**: 할 일이 있다는 알림은 메뉴 잎 옆 숫자다(지금은 수입검사 작성의 검사 대기 하나, `left_menu_class.html` `refreshBadges`).
링크에 `data-badge` 속성을 달고 CSS `.menu-leaf-link[data-badge]::after`(`SF-Custom.css`)가 그린다 — 글자로 넣으면 탭 이름·메뉴 검색이 읽는 메뉴 이름(`text()`)에 숫자가 섞인다.
0 이면 속성을 지운다. 100 이상은 `99+` 다.

**좌측 메뉴 글자**: 1단계(폴더·대시보드)는 16px, 그 아래는 14px 다. 이름은 한 줄이고 넘치면 `…` 로 줄이며 전체 이름은 링크 `title` 이다 —
그래서 이름은 링크 안 `<span>` 에 넣는다(`text()` 는 그대로 이름이다). 마우스를 올리면 글자가 흰색이 되고 `--sidebar-hover-bg` 막대가 깔린다
(`SF-Custom.css` "좌측 메뉴 글자·간격·hover"). 접힌 사이드바의 1단계는 flyout 규칙이 따로 그린다.

### 5.4 그리드 (WeZonGrid)

- **컬럼은 그리드 폭을 채운다.** `WeZonGrid.create` 다음 줄에 `GridUtil.fitWidth(grid)`(`assets/js/grid.js`)를 둔다.
  남는 폭을 컬럼 정의 width 비율대로 나누고, 창 폭·탭 전환(`resize`)·컬럼 설정 뒤에 다시 맞춘다.
  컬럼 폭이 고정 px 라 합이 그리드보다 작으면 오른쪽이 비는데, WeZonGrid 에는 남는 폭 채우기가 없고 내부는 고치지 않는다(§7).
- **쌓이기만 하는 목록(로그·검사 이력·데이터 목록)은 서버 페이징이다.** `dataMode:'server'` + `AjaxUtil.gridRemoteSource`,
  서버는 `{rows, totalRows}`. 최신순 고정이라 헤더 정렬을 끈다(`enableSorting: false`). 조건 함수가 `null` 을 주면 받지 않는다([조회] 전).
  엑셀을 둘 때는 `GridUtil.exportAll`(조건 전체를 `export=1` 로 받는다 — WeZonGrid 는 서버 모드 내보내기를 막는다). 시스템 관리의 로그 화면은 화면 버튼을 내렸고 서버의 `export=1` 은 남겼다.
  상한 없는 테이블을 처음부터 통째로 받으면 데이터가 늘수록 화면이 느려진다.
- 작은 목록은 전부 받아 화면 안 페이징이다(`enablePaging`. 데이터·비전 화면은 `pageSize: 20`, 지정하지 않으면 WeZonGrid 기본 50건).
  변경 뒤 다시 읽을 때는 `GridUtil.setRows(grid, rows, {select})` 로 보던 페이지와 고른 행을 지킨다.
- 셀에는 **사람이 읽는 값**만 보인다. `true`/`false`·상태 코드·클래스 키는 `labelFunction` 이나 서버의 `*_label` 로 바꾼다
  (예: `사용`/`중지`, `있음`/`없음`, `로그인`/`실패`).
- 늘 비는 컬럼은 두지 않는다. 강조는 `styleFunction` 으로 클래스를 준다(`text-danger fw-bold`).
- 행 선택은 `selectionMode: 'singleRow'`, 상세는 `cellClick` 으로 연다.
- 그리드 머리 이름은 `grid_col` 시드(`domain/_sql/i18n/020_template_grid_columns*.sql`)가 덮을 수 있다. 머리 이름을 바꾸면 시드도 맞춘다.

### 5.5 등록과 상세 영역 (공통 CRUD)

**[등록]은 목록 머리 오른쪽 위**에 두고(흰 바탕, §5.2), 누르면 필수 값만 받는 모달을 연다 — 오른쪽 아래 [취소]·[등록].
목록 아래 상세 영역의 머리에는 **[수정]·[삭제]만** 둔다. 상태 전환·재발급 같은 동작은 버튼으로 늘리지 않고 수정 모드의 필드로 옮긴다.
공통 도우미는 `DetailForm.create({...})`(`assets/js/common.js`)다.
데이터 화면(비전검사항목 관리·스냅샷 관리 등)의 상세 머리에는 그 화면의 업무 동작 버튼을 둔다.

| 상태 | 필드 | 머리 버튼 |
|---|---|---|
| 고른 행 없음 / 행을 고름 | 읽기 전용 | [수정]·[삭제] — **늘 켜져 있다**. 고른 행 없이 누르면 "목록에서 항목을 선택해 주세요." 안내만. 목록 머리 [등록]도 켜져 있다 |
| [수정]을 누름 | 수정할 칸만 풀린다(키 값은 계속 막힘) | [취소]·[저장](+ 수정 모드 전용 버튼, 예: API Key [재발급]). 목록 머리 [등록]은 숨는다 |

- [취소]는 고른 행의 원래 값으로 되돌린다. 수정 중에 다른 행을 누르면 바꾼 값이 있을 때 확인을 거친다(취소하면 계속 수정).
- [등록] 모달은 필수 칸에 `required` 와 "(필수)" 표기를 두고 `DetailForm.requireFields($form)` 로 검사한다(빈 칸에 `is-invalid`, "필수 항목을 입력해 주세요.").
- [삭제]는 확인창을 거친다(§5.2). 행을 만들거나 지울 수 없는 화면(비전검사 Overlay 관리 — 행이 곧 비전검사항목)은 [수정]만 둔다.
- 켜고 끄는 값(클라이언트 사용·Overlay 표시)은 체크박스가 아니라 **토글**(Bootstrap `.form-switch` + `.detail-switch` — 입력칸과 같은 32px 줄·44×24 크기, `SF-Custom.css`)이고 옆에 상태를 글로 보인다.
  글 label 에 `data-on="활성화" data-off="비활성화"` 를 두면 `DetailForm` 이 맞춘다.
- 이미지가 있는 상세(비전 검사 이력·비전검사 Overlay 관리)는 왼쪽 이미지 칸(`.detail-image-box`, `SF-Custom.css`)과 오른쪽 표다. 이미지 칸은 표와 같은 높이이고 이미지는 비율을 지켜 담는다.
- 크게 보이는 읽기 전용 이미지 칸(데이터 목록·검수·비전 검사 이력·Overlay 상세)에는 `ImageZoom.attach(칸, 대상)`(`assets/js/image_zoom.js`)을 붙인다 — 휠은 커서 자리를 기준으로 1~8배, 확대한 그림은 끌어서 옮기고, 더블클릭하면 원래 크기다. 클릭이 편집 동작인 칸(라벨링·이미지 편집 창)에는 붙이지 않는다. 라벨링은 자기 배율(50~400%)에 휠·끌어 이동을 따로 둔다(BBOX 를 그릴 때는 휠 버튼으로 끌어 이동).
- 표의 줄 순서는 **판단에 쓰는 값이 위**다(예: 이상 판정 → 상태 → 결과 → 점수 → 식별 정보). 값이 없는 줄은 숨긴다.
- 내부 식별자(요청 ID 등)는 운영에 쓰지 않으면 보이지 않는다. 소수는 필요한 자리까지만(점수·임계값은 셋째 자리).
- 기준 화면은 비전검사 클라이언트 관리다. 사용자·사용자 그룹도 이 구조다. 메뉴명 설정은 한국어 표시값만 고치는 수정 전용 화면이다([수정]만).
  수입검사 품목 지정은 양식(행)을 검사양식 관리에서 만들어 [수정]만 두고, 상세 아래 품목 목록을 수정 중에만 고친다([품목 추가]·행 [삭제] → [저장]).
  검사양식 코드 관리(그룹 → 결과 코드 2단계)도 이 구조다 — 한 목록(트리)에 둘을 보이고 목록 머리에 [그룹 등록]·[결과 코드 등록]과 각자의 등록 모달을 둔다.

### 5.6 모달·확인창

#### 계열

구현체는 세 가지다. 구현을 하나로 모으지 않고 **동작**을 맞췄다. 데이터 화면도 MES 계열을 쓴다.

| 계열 | 구현 | 쓰는 곳 | 여는 법 |
|---|---|---|---|
| 알림·확인 | Bootstrap Modal (`#commonAlertModal`·`#commonConfirmModal`, `common.js` 가 동적 생성) | MES 계열 화면 | `Alert.alert(title, msg, ok)` · `Alert.confirm(title, msg, yes, no)` |
| 팝업 | `PopupDraggable`(`common.js`, Bootstrap Modal + 드래그) | 그리드 컬럼 설정, 내 정보, 사용자 비밀번호 설정, 라벨 편집(관리자 우클릭), 디지털 양식의 창(양식 상세 조회·양식 편집·검사 작성·검사 결과·사진 넣기·WO/자재입고 검색) | `new PopupDraggable(...)` |
| Bootstrap 단독 | `#apiKeyModal`·`#clientCreateModal`·`#clientPackageModal`·`#groupCreateModal`(사용자 그룹 등록)·`#userCreateModal`(사용자 등록)·`#tempPasswordModal`(사용자 등록 뒤 임시 비밀번호), 데이터 화면의 입력 창(`#minorCreateModal`·`#itemCreateModal`·`#itemEditModal`·`#uploadModal`·`#preprocessModal`·`#snapshotCreateModal`), `#productAddModal`(수입검사 품목 지정), `#groupCreateModal`·`#optionCreateModal`(검사양식 코드 관리). 모두 `data-bs-backdrop="static"` | `vision/client.html`, `system/user.html`·`usergroup.html`·`product_form.html`, `dig_form/judge_code.html`, `data/*.html` | `bootstrap.Modal.getOrCreateInstance(el).show()` |

토스트는 `Notify`(`bscommUtil.js`) 하나다. 우하단 `#commonToastContainer` 에 뜬다(라벨링 작업대 포함).

`Alert`·`Notify` 의 메시지는 **글자**로 보인다 — HTML 을 넣어도 태그가 그대로 글자로 나온다. 줄을 바꾸려면 `\n` 을 쓴다
(`Alert` 가 `<br>` 로 바꾼다). 알림·확인창의 한국어는 단어 중간에서 끊기지 않는다(`.common-alert-modal` 의
`word-break: keep-all`). 사용자 값을 화면에 넣는 규칙은 §5.7 이다.

#### 공통 동작

| 항목 | 규칙 |
|---|---|
| 백드롭 | `--modal-backdrop` 하나. 눈에 보이는 실효 알파(색 알파 × opacity)가 0.45 다. 화면 전체를 덮으므로 빨강을 쓰지 않는다 |
| Esc | 닫힌다 (Bootstrap 계열 `keyboard: true`). `PopupDraggable` 은 Esc 도 `close()` 를 거친다 — 화면이 닫기에 "저장하지 않은 내용" 확인을 붙였으면 Esc 에도 묻는다 |
| 백드롭 클릭 | 닫히지 않는다 (Bootstrap 계열 `backdrop: 'static'`). 입력 중이던 폼이 실수로 사라지는 것을 막는다 |
| 포커스 | 열 때 모달 안에 있다 |
| 푸터 | 보조 → 주요 (취소 → 확인) |
| 확인 버튼 | 브랜드 빨강 채움 |
| 알림 아이콘 | 중립(`.text-info` → `--brand-muted`). 빨강이면 단순 안내가 오류로 읽힌다 |

Esc 는 **확인으로 간주되지 않는다.** `Alert.confirm` 은 Esc 로 닫으면 어느 콜백도 부르지 않는다.

#### 어느 것을 쓰나

모든 화면(데이터 관리 포함)의 알림·확인은 `Alert.alert` · `Alert.confirm` · `Notify` 다. 열린 Bootstrap 모달 위에서도 `Alert.confirm` 이 그 위에 뜬다.
입력 창은 Bootstrap 모달 계열(Bootstrap 단독 또는 `PopupDraggable`)로 만든다 — `<dialog>` 의 `showModal()` 은 쓰지 않는다(§8).

#### `verify_modals.py` 가 보는 것

모달을 열어 열림·Esc 닫힘·포커스가 모달 안인지, 백드롭 rgb `(36, 36, 36)`·실효 알파 0.45 ± 0.02, Confirm 버튼 순서(취소 → 확인)와 확인 버튼 `rgb(218, 33, 41)`, Alert 확인 버튼 빨강·아이콘이 보라(`#6451f3`)가 아닌지를 잰다.

여는 모달 목록은 DEVELOPMENT §3 의 `verify_modals.py` 행에 있다.

### 5.7 문구

근거: DECISIONS 사용자 결정 2026-10-06.

#### 어조 — `~합니다`

사용자에게 보이는 문구는 `~합니다` 체로 쓴다. `~해 주세요` 도 된다. `~다`·`~했다`·`~하라` 는 쓰지 않는다.

**`~하세요`·`~할까요?`(해요체)는 이 규칙의 대상이 아니다**. `비전검사항목을 선택하세요.`
같은 짧은 안내와 확인 질문은 그대로 둔다 — `~합니다` 로 바꾸지 않는다.

| 대상 | 대상 아님 |
|---|---|
| `Alert.alert`·`Alert.confirm`·`Notify` | 로그(`logger.*`) |
| API 응답 `message`(두 규약 모두, `/api/v1` 포함) | 주석·docstring |
| 검증 오류 | 커밋 메시지 |
| 빈 화면 안내, 화면 설명, `placeholder` | 문서(`docs/`·이 문서) — 문서체 `~다` |

- **`/api/v1` 메시지도 경어체다.** 계약 문서가 문구를 인용하므로 바꿀 때
  계약 문서(docs/client/SERVER_API_CONTRACT.md)를 함께 고친다. 비전검사 클라이언트는
  `code` 로 분기하므로 `code`·HTTP 상태·`retryable` 은 문구와 함께 바꾸지 않는다.
- **어조 검사 스크립트는 두지 않는다**. 리뷰에서 사람이 본다. 새 코드에서 `~다` 체가 되풀이되기 쉽다.
- 오류 안내에는 예외 원문(`str(ex)`)·영문 메시지를 넣지 않는다. 무엇이 안 됐고 무엇을 하면 되는지를 쓴다.
- 빈 상태는 이유를 쓴다(예: `등록된 라벨 클래스가 없습니다.`, `목록에서 검사를 선택합니다.`).
- 사용자·클라이언트 값은 `.text()` 로 넣는다. 문자열을 이어 `.html()` 로 넣지 않는다.

#### 용어·제목

| 규칙 | 예 |
|---|---|
| 제품 이름은 `제조AI플랫폼` | 탭 제목, 로그인 제목, 로고 `alt` |
| 기능 원본 저장소 이름을 화면·소스에 쓰지 않는다 | `scripts/verify/verify_naming.py` 가 막는다 |
| 관리 단위는 `비전검사항목` 이다. `프로젝트`·`PROJECT` 를 표시하지 않는다 | 데이터 화면 주소는 `?inspection_item=<id>`, 식별자도 `inspection_item`·`inspectionItemId` 다 |
| 영문은 기술 용어·계약 식별자만 남긴다 | `Overlay`, `Client ID`(`X-Client-ID`), `BBOX`, `Polygon mask` |
| 클라이언트 프로그램은 `비전검사 클라이언트` 라고 부른다. 그것을 관리하는 메뉴·화면 이름은 `비전검사 클라이언트 관리` 다 | 메뉴 `wm_vis_client`. 데이터 목록 상세의 "수집" 값 `비전검사 클라이언트`(목록 "수집" 열은 줄여 `클라이언트`)는 프로그램을 가리키므로 그대로다 |
| 같은 대상을 두 이름으로 부르지 않는다 | 메뉴와 화면 제목이 모두 `스냅샷 관리` 다. 정해 둔 말: `아이디`(사번·로그인 ID 아님) · `비밀번호`(패스워드 아님) · 비전검사항목 상태 `사용`/`중지`(활성화·일시 중지 아님) · `객체 탐지`(객체 검출 아님) · `검수 완료`(검수 승인 아님) · 라벨링 `작업 시간`(lease 아님) |

### 5.8 패널 머리와 빈 상태

카드 안 한 덩어리(차트·짧은 표)를 **패널**이라 부른다(대시보드, 비전검사항목 홈). 머리는 왼쪽 `.sub-tit` 제목, 오른쪽 그 패널의 링크·동작이다.

```
.panel-head  ── 제목(.sub-tit) ─────────────────────────── 전체 조회(.panel-link)
             └ 아래 1px --brand-line, 본문과 12px
```

- 오른쪽 링크는 글자 링크(`.panel-link` — `--brand-muted`, hover `--brand-primary`)다. 버튼으로 만들지 않는다.
- 패널 표의 행이 그 대상을 연다면 행 전체가 누르는 곳이다 — `cursor: pointer`, hover 바탕 `--brand-surface-2`(그리드 행 hover 와 같다 — 벤더가 칸 바탕을 `!important` 로 막아 두어 `--ct-table-bg-state` 로 칠한다), `tabindex` 와 Enter. 행이 열어 주면 같은 곳으로 가는 [전체 조회]는 두지 않는다.
- 빈 상태는 이유를 쓰고(§5.7), 이어서 할 일이 있으면 그 화면으로 가는 링크를 둔다(예: `대기 중인 검사가 없습니다.` · 고객사 웹의 공지사항 빈 상태와 같은 방식).

### 5.9 차트

근거: 사용자 결정 2026-10-23(데이터 시각화 규칙 적용). Chart.js(`assets/vendor/chart.js/chart.umd.js`)는 차트가 있는 화면에서만 싣는다.

| 규칙 | 값 |
|---|---|
| **축은 하나다** | 두 값의 단위·크기가 다르면 축을 둘 두지 않고 차트를 나눈다 — 같은 x 축을 쓰는 위아래 작은 차트 둘. **예외**: 대시보드 "최근 7일 검사 완료 · 부적합"은 한 차트에 완료 막대(왼쪽 축)와 부적합 선(오른쪽 축)을 겹친다 — 나누니 동떨어져 보였다(사용자 결정 2026-10-23). 두 축이면 양쪽 축 제목에 단위를 적고, 다른 계열은 막대·선으로 모양을 가른다 |
| 계열 색 | `--chart-1` → `--chart-4` **순서대로**. 걸러져 계열이 줄어도 남은 계열의 색을 바꾸지 않는다(색은 계열을 따른다). 5개를 넘으면 "기타"로 묶는다 |
| 상태색 | 빨강·주황은 계열에 쓰지 않는다(§2.3). 한 계열만 상태를 뜻할 때(예: 부적합)는 `--brand-danger` 를 쓴다 |
| 범례 | 계열이 2개 이상이면 둔다(위 오른쪽). 1개면 두지 않고 제목이 이름이다 |
| 막대 | 굵기 최대 36px, 데이터 끝 4px 둥글게(`borderRadius: 4`, 바닥 쪽은 각지게), 쌓은 막대 사이 2px 흰 틈(`borderColor` 바탕색 · `borderWidth: { top: 2 }`) |
| 선 | 2px, **직선**(`tension: 0`) — 곡선은 점 사이에 없는 값을 그린다. 점 3px |
| 축·격자 | x 격자 없음, y 격자 `--brand-line`, 축 제목에 단위(`완료(건)`) |
| 툴팁 | 같은 x 의 모든 계열(`mode: 'index'`) |
| 글자 | 값·축·범례 글자는 글자 토큰(`--brand-muted`)이다. 계열 색으로 글자를 칠하지 않는다 |
| 빈 차트 | 축을 그리지 않고 한 줄 안내(`최근 7일 기록이 없습니다.`) |

차트 계열 색을 바꿀 때는 팔레트 검증(명도 범위·채도 하한·색각 이상 구분 ΔE 8 이상·정상 시각 ΔE 15 이상)을 통과한 값만 쓴다.
지금 4색은 흰 바탕에서 모두 통과하고, 대비 경고(3:1 미만 2색)는 범례로 보완한다.

### 5.10 데이터 표기

| 항목 | 규칙 | 예 |
|---|---|---|
| 천 단위 | 쉼표 | `1,284건` |
| 단위 | 수치에 붙이고, 요약 띠는 작게 회색으로 | `97건`, `등록(장)` |
| 날짜 | `YYYY-MM-DD` | `2026-10-23` |
| 일시 | `YYYY-MM-DD HH:mm`. 초는 로그·이력 상세에만 | `2026-10-23 10:29` |
| 짧은 날짜(축·카드) | `MM/DD`, `MM-DD HH:mm` | `10/23` |
| 소수 | 필요한 자리까지(점수·임계값 셋째 자리, §5.5) | `0.873` |
| 값 없음 | `-` | |

## 6. 한국어 전용 화면

근거: DECISIONS DEC-021.

다국어는 **내부 기능으로 남기고 화면에는 한국어만** 내보낸다. 다국어 표·모델·API·관리자 화면은 그대로 있고, **고르는 수단만** 없다.

- 언어는 `sessionStorage['lang_code']` 하나로 정해지고 기본값은 `i18n.DEFAULT_LOCALE = 'ko-KR'` 이다.
  고르는 수단이 없으므로 항상 한국어다.
- 사용자 언어 설정(`UserProfile.lang_code`)은 저장되지 않는다.
- `page/account/language.html` 은 남아 있지만 여는 트리거가 없다. 되살릴 때를 위해 둔다.
- 라벨 우클릭 편집은 `userinfo.group_code == 'admin'` 일 때만 붙는다.

`verify_korean_only.py` 는 템플릿을 읽어 아래 흔적이 사용자 화면에 있으면 위반으로 잡는다.

| 흔적 | 의미 |
|---|---|
| `data-lang-code` | 언어 선택 항목 |
| `top-language-item` | 상단바 언어 항목 |
| `images/flags/` | 국기 이미지 |
| `lang_list` | 언어 목록 |
| `#lang_select` | 언어 선택 버튼 |

검사에서 빼는 관리자 전용 화면: `system/multi_language.html`(다국어 설정) · `system/menu_language.html`(메뉴명 설정) ·
`page/popup/label.html`(라벨 편집 팝업) · `page/account/language.html`.

다국어를 다시 열 때 볼 것은 STATUS 의 E-1 이다.

## 7. 범위 밖으로 정한 것

| 하지 않는 것 | 이유 |
|---|---|
| 라벨링 작업대 레이아웃 변경 | §1. 3열 작업대(대기열·캔버스·주석 목록)는 작업에 맞춘 구조다 |
| 치수 통일 — 그리드 서체, 라벨링 작업대 안쪽의 도구 버튼 치수 | 치수라 레이아웃이 움직인다 |
| `app.min.css` 수정 | 벤더 테마는 오버라이드로만 다룬다 |
| WeZonGrid 내부 수정 | `--wzg-*` 커스터마이즈 지점으로만 다룬다 |
| 모달 구현체 통일(`PopupDraggable` 을 `<dialog>` 로 등) | `PopupDraggable` 은 드래그가 있고 컬럼 설정·내정보(`parent.modal.close()`)가 프레임을 넘어 쓴다. 동작 통일로 체감 결함은 없어졌다 |
| 백드롭이 셸(상단바·좌측 메뉴·탭바)까지 덮게 하기 | 화면이 iframe 탭이라 백드롭이 프레임 경계를 넘지 못한다. 교차 프레임 연동이 필요하다 |
| 사이드바에 로고 올리기 | 흰 워드마크 변형이 없다 |
| 다크 모드 | 요구에 없다 |
| 반응형·모바일 | 현장 PC 기준 제품이다. 최소 사양 1920 × 911 |
| 고객사 웹의 홍보 요소 — 영문 대문자 머리말(`COMPANY`), 사진 배경 큰 화면, 스크롤 등장 효과, 38~72px 큰 제목, 모든 제목 아래 빨강 짧은 막대 | 업무 도구다. 영문 머리말은 §1·§5.1 이 막고, 강조는 한 곳만 둔다(§1) |
| 고객사 웹의 빨강 `#c52d2f` 를 글자용 토큰으로 두기 | 쓸 곳이 없다. 빨강 글자는 `--brand-primary`(4.96:1)로 충분하다 |

## 8. 확정된 함정

**`showModal()` 로 연 `<dialog>` 위에는 Bootstrap 모달·토스트가 올라오지 못한다.** 열린 `<dialog>` 는
브라우저의 최상위 레이어(top layer)에 놓이고 나머지 문서를 inert 로 만든다. `body` 에 붙는 `Alert.confirm`·
`Notify` 는 z-index 와 무관하게 그 아래에 깔려 보이지도 눌리지도 않는다. 입력 창은 Bootstrap 모달로 만든다 —
Bootstrap 모달 위에는 `Alert.confirm` 이 쌓인다.

**`--ct-*` 매핑은 `:root` 와 `:root[data-bs-theme=light]` 둘 다에 건다.** `data-bs-theme` 는 템플릿이 아니라
벤더 JS 가 런타임에 붙인다. 그 JS 를 싣지 않는 문서에는 속성이 없고, 한쪽만 쓰면 그 문서의 `--ct-*` 가
벤더 기본 보라(`#727cf5`)로 남는다.

**Bootstrap 백드롭 색은 `.modal-backdrop` 요소에서 덮는다.** 벤더가 `--ct-backdrop-bg` 를 그 요소에 선언하므로 `:root` 에서 덮으면 소용없고, `--ct-backdrop-opacity: 1` 로 두어야 알파가 두 번 곱해지지 않는다(§5.6).

**`app.min.css` 가 보라를 하드코딩한 곳이 있다.** `.btn-primary` 는 `--ct-btn-bg: #727cf5` 라 `--ct-primary`
를 따르지 않는다. `SF-Custom.css` 에서 덮었다. `.text-danger` 는 벤더 분홍이 나와 `--brand-danger` 로 덮었다.

**벤더가 링크·버튼의 외곽선을 `!important` 로 끈다.** `app.min.css` 의 `a,button{outline:0!important}` 때문에 포커스 링은
`!important` 와 더 구체적인 셀렉터(`:focus-visible`)로만 그려진다(`SF-Custom.css` 끝). 입력칸은 포커스 때 테두리도 그림자도 바뀌지 않아
테두리를 잉크로 바꾼다.

**`.form-control`·`.form-select` 의 모서리는 벤더가 `.25rem` 으로 박았다.** `--ct-border-radius` 를 따르지 않으므로 `SF-Custom.css` 에서
`var(--radius)` 로 덮는다. `SF-Custom.css` 도 `:root[data-bs-theme=light]` 에서 `--ct-border-radius: 10px` 를 선언하는데, 뒤에 실리는
`tokens.css` 가 `var(--radius)` 로 이긴다.

**`--ct-danger: #2e2e31` 은 죽은 선언이 아니다.** 벤더의 `var(--ct-danger)` 40곳(입력 오류 말풍선·알림 점·
`btn-soft-danger`)이 받는다. 지우면 그곳들이 벤더 분홍으로 바뀐다.

**`app.css` 는 로드되지 않는다.** 템플릿은 `app.min.css` 를 싣는다. `app.css` 는 읽기용 쌍둥이라 고쳐도 반영되지 않는다. 빌드 단계는 없다 — CSS 를 손으로 고쳐 그대로 서빙한다.

**템플릿만 grep 해서 CSS 를 "미사용"으로 판단하지 않는다.** 동적으로 만들어지는 마크업이 있다.

| 규칙 | 왜 살아 있나 |
|---|---|
| `.btn-info` · `.text-info` · `.btn-primary` · `.btn-light` | `common.js` 가 Alert/Confirm 마크업을 동적 생성하며 쓴다 |
| `.toast:not(.show)` | `Notify` 가 토스트를 그때 만든다. 로드 시점 DOM 에는 없다 |
| `select2-container--default` · `simplebar-*` | 벤더 JS 가 런타임에 이름을 이어 붙인다 |

죽은 규칙 판정은 **두 축을 모두** 통과해야 한다 — (1) 브라우저에서 해당 화면들에 `querySelectorAll` 로 하나도
걸리지 않고, (2) 마크업을 넣을 수 있는 곳(템플릿·화면 JS·응답을 만드는 파이썬)에 이름이 없다. 지운 뒤에는 레이아웃 이동 0건을 확인한다.

**서체는 선언이 아니라 계산값으로 확인한다.** `app.min.css` 가 `body` 에 `font-family: var(--ct-body-font-family)` 를
직접 선언해 `:root` 의 `font-family` 상속을 이긴다. 실제 서체는 `getComputedStyle(document.body).fontFamily` 로 본다.

**색만 바꿨다는 것은 스크린샷으로 증명되지 않는다.** 색이 바뀌면 그림이 전부 달라진다. CSS 를 고쳤으면
레이아웃 비교(`verify_layout_stable.py`)로 요소가 움직이지 않았음을 확인한다.

## 9. 체크리스트

### 9.1 화면을 더할 때

근거: DECISIONS 사용자 결정 2026-10-21.

- [ ] 템플릿은 `app/templates/<폴더>/<화면>.html`, `app/layout_page.html` 을 상속한다
- [ ] `domain/gui.py` `menu_init()` 에 화면을, `taskview_menu_code_map()` 에 화면이 부르는 API 를 등록한다
- [ ] 메뉴 행은 `seed_initial.py` `MENU_TREE` 에 더한다 — 공유 개발 DB 에는 담당자가 돌린다
- [ ] **메뉴로 열 수 없는 화면을 두지 않는다** — 화면은 좌측 메뉴 항목이거나 메뉴 화면 안의 탭(§5.1)이다. 다른 화면의 버튼·링크로만 열리는 화면은 두지 않는다(팝업·모달, 메뉴에서 내린 화면은 예외)
- [ ] 화면 제목이 메뉴 이름과 같다
- [ ] 화면 골격(§5.1) — 제목·검색 카드 → (요약 카드) → 목록 → 상세 순서다
- [ ] 버튼은 §5.2 의 클래스만 쓰고, 삭제처럼 되돌릴 수 없는 동작은 `Alert.confirm` 을 거친다
- [ ] 그리드에 `GridUtil.fitWidth`, 쌓이는 목록이면 서버 페이징이다(§5.4)
- [ ] 새 색은 토큰으로 쓰고, 새 클래스·인라인 스타일을 최소로 둔다
- [ ] 색은 의미가 있을 때만 쓰고(§2.3), 새 글자색은 명암비 표(§2.4)를 통과한다
- [ ] 차트는 축이 하나이고 계열 색은 `--chart-*` 순서다(§5.9). 표기는 §5.10
- [ ] Ajax 는 `AjaxUtil.getAsyncData`·`postAsyncData`(동기 Ajax 금지)
- [ ] 화면 문구가 `~합니다` 체이고 정해 둔 말(§5.7)을 쓴다
- [ ] 1920 × 911 과 1366 폭에서 가로 스크롤·잘림이 없다. 디지털 전환 화면은 1024 폭도(`verify_dig_form_width.py`)
- [ ] 버튼·레이아웃 검사 대상에 넣을 화면이면 `verify_buttons.py`·`verify_layout_stable.py` 의 `SCREENS` 에 더한다

### 9.2 화면을 고칠 때

- [ ] 셀·상세 값에 `true`/`false`·코드·영문 내부 값이 보이지 않는다
- [ ] 늘 비는 컬럼·줄이 없고, 판단에 쓰는 값이 위에 있다
- [ ] 요약 카드 이름에 범위가 적혀 있다
- [ ] 같은 대상의 이름이 메뉴·제목·버튼·확인창에서 같다
- [ ] 오류·빈 상태 문구가 원인과 할 일을 말한다
- [ ] 사용자 값은 `.text()` 로 넣는다
- [ ] `/api/v1`·`/api/v1/datasets` 응답 문구는 바꾸지 않았다(바꾸면 계약 문서도 고친다)
- [ ] CSS 를 고쳤으면 레이아웃 비교로 요소가 움직이지 않았음을 확인했다
- [ ] 그리드 머리 이름을 바꿨으면 `domain/_sql/i18n/020_template_grid_columns*.sql` 도 맞췄다
- [ ] 키보드로 옮겨 다닐 때 버튼·링크·탭에 포커스 링이 보인다

### 9.3 돌리는 검증

```bash
python scripts/verify/verify_tokens.py          # 색·서체 하드코딩
python scripts/verify/verify_korean_only.py     # 언어 변경 수단 노출
python scripts/verify/verify_naming.py          # 제품 이름
node scripts/verify/verify_screen_js.js         # 화면 JS 문법
python scripts/verify/verify_menu.py            # 화면 ↔ 메뉴
python scripts/verify/verify_permission_map.py  # API ↔ 메뉴 권한
python scripts/verify/verify_buttons.py         # 버튼 형태 (서버 필요)
python scripts/verify/verify_modals.py          # 모달 동작 (서버 필요)
```

e2e 는 고친 화면을 지나는 파일만 돌린다. 레이아웃 비교(`verify_layout_stable.py`)와 테스트 절차는
DEVELOPMENT 에 있다.
