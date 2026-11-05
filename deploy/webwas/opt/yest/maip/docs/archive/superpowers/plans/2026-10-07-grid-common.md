# WeZonGrid 화면 공통 보완 — 폭 채움 · 상세 영역 등록/수정 구조 · 페이징 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** WeZonGrid 목록이 있는 화면에서 ① 컬럼이 그리드 폭을 채우고, ② 상세 영역이 "읽기 전용 → [수정] → 저장/취소, [등록]은 모달" 한 가지 구조로 동작하고, ③ 목록이 페이지로 나뉘어 처음 열 때 받는 양이 제한되게 한다.

**Architecture:**
- 그리드마다 `WeZonGrid.create` 를 직접 부르고 공통 래퍼가 없다. 공통 동작은 `app/static/assets/js/common.js` 에 작은 도우미로 두고 각 화면이 한 줄로 부른다. `wezongrid.js` 는 고치지 않는다(UI_GUIDE §8 "WeZonGrid 내부 수정 — 범위 밖").
- 많이 쌓이는 목록은 서버 페이징(데이터 관리 화면이 쓰는 `dataMode:'server'` + `AjaxUtil.gridRemoteSource`), 작은 목록은 그리드 안 페이징(`enablePaging`)이다.

**Tech Stack:** Django 5.0.4 · jQuery · Bootstrap 5 · WeZonGrid · Playwright e2e

**Spec:** 사용자 요청(2026-10-07 "위존그리드 적용 화면 전체 공통 보완사항")과 그 확인 답변·2차 보완(아래 "요청")

## Global Constraints

- 사용자 문구는 `~합니다` 체(`~해 주세요` 포함, `~하세요`·`~할까요?` 는 그대로)
- 동기 Ajax 금지. 조회 `AjaxUtil.getAsyncData`, 변경 `postAsyncData`
- 하드코딩 색 금지(`tokens.css`), 새 버튼 클래스 금지 — 주요 `.btn-band`, 보조 `.btn-input`, 위험 `.btn-dell`
- 모달은 Bootstrap `.modal` + `data-bs-backdrop="static"`, 푸터 순서 취소 → 확인(UI_GUIDE §5)
- 마이그레이션은 Django 로만. 테스트는 `--settings=configurations.test_settings`, e2e 는 `E2E-` 데이터만
- 커밋 메시지 한국어, main 직접 커밋 금지

---

## 요청 (확인 답변 반영, 2차 보완 2026-10-07)

| # | 요청 |
|---|---|
| U-1 | 그리드 오른쪽 공백을 없앤다 — 컬럼이 그리드 폭을 채우되 **각 컬럼 정의 width 의 비율대로** 넓힌다 |
| U-2 | 상세 영역에는 **[등록]·[수정]·[삭제] 버튼만** 둔다. 행을 삭제할 수 없는 구조(Overlay 관리·검사항목 모델 매핑)는 [삭제]도 없다. 행을 고르면 필드는 읽기 전용, [수정]을 누르면 [등록]·[수정]·[삭제]가 사라지고 필드가 풀리며 [저장]·[취소]가 나온다. [등록]은 모달이고 필수·선택 값을 모두 받으며 등록할 때 필수 값을 검사한다. **시스템 관리 메뉴의 화면은 대상이 아니다(건드리지 않는다)** |
| U-3 | **메뉴로그·검사 결과/이력·로그인로그·시스템로그·데이터 목록만 서버 페이징**이다. 지금 서버 페이징인 **검수·스냅샷·검사항목 관리는 화면 안 페이징으로 바꾼다**(일관성). 기본 건수는 추천안대로. `vision_inspection` 인덱스 마이그레이션 **승인됨** |
| U-4 | 클라이언트 [삭제]는 제안안대로 새로 만든다. [API Key 재발급]은 수정 모드의 필드 안 버튼으로 둔다. "시스템 관리 화면 제외"는 U-2 에만 해당한다 |

## 조사로 확인한 사실

