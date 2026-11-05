# 엑셀 사진 전부 자동 연결 보고서 (2026-10-22)

> 결정: 변경로그 **D-20** — 장식·양식 머리글을 뺀 모든 엑셀 사진을 셀 위치 기준으로 청크에 자동 연결하고, 사진 연결 검수 화면(UI-15)은 1차에서 만들지 않는다.
> 관련 ID: R3-2(사진↔작업 단계 연결), R3-5(연결 검수 → 1차 제외), F-3-04, UI-15·API-08(1차 제외), SC-02(사진 포함 답변)

## 1. 요약

- 이전(Phase 2): **SOP 시트의 Step 표 안 사진만** Step 청크에 ID로 연결했다. 나머지는 답변할 때 표 청크 행 범위로 찾거나 아예 찾지 못했다.
- 10-22 dev 점검(C2 샘플 190장): ID 연결 47장, 행 범위로 찾음 68장, 장식·머리글 22장, **어디에도 안 나옴 53장**. 재생 Heater 시트 Step 0 청크에 **Step 1 사진 오연결** 2건(Step 0이 두 번 나오는 표 + 같은 그림 교차 연결), Step 6·7 교차 연결 2건.
- 이번 변경(`EXCEL_IMAGE_LINK_ALL=true`, 기본값): 적재할 때 모든 사진을 다음 순서로 청크에 연결한다.
  1. **step**: 파서가 Step을 정한 사진 → 같은 Step 번호 청크(Step 번호가 겹치면 사진 시작 행이 드는 청크)
  2. **row_overlap**: 사진 행 범위와 겹치는 청크 전부
  3. **nearest**: 같은 시트에서 행 거리가 가장 가까운 청크(같으면 위쪽). 거리 제한 없음
  4. **image_chunk**: 위치가 있는 글자 청크가 없는 시트 → excel_ingest가 만든 이미지 청크(위치 설명)를 적재하고 연결
- 청크 위치: Step·공정단계 = IR `steps[].rows`, 표 = `meta.rows`, 안내문 = `shape_range`, 개요 = IR `header_kv` 행. 체크박스·흐름도 청크는 위치가 없어 대상이 아니다.
- 한 청크 안의 사진 순서: step → row_overlap → nearest → image_chunk, 같은 방식이면 배치 순서.
- 연결 결과는 기존과 같은 곳에 저장한다: `tb_chunk_resources` + Qdrant payload `resource_ids`. 답변 경로(`app/graphs/images.py`)는 바꾸지 않았다.
- `excel_ingest`·docling-parser·DB 스키마·목업·요구사항 원본은 수정하지 않았다.

## 2. 변경 파일

| 파일 | 내용 |
|---|---|
| `adrag_backend/app/ingest/excel_images.py` | `link_excel_images`(청크 위치 계산·연결 규칙 1~4·요약), `ExcelImageLinks`, 계획에 배치 목록(`items`) 추가 |
| `adrag_backend/app/ingest/excel_chunks.py` | `resource_ids_by_index`(청크 순번 → 사진)·`keep_indexes`(적재할 이미지 청크) 인자. 없으면 기존 동작 |
| `adrag_backend/app/services/ingest_pipeline.py` | 설정이 켜져 있으면 연결 계산 → 청크 변환에 전달, 처리 요약에 `image_links`, 미연결 경고 로그 |
| `adrag_backend/app/core/config.py`, `.env.example` | `EXCEL_IMAGE_LINK_ALL`(기본 true) |
| `adrag_backend/tests/test_excel_image_links.py` (신규) | 규칙 단위 테스트 6건 |
| `adrag_backend/tests/test_excel_ingest_pipeline_sample.py` | 샘플: 168장 전부 연결·DB 미연결 0·payload 168장·Step 청크에 다른 Step 사진 0 |
| `docs/design/01_결정사항_변경로그.md` | D-20 추가 |

## 3. 완료 기준 충족 근거

