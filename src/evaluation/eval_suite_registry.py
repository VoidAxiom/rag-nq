"""In-process status registry for evaluation-suite runs."""

from __future__ import annotations

import copy
import datetime
import threading
from dataclasses import dataclass
from typing import Literal

RunStatusLiteral = Literal["queued", "running", "done", "error", "cancelled"]


@dataclass
class RunStatus:
    run_id: str
    suite_id: str
    status: RunStatusLiteral = "queued"
    completed: int = 0
    total: int = 0
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None
    error: str | None = None


class EvalSuiteRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runs: dict[str, RunStatus] = {}

    def create(self, *, run_id: str, suite_id: str, total: int) -> RunStatus:
        with self._lock:
            if run_id in self._runs:
                raise ValueError(f"run_id already exists: {run_id}")
            status = RunStatus(
                run_id=run_id,
                suite_id=suite_id,
                status="queued",
                completed=0,
                total=total,
            )
            self._runs[run_id] = status
            return copy.deepcopy(status)

    def get(self, run_id: str) -> RunStatus | None:
        with self._lock:
            status = self._runs.get(run_id)
            return copy.deepcopy(status) if status is not None else None

    def mark_running(self, run_id: str) -> None:
        with self._lock:
            status = self._runs[run_id]
            status.status = "running"
            status.started_at = _utc_now()

    def mark_progress(self, run_id: str, completed: int) -> None:
        with self._lock:
            status = self._runs[run_id]
            status.completed = completed

    def mark_done(self, run_id: str) -> None:
        with self._lock:
            status = self._runs[run_id]
            status.status = "done"
            status.finished_at = _utc_now()

    def mark_error(self, run_id: str, error: str) -> None:
        with self._lock:
            status = self._runs[run_id]
            status.status = "error"
            status.finished_at = _utc_now()
            status.error = error


_REGISTRY = EvalSuiteRegistry()


def get_registry() -> EvalSuiteRegistry:
    return _REGISTRY


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)  # noqa: UP017