| 사실 | 근거 | 계획에 미치는 것 |
|---|---|---|
| 22개 화면 모두 컬럼 폭이 고정 px 다. WeZonGrid 에 "남는 폭 채우기"는 없다. 폭을 비운 컬럼은 남은 폭을 균등 분배(최소 100px)하고 `'%'` 도 받는다 | `wezongrid.js:765-819` `_resolveWidths` | 폭 채움은 도우미가 한다 |
| 폭 재계산은 `grid.resize()` 안에서만 한다. 숫자 높이 그리드에는 크기 관찰자가 없어 창·사이드바 폭이 바뀌어도 다시 계산하지 않는다 | `21830`(auto 높이에만 ResizeObserver), `27129-27149` | 도우미가 컨테이너 폭을 관찰한다 |
| 컬럼 설정(9개 화면)은 처음 계산된 px 를 기본값으로 잡고 **설정이 없어도** `setColumnLayout` 으로 다시 넣는다 | `common/columns_setting.html:237,281`, `getColumnLayout` 이 계산된 px 를 돌려줌(`wezongrid.js:26326`) | 비운 폭·`%` 로는 안 된다. 컬럼 설정 적용 **뒤에** 맞춰야 한다 |
| 폭을 바꾸는 공개 API 는 `setColumnWidth(field, px)`(부를 때마다 컬럼 재구성)와 `setColumnLayout` 이다 | `26224`, `26271` | 도우미는 바뀐 컬럼만 `setColumnWidth` 로 고친다(렌더러를 잃지 않는다) |
| 페이징: `enablePaging` 이면 하단 pager(“a ~ b / 총 N건”, 10페이지 버튼, 건수 선택 `pageSizeOptions` 기본 20/50/100). client 모드는 받은 전체를 잘라 보이고, server 모드는 `remoteDataSource.loadRows({page,pageSize,...})` 로 페이지마다 받는다. 트리 모드는 pager 를 숨긴다 | `9494-9498`, `12290-12375`, `23182-23292` | 그대로 쓴다 |
| 처음 열 때 받는 양(실측 2026-10-07, 관리자) | 아래 표 | 서버 페이징 대상 |
| `vision_inspection` 목록은 날짜 기본값이 없고 **소리 없이 500건에서 자른다**. 날짜 조건이 `created_at::date`(인덱스를 못 탄다)이고 `created_at` 단독 인덱스가 없다 | `app/views/vision/inspection.py:49-69`, `pg_indexes` | 서버 페이징 + 날짜 조건 고침 + 인덱스(마이그레이션) |
| 로그 3종은 서버 상한이 없다. `menu_use_log`·`login_log`·`sys_log` 에는 `_created` 인덱스가 있다 | `system.py:619,734`, `menulog.py` | 서버 페이징 |
| 상세 폼 화면은 행을 누르면 바로 편집된다(`FormUtil.BindDataForm` 이 `disabled` 를 푼다). HTML `required` 는 실제로 막지 않는다(`.valid()` 호출 없음) | `common.js:1247-1278` | 읽기 전용·필수 검사를 도우미로 |
| 사용자 등록 시 서버가 돌려주는 임시 비밀번호를 화면이 보여 주지 않는다 | `system/user.html`(읽는 곳 없음), `app/views/system/user.py:45-80` | 시스템 관리 화면이라 이번 범위 밖 — "범위 밖"에 결함으로 남긴다 |
| 사용자를 가리키는 외래키(감사 로그·검사항목·Export 요청자 등)는 모두 `SET_NULL` 이다 | `domain/models/data.py:178,251,301,459,546,583,617` | 클라이언트 삭제 때 서비스 계정을 지워도 다른 행을 막지 않는다(`tenant_atomic` 안에서 지운다) |

### 처음 열 때 받는 양 (실측)

| 화면 | 기본 조건 | 행 | 응답 | 서버 상한 | 성장 |
|---|---|---|---|---|---|
| 메뉴로그 | 최근 7일 | **7,232** | **1.38 MB**, 194 ms | 없음 | 사용자 수 × 화면 열기 |
| 로그인로그 | 오늘 | 322 | 41 KB | 없음 | 로그인 수(기간을 넓히면 수천) |
| 시스템로그 | 오늘·error | 16 | 4 KB | 없음 | 오류 수 |
| 검사 결과/이력 | 기간 없음 | 6 | 2 KB | **500(무표시)** | **Client 전송마다 1건 — 라인당 하루 수천 건 가능** |
| 사용자 / 사용자그룹 / 메뉴명 설정 | — | 4 / 2 / 20 | ≤ 3 KB | 없음 | 거의 고정 |
| 클라이언트 / Overlay / 모델 매핑 | — | 1 / 3 / 3 | ≤ 1 KB | 없음 | 검사항목·현장 PC 수 |
| 검사항목 관리·데이터 목록·검수·스냅샷 | — | 서버 페이징 20 | ≤ 1 KB | 100 | 데이터 목록 외 셋은 Q-4 로 화면 안 페이징으로 바꾼다 |
| 메뉴권한 | 그룹 선택 | 17(트리) | 3 KB | — | 메뉴 수 고정 |

