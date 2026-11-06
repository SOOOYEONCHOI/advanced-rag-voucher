# Qdrant payload 구조와 사진 ID 조회 경로 분석 v1.0

> 작성 2026-11-06 · 기준: 현재 코드 + 개발 Qdrant(`localhost:6333`, 컬렉션 `AIE_C2`) · 개발 DB `rag_chatbot_dev` 실측
> 관련 ID: F-3-04, R3-1·R3-2, R4-3·R4-4, Phase 2 P2-2·P2-7·P2-8, Phase 4-A
> 함께 볼 문서: `엑셀_적재_검색_사진_흐름_분석_v1.0.md`(전체 흐름), `사진ID_청크연결_분석_v1.0.md`(연결 규칙)
> 문서 내용(본문·키워드·파일명)은 적지 않고 필드 이름·형식·건수만 적는다.

---

## 1. 요약

- payload는 **평평한(flat) JSON 63개 필드**로 저장된다. 모든 엑셀 점이 같은 키 집합을 가지며, 그중 약 20개는 docling 스프레드시트용이라 항상 `null`이다.
- 사진 ID는 payload의 **`resource_ids`(문자열 배열)** 하나에만 들어 있다. 형식은 `{document_id}-v{version_no}-i{순번 4자리}`.
- 답변 사진은 `resource_ids` → `tb_spreadsheet_resources`를 조회해 만든다. `tb_chunk_resources`는 답변 경로에서 읽지 않는다.
- 실측 결과 **payload `resource_ids`와 `tb_chunk_resources`는 청크별 목록·순서까지 완전히 일치**한다(4절).

---

## 2. payload는 어떻게 만들어지는가

```
청크 LCDocument.metadata  (excel_chunks.py excel_chunks_to_documents + records.py assign_chunk_identity)
        │
        ▼
build_unified_payload()   parsers/metadata_extractor.py:118
  ├─ DocumentMeta / ChunkMeta / SemanticMeta → to_qdrant_payload()   parsers/metadata_schema.py:84   (공통 26개)
  ├─ result["text"] = 청크 텍스트
  └─ document_type == "spreadsheet" → _SPREADSHEET_PAYLOAD_FIELDS 33개를 metadata에서 그대로 복사   (:26)
        │
        ▼
IngestService._build_points()   services/ingest_service.py:415
  ├─ version_no, point_type="text", source_key, kiwi_text, bm25_encoder_version 추가
  └─ 시맨틱 보강 결과가 있으면 summary·keywords·topics·intent(·section_title) 덮어씀
        │
        ▼
PointStruct(id = point_id(uuid5), vector = {dense, kiwi_bm25[, sparse]}, payload)
        → VectorRepository.upsert_points (100개씩)
```

### 2.1 컬렉션 설정 (실측 `AIE_C2`)

| 항목 | 값 |
|---|---|
| 점 수 | 486 (엑셀 문서 2개 × 243, 모두 `processing_engine=excel_ingest`) |
| dense | 2560차원, Cosine |
| sparse | `kiwi_bm25` (IDF) — `sparse`(BM42 등)는 없음 |
| payload 인덱스 | `block_type, chunk_type, content_type, document_id, document_type, intent, keywords, point_type, resource_ids, security_level, sheet_index, sheet_name, source_collection, source_key, text, version_no` |

---

## 3. payload 필드 전체 (엑셀 점 기준, 실측)

### 3.1 값이 들어 있는 필드

