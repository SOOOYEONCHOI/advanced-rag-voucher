# Phase 4-A 보고서 — 답변에 사진 포함 (검색 → 답변 → 사진·출처 최소 경로)

> 작성 2026-10-19 · 관련 ID: R4-3(사진 포함 답변), F-4-03·F-4-04, MOD-09, API-05, UI-03·UI-04, SC-01·SC-03, 목업 ANS-01·02·04
> 범위: 사용자 결정(10-19) — Phase 3보다 Phase 4 최소 경로를 먼저. 권한 함수 통합·용어 사전·출처 패널 연결 이미지는 4-B.
> 마이그레이션 없음.

## 1. 요약

- **질의 흐름에 사진을 연결했다.** 그래프에 `collect_answer_images` 노드를 하나 추가했다(11 → 12개).
  - `assemble_context` → **`collect_answer_images`** → `generate_answer` → `format_citations`(사진 인용 검증) → `build_response`
  - 사진 후보 = LLM에 넘긴 컨텍스트 청크에 연결된 사진(`tb_spreadsheet_resources`, Phase 2 적재분). 청크 payload `resource_ids`를 쓰고, 연결 사진이 없는 excel_ingest 표 청크(예: 핵심 부품 List)는 같은 시트·청크 행 범위(`source_range`) 안의 인쇄 영역 사진을 쓴다.
  - 후보는 컨텍스트 뒤에 `[관련 이미지 후보]` 목록(`[IMG:ref] 제목 (문서 [n] 셀)`)으로만 준다. URL·파일 경로는 프롬프트에 넣지 않는다.
  - 답변의 `[IMG:ref]` 중 후보에 있는 것만 남기고 나머지는 지운다(최대 `RAG_MAX_IMAGES`=4). 인용이 하나도 없으면 ① 1순위 근거가 Step 청크일 때 그 Step 사진 1장, ② 질의어가 2개 이상 분명히 겹치는 사진 1장을 자동 첨부한다(`cited=false`). 근거 없음 답변에는 첨부하지 않는다.
- **`app/graphs/images.py`를 현행 테이블 기준으로 다시 작성했다.** 10-12 이전 판은 없는 테이블(`tb_image_placements`·`tb_image_assets`)을 조회했고 어디서도 호출되지 않았다.
  - 후보에서 빼는 것: 삭제된 사진, 문서의 현재 버전이 아닌 사진, 삭제된 문서, 다른 문서 사진(청크와 같은 문서만), 브라우저가 못 여는 형식(emf·wmf·svg·도형 XML), 장식·양식 머리글, 검수에서 "연결 안 함"
  - 정렬: 질의어가 주변 텍스트·Step 제목에 많이 나오는 사진 → 역할(Step 사진 > 확대도 > 도면 > 부품 사진 > 흐름도 > …) → 컨텍스트 순서 → 같은 시트·Step → 연결 신뢰도. 같은 이미지(내용 해시)는 1건
  - 이미지 분석 상태(`analysis_*`)와 무관하게 표시한다(상태 조건은 `status <> 'deleted'`).
- **응답**
  - 비스트리밍 `POST /api/query/`: 응답에 `images[]` 추가
  - 스트리밍 `POST /api/query/stream`: `citations` 다음에 `{"type":"images","data":[…]}` 이벤트(사진이 있을 때만). 기존 이벤트는 그대로
  - 대화 이력(`tb_query_sessions.conversation_history`)의 답변 항목에 `images` 저장 → 대화방 재입장 시 사진 복원
  - 저장·기록되는 답변 본문은 검증 후 본문(후보 밖 태그 제거)이다.
  - 사진 항목 필드: `ref, resource_id, document_id, title, role, sheet_name, from_cell, to_cell, step_no, step_title, surrounding_text(200자), original_filename, context_no, cited`. 파일 경로·내부 점수는 내보내지 않는다.
