"""Multihop benchmark loader scaffold."""

from __future__ import annotations

from collections.abc import Iterator
from enum import Enum
from typing import Protocol

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
    def expected_eval_count(self) -> int:
        """Return the dev-split row count (sanity-check anchor for P1-B/C/D)."""

    def iter_passages(self) -> Iterator[Passage]:
        """Iterate normalized benchmark passages."""


class _HotpotqaStubLoader:
    """Placeholder loader for HotpotQA."""

    _DATASET_NAME = "hotpotqa"
    _COLLECTION_NAME = "hotpotqa_passages_qwen3_embed_4b"
    _EVAL_COUNT = 7405
    _PENDING_TOKEN = "VOI-PENDING-P1-B"

    @property
    def dataset_name(self) -> str:
        """Return the canonical benchmark dataset name."""

        return self._DATASET_NAME

    @property
    def expected_collection_name(self) -> str:
        """Return the expected Qdrant collection name."""

        return self._COLLECTION_NAME

    @property
    def expected_eval_count(self) -> int:
        """Return the dev-split row count (sanity-check anchor for P1-B/C/D)."""

        return self._EVAL_COUNT

    def iter_passages(self) -> Iterator[Passage]:
        """Iterate normalized benchmark passages."""

        raise NotImplementedError(f"HotpotQA loader pending — see {self._PENDING_TOKEN}")
        yield  # pragma: no cover


class _TwoWikiMhqaStubLoader:
    """Placeholder loader for 2WikiMultihopQA."""

    _DATASET_NAME = "2wikimhqa"
    _COLLECTION_NAME = "2wikimhqa_passages_qwen3_embed_4b"
    _EVAL_COUNT = 12576
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
    def expected_eval_count(self) -> int:
        """Return the dev-split row count (sanity-check anchor for P1-B/C/D)."""

        return self._EVAL_COUNT

    def iter_passages(self) -> Iterator[Passage]:
        """Iterate normalized benchmark passages."""

        raise NotImplementedError(f"2WikiMHQA loader pending — see {self._PENDING_TOKEN}")
        yield  # pragma: no cover


class _MuSiQueStubLoader:
    """Placeholder loader for MuSiQue."""

    _DATASET_NAME = "musique"
    _COLLECTION_NAME = "musique_passages_qwen3_embed_4b"
    _EVAL_COUNT = 2417
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
    def expected_eval_count(self) -> int:
        """Return the dev-split row count (sanity-check anchor for P1-B/C/D)."""

        return self._EVAL_COUNT

    def iter_passages(self) -> Iterator[Passage]:
        """Iterate normalized benchmark passages."""

        raise NotImplementedError(f"MuSiQue loader pending — see {self._PENDING_TOKEN}")
        yield  # pragma: no cover


def load_multihop(name: MultihopBenchmark) -> MultihopLoader:
    """Return the scaffold loader for a supported multihop benchmark."""

    loaders = {
        MultihopBenchmark.HOTPOTQA: _HotpotqaStubLoader,
        MultihopBenchmark.TWOWIKIMHQA: _TwoWikiMhqaStubLoader,
        MultihopBenchmark.MUSIQUE: _MuSiQueStubLoader,
    }
    loader_cls = loaders.get(name)
    if loader_cls is None:
        raise ValueError(f"Unknown multihop benchmark: {name!r}")
    return loader_cls()
