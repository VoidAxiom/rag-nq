"""Multihop benchmark loader scaffold."""

from __future__ import annotations

from collections.abc import Iterator
from enum import Enum
from typing import Protocol

from src.ingestion.hotpotqa_loader import HotpotqaLoader
from src.ingestion.models import Passage


class MultihopBenchmark(Enum):
    """Supported multihop benchmark identifiers."""

    HOTPOTQA = "hotpotqa"
    TWOWIKIMHQA = "2wikimhqa"
    MUSIQUE = "musique"


class MultihopLoader(Protocol):
    """Public multihop benchmark loader protocol."""

    @property
    def dataset_name(self) -> str:
        """Return the canonical benchmark dataset name."""

    @property
    def expected_collection_name(self) -> str:
        """Return the expected Qdrant collection name."""

    @property
    def expected_passage_count(self) -> int:
        """APPROXIMATE published passage count for the benchmark's corpus (per docs/PLAN.md §3). Used by P1-B/C/D ingest scripts as a downstream sanity-check sentinel (assert 0.5 * expected <= actual <= 2 * expected after ingest completes). NOT a question count."""  # noqa: E501

    def iter_passages(self) -> Iterator[Passage]:
        """Iterate normalized benchmark passages."""


class _TwoWikiMhqaStubLoader:
    """Placeholder loader for 2WikiMultihopQA."""

    _DATASET_NAME = "2wikimhqa"
    _COLLECTION_NAME = "2wikimhqa_passages_qwen3_embed_4b"
    _PASSAGE_COUNT = 430_000
    _PENDING_TOKEN = "VOI-PENDING-P1-C"

    @property
    def dataset_name(self) -> str:
        """Return the canonical benchmark dataset name."""

        return self._DATASET_NAME

    @property
    def expected_collection_name(self) -> str:
        """Return the expected Qdrant collection name."""

        return self._COLLECTION_NAME

    @property
    def expected_passage_count(self) -> int:
        """Return the approximate passage-count sentinel for downstream sanity checks."""

        return self._PASSAGE_COUNT

    def iter_passages(self) -> Iterator[Passage]:
        """Iterate normalized benchmark passages."""

        raise NotImplementedError(f"2WikiMHQA loader pending — see {self._PENDING_TOKEN}")
        yield  # pragma: no cover


class _MuSiQueStubLoader:
    """Placeholder loader for MuSiQue."""

    _DATASET_NAME = "musique"
    _COLLECTION_NAME = "musique_passages_qwen3_embed_4b"
    _PASSAGE_COUNT = 100_000
    _PENDING_TOKEN = "VOI-PENDING-P1-D"

    @property
    def dataset_name(self) -> str:
        """Return the canonical benchmark dataset name."""

        return self._DATASET_NAME

    @property
    def expected_collection_name(self) -> str:
        """Return the expected Qdrant collection name."""

        return self._COLLECTION_NAME

    @property
    def expected_passage_count(self) -> int:
        """Return the approximate passage-count sentinel for downstream sanity checks."""

        return self._PASSAGE_COUNT

    def iter_passages(self) -> Iterator[Passage]:
        """Iterate normalized benchmark passages."""

        raise NotImplementedError(f"MuSiQue loader pending — see {self._PENDING_TOKEN}")
        yield  # pragma: no cover


def load_multihop(name: MultihopBenchmark) -> MultihopLoader:
    """Return the scaffold loader for a supported multihop benchmark."""

    loaders = {
        MultihopBenchmark.HOTPOTQA: HotpotqaLoader,
        MultihopBenchmark.TWOWIKIMHQA: _TwoWikiMhqaStubLoader,
        MultihopBenchmark.MUSIQUE: _MuSiQueStubLoader,
    }
    loader_cls = loaders.get(name)
    if loader_cls is None:
        raise ValueError(f"Unknown multihop benchmark: {name!r}")
    return loader_cls()
