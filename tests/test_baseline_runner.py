"""Tests for the P0-F baseline runner mapping and orchestration."""

from __future__ import annotations

import math
import shutil
import subprocess
import time
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
    EvalCase,
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


def test_resolve_commit_sha_rejects_empty_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        _ = args, kwargs
        return subprocess.CompletedProcess(
            args=["git", "rev-parse", "HEAD"],
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr("src.evaluation.baseline_runner.subprocess.run", fake_run)

    with pytest.raises(
        RuntimeError,
        match="git rev-parse HEAD returned unexpected output",
    ):
        resolve_commit_sha(tmp_path)


def test_run_baseline_fails_fast_if_git_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_commit_sha(repo_root: Path | None = None) -> str:
        _ = repo_root
        raise RuntimeError("git unavailable")

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        _fail_if_called,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        fail_commit_sha,
    )

    with pytest.raises(RuntimeError, match="git unavailable"):
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
    _patch_fast_latency_sample(monkeypatch)

    settings = Settings()
    output_path = tmp_path / "eval.json"
    scoreboard_path = tmp_path / "scoreboard.json"
    report, row = run_baseline(
        settings,
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
    assert captured["kwargs"]["corpus_path"] == settings.index_chunks_path
    assert scoreboard_path.is_file()
    scoreboard = load_scoreboard(scoreboard_path)
    assert len(scoreboard.rows) == 1
    saved_row = scoreboard.rows[0]
    assert saved_row.retriever_metrics.recall_at_10 == 0.8
    assert saved_row.retriever_metrics.mrr_at_10 == 0.55
    assert saved_row.retriever_metrics.ndcg_at_10 == 0.62
    assert saved_row.notes is not None
    assert "latency_p50_p95_from_prefix_sample" in saved_row.notes
    assert "deadbeef" in saved_row.commit_sha


def test_run_baseline_passes_explicit_corpus_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report(query_count=10)
    captured: dict[str, Any] = {}
    settings = Settings()

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
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )

    run_baseline(
        settings,
        max_queries=5,
        output_path=tmp_path / "eval.json",
        scoreboard_path=None,
        phase="P0",
        pipeline="hybrid+rerank",
        benchmark="nq-retrieval",
        split="dev",
        modes=["hybrid"],
        k_values=[1, 5, 10],
        latency_sample_size=0,
    )

    assert captured["kwargs"]["corpus_path"] == settings.index_chunks_path


def test_run_baseline_missing_index_chunks_propagates_filenotfound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_run_retrieval_evaluation(
        *args: Any,
        **kwargs: Any,
    ) -> RetrievalEvalReport:
        _ = args, kwargs
        raise FileNotFoundError("Evaluation corpus does not exist: missing.jsonl")

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        fail_run_retrieval_evaluation,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )

    with pytest.raises(FileNotFoundError, match="Evaluation corpus does not exist"):
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
            latency_sample_size=0,
        )


def test_run_baseline_latency_sample_failure_falls_back_to_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report(query_count=10)
    fixed_sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        lambda *args, **kwargs: fake_report,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: fixed_sha,
    )

    def fail_latency_sample(*args: Any, **kwargs: Any) -> list[float]:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "src.evaluation.baseline_runner._measure_latency_sample_ms",
        fail_latency_sample,
    )

    scoreboard_path = tmp_path / "scoreboard.json"
    _report, row = run_baseline(
        Settings(),
        max_queries=5,
        output_path=tmp_path / "eval.json",
        scoreboard_path=scoreboard_path,
        phase="P0",
        pipeline="hybrid+rerank",
        benchmark="nq-retrieval",
        split="dev",
        modes=["hybrid"],
        k_values=[1, 5, 10],
    )

    assert row.latency_ms.p50 == 0
    assert row.latency_ms.p95 == 0
    assert scoreboard_path.is_file()
    scoreboard = load_scoreboard(scoreboard_path)
    assert len(scoreboard.rows) == 1
    saved_row = scoreboard.rows[0]
    assert saved_row.latency_ms.p50 == 0
    assert saved_row.latency_ms.p95 == 0
    assert saved_row.notes is not None
    assert "latency_p50_p95_from_prefix_sample=0_queries" in saved_row.notes
    assert "latency_sample_failed=RuntimeError" in saved_row.notes


def test_run_baseline_latency_sample_programming_bug_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report(query_count=10)
    fixed_sha = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        lambda *args, **kwargs: fake_report,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: fixed_sha,
    )

    def fail_latency_sample(*args: Any, **kwargs: Any) -> list[float]:
        raise TypeError("bug")

    monkeypatch.setattr(
        "src.evaluation.baseline_runner._measure_latency_sample_ms",
        fail_latency_sample,
    )

    with pytest.raises(TypeError, match="bug"):
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
    _patch_fast_latency_sample(monkeypatch)

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
    _patch_fast_latency_sample(monkeypatch)

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
        assert "latency_p50_p95_from_prefix_sample" in row.notes


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


