"""CLI: build per-benchmark multihop passage artifacts and indexes."""

from __future__ import annotations

import argparse
import logging
import uuid
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from src.config.settings import Settings
from src.ingestion.models import IndexBuildManifest, IndexChunk, Passage
from src.ingestion.multihop_loader import MultihopBenchmark, load_multihop
from src.ingestion.passage_store import PassageStore
from src.observability.logging_setup import get_stage_logger, setup_logging
from src.retrieval.dense_index import DenseIndexer
from src.retrieval.sparse_qdrant import SparseQdrantIndexer

LOGGER = get_stage_logger(__name__)

_ANOMALY_RATIO_MIN: float = 0.5
_ANOMALY_RATIO_MAX: float = 2.0
_MULTIHOP_DATASET_SPLIT: str = "validation"
_MULTIHOP_POINT_ID_NAMESPACE: uuid.UUID = uuid.UUID("0193b3a6-7c5e-7d3b-9b6e-3c2b1a4f7e91")
_DATASET_CHOICES: tuple[str, ...] = tuple(benchmark.value for benchmark in MultihopBenchmark)


@dataclass(slots=True, frozen=True)
class _CliArgs:
    dataset: str
    dry_run: bool
    min_available_ram_gb: float
    force: bool
    sample_size: int | None


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("--sample-size must be greater than zero.")
    return parsed


