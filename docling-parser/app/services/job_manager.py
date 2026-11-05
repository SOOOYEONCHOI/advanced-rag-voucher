"""
Job 상태 관리 모듈
"""
import threading
from datetime import datetime
from typing import Dict, Optional, Any
from pathlib import Path


class JobManager:
    """Job 상태 관리자"""
    
    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        # 2026.06.17(sooyeon.choi) 수정 - docker-compose 볼륨 마운트 경로(./data/results:/app/data/results)에 맞게 경로 수정
        self._results_dir = Path("/app/data/results")
        self._results_dir.mkdir(parents=True, exist_ok=True)
    
    def create_job(
        self,
        job_id: str,
        file_path: str,
        output_format: str,
        document_id: Optional[str] = None,
    ):
        # 2026.03.18 수정 - options 파라미터 제거
        # 2026.08.28(sooyeon.choi) 수정 - parse.py가 전달하는 document_id 수용
        #   (파라미터 누락으로 TypeError -> /api/parse가 500 반환하던 문제)
        """새 Job 생성"""
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "completed_at": None,
                "file_path": file_path,
                "output_format": output_format,
                "document_id": document_id,
                "result": None,
                "error": None
            }
    
    def update_job_status(self, job_id: str, status: str):
        """Job 상태 업데이트"""
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = status
    
    def complete_job(self, job_id: str, result: Dict[str, Any]):
        """Job 완료 처리"""
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "completed"
                self._jobs[job_id]["completed_at"] = datetime.now().isoformat()
                self._jobs[job_id]["result"] = result

                # 결과 파일 저장
                result_file = self._results_dir / f"{job_id}_result.json"
                import json
                with open(result_file, "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)

                # 2026.06.17(sooyeon.choi) 수정 - md 포맷인 경우 마크다운 파일 별도 저장
                if result.get("format") == "md":
                    pages = result.get("pages", [])
                    md_content = "\n\n".join(
                        p["markdown"] for p in pages if p.get("markdown")
                    )
                    md_file = self._results_dir / f"{job_id}_result.md"
                    with open(md_file, "w", encoding="utf-8") as f:
                        f.write(md_content)
    
    def fail_job(self, job_id: str, error_message: str):
        """Job 실패 처리"""
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "failed"
                self._jobs[job_id]["completed_at"] = datetime.now().isoformat()
                self._jobs[job_id]["error"] = error_message
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Job 조회"""
        with self._lock:
            return self._jobs.get(job_id)
    
    def get_active_job_count(self) -> int:
        """활성 Job 개수 조회"""
        with self._lock:
            return sum(
                1 for job in self._jobs.values()
                if job["status"] in ["pending", "processing"]
            )

    def delete_job(self, job_id: str):
        # 2026.03.18 수정 - Job 메모리 누수 방지: 결과 조회 후 메모리에서 제거
        """Job 삭제 (결과 조회 완료 후 메모리 정리용)"""
        with self._lock:
            self._jobs.pop(job_id, None)