※ 10-06 메뉴로그 2,793건·로그인로그 1,635건은 대부분 e2e·검증 스크립트가 남긴 것이다. 운영에서는 그보다 적지만 상한이 없다는 점은 같다.

---

## 판단

| # | 판단 | 결정 | 이유 |
|---|---|---|---|
| G-1 | U-2 대상 화면 | **비전 검사 관리의 상세 폼 화면 3개** — 비전검사 클라이언트, Overlay 관리, 검사항목 모델 매핑. 시스템 관리 메뉴(사용자·사용자그룹·메뉴명 설정·검사항목 관리 등)는 제외(사용자 결정). 데이터 관리 화면은 상세가 읽기 전용 표이고 등록이 이미 모달이라 대상이 아니다 | 사용자 결정 |
| G-2 | 화면별 상세 버튼 | 클라이언트 [등록][수정][삭제] · Overlay 관리 [수정] · 모델 매핑 [수정] | Overlay·모델 매핑은 행이 곧 검사항목이라 만들거나 지울 행이 없다(사용자 결정: 삭제 제거). [등록]도 같은 이유로 두지 않는다 |
| G-3 | 공통 도우미 | `common.js` 에 `GridUtil.fitWidth(grid)`(폭 채움)와 `DetailForm`(읽기 전용/수정/취소 상태, 필수 검사)을 둔다 | 같은 코드를 화면마다 복사하지 않는다. 래퍼가 없으므로 "만들 때 한 줄 더"로 붙인다 |
| G-4 | 폭 채움 기준 | **컬럼 정의(`columnLayout`)의 width 비율**로 남는 폭을 나눈다. 컬럼 설정에서 폭을 저장한 사용자는 그 저장 폭이 정의를 대신한다. 정의 폭 합이 컨테이너보다 크면 정의 폭 그대로(가로 스크롤). 기준 폭을 한 번 잡아 두고 매번 그것에서 계산한다(폭이 바뀔 때마다 늘어난 값을 다시 늘리지 않는다) | 사용자 결정. 기준을 고정해야 창을 넓혔다 줄여도 비율이 무너지지 않는다 |
| G-5 | 없어지는 버튼의 기능 | 클라이언트 [사용/중지] → 수정 모드의 **"사용" 필드**. Overlay [표시/숨김] → 수정 모드의 **"표시" 필드**, [삭제] → 없앤다(숨기려면 "표시" 해제). 모델 매핑 [매핑 해제] → 수정 모드에서 모델 **"(매핑 없음)"** 을 골라 저장 | 상세 영역 버튼을 셋으로 줄여도 기능은 남긴다. 상태 전환은 필드 값이 더 분명하다 |
| G-6 | 검사 이력 기본 기간 | 최근 7일(요약 카드 `days=7` 과 같다). 날짜 조건을 `created_at >= 시작 00:00, < 끝 다음날 00:00` 범위로 바꾸고 `created_at` 인덱스를 더한다(**승인됨**) | 기간이 없으면 건수 계산이 테이블 전체를 센다. `::date` 는 인덱스를 못 탄다 |
| G-7 | 서버 페이징의 정렬 | 서버 페이징 화면은 헤더 정렬을 끈다(`enableSorting:false`), 최신순 고정 | `gridRemoteSource` 가 정렬을 보내지 않아 지금도 헤더를 눌러도 결과가 같다. 한 페이지만 정렬하면 오해를 산다 |

### 확인 결과 (2026-10-07)