def test_run_baseline_latency_uses_real_percentiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report(query_count=21)
    calls = {"count": 0}
    queries: list[str] = []
    durations_ms = [
        5,
        10,
        15,
        20,
        25,
        30,
        35,
        40,
        45,
        50,
        55,
        60,
        65,
        70,
        75,
        80,
        85,
        90,
        95,
        100,
    ]
    perf_sequence: list[float] = []
    clock = 0.0
    for duration_ms in durations_ms:
        perf_sequence.append(clock)
        clock += duration_ms / 1000.0
        perf_sequence.append(clock)
        clock += 0.001
    perf_iter = iter(perf_sequence)

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        lambda *args, **kwargs: fake_report,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )

    def fake_build_eval_cases_from_index_artifact(
        _index_path: Path,
        *,
        max_queries: int | None,
        **_kwargs: Any,
    ) -> list[EvalCase]:
        assert max_queries == 21
        return [EvalCase(query=f"query-{index}") for index in range(max_queries)]

    def fake_retrieve(_self: object, query: str, top_k: int) -> list[Any]:
        _ = top_k
        call_index = calls["count"]
        calls["count"] = call_index + 1
        queries.append(query)
        return []

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.build_eval_cases_from_index_artifact",
        fake_build_eval_cases_from_index_artifact,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.QdrantModeRetriever.retrieve",
        fake_retrieve,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.time.perf_counter",
        lambda: next(perf_iter),
    )

    _report, row = run_baseline(
        Settings(),
        max_queries=21,
        output_path=tmp_path / "eval.json",
        scoreboard_path=None,
        phase="P0",
        pipeline="hybrid+rerank",
        benchmark="nq-retrieval",
        split="dev",
        modes=["hybrid"],
        k_values=[1, 5, 10],
        latency_sample_size=20,
    )

    assert calls["count"] == 21
    assert queries[0] == "query-0"
    assert queries[1:] == [f"query-{index}" for index in range(1, 21)]
    sorted_latencies = sorted(durations_ms)
    latency_count = len(sorted_latencies)
    # nearest-rank p50 uses ceil(0.50*20)-1 = 9 -> 50ms;
    # p95 uses ceil(0.95*20)-1 = 18 -> 95ms.
    expected_p50_index = math.ceil(0.50 * latency_count) - 1
    expected_p95_index = math.ceil(0.95 * latency_count) - 1
    assert row.latency_ms.p50 == sorted_latencies[expected_p50_index]
    assert row.latency_ms.p95 == sorted_latencies[expected_p95_index]
    assert row.latency_ms.p95 > row.latency_ms.p50
    assert row.notes is not None
    assert "latency_p50_p95_from_prefix_sample=20_queries" in row.notes


def test_run_baseline_latency_sample_zero_queries(
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
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.build_eval_cases_from_index_artifact",
        _fail_if_called,
    )

    _report, row = run_baseline(
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
    assert row.notes is not None
    assert "latency_p50_p95_from_prefix_sample=0_queries" in row.notes


def test_run_baseline_query_count_one_skips_warmup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report(query_count=1)
    retriever_instantiated = False

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        lambda *args, **kwargs: fake_report,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )

    def fail_case_build(*args: Any, **kwargs: Any) -> list[EvalCase]:
        raise AssertionError("latency cases should not be built")

    def fail_retriever_instantiation(*args: Any, **kwargs: Any) -> object:
        nonlocal retriever_instantiated
        retriever_instantiated = True
        raise AssertionError("retriever should not be instantiated")

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.build_eval_cases_from_index_artifact",
        fail_case_build,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.QdrantModeRetriever",
        fail_retriever_instantiation,
    )

    _report, row = run_baseline(
        Settings(),
        max_queries=1,
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
    assert row.notes is not None
    assert "latency_p50_p95_from_prefix_sample=0_queries" in row.notes
    assert not retriever_instantiated


def test_run_baseline_latency_sample_single_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report(query_count=2)
    calls = {"count": 0}
    queries: list[str] = []

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        lambda *args, **kwargs: fake_report,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.build_eval_cases_from_index_artifact",
        lambda *args, **kwargs: [
            EvalCase(query="warmup-query"),
            EvalCase(query="timed-query"),
        ],
    )

    def fake_retrieve(_self: object, query: str, top_k: int) -> list[Any]:
        _ = top_k
        calls["count"] += 1
        queries.append(query)
        time.sleep(0.02)
        return []

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.QdrantModeRetriever.retrieve",
        fake_retrieve,
    )

    _report, row = run_baseline(
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
        latency_sample_size=1,
    )

    assert calls["count"] == 2
    assert queries == ["warmup-query", "timed-query"]
    assert row.latency_ms.p50 == row.latency_ms.p95
    # One timed 20ms sleep should round to the same p50/p95 value.
    assert 15 <= row.latency_ms.p50 <= 40
    assert 15 <= row.latency_ms.p95 <= 40
    assert row.notes is not None
    assert "latency_p50_p95_from_prefix_sample=1_queries" in row.notes


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


def _patch_fast_latency_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_build_eval_cases_from_index_artifact(
        _index_path: Path,
        *,
        max_queries: int | None,
        **_kwargs: Any,
    ) -> list[EvalCase]:
        return [
            EvalCase(query=f"latency-query-{index}")
            for index in range(max_queries if max_queries is not None else 0)
        ]

    def fake_retrieve(_self: object, _query: str, top_k: int) -> list[Any]:
        _ = top_k
        return []

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.build_eval_cases_from_index_artifact",
        fake_build_eval_cases_from_index_artifact,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.QdrantModeRetriever.retrieve",
        fake_retrieve,
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
