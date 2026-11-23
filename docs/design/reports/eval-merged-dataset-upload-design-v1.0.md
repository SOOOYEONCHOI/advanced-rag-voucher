# 합본 데이터셋 xlsx 업로드 등록 설계 v1.0 (초안)

- 작성: 2026-11-23 (sooyeon.choi)
- 목적: 평가 실행은 지금처럼 **등록된 데이터셋(확정 골드셋)** 으로 한다. 여기에 더해, 합본 시험 데이터셋 xlsx(시험 데이터셋 다운로드와 같은 형식)를 **업로드해서 데이터셋으로 등록**하고, 등록되면 기존 평가 실행에서 바로 고를 수 있게 한다.
- 쓰임: 다른 서버(dev ↔ 운영)에서 만든 합본을 옮겨 오기, 시험기관이 준 질의·정답 근거 파일로 사전 평가하기, 생성·검수 없이 정해진 문항으로 평가하기
- 관련: `eval-merged-dataset-design-v1.0.md`(합본), `eval-law-testset-design-v1.0.md`(시험 데이터셋 xlsx 형식), `eval-batch-query-phase1-20261118.md`(정답 근거 읽기·매칭)
- 상태: **초안. 9장 결정 사항 확정 후 구현한다.**

## 1. 원칙

1. **평가 실행 로직은 바꾸지 않는다.** 업로드도 결과적으로 "확정된 데이터셋 + 골드셋 v1" 하나를 만들 뿐이다. 실행, 지표, 결과 화면, 결과 xlsx는 기존 합본과 같다.
2. **합본과 같은 저장 구조를 쓴다.** `dataset_kind = "merged"`에 `origin = "upload"`를 더한다. 합본에 있는 보호(문항 수정·확정·재생성 금지, 법령별 집계, 저장된 질의ID 사용)를 그대로 받는다.
3. **DB 마이그레이션은 없다.** 기존 열(`gen_config_json`, `source_meta_json`)만 쓴다.
4. **업로드 파일은 서버에 저장하지 않는다.** 읽어서 문항으로 바꾸면 버리고, 파일 이름·해시·크기만 기록한다(절대 규칙 3).
5. **틀린 파일은 등록하지 않는다.** 일부만 등록하지 않고, 오류가 하나라도 있으면 행 번호와 사유를 보여 주고 멈춘다(평가 수치가 조용히 틀어지는 것을 막는다).
6. 설정 `EVAL_DATASET_UPLOAD_ENABLED`(기본 true)로 켜고 끈다. 끄면 업로드 API는 404, 버튼은 숨김.

## 2. 사용자 흐름

```
[평가 실행] 화면
  골드셋 선택 ▼  [xlsx로 데이터셋 등록]   ← 새 버튼
        │
        ▼ ① 파일 선택(.xlsx)
  ┌─ 미리보기 (서버가 읽고 검사만, 저장 안 함) ─────────────┐
  │ 문항 120 · 법령 2                                         │
  │ 법령            문항  검색 컬렉션(자동 → 바꿀 수 있음)    │
  │ 산업안전보건법    60   [AIE_산업안전보건법 ▼]  청크 60/60 ✓ │
  │ 중대재해처벌법    60   [AIE_중대재해처벌법 ▼]  청크 58/60 ✗ │
  │ 오류 2건: 정답 근거 15행 청크ID 없음(컬렉션에 없음) …      │
  │ 데이터셋 이름 [시험 합본(업로드) 120]                      │
  │                          [취소] [등록] (오류 있으면 꺼짐)  │
  └───────────────────────────────────────────────────────────┘
        │ ② 등록 → 데이터셋 + 골드셋 v1 생성(바로 확정)
        ▼
  골드셋 목록 새로고침, 방금 등록한 골드셋이 선택됨 → 기존 [평가 실행]
```

- 등록된 데이터셋은 **평가 데이터셋 목록**에도 `합본` `업로드` 배지로 보인다. 다운로드·삭제는 기존 합본과 같다.
- 파일을 고친 뒤 다시 올리면 **새 데이터셋**으로 등록된다(덮어쓰지 않음, 이전 실행 결과 보존).

## 3. 받는 xlsx 형식

시험 데이터셋 다운로드 파일(`build_testset_workbook`)과 같다. 우리 화면에서 내려받은 파일은 그대로 올릴 수 있다.

