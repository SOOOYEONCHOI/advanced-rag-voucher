"""Persistent state for asynchronous ingest jobs."""

import json
from typing import Any, Dict, Optional

from app.core.config import get_settings
from app.repositories.database import get_database_manager


class IngestJobRepository:
    def __init__(self, db_path: str | None = None) -> None:
        self.db = get_database_manager(db_path or get_settings().sqlite_db_path)

    def create(self, job_id: str, request: Dict[str, Any], created_by: str) -> None:
        self.db.execute_update(
            "INSERT INTO tb_ingest_jobs(job_id,status,current_step,request_json,created_by) VALUES(?,?,?,?,?)",
            (job_id, "queued", "queued", json.dumps(request, ensure_ascii=False), created_by),
        )

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.execute_query("SELECT * FROM tb_ingest_jobs WHERE job_id=?", (job_id,))
        if not rows:
            return None
        item = dict(rows[0])
        item["request"] = json.loads(item.pop("request_json"))
        item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
        return item

    def update(self, job_id: str, *, status: str, step: str, result=None, error=None, error_code=None) -> None:
        self.db.execute_update(
            """UPDATE tb_ingest_jobs SET status=?, current_step=?, result_json=?, error_message=?, error_code=?,
               updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
            (status, step, json.dumps(result, ensure_ascii=False) if result else None, error, error_code, job_id),
        )

    def requeue_interrupted(self) -> list[str]:
        rows = self.db.execute_query("SELECT job_id FROM tb_ingest_jobs WHERE status IN ('queued','running')")
        self.db.execute_update(
            "UPDATE tb_ingest_jobs SET status='queued', current_step='queued' WHERE status='running'"
        )
        return [row["job_id"] for row in rows]
