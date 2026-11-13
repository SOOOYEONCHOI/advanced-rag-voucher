"""Spreadsheet resource metadata repository."""

# 2026.08.27(sooyeon.choi) 추가 - resource metadata 저장소
from __future__ import annotations

import json
from typing import Any

from app.repositories.database import DatabaseManager, get_database_manager


# staging → 확정 이동 시 복사하는 컬럼(resource_path·status는 commit 값으로 덮어씀)
_COMMIT_COLUMNS = (
    "resource_id,document_id,parse_job_id,resource_type,content_hash,mime_type,file_size,sheet_id,sheet_name,"
    "from_cell,to_cell,linked_block_id,linked_record_ids,surrounding_range,surrounding_text,created_at"
)


class SpreadsheetResourceRepository:
    def __init__(self, db: DatabaseManager | None = None) -> None:
        self.db = db or get_database_manager()

    def get(self, resource_id: str) -> dict[str, Any] | None:
        rows = self.db.execute_query(
            "SELECT * FROM tb_spreadsheet_resources WHERE resource_id=?",
            (resource_id,),
        )
        if not rows:
            return None
        return self._decode(dict(rows[0]))

    def list_by_document(self, document_id: str, include_deleted: bool = False) -> list[dict[str, Any]]:
        query = "SELECT * FROM tb_spreadsheet_resources WHERE document_id=?"
        if not include_deleted:
            query += " AND status!='deleted'"
        return [self._decode(dict(row)) for row in self.db.execute_query(query, (document_id,))]

    # 2026.10.16 추가 - Phase 2: staging은 tb_spreadsheet_staging_resources에 따로 둔다
    def get_staging(self, resource_id: str) -> dict[str, Any] | None:
        rows = self.db.execute_query(
            "SELECT *, 'staging' AS status FROM tb_spreadsheet_staging_resources WHERE resource_id=?",
            (resource_id,),
        )
        return self._decode(dict(rows[0])) if rows else None

    # 2026.10.16 수정 - Phase 2: staging 행(status='staging')과 이미 확정된 행을 함께 돌려준다
    def list_by_parse_job(self, parse_job_id: str) -> list[dict[str, Any]]:
        staging = self.db.execute_query(
            "SELECT *, 'staging' AS status FROM tb_spreadsheet_staging_resources WHERE parse_job_id=?",
            (parse_job_id,),
        )
        committed = self.db.execute_query(
            "SELECT * FROM tb_spreadsheet_resources WHERE parse_job_id=?",
            (parse_job_id,),
        )
        return [self._decode(dict(row)) for row in [*staging, *committed]]

    # 2026.08.27(sooyeon.choi) 추가 - 삭제된 document에 남아 있는 재시도 대상 조회
    def list_documents_pending_deletion(self) -> list[str]:
        rows = self.db.execute_query(
            """SELECT DISTINCT r.document_id
               FROM tb_spreadsheet_resources r
               LEFT JOIN tb_documents d ON d.document_id = r.document_id
               WHERE r.status != 'deleted'
                 AND (d.document_id IS NULL OR d.deleted_at IS NOT NULL)""",
        )
        return [dict(row)["document_id"] for row in rows]

    # 2026.10.16 수정 - Phase 2: staging 전용 테이블에 기록(문서 행이 생기기 전 단계)
    def create_staging(self, metadata: dict[str, Any]) -> None:
        self.db.execute_update(
            """INSERT INTO tb_spreadsheet_staging_resources(
                resource_id,document_id,parse_job_id,resource_type,resource_path,
                content_hash,mime_type,file_size,sheet_id,sheet_name,from_cell,to_cell,
                linked_block_id,linked_record_ids,surrounding_range,surrounding_text
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                metadata["resource_id"], metadata["document_id"], metadata["parse_job_id"],
                metadata["resource_type"], metadata["resource_path"], metadata["content_hash"],
                metadata["mime_type"], metadata["file_size"], metadata.get("sheet_id"),
                metadata.get("sheet_name"), metadata.get("from_cell"), metadata.get("to_cell"),
                metadata.get("linked_block_id"),
                json.dumps(metadata.get("linked_record_ids") or [], ensure_ascii=False),
                metadata.get("surrounding_range"), metadata.get("surrounding_text"),
            ),
        )

    # 2026.08.27(sooyeon.choi) 수정 - 분석 대기 resource는 analysis_pending으로 commit
    # 2026.10.16 수정 - Phase 2: staging 행을 확정 테이블로 옮긴다(문서 FK — 문서 행이 먼저 있어야 함)
    def mark_committed(self, resource_id: str, resource_path: str, status: str = "committed") -> None:
        with self.db.get_connection() as conn:
            conn.execute(
                f"""INSERT INTO tb_spreadsheet_resources({_COMMIT_COLUMNS}, resource_path, status)
                    SELECT {_COMMIT_COLUMNS}, ?, ? FROM tb_spreadsheet_staging_resources WHERE resource_id=?
                    ON CONFLICT (resource_id) DO UPDATE SET resource_path=excluded.resource_path,
                                                            status=excluded.status""",
                (resource_path, status, resource_id),
            )
            conn.execute("DELETE FROM tb_spreadsheet_staging_resources WHERE resource_id=?", (resource_id,))

    # 2026.08.27(sooyeon.choi) 추가 - 분석 상태 전이
    def set_status(self, resource_id: str, status: str) -> None:
        self.db.execute_update(
            """UPDATE tb_spreadsheet_resources
               SET status=?, updated_at=CURRENT_TIMESTAMP WHERE resource_id=?""",
            (status, resource_id),
        )

    def mark_deleted_by_document(self, document_id: str) -> None:
        self.db.execute_update(
            """UPDATE tb_spreadsheet_resources
               SET status='deleted', updated_at=CURRENT_TIMESTAMP WHERE document_id=?""",
            (document_id,),
        )

    def delete_staging_by_parse_job(self, parse_job_id: str) -> None:
        # 2026.10.16 수정 - Phase 2: staging 전용 테이블에서 삭제
        self.db.execute_update(
            "DELETE FROM tb_spreadsheet_staging_resources WHERE parse_job_id=?",
            (parse_job_id,),
        )

    # 2026.08.27(sooyeon.choi) 추가 - resource 분석 결과 등록/조회
    def create_analysis(self, analysis: dict[str, Any]) -> None:
        self.db.execute_update(
            """INSERT INTO tb_spreadsheet_resource_analyses(
                analysis_id,resource_id,document_id,analysis_version,method,model,model_version,
                prompt_version,pipeline_version,status,result_path,text,confidence
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                analysis["analysis_id"], analysis["resource_id"], analysis["document_id"],
                analysis["analysis_version"], analysis["method"], analysis.get("model"),
                analysis.get("model_version"), analysis.get("prompt_version"),
                analysis.get("pipeline_version"), analysis["status"], analysis.get("result_path"),
                analysis.get("text"), analysis.get("confidence"),
            ),
        )

    def list_analyses(self, resource_id: str) -> list[dict[str, Any]]:
        return [
            dict(row)
            for row in self.db.execute_query(
                """SELECT * FROM tb_spreadsheet_resource_analyses
                   WHERE resource_id=? ORDER BY analysis_version""",
                (resource_id,),
            )
        ]

    def latest_analysis_version(self, resource_id: str) -> int:
        rows = self.db.execute_query(
            """SELECT MAX(analysis_version) AS version
               FROM tb_spreadsheet_resource_analyses WHERE resource_id=?""",
            (resource_id,),
        )
        return int(dict(rows[0])["version"] or 0) if rows else 0

    def delete_analyses_by_document(self, document_id: str) -> None:
        self.db.execute_update(
            "DELETE FROM tb_spreadsheet_resource_analyses WHERE document_id=?",
            (document_id,),
        )

    @staticmethod
    def _decode(item: dict[str, Any]) -> dict[str, Any]:
        item["linked_record_ids"] = json.loads(item.get("linked_record_ids") or "[]")
        return item