### 3.1 `질의` 시트 (필수)
| 열 | 필수 | 비고 |
|---|---|---|
| 질의ID | ✓ | 파일 안에서 중복 금지. 그대로 저장(`source_meta.query_id`) |
| 질의문 | ✓ | 최대 길이는 일괄 질의와 같은 `EVAL_BATCH_QUERY_MAX_CHARS`(기본 2000자) 기준 |
| 정답 답변 | 권장 | 비어도 등록(F2 정답 유사도는 그 문항 제외) |
| 법령 | 합본 | 검색 컬렉션을 정하는 값. **없으면 단일 컬렉션 파일**로 보고 미리보기에서 컬렉션 1개를 고른다 |

### 3.2 `정답 근거` 시트 (필수)
| 열 | 필수 | 비고 |
|---|---|---|
| 질의ID | ✓ | `질의` 시트에 있는 ID만 |
| 근거순번 | | 없으면 행 순서 |
| 청크ID | ✓ (v1) | 그 문항 법령의 컬렉션에 **지금 있는** 청크여야 한다(문서 재등록으로 바뀐 ID 차단) |
| 근거 문서명·근거 조항·페이지·근거 내용 | | 저장해 두고 결과 화면 참고용으로 쓴다 |

- 읽기는 일괄 질의의 `read_table`·`read_gold_file`(열 이름 별칭, 근거순번 중복 검사)을 재사용한다.
- 정답 근거가 없는 질의는 오류로 본다. 거절 평가용 문항(정답 근거 없음)은 v1 범위 밖이다(9장 Q4).

### 3.3 `검수 정보`·`요약` 시트 (선택)
- `검수 정보`가 있으면 유형·기대 동작·태그·난이도를 가져온다. 없으면 기본값(`law`·`answer`·`[]`·`normal`)을 쓴다.
- `요약`은 읽지 않는다.

## 4. 검사 규칙 (미리보기와 등록이 같은 함수 사용)

| # | 검사 | 실패 시 |
|---|---|---|
| V1 | 확장자 .xlsx, 크기 ≤ 10MB, `질의`·`정답 근거` 시트 있음, 필수 열 있음 | 파일 오류(등록 불가) |
| V2 | 문항 수 1 ~ `EVAL_BATCH_MAX_ROWS`(기본 500) | 오류 |
| V3 | 질의ID 빈 값·중복, 질의문 빈 값·길이 초과 | 행 오류 |
| V4 | 정답 근거의 질의ID가 `질의` 시트에 없음, 근거순번 중복 | 행 오류 |
| V5 | 질의마다 청크ID 1개 이상 | 행 오류 |
| V6 | 법령 → 컬렉션: 법령 값과 컬렉션 **표시 이름**이 같으면 자동 연결. 없으면 미리보기에서 사용자가 고른다 | 연결 안 된 법령이 있으면 등록 불가 |
| V7 | 청크ID가 연결된 컬렉션에 있는지(Qdrant 조회, 활성 청크) | 행 오류(청크ID·행 번호 표시) |
| V8 | 셀 값이 수식으로 시작(`=`,`+`,`-`,`@`)하면 문자로 저장 | 경고만 |

- 등록 API도 V1~V7을 **다시** 검사한다(미리보기 뒤 컬렉션이 바뀌었을 수 있음).

## 5. 데이터 구조 (마이그레이션 없음)

### 5.1 `tb_eval_datasets`
| 열 | 값 |
|---|---|
| `name` | 사용자 입력(기본: 파일 이름 기반) |
| `collection_id` | 첫 법령의 컬렉션(NOT NULL 채움용, 기존 합본과 같음) |
| `status` | `finalized`(골드셋 v1까지 만들어 바로 확정) |
| `gen_config_json` | 아래 |

```json
{
  "dataset_kind": "merged",
  "origin": "upload",
  "upload": {"filename": "시험데이터셋_….xlsx", "sha256": "…", "size": 123456, "uploaded_at": "…"},
  "merged_from": [
    {"law_label": "산업안전보건법", "collection_name": "AIE_산업안전보건법", "item_count": 60},
    {"law_label": "중대재해처벌법", "collection_name": "AIE_중대재해처벌법", "item_count": 60}
  ]
}
```
- `merged_from`에 `dataset_id`·`goldset_id`가 없다는 것이 화면에서 "업로드" 표시 기준이다.

### 5.2 `tb_eval_qa_items` (문항)
| 열 | 값 |
|---|---|
| `question`·`gold_answer` | 파일 값 |
| `gold_chunk_ids` | 파일 청크ID(근거순번 순) |
| `gold_document_ids` | 청크 조회 결과의 `document_id`(중복 제거) |
| `gold_chunk_texts` | 파일 `근거 내용`, 비면 청크 본문 |
| `question_type` 등 | `검수 정보` 시트 또는 기본값 |
| `review_status` | `approved`, `reviewed_by` = 업로드한 관리자 |
| `source_meta_json` | `{"query_id", "law_label", "qdrant_name", "merge_order", "original_filename", "article", "page_number", "uploaded": true}` |