| 항목 | 결과 |
|---|---|
| 샘플 연결 수(파싱만, DB 없이) | 배치 190 = 제외 22 + **연결 168 + 미연결 0**. 방식별 step 47 / row_overlap 77 / nearest 44 / image_chunk 0. 청크 수 240(변경 전과 같음) |
| 기존 Step 연결 보존 | 이전 연결 51건 중 47건 유지, 빠진 4건은 ②에서 확인한 오연결·교차 연결(Heater Step 0의 Step 1 사진 2건, Step 6·7 교차 2건) |
| 단위 테스트 | `test_excel_image_links.py` 6 passed — Step 0 중복·보정된 확대도·같은 그림 두 Step, 겹침(여러 청크), 가장 가까운 청크·위아래 같을 때 위쪽, 안내문 위치·순서, 장식 제외, 사진만 있는 시트의 이미지 청크, 분할 청크 |
| 샘플 통합 테스트 | `test_excel_image_links` + `test_excel_ingest_pipeline_sample` + `test_ingest_records` + `test_excel_ingest_routing` **32 passed**(74초). 기존 Phase 2·4-A 단언(Step 6 사진 1순위 등) 유지 |
| 전체 회귀 | `-m "not e2e and not voice"` **479 passed / 11 failed / 17 skipped / 3 errors**(67분). 기준선(10-20) 473/11/3 대비 +6 = 신규 단위 테스트. 실패 11·오류 3은 기준선과 같은 기존 문제(평가·인증·`requeue_failed`·parse_regression·stats/voice 수집 순서)로, 이번 변경 파일과 무관 |

청크당 연결 사진 수(조각 0 기준): 0장 67청크, 1~5장 55청크, 8장 이상 6청크(최대 21장 — Recheck Sheet 표 청크). 답변에는 후보 정렬(질의어 일치 → 역할 → 같은 Step·시트 → 신뢰도) 후 최대 `RAG_IMAGE_CANDIDATES`(8)장만 후보, `RAG_MAX_IMAGES`(4)장만 표시된다.

## 4. 마이그레이션

없음. 이미 적재한 문서는 바뀌지 않는다. 반영하려면 문서를 **삭제 후 다시 등록**한다(사용자 결정, 재연결 스크립트 없음). 같은 파일로 [최신본 변경]은 409(같은 파일)라 쓸 수 없다.

## 5. 되돌리는 방법

- 설정: `.env`에 `EXCEL_IMAGE_LINK_ALL=false` → Phase 2 동작(SOP Step 사진만 연결). 이후 다시 등록한 문서부터 적용.
- 코드: 2절 파일을 이전 판으로 복원, `test_excel_image_links.py` 삭제.

## 6. 남은 이슈

| 구분 | 내용 |
|---|---|
| 확인 필요 | 검사표 시트(출하검수Sheet 등)는 그림이 많아 표 청크 하나에 사진이 많이 붙는다(최대 21장). 표시 상한(4장)과 정렬로 걸러지지만, 관련 낮은 그림이 나오는지 dev 질의로 확인 필요 |
| 확인 필요 | nearest는 거리 제한이 없어 멀리 떨어진 그림도 붙는다(요구: "무조건 연결"). 답변 품질 문제가 보이면 시트 유형별 거리 상한을 설정으로 추가 |
| 미반영 | `tb_spreadsheet_resources.link_method`·`link_confidence`는 파서 판정 그대로이고, 청크 연결 방식(step/row_overlap/…)은 문서 단위 요약(`summary_json.image_links.by_method`)에만 남는다. 사진별로 필요하면 `tb_chunk_resources`에 컬럼 추가(마이그레이션) |
| 기존 | 관리대장(register) 시트는 excel_ingest가 청크를 만들지 않아, 그 시트의 사진은 연결할 청크가 없다(샘플에는 없음). 생기면 처리 요약 `unlinked`와 경고 로그로 드러난다 |
| 기존 | Main Frame 조립 시트가 SOP로 분류되지 않는 것(excel_ingest 분류 규칙)은 그대로. 이번 규칙으로 사진은 표 청크에 연결된다 |
| 기존 | 추출 범위: excel_ingest는 도면 영역의 `pic`만 읽는다. 그림 채우기 도형·셀 안 그림·머리글/바닥글·배경·차트 안 그림은 추출되지 않는다(샘플에는 없음, 수정 시 승인 필요) |

## 7. 요구사항 정의서·기능 목록에 반영할 것

- R3-2: "사진을 해당 작업 단계에 자동으로 연결하고, 담당자 검수로 정확도를 맞춘다" → "모든 사진을 셀 위치 기준(Step → 행 겹침 → 가장 가까운 내용)으로 자동 연결한다".
- R3-5(연결 검수): 1차 제외(2차 또는 삭제). UI-15·API-08 1차 제외.
- 작업지시서 v3.1 Phase 5: 할 일 3과 완료 기준 "검수 반영 후 사진이 바뀌고 재등록 시 검수 결과 유지" 제외.
- 신규 설정 `EXCEL_IMAGE_LINK_ALL`.
