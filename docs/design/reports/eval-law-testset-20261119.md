# 단일 출처 평가 데이터셋(법령 조항·일반 문서) + 시험 데이터셋 다운로드 — 2026-11-19

- 작성: sooyeon.choi
- 설계: `eval-law-testset-design-v1.0.md` (상단 "구현 반영" 참고)
- 관련: AI+ 인증 시험 합의서 시험 1(Recall@10)·2(NDCG@5)·3(LLM 심사 정답 데이터)·4(평균 반환 시간)

## 1. 요약

| 항목 | 내용 |
|---|---|
| 생성 방식 추가 | `generation_mode` = `law_article`(법령 조항) / `single_section`(일반 문서). 기본 `typed` = 기존 유형별 생성 그대로 |
| 단일 출처 | 질의 1건 = 근거 청크 1개. 멀티홉 경로를 쓰지 않음. 프롬프트 규칙 + 자동 검사(답변 숫자·조항 번호가 근거 본문에 있어야 함, 실패 시 사유를 넣어 1회 재생성 → 그래도 실패면 대체 후보) |
| 배분 | 조항(섹션) 단위로 같은 간격 선택. 법률 → 시행령 순. 부칙·조항 정보 없음·본문 80자 미만 제외. 별표는 기본 보충용(`include_annex`). 모자라면 2바퀴 → 별표 → 같은 청크의 두 번째 질문(최대 2) |
| 고아 포인트 제외 | Qdrant에만 있고 DB에서 지워진 문서·비활성 버전 청크는 생성 대상에서 뺀다(DB 활성 버전 청크로 거름) |
| 검색 미검출 재생성 | 단일 출처 생성에서는 하지 않음(순위만 기록) — 시험 수치를 부풀리지 않기 위함 |
| 데이터셋 다운로드 통합 | 데이터셋 목록 다운로드 버튼을 **하나로 통합** → `질의`·`정답 근거`·`검수 정보`·`요약` 시트 xlsx. 기존 승인 QA Excel 버튼은 내용이 겹쳐 화면에서 숨김(API `approved-items.xlsx`는 유지, 사용자 결정 11-19) |
| 일괄 질의 정답 대조 수정 | **청크ID를 Qdrant 포인트 ID로 통일**(검색 결과와 같은 ID). 11-18 구현은 DB 청크 키로 비교해 실제 실행 시 적중이 항상 0이었음 |
| 합의서 계산식 반영 | Recall@10·NDCG@5 분모 = **전체 시험 질의 수**. `청크ID` 열이 있는 정답 파일은 매칭 없이 바로 확정 → 스크립트 한 번 실행으로 Recall@10(%)·NDCG@5·평균 반환 시간 출력 |

## 2. 사용 방법 (시험 데이터셋)

1. 평가 > 데이터셋 > 새 데이터셋
   - 대상 컬렉션: `AIE_산업안전보건법` 또는 `AIE_중대재해처벌법` (법령마다 데이터셋 1개)
   - 생성 방식: **법령 조항 (단일 출처, 조항별 고르게)**
   - 생성 목표 건수: 60
   - 생성 모델: `gemma-4-31B-it-FP8`
   - 조항 직접 언급 비율: 30%(기본)
   - 질의ID 접두어: 예) `산안`, `중처`
2. 생성된 문항을 검수(승인·수정·반려)한다. **승인·수정 문항만** 내보낸다.
3. 다운로드 칸의 두 번째 버튼(시험 데이터셋) → xlsx를 받는다.
   - `질의`: 질의ID·질의문·정답 답변 → 그대로 일괄 질의 파일
   - `정답 근거`: 질의ID·근거순번·근거 문서명·근거 조항·페이지·청크ID·근거 내용 → 그대로 정답 파일
   - `요약`: 생성 방식·모델·문서 버전·법령별/장별 문항 수·버전 변경 경고
4. 시험 실행: `python scripts/eval_batch_query.py --base-url <주소> --collection <컬렉션> --file 시험.xlsx --gold 시험.xlsx --out ./result`
   - 출력: `[시험 1] Recall@10 %`, `[시험 2] NDCG@5`, `[시험 4] 평균 반환 시간(ms)`

## 3. dev 데이터 확인 결과 (배분 미리보기, 실제 생성 전)

| 컬렉션 | 활성 문서 | 조항 단위 | 별표 | 60문항 배분 결과 |
|---|---|---|---|---|
| AIE_산업안전보건법 | 시행령 1건(339청크) | 86 | 11 | 조항 60개에서 1문항씩(부칙 69청크·짧은 27청크 제외) |
| AIE_중대재해처벌법 | 법률 23청크 + 시행령 44청크 | 26 | 4 | 조문·별표 청크 50개 + 같은 청크 두 번째 질문 10개 |

- `AIE_산업안전보건법` Qdrant에는 DB에 없는 문서의 포인트 647개가 남아 있다. 생성 대상에서는 빠지지만 **검색에는 나온다**(아래 7-1).

