"""실행 중인 평가 run의 인메모리 추적 및 취소 관리.

단일 인스턴스 환경 전제. 서버 재시작 시 실행 중이던 run은 기동 로직에서
EvalRepository.mark_orphan_runs_failed()로 failed 마킹된다.
(reference app/evaluation/runner/run_registry.py 이식)
"""

import asyncio
from typing import Dict


class _RunEntry:
    def __init__(self, task: asyncio.Task):
        self.task = task
        self.cancel_event = asyncio.Event()


_active_runs: Dict[int, _RunEntry] = {}


def register(run_id: int, task: asyncio.Task) -> None:
    _active_runs[run_id] = _RunEntry(task)


def unregister(run_id: int) -> None:
    _active_runs.pop(run_id, None)


def request_cancel(run_id: int) -> bool:
    """취소를 요청한다. 실행 중이 아니면 False."""
    entry = _active_runs.get(run_id)
    if entry is None:
        return False
    entry.cancel_event.set()
    return True


def is_cancel_requested(run_id: int) -> bool:
    entry = _active_runs.get(run_id)
    return entry is not None and entry.cancel_event.is_set()
