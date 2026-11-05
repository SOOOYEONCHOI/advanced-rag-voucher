# 문서 정리 — "어떻게 만들어졌나"에서 "무엇인가"로 — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 문서를 읽은 사람이 **지금 이 제품이 무엇이고 어떻게 돌고 어떻게 고치는지**를 알게 한다. 구축 과정(원본 3개 비교·이관 계획·Phase 기록)은 본문에서 빼고 보관함으로 옮긴다.

**Architecture:** 주제별 현행 문서 8개 + 외부 계약 2개 + 보관함. 현행 문서는 지금 사실만 쓰고, 왜 그런지는 한 줄 근거와 결정 ID 로 단다. 과거 문서는 고치지 않고 `docs/archive/` 로 옮긴다(원문 보존).

**선행 조건:** R10~R16 과 `/api/v1` 어조 작업이 끝난 뒤. R10~R16 계획이 `USER_DECISIONS.md` 에 §1.66(DEC-C11~C18)을 쓰고 계약 문서를 고친다 — 먼저 옮기면 그 계획의 수정 대상이 사라진다.

## 지금 상태 (2026-10-06 실측)

| 분류 | 파일 | 줄 |
|---|---|---|
| 현행 | AGENTS · README · docs/README · 08 · distribution/README · i18n README | 822 |
| 섞임 | 04 · 05 · 06 · 09 · IMPLEMENTATION_STATUS · SCREEN_MAPPING · USER_DECISIONS | 4,578 (현행 약 1,075) |
| 과거 | 01 · 02 · 03 · 07 · superpowers 계획·설계 10개 | 9,041 |
| 외부 계약 | client/SERVER_API_CONTRACT(서버 소유) · client/SERVER_REQUESTS(클라이언트 소유) | 1,095 |

현행 내용이 약 3,000줄인데 16,600줄 속에 흩어져 있고, 같은 주제가 여러 곳에 있다
(실행·검증 명령 4곳, 운영 전 확인 4곳, GPU Stub 8곳, 배포물 인증 없음 6곳 …).
틀린 사실도 섞였다 — 04 의 없는 `purge_vision_images` 타이머·120회/분 제한, 05 의 DB 이름
`manufacturing_ai_platform`(실제 `yest`)·없는 seed 명령, SCREEN_MAPPING 의 내린 메뉴 4개 등.

## 목표 구조

```text
README.md                    제품 소개 · 빠른 시작 · 문서 지도            (지금 것 다듬기)
AGENTS.md                    고치기 전에 지킬 것(규칙만). 설명은 docs 로 링크
docs/
├─ README.md                 문서 지도
├─ ARCHITECTURE.md           구성 요소 · 세 API 규약 · 2단계 인가 · 단일 조직·RLS ·
│                            작업 큐/워커 · 저장소·파일 제공 · 추론 경계(Stub) · 로그
├─ FEATURES.md               메뉴 트리와 화면별 기능 · 역할(작업자/검사항목 관리자/플랫폼 관리자)
│                            · 데이터 흐름(업로드→라벨링→검수→품질→스냅샷→Export)
├─ DATA_MODEL.md             주요 테이블 · RLS 테이블 21개 · 마이그레이션 규칙 · 시드
├─ DEVELOPMENT.md            개발 환경 · 테스트(단위·e2e 원칙) · 검증 스크립트 10종 · 함정
├─ DEPLOYMENT.md             (08 에서) 설치 · .env · nginx/gunicorn/systemd · 로그·백업 · 운영 확인
├─ UI_GUIDE.md               (09 규칙만) 토큰 · 버튼 역할 · 모달 · 문구 어조 · 범위 밖
├─ DECISIONS.md              지금 유효한 결정만(ID 유지) · 미래 확장 F-1~F-7
├─ STATUS.md                 지금 되는 것 · 알려진 제약 · 남은 일
├─ client/                   외부 계약 — 손대지 않는다(서버 소유 계약 + 클라이언트 요청서)
└─ archive/                  과거 문서 원문(아래 표). README 한 장으로 무엇이 있는지만
```

