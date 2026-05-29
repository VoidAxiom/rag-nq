from __future__ import annotations

import pytest

from src.evaluation.eval_suite_registry import EvalSuiteRegistry


def test_registry_state_transitions_return_copies() -> None:
    registry = EvalSuiteRegistry()

    created = registry.create(run_id="run-1", suite_id="suite-1", total=3)
    created.completed = 99
    queued = registry.get("run-1")

    assert queued is not None
    assert queued.status == "queued"
    assert queued.completed == 0
    assert queued.total == 3
    assert queued.started_at is None
    assert queued.finished_at is None

    registry.mark_running("run-1")
    running = registry.get("run-1")

    assert running is not None
    assert running.status == "running"
    assert running.started_at is not None

    registry.mark_progress("run-1", 2)
    progressed = registry.get("run-1")

    assert progressed is not None
    assert progressed.status == "running"
    assert progressed.completed == 2

    registry.mark_done("run-1")
    done = registry.get("run-1")

    assert done is not None
    assert done.status == "done"
    assert done.finished_at is not None
    assert done.error is None


def test_registry_rejects_duplicate_run_id() -> None:
    registry = EvalSuiteRegistry()
    registry.create(run_id="run-1", suite_id="suite-1", total=1)

    with pytest.raises(ValueError):
        registry.create(run_id="run-1", suite_id="suite-2", total=1)


def test_registry_unknown_run_id_raises_key_error() -> None:
    registry = EvalSuiteRegistry()

    with pytest.raises(KeyError):
        registry.mark_running("missing")
    with pytest.raises(KeyError):
        registry.mark_progress("missing", 1)
    with pytest.raises(KeyError):
        registry.mark_done("missing")
    with pytest.raises(KeyError):
        registry.mark_error("missing", "boom")


def test_registry_mark_error_records_error_and_finished_at() -> None:
    registry = EvalSuiteRegistry()
    registry.create(run_id="run-1", suite_id="suite-1", total=1)

    registry.mark_error("run-1", "boom")
    status = registry.get("run-1")

    assert status is not None
    assert status.status == "error"
    assert status.error == "boom"
    assert status.finished_at is not None