| 그룹 | 필드 | 타입 | 값 출처 | 실측 예(형식) |
|---|---|---|---|---|
| 문서 | `document_id` | str | 파이프라인 `IngestContext.document_id` | UUID |
| | `source_collection` | str | 컬렉션 qdrant_name | `AIE_C2` |
| | `security_level` | str | 업로드 사용자 최대 등급 | `public` |
| | `document_type` | str | `parse_result.doc_type` | `spreadsheet` |
| | `requested_document_type` | str | 업로드 요청값 | `auto` |
| | `document_type_source` | str | `parse_result.doc_type_source` | `excel_ingest` |
| | `file_format` | str | 확장자 | `xlsx` |
| | `original_filename` | str | 업로드 파일명 | (생략) |
| | `source_path` | str | 원본 저장 상대 경로 | `instance/data/YYYY/MM/…` |
| | `title` | str | 첫 청크 첫 줄 `extract_doc_title` | `[모델 > 시트 > 개요]` 형태 |
| 청크 | `chunk_id` | str | **point_id(UUID)** | `003b5894-…` |
| | `chunk_index` | int | 문서 안 순번 | 109 |
| | `content_type` / `block_type` / `chunk_type` | str | excel_ingest 청크 종류(세 필드 같은 값) | `step`, `table_section` … |
| | `header_path` | list | 엑셀은 비움 | `[]` |
| | `text` | str | 청크 텍스트(머리말 포함) | — |
| | `display_markdown` | str | `text`와 같음 | — |
| | `kiwi_text` | str | Kiwi 형태소 정규화 텍스트 | — |
| | `bm25_encoder_version` | str | 설정 | `kiwi-bm25-v1` |
| 엑셀 | `processing_engine` | str | 고정 | `excel_ingest` |
| | `chunk_key` | str | excel_ingest 청크 ID | `{doc_key}:10:table_section:2.0` |
| | `source_key` | str | `chunk_key`에서 문서 키 뺀 값 | `10:table_section:2.0` |
| | `sheet_name` / `sheet_index` | str / int | 시트 이름 / 순번 | — / 10 |
| | `section_type` | str | 시트 유형 | `sop`, `flowchart` … |
| | `step_no` | int/null | Step·공정단계 청크만 | 3 |
| | `source_range` | str/null | 표: `"시작행:끝행"`, 안내문: 셀 범위 | `58:59` |
| | `revision` | str/null | 관리대장 개정 차수 | null(매칭 없음) |
| | **`resource_ids`** | **list[str]** | **사진 연결 결과** | `["…-v1-i0065", …]` |
| 버전 | `version_no` | int | 버전 번호 | 1, 3 |
| | `point_type` | str | 고정 | `text` |
| 시맨틱 | `summary`, `keywords`, `topics`, `intent` | str/list | LLM 시맨틱 보강 | 개발 환경은 **보강이 켜져 있어 486건 모두 채워짐** |
| | `section_title` | str | 규칙 값이 없을 때 보강 값으로 채움 | 짧은 문자열(번호 등) |

### 3.2 항상 null인 필드 (docling 스프레드시트 전용)

`sheet_id, block_id, block_index, row_start, row_end, header_range, headers, header_paths, record_ids, record_count, warning_codes, spreadsheet_schema_version, embedding_text_version, display_format_version, formula_count, formula_manifest, formula_manifest_truncated, formula_cache_status, formula_dominant, formula_recalculated`
+ 공통 중 미사용: `page_number, char_start_offset, char_end_offset, created_at, updated_at, version`

excel_ingest 메타에 해당 키가 없어도 `_SPREADSHEET_PAYLOAD_FIELDS`를 전부 `chunk_meta.get()`으로 넣기 때문에 키는 생기고 값이 `null`이다(점마다 약 26개 null 필드).

### 3.3 payload에 없는 것

| 정보 | 있는 곳 |
|---|---|
| 모델명 | 텍스트 머리말 `[모델명 > …]`, `tb_documents.product_model` |
| 사진의 위치·역할·주변 텍스트 | `tb_spreadsheet_resources` |
| 사람이 읽는 청크 키(`{document_id}:{v}:{source_key}#{part}`) | `tb_chunks.chunk_id` (payload `chunk_id`는 UUID) |
| 문서 단위 집계(사진 연결 수 등) | `tb_document_versions.summary_json` |

---

## 4. 사진 ID는 어디서 오는가

### 4.1 만들어지는 곳 → payload에 들어가는 곳

| 순서 | 위치 | 필드 |
|---|---|---|
| 1 | `excel_ingest/parser.py _placement` | 배치별 `sha256`, `image_id`(sha256 앞 16자), `cell_range`, `step_no`, `role` |
| 2 | `app/ingest/excel_images.py plan_excel_images:54` | `resource_id = f"{document_id}-v{version_no}-i{seq:04d}"` 발급 (시트 순서 → 배치 순서) |
| 3 | `excel_images.py link_excel_images` | 청크 순번 → `[resource_id …]` (step → row_overlap → nearest → image_chunk 순) |
| 4 | `app/ingest/excel_chunks.py:121` | `metadata["resource_ids"]` (분할 조각도 같은 목록) |
| 5 | `metadata_extractor.py:172-175` | `payload["resource_ids"] = chunk_meta.get("resource_ids")` |
| 6 | `records.py chunk_resource_links` → `ingest_record_repository.insert_chunk_resources` | `tb_chunk_resources(chunk_id, resource_id, sort_order=목록 순번)` |

