# 현행 문서 최신화 (2026-10-07 기능 개발 반영) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2026-10-07 에 넣은 기능(그리드 폭 채움·페이징·상세 영역·클라이언트 삭제·Overlay/매핑 구조, 첫 화면, 라벨링 워크플로우)이 현행 문서 전체에서 사실과 맞게 한다.

**Architecture:** 코드는 바꾸지 않는다. 기능을 넣으며 바로 고친 문서(FEATURES·UI_GUIDE §1·§4.4·STATUS·DATA_MODEL 마이그레이션 표·ARCHITECTURE API 표)는 그대로 두고, **감사에서 빠진 곳**만 고친다. 결정은 DECISIONS 가 정본이므로 결정 기록을 먼저 넣고, 다른 문서는 그것을 가리킨다.

**Tech Stack:** Markdown. 검증은 `scripts/verify_links.py`·`verify_naming.py`·`verify_korean_only.py` 와 `grep`.

**Spec:** 이 계획의 "감사 결과" 절. 근거는 보관한 계획 [2026-10-07-grid-common.md](../../archive/superpowers/plans/2026-10-07-grid-common.md)·[2026-10-07-labeling-workflow.md](../../archive/superpowers/plans/2026-10-07-labeling-workflow.md) 와 커밋 `e915a83`~`727f7e3`.

## Global Constraints

- 새 문서를 만들지 않는다. 같은 내용을 두 곳에 쓰지 않는다 — 한 곳에 쓰고 나머지는 링크한다(docs/README.md 끝 문장)
- `docs/archive/` 는 고치지 않는다
- 문서 본문은 지금 문서의 `~한다` 체를 따른다(`~합니다` 체는 사용자에게 보이는 문구 규칙이다)
- 제품 이름은 제조AI플랫폼. 원본 저장소 이름을 쓰지 않는다(`verify_naming.py`)
- 커밋 메시지는 한국어, `docs:` type. main 에 직접 커밋하지 않는다(브랜치 `docs/refresh-2026-10-07`)

---

## 감사 결과 (2026-10-07)

