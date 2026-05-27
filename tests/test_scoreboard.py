from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.evaluation.scoreboard import (
    AnswerMetrics,
    LatencyMs,
    ModelSet,
    QualityMetrics,
    RetrieverMetrics,
    ScoreboardRow,
    add_row,
    load_scoreboard,
)


def test_load_empty_scoreboard(tmp_path: Path) -> None:
    path = tmp_path / "scoreboard.json"

    scoreboard = load_scoreboard(path)

    assert scoreboard.schema_version == 1
    assert scoreboard.rows == []
    assert not path.exists()
    _assert_utc(scoreboard.generated_at)


def test_add_row_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "scoreboard.json"
    row = _sample_row()

    add_row(row, path)
    scoreboard = load_scoreboard(path)

    assert scoreboard.schema_version == 1
    assert scoreboard.rows == [row]
    assert scoreboard.rows[0].models.embedder == "Qwen3-Embedding-4B"
    assert scoreboard.rows[0].retriever_metrics.recall_at_10 == 0.81
    _assert_utc(scoreboard.generated_at)


def test_retrieval_only_row_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "scoreboard.json"
    row = _sample_row(
        phase="P0",
        pipeline="retrieval-only",
        benchmark="nq",
        split="dev",
        notes="retrieval baseline",
    ).model_copy(update={"answer_metrics": None, "quality_metrics": None})

    add_row(row, path)
    scoreboard = load_scoreboard(path)

    assert scoreboard.rows == [row]
    assert scoreboard.rows[0].answer_metrics is None
    assert scoreboard.rows[0].quality_metrics is None


def test_row_notes_optional_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "scoreboard.json"
    row = _sample_row(
        phase="P0",
        pipeline="retrieval-only",
        benchmark="nq",
        split="dev",
        notes=None,
    ).model_copy(update={"answer_metrics": None, "quality_metrics": None})

    add_row(row, path)
    scoreboard = load_scoreboard(path)

    assert scoreboard.rows == [row]
    assert scoreboard.rows[0].notes is None


def test_retrieval_only_models_omit_llm_fields(tmp_path: Path) -> None:
    path = tmp_path / "scoreboard.json"
    models = ModelSet(
        embedder="Qwen3-Embedding-4B",
        reranker="BGE-reranker-v2-m3",
    )
    row = ScoreboardRow(
        phase="P0",
        pipeline="retrieval-only",
        benchmark="nq",
        split="dev",
        retriever_metrics=RetrieverMetrics(
            recall_at_1=0.43,
            recall_at_5=0.72,
            recall_at_10=0.81,
            mrr_at_10=0.55,
            ndcg_at_10=0.62,
        ),
        answer_metrics=None,
        quality_metrics=None,
        latency_ms=LatencyMs(
            p50=1240,
            p95=2810,
        ),
        models=models,
        commit_sha="abcdef1234567890",
        notes="retrieval-only row",
    )

    add_row(row, path)
    scoreboard = load_scoreboard(path)

    assert scoreboard.rows[0].models.reasoning_llm is None
    assert scoreboard.rows[0].models.verifier is None


def test_add_row_appends_not_replaces(tmp_path: Path) -> None:
    path = tmp_path / "scoreboard.json"
    row_a = _sample_row(phase="P3", commit_sha="abcdef1234567890", notes="first")
    row_b = _sample_row(phase="P4", commit_sha="123456abcdef7890", notes="second")

    add_row(row_a, path)
    add_row(row_b, path)
    scoreboard = load_scoreboard(path)

    assert scoreboard.rows == [row_a, row_b]


def test_schema_version_must_be_one(tmp_path: Path) -> None:
    path = tmp_path / "scoreboard.json"
    path.write_text(
        """
{
  "schema_version": 2,
  "generated_at": "2026-01-01T00:00:00+00:00",
  "rows": []
}
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_scoreboard(path)


def test_extra_fields_rejected(tmp_path: Path) -> None:
    path = tmp_path / "scoreboard.json"
    row = _sample_row().model_dump(mode="json")
    quality_metrics = row["quality_metrics"]
    assert isinstance(quality_metrics, dict)
    quality_metrics["groundedness_judged"] = 0.5
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-01-01T00:00:00+00:00",
                "rows": [row],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValidationError):
        load_scoreboard(path)


def test_required_fields_enforced() -> None:
    payload = _sample_row().model_dump()
    retriever_metrics = payload["retriever_metrics"]
    assert isinstance(retriever_metrics, dict)
    del retriever_metrics["recall_at_10"]
    del payload["commit_sha"]

    with pytest.raises(ValidationError) as exc_info:
        ScoreboardRow.model_validate(payload)

    locations = {tuple(error["loc"]) for error in exc_info.value.errors()}
    assert ("retriever_metrics", "recall_at_10") in locations
    assert ("commit_sha",) in locations


def test_add_row_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "scoreboard.json"

    add_row(_sample_row(), path)

    assert path.is_file()
    assert len(load_scoreboard(path).rows) == 1


def _sample_row(
    *,
    phase: str = "P3",
    pipeline: str = "hipporag2",
    benchmark: str = "musique-ans",
    split: str = "dev",
    commit_sha: str = "abcdef1234567890",
    notes: str | None = "sample row",
) -> ScoreboardRow:
    return ScoreboardRow(
        phase=phase,
        pipeline=pipeline,
        benchmark=benchmark,
        split=split,
        retriever_metrics=RetrieverMetrics(
            recall_at_1=0.43,
            recall_at_5=0.72,
            recall_at_10=0.81,
            mrr_at_10=0.55,
            ndcg_at_10=0.62,
        ),
        answer_metrics=AnswerMetrics(
            em=0.41,
            f1=0.49,
            joint_f1=0.44,
        ),
        quality_metrics=QualityMetrics(
            faithfulness=0.92,
            context_precision=0.78,
            context_recall=0.84,
            hallucination_rate_judged=0.06,
            abstention_rate=0.04,
        ),
        latency_ms=LatencyMs(
            p50=1240,
            p95=2810,
        ),
        models=ModelSet(
            embedder="Qwen3-Embedding-4B",
            reranker="BGE-reranker-v2-m3",
            reasoning_llm="Qwen3-14B-Instruct (MLX 4-bit)",
            verifier="DeBERTa-v3-large-mnli",
        ),
        commit_sha=commit_sha,
        notes=notes,
    )


def _assert_utc(value: datetime.datetime) -> None:
    assert value.tzinfo is not None
    assert value.tzinfo.utcoffset(value) == datetime.timedelta(0)
