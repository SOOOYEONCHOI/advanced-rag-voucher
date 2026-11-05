# 사진 ID 발급과 청크 연결 구조 분석 v1.0

> 작성 2026-11-03 · 기준: 스키마 revision `0005_document_version_replace`, 설정 `EXCEL_IMAGE_LINK_ALL=True`(기본값)
> 범위: 엑셀(`excel_ingest`) 등록 시 사진(`resource_id`)이 만들어지고, 청크·Qdrant·답변 사진과 이어지는 방식
> 관련 ID: F-3-04, R3-1·R3-2(사진 추출·연결), Phase 2 P2-4·P2-5·P2-7·P2-8, Phase 4-A(답변 사진)
> 근거: 코드 분석 + 개발 DB(`rag_chatbot_dev`)·개발 Qdrant 실제 데이터 대조 (값은 ID 형식·건수만 적고 문서 내용은 적지 않음)

---

## 1. 요약

- 사진 ID(`resource_id`)는 **backend가 발급**한다. 형식은 `{document_id}-v{version_no}-i{순번 4자리}`다.
- 사진 ↔ 청크 연결은 **두 곳에 같은 값으로** 저장된다.
  - Qdrant payload `resource_ids`
  - PostgreSQL `tb_chunk_resources`
- **답변 사진은 Qdrant payload의 `resource_ids`를 읽는다.** `tb_chunk_resources`는 DB 쪽 기록·집계용이다.
- 버전 번호가 사진 ID와 청크 ID에 모두 들어간다. 그래서 최신본으로 바꾸면 사진과 청크가 전부 새 ID를 받고, 이전 버전과 섞이지 않는다.

---

## 2. ID 3종류

| ID | 형식 | 예 (문서 ID 부분 생략) | 만드는 코드 |
|---|---|---|---|
| 사진 `resource_id` | `{document_id}-v{version_no}-i{순번:04d}` | `…-v3-i0036` | `adrag_backend/app/ingest/excel_images.py:54` |
| 청크 `chunk_id` (`tb_chunks` 기본키) | `{document_id}:{version_no}:{source_key}#{part_no}` | `…:1:08:step:3#0` | `adrag_backend/app/ingest/records.py:32` |
| 벡터 `point_id` (Qdrant 점 ID) | `uuid5(고정 네임스페이스 "adrag/tb_chunks", chunk_id)` | `2cdf9a8b-…` | `adrag_backend/app/ingest/records.py:15-19` |

### 2.1 사진 `resource_id`

- **순번:** 시트 순서 → 시트 안 배치 순서로 1부터 매긴다. 결정적이라 같은 파일을 다시 처리(재시도)해도 같은 ID가 나온다.
- **배치 1개 = 1행:** 같은 사진이 여러 곳에 붙어 있으면 ID는 배치 수만큼 생기고, 내용 해시(`content_hash = sha256:…`)는 같다.
  - 개발 DB v1 기준 621행에 고유 해시는 158개다.
- **저장 테이블:** `tb_spreadsheet_resources`
  - 처음부터 `status = committed`로 넣는다. 임시 테이블 `tb_spreadsheet_staging_resources`는 거치지 않는다.
  - `parse_job_id`는 `excel-{job_id}`다.
- **원본 파일:** `documents/{document_id}/resources/{resource_id}/original/{sha256}.{확장자}`
  - emf·wmf는 변환하지 않고 원본 그대로 둔다.
  - 같은 폴더에 `renditions/`, `analyses/`를 미리 만든다.
- **같이 저장하는 위치·역할 정보:**
  - 위치: `sheet_name`, `from_cell`, `to_cell`, `surrounding_range`, `surrounding_text`
  - Step: `step_no`, `step_title`
  - 역할: `role_cd` (step_photo, part_photo, detail_view, figure, decoration, form_header 등)
  - 기타: `in_print_area`, `overlay_json`(callouts·markers·overlay_texts), `link_method`, `link_confidence`, `review_status`

### 2.2 청크 `chunk_id`와 `point_id`

- `source_key`는 버전과 무관한 위치 키다. excel_ingest 청크 ID `{doc_key}:{시트}:{종류}:{블록}`에서 문서 키를 뗀 값이다(예: `08:step:3`, `10:table_section:2.0`).
  - 같은 키가 두 번 나오면(예: Step 0이 두 번) `~2`, `~3`을 붙인다(`excel_chunks.py:93-97`).