- 기존 합본 생성(`create_merged_dataset`)을 그대로 써서 데이터셋 → 문항 → 골드셋 v1을 만든다. 골드셋 생성이 실패하면 데이터셋을 지운다.

## 6. 수정 내용

### 6.1 백엔드
| 파일 | 내용 |
|---|---|
| `app/evaluation/dataset/upload.py` (새 파일) | `parse_testset_workbook(content)` → 질의·근거·검수 정보 / `resolve_collections(laws, mapping)` / `validate_chunks(items, store)` / `build_upload_items(...)` → `create_merged_dataset` 입력. 오류는 `[{sheet, row, column, reason}]` |
| `app/routes/evaluation.py` | `POST /api/eval/datasets/upload/preview` (multipart: file) → 요약·법령별 자동 연결·청크 검사·오류 목록. `POST /api/eval/datasets/upload` (multipart: file, name, collection_map JSON) → 다시 검사 후 등록, `{dataset_id, goldset_id, item_count}` |
| `app/core/config.py` | `eval_dataset_upload_enabled: bool = True`. 크기 제한은 기존 `eval_batch_upload_max_mb`(기본 10MB) 재사용 |
| `app/evaluation/dataset/merge.py` | `is_uploaded_dataset()` 추가(표시용). 보호 로직은 `is_merged_dataset`로 이미 적용됨 |
| `app/routes/evaluation.py` 질의ID 접두어 변경 | 업로드 데이터셋도 합본이라 409(기존 동작) |

### 6.2 화면
| 파일 | 내용 |
|---|---|
| `src/api/evalApi.js` | `previewDatasetUpload(file)`, `uploadDataset(file, name, collectionMap)` |
| `src/composables/useEvalRuns.js` | 업로드 모달 상태, 미리보기·등록, 등록 후 골드셋 다시 불러와 선택 |
| `src/views/EvalRunView.vue` | 골드셋 선택 옆 [xlsx로 데이터셋 등록] 버튼, 미리보기 모달(법령별 컬렉션 선택, 오류 표) |
| `src/composables/useEvalDatasets.js`·`EvalDatasetView.vue` | 목록 `업로드` 배지, 상세의 원본 구성 문구("업로드: 파일 이름 · 날짜") |

## 7. 테스트
1. 우리 화면에서 내려받은 합본 xlsx → 업로드 → 문항 수·질의ID·법령·청크ID가 원본 합본과 같다.
2. 단일 컬렉션 xlsx(법령 열 없음) → 컬렉션 1개 선택 → 등록.
3. 오류: 시트 없음, 질의ID 중복, 근거 질의ID 없음, 청크ID 없음·무효, 법령 연결 없음 → 등록 안 됨, 행 번호 표시.
4. 등록된 데이터셋: 문항 수정·확정·재생성·접두어 변경 409, 평가 실행 시 문항별 컬렉션 검색, 법령별 지표 나옴.
5. 설정을 끄면 업로드 API 404.
6. 미리보기 API는 DB에 아무것도 만들지 않는다.

## 8. 되돌리는 방법
- 설정 `EVAL_DATASET_UPLOAD_ENABLED=false` → 버튼·API 숨김(등록된 데이터셋은 그대로 사용 가능).
- 코드 되돌림 시 등록된 업로드 데이터셋은 일반 합본으로 보인다(`origin` 무시). 마이그레이션이 없어 DB 되돌림 불필요.

## 9. 결정 필요 (구현 전 확인)

| # | 질문 | 제안 |
|---|---|---|
| Q1 | 업로드 버튼 위치 | **평가 실행 화면**(골드셋 선택 옆). 데이터셋 목록에도 같은 버튼을 둘지? → 제안: 실행 화면만 |
| Q2 | 청크ID가 없거나 무효인 근거 | **v1은 등록 거부**(행 표시). 근거 문서명·내용으로 자동 매칭(일괄 질의 `match_all` 재사용)해 등록하는 것은 2단계 |
| Q3 | 법령 열이 없는 단일 컬렉션 파일도 받기 | **받는다**(컬렉션 1개 선택) |
| Q4 | 정답 근거가 없는 문항(거절 평가용) | v1은 오류. 필요하면 `기대 동작`이 거절인 문항만 허용 |
| Q5 | 업로드 데이터셋 이름 기본값 | `<파일 이름> (업로드)` |
