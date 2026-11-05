"""SQLite 메타 DB 이관 전 데이터 품질 점검 (읽기 전용, 2026.09.29 Phase 1.5).

스키마 진단서 4장 항목: FK 위반, 시드 관리자 비밀번호 변경 여부, 고아 행, JSON 유효성·형태,
유일성 위반, 문서 버전, 시각 형식 분포, resource 해시 재사용, 불리언·범위, 권한 데이터, 시퀀스 값.
비밀값(비밀번호 해시·암호문)은 출력하지 않는다.

사용법 (adrag_backend 폴더에서)
    python scripts/check_sqlite_quality.py [SQLite 경로] [schema.sql 경로(시드 해시 비교용, 선택)]
"""

import re
import sqlite3
import sys
from collections import Counter

DB = sys.argv[1] if len(sys.argv) > 1 else "./instance/db/db_rag_metadata.db"
SCHEMA = sys.argv[2] if len(sys.argv) > 2 else None
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
q = lambda sql, *a: [tuple(r) for r in c.execute(sql, a).fetchall()]

tables = [r[0] for r in q("select name from sqlite_master where type='table' and name like 'tb_%' order by name")]
print("## tables", len(tables))

print("\n## 1. foreign_key_check")
fk = q("PRAGMA foreign_key_check")
print(Counter((r[0], r[2]) for r in fk) or "none")

row = q("select user_pwd from tb_users where user_id='admin'")
if SCHEMA:
    seed_hash = re.search(r"'admin',\s*'(\$2b\$[^']+)'", open(SCHEMA, encoding="utf-8").read()).group(1)
    print("admin exists:", bool(row), "| admin pwd == seed hash:", bool(row) and row[0][0] == seed_hash)
else:
    print("admin exists:", bool(row), "| (schema.sql 미지정: 시드 해시 비교 생략)")

print("\n## 2. orphans")
print("resources.document_id not in documents, by status:",
      q("""select r.status, count(*) n, count(distinct r.document_id) docs from tb_spreadsheet_resources r
           left join tb_documents d on d.document_id=r.document_id where d.document_id is null group by r.status"""))
print("resources by doc state:",
      q("""select case when d.document_id is null then 'no_doc' when d.deleted_at is not null then 'doc_deleted' else 'doc_live' end s,
           r.status, count(*) from tb_spreadsheet_resources r left join tb_documents d on d.document_id=r.document_id group by 1,2"""))
print("jobs.created_by not in users:",
      q("select count(*) from tb_ingest_jobs j left join tb_users u on u.user_id=j.created_by where j.created_by is not null and u.user_id is null")[0][0])
print("document_events.document_id not in documents:",
      q("select count(*) from tb_document_events e left join tb_documents d on d.document_id=e.document_id where d.document_id is null")[0][0])
print("citations.document_id not in documents:",
      q("select count(*) from tb_query_citations x left join tb_documents d on d.document_id=x.document_id where d.document_id is null")[0][0])
print("eval_item_results.qa_id not in qa_items:",
      q("select count(*) from tb_eval_item_results r left join tb_eval_qa_items a on a.qa_id=r.qa_id where a.qa_id is null")[0][0])
print("app_settings.updated_by not in users:",
      q("select count(*) from tb_app_settings s left join tb_users u on u.user_id=s.updated_by where s.updated_by is not null and u.user_id is null")[0][0])

print("\n## 3. JSON columns (invalid / type distribution)")
json_cols = {}
for t in tables:
    for col in q(f"PRAGMA table_info({t})"):
        name = col[1]
        if name.endswith("_json") or name in {"allowed_topics", "blocked_topics", "allowed_doc_types", "metadata_filters",
                                               "conversation_history", "context_text", "context_meta", "extracted_keywords",
                                               "linked_record_ids", "gold_chunk_ids", "gold_document_ids", "gold_chunk_texts",
                                               "tags", "setting_value"}:
            json_cols.setdefault(t, []).append(name)
for t, cols in json_cols.items():
    for col in cols:
        rows = q(f"select json_valid({col}) v, case when json_valid({col}) then json_type({col}) end jt, count(*) n from {t} where {col} is not null group by 1,2")
        nulls = q(f"select count(*) from {t} where {col} is null")[0][0]
        print(f"{t}.{col}: " + ", ".join(f"{'valid' if r[0] else 'INVALID'}:{r[1]}={r[2]}" for r in rows) + (f", null={nulls}" if nulls else ""))