- `part_no`: 청크가 `MAX_CHUNK_SIZE`보다 길면 행 단위로 나눈다. 조각 번호는 0부터다(`excel_chunks.py:102`).
- `point_id`는 `chunk_id`에서 계산한다. 재시도해도 같은 점 ID가 나와서 Qdrant에 중복 점이 생기지 않는다.

---

## 3. 연결 흐름 (엑셀 등록)

코드: `adrag_backend/app/services/ingest_pipeline.py`

```
① run_excel_ingest()            엑셀 파싱 (excel_ingest — 추출 규칙은 수정 금지 대상)
② plan_excel_images()           사진 배치마다 resource_id 발급, 행 데이터 준비          pipeline:162
③ link_excel_images()           사진 → 붙일 청크(청크 순번) 결정                         pipeline:168
④ excel_chunks_to_documents()   청크 메타에 resource_ids 목록 기록, 긴 청크 분할          pipeline:174
⑤ assign_chunk_identity()       source_key·part_no·chunk_id·point_id 부여                pipeline:243
⑥ _build_points()               Qdrant payload 에 resource_ids 포함 → upsert            pipeline:244
⑦ 한 트랜잭션으로 DB 기록                                                               pipeline:303-327
     _commit_resources → write_excel_images(원본 파일) + insert_resources(tb_spreadsheet_resources)
     insert_chunks(tb_chunks)
     insert_chunk_resources(tb_chunk_resources)
```

### 3.1 ③ 연결 규칙 (`excel_images.py:120-251`)

- **켜는 설정:** `EXCEL_IMAGE_LINK_ALL` (`app/core/config.py:232`, 기본 `True`)
  - 꺼져 있으면 Step 청크의 `image_ids`(sha256 앞 16자리)로만 연결한다(`resource_ids_for`, `excel_images.py:110`).
- **제외:** `role_cd`가 `decoration`, `form_header`인 사진
- **청크 위치(행 범위)를 정하는 방법:**

  | 청크 종류 | 위치 기준 |
  |---|---|
  | Step·공정단계 | IR `steps[].rows` |
  | 표(`table_section`) | `meta.rows` |
  | 안내문(`guide_note`) | `shape_range` |
  | 개요(`summary`) | IR `header_kv` 행 |
  | 체크박스·흐름도 | 위치 없음 (연결 대상 아님) |

- **규칙 우선순위:** 위에서부터 적용하고, 먼저 맞는 규칙으로 연결한다.

  | 순서 | 규칙 | 내용 |
  |---|---|---|
  | 1 | `step` | 파서가 Step을 정한 사진 → 같은 Step 번호 청크. 사진 시작 행이 드는 청크가 우선 |
  | 2 | `row_overlap` | 사진 행 범위와 겹치는 청크 전부 |
  | 3 | `nearest` | 같은 시트에서 행 거리가 가장 가까운 청크. 거리가 같으면 위쪽 청크 |
  | 4 | `image_chunk` | 위치 있는 글자 청크가 없는 시트 → excel_ingest 이미지 청크(사진 설명)를 적재하고 연결 |

- **한 청크 안의 사진 순서:** 규칙 순서 → 배치 순서. 이 순서가 `sort_order`와 payload 목록 순서가 된다.
- **결과 집계:** `tb_document_versions.summary_json.image_links`에 저장한다. 항목은 `placements`, `excluded`, `linked`, `unlinked`, `by_method`, `unlinked_resource_ids`(최대 20개)다.

### 3.2 ④ 청크 메타

- `resource_ids`(③의 결과)를 청크 메타에 넣는다(`excel_chunks.py:121`).
- 긴 청크를 나누면 **조각마다 같은 사진 목록**을 가진다.
- `content_type = image` 청크는 적재하지 않는다. ③의 4번 규칙에 해당하는 청크만 예외로 적재한다.

### 3.3 ⑥·⑦ 두 곳에 저장

| 저장 위치 | 필드 | 코드 |
|---|---|---|
| Qdrant payload | `resource_ids: [resource_id, …]` (엑셀 전용 필드 목록에 포함) | `app/parsers/metadata_extractor.py:26, 172-175` |
| `tb_chunk_resources` | `(chunk_id, resource_id, sort_order)` | `app/ingest/records.py:65-70`, `app/repositories/ingest_record_repository.py:258-265` |

