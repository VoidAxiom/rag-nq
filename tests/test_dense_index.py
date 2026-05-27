from __future__ import annotations

import pytest

from src.retrieval import dense_index
from src.retrieval.dense_index import build_embedder


class FakeSentenceTransformer:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs
        self.max_seq_length = 32768


def test_build_embedder_caps_max_seq_length_qwen3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", FakeSentenceTransformer)
    monkeypatch.setattr(dense_index, "_is_apple_silicon", lambda: True)

    embedder = build_embedder("Qwen/Qwen3-Embedding-4B")

    inner = getattr(embedder, "_inner")
    assert isinstance(inner, FakeSentenceTransformer)
    assert inner.max_seq_length == 512


def test_build_embedder_caps_max_seq_length_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sentence_transformers.SentenceTransformer", FakeSentenceTransformer)

    embedder = build_embedder("sentence-transformers/all-MiniLM-L6-v2")

    assert isinstance(embedder, FakeSentenceTransformer)
    assert embedder.max_seq_length == 512
