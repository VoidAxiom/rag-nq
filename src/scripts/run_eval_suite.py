"""CLI for running a persisted evaluation suite and appending a scoreboard row."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from uuid import uuid4

from app.api.main import _default_generator_factory, _default_retriever_factory
from src.config.settings import Settings
from src.evaluation import eval_suite as suites_mod
from src.evaluation.eval_suite_runner import EvalSuiteRunResult, run_suite
from src.evaluation.scoreboard import add_row


def _resolve_suite(
    arg: str, *, suites_dir: Path
) -> tuple[suites_mod.EvalSuite | None, str | None]:
    direct = suites_mod.load_suite(arg, suites_dir)
    if direct is not None:
        return direct, None
    all_suites = suites_mod.list_suites(suites_dir)
    lower = arg.lower()
    matches = [suite for suite in all_suites if suite.name.lower() == lower]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        ids = ", ".join(suite.id for suite in matches)
        return None, f"ambiguous suite name {arg!r}; matches: {ids}"
    return None, f"no suite found with id or name {arg!r}"


def _print_summary(
    result: EvalSuiteRunResult, suite: suites_mod.EvalSuite, run_id: str
) -> None:
    print(f"Suite: {suite.name} ({suite.id})  config={suite.config.model_dump()}")
    print(f"Entries: {len(result.per_entry)}")
    print()
    print(
        f"{'#':>3}  {'entry_id':<14}  {'em':>4}  {'f1':>4}  "
        f"{'r@5':>4}  {'lat_ms':>6}  question"
    )
    for i, entry in enumerate(result.per_entry, 1):
        em = f"{entry.em:.2f}" if entry.em is not None else "  -"
        f1 = f"{entry.f1:.2f}" if entry.f1 is not None else "  -"
        r5 = f"{entry.recall_at_5:.2f}" if entry.recall_at_5 is not None else "  -"
        print(
            f"{i:>3}  {entry.entry_id[:14]:<14}  {em:>4}  {f1:>4}  "
            f"{r5:>4}  {entry.latency_ms:>6.0f}  {entry.question[:60]}"
        )
    print()
    print("Aggregate:")
    rm = result.row.retriever_metrics
    print(
        f"  retriever:  r@1={rm.recall_at_1:.2f}  r@5={rm.recall_at_5:.2f}  "
        f"r@10={rm.recall_at_10:.2f}  mrr@10={rm.mrr_at_10:.2f}  "
        f"ndcg@10={rm.ndcg_at_10:.2f}"
    )
    if result.row.answer_metrics is not None:
        am = result.row.answer_metrics
        contributing = sum(1 for entry in result.per_entry if entry.em is not None)
        print(
            f"  answer:     em={am.em:.2f}  f1={am.f1:.2f}  "
            f"joint_f1={am.joint_f1:.2f}  "
            f"(over {contributing}/{len(result.per_entry)} entries)"
        )
    else:
        print("  answer:     (no entries with gold answers + answer)")
    lm = result.row.latency_ms
    print(f"  latency:    p50={lm.p50}ms  p95={lm.p95}ms")
    print(f"  pipeline={result.row.pipeline}   models={result.row.models.model_dump()}")
    print(f"Wrote scoreboard row id={run_id} launched_via=cli")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_eval_suite")
    parser.add_argument("--suite", required=True)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    settings = Settings.from_env()
    if args.output_dir is not None:
        settings = settings.model_copy(update={"output_dir": args.output_dir})
    suites_dir = settings.output_dir / "eval_suites"
    suite, err = _resolve_suite(args.suite, suites_dir=suites_dir)
    if suite is None:
        print(err, file=sys.stderr)
        return 1
    run_id = uuid4().hex
    try:
        result = run_suite(
            suite,
            app_settings=settings,
            retriever_factory=_default_retriever_factory,
            generator_factory=_default_generator_factory,
            launched_via="cli",
            run_id=run_id,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    add_row(result.row, settings.output_dir / "scoreboard.json")
    _print_summary(result, suite, run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