- **챗봇 화면**(목업 ANS-01·02·04 기준, 목업 CSS·이미지는 복사하지 않음)
  - 답변 본문 `[IMG:ref]` → 사진 번호 배지, 배지가 있는 목록 항목·단락 끝에 썸네일(ANS-01)
  - 답변 아래 **[관련 이미지]** 카드: 번호·사진·제목·`시트!셀`(ANS-02). [참고 문서] 위
  - **이미지 뷰어**: 제목·`n / N`·←/→(키보드 포함)·출처(파일 · `시트!셀`)·주변 설명·[원본 열기]·[문서 위치](해당 인용을 출처 패널에서 엶)·Esc 닫기(ANS-04)
  - 스트리밍 중에는 태그를 숨기고(끝에 걸린 미완성 `[IMG:` 포함), 서버가 검증한 목록이 오면 그 목록에 없는 태그는 지운다.
  - 이미지 API가 인증 헤더를 요구하므로 blob으로 받아 resource_id별 1회만 조회한다(실패는 빈 썸네일).
- **설정**(기본값으로 기존 동작 유지)
  - `ANSWER_IMAGES_ENABLED`(기본 true). false면 후보를 프롬프트에 넣지 않고 `images`는 빈 목록, 본문 태그는 모두 지운다.
  - 사진이 연결된 엑셀 문서가 근거일 때만 프롬프트가 바뀐다. 그 외 문서(PDF·docling 비이미지)는 후보 0건이라 프롬프트·답변이 기존과 같다.
  - `RAG_MAX_IMAGES`(4), `RAG_IMAGE_CANDIDATES`(8), `ANSWER_IMAGE_AUTO_ATTACH`(true)
  - 사진 목록을 붙여 프롬프트 토큰 예산을 넘으면 뒤 후보부터 뺀다(문서 컨텍스트는 줄이지 않음).

## 2. 변경 파일

**백엔드 (`adrag_backend/`)**

| 파일 | 내용 |
|---|---|
| `app/graphs/images.py` | 다시 작성: 후보 수집(현행 테이블)·프롬프트 블록(실제 후보 ID 예시 포함)·인용 검증·공개 필드 |
| `app/graphs/nodes/collect_answer_images.py` (신규) | 후보 수집 노드, 프롬프트 예산 확인, `context_with_images()` |
| `app/graphs/nodes/__init__.py`, `app/graphs/rag_graph.py` | 노드 등록·엣지(assemble_context → collect_answer_images → generate_answer) |
| `app/graphs/nodes/assemble_context.py` | 프롬프트 예산 계산을 `_max_prompt_tokens()`·`prompt_fits()`로 분리(동작 같음) |
| `app/graphs/nodes/generate_answer.py` | 컨텍스트 뒤에 사진 후보 목록을 붙임(후보 없으면 기존 그대로) |
| `app/graphs/nodes/format_citations.py` | 사진 인용 검증 → `answer_images`, 정리된 `generated_answer` |
| `app/graphs/state.py` | `image_candidates`·`answer_images` 필드·초기값 |
| `app/services/rag_service.py` | 비스트리밍 `images`, SSE `images` 이벤트, 대화 이력 `images` |
| `app/models/data_models.py` | `QueryResponse.images` |
| `app/core/config.py` | 설정 4개(1절) |
| `tests/test_answer_images.py` | 다시 작성(옛 계보 → 현행), `conftest.py` 수집 제외 해제 |
| `tests/test_excel_ingest_pipeline_sample.py` | 샘플 실제 적재 후 Step 6 사진 후보·검증·자동 첨부 단언 추가 |

**프런트엔드 (`adrag_frontend/`, 주석 `2026.10.19(sooyeon.choi) 추가/수정`)**

| 파일 | 내용 |
|---|---|
| `src/utils/answerImages.js` (신규) | `[IMG:ref]` → 배지·단계별 썸네일, 미완성 태그 숨김, `시트!셀` 표기 |
| `src/composables/useImageBlobs.js` (신규) | 이미지 API blob 캐시(resource_id별 1회, 실패 기억, 해제) |
| `src/components/AnswerImageSection.vue` (신규) | [관련 이미지] 카드 |
| `src/components/ImageViewer.vue` (신규) | 이미지 뷰어 |
| `src/composables/useChatView.js` | SSE `images`, 비스트리밍·이력 복원 `images`, 스트리밍 중 미완성 태그 숨김 |
| `src/views/ChatView.vue` | 본문 사진 렌더·클릭(이벤트 위임), [관련 이미지], 뷰어·[문서 위치], 복사 텍스트에서 태그 제외, 스타일 |
| `tests/answerImages.test.mjs` (신규) | 6개 |

