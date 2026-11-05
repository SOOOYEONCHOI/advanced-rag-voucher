# Phase 1 보고서 — 엑셀 분기·파서 연동·확인용 md (재구현)

> 작성 2026-10-16 · 관련 ID: F-2-01, F-3-01, F-3-02 / R1-1, R2-1~3 / D-16 / UI-12 · 기준: 작업지시서 v3.1 1장, Phase 1.5 직후 소스
> 스키마 변경 없음. DB 구조 변경안(04, 승인 전)과 무관하게 진행할 수 있는 범위만 구현했다.

## 1. 요약

- `EXCEL_PARSE_MODE=backend`이면 엑셀(xlsx·xlsm·xls)을 docling 대신 **엑셀 전용 처리기(`excel_ingest`)**로 처리한다. 문서 유형·파서 선택은 무시한다(D-16). 기본값은 `docling`이라 **기존 동작이 그대로**다(절대 규칙 6). dev compose만 `backend`로 켠다.
- 접수 단계에서 파일 서명을 확인해 **위장 파일·암호 파일을 거부**하고 임시 파일을 지운다(R1-1). `.xls`는 LibreOffice로 변환한다(dev 컨테이너에는 없어 명확한 오류로 실패).
- 처리 결과를 **확인용 md**로 남긴다: `{MD_SAVE_DIR}/excel/{doc_key}/{job_id}/`(00_summary.md, sheets/, chunks.md, ir.json, images/) + `LATEST`, 최근 5회 보관(F-3-02).
- 엑셀 청크를 기존 임베딩·Qdrant 적재로 그대로 보내 **검색 대상이 된다**(텍스트 청크). 출처 표시용 `sheet_name`·`source_range`(행 범위)·`step_no`·`section_type`·`revision`이 payload에 들어간다.
- 업로드 화면: 서버가 backend 모드면 엑셀 선택 시 "엑셀은 전용 처리기로 처리됩니다" 안내, 파일이 모두 엑셀이면 파서 선택 비활성, `.xls` 선택 허용(D-16).

## 2. 변경 파일

| 파일 | 내용 |
|---|---|
| `adrag_backend/excel_ingest/` (신규) | 엑셀 파서 모듈. `D:\Dev\SVNLocalackup\_excel_ingest_모듈`(09-29) 복사. 추출 규칙 수정 없음(절대 규칙 5). 승인된 1줄 수정만 있음(`ooxml.py` `rels()` 절대 경로 관계, Q-P1-1) |
| `adrag_backend/app/ingest/__init__.py`, `file_router.py` (신규) | 처리 경로 결정 `resolve_parse_route`, 거부 사유 `ExcelFileRejected(reason=invalid_format|encrypted)` |
| `adrag_backend/app/ingest/excel_runner.py` (신규) | `run_excel_ingest`: xls 변환, 파싱, md 출력(작업별 임시 폴더 → 이동, 실패는 경고만), 결과 요약 |
| `adrag_backend/app/ingest/excel_chunks.py` (신규) | excel_ingest 청크 → `LCDocument` 변환(이미지 청크 제외) |
| `adrag_backend/app/services/ingest_pipeline.py` | `ChunkStep` 분기, 문서 행 `parser_type`=처리기 이름, 작업 결과에 `processing_engine`·`excel_ingest` 요약 |
| `adrag_backend/app/services/ingest_service.py`, `ingest_jobs.py` | `job_id`를 파이프라인까지 전달(md 폴더 이름) |
| `adrag_backend/app/routes/ingest.py` | 업로드 검증 분기·서명 확인·거부 시 임시 파일 삭제, `GET /api/ingest/options` 신규 |
| `adrag_backend/app/core/config.py` | `excel_parse_mode`(기본 docling), `excel_md_keep_last`(5), `excel_xls_convert_timeout`(120) |
| `adrag_backend/app/parsers/metadata_extractor.py` | 스프레드시트 payload 필드에 `processing_engine`·`section_type`·`step_no`·`revision` 추가(docling 경로는 None) |
| `adrag_frontend/src/api/adminApi.js`, `composables/useDocumentUpload.js`, `views/AdminView.vue` | D-16 화면 처리. 변경 지점마다 `2026.10.16(sooyeon.choi) 추가` 주석 |
| `adrag_backend/tests/test_excel_ingest_routing.py` | 수집 제외 해제, Phase 1 기준으로 단언 2곳 수정(버전·청크 기록 → 문서 행, 업로드 대기 폴더 위치) |
| `adrag_backend/tests/test_excel_ingest_phase1_sample.py` (신규) | 샘플 엑셀 Phase 1 완료 기준(md·요약·적재·동시 3건) |
| `adrag_backend/tests/excel_ingest_fakes.py` | 다른 테스트의 `sys.modules` stub에 걸리지 않게 문서 저장소를 원본 파일에서 로드 |
| `adrag_backend/tests/conftest.py` | `collect_ignore`에서 `test_excel_ingest_routing.py` 제거 |
| `.env.example` | `EXCEL_PARSE_MODE`·`EXCEL_MD_KEEP_LAST`·`EXCEL_XLS_CONVERT_TIMEOUT` 이름 추가 |

정리 작업: `adrag_backend` 아래 `__pycache__` 전부 삭제 — **87개 .pyc가 다른 프로젝트(`advanced-rag-framework`, Bitbucket 사본) 경로에서 컴파일된 것**이었다(10-15 덮어쓰기 때 함께 복사된 것으로 보임). pytest가 원본 시각·크기가 같으면 이 캐시를 재사용하므로 삭제했다(자동 재생성되는 캐시).