def _parse_args(argv: Sequence[str] | None = None) -> _CliArgs:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, choices=_DATASET_CHOICES)
    parser.add_argument(
        "--sample-size",
        type=_positive_int,
        default=None,
        help=(
            "Cap ingestion to passages from first N source rows that emit passages "
            "(deterministic passage-prefix)."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write artifacts and manifest without building dense or sparse indexes.",
    )
    parser.add_argument(
        "--min-available-ram-gb",
        type=float,
        default=20.0,
        help="Minimum available RAM in GiB required at startup.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass the startup memory-budget guard.",
    )
    namespace = parser.parse_args(argv)
    return _CliArgs(
        dataset=namespace.dataset,
        dry_run=namespace.dry_run,
        min_available_ram_gb=namespace.min_available_ram_gb,
        force=namespace.force,
        sample_size=namespace.sample_size,
    )


def _check_memory_budget(min_gb: float, force: bool) -> None:
    if force:
        LOGGER.info("memory_guard bypassed (--force)", extra={"stage": "memory_guard"})
        return

    import psutil

    available_gib = psutil.virtual_memory().available / (1024**3)
    if available_gib < min_gb:
        message = (
            f"memory_guard abort available_gib={available_gib:.2f} "
            f"min={min_gb:.2f}; free memory or pass --force to bypass"
        )
        LOGGER.error(message, extra={"stage": "memory_guard"})
        raise SystemExit(message)

    LOGGER.info(
        "memory_guard pass available_gib=%.2f min=%.2f",
        available_gib,
        min_gb,
        extra={"stage": "memory_guard"},
    )


def _multihop_point_id(passage_id: str) -> str:
    return str(uuid.uuid5(_MULTIHOP_POINT_ID_NAMESPACE, passage_id))


def _passage_to_index_chunk(passage: Passage, ordinal: int) -> IndexChunk:
    """Convert one loader passage into the chunk shape consumed by indexers."""

    return IndexChunk(
        chunk_id=_multihop_point_id(passage.passage_id),
        group_id=passage.passage_id,
        text=passage.text,
        context_text=passage.text,
        source_row_ordinal=ordinal,
        start_candidate_idx=0,
        end_candidate_idx=0,
        passage_types=[],
        title=passage.title,
        source=passage.source,
        question=passage.question,
        document_url=passage.document_url,
        parent_candidate_idx=None,
        chunk_kind="chunk",
        token_count=0,
        context_token_count=0,
        long_answers=list(passage.long_answers),
    )


def _write_index_chunks_jsonl(passages: Iterable[Passage], path: Path) -> int:
    """Stream loader passages to disk as one ``IndexChunk`` JSON object per line."""

    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for ordinal, passage in enumerate(passages):
            handle.write(_passage_to_index_chunk(passage, ordinal).model_dump_json())
            handle.write("\n")
            count = ordinal + 1
    return count


def _cap_passages_by_row(passages: Iterator[Passage], max_rows: int) -> Iterator[Passage]:
    """Yield every passage whose ``passage_id`` row-key falls within the prefix.

    The prefix is the first ``max_rows`` distinct row-keys observed in the input
    stream. Sampling happens at the passage-emission boundary (downstream of any
    loader-side filtering of empty/whitespace paragraphs), not at the HF
    source-row boundary. Deterministic: same loader output means same bytewise
    emitted passages for a fixed ``max_rows``. Passage IDs must follow the
    ``{prefix}-{row}-{para}`` multihop format so this wrapper can derive the
    row-key safely. The underlying iterator is advanced at most one passage past
    the cap (to discover the (N+1)th row-key); no subsequent passages are
    consumed.
    """

    seen_row_keys: set[str] = set()
    for passage in passages:
        if passage.passage_id.count("-") < 2:
            raise ValueError(
                f"passage_id={passage.passage_id!r} does not match the "
                "expected '{prefix}-{row}-{para}' multihop format; "
                "_cap_passages_by_row cannot derive a row-key safely."
            )
        row_key = passage.passage_id.rsplit("-", 1)[0]
        if row_key not in seen_row_keys:
            if len(seen_row_keys) >= max_rows:
                return
            seen_row_keys.add(row_key)
        yield passage


def _passage_ratio(actual: int, expected: int) -> float:
    if expected <= 0:
        raise ValueError("expected_passage_count must be greater than zero.")
    return actual / expected


def _is_anomalous_ratio(ratio: float) -> bool:
    return ratio < _ANOMALY_RATIO_MIN or ratio > _ANOMALY_RATIO_MAX


def run_ingest_multihop(
    benchmark: MultihopBenchmark,
    *,
    dry_run: bool = False,
    sample_size: int | None = None,
) -> IndexBuildManifest:
    """Run the multihop artifact, dense, sparse, reconcile, and manifest pipeline."""

    loader = load_multihop(benchmark)
    LOGGER.info(
        "benchmark=%s loader=%s expected_count=%s",
        benchmark.value,
        loader.__class__.__name__,
        loader.expected_passage_count,
        extra={"stage": "load_multihop"},
    )
    if sample_size is not None:
        LOGGER.info("sample_size=%s", sample_size, extra={"stage": "sample"})

    settings = Settings.from_env()
    per_benchmark_settings = settings.model_copy(
        update={
            "qdrant_collection": loader.expected_collection_name,
            "sparse_pass1_file": f"sparse_pass1__{benchmark.value}.json",
            "sparse_manifest_file": f"sparse_index_manifest__{benchmark.value}.json",
        }
    )

    jsonl_path = PassageStore.multihop_jsonl_path(benchmark, per_benchmark_settings.output_dir)
    if sample_size is None:
        passages_source = loader.iter_passages()
    else:
        passages_source = _cap_passages_by_row(loader.iter_passages(), sample_size)
    passage_count = _write_index_chunks_jsonl(passages_source, jsonl_path)
    LOGGER.info(
        "passages_written=%s path=%s",
        passage_count,
        jsonl_path.resolve(),
        extra={"stage": "passage_yield"},
    )

    if not dry_run:
        dense_result = DenseIndexer(settings=per_benchmark_settings).build_from_jsonl_streaming(
            jsonl_path,
            lines_per_batch=per_benchmark_settings.dense_read_batch_lines,
        )
        LOGGER.info(
            "collection=%s points=%s",
            per_benchmark_settings.qdrant_collection,
            dense_result.vector_count,
            extra={"stage": "dense_index"},
        )

        sparse_result = SparseQdrantIndexer(settings=per_benchmark_settings).build_from_jsonl(
            jsonl_path
        )
        LOGGER.info(
            "collection=%s vocab=%s",
            per_benchmark_settings.qdrant_collection,
            sparse_result.vocabulary_size,
            extra={"stage": "sparse_index"},
        )

    if sample_size is None:
        ratio = _passage_ratio(passage_count, loader.expected_passage_count)
        LOGGER.info(
            "actual_passage_count=%s expected=%s ratio=%.4f",
            passage_count,
            loader.expected_passage_count,
            ratio,
            extra={"stage": "reconcile"},
        )
        if _is_anomalous_ratio(ratio):
            LOGGER.warning(
                "anomaly=true reason=ratio_out_of_band ratio=%.4f",
                ratio,
                extra={"stage": "reconcile"},
            )
    else:
        LOGGER.info(
            "mode=sampled actual_passage_count=%s sample_size=%s",
            passage_count,
            sample_size,
            extra={"stage": "reconcile"},
        )

    manifest = IndexBuildManifest(
        dataset_name=loader.dataset_name,
        dataset_split=_MULTIHOP_DATASET_SPLIT,
        embedder_name=per_benchmark_settings.embedder_name,
        passage_count=passage_count,
        qdrant_collection=loader.expected_collection_name,
        sparse_index_path=str(per_benchmark_settings.sparse_manifest_path),
        chunk_count=None,
        chunk_artifact_path=str(jsonl_path),
        dense_indexed_from="artifact" if not dry_run else None,
    )
    manifest_path = settings.output_dir / f"multihop_manifest__{benchmark.value}.json"
    PassageStore.write_manifest(manifest=manifest, path=manifest_path)
    return manifest


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entrypoint."""

    args = _parse_args(argv)
    setup_logging(level=logging.INFO)
    _check_memory_budget(args.min_available_ram_gb, args.force)
    benchmark = MultihopBenchmark(args.dataset)
    run_ingest_multihop(benchmark, dry_run=args.dry_run, sample_size=args.sample_size)


if __name__ == "__main__":
    main()
