"""Local dev HTTP verification: R4-3 / SC-01 / UI-02..05 / ANS-01..04.

Run only in rag-backend-dev. Never writes source documents or raw responses.
Creates an isolated user and removes that user's records on completion.
"""
import json
import logging
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.models.data_models import UserPermission
from app.repositories.database import get_database_manager
from app.repositories.metadata_repository import MetadataRepository
from app.utils.security import create_user_access_token


def main():
    logging.disable(logging.CRITICAL)
    db = get_database_manager()
    name = db.execute_query("SELECT current_database() AS name")[0]["name"]
    if not name.endswith("_dev"):
        raise RuntimeError("Only a local development database is allowed")
    uid = "api_verify_" + uuid.uuid4().hex[:12]
    results = []
    samples = {}
    client = httpx.Client(base_url="http://127.0.0.1:8081", timeout=180)

    def shape(value, key=""):
        if isinstance(value, dict):
            return {k: shape(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [shape(v, key) for v in value[:1]]
        if not isinstance(value, str):
            return value
        if key in {"type", "stage", "role", "provider", "feedback", "status", "resource_type", "mime_type", "review_status", "document_type", "token_type"}:
            return value
        return "<" + key + ">"

    def check(label, ok, **info):
        results.append({"test": label, "pass": bool(ok), **info})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    def call(label, method, path, expected=200, auth=True, **kw):
        r = client.request(method, path, headers=headers if auth else {}, **kw)
        check(label, r.status_code == expected, status=r.status_code)
        if "json" in r.headers.get("content-type", ""):
            samples[label] = shape(r.json())
        return r

    db.execute_update("INSERT INTO tb_users (user_id,user_pwd,user_name,role,is_active) VALUES (?, '!', 'API verification', 'user', true)", (uid,))
    headers = {"Authorization": "Bearer " + create_user_access_token(uid)}
    try:
        docs = db.execute_query("SELECT d.document_id,c.qdrant_name FROM tb_documents d JOIN tb_collections c ON c.collection_id=d.collection_id WHERE d.deleted_at IS NULL AND EXISTS (SELECT 1 FROM tb_spreadsheet_resources r WHERE r.document_id=d.document_id AND r.status!='deleted') LIMIT 1")
        all_cols = db.execute_query("SELECT qdrant_name FROM tb_collections ORDER BY collection_id")
        col = docs[0]["qdrant_name"] if docs else (all_cols[0]["qdrant_name"] if all_cols else None)
        if col:
            db.execute_update("UPDATE tb_users SET department_id=(SELECT department_id FROM tb_collections WHERE qdrant_name=?) WHERE user_id=?", (col, uid))
        MetadataRepository().store_user_permission(UserPermission(user_id=uid, accessible_collections=[col] if col else [], max_security_level="restricted", allowed_document_types=[], metadata_filters={}))
        call("health", "GET", "/api/health", auth=False)
        call("models", "GET", "/api/models", auth=False)
        call("chat_models", "GET", "/api/chat/models", auth=False)
        call("collections_anonymous", "GET", "/api/query/collections", auth=False)
        call("collections", "GET", "/api/query/collections")
        call("resource_no_token", "GET", "/api/spreadsheet-resources/missing", expected=401, auth=False)
        call("resource_missing", "GET", "/api/spreadsheet-resources/missing", expected=404)
        call("document_missing", "GET", "/api/documents/missing/spreadsheet-resources", expected=404)
        call("stream_forbidden", "POST", "/api/query/stream", expected=403, json={"query":"test", "collection_name":"api_verify_nonexistent", "llm_provider":"local"})
        call("stream_invalid", "POST", "/api/query/stream", expected=422, json={})
        call("feedback_missing", "PATCH", "/api/query/2147483647/feedback", expected=404, json={"feedback":"like"})
        call("feedback_invalid", "PATCH", "/api/query/2147483647/feedback", expected=422, json={"feedback":"invalid"})
        call("voice_no_token", "POST", "/api/voice/transcriptions", expected=401, auth=False, files={"audio":("empty.wav",b"","audio/wav")})
        call("voice_empty", "POST", "/api/voice/transcriptions", expected=400, files={"audio":("empty.wav",b"","audio/wav")})
        call("voice_invalid_type", "POST", "/api/voice/transcriptions", expected=415, files={"audio":("test.txt",b"test","text/plain")})
        if col:
            call("history_empty", "GET", "/api/query/history", params={"collection_name":col})
            call("setting_empty", "GET", "/api/user/llm-settings", params={"collection_name":col})
            call("setting_save", "POST", "/api/user/llm-settings", json={"collection_name":col,"model_id":"local"})
            call("setting_get", "GET", "/api/user/llm-settings", params={"collection_name":col})
            body = {"query":"작업 단계와 조립 시 주의사항을 사진과 함께 알려줘", "collection_name":col,"llm_provider":"local"}
            started = time.monotonic()
            events = []
            with client.stream("POST", "/api/query/stream", headers=headers, json=body) as response:
                for line in response.iter_lines():
                    if line.startswith("data:"):
                        events.append(json.loads(line[5:].strip()))
                check("stream_http", response.status_code == 200 and "text/event-stream" in response.headers.get("content-type", ""), status=response.status_code, seconds=round(time.monotonic()-started,2))
            types = [e.get("type") for e in events]
            check("stream_completed", bool(types) and types[-1]=="done" and "error" not in types, events=list(dict.fromkeys(types)))
            samples["stream"] = [shape(e) for i,e in enumerate(events) if e.get("type")!="token" or i==next((j for j,v in enumerate(events) if v.get("type")=="token"),-1)]
            images = next((e["data"] for e in events if e.get("type")=="images"),[])
            citations = next((e["data"] for e in events if e.get("type")=="citations"),[])
            check("stream_image_count", 0 < len(images) <= 4, count=len(images), citations=len(citations))
            for image in images:
                check("image_citation_link", any(str(c.get("citation_id"))==str(image.get("context_no")) and c.get("document_id")==image.get("document_id") for c in citations))
            for citation in citations:
                linked = call("citation_document_resources", "GET", f"/api/documents/{citation['document_id']}/spreadsheet-resources").json().get("resources", [])
                selected = [v for v in linked if v["resource_id"] in citation.get("resource_ids",[]) and v["displayable"]]
                check("citation_resource_ids_resolve", set(citation.get("resource_ids",[])) <= {v["resource_id"] for v in linked}, linked_displayable=len(selected))
            if docs:
                r = call("resource_list", "GET", f"/api/documents/{docs[0]['document_id']}/spreadsheet-resources")
                resources = r.json().get("resources",[])
                check("resource_list_fields", bool(resources) and all({"title","role","displayable","version_no"} <= set(v) for v in resources), count=len(resources))
                for image in images:
                    own = call("image_document_resources", "GET", f"/api/documents/{image['document_id']}/spreadsheet-resources").json().get("resources", [])
                    check("image_resource_consistency", any(v["resource_id"]==image["resource_id"] and v["displayable"] and v["title"]==image["title"] for v in own))
                ids = {i["resource_id"] for i in images} or {v["resource_id"] for v in resources if v["displayable"]}
                for rid in list(ids)[:4]:
                    r = call("image_download", "GET", f"/api/spreadsheet-resources/{rid}")
                    check("image_binary", r.headers.get("content-type", "").startswith("image/") and len(r.content)>0, bytes=len(r.content), content_type=r.headers.get("content-type"))
                MetadataRepository().store_user_permission(UserPermission(user_id=uid, accessible_collections=[], max_security_level="public", allowed_document_types=[], metadata_filters={}))
                db.execute_update("UPDATE tb_users SET blocked_topics=(SELECT jsonb_build_array(topic_name) FROM tb_collections WHERE qdrant_name=?) WHERE user_id=?", (col, uid))
                call("resource_forbidden", "GET", f"/api/documents/{docs[0]['document_id']}/spreadsheet-resources", expected=403)
                if ids:
                    call("image_forbidden", "GET", f"/api/spreadsheet-resources/{next(iter(ids))}", expected=403)
                revoked = call("history_after_revoke", "GET", "/api/query/history", params={"collection_name":col}).json()
                check("history_hides_revoked_content", not revoked.get("history"))
                MetadataRepository().store_user_permission(UserPermission(user_id=uid, accessible_collections=[col], max_security_level="restricted", allowed_document_types=[], metadata_filters={}))
                db.execute_update("UPDATE tb_users SET blocked_topics='[]'::jsonb WHERE user_id=?", (uid,))
            history = call("history_restore", "GET", "/api/query/history", params={"collection_name":col}).json().get("history",[])
            check("history_images_match", bool(history) and history[-1].get("images",[])==images)
            log = next((e.get("log_id") for e in events if e.get("type")=="meta"),None)
            if log:
                for value in ("like","dislike",None):
                    call("feedback_"+str(value),"PATCH",f"/api/query/{log}/feedback",json={"feedback":value})
            nonstream = call("query_json", "POST", "/api/query/", json=body)
            if nonstream.status_code==200:
                check("query_json_fields", {"answer","citations","images","log_id","chunks","processing_time_ms","query"} <= set(nonstream.json()))
            call("reset", "POST", "/api/query/reset", json={"collection_name":col})
            cleared = call("history_reset", "GET", "/api/query/history", params={"collection_name":col}).json()
            check("reset_clears_history", cleared.get("history")==[])
        else:
            check("data_available", False, reason="No development collection")
    finally:
        db.execute_update("DELETE FROM tb_query_logs WHERE user_id=?", (uid,))
        db.execute_update("DELETE FROM tb_users WHERE user_id=?", (uid,))
        client.close()
        target = Path(__file__).resolve().parents[2] / "docs/design/reports/chat-api-verification-20261021.json"
        # /app is a backend-only mount in the container.
        if not target.parent.exists():
            target = Path("/app/instance/chat-api-verification-20261021.json")
        target.write_text(json.dumps({"results":results,"response_shapes":samples},ensure_ascii=False,indent=2),encoding="utf-8")
        print("RESULT_FILE="+str(target),flush=True)


if __name__ == "__main__":
    main()