**문서**: 이 보고서, `06_미결_이슈_목록.md`(목업 차이·반영할 것).

목업·요구사항 원본, `excel_ingest`, docling-parser, DB 스키마는 수정하지 않았다.

## 3. 완료 기준 충족 근거

작업지시서 v3.1 Phase 4 완료 기준 중 사진 항목: "FAN 모듈 REACT FAN 조립 체크포인트 질의 → Step 6 사진 포함, 후보에 없는 IMG ID 제거".

| 검증 | 결과 |
|---|---|
| `tests/test_answer_images.py` (로컬) | **9 passed, 1 skipped**(스트리밍 1개는 로컬에 `langgraph` 없음 → 아래 컨테이너에서 실행) |
| 같은 파일 + `test_rag_stream.py` (dev 컨테이너, langgraph 있음) | `test_answer_images.py` **10 passed**. `test_rag_stream.py` 1 failed — **기존 문제**: 테스트의 가짜 설정에 `sqlite_db_path`가 없음(`rag_service.py`가 원래 읽던 값, 이번 변경 전부터). 로컬에선 늘 skip이라 드러나지 않았다 |
| 실제 행 테스트(PostgreSQL) | 제외 7종(emf·장식·연결 안 함·삭제·이전 버전·다른 문서·같은 이미지) 확인, 질의어·역할 정렬, 분석 완료 사진 표시, 문서 삭제 시 0건, 표 청크 행 범위(범위 밖·인쇄 영역 밖 제외, docling 청크는 범위 대체 안 함) |
| 노드 | 설정 끔 → 후보 0·태그 전부 제거, 예산 초과 시 뒤 후보 제외, 근거 없음 → 자동 첨부 안 함, Step 답변 무인용 → Step 사진 1장 |
| 스트리밍 | 이벤트 순서 `token → citations → images → meta → done`, 대화 이력에 검증 후 본문과 `images` 저장 |
| 샘플 실제 적재(`test_excel_ingest_pipeline_sample.py`) | **1 passed**(26초): excel_ingest로 적재한 Step 6 청크 → 1순위 후보가 Step 6 Step 사진, 후보는 모두 그 청크의 `resource_ids`, 가짜 `[IMG:zz9999]` 제거, 무인용 시 Step 6 사진 자동 첨부 |
| 프런트 `node --test tests/*.test.mjs` | **9 passed**(신규 6 + 기존 3) |
| `vite build` | 성공(출력은 저장소 밖, 삭제) |

**dev 실E2E**(rag-backend-dev, 실제 Qdrant·임베딩·리랭커·LLM, dev에 있던 `NEOCON C2 제조 관리 문서 대장.xlsx` v3). 질의 로그·대화 이력을 남기지 않도록 API 대신 컴파일된 그래프를 직접 실행했다.

| 질의 | 근거(시트·Step) | 결과 |
|---|---|---|
| FAN 모듈 REACT FAN 조립 체크포인트 | FAN Module 조립 Step 6·Step 9 | 후보 1순위 **Step 6 REACT FAN Step 사진**(C18). 답변 본문에 `[1][IMG:…]`로 인용(`cited=true`) — **완료 기준 충족** |
| PROCESS FAN 방진고무 체결 방법 | Step 5·Step 7 | Step 5 Step 사진 + 확대도 2장 인용 |
| 재생 FAN 품번 | 핵심 부품 List(연결 사진 없는 표) | 행 범위 대체로 부품 사진 8장 후보 → "재생 FAN · MEC21103" 사진 1장 인용 |

- 프롬프트 조정(실측): 규칙 한 줄만 줬을 때는 LLM이 태그를 쓰지 않아 자동 첨부로만 사진이 붙었다. 실제 후보 ID로 예시(`...체결합니다[1][IMG:xxxxxx].`)를 넣은 뒤 3개 질의 모두 본문 인용이 나왔다. 같은 질의를 다시 돌리면 인용 없이 답할 때도 있다(LLM 비결정성) — 이때는 자동 첨부로 [관련 이미지]에 1장이 나온다.

