# 문서 지도

제조AI플랫폼이 **지금 무엇이고 어떻게 동작하는지**를 적은 문서다. 구축 과정의 기록은
[archive/](archive/README.md) 에 원문 그대로 있다 — 현행 사실은 여기 문서가 정본이다.

## 현행 문서

| 문서 | 내용 | 언제 보나 |
|---|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 구성·디렉터리, **API 규약**, 인가, RLS, 작업 큐, 파일 제공, 추론 경계 | 구조를 바꾸기 전 |
| [FEATURES.md](FEATURES.md) | 메뉴 트리, 역할별 권한, 화면별 기능, 데이터 흐름 | 화면·메뉴·업무 흐름을 손댈 때 |
| [DATA_MODEL.md](DATA_MODEL.md) | 테이블, RLS 대상, 마이그레이션, 시드, 파일 경로 | 스키마를 건드릴 때 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 개발 환경, 테스트, 검증 스크립트, 개발 함정 | 개발을 시작할 때 · 테스트가 흔들릴 때 |
| [SOURCE_CONTROL.md](SOURCE_CONTROL.md) | 역할, 브랜치·커밋·push, 공유 개발 DB 의 마이그레이션·시드 규칙 | 팀원으로 개발에 참여할 때 · push 하기 전 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 설치, `.env`, nginx·systemd, 로그·백업, 연결, 배포물 반입, 점검 | 서버에 올릴 때 |
| [../DESIGN.md](../DESIGN.md) | 디자인 토큰, 화면 골격, 버튼, 그리드, 모달, 문구, 화면 체크리스트 | 화면 스타일·문구를 손댈 때 |
| [DECISIONS.md](DECISIONS.md) | 유효한 결정(ID 유지), 향후 확장 F-3~F-8 | 왜 이렇게 만들었는지 따질 때 |
| [STATUS.md](STATUS.md) | 지금 되는 것, 알려진 제약, 남은 일 | 다음에 할 일을 정할 때 |

## 비전검사 클라이언트와 주고받는 문서 (`client/`)

현장 검사 PC 의 **비전검사 클라이언트**(별도 프로젝트, 배포물 이름 `VisionInspectionClient`)와의 계약이다.

| 문서 | 관리 | 내용 |
|---|---|---|
| [client/SERVER_API_CONTRACT.md](client/SERVER_API_CONTRACT.md) | **서버(우리)** | `/api/v1` 계약 정본. 요청 처리 결과(§15)와 변경 이력(§17). 클라이언트에 전달하는 문서는 이것 하나다 |
| [client/SERVER_REQUESTS.md](client/SERVER_REQUESTS.md) | 클라이언트 담당 | 서버에 보내 온 요청·실측 결과. 받은 그대로 둔다 |

## 학습 플랫폼(Wezard)과 주고받는 문서 (`Wezard/`)

Wezard(GPU·학습·추론 서버)와 **양방향**으로 통신한다 — Wezard 가 우리 스냅샷을 가져가 학습하고(①), 우리가 Wezard 의 모델 목록·추론을 부른다(②).

| 문서 | 관리 | 내용 |
|---|---|---|
| [Wezard/integration-protocol.md](Wezard/integration-protocol.md) | **두 쪽 합의** | 통신 규약 v1 — 인증·오류·재시도·데이터 형식 등 두 방향 공통 규칙. Wezard 저장소에 같은 사본을 둔다 |
| [Wezard/maip-api.md](Wezard/maip-api.md) | **서버(우리)** | ① `/api/v1/datasets` 계약 정본 — 우리가 Wezard 에 전달한다 |
| [Wezard/wezard-api.md](Wezard/wezard-api.md) | Wezard | ② 모델 목록·정보·추론 계약 — Wezard 가 전달한 사본(원본 `wezard/docs/maip/wezard-api.md`). 받은 그대로 둔다 |

## 문서 안의 짧은 표기

| 표기 | 뜻 |
|---|---|
| `FEATURES §8`·`DEVELOPMENT §4` 처럼 문서 이름 + 절 | 이 폴더(`docs/`)의 그 문서. `AGENTS`·`README`·`DESIGN` 은 저장소 루트의 문서다 |
| `계약 §16` | `client/SERVER_API_CONTRACT.md` 의 절 |
| `근거: DECISIONS …` | `DECISIONS.md` 에서 그 ID(`DEC-024`·`O-1` 등) 또는 "사용자 결정(날짜)" 행. 같은 날짜 행이 여럿이면 절 제목과 같은 주제의 행이다 |
| 코드 주석의 `설계 2026-10-21 §6`·`설계 2026-10-20` | `archive/superpowers/specs/` 의 그 날짜 설계 문서(`2026-10-21-inspection-rework-design.md`·`2026-10-20-measurement-type-design.md`)와 그 절. 결정은 DECISIONS 의 같은 날짜 행이 정본이고, 설계 문서는 그때의 상세다 |
| `더 볼 곳: …` | 이 절에 없는 내용이 있는 곳. 절 끝에 한 줄만 둔다 |

## 그 밖의 자료

| 위치 | 내용 |
|---|---|
| `logo/` | YEST 로고 원본과 파생([../DESIGN.md](../DESIGN.md) §4) |
| [archive/](archive/README.md) | 구축 과정 기록(원본 분석·이관 계획·결정 원문·실행을 마친 계획) |
| [../AGENTS.md](../AGENTS.md) | 코드를 고치는 사람(사람·AI)이 먼저 읽는 규칙 |
| [../README.md](../README.md) | 무엇이고 어떻게 띄우는지(요약과 링크. 절차 정본은 DEVELOPMENT·DEPLOYMENT) |
| [../domain/_sql/i18n/README.md](../domain/_sql/i18n/README.md) | 다국어 시드 SQL 실행법 |
| [../distribution/README.md](../distribution/README.md) | 클라이언트 배포물·LGPL 대응 소스 폴더 |