## 판단 (제안)

| # | 판단 | 제안 | 대안 |
|---|---|---|---|
| D-1 | 과거 문서를 어떻게 | **`docs/archive/` 로 옮긴다**(원문 그대로) | 지운다 — git 이력에만 남는다. 깔끔하지만 git 을 모르는 사람은 못 찾는다 |
| D-2 | `USER_DECISIONS.md`(2,328줄) | **유효한 결정만 `DECISIONS.md` 로 새로 쓴다. ID(O-8·DEC-C2·F-1 …)는 유지**, 원문은 archive | 그대로 둔다 — §2 분석 1,870줄이 현행 문서 속에 남는다 |
| D-3 | 파일 이름 | **번호를 떼고 주제 이름으로**(`08_DEPLOYMENT` → `DEPLOYMENT`) | 번호 유지 — 링크는 안 깨지지만 01~07 이 빠지면 번호가 듬성듬성해진다 |
| D-4 | 변경 이력 | **두지 않는다.** 현행 문서는 지금 사실만, 이력은 git 과 archive | `CHANGELOG.md` 를 둔다 — 정리 대상이 하나 더 생긴다 |
| D-5 | 실행이 끝난 계획(`superpowers/plans`·`specs`) | **archive 로.** 진행 중인 계획만 `superpowers/` 에 남긴다 | 그대로 — 계획 10개(5,800줄)가 docs 의 1/3 이다 |

## 기존 문서 → 새 문서