`EXCEL_IMAGE_LINK_ALL=false`면 3 대신 Step 청크의 `meta.image_ids`(sha256 앞 16자) → `resource_ids_for`로 같은 시트 배치의 `resource_id`로 바꾼다.

### 4.2 실측: 청크 종류별 사진 연결 (`AIE_C2`, 2개 문서 합계)

| content_type | 점 수 | `resource_ids` 있는 점 |
|---|---|---|
| table_section | 360 | 82 |
| step | 66 | 60 |
| guide_note | 16 | 4 |
| flow_stage | 28 | 0 |
| summary | 10 | 0 |
| flow_overview | 4 | 0 |
| form_control | 2 | 0 |

- 사진 ID 총 510개(문서당 255), 한 청크 최대 21개.
- 같은 사진 ID가 여러 청크에 들어간다(row_overlap·분할 조각). 예: 한 사진 ID가 6개 청크에 연결된 경우가 있다.
- 한 청크 안 순서는 규칙 순서 → 배치 순서라 번호가 오름차순이 아닐 수 있다(예: `i0102, i0099, i0100, i0101`).

### 4.3 실측: payload ↔ DB 일치 확인

청크별 `point_id=사진ID목록`을 정렬해 MD5로 비교했다.

| 문서 | 사진 있는 청크 | Qdrant payload MD5 | `tb_chunk_resources` MD5 |
|---|---|---|---|
| `895fd6e9…` v1 | 73 | `be415a11…f320` | `be415a11…f320` |
| `a8470a0e…` v3 | 73 | `14cc469c…9395` | `14cc469c…9395` |

→ **목록·순서 모두 일치.** 연결 건수도 같다(DB 255건 = payload 255개).

---

## 5. 사진 ID를 읽는 곳 (어떤 필드를 불러오나)

### 5.1 답변 사진 — `app/graphs/images.py`

| 단계 | 읽는 값 | 출처 |
|---|---|---|
| 후보 조회 키 | `metadata.resource_ids`, `chunk.document_id`(없으면 `metadata.document_id`) | 검색 결과 payload (`retrieve.py`가 payload 전체를 `ChunkResult.metadata`로 전달) |
| 대체 조회(`resource_ids`가 비었을 때) | `metadata.processing_engine == "excel_ingest"`, `metadata.source_range`("시작:끝"), `metadata.sheet_name`, `metadata.version_no` | payload |
| 정렬용 | `metadata.sheet_name`, `metadata.step_no` | payload |
| 사진 정보 | `resource_id, document_id, version_no, sheet_name, from_cell, to_cell, role_cd, step_no, step_title, link_confidence, surrounding_text, content_hash, in_print_area` + `tb_documents.original_filename` | `tb_spreadsheet_resources` JOIN `tb_documents` (`_RESOURCE_SQL`) |
| 걸러내는 조건 | `status <> 'deleted'`, `mime_type ∈ {png,jpeg,gif,webp,bmp}`, `review_status <> 'unlinked'`, `role_cd ∉ {decoration, form_header}`, `r.version_no = d.version_no`, `d.deleted_at IS NULL`, **`r.document_id = 청크 document_id`** | 같은 SQL |

조회 SQL(요지):

```sql
SELECT r.resource_id, r.document_id, r.version_no, r.sheet_name, r.from_cell, r.to_cell, r.role_cd,
       r.step_no, r.step_title, r.link_confidence, r.surrounding_text, r.content_hash, r.in_print_area,
       d.original_filename
FROM tb_spreadsheet_resources r
JOIN tb_documents d ON d.document_id = r.document_id AND d.deleted_at IS NULL
WHERE r.status <> 'deleted' AND r.mime_type = ANY(:표시가능형식)
  AND r.review_status <> 'unlinked' AND (r.role_cd IS NULL OR r.role_cd <> ALL(:제외역할))
  AND (r.version_no IS NULL OR r.version_no = d.version_no)
  AND r.document_id = :청크문서 AND r.resource_id = ANY(:payload.resource_ids)
```

