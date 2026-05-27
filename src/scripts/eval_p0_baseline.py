"""CLI: run the P0-F NQ-dev canonical baseline -> eval report + scoreboard row."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.config.settings import Settings
from src.evaluation.baseline_runner import run_baseline
from src.evaluation.scoreboard import SCOREBOARD_PATH
from src.ingestion.chunk_raw import load_chunk_manifest
from src.observability.logging_setup import setup_logging


def _quiet_dependency_logs() -> dict[str, int]:
    prior_levels: dict[str, int] = {}
    for logger_name in (
        "httpx",
        "httpcore",
        "huggingface_hub",
        "sentence_transformers",
        "transformers",
        "qdrant_client",
        "src.retrieval.qdrant_retrievers",
    ):
        logger = logging.getLogger(logger_name)
        prior_levels[logger_name] = logger.level
        logger.setLevel(logging.WARNING)
    return prior_levels


def _restore_logger_levels(levels: dict[str, int]) -> None:
    for logger_name, level in levels.items():
        logging.getLogger(logger_name).setLevel(level)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return parsed


def main() -> None:
    setup_logging()
    saved_levels = _quiet_dependency_logs()
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument(
            "--max-queries",
            type=_positive_int,
            required=True,
            help="Maximum number of NQ-dev eval queries to run.",
        )
        parser.add_argument(
            "--output",
            type=Path,
            required=True,
            help="Output JSON path for the retrieval eval report.",
        )
        parser.add_argument(
            "--scoreboard",
            type=Path,
            default=SCOREBOARD_PATH,
            help="Scoreboard JSON path to append.",
        )
        parser.add_argument(
            "--no-append-scoreboard",
            action="store_true",
            default=False,
            help="Skip appending a scoreboard row.",
        )
        parser.add_argument(
            "--latency-sample-size",
            type=_non_negative_int,
            default=50,
            help=(
                "Maximum number of timed eval queries for p50/p95 capture; one "
                "additional case is consumed as a warm-up (discarded), so actual "
                "timed sample is at most min(N, query_count - 1)."
            ),
        )
        parser.add_argument("--phase", default="P0")
        parser.add_argument("--pipeline", default="hybrid+rerank")
        parser.add_argument("--benchmark", default="nq-retrieval")
        parser.add_argument(
            "--split",
            default="dev",
            help=(
                "Dataset split label for the scoreboard row. Must equal "
                "the persisted chunk manifest split (the split the corpus index "
                "was built from). "
                "Default 'dev' matches the canonical NQ-dev baseline run; "
                "set RAG_DATASET_SPLIT before rebuilding artifacts for another split."
            ),
        )
        args = parser.parse_args()

        settings = Settings.from_env()
        chunk_manifest = load_chunk_manifest(settings.chunk_manifest_path)
        if chunk_manifest is None:
            parser.error(
                f"No chunk manifest found at {settings.chunk_manifest_path}; "
                f"run `uv run python -m src.scripts.build_indexes` first so the "
                f"corpus split can be validated against the scoreboard row label."
            )

        persisted_split = chunk_manifest.dataset_split
        if args.split != persisted_split:
            parser.error(
                f"--split={args.split!r} does not match the persisted chunk manifest "
                f"split={persisted_split!r} at {settings.chunk_manifest_path}. "
                f"The corpus indexed at {settings.index_chunks_path} was built from "
                f"the {persisted_split!r} split. Either re-build the index against "
                f"the {args.split!r} split (e.g. RAG_DATASET_SPLIT={args.split} "
                f"uv run python -m src.scripts.build_indexes), or pass "
                f"--split={persisted_split} to label the row truthfully."
            )
        expected_rerank_by_pipeline = {
            "hybrid+rerank": True,
            "hybrid": False,
        }
        expected_rerank = expected_rerank_by_pipeline.get(args.pipeline)
        if expected_rerank is not None and expected_rerank != settings.rerank_enabled:
            parser.error(
                f"--pipeline={args.pipeline!r} requires "
                f"settings.rerank_enabled={expected_rerank!r}, but "
                f"settings.rerank_enabled={settings.rerank_enabled!r}. The "
                f"HybridQdrantRetriever's reranker stage runs iff "
                f"rerank_enabled is True; the scoreboard pipeline label must "
                f"truthfully describe whether rerank ran. To resolve: set "
                f"RAG_RERANK_ENABLED={'true' if expected_rerank else 'false'} "
                f"(or unset it to use the default True), or pass "
                f"--pipeline={'hybrid+rerank' if settings.rerank_enabled else 'hybrid'} "
                f"to label the row truthfully for the current rerank setting."
            )
        if settings.dataset_split != persisted_split:
            print(
                f"WARNING: settings.dataset_split={settings.dataset_split!r} differs "
                f"from persisted chunk manifest split={persisted_split!r}; the "
                f"corpus on disk (and the scoreboard row label) reflects "
                f"{persisted_split!r}.",
                file=sys.stderr,
            )
        print(f"Validated split={args.split} matches persisted chunk manifest split")
        report, row = run_baseline(
            settings,
            max_queries=args.max_queries,
            output_path=args.output,
            scoreboard_path=None if args.no_append_scoreboard else args.scoreboard,
            phase=args.phase,
            pipeline=args.pipeline,
            benchmark=args.benchmark,
            split=args.split,
            modes=["hybrid"],
            k_values=[1, 5, 10],
            latency_sample_size=args.latency_sample_size,
        )
        print(
            f"Wrote retrieval eval report to {args.output} "
            f"for {report.run_config.query_count} queries "
            f"(recall@10={row.retriever_metrics.recall_at_10:.4f}, "
            f"mrr@10={row.retriever_metrics.mrr_at_10:.4f}, "
            f"ndcg@10={row.retriever_metrics.ndcg_at_10:.4f})"
        )
        if not args.no_append_scoreboard:
            print(f"Appended scoreboard row at {args.scoreboard}")
    finally:
        _restore_logger_levels(saved_levels)


if __name__ == "__main__":
    main()
