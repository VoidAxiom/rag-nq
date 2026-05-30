"""Pure-sync per-question runner for the /api/benchmark/stream endpoint.

Async/SSE/queue orchestration lives in app/api/main.py; this module is
unit-testable without asyncio.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.api.schemas import (
    BenchmarkAdhocQuestion,
    BenchmarkComboSettings,
    BenchmarkQuestionSet,
    BenchmarkSampleQuestion,
    BenchmarkSuiteQuestion,
)
from src.config.settings import Settings
from src.evaluation.eval_suite import EvalSuite
from src.evaluation.per_query_metrics import compute_em, compute_f1
from src.evaluation.retrieval_eval import (
    compute_mrr_at_k,
    compute_ndcg_at_k,
    compute_recall_at_k,
)
from src.models.query_schemas import (
    GroundedAnswer,
    LatencyBreakdown,
    PassageHit,
    RetrievalMetrics,
)
from src.retrieval.qdrant_retrievers import Mode


class _RetrieverP(Protocol):
    last_retrieval_metrics: RetrievalMetrics | None

    def retrieve_with_metrics(
        self, query: str, top_k: int
    ) -> tuple[list[PassageHit], RetrievalMetrics | None]: ...


class _GeneratorP(Protocol):
    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer: ...


@dataclass(frozen=True)
class QuestionInput:
    query: str
    benchmark: str
    gold_answers: tuple[str, ...]
    supporting_passage_ids: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedQuestionSet:
    questions: list[QuestionInput]
    collection_override: str | None
    benchmark: str


@dataclass(frozen=True)
class PerQuestionMetricValues:
    recall_at_1: float | None
    recall_at_5: float | None
    recall_at_10: float | None
    mrr_at_10: float | None
    ndcg_at_10: float | None
    em: float | None
    f1: float | None


@dataclass(frozen=True)
class ComboRunResult:
    combo_id: str
    question_index: int
    query: str
    grounded: GroundedAnswer | None
    retrieved_passages: list[PassageHit]
    metrics: PerQuestionMetricValues
    latency_ms: LatencyBreakdown


def settings_for_combo(base: Settings, combo: BenchmarkComboSettings) -> Settings:
    """Derive an effective Settings from base + combo overrides.

    Mirrors the override layering in `_build_effective_settings` in
    `app/api/main.py` but for the benchmark endpoint's combo schema.
    """
    overrides: dict = {}
    if combo.retrieve_k is not None:
        overrides["retrieve_k"] = combo.retrieve_k
    overrides["rerank_enabled"] = combo.rerank_enabled
    if combo.rerank_model_name == "off":
        overrides["rerank_enabled"] = False
    elif combo.rerank_model_name is not None:
        overrides["rerank_model_name"] = combo.rerank_model_name
    if combo.generation_provider is not None:
        overrides["generation_provider"] = combo.generation_provider
        if combo.generation_provider == "openai":
            overrides["generation_model_name"] = "gpt-4o"
            overrides["generation_api_key_env"] = "RAG_OPENAI_API_KEY"
            overrides["generation_api_url"] = None
    if combo.generation_model_name is not None:
        overrides["generation_model_name"] = combo.generation_model_name
    return base.model_copy(update=overrides)


def run_single_question(
    *,
    combo: BenchmarkComboSettings,
    settings: Settings,
    question: QuestionInput,
    question_index: int,
    retriever_factory: Callable[[Settings, Mode], _RetrieverP],
    generator_factory: Callable[[Settings], _GeneratorP],
) -> ComboRunResult:
    """Run a single combo+question through retrieve(+generate); pure sync."""

    retrieval_started_at = time.perf_counter()
    retriever = retriever_factory(settings, combo.mode)
    scoring_top_k = max(combo.top_k, 10)
    hits, raw_metrics = retriever.retrieve_with_metrics(question.query, top_k=scoring_top_k)
    retrieval_wall_ms = (time.perf_counter() - retrieval_started_at) * 1000.0
    retrieval_metrics = raw_metrics or RetrievalMetrics()
    retrieval_ms, rerank_ms = _retrieval_latency_ms(retrieval_metrics, retrieval_wall_ms)

    generation_hits = hits[: combo.top_k]
    grounded: GroundedAnswer | None = None
    generation_ms = 0.0
    if combo.generation_provider is not None:
        generation_started_at = time.perf_counter()
        generator = generator_factory(settings)
        grounded = generator.generate(question.query, generation_hits)
        generation_ms = (time.perf_counter() - generation_started_at) * 1000.0

    latency = LatencyBreakdown(
        retrieval_ms=retrieval_ms,
        rerank_ms=rerank_ms,
        generation_ms=generation_ms,
        total_ms=retrieval_ms + rerank_ms + generation_ms,
    )
    metrics = _compute_per_question_metrics(question, hits, grounded)

    return ComboRunResult(
        combo_id=combo.id,
        question_index=question_index,
        query=question.query,
        grounded=grounded,
        retrieved_passages=generation_hits,
        metrics=metrics,
        latency_ms=latency,
    )


def compute_running_aggregates(results: list[ComboRunResult]) -> dict[str, float | None]:
    """Return a flat dict of `<metric>_mean` over the completed subset.

    For each metric (recall_at_1/5/10, mrr_at_10, ndcg_at_10, em, f1):
    mean over the subset where the per-question value is non-null; null
    if zero non-null values.
    Latency fields (retrieval_ms, rerank_ms, generation_ms, total_ms):
    mean over all results; null if results is empty.
    """
    metric_fields = (
        "recall_at_1",
        "recall_at_5",
        "recall_at_10",
        "mrr_at_10",
        "ndcg_at_10",
        "em",
        "f1",
    )
    out: dict[str, float | None] = {}
    for field in metric_fields:
        values = [getattr(r.metrics, field) for r in results]
        non_null = [v for v in values if v is not None]
        out[f"{field}_mean"] = sum(non_null) / len(non_null) if non_null else None
    if results:
        for lat_field in ("retrieval_ms", "rerank_ms", "generation_ms", "total_ms"):
            values = [getattr(r.latency_ms, lat_field) for r in results]
            out[f"{lat_field}_mean"] = sum(values) / len(values)
    else:
        for lat_field in ("retrieval_ms", "rerank_ms", "generation_ms", "total_ms"):
            out[f"{lat_field}_mean"] = None
    return out


def resolve_questions(
    qset: BenchmarkQuestionSet,
    *,
    suite_loader: Callable[[str], EvalSuite | None],
    eval_questions_loader: Callable[[str], list[QuestionInput]],
) -> ResolvedQuestionSet:
    """Resolve the request's question_set into a concrete list.

    Raises ValueError if the suite/sample lookup is unsatisfiable; the
    handler converts this into an SSE `error` event (NOT a 4xx).
    """
    if isinstance(qset, BenchmarkAdhocQuestion):
        return ResolvedQuestionSet(
            questions=[
                QuestionInput(
                    query=qset.query,
                    benchmark=qset.benchmark,
                    gold_answers=tuple(qset.gold_answers),
                    supporting_passage_ids=tuple(qset.supporting_passage_ids),
                )
            ],
            collection_override=None,
            benchmark=qset.benchmark,
        )
    if isinstance(qset, BenchmarkSuiteQuestion):
        suite = suite_loader(qset.suite_id)
        if suite is None:
            raise ValueError(f"suite {qset.suite_id!r} not found")
        benchmark = suite.config.benchmark
        return ResolvedQuestionSet(
            questions=[
                QuestionInput(
                    query=entry.question,
                    benchmark=benchmark,
                    gold_answers=tuple(entry.gold_answers),
                    supporting_passage_ids=(),
                )
                for entry in suite.entries
            ],
            collection_override=suite.config.collection,
            benchmark=benchmark,
        )
    if isinstance(qset, BenchmarkSampleQuestion):
        questions = eval_questions_loader(qset.benchmark)
        if not questions:
            raise ValueError(f"no eval_questions available for benchmark {qset.benchmark!r}")
        if qset.strategy == "first":
            return ResolvedQuestionSet(
                questions=questions[: qset.size],
                collection_override=None,
                benchmark=qset.benchmark,
            )
        rng = random.Random(qset.seed)
        return ResolvedQuestionSet(
            questions=rng.sample(questions, min(qset.size, len(questions))),
            collection_override=None,
            benchmark=qset.benchmark,
        )
    raise ValueError(f"unsupported question_set kind: {type(qset).__name__}")


def load_eval_questions(benchmark: str, *, eval_questions_dir: Path) -> list[QuestionInput]:
    """Load curated eval questions for `benchmark` from the on-disk JSON.

    Mirrors the source used by `GET /api/eval_questions/{benchmark}`.
    Returns an empty list if the file is missing.
    """
    path = eval_questions_dir / f"{benchmark}.json"
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: list[QuestionInput] = []
    for item in raw:
        try:
            out.append(
                QuestionInput(
                    query=item["query"],
                    benchmark=benchmark,
                    gold_answers=tuple(item.get("gold_answers") or []),
                    supporting_passage_ids=tuple(item.get("supporting_passage_ids") or []),
                )
            )
        except (KeyError, TypeError):
            continue
    return out


def _compute_per_question_metrics(
    question: QuestionInput,
    hits: list[PassageHit],
    grounded: GroundedAnswer | None,
) -> PerQuestionMetricValues:
    if question.supporting_passage_ids:
        retrieved_ids = [hit.point_id for hit in hits]
        relevant_ids = set(question.supporting_passage_ids)
        recall_at_1 = compute_recall_at_k(retrieved_ids, relevant_ids, k=1)
        recall_at_5 = compute_recall_at_k(retrieved_ids, relevant_ids, k=5)
        recall_at_10 = compute_recall_at_k(retrieved_ids, relevant_ids, k=10)
        mrr_at_10 = compute_mrr_at_k(retrieved_ids, relevant_ids, k=10)
        ndcg_at_10 = compute_ndcg_at_k(retrieved_ids, relevant_ids, k=10)
    else:
        recall_at_1 = recall_at_5 = recall_at_10 = None
        mrr_at_10 = ndcg_at_10 = None

    if question.gold_answers and grounded is not None and not grounded.abstained:
        em = compute_em(grounded.answer, list(question.gold_answers))
        f1 = compute_f1(grounded.answer, list(question.gold_answers))
    else:
        em = None
        f1 = None

    return PerQuestionMetricValues(
        recall_at_1=recall_at_1,
        recall_at_5=recall_at_5,
        recall_at_10=recall_at_10,
        mrr_at_10=mrr_at_10,
        ndcg_at_10=ndcg_at_10,
        em=em,
        f1=f1,
    )


def _retrieval_latency_ms(metrics: RetrievalMetrics, fallback_ms: float) -> tuple[float, float]:
    """Same split as app/api/main.py:_retrieval_latency_ms."""
    timings = metrics.timings
    if timings is None:
        return fallback_ms, 0.0
    rerank_ms = timings.rerank_seconds * 1000.0
    retrieval_ms = (
        timings.retrieve_seconds + timings.fusion_seconds + timings.dedupe_seconds
    ) * 1000.0
    if retrieval_ms == 0.0 and timings.total_seconds > 0.0:
        retrieval_ms = max((timings.total_seconds * 1000.0) - rerank_ms, 0.0)
    return retrieval_ms, rerank_ms
