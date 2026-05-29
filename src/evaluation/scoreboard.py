"""Master scoreboard artifact schema and append helpers."""

from __future__ import annotations

import datetime
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCOREBOARD_PATH = Path("artifacts/scoreboard.json")


class RetrieverMetrics(BaseModel):
    """Retriever metrics captured for one benchmark/config row."""

    model_config = ConfigDict(extra="forbid")

    recall_at_1: float = Field(ge=0.0, le=1.0)
    recall_at_5: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    mrr_at_10: float = Field(ge=0.0, le=1.0)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)


class AnswerMetrics(BaseModel):
    """Answer quality metrics captured when generation is enabled."""

    model_config = ConfigDict(extra="forbid")

    em: float = Field(ge=0.0, le=1.0)
    f1: float = Field(ge=0.0, le=1.0)
    joint_f1: float = Field(ge=0.0, le=1.0)


class QualityMetrics(BaseModel):
    """Judged quality metrics for generated answers and supporting context."""

    model_config = ConfigDict(extra="forbid")

    faithfulness: float = Field(ge=0.0, le=1.0)
    context_precision: float = Field(ge=0.0, le=1.0)
    context_recall: float = Field(ge=0.0, le=1.0)
    hallucination_rate_judged: float = Field(ge=0.0, le=1.0)
    abstention_rate: float = Field(ge=0.0, le=1.0)


class LatencyMs(BaseModel):
    """Latency percentiles in milliseconds."""

    model_config = ConfigDict(extra="forbid")

    p50: int = Field(ge=0)
    p95: int = Field(ge=0)


class ModelSet(BaseModel):
    """Model identifiers used for one benchmark/config row.

    PLAN.md §6 shows the example schema with all four model fields populated
    for a P3 HippoRAG row. PLAN.md §5.0 makes generation conditional ("when
    generation is enabled"), so `reasoning_llm` and `verifier` are Optional
    for retrieval-only baselines such as P0 `src/scripts/eval_retrieval.py`
    without inventing placeholder LLM identifiers. That mirrors avoiding fake
    EM/F1 for retrieval-only rows; `embedder` and `reranker` remain required
    retrieval primitives present in every config.
    """

    model_config = ConfigDict(extra="forbid")

    embedder: str
    reranker: str
    reasoning_llm: str | None = None
    verifier: str | None = None


class ScoreboardRow(BaseModel):
    """One immutable scoreboard result row."""

    model_config = ConfigDict(extra="forbid")

    phase: str
    pipeline: str
    benchmark: str
    split: str
    retriever_metrics: RetrieverMetrics
    answer_metrics: AnswerMetrics | None = None
    quality_metrics: QualityMetrics | None = None
    latency_ms: LatencyMs
    models: ModelSet
    commit_sha: str
    notes: str | None = None
    suite_id: str | None = None
    suite_name: str | None = None
    run_id: str | None = None
    num_questions: int | None = None
    launched_via: Literal["ui", "cli"] | None = None


class Scoreboard(BaseModel):
    """Versioned master scoreboard artifact."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    generated_at: datetime.datetime
    rows: list[ScoreboardRow]


def load_scoreboard(path: Path = SCOREBOARD_PATH) -> Scoreboard:
    """Load a scoreboard artifact, or return an empty v1 scoreboard if absent."""

    if not path.is_file():
        return Scoreboard(schema_version=1, generated_at=_utc_now(), rows=[])
    return Scoreboard.model_validate_json(path.read_text(encoding="utf-8"))


def add_row(row: ScoreboardRow, path: Path = SCOREBOARD_PATH) -> None:
    """Append one row to the scoreboard artifact using an atomic file replace."""

    scoreboard = load_scoreboard(path)
    updated = Scoreboard(
        schema_version=1,
        generated_at=_utc_now(),
        rows=[*scoreboard.rows, row],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(updated.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(tz=datetime.timezone.utc)  # noqa: UP017