**화면 확인**(Playwright, 로컬 vite → dev 백엔드, 사용자 AIE 토큰). 스트리밍 응답만 위 E2E 결과로 만든 고정 응답으로 바꾸고 GET 이외 요청은 막아 dev DB에 기록이 없음을 확인했다(최근 1시간 질의 로그 0건).
- 본문 배지 `1` + 목록 항목 아래 썸네일(실제 이미지 API로 받은 325×544 이미지), [관련 이미지] 카드 `FAN Module 조립!C17`, 가짜 `[IMG:zz9999]` 화면에서 제거
- 뷰어: 제목·`1 / 1`·출처·주변 설명, Esc 닫기, [문서 위치] → 뷰어 닫고 출처 [1] 활성
- 스크린샷은 샘플 추출 사진이 들어 있어 확인 후 삭제했다.

## 4. 마이그레이션·되돌리는 방법

- 마이그레이션 없음(기존 Phase 2 테이블만 읽음).
- 끄기: `ANSWER_IMAGES_ENABLED=false` → 프롬프트·응답이 이전과 같아진다(`images`는 빈 목록, SSE `images` 이벤트 없음).
- 코드 되돌리기: 2절 파일을 이전 판으로. 신규 파일 6개 삭제, `conftest.py`의 `test_answer_images.py` 수집 제외 복원. 대화 이력에 저장된 `images` 키는 이전 화면이 무시한다.

## 5. 백엔드 전체 회귀

`pytest -m "not e2e and not voice" --continue-on-collection-errors` (10-19, 5분 42초): **465 passed / 11 failed / 17 skipped / 3 errors**

- 기준선(document-versions 6절) 456 / 11 / 16 / 3 대비 **신규 실패 0**. 통과 +9·skip +1 = 다시 쓴 `test_answer_images.py`(로컬 9 passed, 스트리밍 1 skip).
- 실패 11건 파일: parse_regression 1, deletion_consistency 1, eval_e2e 1, eval_kiwi_direct_search 2, eval_routes 1, multi_document_upload 1(`requeue_failed`), rule_based_metric_regressions 2, spreadsheet_payload 1, unified_auth_routes 1(`ui_type`) — 기준선 목록과 같음. 오류 3건도 같음(stats_api·voice 2개 수집 순서).
- 중간 경과: 첫 전체 실행에서 신규 테스트가 기존 순서 의존 문제(다른 테스트가 수집 중 `app.core.config`를 stub으로 바꿈)로 수집 오류 → 옛 판과 같은 방식으로 import 동안만 실제 설정 모듈을 쓰게 고친 뒤 통과. 제품 코드 결함 아님.
- 다음 Phase 시작 시 기준선: **465 / 11 / 3**.

## 6. 남은 이슈

| # | 내용 | 처리 |
|---|---|---|
| 1 | **이미지 API 권한**: `/api/spreadsheet-resources/{id}`의 권한 판단(`_authorize_document`)이 검색과 따로 있다 — 접근 가능 주제가 빈 목록이면 검색은 "전체 허용", 이미지 API는 "차단". 권한 없을 때 403(D-04는 404). 답변 사진 후보는 검색을 통과한 청크의 같은 문서 사진만 쓰므로 답변에 남의 사진이 섞이지는 않는다 | 4-B(`allowed_acl` 통합) |
| 2 | 대화 이력의 사진 목록은 저장 시점 기준이다. 나중에 권한이 빠지면 이력의 제목·`시트!셀`은 보이고 이미지 자체는 이미지 API가 막는다 | 4-B 권한 통합 때 이력 응답에서 거를지 결정 |
| 3 | 출처 패널(UI-05, ANS-03) "연결된 이미지 N장" 화면 | 백엔드 필드는 8절에서 추가, 화면은 프런트 개발자(07 명세 ⑧) |
| 4 | 이미지 API에 `size=thumb|preview`(02 문서 API-06) 없음 — 썸네일도 원본을 받는다(샘플 사진은 수십 KB~수백 KB) | 4-B 또는 5(emf·wmf 변환과 함께) |
| 5 | emf·wmf 사진은 후보에서 뺀다(변환 전까지 표시 불가) | 5 |
| 6 | 질의 로그(`tb_query_logs`)·출처 기록에는 사진을 남기지 않는다(대화 이력에만). 평가(사진 포함 여부, Phase 7)에 필요하면 추가 | 7 |
| 7 | LLM이 사진을 인용하지 않는 경우가 있다(비결정성). 자동 첨부로 최소 1장은 나오지만 본문 인라인 썸네일은 인용될 때만 나온다 | 7 모델 비교 때 함께 평가 |
| 8 | `test_rag_stream.py` 기존 실패(가짜 설정에 `sqlite_db_path` 없음) — 로컬은 langgraph 없어 skip | 테스트만 고치면 됨(이번 범위 밖이라 그대로 둠) |
| 9 | 로컬 Python에 `langgraph`가 없어 질의 그래프 관련 테스트가 로컬에서 skip된다(requirements에는 있음) | 사용자 확인 — 로컬 설치 또는 컨테이너에서 실행 |

