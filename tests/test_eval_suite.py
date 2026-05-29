from __future__ import annotations

import datetime
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.api.schemas import DatasetRef, SuiteConfig
from src.evaluation import eval_suite
from src.evaluation.eval_suite import EvalSuite


def test_new_suite_id_is_slug_derived_and_filesystem_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        eval_suite,
        "uuid4",
        lambda: SimpleNamespace(hex="abcdef1234567890"),
    )

    suite_id = eval_suite.new_suite_id("  My Suite: 2026!  ")
    fallback_id = eval_suite.new_suite_id("!!!")

    assert suite_id == "my-suite-2026-abcdef12"
    assert fallback_id == "suite-abcdef12"
    assert re.fullmatch(r"[a-z0-9][a-z0-9-]*", suite_id) is not None


def test_save_load_list_and_delete_suite_roundtrip(tmp_path: Path) -> None:
    suites_dir = tmp_path / "eval_suites"
    beta = _sample_suite("beta-suite", name="Beta")
    alpha = _sample_suite("alpha-suite", name="Alpha")

    eval_suite.save_suite(beta, suites_dir)
    eval_suite.save_suite(alpha, suites_dir)

    assert (suites_dir / "beta-suite.json").is_file()
    assert eval_suite.load_suite("missing-suite", suites_dir) is None
    assert eval_suite.load_suite("alpha-suite", suites_dir) == alpha
    assert [suite.id for suite in eval_suite.list_suites(suites_dir)] == [
        "alpha-suite",
        "beta-suite",
    ]

    assert eval_suite.delete_suite("alpha-suite", suites_dir) is True
    assert not (suites_dir / "alpha-suite.json").exists()
    assert eval_suite.delete_suite("alpha-suite", suites_dir) is False
    assert [suite.id for suite in eval_suite.list_suites(suites_dir)] == ["beta-suite"]


def test_entry_helpers_mutate_persist_and_bump_updated_at(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suites_dir = tmp_path / "eval_suites"
    suite = _sample_suite("entry-suite", name="Entry Suite")
    eval_suite.save_suite(suite, suites_dir)
    first_update = _utc_datetime(2026, 1, 2)
    second_update = _utc_datetime(2026, 1, 3)
    third_update = _utc_datetime(2026, 1, 4)
    update_times = iter([first_update, second_update, third_update])
    monkeypatch.setattr(eval_suite, "_utc_now", lambda: next(update_times))

    dataset_ref = DatasetRef(benchmark="nq", question_id="nq-1")
    added = eval_suite.add_entry(
        "entry-suite",
        question="What is the capital of France?",
        gold_answers=["Paris"],
        source="dataset",
        dataset_ref=dataset_ref,
        notes="fixture",
        suites_dir=suites_dir,
    )

    assert added is not None
    assert added.updated_at == first_update
    assert len(added.entries) == 1
    entry = next(iter(added.entries))
    assert entry.id
    assert entry.dataset_ref == dataset_ref
    assert eval_suite.load_suite("entry-suite", suites_dir) == added

    updated = eval_suite.update_entry(
        "entry-suite",
        entry.id,
        question="Which city is France's capital?",
        gold_answers=["Paris", "City of Paris"],
        notes="updated",
        suites_dir=suites_dir,
    )

    assert updated is not None
    assert updated.updated_at == second_update
    assert len(updated.entries) == 1
    updated_entry = next(iter(updated.entries))
    assert updated_entry.id == entry.id
    assert updated_entry.question == "Which city is France's capital?"
    assert updated_entry.gold_answers == ["Paris", "City of Paris"]
    assert updated_entry.source == "dataset"
    assert updated_entry.dataset_ref == dataset_ref
    assert updated_entry.notes == "updated"

    deleted = eval_suite.delete_entry("entry-suite", entry.id, suites_dir)

    assert deleted is not None
    assert deleted.updated_at == third_update
    assert deleted.entries == []
    assert eval_suite.load_suite("entry-suite", suites_dir) == deleted
    assert eval_suite.update_entry(
        "entry-suite",
        "missing-entry",
        question="No-op",
        suites_dir=suites_dir,
    ) is None
    assert eval_suite.delete_entry("entry-suite", "missing-entry", suites_dir) is None


def _sample_suite(suite_id: str, *, name: str) -> EvalSuite:
    created_at = _utc_datetime(2026, 1, 1)
    return EvalSuite(
        id=suite_id,
        name=name,
        description="Sample suite",
        created_at=created_at,
        updated_at=created_at,
        config=_sample_config(),
        entries=[],
    )


def _sample_config() -> SuiteConfig:
    return SuiteConfig(
        benchmark="nq",
        collection="nq_passages_qwen3_embed_4b",
        mode="hybrid",
        top_k=10,
        reranker="BAAI/bge-reranker-v2-m3",
        generator="heuristic",
    )


def _utc_datetime(year: int, month: int, day: int) -> datetime.datetime:
    value = datetime.datetime(year, month, day, tzinfo=datetime.UTC)
    assert value.tzinfo is not None
    return value