`tb_chunk_resources`는 사진 행(`tb_spreadsheet_resources`)이 실제로 있을 때만 INSERT한다(`WHERE EXISTS`).

---

## 4. 테이블 관계

```
tb_documents ─┬─ tb_document_versions (document_id, version_no, status, summary_json.image_links)
              │
              ├─ tb_chunks ──────────── chunk_id (PK), version_no, source_key, part_no, point_id
              │      │                                                        ║
              │      │                                        Qdrant 점 ID ═══╝
              │      │                                        └ payload.resource_ids [...]
              │      └─ tb_chunk_resources (chunk_id, resource_id, sort_order)
              │                    │
              └─ tb_spreadsheet_resources ── resource_id (PK), version_no, role_cd, content_hash, from_cell …
```

---

## 5. 답변에 사진이 붙는 과정

코드: `adrag_backend/app/graphs/images.py`

1. **후보 모으기** (`collect_image_candidates`)
   - 검색된 청크 payload의 `resource_ids`로 `tb_spreadsheet_resources`를 조회한다(`images.py:75-81`).
   - 연결 사진이 없는 엑셀 청크는 같은 시트·같은 행 범위(`source_range` "5:12") 안의 인쇄 영역 사진을 쓴다(`images.py:83-93`).
   - 걸러내는 조건(`_RESOURCE_SQL`):
     - 다른 문서의 사진
     - 삭제된 문서·사진
     - 현재 버전이 아닌 사진(`r.version_no = d.version_no`)
     - 브라우저가 못 여는 형식(emf 등)
     - 제외 역할(장식 등)
     - 검수에서 `unlinked` 처리된 사진
   - 정렬 순서: 질의어 일치 수 → 역할 우선순위(Step 사진 > 확대도 > 도면 > 부품 > …) → 컨텍스트 순서 → 같은 시트·Step → 신뢰도
   - 내용 해시가 같은 사진은 1건만 남긴다.
2. **프롬프트:** `[IMG:짧은코드] 설명` 목록만 넘긴다. URL과 경로는 넘기지 않는다.
3. **검증:** 답변의 `[IMG:…]` 중 후보에 있는 것만 남긴다(최대 `rag_max_images`).
   - 인용이 없으면 1순위 컨텍스트 Step의 사진 1장을 자동으로 붙인다.
   - 그것도 없으면 질의어가 분명히 겹치는 사진 1장을 붙인다.

권한·활성 버전 필터는 검색 단계에서 이미 통과한 청크에만 적용되므로, 사진도 같은 문서·현재 버전으로 한정된다(CLAUDE.md 절대 규칙 8).

---

## 6. 최신본 변경 시

| 항목 | 새 버전 | 이전 버전 |
|---|---|---|
| 사진 ID | `…-v{새 번호}-i…`로 새로 발급 | 행은 남는다. 답변에서는 `version_no` 조건으로 빠진다 |
| 청크 ID·점 ID | `…:{새 번호}:…`와 새 UUID | `tb_chunks` 행은 남고, Qdrant 점은 전환 후 삭제된다(`vectors_purged_at`) |
| 연결 | 새 청크와 새 사진끼리만 연결 | 이전 연결은 이전 청크에 남는다 |

전환 중에 실패하면 새 버전의 사진 ID(`new_resource_ids`)만 지운다. 기존 최신본은 그대로 남는다(`ingest_pipeline.py:376-391, 484-489`).

---

## 7. 실제 데이터 확인 (2026-11-03, 개발 환경)

| 확인 | 결과 |
|---|---|
| 사진 ID 형식 | 864행 모두 `{document_id}-v{n}-i{4자리}`. ID 앞부분 = `document_id`, `parse_job_id`는 `excel-…` |
| 연결 집계 (C2 문서 v3) | 배치 190 = 연결 168 + 제외 22 + 미연결 0. 규칙별 step 47, row_overlap 77, nearest 44, image_chunk 0 |
| DB와 Qdrant 일치 | 표 청크 1건에서 `tb_chunk_resources` = `v1-i0065, i0069, i0070, i0074`, Qdrant payload `resource_ids`도 같은 값·같은 순서 |
| Step 청크 예 | `…:1:08:step:3#0` → `…-v1-i0036` (step_photo, C15) |
| 임시 테이블 | `tb_spreadsheet_staging_resources` 0건 |

