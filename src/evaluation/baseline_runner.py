"""P0-F: NQ-dev canonical baseline runner mapping retrieval eval -> scoreboard row."""

from __future__ import annotations

import logging
import math
import re
import subprocess
import time
from pathlib import Path

from src.config.settings import Settings
from src.evaluation.retrieval_eval import (
    EvalCase,
    RelevanceContract,
    RetrievalEvalReport,
    build_eval_cases_from_index_artifact,
    run_retrieval_evaluation,
)
from src.evaluation.scoreboard import (
    LatencyMs,
    ModelSet,
    RetrieverMetrics,
    ScoreboardRow,
    add_row,
)
from src.retrieval.qdrant_retrievers import Mode, QdrantModeRetriever


def build_scoreboard_row_from_eval(
    report: RetrievalEvalReport,
    *,
    phase: str,
    pipeline: str,
    benchmark: str,
    split: str,
    latency_ms: LatencyMs,
    commit_sha: str,
    models: ModelSet,
    primary_mode: Mode,
    notes: str | None = None,
) -> ScoreboardRow:
    if primary_mode not in report.modes:
        raise KeyError(
            f"primary_mode {primary_mode!r} not in eval report modes={sorted(report.modes)}"
        )
    summary = report.modes[primary_mode]
    required_cutoffs = {"1", "5", "10"}
    if not required_cutoffs.issubset(summary.metrics_by_k):
        raise ValueError(
            f"metrics_by_k for mode {primary_mode!r} missing required cutoffs; "
            f"need {{1,5,10}}, got {sorted(summary.metrics_by_k)}"
        )
    metrics_by_k = summary.metrics_by_k
    retriever_metrics = RetrieverMetrics(
        recall_at_1=metrics_by_k["1"].recall_at_k,
        recall_at_5=metrics_by_k["5"].recall_at_k,
        recall_at_10=metrics_by_k["10"].recall_at_k,
        mrr_at_10=metrics_by_k["10"].mrr_at_k,
        ndcg_at_10=metrics_by_k["10"].ndcg_at_k,
    )
    return ScoreboardRow(
        phase=phase,
        pipeline=pipeline,
        benchmark=benchmark,
        split=split,
        retriever_metrics=retriever_metrics,
        answer_metrics=None,
        quality_metrics=None,
        latency_ms=latency_ms,
        models=models,
        commit_sha=commit_sha,
        notes=notes,
    )


def resolve_repo_root(start: Path | None = None) -> Path:
    start_path = (start or Path(__file__).resolve()).resolve()
    first_candidate = start_path if start_path.is_dir() else start_path.parent
    for ancestor in (first_candidate, *first_candidate.parents):
        if (ancestor / ".git").exists():
            return ancestor
    raise RuntimeError(f"could not resolve repo root from {start_path}")


def resolve_commit_sha(repo_root: Path | None = None) -> str:
    resolved_repo_root = repo_root or resolve_repo_root()
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=resolved_repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RuntimeError(f"failed to resolve commit sha: {e}") from e
    sha = proc.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise RuntimeError(
            "git rev-parse HEAD returned unexpected output "
            f"(not a 40-char hex sha): {sha!r}"
        )
    return sha


def _measure_latency_sample_ms(
    settings: Settings,
    *,
    report: RetrievalEvalReport,
    primary_mode: Mode,
    top_k: int,
    max_queries: int,
    latency_sample_size: int,
) -> list[float]:
    """Return timed retrieval latencies from a prefix sample.

    latency_sample_size: Upper bound on number of timed retrievals for p50/p95
        capture. One additional case is consumed as a warm-up call (whose timing
        is discarded), so the actual timed sample size is at most
        min(latency_sample_size, query_count - 1). If query_count <= 1 or
        latency_sample_size == 0, no latency capture is performed
        (returns []).
    """
    case_limit = min(
        latency_sample_size + 1,
        max_queries + 1,
        report.run_config.query_count,
    )
    if latency_sample_size <= 0 or case_limit < 2:
        return []

    cases = build_eval_cases_from_index_artifact(
        Path(report.run_config.corpus_path),
        max_queries=case_limit,
    )
    return _time_retrieval_cases_ms(
        settings,
        cases=cases,
        primary_mode=primary_mode,
        top_k=top_k,
    )