| 기존 | 현행 내용 → 갈 곳 | 나머지 |
|---|---|---|
| README.md | 다듬어 유지. 9행 "MES 를 복제해" 문장은 한 줄 연혁으로 줄임 | — |
| AGENTS.md | 규칙만 남기고 설명은 ARCHITECTURE·DEVELOPMENT 로 링크. 연혁 문장(3–5, 108–112) 정리 | — |
| 01 · 02 · 03 · 07 | 없음 | archive |
| 04 TARGET_ARCHITECTURE | §7 화면층 · §8 인증·인가 · §10 검사 흐름 · §11 워커 → ARCHITECTURE (틀린 사실은 고쳐서) | 나머지 archive |
| 05 DATABASE_MIGRATION_PLAN | §1 규칙 · §3 RLS · §4 타입 → DATA_MODEL | archive |
| 06 API_COMPATIBILITY_PLAN | §0 규약 → ARCHITECTURE. §2 GPU 계약(미래 설계) → ARCHITECTURE "추론 경계" 절 | §1(계약 초안)은 SERVER_API_CONTRACT 가 대신함 → archive |
| 08 DEPLOYMENT | 거의 그대로 → DEPLOYMENT (§9 N1·N5·N12 정리) | — |
| 09 UI_DESIGN_SYSTEM | §1 결정 · §3 로고 · §4 토큰 · §5 버튼 · §7 범위 밖 · 확정된 함정 → UI_GUIDE | §2 이전 상태 · §6 Phase 기록 · §8 → archive |
| IMPLEMENTATION_STATUS | 요약 · 남은 일 · 운영 전 확인 → STATUS / DEPLOYMENT. 날짜별 기록 중 지금도 유효한 함정은 DEVELOPMENT 로 | 날짜별 기록 → archive |
| SCREEN_MAPPING | §1 메뉴 트리(내린 메뉴 반영) → FEATURES | §2–§5 이관표 → archive |
| USER_DECISIONS | §1 표 중 유효 행 · §1.6 · §1.65 · §1.66 · §1.7 → DECISIONS (ID 유지, 뒤집힌 결정은 최종 형태로) | 전체 원문 → archive |
| superpowers/* | 진행 중 계획만 남김 | 실행 끝난 계획·설계 → archive |
| client/* | 손대지 않음 | — |

## 코드·스크립트가 문서를 가리키는 곳 (옮기면 같이 고친다)

- `scripts/verify_naming.py:37-43` `LIVING_DOCS` — **없는 파일은 조용히 건너뛴다.** 새 현행 문서 목록으로 바꾸고, 목록에 있는 파일이 없으면 실패하게 한다
- `app/views/api_v1.py:7` · `domain/models/vision.py:147` · `tests/test_client_api.py:4` → `docs/client/SERVER_API_CONTRACT.md`(그대로)
- `domain/services/vision/gateway.py:65` → `06 §6`(없는 절. 실제는 §2) → `ARCHITECTURE.md` 추론 경계 절
- `domain/models/data.py:5` · `domain/models/vision.py:4` · `domain/services/data/__init__.py:4` · `domain/services/data/authorization.py:29` · `domain/services/vision/gateway.py:3` → "§1.6 O-8" 등 → `DECISIONS.md` O-8 (ID 를 유지하므로 파일명만)
- `domain/services/data/item_creation.py:3` → 없는 `docs/WORKFLOWS.md` → `FEATURES.md`
- `distribution/README.md` → `../docs/08_DEPLOYMENT.md` → `../docs/DEPLOYMENT.md`
- `docs/README.md:64` → 지워진 `domain/_sql/numeric_scale3/README.md`
- 메모리(`MEMORY.md` 의 항목)가 문서 경로를 가리키면 함께

## 작업 순서

### Task 1: 보관함

- [ ] `git mv` 로 과거 문서를 `docs/archive/` 로(01·02·03·07, 실행 끝난 superpowers 계획·설계, USER_DECISIONS 원문, 04·05·06·09·IMPLEMENTATION_STATUS·SCREEN_MAPPING **원문 사본**)
- [ ] `docs/archive/README.md` — 한 장. 무엇이 있고, **현행 사실은 여기가 아니라 docs/ 에 있다**는 경고
- [ ] `verify_naming.py` 는 archive 를 보지 않는다(지금도 원본 이름을 허용하는 문서들이다)
- [ ] 커밋 `docs: 구축 과정 문서를 docs/archive 로 옮긴다`

### Task 2~9: 현행 문서 8개를 하나씩

순서: **DECISIONS → ARCHITECTURE → DATA_MODEL → FEATURES → DEVELOPMENT → DEPLOYMENT → UI_GUIDE → STATUS.**
결정이 먼저여야 다른 문서가 ID 로 가리킬 수 있다. 문서마다:

- [ ] 원문에서 현행 내용을 옮기고 **코드와 대조해 틀린 사실을 고친다**(파일 경로·건수·명령은 실제로 확인한 것만 쓴다)
- [ ] 같은 주제를 두 곳에 쓰지 않는다 — 한 곳에 쓰고 나머지는 링크
- [ ] 한 문서 한 커밋 `docs: <문서> 를 현행 기준으로 새로 쓴다`

### Task 10: 입구 정리

- [ ] README · AGENTS · docs/README 를 새 구조로. AGENTS 는 규칙과 링크만
- [ ] 위 "코드·스크립트가 문서를 가리키는 곳" 전부 고친다
- [ ] 커밋

### Task 11: 검증

- [ ] Markdown 링크 검사 — docs·README·AGENTS 의 상대 링크가 모두 있는 파일을 가리키는지(일회성 스크립트, 결과만 보고)
- [ ] `verify_naming.py` PASS(새 `LIVING_DOCS`)
- [ ] 현행 문서에 원본 이름(AIDataHub·vision-inspection)·"이관"·"Phase" 가 남았는지 grep — 남으면 이유가 있는 것만
- [ ] 단위 테스트(코드 주석만 바뀌었는지 확인용)

## 범위 밖

- `docs/client/*` 의 내용(외부 계약 — 서버 소유 계약은 R10~R16·어조 작업에서 고친다)
- 코드 리팩터링. 문서가 가리키는 주석·docstring 의 경로만 고친다