확인용 조회문:

```sql
-- 청크별 연결 사진 (최신 버전)
select substr(c.chunk_id, 38) as chunk_key, c.point_id, c.content_type, c.step_no,
       cr.sort_order, substr(cr.resource_id, 38) as resource_suffix, r.role_cd, r.from_cell
from tb_chunk_resources cr
join tb_chunks c on c.chunk_id = cr.chunk_id
join tb_spreadsheet_resources r on r.resource_id = cr.resource_id
join tb_document_versions v on v.document_id = c.document_id and v.version_no = c.version_no and v.status = 'active'
order by c.chunk_id, cr.sort_order
limit 20;

-- 버전별 연결 집계
select d.doc_key, v.version_no, v.status, v.summary_json->'image_links' as image_links
from tb_document_versions v join tb_documents d on d.document_id = v.document_id
where v.processing_engine = 'excel_ingest' and d.deleted_at is null
order by d.doc_key, v.version_no;
```

Qdrant 쪽 확인(같은 점의 `resource_ids`):

```bash
curl -s "http://<Qdrant 주소>:6333/collections/<qdrant_name>/points/<point_id>" \
  | python -c "import sys,json; print(json.load(sys.stdin)['result']['payload'].get('resource_ids'))"
```

---

## 8. 헷갈리기 쉬운 점

1. **`chunk_id`가 두 가지 뜻으로 쓰인다.**
   - `tb_chunks.chunk_id` = 사람이 읽는 키(`…:1:08:step:3#0`)
   - Qdrant payload `chunk_id`, `tb_query_logs.context_meta[].chunk_id` = **point_id(UUID)**. 평가 코드와 호환하려고 유지한다(`records.py:5`).
   - 둘을 이을 때는 `tb_chunks.point_id`로 조인한다.
2. **`tb_spreadsheet_resources.link_method`는 3.1의 연결 규칙이 아니다.**
   - 이 컬럼에는 파서가 판단한 사진 위치 관계(`row_in_step_range`, `row_item`, `nearest_text`, `same_image_as_step_photo`, `none`)가 들어 있다.
   - 백엔드 연결 규칙(step·row_overlap·nearest·image_chunk)은 연결 1건마다 저장하지 않고, 버전별 집계(`summary_json.image_links`)로만 남는다.
3. **답변 사진의 기준은 Qdrant payload다.** `tb_chunk_resources`만 고치면 답변 사진은 바뀌지 않는다. 연결을 바꾸려면 재등록해서 두 곳을 같이 갱신한다.
4. **PDF(docling)는 사진을 연결하지 않는다.** 개발 DB의 PDF 문서는 청크 164개, 연결 사진 0건이다.
5. **docling-parser에도 자체 사진 ID 경로가 있다.**
   - 형식은 `{문서ID}-r{순번}`이다(`docling-parser/app/spreadsheets/media.py:406`).
   - 임시 테이블에 넣었다가 등록 성공 후 `commit_parse_job`으로 확정한다.
   - 지금 엑셀은 backend `excel_ingest`로 처리하므로 이 경로는 쓰이지 않는다(임시 테이블 0건).
6. **10-22 이전에 등록한 문서는 3.1 규칙 적용 전이다.** `image_links` 집계가 없고 연결이 적다. 시연과 검증에는 다시 등록한 문서를 쓴다.

---

## 9. 남은 이슈 (결정 필요)

| 번호 | 내용 | 제안 |
|---|---|---|
| I-1 | 연결 규칙(step·row_overlap·nearest·image_chunk)이 연결 1건마다 남지 않아 "이 사진이 왜 이 청크에 붙었는지"를 DB에서 바로 볼 수 없다 | `tb_chunk_resources`에 `link_rule` 열 추가 (Alembic revision 필요). 검수 화면(UI-15, 2차) 때 함께 검토 |
| I-2 | payload `chunk_id`와 `tb_chunks.chunk_id`의 뜻이 달라 조회·시연 때 혼동된다 | 이름은 유지하고 문서·조회문에서 `point_id` 조인으로 안내 (평가 코드 호환) |
| I-3 | `tb_query_logs.context_meta`의 `document_name`, `section_name`이 비어 있다 | 질의 기록 저장 코드 확인 후 보완 여부 결정 |