def _time_retrieval_cases_ms(
    settings: Settings,
    *,
    cases: list[EvalCase],
    primary_mode: Mode,
    top_k: int,
) -> list[float]:
    if not cases:
        return []

    retriever = QdrantModeRetriever(settings=settings, mode=primary_mode)
    # Warm-up: first retrieve() of a fresh retriever lazily loads
    # embedder/sub-retrievers -- bias would inflate p95. Discard.
    retriever.retrieve(cases[0].query, top_k=top_k)

    latencies_ms: list[float] = []
    for case in cases[1:]:
        started_at = time.perf_counter()
        retriever.retrieve(case.query, top_k=top_k)
        latencies_ms.append((time.perf_counter() - started_at) * 1000.0)
    return latencies_ms


def _latency_percentiles_ms(latencies_ms: list[float]) -> LatencyMs:
    if not latencies_ms:
        return LatencyMs(p50=0, p95=0)
    sorted_latencies = sorted(latencies_ms)
    latency_count = len(sorted_latencies)
    p50_index = max(0, min(latency_count - 1, math.ceil(0.50 * latency_count) - 1))
    p95_index = max(0, min(latency_count - 1, math.ceil(0.95 * latency_count) - 1))
    p50 = sorted_latencies[p50_index]
    p95 = sorted_latencies[p95_index]
    return LatencyMs(p50=int(round(p50)), p95=int(round(p95)))


def run_baseline(
    settings: Settings,
    *,
    max_queries: int,
    output_path: Path,
    scoreboard_path: Path | None,
    phase: str,
    pipeline: str,
    benchmark: str,
    split: str,
    modes: list[Mode],
    k_values: list[int],
    primary_mode: Mode | None = None,
    relevance_contract: RelevanceContract = "answer_overlap",
    notes: str | None = None,
    commit_sha: str | None = None,
    latency_sample_size: int = 50,
) -> tuple[RetrievalEvalReport, ScoreboardRow]:
    """Run retrieval evaluation and append a scoreboard row.

    latency_sample_size: Upper bound on number of timed retrievals for p50/p95
        capture. One additional case is consumed as a warm-up call (whose timing
        is discarded), so the actual timed sample size is at most
        min(latency_sample_size, query_count - 1). If query_count <= 1 or
        latency_sample_size == 0, no latency capture is performed
        (returns p50=p95=0).
    """
    if not {1, 5, 10}.issubset(k_values):
        raise ValueError(f"k_values must include 1, 5, 10 (got {k_values})")
    if not modes:
        raise ValueError("modes must be a non-empty list")
    resolved_primary_mode = primary_mode or modes[0]
    if resolved_primary_mode not in modes:
        raise ValueError(f"primary_mode {resolved_primary_mode!r} not in modes={modes}")
    sha = commit_sha if commit_sha is not None else resolve_commit_sha()

    report = run_retrieval_evaluation(
        settings,
        k_values=k_values,
        modes=modes,
        relevance_contract=relevance_contract,
        max_queries=max_queries,
        output_path=output_path,
    )

    top_k = max(k_values)
    latency_sample_failure: str | None = None
    try:
        latencies_ms = _measure_latency_sample_ms(
            settings,
            report=report,
            primary_mode=resolved_primary_mode,
            top_k=top_k,
            max_queries=max_queries,
            latency_sample_size=latency_sample_size,
        )
        latency_ms = _latency_percentiles_ms(latencies_ms)
    except (RuntimeError, OSError, ConnectionError, KeyError) as exc:
        logging.getLogger(__name__).warning(
            "latency sample failed: %s; falling back to LatencyMs(0,0)",
            exc,
            exc_info=True,
        )
        latencies_ms = []
        latency_ms = LatencyMs(p50=0, p95=0)
        latency_sample_failure = f"latency_sample_failed={exc.__class__.__name__}"
    models = ModelSet(
        embedder=settings.embedder_name,
        reranker=settings.rerank_model_name,
        reasoning_llm=None,
        verifier=None,
    )
    latency_sample_detail = (
        f"timed sample = {len(latencies_ms)} queries after a discarded warm-up call"
        if latencies_ms
        else "no latency capture performed"
    )
    latency_note = (
        f"latency_p50_p95_from_prefix_sample={len(latencies_ms)}_queries "
        f"({latency_sample_detail}; separate timing pass from eval)"
    )
    if latency_sample_failure is not None:
        latency_note = f"{latency_note}; {latency_sample_failure}"
    stripped_notes = (notes or "").strip()
    combined_notes = (
        latency_note if not stripped_notes else f"{stripped_notes}; {latency_note}"
    )
    row = build_scoreboard_row_from_eval(
        report,
        phase=phase,
        pipeline=pipeline,
        benchmark=benchmark,
        split=split,
        latency_ms=latency_ms,
        commit_sha=sha,
        models=models,
        primary_mode=resolved_primary_mode,
        notes=combined_notes,
    )
    if scoreboard_path is not None:
        add_row(row, scoreboard_path)
    return report, row