print("app_settings value_type:", q("select value_type, count(*) from tb_app_settings group by 1"))

print("\n## 4. uniqueness / version races")
print("eval_item_results dup (run_id,qa_id):", q("select count(*) from (select run_id,qa_id from tb_eval_item_results group by 1,2 having count(*)>1)")[0][0])
print("analyses dup (resource_id,version):", q("select count(*) from (select resource_id,analysis_version from tb_spreadsheet_resource_analyses group by 1,2 having count(*)>1)")[0][0])

print("\n## 5. documents")
print("version_no:", q("select version_no, count(*) from tb_documents group by 1"))
print("same (collection, filename) live>1:", q("""select count(*) from (select collection_id, original_filename from tb_documents
      where deleted_at is null group by 1,2 having count(*)>1)""")[0][0])
print("status vs deleted_at:", q("select status, deleted_at is not null, count(*) from tb_documents group by 1,2"))

print("\n## 6. time formats")
pat = {
    "kst_iso": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$",
    "sqlite_utc": r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$",
    "iso_micro_tz": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+\+\d{2}:\d{2}$",
    "iso_naive": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$",
    "iso_utc_z": r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$",
}
for t in tables:
    for col in q(f"PRAGMA table_info({t})"):
        name = col[1]
        if not (name.endswith("_at") or name in {"expires_at"}):
            continue
        cnt = Counter()
        for (v,) in c.execute(f"select {name} from {t}"):
            if v is None:
                cnt["null"] += 1
                continue
            k = next((k for k, p in pat.items() if re.match(p, str(v))), "OTHER:" + str(v)[:26])
            cnt[k] += 1
        if cnt:
            print(f"{t}.{name}: {dict(cnt)}")

print("\n## 7. resources")
print("content_hash reused across rows (live):", q("""select count(*) from (select content_hash from tb_spreadsheet_resources
      where status!='deleted' group by 1 having count(*)>1)""")[0][0])
print("distinct hashes / live rows:", q("select count(distinct content_hash), count(*) from tb_spreadsheet_resources where status!='deleted'")[0][:])
print("staging parse jobs (age):", q("select parse_job_id is not null, min(created_at), max(created_at), count(distinct parse_job_id) from tb_spreadsheet_resources where status='staging'")[0][:])

print("\n## 8. boolean/range")
for t, col in [("tb_users", "is_active"), ("tb_departments", "is_active"), ("tb_collections", "is_active"),
               ("tb_llm_models", "is_enabled"), ("tb_llm_models", "requires_api_key"), ("tb_query_logs", "answer_generated"),
               ("tb_login_history", "success"), ("tb_query_logs", "feedback")]:
    print(f"{t}.{col}:", q(f"select {col}, count(*) from {t} group by 1"))
for t, col in [("tb_documents", "file_size"), ("tb_documents", "chunk_count"), ("tb_spreadsheet_resources", "file_size"),
               ("tb_query_logs", "response_time_ms"), ("tb_eval_datasets", "progress_done"), ("tb_eval_runs", "progress_done")]:
    print(f"{t}.{col} negative:", q(f"select count(*) from {t} where {col} < 0")[0][0])
print("query_logs s vs ms mismatch(>1ms):", q("select count(*) from tb_query_logs where response_time_s is not null and response_time_ms is not null and abs(response_time_s*1000-response_time_ms)>1")[0][0])

print("\n## 9. permissions / departments")
print("users by role/department:", q("select role, department_id is not null, count(*) from tb_users group by 1,2"))
print("collections with department / topic:", q("select department_id is not null, topic_name is not null, count(*) from tb_collections group by 1,2"))
print("user_collection_permissions rows:", q("select count(*) from tb_user_collection_permissions")[0][0])
print("users.department_name != departments.department_name:", q("""select count(*) from tb_users u join tb_departments d on d.department_id=u.department_id
      where u.department_name != d.department_name""")[0][0])

print("\n## 10. autoincrement next values")
print(q("select name, seq from sqlite_sequence order by name"))