| # | 질문 | 결정 |
|---|---|---|
| Q-1 | 클라이언트 [삭제](지금 없는 기능) | 제안안대로 — 검사 기록이 없을 때만 지운다(서비스 계정도 함께). 있으면 400 "검사 기록이 있어 삭제할 수 없습니다. 사용을 해제해 주세요." |
| Q-2 | [API Key 재발급] 위치 | 제안안대로 — 수정 모드에서만 보이는 "API Key" 칸 옆 [재발급] |
| Q-3 | "시스템 관리 화면 제외"의 범위 | U-2 에만 해당. U-1 은 시스템 관리 화면에도 적용. 사용자·사용자그룹·메뉴명 설정에는 화면 안 페이징을 넣지 않는다 |
| Q-4 | 검수·스냅샷·검사항목 관리(지금 서버 페이징) | **화면 안 페이징으로 바꾼다**(일관성 — 사용자 결정) |

### 페이지 기본 건수 (추천안 적용)

| 묶음 | 화면 | 방식 | 기본 건수 | 건수 선택 | 근거 |
|---|---|---|---|---|---|
| 기록 조회 | 검사 결과/이력 | 서버 | **20** | 20·50·100 | 그리드 높이 340px 에 약 9행 → 20건은 스크롤 두 번 분량. 행을 골라 이미지를 보는 화면이라 한 페이지를 훑고 넘긴다. 데이터 화면(20)과 같은 감각 |
| 로그 | 메뉴로그(목록)·로그인로그·시스템로그 | 서버 | **50** | 50·100·200 | 그리드 높이 500~600px 에 16~18행 → 50건은 세 화면 분량. 로그는 길게 훑는 용도라 넘김을 줄인다. 행 약 190B → 50건 약 10KB(지금 메뉴로그 1.38MB 의 1% 미만) |
| 데이터 | 데이터 목록 | 서버 | **20(유지)** | 20·50·100 | 이미 서버 페이징이다. 썸네일 행(48px)이라 한 페이지 무게를 작게 둔다 |
| 데이터 (전환) | 검수·스냅샷·검사항목 관리 | **화면 안** | **20** | 20·50·100 | 지금과 같은 20건. 한 번에 다 받고 화면이 나눈다(Q-4). 검사항목·스냅샷은 수십 행이다. 검수 대기는 "제출됐지만 검수 전"인 이미지만이라 검수 속도만큼만 쌓인다 — 1,000행이어도 약 300KB |
| 작은 목록 | 비전검사 클라이언트·Overlay 관리·검사항목 모델 매핑 | 화면 안 | **20** | 20·50·100 | 지금 1~3행, 앞으로도 현장 PC·검사항목 수만큼(수십 행). 한 번에 받아도 수 KB 라 서버 페이징은 요청만 늘린다. 20건이면 대부분 한 페이지 |
| 손대지 않음 | 메뉴로그 집계 탭(32행) | — | — | — | 기간·메뉴·사용자로 묶은 집계라 행 수가 "메뉴 × 사용자"를 넘지 않는다 |
| 손대지 않음 | 시스템 관리의 작은 목록(사용자·사용자그룹·메뉴명 설정) · 메뉴권한(트리) | — | — | — | Q-3 |

**최적화 판단**
- **좋은 판단인 부분:** 병목은 "상한 없는 누적 테이블을 처음부터 통째로 받는 것"이다. 로그 3종과 검사 이력을 서버 페이징으로 바꾸면 첫 응답이 최대 50행으로 고정되어, 데이터가 늘어도 화면 열기 시간이 일정하다(메뉴로그 1.38MB → 약 10KB). 작은 목록까지 서버 페이징하면 요청 수만 늘고 검색 반응이 느려지므로 화면 안 페이징이 맞다.
- **같이 해야 효과가 나는 부분:** 서버 페이징은 페이지마다 `count(*)` 와 `ORDER BY ... LIMIT` 을 한다. 기간 조건이 인덱스를 타야 이 두 쿼리가 싸다. 로그 3종은 `_created` 인덱스가 이미 있다. 검사 이력은 G-6(범위 조건 + `created_at` 인덱스)이 없으면 건수 계산이 테이블 크기에 비례해 느려진다.
- **화면 안 페이징으로 바꾸는 검수 목록의 한계:** 검수가 오래 밀리면 처음 열 때 받는 양이 대기 건수에 비례한다(1,000행 약 300KB, 5,000행 약 1.5MB). 대기 수천 건이 일상이 되면 그 화면만 서버 페이징으로 되돌린다 — API 의 `{rows, totalRows}` 모양을 유지하므로 되돌리기 쉽다.
- **한계:** 아주 뒤쪽 페이지(OFFSET 이 수만)는 PostgreSQL 이 앞 행을 건너뛰며 읽어 느려진다. 기간 기본값(오늘·7일)이 범위를 좁혀 주므로 지금 규모에서는 문제 되지 않는다. 수십만 건을 넘기면 "마지막으로 본 시각 이후" 방식(keyset)으로 바꾼다 — 이번 범위 밖.