현행 문서(README.md, docs/*.md, docs/client/*.md, docs/superpowers/plans/*.md)에서 이번 변경과 어긋나는 곳.

| # | 문서 | 위치 | 지금 | 맞는 사실 |
|---|---|---|---|---|
| A-1 | DECISIONS | §8 | 이번 사용자 결정(첫 화면·폭 채움·페이징 정책·상세 영역 구조·클라이언트 삭제·Overlay 삭제 없음)이 없다 | 결정의 정본이 비어 있다 |
| A-2 | DECISIONS | DEC-022 | "품질 점검·Export 는 `BackgroundJob`…" | 품질 점검은 `0011` 에서 지웠다. 작업은 스냅샷 Export 하나다 |
| A-3 | DEVELOPMENT | §2.1 | "18개 파일, **142건**(2026-10-06)" | 25개 파일, 247건(2026-10-07) |
| A-4 | DEVELOPMENT | §2.2 | "6개 파일 … **89건** 수집" | 8개 파일(`test_grid_common`·`test_detail_form` 추가), 127건 |
| A-5 | DEVELOPMENT | §2.2 | "화면에 삭제 기능이 없는 것(Client 자격증명·검사 기록)은 `manage_shell` 로" | Client 는 화면 삭제가 있다(검사 기록이 없을 때만). 검사 기록만 화면 삭제가 없다 |
| A-6 | DEVELOPMENT | §2.2 | `page.route` 로 쓰기를 끊는 규칙만 있다 | 끊은 경로는 픽스처 정리 요청도 끊는다 — `finally` 에서 `unroute` (이번에 실제로 E2E 데이터가 남았다) |
| A-7 | DEVELOPMENT | §2.3 10단계 | "`E2E-MANUAL` 사용 중지" | [수정] → "사용" 해제 → [저장]. 검사 기록이 있어 [삭제]는 거절된다 |
| A-8 | DEVELOPMENT | §1.3 | 다른 PC 접속은 주석 한 줄. 끄는 법이 없다 | `0.0.0.0` + `ALLOWED_HOSTS` + 방화벽, 끄는 명령(`Ctrl+C`·`pkill -f "manage.py runserver 127.0.0.1:8123"`) |
| A-9 | DEVELOPMENT | §5 | 이번에 밟은 함정이 없다 | 정적 JS `?v=` 캐시, 서버 모드 그리드의 첫 조회·내보내기, `BindDataForm` 의 disabled·체크박스, `rowIdField` 없는 `setSelectionByRowId`, `GridUtil` 재선언 |
| A-10 | README | 할 수 있는 것·띄우기 | 첫 화면·클라이언트 등록/수정/삭제가 없다. `runserver 0.0.0.0:8123` 뒤 "`127.0.0.1` 에 접속" | 첫 화면은 검사 결과/이력. 다른 PC 는 `http://<서버 IP>:8123/` |
| A-11 | ARCHITECTURE | §6 화면층·§2 고칠 때 보는 곳 | 그리드·상세 공통 도우미가 없다 | `GridUtil`(`grid.js`)·`AjaxUtil.gridRemoteSource`·`DetailForm`(`common.js`) |
| A-12 | UI_GUIDE | §4.1 표 예시 | 보조 "사용/중지" | 그 버튼은 없어졌다(필드로 옮김). 보조 예시는 "수정, 취소" |
| A-13 | UI_GUIDE | §9 `--ct-*` 함정 | "데이터 셸은 그 JS 를 싣지 않아" | 데이터 셸은 지웠다(2026-10-07). 지금도 맞는 일반 원칙만 남긴다 |
| A-14 | docs/README | 현행 문서 표 UI_GUIDE 행 | "디자인 토큰, 로고, 버튼 역할, 모달·확인창, 문구 어조" | + 그리드 공통(폭·페이징)·상세 영역 구조 |
| A-15 | DATA_MODEL | `VisionClient` 행 | 삭제 규칙이 없다 | 검사 기록이 있으면 못 지운다(`vision_inspection.client` PROTECT), 지우면 서비스 계정도 지운다 |
| A-16 | DEPLOYMENT | §4 업데이트 | 마이그레이션 주의가 없다 | `0012` 는 `vision_inspection` 에 인덱스를 만든다(쓰기가 잠깐 막힌다) — 업무 외 시간 |
| A-17 | 후속 계획·STATUS | `2026-10-06-client-requests-followup.md:117`, STATUS §3-5 | 검사항목 3 Overlay 를 "관리 화면에서 삭제" | 화면에 [삭제]가 없다. **방법은 사용자 결정 필요**(Task 5) |

**고치지 않는 것(맞다):** "라벨링 대기열"(STATUS:17·DEPLOYMENT:340·계약 SERVER_API_CONTRACT:353 — 라벨링 작업대의 이미지 목록을 뜻한다, 지운 "작업 대기열" 화면이 아니다), 계약 §9 "지금 등록된 Overlay"(Task 5 결정 뒤에만 바뀐다), AGENTS.md(규칙만 적는다 — 그리드 규칙은 UI_GUIDE §1 이 갖는다).

---

### Task 1: DECISIONS — 이번 결정을 정본에 기록한다 (A-1·A-2)

**Files:**
- Modify: `docs/DECISIONS.md` §7 DEC-022 행, §8 표 끝

- [x] **Step 1: 브랜치**

```bash
git checkout -b docs/refresh-2026-10-07
```

- [x] **Step 2: DEC-022 의 "품질 점검" 을 걷는다**

`| DEC-022 | 품질 점검·Export 는 ` → `| DEC-022 | 스냅샷 Export 는 ` (품질 점검은 `0011` 에서 지웠다 — DATA_MODEL 마이그레이션 표). 나머지 문장은 그대로.

- [x] **Step 3: §8 표 끝(마지막 `사용자 결정(2026-10-04·2026-10-06)` 행 다음)에 6행을 더한다**

```markdown
| 사용자 결정(2026-10-07) | 로그인하면 **검사 결과/이력**(`wm_vis_inspection`)이 닫을 수 없는 첫 탭으로 열린다. 시스템 옵션 `main_menu` 기본값이다 | 현장 관리자가 가장 먼저 보는 화면이다. `app/views/__init__.py`·`system_option.py` |
| 사용자 결정(2026-10-07) | 그리드 컬럼은 그리드 폭을 채운다. 남는 폭을 **컬럼 정의 width 비율대로** 나눈다(컬럼 설정에서 저장한 폭이 있으면 그것) | 오른쪽 공백. WeZonGrid 는 고치지 않고 `GridUtil.fitWidth` 로 한다(UI_GUIDE §1·§8) |
| 사용자 결정(2026-10-07) | **서버 페이징은 쌓이기만 하는 5화면** — 메뉴로그·로그인로그·시스템로그(50건)·검사 결과/이력(20건, 기본 최근 7일)·데이터 목록(20건). 최신순 고정이라 헤더 정렬을 끈다. 나머지 목록(검수·스냅샷·검사항목 관리·비전 작은 목록 3개)은 **전부 받아 화면 안 20건**이다(일관성). 시스템 관리의 작은 목록(사용자·사용자그룹·메뉴명 설정)은 나누지 않는다 | 메뉴로그 최근 7일이 7천여 건·1.4MB 였고 검사 이력은 500건에서 소리 없이 잘렸다. 작은 목록을 서버 페이징하면 요청만 는다. 검사 이력은 `created_at` 인덱스(`0012`)와 범위 조건을 함께 둔다 |
| 사용자 결정(2026-10-07) | **비전 검사 관리 화면의 상세 영역은 [등록]·[수정]·[삭제]만** 둔다. 행을 고르면 읽기 전용, [수정]이면 [저장]·[취소]. 상태 전환·재발급은 버튼이 아니라 수정 모드의 필드다(클라이언트 "사용"·API Key [재발급], Overlay "표시", 모델 매핑 "(매핑 없음)"). Overlay 관리·모델 매핑은 행이 곧 검사항목이라 [수정]만 둔다. **시스템 관리 메뉴의 화면은 대상이 아니다** | 화면마다 버튼 구성이 달랐다. 공통 도우미 `DetailForm`(UI_GUIDE §4.4) |
| 사용자 결정(2026-10-07) | 비전검사 클라이언트는 **검사 기록이 없을 때만** 지운다. 서비스 계정(`svc-<id>`)도 함께 지운다. 기록이 있으면 "사용"을 해제한다 | 검사 기록이 클라이언트를 PROTECT 로 가리킨다(이력 보존). 서비스 계정을 가리키는 업로더 등은 SET_NULL 이다 |
| 사용자 결정(2026-10-07) | Overlay 는 지우지 않는다. 숨기려면 "표시"를 해제한다 — 클라이언트에는 없는 것과 같다(DEC-C14) | 행이 곧 검사항목이다. 이미지 교체 때 옛 파일은 지운다 |
```

- [x] **Step 4: 검증**

```bash
.venv/bin/python scripts/verify_links.py && .venv/bin/python scripts/verify_naming.py
grep -n "품질 점검·Export" docs/DECISIONS.md   # 0건
```

- [x] **Step 5: 커밋**

```bash
git add docs/DECISIONS.md
git commit -m "docs: 첫 화면·그리드·페이징·상세 영역·클라이언트 삭제 결정을 DECISIONS 에 기록한다"
```

### Task 2: DEVELOPMENT — 테스트 규모·e2e 규칙·서버 띄우기·개발 함정 (A-3~A-9)

**Files:**
- Modify: `docs/DEVELOPMENT.md` §1.3, §2.1 끝 문장, §2.2 표·규칙 목록, §2.3 10단계, §5 끝

- [x] **Step 1: 숫자를 실제로 다시 센다(문서에 적기 직전)**

```bash
ls tests/test_*.py | wc -l                                                   # 기대 25
.venv/bin/python manage.py test tests --settings=configurations.test_settings 2>&1 | grep "^Ran"   # 기대 247
.venv/bin/python -m pytest tests/e2e --collect-only -q -p no:cacheprovider | tail -1                # 기대 127
```

값이 다르면 실제 값을 쓴다.

- [x] **Step 2: §2.1·§2.2 숫자**

- §2.1: `현재 \`tests/\` 아래 18개 파일, **142건**이다(2026-10-06 실행, 0.4초).` → `현재 \`tests/\` 아래 25개 파일, **247건**이다(2026-10-07 실행, 1.3초).`
- §2.2 규모 행: `6개 파일(…), **89건** 수집` → `8개 파일(\`test_crud\`·\`test_menu\`·\`test_workflow\`·\`test_write_paths\`·\`test_image_fit\`·\`test_client_workflow\`·\`test_grid_common\`·\`test_detail_form\`), **127건** 수집(전체 약 11분)`

- [x] **Step 3: §2.2 규칙 목록 두 곳**

`page.route` 항목 끝에 한 문장을 더한다:

```markdown
  끊은 경로는 같은 페이지의 픽스처 정리 요청도 끊는다 — 테스트 안에서 `try/finally` 로 `page.unroute(pattern)` 한다
  (`test_detail_form.test_검사_기록이_있어_삭제를_거절하면_사유를_보인다`).
```

`화면에 삭제 기능이 없는 것(Client 자격증명·검사 기록)은 …` 항목을 바꾼다:

```markdown
- 화면에 삭제 기능이 없는 검사 기록은 `conftest.manage_shell` 로 지운다. Client 는 검사 기록이 없을 때만 지워지므로
  검사 기록 → 검사항목 → Client 순이다(`test_client_workflow.workflow`). 검사 기록이 없는 E2E Client 는
  `/api/vision/client?action=delete` 로 지운다(`test_detail_form.clients`).
```

- [x] **Step 4: §2.3 10단계**

`10. **정리** — 비전검사 클라이언트 화면에서 \`E2E-MANUAL\` 사용 중지, 검사항목은 …` →

```markdown
10. **정리** — 비전검사 클라이언트 화면에서 `E2E-MANUAL` 을 골라 [수정] → "사용" 해제 → [저장](검사 기록이 있어 [삭제]는 거절된다).
    검사항목은 일시 중지 → 삭제 요청 → 승인.
```

- [x] **Step 5: §1.3 표 아래(“검증 스크립트와 e2e 는 주소 … 포트를 바꾸지 않는다.” 다음)에 더한다**

```markdown
**다른 PC 에서 열기.** `127.0.0.1` 로 띄우면 그 PC 안에서만 열린다. `runserver 0.0.0.0:8123` 으로 띄우고
`http://<서버 IP>:8123/` 로 연다. 그 IP 가 `.env` 의 `ALLOWED_HOSTS` 에 있어야 하고(없으면 400), 방화벽이 8123 을
막지 않아야 한다(`sudo ufw status`). 개발 서버이므로 내부망에서만 쓴다(DECISIONS DEC-C7).

**끄기.** 터미널에서 띄웠으면 `Ctrl+C`. 백그라운드로 띄웠으면
`pkill -f "manage.py runserver 127.0.0.1:8123"`(주소까지 넣는다 — 같은 PC 의 다른 프로젝트 `manage.py` 를 건드리지 않는다).
`pgrep -af "runserver 127.0.0.1:8123"` 가 비면 꺼진 것이다. 자동 재시작 자식 프로세스가 하나 더 있다.
```

- [x] **Step 6: §5 끝에 함정 4개를 더한다(5.18 다음, 같은 형식)**

```markdown
### 5.19 정적 JS 를 고치면 `?v=` 를 올린다

- **증상** 고친 `common.js`·`grid.js` 가 브라우저에 반영되지 않는다.
- **원인** 템플릿이 `common.js?v=…`·`grid.js?v=…` 로 싣는다. 같은 값이면 브라우저 캐시를 쓴다. `common.js` 는 `layout_page.html`·`index.html`·`login_mes.html` 세 곳이 싣는다.
- **대처** 고칠 때마다 세 곳의 값을 함께 올린다(`grid.js` 는 `layout_page.html` 한 곳).

### 5.20 서버 모드 그리드는 스스로 첫 조회를 하고 내보내기를 막는다

- **증상** 화면을 열 때 목록을 두 번 받는다. 엑셀 버튼이 아무것도 받지 않는다.
- **원인** WeZonGrid `dataMode:'server'` 는 만들어진 직후 `initial` 조회를 한다. 화면이 [조회]를 바로 부르면 한 번 더 받는다. 서버 모드에서는 `exportToExcel` 이 막혀 있다.
- **대처** 조건이 정해지기 전에는 `gridRemoteSource` 의 조건 함수가 `null` 을 준다(요청하지 않는다). `AjaxUtil.gridResearch` 는 첫 조회 전이면 다시 부르지 않는다. 엑셀은 `GridUtil.exportAll(grid, url, params, fileName)` — 조건 전체를 `export=1` 로 받는다(UI_GUIDE §1).

### 5.21 `FormUtil.BindDataForm` 은 disabled 를 풀고 참/거짓을 체크하지 못한다

- **증상** 읽기 전용으로 둔 칸(Client ID 등)이 행을 고르면 입력 가능해진다. `active: true` 인데 체크박스가 꺼져 있다.
- **원인** `BindDataForm` 이 값을 넣으며 `disabled` 를 지운다. 체크박스는 `value` 문자열(`'on'`)과 비교한다.
- **대처** 상세 영역은 `DetailForm`(UI_GUIDE §4.4)을 쓴다 — 처음부터 막힌 칸은 계속 막고, 참/거짓 값은 `checked` 로 맞춘다. 저장할 때 체크박스는 `'1'`/`'0'` 으로 직접 보낸다(빠지면 서버가 기본값으로 본다).

### 5.22 `setSelectionByRowId` 는 `rowIdField` 가 없으면 조용히 아무것도 안 한다

- **증상** 다시 읽은 뒤 고른 행이 선택되지 않는다. 오류도 없다.
- **원인** WeZonGrid 가 `props.rowIdField` 로 행을 찾는다. 서버 모드가 아닌 그리드는 지정하지 않아도 만들어진다.
- **대처** `GridUtil.setRows(..., {select})`·`DetailForm` 의 선택 복원을 쓰는 그리드에는 `rowIdField` 를 준다(클라이언트 `id`, Overlay·모델 매핑 `item_id`). 그리고 `GridUtil` 은 `grid.js` 가 `let` 으로 선언한다 — 다른 파일에서 같은 이름을 선언하면 모든 화면 스크립트가 멈춘다.
```

- [x] **Step 7: 검증·커밋**

```bash
.venv/bin/python scripts/verify_links.py && .venv/bin/python scripts/verify_korean_only.py
grep -n "142건\|89건\|사용 중지" docs/DEVELOPMENT.md     # 0건
git add docs/DEVELOPMENT.md
git commit -m "docs: DEVELOPMENT 에 테스트 규모·e2e 정리 규칙·다른 PC 접속·그리드 함정을 반영한다"
```

### Task 3: README — 처음 보는 사람의 사실 (A-10)

**Files:**
- Modify: `README.md` "할 수 있는 것" 비전 검사 행, "개발 환경에서 띄우기" 접속 문장

> 작업 트리에 사용자가 고친 README 변경(`runserver 127.0.0.1:8123` → `0.0.0.0:8123`, 커밋 전)이 있다. 되돌리지 않고 이 Task 커밋에 함께 넣는다 — 아래 접속 문장은 그 줄을 전제로 한다.

- [x] **Step 1: 비전 검사 행**

`| **비전 검사** | 검사 결과·이력 조회, 비전검사 클라이언트 관리, Overlay 관리, …` →

```markdown
| **비전 검사** | 검사 결과·이력 조회(로그인 첫 화면, 기본 최근 7일), 비전검사 클라이언트 등록·수정·삭제·API Key 재발급, Overlay 관리, 검사항목↔모델 매핑(모델 목록은 GPU 서버 Wezard 연동 후) |
```

- [x] **Step 2: 접속 문장**

`` `http://127.0.0.1:8123/` 에 접속해 `seed_initial` 로 만든 관리자 계정으로 로그인한다. `` →

```markdown
`http://127.0.0.1:8123/`(다른 PC 에서는 `http://<서버 IP>:8123/` — 그 IP 를 `.env` 의 `ALLOWED_HOSTS` 에 넣는다)에
접속해 `seed_initial` 로 만든 관리자 계정으로 로그인한다. 끄는 법·방화벽은 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) §1.3.
```

- [x] **Step 3: 검증·커밋**

```bash
.venv/bin/python scripts/verify_links.py && .venv/bin/python scripts/verify_naming.py
git add README.md
git commit -m "docs: README 에 첫 화면·클라이언트 관리 범위와 다른 PC 접속을 적는다"
```

### Task 4: 구조·화면·데이터·운영 문서의 남은 곳 (A-11~A-16)

**Files:**
- Modify: `docs/ARCHITECTURE.md` §2 "고칠 때 보는 곳" 표, §6 화면층 표
- Modify: `docs/UI_GUIDE.md` §4.1 표, §9 `--ct-*` 단락
- Modify: `docs/README.md` 현행 문서 표 UI_GUIDE 행
- Modify: `docs/DATA_MODEL.md` `VisionClient` 행
- Modify: `docs/DEPLOYMENT.md` §4 "업데이트"

- [x] **Step 1: ARCHITECTURE §2 "고칠 때 보는 곳" 표 — `| 화면 |` 행 다음에**

```markdown
| 그리드 공통 동작(폭 채움·페이지 유지·엑셀) · 상세 영역 | `app/static/assets/js/grid.js` `GridUtil` · `common.js` `AjaxUtil.gridRemoteSource`·`DetailForm` (규칙은 [UI_GUIDE.md](UI_GUIDE.md) §1·§4.4). 고치면 템플릿의 `?v=` 를 올린다 |
```

- [x] **Step 2: ARCHITECTURE §6 표 — `| 그리드 |` 행을 바꾼다**

```markdown
| 그리드 | WeZonGrid (`app/static/wezongrid/`, 고치지 않는다). 화면 공통 동작은 `GridUtil`(`assets/js/grid.js` — `fitWidth`·`setRows`·`exportAll`)과 `AjaxUtil.gridRemoteSource`·`gridResearch`. 서버 페이징 응답은 `{rows, totalRows}` |
```

그리고 `| 모달 |` 행 다음에:

```markdown
| 상세 영역 | `DetailForm`(`common.js`) — 비전 검사 관리 화면의 [등록]·[수정]·[삭제] 구조(UI_GUIDE §4.4) |
```

- [x] **Step 3: UI_GUIDE §4.1 보조 행 예시**

`| 등록, 닫기, 초기화, 사용/중지 |` → `| 등록, 수정, 취소, 닫기, 초기화 |`

- [x] **Step 4: UI_GUIDE §9 `--ct-*` 단락의 둘째 문장**

`데이터 셸은 그 JS 를 싣지 않아 속성이 없고, 한쪽만 쓰면 그 화면의 \`--ct-*\` 가` →
`그 JS 를 싣지 않는 문서(예: 지운 데이터 셸)에는 속성이 없고, 한쪽만 쓰면 그 문서의 \`--ct-*\` 가`

- [x] **Step 5: docs/README UI_GUIDE 행**

`| 디자인 토큰, 로고, 버튼 역할, 모달·확인창, 문구 어조 |` → `| 디자인 토큰, 로고, 그리드 공통(폭·페이징), 버튼 역할, 상세 영역 구조, 모달·확인창, 문구 어조 |`

- [x] **Step 6: DATA_MODEL `VisionClient` 행 넷째 칸 끝에**

`… 웹 로그인 불가 — DECISIONS Q5) |` → `… 웹 로그인 불가 — DECISIONS Q5). 검사 기록이 있으면 지울 수 없고(`vision_inspection.client` PROTECT), 지우면 서비스 계정도 지운다 |`

- [x] **Step 7: DEPLOYMENT §4 "업데이트" — "메뉴를 바꾼 배포는 …" 단락 다음에**

```markdown
**인덱스를 만드는 마이그레이션은 업무 외 시간에 돌린다.** `0012_vision_inspection_created_at_index` 는
`vision_inspection` 에 인덱스를 만들고, 만드는 동안 그 테이블 쓰기(검사 접수)가 막힌다. 행이 적으면 순간이다.
검사가 수십만 건 쌓인 뒤라면 현장 검사가 멈춘 시간에 돌린다.
```

- [x] **Step 8: 검증·커밋**

```bash
.venv/bin/python scripts/verify_links.py && .venv/bin/python scripts/verify_naming.py && .venv/bin/python scripts/verify_korean_only.py
grep -n "사용/중지\|데이터 셸은 그 JS" docs/UI_GUIDE.md     # 0건
git add docs/ARCHITECTURE.md docs/UI_GUIDE.md docs/README.md docs/DATA_MODEL.md docs/DEPLOYMENT.md
git commit -m "docs: 그리드·상세 영역 도우미 위치, 클라이언트 삭제 규칙, 인덱스 마이그레이션 주의를 반영한다"
```

### Task 5: 검사항목 3 Overlay 정리 방법 (A-17) — **사용자 결정 필요**

**Files:**
- Modify: `docs/superpowers/plans/2026-10-06-client-requests-followup.md:117`
- Modify: `docs/STATUS.md` §3-5 "클라이언트 요청 대기 항목" 행

화면에서 Overlay [삭제]를 없앴다(사용자 결정 2026-10-07). 후속 계획은 "관리 화면에서 삭제"라고 적고 있다. 둘 중 하나로 정한다.

| 안 | 방법 | 결과 |
|---|---|---|
| A (추천) | Overlay 관리 › 검사항목 3 › [수정] → "표시" 해제 → [저장] | 클라이언트에는 없는 것과 같다(DEC-C14, 카탈로그 `version: null`, 이미지 404). 행과 파일이 남아 다시 켤 수 있다 |
| B | `manage.py shell` 로 행과 파일을 지운다 | 완전히 지운다. 화면 밖 작업이라 절차를 문서에 남겨야 한다 |

- [x] **Step 1: 결정을 받는다**
- [x] **Step 2 (A 일 때):** 후속 계획 117행 `| 관리 화면에서 삭제 → §9 "지금 등록된 Overlay" 문장 갱신 |` → `| Overlay 관리 [수정]에서 "표시" 해제 → §9 "지금 등록된 Overlay" 문장 갱신(DEC-C14 — 클라이언트에는 없는 것과 같다) |`. STATUS §3-5 같은 행의 "삭제" → "표시 해제"
- [x] **Step 2 (B 일 때):** 같은 두 곳을 "`manage.py shell` 로 행·파일 삭제(아래 명령)" 로 바꾸고 후속 계획에 명령을 적는다:

```python
from domain.models.vision import VisionOverlay
from domain.tenancy import tenant_atomic
with tenant_atomic():
    row = VisionOverlay.objects.get(item_id=3)
    storage, name = row.image.storage, row.image.name
    row.delete()
storage.delete(name)
```

- [x] **Step 3: 커밋**

```bash
git add docs/superpowers/plans/2026-10-06-client-requests-followup.md docs/STATUS.md
git commit -m "docs: 검사항목 3 Overlay 정리 방법을 화면 구조 변경에 맞춘다"
```

### Task 6: 마무리

- [x] **Step 1: 남은 흔적 검사**

```bash
grep -rnE "사용/중지|표시/숨김|매핑 해제|toggle_active|toggle_visible|500건|142건|89건|품질 점검·Export" README.md docs/*.md docs/client/*.md docs/superpowers/plans/*.md
```

Expected: 0건(이 계획 파일 자신은 제외하고 본다).

- [x] **Step 2: 검증 스크립트**

```bash
for s in verify_links verify_naming verify_korean_only; do .venv/bin/python scripts/$s.py | tail -1; done
```

Expected: 모두 PASS

- [x] **Step 3: 계획 보관·병합**

계획 체크박스를 `[x]` 로 바꾸고 `git mv docs/superpowers/plans/2026-10-07-docs-refresh.md docs/archive/superpowers/plans/` → 커밋 `docs: 끝난 문서 최신화 계획을 보관 폴더로 옮긴다` → `git checkout main && git merge --no-ff docs/refresh-2026-10-07` → `git branch -d docs/refresh-2026-10-07`

---

## 실행 결과 (2026-10-07)

Task 1~6 완료. Task 5 는 A 안("표시" 해제). 계획과 다르게 한 것:

- README 의 사용자 수정(`runserver 0.0.0.0:8123`)은 사용자 요청으로 Task 3 과 따로 먼저 커밋했다.
- DEVELOPMENT §1.3 "끄기"에 `0.0.0.0` 으로 띄운 경우를 덧붙이고 확인 명령을 `pgrep -af "manage.py runserver"` 로 넓혔다 — README 예시가 `0.0.0.0` 이 됐다.
- 계약 §0 "걷는다(§9)" 는 고치지 않았다. 표시 해제도 클라이언트 쪽에서는 걷힌 것과 같다(DEC-C14). §9 "지금 등록된 Overlay" 는 실제로 해제한 뒤 고친다.
- 마무리 검사의 "500건" 1건은 DECISIONS 에 새로 쓴 근거 문장(옛 동작 설명)이라 둔다.
