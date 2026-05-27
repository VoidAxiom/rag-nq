"""Tests for the P0-F baseline runner mapping and orchestration."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from src.config.settings import Settings
from src.evaluation.baseline_runner import (
    build_scoreboard_row_from_eval,
    resolve_commit_sha,
    resolve_repo_root,
    run_baseline,
)
from src.evaluation.retrieval_eval import (
    EvalRunConfig,
    MetricAtK,
    ModeMetricSummary,
    RetrievalEvalReport,
)
from src.evaluation.scoreboard import LatencyMs, ModelSet, load_scoreboard
from src.retrieval.qdrant_retrievers import Mode


def test_build_scoreboard_row_from_eval_extracts_correct_metrics() -> None:
    report = _build_fake_report()
    row = build_scoreboard_row_from_eval(
        report,
        phase="P0",
        pipeline="hybrid+rerank",
        benchmark="nq-retrieval",
        split="dev",
        latency_ms=LatencyMs(p50=12, p95=12),
        commit_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        models=ModelSet(embedder="embedder", reranker="reranker"),
        primary_mode="hybrid",
        notes="baseline",
    )

    assert row.phase == "P0"
    assert row.pipeline == "hybrid+rerank"
    assert row.benchmark == "nq-retrieval"
    assert row.split == "dev"
    assert row.retriever_metrics.recall_at_1 == 0.3
    assert row.retriever_metrics.recall_at_5 == 0.6
    assert row.retriever_metrics.recall_at_10 == 0.8
    assert row.retriever_metrics.mrr_at_10 == 0.55
    assert row.retriever_metrics.ndcg_at_10 == 0.62
    assert row.answer_metrics is None
    assert row.quality_metrics is None
    assert row.latency_ms.p50 == 12
    assert row.models.embedder == "embedder"
    assert row.commit_sha == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert row.notes == "baseline"


def test_build_scoreboard_row_from_eval_missing_primary_mode_raises() -> None:
    report = _build_fake_report(modes=["dense"])

    with pytest.raises(KeyError):
        build_scoreboard_row_from_eval(
            report,
            phase="P0",
            pipeline="hybrid+rerank",
            benchmark="nq-retrieval",
            split="dev",
            latency_ms=LatencyMs(p50=12, p95=12),
            commit_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            models=ModelSet(embedder="embedder", reranker="reranker"),
            primary_mode="hybrid",
        )


def test_build_scoreboard_row_from_eval_missing_k_raises() -> None:
    report = _build_fake_report()
    del report.modes["hybrid"].metrics_by_k["10"]

    with pytest.raises(ValueError):
        build_scoreboard_row_from_eval(
            report,
            phase="P0",
            pipeline="hybrid+rerank",
            benchmark="nq-retrieval",
            split="dev",
            latency_ms=LatencyMs(p50=12, p95=12),
            commit_sha="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
            models=ModelSet(embedder="embedder", reranker="reranker"),
            primary_mode="hybrid",
        )


def test_resolve_repo_root_finds_git_dir() -> None:
    root = resolve_repo_root(Path.cwd())

    assert (root / ".git").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_resolve_commit_sha_returns_40_hex_string() -> None:
    commit_sha = resolve_commit_sha()

    assert len(commit_sha) == 40
    assert set(commit_sha) <= set("0123456789abcdef")


def test_run_baseline_calls_run_retrieval_evaluation_and_appends_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report(query_count=10)
    captured: dict[str, Any] = {}
    fixed_sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

    def fake_run_retrieval_evaluation(*args: Any, **kwargs: Any) -> RetrievalEvalReport:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return fake_report

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        fake_run_retrieval_evaluation,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: fixed_sha,
    )

    output_path = tmp_path / "eval.json"
    scoreboard_path = tmp_path / "scoreboard.json"
    report, row = run_baseline(
        Settings(),
        max_queries=5,
        output_path=output_path,
        scoreboard_path=scoreboard_path,
        phase="P0",
        pipeline="hybrid+rerank",
        benchmark="nq-retrieval",
        split="dev",
        modes=["hybrid"],
        k_values=[1, 5, 10],
    )

    assert report == fake_report
    assert row.commit_sha == fixed_sha
    assert captured["kwargs"]["max_queries"] == 5
    assert captured["kwargs"]["output_path"] == output_path
    assert captured["kwargs"]["modes"] == ["hybrid"]
    assert captured["kwargs"]["k_values"] == [1, 5, 10]
    assert scoreboard_path.is_file()
    scoreboard = load_scoreboard(scoreboard_path)
    assert len(scoreboard.rows) == 1
    saved_row = scoreboard.rows[0]
    assert saved_row.retriever_metrics.recall_at_10 == 0.8
    assert saved_row.retriever_metrics.mrr_at_10 == 0.55
    assert saved_row.retriever_metrics.ndcg_at_10 == 0.62
    assert saved_row.notes is not None
    assert "latency=mean-per-query approximation" in saved_row.notes
    assert "deadbeef" in saved_row.commit_sha


def test_run_baseline_skips_scoreboard_append_when_path_is_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report()

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        lambda *args, **kwargs: fake_report,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )

    run_baseline(
        Settings(),
        max_queries=5,
        output_path=tmp_path / "eval.json",
        scoreboard_path=None,
        phase="P0",
        pipeline="hybrid+rerank",
        benchmark="nq-retrieval",
        split="dev",
        modes=["hybrid"],
        k_values=[1, 5, 10],
    )

    assert not (tmp_path / "scoreboard.json").exists()


def test_run_baseline_empty_notes_does_not_produce_leading_semicolon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report(query_count=10)
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        lambda *args, **kwargs: fake_report,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )

    for index, notes in enumerate(("", "   ")):
        _report, row = run_baseline(
            Settings(),
            max_queries=5,
            output_path=tmp_path / f"eval-{index}.json",
            scoreboard_path=None,
            phase="P0",
            pipeline="hybrid+rerank",
            benchmark="nq-retrieval",
            split="dev",
            modes=["hybrid"],
            k_values=[1, 5, 10],
            notes=notes,
        )
        assert row.notes is not None
        assert not row.notes.startswith(";")
        assert not row.notes.startswith(" ;")
        assert "latency=mean-per-query approximation" in row.notes


def test_run_baseline_zero_queries_yields_zero_latency(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report(
        query_count=0,
        recall_at_1=0.0,
        recall_at_5=0.0,
        recall_at_10=0.0,
        mrr_at_10=0.0,
        ndcg_at_10=0.0,
    )

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        lambda *args, **kwargs: fake_report,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )

    _, row = run_baseline(
        Settings(),
        max_queries=5,
        output_path=tmp_path / "eval.json",
        scoreboard_path=None,
        phase="P0",
        pipeline="hybrid+rerank",
        benchmark="nq-retrieval",
        split="dev",
        modes=["hybrid"],
        k_values=[1, 5, 10],
    )

    assert row.latency_ms.p50 == 0
    assert row.latency_ms.p95 == 0


def test_run_baseline_rejects_k_values_missing_required_cutoffs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        _fail_if_called,
    )

    with pytest.raises(ValueError):
        run_baseline(
            Settings(),
            max_queries=5,
            output_path=Path("eval.json"),
            scoreboard_path=None,
            phase="P0",
            pipeline="hybrid+rerank",
            benchmark="nq-retrieval",
            split="dev",
            modes=["hybrid"],
            k_values=[10],
        )


def test_run_baseline_primary_mode_must_be_in_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        _fail_if_called,
    )

    with pytest.raises(ValueError):
        run_baseline(
            Settings(),
            max_queries=5,
            output_path=Path("eval.json"),
            scoreboard_path=None,
            phase="P0",
            pipeline="hybrid+rerank",
            benchmark="nq-retrieval",
            split="dev",
            modes=["hybrid"],
            k_values=[1, 5, 10],
            primary_mode="dense",
        )


def test_run_baseline_rejects_empty_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_report = _build_fake_report(query_count=10)
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        lambda *a, **kw: fake_report,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )
    with pytest.raises(ValueError, match="modes must be a non-empty list"):
        run_baseline(
            Settings(),
            max_queries=5,
            output_path=Path("/tmp/never_written.json"),
            scoreboard_path=None,
            phase="P0",
            pipeline="hybrid+rerank",
            benchmark="nq-retrieval",
            split="dev",
            modes=[],
            k_values=[1, 5, 10],
        )


def _build_fake_report(
    query_count: int = 10,
    *,
    modes: list[Mode] | None = None,
    recall_at_1: float = 0.3,
    recall_at_5: float = 0.6,
    recall_at_10: float = 0.8,
    mrr_at_10: float = 0.55,
    ndcg_at_10: float = 0.62,
) -> RetrievalEvalReport:
    resolved_modes = modes or ["hybrid"]
    summaries: dict[Mode, ModeMetricSummary] = {}
    for mode in resolved_modes:
        metrics_by_k = {
            "1": MetricAtK(
                query_count=query_count,
                recall_at_k=recall_at_1,
                mrr_at_k=recall_at_1,
                ndcg_at_k=recall_at_1,
            ),
            "5": MetricAtK(
                query_count=query_count,
                recall_at_k=recall_at_5,
                mrr_at_k=0.5 if query_count else 0.0,
                ndcg_at_k=0.5 if query_count else 0.0,
            ),
            "10": MetricAtK(
                query_count=query_count,
                recall_at_k=recall_at_10,
                mrr_at_k=mrr_at_10,
                ndcg_at_k=ndcg_at_10,
            ),
        }
        summaries[mode] = ModeMetricSummary(
            query_count=query_count,
            recall_at_k=recall_at_10,
            mrr_at_k=mrr_at_10,
            ndcg_at_k=ndcg_at_10,
            metrics_by_k=metrics_by_k,
        )
    return RetrievalEvalReport(
        run_config=EvalRunConfig(
            top_k=10,
            k_values=[1, 5, 10],
            modes=resolved_modes,
            relevance_contract="answer_overlap",
            max_queries=query_count if query_count else None,
            query_count=query_count,
            corpus_path="/tmp/fake_corpus.jsonl",
            passages_path=None,
            qdrant_url="http://localhost:6333",
            qdrant_collection="nq_passages_qwen3_embed_4b",
            qdrant_vector_name="dense",
            qdrant_sparse_vector_name="sparse",
            sparse_identifiers=None,
        ),
        modes=summaries,
    )


def _fail_if_called(*args: Any, **kwargs: Any) -> RetrievalEvalReport:
    raise AssertionError("run_retrieval_evaluation should not be called")
