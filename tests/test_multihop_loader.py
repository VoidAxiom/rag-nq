from __future__ import annotations

from pathlib import Path

import pytest

from src.ingestion.multihop_loader import (
    MultihopBenchmark,
    MultihopLoader,
    load_multihop,
)
from src.ingestion.passage_store import PassageStore


def test_multihop_benchmark_enum_has_three_values() -> None:
    assert list(MultihopBenchmark) == [
        MultihopBenchmark.HOTPOTQA,
        MultihopBenchmark.TWOWIKIMHQA,
        MultihopBenchmark.MUSIQUE,
    ]
    assert set([b.value for b in MultihopBenchmark]) == {"hotpotqa", "2wikimhqa", "musique"}


@pytest.mark.parametrize(
    ("benchmark", "expected_name", "expected_collection", "expected_count"),
    [
        (
            MultihopBenchmark.HOTPOTQA,
            "hotpotqa",
            "hotpotqa_passages_qwen3_embed_4b",
            7405,
        ),
        (
            MultihopBenchmark.TWOWIKIMHQA,
            "2wikimhqa",
            "2wikimhqa_passages_qwen3_embed_4b",
            12576,
        ),
        (
            MultihopBenchmark.MUSIQUE,
            "musique",
            "musique_passages_qwen3_embed_4b",
            2417,
        ),
    ],
)
def test_load_multihop_dispatches_to_per_benchmark_stub(
    benchmark: MultihopBenchmark,
    expected_name: str,
    expected_collection: str,
    expected_count: int,
) -> None:
    loader = load_multihop(benchmark)

    assert loader.dataset_name == expected_name
    assert loader.expected_collection_name == expected_collection
    assert loader.expected_eval_count == expected_count


@pytest.mark.parametrize(
    ("benchmark", "expected_token"),
    [
        (MultihopBenchmark.HOTPOTQA, "VOI-PENDING-P1-B"),
        (MultihopBenchmark.TWOWIKIMHQA, "VOI-PENDING-P1-C"),
        (MultihopBenchmark.MUSIQUE, "VOI-PENDING-P1-D"),
    ],
)
def test_stub_iter_passages_raises_with_pending_token(
    benchmark: MultihopBenchmark,
    expected_token: str,
) -> None:
    loader = load_multihop(benchmark)

    with pytest.raises(NotImplementedError) as exc_info:
        next(loader.iter_passages())
    assert expected_token in str(exc_info.value)


def test_load_multihop_returns_loader_implementing_protocol() -> None:
    loader: MultihopLoader = load_multihop(MultihopBenchmark.HOTPOTQA)

    assert isinstance(loader.dataset_name, str) and loader.dataset_name
    assert isinstance(loader.expected_collection_name, str) and loader.expected_collection_name
    assert isinstance(loader.expected_eval_count, int) and loader.expected_eval_count > 0
    assert callable(loader.iter_passages)


def test_load_multihop_rejects_unknown_value() -> None:
    sentinel = object()

    with pytest.raises(ValueError):
        load_multihop(sentinel)


def test_passage_store_multihop_jsonl_path_returns_expected_filename(tmp_path: Path) -> None:
    for benchmark in MultihopBenchmark:
        assert PassageStore.multihop_jsonl_path(benchmark, tmp_path) == (
            tmp_path / f"multihop_passages__{benchmark.value}.jsonl"
        )
