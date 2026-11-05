# CLAUDE.md — 지능형 작업표준 안내 AI(RAG)

> 이 파일은 저장소 루트에 두고 Claude Code가 세션마다 자동으로 읽는다. 짧게 유지하고, 상세는 `docs/design/` 문서로 넘긴다.
> 갱신 2026-10-15 · 요구사항 정의서 v0.7 / 협의 자료 v0.3 / 프로그램·기능 목록 v0.5 / 화면 목업 2종 기준

## 1. 무엇을 만드는가

조립 절차서(엑셀 SOP)·이미지·DXF 도면을 등록하면, 작업자가 텍스트·음성으로 물었을 때 **최신 작업표준의 작업 단계·사진·출처로 답하는** RAG 챗봇. 현재 운영 중인 We.RAG(backend Python + adrag_frontend Vue)를 확장한다.

- 1차 년도: 개발 2026-10-01 ~ 11-30, 안정화 12월. 엑셀 SOP 기반 텍스트+사진 답변이 등록부터 답변까지 동작하는 수준 + STT 음성 질문 + TTS 기본 기능 + DXF 기본 모듈(시범)
- 2차 년도(2027): 고도화. **2차 항목은 요청이 없으면 구현하지 않는다.**

## 2. 문서 우선순위 (값이 다르면 위쪽을 따른다)

| 순위 | 문서 | 용도 |
|---|---|---|
| 1 | 실제 코드(Phase 0 조사 결과 `docs/design/current_architecture.md`) | 기존 테이블·API·설정 이름 |
| 2 | `docs/design/01_결정사항_변경로그.md` | **최신 결정. 아래 문서와 다르면 이것이 우선** |
| 3 | `docs/design/00_요구사항_기준_1차_v0.7.md` | 1차 범위, 요구사항 ID(R…), 업무 시나리오(SC-01~13), 완료 기준 |
| 4 | `docs/design/CLAUDE_CODE_작업지시서_v3.1.md` | Phase별 작업·완료 기준 |
| 5 | `docs/design/02_화면_API_ID_목록.md` | 화면·API·프로그램 ID |
| 6 | `docs/design/프로그램설계서_지능형작업표준안내AI_v0.2.md` | 모듈·함수·SQL·설정값 (변경로그가 덮어쓴 절은 따르지 않음) |
| 7 | 작업지시서 v2.3, DB 환경·운영이관 보완 지시서, 엑셀 적재 설계 v0.4, DXF 기술검토 v0.1, 테이블 정의서 v0.3 | 세부 근거 |

원본 표: `docs/requirements/` 의 요구사항 정의서 v0.7(xlsx), 프로그램·기능 목록 v0.5(xlsx).
화면 목업: `docs/design/mockups/` — 챗봇(`chat_UI-02-08_20261008.html`), 문서 관리(`admin_UI-12_문서관리_20261012.html`). 배치·문구·상태 흐름의 기준이며 범위 차이는 변경로그 D-14~D-18.

## 3. 절대 규칙

1. **로컬 개발만 한다.** SVN 작업 폴더다. `svn commit`, `git push`, PR 생성 금지. 로컬 git이 있으면 Phase마다 `phase-N` 브랜치에 로컬 커밋만.
2. **운영 DB·운영 서버에 접속하지 않는다.** 운영 반영은 사용자가 실행할 스크립트·절차서로만 만든다.
3. `.env`·비밀번호·내부 IP·원본 문서·추출 이미지를 코드·문서·로그·보고서에 쓰지 않는다. 변수 **이름**만 언급한다. 챗봇 목업 HTML에는 샘플 엑셀에서 뽑은 이미지가 들어 있으므로 **읽기만 하고 수정·복사·커밋하지 않는다**(목업 이미지·데이터를 화면 코드나 테스트 데이터로 옮기지 않는다).
4. RDB는 PostgreSQL 16, 벡터는 Qdrant, 작업 큐는 PostgreSQL 작업 테이블(`tb_ingest_job`). **Redis·Celery·RQ 도입 금지.** 스키마 변경은 Alembic revision(upgrade·downgrade)으로만.
5. `excel_ingest`의 추출 규칙과 docling-parser 서버 코드는 수정하지 않는다. 바꿔야 하면 이유·영향을 보고하고 승인 후 진행.
6. 새 기능은 설정값으로 켜고 끌 수 있게 하고, 기본값은 기존 동작을 깨지 않게 한다.
7. 문서·사진 등 데이터는 사내망 밖으로 보내지 않는다. 외부 AI API를 호출하지 않는다(모델은 모두 GPU 서버 자체 서빙).
8. 권한 없는 문서의 내용·이미지는 검색·답변·출처·이미지 API 어디에도 나오면 안 된다(권한 판단 함수는 한 곳).
9. `docs/requirements/`의 엑셀과 `docs/design/mockups/`의 HTML은 읽기 전용이다. 바꿔야 할 내용은 Phase 보고서의 "요구사항 정의서·기능 목록에 반영할 것" 절에 적는다.

## 4. 작업 방식

- 세션 시작 시: `docs/design/reports/`의 마지막 보고서와 변경로그를 읽고, 지금 Phase와 남은 이슈를 한 문단으로 요약한 뒤 시작한다.
- Phase 시작 시: 수정할 파일 목록과 구현 계획을 먼저 보고한다. **이미 구현된 코드가 변경로그와 다르면**(예: 개정본 자동 판단, 역할 기준 권한, 등록 결과 리포트 화면) 수정 계획을 먼저 보고하고 승인 후 바꾼다.
- 코드·테스트·보고서에는 요구사항 ID(R…), 기능 ID(F-…), 시나리오 ID(SC-…), 화면·API ID(UI-…, API-…)를 남긴다.
- Phase가 끝나면 `docs/design/reports/phase-N.md`에 변경 파일 / 요약 / 관련 ID / 완료 기준 충족 근거(테스트 결과·수치) / 마이그레이션 여부 / 되돌리는 방법 / 남은 이슈를 쓰고 **멈춘다.**
- 결정이 필요한 것(요구사항에 없거나 문서끼리 다른 것)은 추측해서 구현하지 말고 질문 목록으로 보고한다. 코드에는 설정값이나 `TODO(결정필요: …)`로 남긴다.

## 5. 자주 쓰는 명령 (2026-10-16 Phase 1.5 기준 실제 값)

```bash
# WSL에서 (compose 플러그인 없음 → docker-compose v1)
docker-compose -f docker-compose.dev.yml up -d postgres-dev qdrant-dev   # 로컬 DB (DB: rag_chatbot_dev / 테스트 rag_chatbot_test)
docker-compose -f docker-compose.dev.yml up -d --no-deps backend          # dev 백엔드 (기동 시 init_database.py = alembic upgrade head)
# adrag_backend 폴더에서 (로컬 Python, .env의 POSTGRES_HOST=localhost)
python init_database.py                                   # alembic upgrade head + 스키마 버전 확인
python scripts/create_admin.py                            # 관리자 계정 생성(고정 시드 없음). dev 컨테이너는 .env ADMIN_PASSWORD로 자동 생성(D-19)
python scripts/migrate_sqlite_to_postgres.py --dry-run    # SQLite → PostgreSQL 이관 검증
pytest -q -m "not e2e and not voice" --basetemp=<짧은 경로>   # 테스트 DB는 하나의 pytest만 동시에
# 적재 워커: Phase 3에서 확정 (현재는 앱 프로세스 안 asyncio 큐)
```
