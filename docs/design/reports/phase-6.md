# Phase 6 — DWG 도면 1단계: 업로드·기본 파싱·검수 (2026-11-12)

> 브랜치 `refactor-1`(작업 폴더, 커밋 안 함) · 계획 `phase-6-plan.md` · 화면 설계 `docs/design/drawing/도면업로드_화면설계_현행기준_v1.0.md` · 목업 v0.6
> 코드 주석은 사용자 지시대로 `2026.11.12(sooyeon.choi) 도면 파싱 기능 추가` 하나로 통일하고 요구사항 번호는 넣지 않았다.

## 1. 요약

- `.dwg`·`.dxf`를 올리면 **판별 → (DWG) LibreDWG 변환 → 보정 → ezdxf 읽기 → 표제란·부품표·개정이력·주기·치수 추출 → 도면 IR 저장 → 이미지(전체·미리보기·표제란/부품표/개정 크롭) → 문서·버전·이미지 저장**까지 처리한다.
- **임베딩·Qdrant·`tb_chunks` 저장 없음**(테스트로 확인). 검수 상태와 검색 미적용 표시를 문서 목록·처리 결과에 보여 준다.
- 기본값 `DRAWING_PARSE_MODE=off` — 켜기 전에는 기존 동작 그대로(`.dwg` 거부).
- **마이그레이션 `0010_drawing_ingest_steps`**(11-12 추가, 11-13 `0009_collection_start_questions` 다음으로 번호 변경): `tb_ingest_jobs.current_step` 제약에 도면 단계 4개 추가(값 추가만). 그 밖에는 기존 테이블 사용 — 검수 상태는 버전 `summary_json.drawing.review`, 이력은 `tb_document_events`(`update`, "도면 검수 완료/취소"), 이미지는 `tb_spreadsheet_resources`(`role_cd` = `drawing`·`drawing_preview`·`drawing_crop`).

## 2. 변경 파일

| 구분 | 파일 | 내용 |
|---|---|---|
| 신규 | `adrag_backend/app/ingest/drawing/` `common.py` `detect.py` `convert.py` `sanitize.py` `textcodes.py` `reader.py` `extract.py` `render.py` `ir.py` `runner.py` `templates/default.yaml` `templates/fonts.yaml` | 도면 처리기 |
| 신규 | `adrag_backend/app/services/drawing_pipeline.py` | 단계 `parse → drawing_convert → drawing_extract → drawing_render → drawing_store`(기존 체크포인트·재시도·보상 재사용) |
| 신규 | `adrag_backend/app/routes/drawings.py` | 처리 결과 `GET …/versions/{v}/drawing-result`, 검수 `POST/DELETE …/drawing-review` |
| 수정 | `app/core/config.py`, `.env.example` | 설정 9개(`DRAWING_PARSE_MODE` 등) |
| 수정 | `app/routes/ingest.py` | 업로드 도면 분기·서명/크기 확인, `/options` 도면 항목, 목록 `drawing` 요약, 새 버전 형식 불일치 400, 버전 이력 적용 숨김 |
| 수정 | `app/services/ingest_service.py`, `ingest_jobs.py`, `ingest_pipeline.py` | 도면 파이프라인 분기, 도면 단계 재시도, 오류 코드(E_…) 기록, 단계 로그 이름 |
| 수정 | `app/services/document_version_restore.py` | `DRAWING_NOT_SUPPORTED`(도면 버전 적용 거부) |
| 수정 | `app/parsers/document_types.py`, `app/ingest/file_router.py`, `app/models/ingest_models.py`, `main.py` | 문서 유형 `drawing`, 라우터 등록, `DocumentItem.drawing` |
| 수정 | `requirements.txt`, `Dockerfile.dev`, `Dockerfile` | ezdxf 1.4.2·matplotlib·contourpy<1.4, LibreDWG 0.13.3 소스 빌드(dev 기본 켬, 운영 이미지 기본 끔 `WITH_LIBREDWG=false`) |
| 신규 | `tests/drawing_fakes.py`, `tests/test_drawing_parse.py`(25), `tests/test_drawing_ingest.py`(9) | 합성 도면·가짜 변환기 |
| 신규 | `adrag_frontend/src/components/DrawingResultDialog.vue` | 처리 결과(요약·부품표·개정이력·주기·치수·경고·정보·처리 정보), 검수 완료/취소, 필수 항목 누락 확인 창 |
| 수정 | `adrag_frontend/src/composables/useDocumentUpload.js`, `useAdminDocuments.js`, `views/AdminView.vue`, `api/adminApi.js`, `utils/textFormat.js` | 도면 확장자·크기, 처리기별 단계 칸(도면 5칸), 확인 필요 상태, 같은 품번 안내, 목록 품번·Rev·상태 칩·[처리 결과], 유형 칩 "도면 N" |