결과는 payload `resource_ids` 순서로 다시 정렬한 뒤, 질의어 일치 → 역할 → 컨텍스트 순서 → 같은 Step·시트 → 신뢰도로 후보를 정한다. 같은 `content_hash`는 1건만 남긴다.

### 5.2 응답으로 나가는 사진 필드 — `images.public_images`

`ref, resource_id, document_id, title, role, sheet_name, from_cell, to_cell, step_no, step_title, surrounding_text, original_filename, context_no, cited`
(파일 경로·`content_hash`·점수는 나가지 않음)

### 5.3 출처(citation) — `graphs/nodes/format_citations.py`

출처 항목에 `resource_ids: metadata.resource_ids`를 그대로 넣는다. 출처 패널이 청크에 연결된 사진 ID를 알 수 있다.

### 5.4 화면 → 이미지 파일

| API | 입력 | 읽는 것 |
|---|---|---|
| `GET /api/spreadsheet-resources/{resource_id}` | 응답 `images[].resource_id` | `tb_spreadsheet_resources.resource_path` → `RESOURCE_STORAGE_ROOT/documents/{document_id}/resources/{resource_id}/original/{sha256}.{ext}`, 문서 권한 재검사 |
| `GET /api/documents/{document_id}/spreadsheet-resources` | 문서 ID | 그 문서의 사진 목록(표시 규칙 `resource_labels.is_displayable`) |

### 5.5 읽지 않는 곳

- `tb_chunk_resources`: 답변·출처·이미지 API 어디에서도 읽지 않는다. 적재 때 기록만 하고, 집계·점검용이다.
- payload `resource_ids` 인덱스(KEYWORD)는 만들어져 있지만 현재 이 필드로 필터 검색하는 코드는 없다.

---

## 6. 정리·주의점

| # | 내용 |
|---|---|
| P-1 | 답변 사진의 기준은 payload `resource_ids`다. 연결을 바꾸려면 재등록해서 payload와 DB를 같이 갱신해야 한다. |
| P-2 | payload의 `chunk_id`는 UUID(point_id)다. DB와 이을 때는 `tb_chunks.point_id`로 조인한다. |
| P-3 | 엑셀 점마다 null 필드가 약 26개 있다. 기능 문제는 없고 용량만 조금 늘어난다. 정리하려면 `build_unified_payload`에서 null을 빼야 하는데 docling 경로와 공용이라 영향 확인이 필요하다(결정 필요). |
| P-4 | 개발 환경은 시맨틱 보강이 켜져 있어 `section_title`이 LLM 값으로 채워진다. 그래서 재랭커 입력에 `[섹션]` 접두어가 붙는다. `엑셀_적재_검색_사진_흐름_분석_v1.0.md` N-2의 "섹션도 비어 있음"은 보강을 끈 경우에만 맞다. `[문서명]`(payload `filename` 없음)은 여전히 빠진다. |
| P-5 | 개발 DB에는 Qdrant `AIE_C2`에 없는 엑셀 문서(`755cd6e5…`, 연결 51건)도 있다. 다른 컬렉션 소속인지 이번 점검에서는 확인하지 않았다. |

### 확인용 명령

```bash
# 사진이 연결된 점의 payload 키·resource_ids 확인 (개발 Qdrant)
curl -s -X POST "http://localhost:6333/collections/<컬렉션>/points/scroll" -H "Content-Type: application/json" \
  -d '{"limit":5,"with_payload":["chunk_id","content_type","source_key","resource_ids"],"filter":{"must_not":[{"is_empty":{"key":"resource_ids"}}]}}'
```

```sql
-- 같은 점의 DB 연결 (point_id로 조인)
select c.point_id, c.source_key, string_agg(cr.resource_id, ',' order by cr.sort_order) ids
from tb_chunks c join tb_chunk_resources cr on cr.chunk_id = c.chunk_id
where c.point_id = '<point_id>'
group by c.point_id, c.source_key;
```