---

# 단계 ① `feat/grid-fit-width` — U-1

### Task 1: 컬럼이 그리드 폭을 채운다

**Files:** `app/static/assets/js/common.js`(`GridUtil.fitWidth`), `app/templates/common/columns_setting.html`(설정 적용 뒤 호출), 메뉴에 보이는 그리드 화면 15개(시스템 관리 8 — 검사항목 관리 포함, 비전 4, 데이터 3 — Q-3). 한 화면에 그리드가 둘인 곳(메뉴로그·메뉴명 설정)은 둘 다, Test: `tests/e2e/test_grid_common.py`(신규)

**Interfaces:** Produces `GridUtil.fitWidth(grid)` — 기준 폭은 컬럼 정의(`columnLayout`) width 이고 컬럼 설정 저장 폭이 있으면 그것이다(G-4). 보이는 컬럼(행번호·체크 같은 extra 제외)의 기준 폭 합이 컨테이너보다 작으면 남는 폭을 기준 폭 비율대로 나눠 `setColumnWidth` 로 반영하고, 크면 기준 폭 그대로 둔다. 처음 한 번 맞추고, 컨테이너에 `ResizeObserver` 를 붙여 폭이 바뀔 때마다 다시 맞춘다(같은 그리드에 두 번 붙이지 않는다). 사용자가 컬럼 경계를 끌어 폭을 바꾸면 그 뒤로는 늘리지 않는다

- [x] **RED** — e2e: 메뉴에 보이는 그리드 화면 15개를 1920×911 로 열고 각 그리드의 마지막 헤더 셀 오른쪽 끝이 그리드 오른쪽 끝과 2px 안이다. 두 컬럼의 폭 비가 정의 width 비와 같다(±2%). 사이드바를 접어(셸 폭 변화) 다시 같은 검사. 지금은 검사 이력이 약 580px 비어 실패한다
- [x] **GREEN** — 도우미 구현 → 각 화면 `WeZonGrid.create` 다음 줄에 `GridUtil.fitWidth(this.grid)`. 컬럼 설정 화면은 `_applyColumnData` 끝(`setColumnLayout` 다음)에서도 부른다
- [x] 렌더러(썸네일·받기 링크)·고정 컬럼(메뉴권한 `fixedColumnCount:1`)이 그대로인지 화면 캡처로 본다. `verify_layout_stable` 은 그리드 컬럼 폭이 의도적으로 바뀌므로 그리드 바깥 요소만 비교한다
- [x] 커밋 `feat: WeZonGrid 컬럼이 그리드 폭을 채운다` → 단위·검증 스크립트·e2e → main 병합

# 단계 ② `feat/grid-paging` — U-3

### Task 2: 검사 결과/이력 서버 페이징 (G-6)

**Files:** `app/views/vision/inspection.py`(`_list`), `domain/models/vision.py`(+ 마이그레이션: `created_at` 인덱스), `app/templates/vision/inspection.html`, Test: `tests/test_vision_inspection_filters.py`

- [x] **RED** — 단위: 25건을 만들고 `page=2&page_size=20` → `{rows: 5행, totalRows: 25}`. 날짜를 비우면 최근 7일만. `date_to` 당일 23:59 건이 들어간다(범위 조건). 500건 상한이 사라진다
- [x] **GREEN** — `app/views/item/__init__.py` 의 `page_params`/`paged` 와 같은 규칙(최대 100)으로 `{rows, totalRows}`. 날짜는 `created_at__gte`·`created_at__lt` 범위. 마이그레이션 `AddIndex(fields=["-created_at"])`(**사용자 승인 2026-10-07**)
- [x] 화면: `dataMode:'server'`, `rowIdField:'id'`, `remoteDataSource: AjaxUtil.gridRemoteSource(...)`, `pageSize:20`, `enableSorting:false`. 검사일 기본값을 최근 7일로 채운다. [조회]는 `AjaxUtil.gridResearch`
- [x] 커밋 `feat: 검사 결과/이력을 서버 페이징하고 기본 기간을 최근 7일로 한다`

