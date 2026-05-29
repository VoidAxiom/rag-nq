"""CLI: curate deterministic evaluation question JSON artifacts."""

from __future__ import annotations

import argparse
import hashlib
import os
import random
from pathlib import Path
from typing import Literal

from pydantic import TypeAdapter

from app.api.schemas import EvalQuestion
from src.config.settings import Settings
from src.evaluation.retrieval_eval import EvalCase, build_eval_cases_from_index_artifact
from src.ingestion.musique_loader import MuSiQueLoader

CuratableBenchmark = Literal["nq", "musique"]

_CURATABLE_BENCHMARKS: frozenset[str] = frozenset({"nq", "musique"})
_EMPTY_BENCHMARKS: frozenset[str] = frozenset({"hotpotqa", "2wikimhqa"})


def curate(
    benchmark: str,
    *,
    sample_size: int = 50,
    seed: int = 0,
    output_dir: Path | None = None,
) -> list[EvalQuestion]:
    """Curate sampled eval questions for one benchmark and persist them as JSON."""

    resolved_benchmark = _curatable_benchmark(benchmark)
    if sample_size <= 0:
        raise ValueError("sample_size must be >= 1.")

    resolved_output_dir = (
        output_dir if output_dir is not None else Settings.from_env().output_dir
    )
    if resolved_benchmark == "nq":
        index_path = _index_artifact_path(resolved_benchmark, resolved_output_dir)
        cases = build_eval_cases_from_index_artifact(index_path, max_queries=None)
    else:
        cases = _build_musique_cases()
    sampled_cases = _sample_cases(cases, sample_size=sample_size, seed=seed)
    questions = [
        _eval_question_from_case(resolved_benchmark, case)
        for case in sorted(sampled_cases, key=lambda item: item.query)
    ]
    _write_questions(
        questions,
        resolved_output_dir / "eval_questions" / f"{resolved_benchmark}.json",
    )
    return questions


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        required=True,
        metavar="{nq,musique}",
        help="Benchmark to curate. Supported: nq, musique.",
    )
    parser.add_argument(
        "--sample-size",
        type=_positive_int,
        default=50,
        help="Number of eval questions to sample.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed used for deterministic sampling.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Artifacts directory containing the benchmark index JSONL.",
    )
    args = parser.parse_args()

    try:
        questions = curate(
            args.benchmark,
            sample_size=args.sample_size,
            seed=args.seed,
            output_dir=args.output_dir,
        )
    except ValueError as exc:
        parser.error(str(exc))
    output_dir = (
        args.output_dir if args.output_dir is not None else Settings.from_env().output_dir
    )
    output_path = output_dir / "eval_questions" / f"{args.benchmark}.json"
    print(f"Wrote {len(questions)} eval questions to {output_path}")


def _curatable_benchmark(benchmark: str) -> CuratableBenchmark:
    if benchmark in _EMPTY_BENCHMARKS:
        raise ValueError(
            f"{benchmark} eval question curation is unavailable because its collection "
            "is empty by design."
        )
    if benchmark not in _CURATABLE_BENCHMARKS:
        raise ValueError("unsupported benchmark; expected one of: nq, musique.")
    if benchmark == "nq":
        return "nq"
    return "musique"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be >= 1")
    return parsed


def _index_artifact_path(_benchmark: Literal["nq"], output_dir: Path) -> Path:
    return Settings(output_dir=output_dir).index_chunks_path


def _build_musique_cases() -> list[EvalCase]:
    loader = MuSiQueLoader()
    cases: list[EvalCase] = []
    for gold in loader.iter_gold_questions():
        cases.append(
            EvalCase(
                query=gold.question,
                answer_texts=list(gold.gold_answers),
                relevant_passage_ids=list(gold.supporting_passage_ids),
            )
        )
    return cases


def _sample_cases(cases: list[EvalCase], *, sample_size: int, seed: int) -> list[EvalCase]:
    if not cases:
        return []
    sample_count = min(sample_size, len(cases))
    rng = random.Random(seed)
    return rng.sample(cases, sample_count)


def _eval_question_from_case(
    benchmark: CuratableBenchmark, case: EvalCase
) -> EvalQuestion:
    digest = hashlib.sha1(case.query.encode("utf-8")).hexdigest()[:12]
    return EvalQuestion(
        query_id=f"{benchmark}-{digest}",
        query=case.query,
        gold_answers=case.answer_texts,
        supporting_passage_ids=case.relevant_passage_ids,
        notes=None,
    )


def _write_questions(questions: list[EvalQuestion], path: Path) -> None:
    adapter = TypeAdapter(list[EvalQuestion])
    payload = adapter.dump_json(questions, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_bytes(payload)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    adapter.validate_json(path.read_bytes())


if __name__ == "__main__":
    main()