### 결정 필요

- **Q-4A-1** 사진 자동 첨부(인용 없을 때 1장)를 유지할지. 추천: **유지**(완료 기준 "Step 6 사진 포함"을 LLM 비결정성과 무관하게 보장). 끄려면 `ANSWER_IMAGE_AUTO_ATTACH=false`.
- **Q-4A-2** 대화 이력 사진의 권한 재확인 위치(위 2번). 추천: 4-B에서 이력 응답 시 `allowed_acl`로 거름.

## 7. 요구사항 정의서·기능 목록에 반영할 것

- 설정 `ANSWER_IMAGES_ENABLED`·`RAG_MAX_IMAGES`·`RAG_IMAGE_CANDIDATES`·`ANSWER_IMAGE_AUTO_ATTACH`
- API-05 응답: 비스트리밍 `images[]`, SSE `images` 이벤트(필드는 1절), 답변 본문 `[IMG:ref]` 태그 규칙(ref = 이미지 내용 해시 앞 6자 이상)
- 대화 이력 답변 항목 `images`(R4-7 준비)
- MOD-09 그래프 노드 `collect_answer_images` 추가
- 화면 UI-03·UI-04 구현 범위(1절), [원본 열기]는 원본 파일 새 탭(별도 원본 크기·미리보기 크기 구분 없음)

## 8. 추가 (10-19) — 사진 목록 API 필드

사용자 요청으로 4-B 예정이던 출처 패널용 필드를 먼저 넣었다(프런트 개발자 연동용, `07_프런트_연동_명세_챗봇.md` ⑧).

- `GET /api/documents/{document_id}/spreadsheet-resources` 항목에 추가: `title`, `role`, `step_no`, `step_title`, `version_no`, `in_print_area`, `review_status`, `displayable`. 기존 필드·권한·삭제 사진 제외 동작은 그대로(추가만).
- `title`·`displayable` 규칙을 `app/services/resource_labels.py`로 모아 답변 사진(`app/graphs/images.py`)과 같은 함수를 쓴다(답변 사진 제목 형식은 바뀌지 않음).
  - `displayable` = 브라우저 표시 형식(png·jpeg·gif·webp·bmp) AND 장식·양식 머리글 아님 AND 검수 "연결 안 함" 아님 AND 삭제 아님.
- 이 목록에는 이전 버전 사진도 있다(기존 동작). 출처 패널은 `citation.resource_ids`로 거르면 현재 버전만 남는다.
- 변경 파일: `app/services/resource_labels.py`(신규), `app/services/spreadsheet_resource_service.py`, `app/graphs/images.py`(공용 함수 사용), `tests/test_answer_images.py`(+1).
- 검증: 신규 테스트(제목·역할·표시 여부·답변 사진과 제목 일치·경로 비노출) 포함 관련 3파일 **30 passed**. dev 실데이터(NEOCON v3): 현재 버전 190장 중 `displayable` 167장(장식 15·양식 머리글 7 등 제외), Step 6 사진 제목이 답변 사진과 같음.
- 전체 회귀: **466 passed / 11 failed / 17 skipped / 3 errors** — 기준선 465/11/3 대비 +1(신규 테스트), 실패·오류 목록 동일, 신규 실패 0. 다음 기준선 **466 / 11 / 3**.
- 되돌리기: 위 파일을 이전 판으로(추가 필드만 사라짐).
