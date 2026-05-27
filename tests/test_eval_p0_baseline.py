"""CLI smoke tests for the P0-F baseline runner."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest

from src.config.settings import Settings
from src.evaluation.retrieval_eval import (
    EvalCase,
    EvalRunConfig,
    MetricAtK,
    ModeMetricSummary,
    RetrievalEvalReport,
)
from src.evaluation.scoreboard import load_scoreboard
from src.ingestion.models import ChunkManifest
from src.retrieval.qdrant_retrievers import Mode


def test_cli_writes_eval_and_appends_scoreboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_report = _build_fake_report()
    output_path = tmp_path / "eval.json"
    scoreboard_path = tmp_path / "scoreboard.json"
    captured = _patch_cli_dependencies(monkeypatch, fake_report)
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
            "--latency-sample-size",
            "3",
        ],
    )

    from src.scripts.eval_p0_baseline import main

    main()

    assert output_path.is_file()
    assert scoreboard_path.is_file()
    scoreboard = load_scoreboard(scoreboard_path)
    assert len(scoreboard.rows) == 1
    assert scoreboard.rows[0].retriever_metrics.recall_at_10 == 0.8
    assert captured["latency_sample_max_queries"] == 4
    stdout = capsys.readouterr().out
    assert (
        f"Wrote retrieval eval report to {output_path} for 10 queries "
        "(recall@10=0.8000, mrr@10=0.5500, ndcg@10=0.6200)"
    ) in stdout
    assert f"Appended scoreboard row at {scoreboard_path}" in stdout


def test_cli_accepts_latency_sample_size_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report()
    output_path = tmp_path / "eval.json"
    scoreboard_path = tmp_path / "scoreboard.json"
    captured = _patch_cli_dependencies(monkeypatch, fake_report)
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
            "--latency-sample-size",
            "0",
        ],
    )

    from src.scripts.eval_p0_baseline import main

    main()

    assert output_path.is_file()
    scoreboard = load_scoreboard(scoreboard_path)
    assert len(scoreboard.rows) == 1
    row = scoreboard.rows[0]
    assert row.latency_ms.p50 == 0
    assert row.latency_ms.p95 == 0
    assert row.notes is not None
    assert "latency_p50_p95_from_prefix_sample=0_queries" in row.notes
    assert "latency_sample_max_queries" not in captured


def test_cli_validates_split_matches_settings_dataset_split(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        Settings,
        "from_env",
        classmethod(lambda cls: cls(dataset_split="train")),
    )
    monkeypatch.setattr(
        "src.scripts.eval_p0_baseline.load_chunk_manifest",
        lambda _path: _build_chunk_manifest(dataset_split="train"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_p0_baseline",
            "--max-queries",
            "5",
            "--output",
            str(tmp_path / "eval.json"),
            "--split",
            "dev",
        ],
    )

    from src.scripts.eval_p0_baseline import main

    with pytest.raises(SystemExit):
        main()

    stderr = capsys.readouterr().err
    assert "dev" in stderr
    assert "train" in stderr


def test_cli_validates_split_matches_persisted_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        Settings,
        "from_env",
        classmethod(lambda cls: cls(dataset_split="dev")),
    )
    monkeypatch.setattr(
        "src.scripts.eval_p0_baseline.load_chunk_manifest",
        lambda _path: _build_chunk_manifest(dataset_split="train"),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_p0_baseline",
            "--max-queries",
            "5",
            "--output",
            str(tmp_path / "eval.json"),
            "--split",
            "dev",
        ],
    )

    from src.scripts.eval_p0_baseline import main

    with pytest.raises(SystemExit):
        main()

    stderr = capsys.readouterr().err
    assert "dev" in stderr
    assert "train" in stderr
    assert "RAG_DATASET_SPLIT" in stderr


def test_cli_no_chunk_manifest_errors_with_build_indexes_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        Settings,
        "from_env",
        classmethod(lambda cls: cls(dataset_split="dev")),
    )
    monkeypatch.setattr(
        "src.scripts.eval_p0_baseline.load_chunk_manifest",
        lambda _path: None,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_p0_baseline",
            "--max-queries",
            "5",
            "--output",
            str(tmp_path / "eval.json"),
        ],
    )

    from src.scripts.eval_p0_baseline import main

    with pytest.raises(SystemExit):
        main()

    assert "build_indexes" in capsys.readouterr().err


def test_cli_accepts_matching_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_report = _build_fake_report()
    output_path = tmp_path / "eval.json"
    scoreboard_path = tmp_path / "scoreboard.json"
    _patch_cli_dependencies(monkeypatch, fake_report, dataset_split="train")
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
            "--split",
            "train",
        ],
    )

    from src.scripts.eval_p0_baseline import main

    main()

    scoreboard = load_scoreboard(scoreboard_path)
    assert len(scoreboard.rows) == 1
    assert scoreboard.rows[0].split == "train"


def test_cli_warns_if_settings_split_differs_from_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_report = _build_fake_report()
    output_path = tmp_path / "eval.json"
    scoreboard_path = tmp_path / "scoreboard.json"
    _patch_cli_dependencies(
        monkeypatch,
        fake_report,
        dataset_split="dev",
        persisted_split="train",
    )
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
            "--split",
            "train",
        ],
    )

    from src.scripts.eval_p0_baseline import main

    main()

    scoreboard = load_scoreboard(scoreboard_path)
    assert len(scoreboard.rows) == 1
    assert scoreboard.rows[0].split == "train"
    stderr = capsys.readouterr().err
    assert "WARNING: settings.dataset_split='dev' differs" in stderr
    assert "persisted chunk manifest split='train'" in stderr


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


def test_cli_restores_dependency_logger_levels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake_report = _build_fake_report()
    output_path = tmp_path / "eval.json"
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
            "--no-append-scoreboard",
        ],
    )

    from src.scripts.eval_p0_baseline import main

    httpx_logger = logging.getLogger("httpx")
    original_level = httpx_logger.level
    httpx_logger.setLevel(logging.DEBUG)
    try:
        main()
        assert httpx_logger.level == logging.DEBUG
    finally:
        httpx_logger.setLevel(original_level)

    assert "Wrote retrieval eval report" in capsys.readouterr().out


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


def test_cli_rejects_latency_sample_size_negative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_p0_baseline",
            "--max-queries",
            "5",
            "--output",
            str(tmp_path / "eval.json"),
            "--latency-sample-size",
            "-1",
        ],
    )

    from src.scripts.eval_p0_baseline import main

    with pytest.raises(SystemExit):
        main()


def _patch_cli_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    fake_report: RetrievalEvalReport,
    *,
    dataset_split: str = "dev",
    persisted_split: str | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    manifest_split = dataset_split if persisted_split is None else persisted_split

    def fake_run_retrieval_evaluation(*args: Any, **kwargs: Any) -> RetrievalEvalReport:
        output_path = kwargs["output_path"]
        assert isinstance(output_path, Path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(fake_report.model_dump_json(), encoding="utf-8")
        return fake_report

    def fake_build_eval_cases_from_index_artifact(
        _index_path: Path,
        *,
        max_queries: int | None,
        **_kwargs: Any,
    ) -> list[EvalCase]:
        captured["latency_sample_max_queries"] = max_queries
        return [
            EvalCase(query=f"latency-query-{index}")
            for index in range(max_queries if max_queries is not None else 0)
        ]

    def fake_retrieve(_self: object, _query: str, top_k: int) -> list[Any]:
        captured["latency_top_k"] = top_k
        return []

    monkeypatch.setattr(
        "src.evaluation.baseline_runner.run_retrieval_evaluation",
        fake_run_retrieval_evaluation,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.resolve_commit_sha",
        lambda repo_root=None: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.build_eval_cases_from_index_artifact",
        fake_build_eval_cases_from_index_artifact,
    )
    monkeypatch.setattr(
        "src.evaluation.baseline_runner.QdrantModeRetriever.retrieve",
        fake_retrieve,
    )
    monkeypatch.setattr(
        Settings,
        "from_env",
        classmethod(lambda cls: cls(dataset_split=dataset_split)),
    )
    monkeypatch.setattr(
        "src.scripts.eval_p0_baseline.load_chunk_manifest",
        lambda _path: _build_chunk_manifest(dataset_split=manifest_split),
    )
    return captured


def _build_chunk_manifest(dataset_split: str = "dev") -> ChunkManifest:
    return ChunkManifest(
        schema_version="test-chunk-manifest",
        chunk_schema_version="test-index-chunk",
        dataset_name="sentence-transformers/NQ-retrieval",
        dataset_split=dataset_split,
        line_count=1,
        raw_schema_version="test-raw-dataset",
        raw_row_count=1,
        created_at_utc="2026-01-01T00:00:00Z",
    )


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
