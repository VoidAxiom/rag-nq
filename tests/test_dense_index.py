from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.config.settings import Settings
from src.ingestion.models import IndexChunk
from src.retrieval import dense_index
from src.retrieval.dense_index import DenseIndexer, build_embedder


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


class _FakeEmbeddingModel:
    def get_sentence_embedding_dimension(self) -> int:
        return 3

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
    ) -> list[list[float]]:
        assert batch_size > 0
        assert normalize_embeddings is True
        return [[0.1, 0.2, 0.3] for _ in texts]


class _FakeQdrantClient:
    def __init__(self) -> None:
        self.exists = False
        self.upsert_batches: list[int] = []

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    def create_collection(
        self, collection_name: str, vectors_config: object, sparse_vectors_config: object
    ) -> None:
        del collection_name, vectors_config, sparse_vectors_config
        self.exists = True

    def upsert(self, collection_name: str, points: list[object]) -> None:
        del collection_name
        self.upsert_batches.append(len(points))

    def count(self, collection_name: str, exact: bool = True) -> object:
        del collection_name, exact
        return type("CountResult", (), {"count": sum(self.upsert_batches)})()


def _write_index_chunks(path: Path, count: int) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for ordinal in range(count):
            chunk = IndexChunk(
                chunk_id=f"chunk-{ordinal}",
                group_id=f"group-{ordinal}",
                text=f"doc {ordinal}",
                context_text=f"doc {ordinal}",
                source_row_ordinal=ordinal,
                start_candidate_idx=0,
                end_candidate_idx=0,
            )
            handle.write(chunk.model_dump_json())
            handle.write("\n")


def test_release_mps_cache_called_per_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    settings = Settings.from_env().model_copy(
        update={"qdrant_collection": "c_cache_release", "embedding_batch_size": 8}
    )
    jsonl_path = tmp_path / "index_chunks.jsonl"
    _write_index_chunks(jsonl_path, count=5)
    release_cache = MagicMock()
    monkeypatch.setattr(dense_index, "_release_mps_cache", release_cache)
    monkeypatch.setattr(
        dense_index,
        "_build_vector_params",
        lambda size, distance_name: {"size": size, "distance": distance_name},
    )

    indexer = DenseIndexer(
        settings=settings,
        client=_FakeQdrantClient(),
        model=_FakeEmbeddingModel(),
    )
    result = indexer.build_from_jsonl_streaming(jsonl_path, lines_per_batch=2)

    assert result.vector_count == 5
    assert release_cache.call_count == 3


def test_init_does_not_load_model(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    build = MagicMock(side_effect=RuntimeError("build_embedder must not be called from __init__"))
    monkeypatch.setattr(dense_index, "build_embedder", build)

    DenseIndexer(settings=Settings.from_env(), client=_FakeQdrantClient())

    assert build.call_count == 0


def test_first_dim_call_triggers_lazy_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RAG_OUTPUT_DIR", str(tmp_path))
    fake_model = MagicMock()
    fake_model.get_sentence_embedding_dimension.return_value = 7
    build = MagicMock(return_value=fake_model)
    monkeypatch.setattr(dense_index, "build_embedder", build)
    indexer = DenseIndexer(settings=Settings.from_env(), client=_FakeQdrantClient())

    assert build.call_count == 0
    assert indexer._embedding_dimension() == 7
    assert build.call_count == 1
    assert indexer._embedding_dimension() == 7
    assert build.call_count == 1