## 3. 완료 기준 근거

| 항목 | 결과 |
|---|---|
| 도면 단위 테스트 `test_drawing_parse.py` | **25 passed** — 판별(허용·거부 5종), 보정 전 `Invalid handle 0` → 보정 후 읽기, 가짜 변환기 성공·실패·시간 초과·실행 파일 없음, 용지 A3·배율 5 판정, 표제란 값이 라벨 아래(필수 3필드 포함 11필드), 2줄 머리글 부품표 3행×5열, 머리글 아래 개정표 2행, 주기 3항목·일반공차·규격 메모, 치수 접두(`2-Ø5.5 THRU`)·참고치수, 고정 문구 제외, 메타데이터 키 계약, 필수 항목 누락 경고, 표제란 없음 → 파일명 doc_key, 렌더(범위 고정·손상 해칭 1건 제외·크롭 3종), 렌더 실패는 경고만 |
| 도면 통합 테스트 `test_drawing_ingest.py`(PostgreSQL 테스트 DB) | **10 passed**(작업 테이블 도면 단계 기록 포함) — 저장 후 `tb_chunks` 0건, 임베딩·Qdrant·BM25 호출 시 즉시 실패하는 대역으로 **호출 0** 확인, 이미지 5개 파일·행, md 생성, 적용 이력 `upload`; DWG 변환 경로; 변환 실패 시 DB·리소스 0; 저장 단계 실패 후 그 단계부터 재시도(변환 1회); 같은 품번은 안내만(문서 2개); 업로드 off/backend·서명·크기 413; 목록 요약·결과·검수(본인 가능, 다른 사용자 403, 열람 불가 404, 이력 2건); 누락 도면 확인 요구 409 → 확인 후 완료; 새 버전 v2 전환·점유 해제·이력 적용 불가 사유 |
| 실제 LibreDWG 경로 | 임시 이미지(`drawing-libredwg-probe:0.13.3`)에서 **LibreDWG 0.13.3 소스 빌드 성공**. 합성 DXF → `dxf2dwg` → DWG(AC1015) → `dwg2dxf`(15 ms) → 추출: 표제란 3필드·부품표 3행·개정 2행 정상. (`dxf2dwg`가 만든 DWG의 블록 누출로 표가 두 번 잡히던 것을 발견해 블록 표 우선·중복 제거를 추가) |
| 관련 기존 테스트 | 도면 포함 114개 중 **113 passed, 1 failed** — 실패 `test_multi_document_upload::test_job_owner_permissions_and_retry_contract`(`requeue_failed` 없음)는 refactor-1 보고서의 기존 실패 목록과 같음 |
| 프런트 빌드 | `vite build` 성공(기존 큰 청크 경고만) |
| dev 백엔드 영향 | 소스 마운트 dev 컨테이너는 ezdxf가 없어도 정상 기동(도면 모듈은 도면 작업에서만 불러옴), `/health` 200 |
| 샘플 3종 정확도 | **미실행** — `DRAWING_SAMPLE_DIR`(실제 샘플 경로)를 받지 못함 |
| 화면 흐름(브라우저) | **미실행** — 별도 백엔드(8091)·화면(3091)은 띄웠으나 로그인 토큰 발급이 자동 승인 정책에 막혀 중단. 사용자 계정으로 직접 확인 필요(6절) |

## 4. 설계와 다르게 한 점

