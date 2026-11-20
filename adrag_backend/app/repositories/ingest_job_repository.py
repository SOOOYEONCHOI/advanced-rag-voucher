"""Persistent state for asynchronous ingest jobs."""

import json
from typing import Any, Dict, Optional

from app.repositories.database import get_database_manager


class IngestJobRepository:
    def __init__(self) -> None:
        self.db = get_database_manager()

    # 2026.11.06(sooyeon.choi) 수정 - 작업 유형(ingest·restore)·대상 문서·멱등 키·요청 fingerprint 저장(설계 v1.1 5.4)
    def create(
        self, job_id: str, request: Dict[str, Any], created_by: str, *, operation_type: str = "ingest",
        document_id: Optional[str] = None, idempotency_key: Optional[str] = None,
        request_fingerprint: Optional[str] = None,
    ) -> None:
        self.db.execute_update(
            "INSERT INTO tb_ingest_jobs(job_id,status,current_step,request_json,created_by,operation_type,document_id,"
            "idempotency_key,request_fingerprint) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                job_id, "queued", "queued", json.dumps(request, ensure_ascii=False), created_by, operation_type,
                document_id or request.get("target_document_id"), idempotency_key, request_fingerprint,
            ),
        )

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.execute_query("SELECT * FROM tb_ingest_jobs WHERE job_id=?", (job_id,))
        if not rows:
            return None
        return self._item(rows[0])

    # 2026.11.06(sooyeon.choi) 수정 - 같은 실행자·유형·멱등 키의 기존 작업(재전송 판단)
    def find_by_idempotency_key(self, created_by: str, operation_type: str, idempotency_key: str) -> Optional[Dict[str, Any]]:
        rows = self.db.execute_query(
            "SELECT * FROM tb_ingest_jobs WHERE created_by=? AND operation_type=? AND idempotency_key=?",
            (created_by, operation_type, idempotency_key),
        )
        return self._item(rows[0]) if rows else None

    # 2026.11.06(sooyeon.choi) 수정 - get·멱등 키 조회 공통 변환(jsonb가 문자열·dict 어느 쪽으로 와도 처리)
    @staticmethod
    def _item(row) -> Dict[str, Any]:
        item = dict(row)
        request = item.pop("request_json")
        result = item.pop("result_json")
        item["request"] = json.loads(request) if isinstance(request, str) else request
        item["result"] = (json.loads(result) if isinstance(result, str) else result) if result else None
        return item

    # 2026.11.06(sooyeon.choi) 수정 - 복원 결과의 시각 값도 저장되도록 default=str
    def update(self, job_id: str, *, status: str, step: str, result=None, error=None, error_code=None) -> None:
        self.db.execute_update(
            """UPDATE tb_ingest_jobs SET status=?, current_step=?, result_json=?, error_message=?, error_code=?,
               updated_at=CURRENT_TIMESTAMP WHERE job_id=?""",
            (status, step, json.dumps(result, ensure_ascii=False, default=str) if result else None, error, error_code,
             job_id),
        )

    def requeue_interrupted(self) -> list[str]:
        rows = self.db.execute_query("SELECT job_id FROM tb_ingest_jobs WHERE status IN ('queued','running')")
        self.db.execute_update(
            "UPDATE tb_ingest_jobs SET status='queued', current_step='queued' WHERE status='running'"
        )
        return [row["job_id"] for row in rows]