## 3-1. 검수 화면 보완 (11-19 사용자 결정)
- 문구: "검색 미검출" → **"검색 확인 필요"**(배지·건수·필터·빈 목록 문구). 설명: "생성 직후 사전 검색에서 원본 근거가 상위 10위 밖이었던 문항(검수 참고용)"
- **같은 조항(섹션)으로 다시 생성** 버튼: `POST /api/eval/items/{qa_id}/regenerate`
  - 대상: 법령 조항·일반 문서 방식 문항 중 '검색 확인 필요'(순위 없음)만. 유형별 문항 400, 순위 있는 문항 409, 생성 중 409
  - 사람이 누를 때 1회만 실행(자동 반복 없음). 근거 청크ID·근거 내용은 그대로, 기존 질문을 "이미 만든 질문"으로 넣어 다른 질문 생성, 단일 출처 검사 동일 적용
  - 결과는 새 검색 순위 기록 + **검수 대기(pending)**로 되돌림. 이전 질문은 `source_meta.previous_questions`, 횟수는 `regenerate_count`
  - 주의: 검색 결과를 보고 고르는 동작이라 시험 데이터 편향 소지가 있음 → 질문 품질(모호·여러 조문 걸침)을 보고 쓸 것
- 데이터셋 생성 때 쓴 모델(gen_config의 llm_model)로 다시 생성. 모델 서버가 꺼져 있으면 400

## 4. 변경 파일

| 구분 | 파일 |
|---|---|
| 마이그레이션 | `adrag_backend/migrations/versions/0013_eval_qa_single_source.py` (신규) |
| 생성 | `app/evaluation/dataset/single_source.py`(신규), `generator.py`, `prompts.py`, `app/evaluation/schemas.py` |
| 저장소 | `app/repositories/evaluation_repository.py`(`active_chunk_versions`, `document_versions`), `app/repositories/eval_batch_repository.py`(포인트 ID, `chunk_versions`, `replace_gold(gold_status)`) |
| 다운로드 | `app/evaluation/excel_exporter.py`(`build_testset_workbook`, 유형 라벨 법령·일반), `app/routes/evaluation.py`(`GET /datasets/{id}/test-set.xlsx`, 생성 방식 검증) |
| 정답 대조 | `app/evaluation/batch/recall.py`, `gold_matcher.py`, `file_reader.py`(시트 선택), `app/routes/eval_batch.py`, `scripts/eval_batch_query.py` |
| 화면 | `adrag_frontend/src/api/evalApi.js`, `composables/useEvalDatasets.js`, `views/EvalDatasetView.vue` |
| 테스트 | `tests/test_eval_law_testset.py`(신규 13개), `tests/test_eval_batch_query.py`(포인트 ID·분모·청크ID 직접 확정 3개 추가) |

주석: `2026.11.19(sooyeon.choi) 추가/수정 - 설명`.

## 5. 테스트 결과

- 평가 관련 6개 파일(`test_eval_law_testset`·`dataset`·`excel_export`·`batch_query`·`routes`·`repository`): **85 passed, 3 skipped**(langgraph 필요분)
- 전체(로컬): 583 passed / 17 failed / 29 skipped / 13 errors (이전 기준 568 / 15 / 29 / 13)
  - 실패 15건은 예전부터 있던 것: 마이그레이션 head 기대값 3, unified_auth 1, parse_regression 1, 순서 의존 stub 오염 10
  - 나머지 2건(`test_eval_run_excel_export`)은 평가 실행 Excel 라벨이 직접 수정되어("답변 생성 응답시간(전체)", "전체 응답시간(s)") 테스트 기대값과 다른 것. 이번 변경과 무관
- 0013 upgrade → downgrade(0012) → upgrade 왕복 확인
- dev 백엔드 이미지 재빌드, 기동 시 `0012 → 0013` 자동 적용, 변경 파일 md5 일치
- 화면 `npm run build` 통과

## 6. 마이그레이션·되돌리기
- `0013_eval_qa_single_source`: `tb_eval_qa_items.question_type` CHECK에 `law`, `general` 추가. upgrade → downgrade(0012) → upgrade 왕복 확인.
- downgrade는 `law/general` 문항이 있으면 중단한다(해당 데이터셋 먼저 삭제).
- 기능 끄기: 생성 방식을 `유형별`로 두면 기존과 같다.

## 7. 남은 이슈
1. **`AIE_산업안전보건법` 고아 포인트 647개가 검색에 나온다.** 같은 시행령의 이전 등록본이 남아 있어 같은 조문이 ID만 다르게 검색될 수 있다 → 시험 전 정리 필요(되돌릴 수 없는 삭제라 승인 후 진행). 시험 서버는 새로 등록 권장.
2. `AIE_산업안전보건법`에는 **시행령만** 있다. 시험 대상이 법률 본문이면 법률을 추가 등록해야 한다(중대재해처벌법 컬렉션은 법률+시행령).
3. 두 법령이 서로 다른 컬렉션이라 일괄 질의도 컬렉션별 2회(60+60) 실행된다. 합의서 계산식(전체 120 기준)은 두 결과를 합산해야 한다 → 합산 출력 또는 한 컬렉션 통합 여부 결정 필요.
4. 3종 LLM 심사(시험 3) 미구현. 정답 데이터(근거 내용·문서명·조항·페이지)는 이번 시험 데이터셋에 포함됨.
5. `tests/test_database_migrations.py` 3건은 예전부터 head를 0010으로 기대해 실패(이번 변경과 무관, 기대값 갱신 필요).
