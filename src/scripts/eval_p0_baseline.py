"""CLI: run the P0-F NQ-dev canonical baseline -> eval report + scoreboard row."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from src.config.settings import Settings
from src.evaluation.baseline_runner import run_baseline
from src.evaluation.scoreboard import SCOREBOARD_PATH
from src.observability.logging_setup import setup_logging


def _quiet_dependency_logs() -> None:
    for logger_name in (
        "httpx",
        "httpcore",
        "huggingface_hub",
        "sentence_transformers",
        "transformers",
        "qdrant_client",
        "src.retrieval.qdrant_retrievers",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def main() -> None:
    setup_logging()
    _quiet_dependency_logs()
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
    parser.add_argument("--phase", default="P0")
    parser.add_argument("--pipeline", default="hybrid+rerank")
    parser.add_argument("--benchmark", default="nq-retrieval")
    parser.add_argument("--split", default="dev")
    args = parser.parse_args()

    settings = Settings.from_env()
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


if __name__ == "__main__":
    main()