### Task 3: 로그 3종 서버 페이징

**Files:** `app/views/system/menulog.py`·`loginlog.py`·`systemlog.py`, `domain/services/system.py`(`get_loginlog_list`·`get_systemlog_list`), 템플릿 3개, Test: 단위(SQLite 로 되는 ORM 경로) + e2e(raw SQL 경로)

- [x] **RED** — e2e: 메뉴로그를 열 때 `log_list` 응답이 50행 이하이고 `totalRows` 가 있다. 2페이지로 가면 다음 50행이다. 로그인로그·시스템로그도 같다
- [x] **GREEN** — raw SQL 에 `count(*) over()` 대신 별도 `count(*)` + `LIMIT %(limit)s OFFSET %(offset)s`(파라미터 바인딩). 응답 `{rows, totalRows}`. 화면은 서버 모드, `pageSize:50`, `pageSizeOptions:[50,100,200]`, 정렬 끔. 메뉴로그 집계 탭은 그대로
- [x] 엑셀 내보내기 버튼이 있는 화면은 "현재 조건 전체"를 따로 받아야 한다 — 지금 동작(받은 행 전체)을 확인하고 조건 전체 내보내기로 맞춘다
- [x] 커밋 `feat: 메뉴·로그인·시스템 로그를 서버 페이징한다`

### Task 4: 검수·스냅샷·검사항목 관리를 화면 안 페이징으로 (Q-4)

**Files:** `app/views/item/review.py`·`snapshot.py`·`item_admin.py`(목록 action), `app/templates/data/review.html`·`snapshot.html`·`item_list.html`, Test: `tests/test_item_api.py`

**Interfaces:** 세 목록 API 는 응답 모양 `{rows, totalRows}` 를 유지하고 **조건에 맞는 행 전부**를 준다(`page`·`page_size` 를 무시). 데이터 목록(`image.py`)만 `paged()` 를 계속 쓴다

- [x] **RED** — 단위: 행 25개를 만들고 `list` 를 부르면 `len(rows) == totalRows == 25`(세 API 각각). 기존 `page_size=1` 기대 테스트(`tests/test_item_api.py:185`·`433` 부근)는 새 동작으로 바꾼다
- [x] **GREEN** — 세 모듈이 `paged()` 대신 전부를 직렬화한다. `snapshot.py` 의 `page_params(default_size=10)` 도 걷는다. `paged`·`page_params` 는 `image.py` 가 계속 쓴다
- [x] 화면: `dataMode:'server'`·`remoteDataSource` 를 걷고 `enablePaging:true, pageSize:20`, 조회는 `AjaxUtil.getAsyncData` → `grid.setData(res.rows)`. 화면별로 서버 모드에 기대던 곳을 바꾼다
  - 검수: 처리 뒤 다음 행 선택이 "현재 페이지 행"이 아니라 받은 전체에서 고른다(`this.rows`). 다시 읽은 뒤 **같은 페이지**에 머문다
  - 스냅샷: 진행 중인 행이 있을 때의 3초 다시 읽기가 페이지·선택 행을 잃지 않는다(다시 읽은 뒤 페이지·선택 복원). 상세 영역이 깜박이지 않는다
  - 검사항목 관리: 상태 전환·삭제 승인 뒤 다시 읽어도 선택한 행과 페이지를 유지한다
- [x] e2e: 세 화면 하단에 "총 N건" pager, 25건이면 2페이지. 검수에서 1페이지 마지막 행을 처리하면 다음 행(2페이지 첫 행)이 열린다. 기존 `TestDataPipeline`·`test_client_workflow` 가 그대로 통과한다
- [x] 커밋 `refactor: 검수·스냅샷·검사항목 관리 목록을 화면 안 페이징으로 바꾼다`

### Task 4b: 비전 검사 작은 목록 화면 안 페이징

**Files:** `vision/client.html`·`overlay.html`·`model_mapping.html`

- [x] 세 화면 `enablePaging:true, pageSize:20`. 클라이언트 화면은 검색어가 API 로 안 가던 것(조사 결과)을 함께 고친다
- [x] e2e: 각 화면 하단에 "총 N건" pager
- [x] 커밋 `feat: 비전 검사 작은 목록에 그리드 안 페이징을 켠다` → 단계 ② 마무리(단위·검증 스크립트·e2e 전체)·병합

