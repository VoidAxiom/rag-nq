"""P0-F: NQ-dev canonical baseline runner mapping retrieval eval -> scoreboard row."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from src.config.settings import Settings
from src.evaluation.retrieval_eval import (
    RelevanceContract,
    RetrievalEvalReport,
    run_retrieval_evaluation,
)
from src.evaluation.scoreboard import (
    LatencyMs,
    ModelSet,
    RetrieverMetrics,
    ScoreboardRow,
    add_row,
)
from src.retrieval.qdrant_retrievers import Mode


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
    return proc.stdout.strip()


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
) -> tuple[RetrievalEvalReport, ScoreboardRow]:
    if not {1, 5, 10}.issubset(k_values):
        raise ValueError(f"k_values must include 1, 5, 10 (got {k_values})")
    if not modes:
        raise ValueError("modes must be a non-empty list")
    resolved_primary_mode = primary_mode or modes[0]
    if resolved_primary_mode not in modes:
        raise ValueError(f"primary_mode {resolved_primary_mode!r} not in modes={modes}")

    start = time.perf_counter()
    report = run_retrieval_evaluation(
        settings,
        k_values=k_values,
        modes=modes,
        relevance_contract=relevance_contract,
        max_queries=max_queries,
        output_path=output_path,
    )
    elapsed_s = time.perf_counter() - start

    query_count = report.run_config.query_count
    if query_count == 0:
        mean_ms = 0
    else:
        mean_ms = int(round((elapsed_s * 1000.0) / query_count))
    latency_ms = LatencyMs(p50=mean_ms, p95=mean_ms)
    models = ModelSet(
        embedder=settings.embedder_name,
        reranker=settings.rerank_model_name,
        reasoning_llm=None,
        verifier=None,
    )
    sha = commit_sha if commit_sha is not None else resolve_commit_sha()
    latency_note = (
        f"latency=mean-per-query approximation ({mean_ms} ms over {query_count} queries, "
        f"total {elapsed_s:.3f}s); per-query histogram not captured in this baseline runner."
    )
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