## 3. 완료 기준 충족 근거

| 기준 | 결과 |
|---|---|
| 파일 판별(R1-1) | `test_excel_ingest_routing.py` **20 passed**: docling 모드는 전부 docling, backend 모드 xlsx·xlsm → excel_ingest, xltx·pdf·pptx → docling, 확장자 위장·ZIP 비엑셀 → `invalid_format`, 암호 OOXML → `encrypted`, xls는 OLE2 서명 필수 |
| 확인용 md(F-3-02) | 같은 파일: md 경로·LATEST·시트 수, MD_SAVE_DIR 비우면 미출력, md 실패는 경고만, LibreOffice 없으면 명확한 오류 |
| 샘플 엑셀(R2-1~3) | `test_excel_ingest_phase1_sample.py` **2 passed**(약 70초): 시트 18, "이미지 배치/고유 이미지 190/152", 인쇄영역 밖 69, 도형 안내문 청크 포함, docling 호출 0건, 이미지 제외 전 청크 적재, Step 6 payload(step_no·section_type·processing_engine), 문서 행 `excel_ingest`·`spreadsheet`·18페이지. 같은 파일 3건 동시 처리 시 md 충돌·임시 폴더 잔존 0 |
| 전체 회귀 | `pytest -m "not e2e and not voice"`: **387 passed / 11 failed / 1 error**(Phase 1.5 기준선 363/10/4). 실패·오류는 기준선과 같은 기존 문제(보고서 phase-1_5 7절) + `test_multi_document_upload`의 Phase 3 API(`requeue_failed`) 1건(이전엔 setup 오류 3건) |
| 실제 서버(dev 컨테이너, backend 모드) | `/api/ingest/options` → backend·[xlsm, xlsx, xls]. 작은 엑셀 업로드(파서 pdfplumber·유형 law를 줘도 접수) → 작업 completed, **실제 임베딩 서버·Qdrant 적재**, md 5종 생성, 문서 행 `excel_ingest`. 위장 엑셀 400 `rejected(invalid_format)`. 시험 문서는 삭제(벡터 3건 삭제, 잔여 0)·md 폴더 정리 |
| 프런트 | `vite build` 성공(생성된 `dist/`는 삭제). 화면 동작은 브라우저로 확인하지 않음 |

## 4. 마이그레이션

없음.

## 5. 되돌리는 방법

- 설정만으로: `.env`에 `EXCEL_PARSE_MODE=docling`(dev compose 기본이 backend이므로 명시) → 기존 동작.
- 코드: 2절 신규 파일 삭제, 수정 파일 이전 판으로 복원. 이미 excel_ingest로 적재한 문서는 문서 관리 화면에서 삭제하면 벡터까지 지워진다.

## 6. 남은 이슈·결정 필요

| # | 내용 | 제안 |
|---|---|---|
| Q-P1-1 | **excel_ingest가 절대 경로 관계(Target="/xl/…")를 못 읽는다.** openpyxl 등 일부 도구가 만든 엑셀에서 파싱 실패(Excel로 저장한 파일·샘플은 정상). 지금은 모듈을 고치지 않고 `excel_runner`가 상대 경로로 바꾼 임시 사본을 파싱한다(`TODO(결정필요)` 표시). 사본이라 IR의 `file_sha256`이 원본 해시와 달라질 수 있다 | ✅ **2026-10-16 승인·반영**: `excel_ingest/ooxml.py` `rels()`에서 절대 Target을 패키지 루트 기준으로 해석(주석 표시), `excel_runner`의 우회 코드 제거. Phase 1 테스트 22건 재통과 |
| Q-P1-2 | **이미지 청크는 적재하지 않았다.** 사진 저장은 Phase 2(`phase-2-plan.md` P2-3·P2-4·P2-13), 답변 사진 연결은 Phase 4 | Phase 2에서 |
| Q-P1-3 | 청크 길이 제한 없음: 표 섹션 청크는 최대 25행 단위(excel_ingest 규칙). 이전 계보 Phase 2는 `MAX_CHUNK_SIZE`(800자) 분할을 했다 | Phase 2에서 분할 규칙 결정(검색 품질 측정 후) |
| Q-P1-4 | dev 컨테이너에 LibreOffice가 없어 `.xls`는 "LibreOffice 필요" 오류로 실패 | 운영 서버 설치 여부 결정(이미지에 추가하면 약 300MB+) |
| Q-P1-5 | `doc_key`는 파일명 기준(표시·md 폴더용). 관리대장 문서번호 연결(R2-3)은 Phase 2·변경안 `doc_key` 결정과 함께 | — |
| 참고 | 업로드 대기 폴더가 여전히 `sqlite_db_path` 기준(Q-15.7) | Phase 2 착수 때 `instance_dir` 기준으로 |

## 7. 요구사항 정의서·기능 목록에 반영할 것

- 신규 설정 `EXCEL_PARSE_MODE`(docling|backend), `EXCEL_MD_KEEP_LAST`, `EXCEL_XLS_CONVERT_TIMEOUT`.
- 신규 API `GET /api/ingest/options`(업로드 화면용 엑셀 처리 방식) — 화면·API ID 목록(02)에 ID 부여 필요.
- 확인용 md 위치 `{MD_SAVE_DIR}/excel/{doc_key}/{job_id}/`.
- R1-1: 암호 파일·위장 파일은 접수 단계에서 400 거부(사유 코드 `encrypted`·`invalid_format`).