# 단계 ③ `feat/detail-form` — U-2

### Task 5: 공통 상세 영역 도우미

**Files:** `common.js`(`DetailForm`), Test: `tests/e2e/test_grid_common.py`

**Interfaces:** `DetailForm.create({form, btnCreate, btnEdit, btnDelete, btnSave, btnCancel, onSave})` — 상태 `empty`(고른 행 없음)·`view`(읽기 전용)·`edit`(수정 중).
- `bind(row)` 는 값을 넣고 `view`. [수정]은 `edit`(원래 값 보관), [취소]는 원래 값으로 되돌려 `view`, [저장] 성공 시 `view`
- `edit` 동안 [등록]·[수정]·[삭제]를 숨기고 [저장]·[취소]를 보인다. `view`·`empty` 에서는 반대
- [등록]·[수정]·[삭제]는 **늘 켜져 있다**(확인 답변 2). 고른 행 없이 [수정]·[삭제]를 누르면 "목록에서 항목을 선택해 주세요." 를 알리고 아무것도 하지 않는다
- `edit` 중에 목록에서 다른 행을 누르면 바꾼 값이 있을 때 "수정 중인 내용을 버리고 이동할까요?" 확인을 거친다(취소하면 그대로 수정 중)
- 필수 검사 `DetailForm.requireFields($scope)` — `required` 가 붙은 빈 칸에 `is-invalid`, 첫 칸에 포커스, 문구 "필수 항목을 입력해 주세요."

- [x] **RED → GREEN** — 클라이언트 화면에 먼저 붙여 상태 전이를 e2e 로 본다(행 선택 → 입력 불가 / [수정] → 입력 가능·[저장][취소] 보임·[등록][수정][삭제] 숨김 / [취소] → 값 복원 / 행 없이 [수정] → 안내만 / 수정 중 다른 행 → 확인창)
- [x] 커밋 `feat: 상세 영역의 읽기 전용·수정·취소 상태를 공통 도우미로 둔다`

### Task 6: 비전 검사 화면 3개에 적용 (G-1·G-2·G-5, Q-1·Q-2)

화면마다 한 커밋. 공통: 상세 머리에 정해진 버튼만 / 행 선택 → 읽기 전용 / e2e: 수정 → 저장, 수정 → 취소 복원

| 화면 | 상세 머리 | 수정 모드 필드 | 등록 모달 | 없어지는 버튼 → 옮겨 가는 곳 |
|---|---|---|---|---|
| 비전검사 클라이언트 | 등록·수정·삭제 | 이름, **사용**(G-5), API Key 칸 옆 [재발급](Q-2, 수정 모드에서만 — 확인창을 거치고 새 키를 1회 표시) | Client ID·이름(필수). 성공 시 API Key 1회 표시(지금 동작 유지). 필수 빈 채 [등록] → 막힘 | [사용/중지] → "사용" 필드 · [API Key 재발급] → 필드 안 버튼 · [삭제] **새 기능**(Q-1: 서버 `action=delete` — 검사 기록이 없으면 클라이언트와 서비스 계정(`svc-<id>`, `tenant_atomic` 안에서)을 지우고, 있으면 400. 확인창을 거친다. 단위 테스트 2건 먼저) |
| Overlay 관리 | 수정 | 불투명도, 이미지 파일, **표시**(G-5) | 없음 | [표시/숨김] → "표시" 필드 · [삭제] 없앰 |
| 검사항목 모델 매핑 | 수정 | 모델(“(매핑 없음)” 포함), 임계값 재지정 | 없음 | [매핑 해제] → 모델 "(매핑 없음)" 저장(G-5) |

- [x] 서버: 클라이언트 `save` 가 `active` 를, Overlay `save` 가 `visible` 을 받게 한다(지금은 전용 toggle action — 화면에서 안 쓰게 되면 지운다). 모델 매핑 `save` 에 "(매핑 없음)" 이 오면 기존 해제 로직을 탄다. Overlay 가 아직 없는 검사항목은 수정 모드에서 이미지 파일이 필수다. 단위 테스트를 먼저
- [x] 기존 e2e 를 새 구조로 바꾼다 — `TestVisionScreens`(클라이언트 `#btnToggle`·Overlay `#btnToggle`·`#btnDel` 를 누르던 테스트), `test_client_workflow` 의 클라이언트 생성(`/api/vision/client?action=save` 는 그대로). `verify_modals` 의 API Key 창 항목이 그대로 열리는지 본다
- [x] 마무리 — 단위·검증 스크립트 10개(`verify_buttons`·`verify_modals` 포함)·e2e 전체 → UI_GUIDE §4·§5 에 "상세 영역 구조" 규칙, FEATURES §6 화면 설명 갱신 → main 병합