| 설계·계획 | 구현 | 이유 |
|---|---|---|
| 검수 기록 `tb_document_events` `review` | `summary_json.drawing.review` + 이벤트 `update` | `event_type` CHECK에 `review`가 없어 마이그레이션이 필요. 마이그레이션 없이 처리 |
| 단계 코드 `drawing_parse` 하나 | `drawing_convert`·`drawing_extract`로 나눔 | 화면 5칸과 1:1, 재시도 시 변환 반복 방지 |
| 표제란 템플릿 = 필드별 좌표 | 템플릿 = 표제란 영역 + 라벨 별칭(값 방향 아래/오른쪽) | 실제 샘플 좌표 없이 일반화. 샘플로 영역 보정 필요(`TODO(결정필요)` YAML에 남김) |
| 렌더 별도 프로세스(multiprocessing) | `python -m app.ingest.drawing.render` 자식 프로세스 | spawn 방식이 실행 환경에 따라 메인 모듈 재로드로 실패 |
| `tb_drawing_links`·풍선·ODA | 미구현 | 계획대로 제외 |

## 5. 마이그레이션·되돌리기

- `0010_drawing_ingest_steps`(이전 이름 `0009_drawing_ingest_steps`, 선행 `0009_collection_start_questions`): 작업 단계 제약 확장. **처음 보고에서 이 제약을 놓쳐 실제 업로드가 `CheckViolation`으로 실패**(통합 테스트가 작업 테이블 단계 기록을 거치지 않았음) → revision 추가, 작업 테이블 단계 기록 테스트 추가. dev DB 적용 완료. downgrade는 도면 단계 행을 `completed`/`parse`로 바꾼 뒤 이전 제약으로 되돌림.
- 끄기: `DRAWING_PARSE_MODE=off`(기본). 이미 등록한 도면 문서는 목록에 남으며 일반 문서처럼 삭제할 수 있다.
- 코드 되돌리기: 2절 신규 파일 삭제 + 수정 파일의 `2026.11.12(sooyeon.choi) 도면 파싱 기능 추가` 주석 부분 제거.

- 11-12 실제 업로드에서 발견·수정: 저장 폴더가 상대 경로(`instance/data`)일 때 변환기가 작업 폴더 기준으로 경로를 겹쳐 `File not found`(E_CONVERT_FAILED) → `convert.py`·`render.py`에서 절대 경로로 넘기도록 수정, 상대 경로 테스트 추가(도면 테스트 36 passed).

## 6. 남은 일·확인 방법

1. **dev 이미지 다시 빌드 필요**: `requirements.txt`·`Dockerfile.dev`가 바뀌었다. `docker-compose -f docker-compose.dev.yml build backend` 후 `.env`에 `DRAWING_PARSE_MODE=backend`를 넣고 재기동.
2. **화면 확인(사용자)**: 지금 띄워 둔 확인용 환경 — 화면 `http://localhost:3091`(백엔드 8091, dev DB 사용). 업로드용 합성 도면: `.playwright-mcp/conveyor_module_assy.dxf`, `.playwright-mcp/lift_unit_norev.dxf`(개정 누락). 종료: `docker rm -f rag-backend-drawing-test`, vite 창 닫기, 임시 이미지 `docker rmi drawing-libredwg-probe:0.13.3`.
3. **실제 샘플 3종 검증**: `DRAWING_SAMPLE_DIR`를 알려 주시면 정답 표 대비 정확도(표제란 필수 3필드 100%·부품표 행 누락 0)를 계산하고 표제란 영역 템플릿을 보정한다.
4. 운영: LibreDWG(GPLv3) 반입 확인 전에는 운영 이미지에 넣지 않는다(`WITH_LIBREDWG=false`). 폐쇄망이라 tarball 반입 절차 필요.

## 7. 질문(결정 필요)

| # | 질문 | 현재 처리 |
|---|---|---|
| Q-1 | LibreDWG 운영 반입 가능 여부 | 운영 이미지 기본 제외 |
| Q-2 | 샘플 도면 경로 | 미수령 |
| Q-3 | REVISION `F.5` 의미 | 원문 + 분리값(`rev_major`·`rev_iter`) 저장 |
| Q-4 | 모델명을 표제란 품명으로 바꿀지 | 파일명 유지(품번·품명은 따로 표시) |

## 8. 요구사항 정의서·기능 목록에 반영할 것

- MOD-14: "DWG 변환 2차" → "DWG 파싱·검수 1차(검색 적용은 다음 단계)"
- API-02(도면 접수)·API-03(도면 단계 코드·오류 코드)·API-09(도면 처리 결과·검수)·UI-12(도면 업로드·처리 결과·유형 칩)
- 변경로그 후보 D-25(DWG 파싱 1차, 메타데이터+도면 보기 목표), 검수 기록 위치(summary_json, 마이그레이션 없음)
