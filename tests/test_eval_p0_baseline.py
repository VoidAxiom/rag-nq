"""CLI smoke tests for the P0-F baseline runner."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from src.config.settings import Settings
from src.evaluation.retrieval_eval import (
    EvalRunConfig,
    MetricAtK,
    ModeMetricSummary,
    RetrievalEvalReport,
)
from src.evaluation.scoreboard import load_scoreboard
from src.retrieval.qdrant_retrievers import Mode


def test_cli_writes_eval_and_appends_scoreboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_report = _build_fake_report()
    output_path = tmp_path / "eval.json"
    scoreboard_path = tmp_path / "scoreboard.json"
    _patch_cli_dependencies(monkeypatch, fake_report)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_p0_baseline",
            "--max-queries",
            "5",
            "--output",
            str(output_path),
            "--scoreboard",
            str(scoreboard_path),
        ],
    )

    from src.scripts.eval_p0_baseline import main

    main()

    assert output_path.is_file()
    assert scoreboard_path.is_file()
    scoreboard = load_scoreboard(scoreboard_path)
    assert len(scoreboard.rows) == 1
    assert scoreboard.rows[0].retriever_metrics.recall_at_10 == 0.8
    stdout = capsys.readouterr().out
    assert (
        f"Wrote retrieval eval report to {output_path} for 10 queries "
        "(recall@10=0.8000, mrr@10=0.5500, ndcg@10=0.6200)"
    ) in stdout
    assert f"Appended scoreboard row at {scoreboard_path}" in stdout


def test_cli_no_append_scoreboard_flag_skips_append(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_report = _build_fake_report()
    output_path = tmp_path / "eval.json"
    scoreboard_path = tmp_path / "scoreboard.json"
    _patch_cli_dependencies(monkeypatch, fake_report)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_p0_baseline",
            "--max-queries",
            "5",
            "--output",
            str(output_path),
            "--scoreboard",
            str(scoreboard_path),
            "--no-append-scoreboard",
        ],
    )

    from src.scripts.eval_p0_baseline import main

    main()

    assert output_path.is_file()
    assert not scoreboard_path.exists()
    stdout = capsys.readouterr().out
    assert "Wrote retrieval eval report" in stdout
    assert "Appended scoreboard row" not in stdout


def test_cli_rejects_non_positive_max_queries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_p0_baseline",
            "--max-queries",
            "0",
            "--output",
            str(tmp_path / "eval.json"),
        ],
    )

    from src.scripts.eval_p0_baseline import main

    with pytest.raises(SystemExit):
        main()

    assert "must be >= 1" in capsys.readouterr().err


def _patch_cli_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    fake_report: RetrievalEvalReport,
) -> None:
    def fake_run_retrieval_evaluation(*args: Any, **kwargs: Any) -> RetrievalEvalReport:
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(fake_report.model_dump_json(), encoding="utf-8")
        return fake_report

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        fake_run_retrieval_evaluation,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: cls()))


def _build_fake_report(
    query_count: int = 10,
    *,
    modes: list[Mode] | None = None,
) -> RetrievalEvalReport:
    resolved_modes = modes or ["hybrid"]
    summaries: dict[Mode, ModeMetricSummary] = {}
    for mode in resolved_modes:
        metrics_by_k = {
            "1": MetricAtK(
                query_count=query_count,
                recall_at_k=0.3,
                mrr_at_k=0.3,
                ndcg_at_k=0.3,
            ),
            "5": MetricAtK(
                query_count=query_count,
                recall_at_k=0.6,
                mrr_at_k=0.5,
                ndcg_at_k=0.5,
            ),
            "10": MetricAtK(
                query_count=query_count,
                recall_at_k=0.8,
                mrr_at_k=0.55,
                ndcg_at_k=0.62,
            ),
        }
        summaries[mode] = ModeMetricSummary(
            query_count=query_count,
            recall_at_k=0.8,
            mrr_at_k=0.55,
            ndcg_at_k=0.62,
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