## 범위 밖

- 메뉴에서 내린 화면 7개(코드·업체·부서·단위·프라퍼티·다국어·AI 모델) — U-1~U-3 모두
- 시스템 관리 화면의 상세 영역(U-2)·화면 안 페이징 — 사용자 결정·Q-3. 단, 검사항목 관리 목록은 Q-4 로 화면 안 페이징으로 바꾼다
- **사용자 등록 시 임시 비밀번호가 화면에 나오지 않는 결함** — 시스템 관리 화면이라 손대지 않는다. 따로 정한다
- `wezongrid.js` 내부 수정, keyset 페이징 — 수십만 건이 넘을 때
- 서버 페이징 화면의 헤더 정렬(서버 정렬 전달) — G-7 로 끈다. 필요하면 `gridRemoteSource` 가 `sortKeys` 를 보내게 따로 한다

---

## 실행 결과 (2026-10-07)

단계마다 main 에 병합했다(`feat/grid-fit-width` → `feat/grid-paging` → `feat/detail-form`). 계획과 다르게 한 것:

| 계획 | 실제 | 이유 |
|---|---|---|
| `GridUtil.fitWidth` 를 `common.js` 에 | `assets/js/grid.js` 의 기존 `GridUtil` 에 | `grid.js` 가 `let GridUtil` 을 이미 선언한다. 같은 이름을 `common.js` 에 두면 재선언 오류다 |
| 컬럼 설정 화면에서 `_applyColumnData` 끝에 다시 호출 | `fitWidth` 가 `setColumnLayout`·`resize` 를 감싸 스스로 다시 맞춘다. 컬럼 설정 저장은 늘린 폭이 아니라 정의 폭(`_widthRaw`)을 저장한다 | 숨은 탭을 열 때 화면이 부르는 `resize()` 도 폭을 되돌려서 한 곳에서 막는다 |
| 로그 엑셀 "조건 전체로 맞춘다" | `GridUtil.exportAll` — `export=1` 로 조건 전체를 받아 보이지 않는 client 그리드로 만든다 | WeZonGrid 는 서버 모드 내보내기를 막는다(`_errorServerModeUnsupported`) |
| — | `gridRemoteSource` 는 조건이 `null` 이면 요청하지 않고, `gridResearch` 는 첫 조회 전이면 다시 부르지 않는다 | 서버 모드 그리드가 만들어지며 스스로 첫 조회를 해서 화면을 열 때 목록을 두 번 받았다 |
| 화면 안 페이징 화면의 페이지·선택 유지를 화면마다 | `GridUtil.setRows(grid, rows, {select, firstPage})` 하나 | 검수 다음 행·스냅샷 3초 다시 읽기·검사항목 상태 전환이 같은 동작이다 |
| 검수 "1페이지 마지막 행 → 2페이지 첫 행" e2e | 검사항목 관리 21건 e2e(`test_다시_읽어도_고른_행을_놓치지_않는다`)로 `setRows` 를 본다 | 제출된 이미지 21장을 만드는 비용. 검수 흐름은 `test_client_workflow` 가 본다 |
| Task 5(도우미)와 Task 6 클라이언트를 따로 커밋 | 한 커밋 | 도우미를 클라이언트 화면으로 검증한다 |
| 클라이언트 삭제 거절은 400 | `{"success": false, "message"}`(200) | 비전 화면 MES 규약(`client.py` 의 다른 실패와 같다). 화면은 사유를 알림으로 보인다 |
| — | Overlay `delete`·`toggle_visible`, 클라이언트 `toggle_active`, 매핑 `deactivate` action 을 지웠다 | 화면에서 쓰지 않게 됐다. Overlay 삭제 파일 정리 테스트도 함께 지웠다 |

검증: 단위 247 · 검증 스크립트 10개 · e2e 전체(단계 ② 121, 단계 ③ 127) 통과. 개발 서버가 단계 ② 도중 로그 없이 내려가 한 번 다시 띄웠다(원인 미확인).
