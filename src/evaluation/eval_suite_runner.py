"""Run persisted evaluation suites through the query pipeline."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from src.config.settings import Settings
from src.evaluation.baseline_runner import latency_percentiles_ms, resolve_commit_sha
from src.evaluation.eval_suite import EvalSuite, SuiteEntry
from src.evaluation.per_query_metrics import compute_em, compute_f1
from src.evaluation.retrieval_eval import (
    compute_mrr_at_k,
    compute_ndcg_at_k,
    compute_recall_at_k,
)
from src.evaluation.scoreboard import (
    AnswerMetrics,
    ModelSet,
    RetrieverMetrics,
    ScoreboardRow,
)
from src.models.query_schemas import GroundedAnswer, PassageHit, RetrievalMetrics
from src.retrieval.qdrant_retrievers import Mode

LOGGER = logging.getLogger(__name__)
LaunchedVia = Literal["ui", "cli"]


class _RetrieverP(Protocol):
    last_retrieval_metrics: RetrievalMetrics | None

    def retrieve(self, query: str, top_k: int) -> list[PassageHit]: ...


class _GeneratorP(Protocol):
    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer: ...


@dataclass(frozen=True)
class EvalSuiteEntryResult:
    entry_id: str
    question: str
    em: float | None
    f1: float | None
    recall_at_5: float | None
    latency_ms: float


@dataclass(frozen=True)
class EvalSuiteRunResult:
    row: ScoreboardRow
    per_entry: list[EvalSuiteEntryResult]


def run_suite(
    suite: EvalSuite,
    *,
    app_settings: Settings,
    retriever_factory: Callable[[Settings, Mode], _RetrieverP],
    generator_factory: Callable[[Settings], _GeneratorP],
    launched_via: LaunchedVia,
    run_id: str,
    eval_questions_dir: Path | None = None,
    progress_cb: Callable[[int], None] | None = None,
    commit_sha: str | None = None,
) -> EvalSuiteRunResult:
    if not suite.entries:
        raise ValueError("suite has no entries")

    LOGGER.info("eval suite run start suite_id=%s run_id=%s", suite.id, run_id)
    effective_settings = app_settings.model_copy(
        update={
            "qdrant_collection": suite.config.collection,
            "rerank_enabled": suite.config.reranker != "off",
            "rerank_model_name": (
                suite.config.reranker
                if suite.config.reranker != "off"
                else app_settings.rerank_model_name
            ),
        }
    )
    supporting_lookup = _load_supporting_lookup(
        (eval_questions_dir or app_settings.output_dir / "eval_questions")
        / f"{suite.config.benchmark}.json"
    )
    retriever = retriever_factory(effective_settings, suite.config.mode)
    if suite.config.generator != "off":
        generator_settings = Settings.model_validate(
            {
                **effective_settings.model_dump(),
                "generation_provider": suite.config.generator,
            }
        )
        generator = generator_factory(generator_settings)
    else:
        generator = None

    per_entry: list[EvalSuiteEntryResult] = []
    retrieval_rows: list[dict[str, float]] = []
    answer_rows: list[dict[str, float]] = []
    latencies_ms: list[float] = []

    for index, entry in enumerate(suite.entries):
        gold_answers = list(entry.gold_answers) if entry.gold_answers else []
        supporting = _supporting_passage_ids(entry, supporting_lookup)

        started_at = time.perf_counter()
        scoring_top_k = max(suite.config.top_k, 10)
        scoring_hits = retriever.retrieve(entry.question, top_k=scoring_top_k)
        generation_hits = scoring_hits[: suite.config.top_k]
        grounded = (
            generator.generate(entry.question, generation_hits)
            if generator is not None
            else None
        )
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        latencies_ms.append(latency_ms)

        recall_at_5: float | None = None
        if supporting:
            retrieved_ids = [hit.point_id for hit in scoring_hits]
            relevant_ids = set(supporting)
            row = {
                "r1": compute_recall_at_k(retrieved_ids, relevant_ids, k=1),
                "r5": compute_recall_at_k(retrieved_ids, relevant_ids, k=5),
                "r10": compute_recall_at_k(retrieved_ids, relevant_ids, k=10),
                "mrr": compute_mrr_at_k(retrieved_ids, relevant_ids, k=10),
                "ndcg": compute_ndcg_at_k(retrieved_ids, relevant_ids, k=10),
            }
            retrieval_rows.append(row)
            recall_at_5 = row["r5"]

        em: float | None = None
        f1: float | None = None
        if gold_answers and grounded is not None and not grounded.abstained:
            em = compute_em(grounded.answer, gold_answers)
            f1 = compute_f1(grounded.answer, gold_answers)
            answer_rows.append({"em": em, "f1": f1})

        per_entry.append(
            EvalSuiteEntryResult(
                entry_id=entry.id,
                question=entry.question,
                em=em,
                f1=f1,
                recall_at_5=recall_at_5,
                latency_ms=latency_ms,
            )
        )
        if progress_cb is not None:
            progress_cb(index + 1)

    if not retrieval_rows:
        raise ValueError(
            "suite has no entries with supporting-passage gold; "
            "cannot populate retriever_metrics"
        )

    retriever_metrics = RetrieverMetrics(
        recall_at_1=_mean(row["r1"] for row in retrieval_rows),
        recall_at_5=_mean(row["r5"] for row in retrieval_rows),
        recall_at_10=_mean(row["r10"] for row in retrieval_rows),
        mrr_at_10=_mean(row["mrr"] for row in retrieval_rows),
        ndcg_at_10=_mean(row["ndcg"] for row in retrieval_rows),
    )
    answer_metrics = (
        AnswerMetrics(
            em=_mean(row["em"] for row in answer_rows),
            f1=_mean(row["f1"] for row in answer_rows),
            joint_f1=_mean(row["em"] * row["f1"] for row in answer_rows),
        )
        if answer_rows
        else None
    )
    pipeline = _pipeline_label(suite.config.mode, suite.config.reranker)
    reranker_actually_ran = (
        suite.config.mode == "hybrid" and suite.config.reranker != "off"
    )
    reranker_label = suite.config.reranker if reranker_actually_ran else "off"
    if suite.config.generator in ("heuristic", "off"):
        reasoning_llm_label: str | None = None
    else:
        reasoning_llm_label = (
            effective_settings.generation_model_name or suite.config.generator
        )
    row = ScoreboardRow(
        phase="suite",
        pipeline=pipeline,
        benchmark=suite.config.benchmark,
        split=(
            "mixed"
            if any(entry.source == "authored" for entry in suite.entries)
            else "dev"
        ),
        retriever_metrics=retriever_metrics,
        answer_metrics=answer_metrics,
        latency_ms=latency_percentiles_ms(latencies_ms),
        models=ModelSet(
            embedder=app_settings.embedder_name,
            reranker=reranker_label,
            reasoning_llm=reasoning_llm_label,
            verifier=None,
        ),
        commit_sha=_resolve_commit_sha(commit_sha),
        suite_id=suite.id,
        suite_name=suite.name,
        run_id=run_id,
        num_questions=len(suite.entries),
        launched_via=launched_via,
    )
    LOGGER.info("eval suite run complete suite_id=%s run_id=%s", suite.id, run_id)
    return EvalSuiteRunResult(row=row, per_entry=per_entry)


def _load_supporting_lookup(path: Path) -> dict[str, list[str]]:
    if not path.is_file():
        return {}
    lookup: dict[str, list[str]] = {}
    for item in json.loads(path.read_text()):
        try:
            query_id = item["query_id"]
            supporting_passage_ids = item["supporting_passage_ids"]
        except (KeyError, TypeError):
            # Skip malformed entries (non-dict items, missing keys).
            continue
        lookup[str(query_id)] = list(supporting_passage_ids)
    return lookup


def _supporting_passage_ids(
    entry: SuiteEntry, lookup: dict[str, list[str]]
) -> list[str]:
    if entry.source == "dataset" and entry.dataset_ref is not None:
        return list(lookup.get(entry.dataset_ref.question_id, []))
    return []


def _pipeline_label(mode: str, reranker: str) -> str:
    if mode == "hybrid" and reranker != "off":
        return "hybrid+rerank"
    return mode


def _resolve_commit_sha(commit_sha: str | None) -> str:
    if commit_sha is not None:
        return commit_sha
    try:
        return resolve_commit_sha()
    except RuntimeError:
        return "unknown"


def _mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items)
