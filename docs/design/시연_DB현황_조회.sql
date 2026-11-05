-- 시연용 DB 현황 조회 (읽기 전용) — 2026-11-02, 스키마 revision 0005_document_version_replace 기준
-- 흐름: ① 대화 주제 추가 → ② 문서 등록·임베딩 → ③ 최신본 변경 → ④ 챗봇 질의·답변
-- 사용: DBeaver/pgAdmin 에서 블록별 실행(자동 새로고침 2~3초) 또는 psql 에서 쿼리 끝 ; 대신 \watch 2
-- 주의: 화면 공유 시 경로 컬럼(source_path, stored_filename, md_dir, resource_path)과 chunk_text 원문은 띄우지 않는다

-- ───────────────────────────────────────────────
-- [1] 수집 — 대화 주제(컬렉션)와 문서 수
-- ───────────────────────────────────────────────
select c.collection_id, c.topic_name, c.department_name, c.qdrant_name, c.is_active, c.created_at,
       count(d.document_id) filter (where d.deleted_at is null) as doc_count
from tb_collections c
left join tb_documents d on d.collection_id = c.collection_id
group by c.collection_id
order by c.created_at desc
limit 5;

-- ───────────────────────────────────────────────
-- [2] 수집·처리 진행 — 적재 작업 상태 (등록 중 새로고침하면 status·current_step 이 바뀐다)
-- ───────────────────────────────────────────────
select j.job_id, j.status, j.current_step, j.error_code, j.created_at, j.updated_at,
       j.updated_at - j.created_at                  as elapsed,
       j.result_json->>'processing_engine'          as engine,
       j.result_json->>'doc_type'                   as doc_type,
       j.result_json->>'version_no'                 as version_no,
       j.result_json->>'chunk_count'                as chunk_count
from tb_ingest_jobs j
order by j.created_at desc
limit 5;

-- ───────────────────────────────────────────────
-- [3] 정제·포맷·버전 — 문서(현재 대표)와 버전 이력
--     최신본 변경 후: 새 버전 active, 이전 버전 retired + retired_at·vectors_purged_at 기록
-- ───────────────────────────────────────────────
select d.original_filename, d.doc_type, d.doc_type_source, d.product_model, d.doc_key,
       d.version_no                       as active_version,
       v.version_no, v.status             as version_status,
       v.processing_engine, v.file_format, v.file_size, left(v.file_sha256, 12) as sha256_12,
       v.total_pages, v.chunk_count,
       v.summary_json->>'sheet_count'        as sheets,
       v.summary_json->>'unique_image_count' as images,
       v.summary_json->>'warning_count'      as warnings,
       v.summary_json->>'needs_review_count' as needs_review,
       v.activated_at, v.retired_at, v.vectors_purged_at
from tb_documents d
join tb_document_versions v on v.document_id = d.document_id
where d.deleted_at is null
order by d.doc_key, v.version_no desc;

-- ───────────────────────────────────────────────
-- [4] 가공 — 청크(검색 단위) 구성: 종류별 개수·벡터 저장·사진 연결
-- ───────────────────────────────────────────────
select d.original_filename, ch.version_no, ch.section_type, ch.content_type,
       count(*)                                         as chunks,
       count(*) filter (where ch.point_id is not null)  as with_vector,
       count(distinct cr.resource_id)                   as linked_images
from tb_chunks ch
join tb_documents d on d.document_id = ch.document_id
left join tb_chunk_resources cr on cr.chunk_id = ch.chunk_id
where d.deleted_at is null
group by 1, 2, 3, 4
order by 1, 2 desc, 3, 4;

-- ───────────────────────────────────────────────
-- [5] 메타데이터 — 청크 1건 구조 (본문은 길이만)
-- ───────────────────────────────────────────────
select ch.chunk_id, ch.version_no, ch.section_type, ch.content_type, ch.sheet_name, ch.source_range,
       ch.step_no, ch.part_no, ch.meta_json, ch.point_id, length(ch.chunk_text) as text_len,
       (select count(*) from tb_chunk_resources cr where cr.chunk_id = ch.chunk_id) as images
from tb_chunks ch
where ch.content_type = 'step'
order by ch.created_at desc
limit 3;

-- ───────────────────────────────────────────────
-- [6] 정제 — 엑셀 사진 분류·연결 결과 (장식 이미지는 decoration 으로 걸러짐)
-- ───────────────────────────────────────────────
select d.original_filename, r.version_no, r.role_cd, r.link_method, r.in_print_area,
       count(*) as cnt, round(avg(r.link_confidence)::numeric, 2) as avg_confidence
from tb_spreadsheet_resources r
join tb_documents d on d.document_id = r.document_id
where d.deleted_at is null
group by 1, 2, 3, 4, 5
order by 1, 2 desc, cnt desc;

-- ───────────────────────────────────────────────
-- [7] 질의·답변 — 최근 질문
-- ───────────────────────────────────────────────
select l.log_id, l.created_at, l.collection_name_snapshot, left(l.query_text, 40) as question,
       l.outcome_code, l.chunks_retrieved, round(l.response_time_ms) as ms, l.model_id,
       (select count(*) from tb_query_citations qc where qc.log_id = l.log_id) as citations
from tb_query_logs l
order by l.created_at desc
limit 5;

-- ───────────────────────────────────────────────
-- [8] 질의·답변 — 최근 질문 1건이 근거로 쓴 청크 (최신본 version_no 로 답했는지 확인)
--     context_meta 의 chunk_id 는 Qdrant point id 라 tb_chunks.point_id 로 잇는다
-- ───────────────────────────────────────────────
select (e->>'citation_no')::int as no, round((e->>'score')::numeric, 3) as score,
       d.original_filename, ch.version_no, v.status as version_status,
       ch.section_type, ch.content_type, ch.step_no,
       (select count(*) from tb_chunk_resources cr where cr.chunk_id = ch.chunk_id) as images
from (select * from tb_query_logs order by created_at desc limit 1) l
cross join jsonb_array_elements(l.context_meta) e
left join tb_chunks ch            on ch.point_id = (e->>'chunk_id')::uuid
left join tb_documents d          on d.document_id = e->>'document_id'
left join tb_document_versions v  on v.document_id = ch.document_id and v.version_no = ch.version_no
order by no;
