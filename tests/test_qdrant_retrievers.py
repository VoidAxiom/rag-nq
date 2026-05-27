from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from src.config.settings import Settings
from src.models.query_schemas import PassageHit
from src.retrieval.qdrant_retrievers import (
    DenseQdrantRetriever,
    HybridQdrantRetriever,
    QdrantModeRetriever,
    SparseQdrantRetriever,
    _build_default_qdrant_client,
)
from src.retrieval.sparse_qdrant import SparsePass1Data


class FakeEmbeddingModel:
    def encode(
        self, texts: list[str], *, batch_size: int, normalize_embeddings: bool
    ) -> list[list[float]]:
        assert batch_size == 1
        assert normalize_embeddings is True
        return [[0.2, 0.8] for _ in texts]


class FakeEmbeddingModelWithProgressFlag:
    def __init__(self) -> None:
        self.show_progress_bar: bool | None = None

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        show_progress_bar: bool,
    ) -> list[list[float]]:
        assert batch_size == 1
        assert normalize_embeddings is True
        self.show_progress_bar = show_progress_bar
        return [[0.2, 0.8] for _ in texts]


class FakeReranker:
    def predict(self, pairs):
        return [10.0 if "best" in passage else 1.0 for _query, passage in pairs]


class FakeQueryClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def query_points(
        self,
        collection_name: str,
        query: Any,
        *,
        using: str,
        limit: int,
        with_payload: bool,
    ) -> Any:
        self.calls.append(
            {
                "collection_name": collection_name,
                "using": using,
                "limit": limit,
                "with_payload": with_payload,
                "query": query,
            }
        )
        if using == "dense":
            return SimpleNamespace(
                points=[
                    SimpleNamespace(id="p1", score=0.9, payload={"text": "d1"}),
                    SimpleNamespace(id="p2", score=0.8, payload={"text": "d2"}),
                ]
            )
        if using == "sparse":
            return SimpleNamespace(
                points=[
                    SimpleNamespace(id="p2", score=5.0, payload={"text": "d2"}),
                    SimpleNamespace(id="p3", score=3.0, payload={"text": "d3"}),
                ]
            )
        raise AssertionError(f"unexpected using={using}")


def _write_sparse_pass1_artifact(path: Path, *, max_passages: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1",
        "silver_path": str((path.parent / "index_chunks.jsonl").resolve()),
        "max_passages": max_passages,
        "document_count": 2,
        "total_tokens": 5,
        "term_to_id": {"alpha": 0, "beta": 1},
        "sparse_analyzer": "regex_stem_stop",
        "sparse_analyzer_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_dense_retriever_maps_scores_and_ranks() -> None:
    settings = Settings(qdrant_collection="c")
    client = FakeQueryClient()
    retriever = DenseQdrantRetriever(settings=settings, client=client, model=FakeEmbeddingModel())
    hits = retriever.retrieve("hello", top_k=2)
    assert [h.point_id for h in hits] == ["p1", "p2"]
    assert [h.dense_rank for h in hits] == [1, 2]
    assert hits[0].dense_score == 0.9
    assert hits[0].sparse_score is None


def test_dense_retriever_disables_sentence_transformer_progress_bar() -> None:
    settings = Settings(qdrant_collection="c")
    client = FakeQueryClient()
    model = FakeEmbeddingModelWithProgressFlag()
    retriever = DenseQdrantRetriever(settings=settings, client=client, model=model)

    retriever.retrieve("hello", top_k=2)

    assert model.show_progress_bar is False


def test_sparse_retriever_uses_term_to_id_and_sets_sparse_fields(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    output_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(output_dir=output_dir, qdrant_collection="c")
    (output_dir / "index_chunks.jsonl").write_text("", encoding="utf-8")
    _write_sparse_pass1_artifact(settings.sparse_pass1_path)
    client = FakeQueryClient()
    retriever = SparseQdrantRetriever(settings=settings, client=client)
    hits = retriever.retrieve("alpha alpha beta", top_k=2)
    assert [h.point_id for h in hits] == ["p2", "p3"]
    assert [h.sparse_rank for h in hits] == [1, 2]
    assert hits[0].sparse_score == 5.0
    assert hits[0].dense_score is None


def test_sparse_retriever_returns_empty_when_query_has_no_vocab_overlap() -> None:
    settings = Settings(qdrant_collection="c")
    client = FakeQueryClient()
    pass1 = SparsePass1Data(
        document_count=1,
        total_tokens=1,
        term_to_id={"alpha": 0},
        silver_path_resolved="/tmp/passages.jsonl",
        max_passages=None,
    )
    retriever = SparseQdrantRetriever(settings=settings, client=client, pass1_data=pass1)
    hits = retriever.retrieve("zzz", top_k=3)
    assert hits == []
    assert client.calls == []


def test_hybrid_retriever_rrf_combines_dense_and_sparse() -> None:
    settings = Settings(qdrant_collection="c", hybrid_rrf_k=60, rerank_enabled=False)
    client = FakeQueryClient()
    dense = DenseQdrantRetriever(settings=settings, client=client, model=FakeEmbeddingModel())
    sparse = SparseQdrantRetriever(
        settings=settings,
        client=client,
        pass1_data=SparsePass1Data(
            document_count=1,
            total_tokens=1,
            term_to_id={"hello": 0},
            silver_path_resolved="/tmp/passages.jsonl",
            max_passages=None,
        ),
    )
    retriever = HybridQdrantRetriever(settings=settings, dense=dense, sparse=sparse)
    hits = retriever.retrieve("hello", top_k=3)
    assert [h.point_id for h in hits] == ["p2", "p3", "p1"]
    assert [h.fusion_rank for h in hits] == [1, 2, 3]
    assert hits[0].dense_rank == 2
    assert hits[0].sparse_rank == 1
    assert [h.dedupe_rank for h in hits] == [1, 2, 3]
    assert retriever.last_dedupe_metrics is not None
    assert retriever.last_dedupe_metrics.raw_count == 3
    assert retriever.last_dedupe_metrics.dedupe_drop_count == 0


def test_hybrid_retriever_dedupes_by_title_and_context_text() -> None:
    settings = Settings(qdrant_collection="c", retrieve_k=10, rerank_enabled=False)
    dense = SimpleNamespace(
        retrieve=lambda query, top_k: [
            PassageHit(
                point_id="p1",
                title="Doc",
                text="short",
                context_text="Same evidence",
                dense_rank=1,
            ),
            PassageHit(
                point_id="p2",
                title="Doc",
                text="different short text",
                context_text=" same   evidence ",
                dense_rank=2,
            ),
            PassageHit(
                point_id="p3",
                title="Other Doc",
                text="short",
                context_text="Same evidence",
                dense_rank=3,
            ),
        ]
    )
    sparse = SimpleNamespace(retrieve=lambda query, top_k: [])
    retriever = HybridQdrantRetriever(settings=settings, dense=dense, sparse=sparse)

    hits = retriever.retrieve("hello", top_k=10)

    assert [hit.point_id for hit in hits] == ["p1", "p3"]
    assert [hit.dedupe_rank for hit in hits] == [1, 2]
    assert hits[0].duplicate_aliases[0].point_id == "p2"
    assert hits[0].duplicate_aliases[0].dense_rank == 2
    assert hits[0].duplicate_aliases[0].fusion_rank == 2
    assert retriever.last_dedupe_metrics is not None
    assert retriever.last_dedupe_metrics.raw_count == 3
    assert retriever.last_dedupe_metrics.unique_count == 2
    assert retriever.last_dedupe_metrics.dedupe_drop_count == 1


def test_hybrid_retriever_reranks_when_enabled() -> None:
    settings = Settings(qdrant_collection="c", rerank_enabled=True, retrieve_k=10)
    dense = SimpleNamespace(
        retrieve=lambda query, top_k: [
            PassageHit(point_id="p1", text="ordinary", dense_rank=1),
            PassageHit(point_id="p2", text="best answer", dense_rank=2),
        ]
    )
    sparse = SimpleNamespace(retrieve=lambda query, top_k: [])
    retriever = HybridQdrantRetriever(
        settings=settings,
        dense=dense,
        sparse=sparse,
        reranker=FakeReranker(),
    )

    hits = retriever.retrieve("hello", top_k=2)

    assert [hit.point_id for hit in hits] == ["p2", "p1"]
    assert [hit.fusion_rank for hit in hits] == [2, 1]
    assert [hit.rerank_rank for hit in hits] == [1, 2]


def test_mode_retriever_routes_to_selected_mode() -> None:
    settings = Settings(qdrant_collection="c")
    dense = SimpleNamespace(
        retrieve=lambda query, top_k: [PassageHit(point_id="dense", text="d")]
    )
    sparse = SimpleNamespace(
        retrieve=lambda query, top_k: [PassageHit(point_id="sparse", text="s")]
    )
    hybrid = SimpleNamespace(
        retrieve=lambda query, top_k: [PassageHit(point_id="hybrid", text="h")]
    )
    retriever = QdrantModeRetriever(
        settings=settings,
        mode="hybrid",
        dense=dense,
        sparse=sparse,
        hybrid=hybrid,
    )
    out = retriever.retrieve("q", top_k=1)
    assert out[0].point_id == "hybrid"


def test_mode_retriever_dense_mode_does_not_require_sparse_dependencies() -> None:
    settings = Settings(qdrant_collection="c")
    dense = SimpleNamespace(
        retrieve=lambda query, top_k: [PassageHit(point_id="dense", text="d")]
    )
    retriever = QdrantModeRetriever(
        settings=settings,
        mode="dense",
        dense=dense,
        sparse=None,
        hybrid=None,
    )
    out = retriever.retrieve("q", top_k=1)
    assert out[0].point_id == "dense"


def test_mode_retriever_applies_dedupe_metrics_to_dense_mode() -> None:
    settings = Settings(qdrant_collection="c", retrieve_k=5)
    dense = SimpleNamespace(
        retrieve=lambda query, top_k: [
            PassageHit(point_id="p1", title="Doc", text="same"),
            PassageHit(point_id="p2", title="Doc", text=" same "),
        ]
    )
    retriever = QdrantModeRetriever(settings=settings, mode="dense", dense=dense)

    out = retriever.retrieve("q", top_k=5)

    assert [hit.point_id for hit in out] == ["p1"]
    assert out[0].duplicate_aliases[0].point_id == "p2"
    assert retriever.last_retrieval_metrics is not None
    assert retriever.last_retrieval_metrics.dedupe is not None
    assert retriever.last_retrieval_metrics.dedupe.dedupe_drop_count == 1
    assert retriever.last_retrieval_metrics.timings is not None
    assert retriever.last_retrieval_metrics.timings.total_seconds >= 0.0


def test_build_default_qdrant_client_passes_timeout(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class FakeQdrantClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    fake_module = SimpleNamespace(QdrantClient=FakeQdrantClient)
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_module)
    client = _build_default_qdrant_client("http://localhost:6333", timeout=15.0)
    assert isinstance(client, FakeQdrantClient)
    assert captured["url"] == "http://localhost:6333"
    assert captured["timeout"] == 15.0


def test_dense_retriever_uses_qwen3_embed_4b_mode() -> None:
    """Settings with Qwen3-Embedding-4B name produces a (2560,) query vector."""

    import numpy as np

    settings = Settings(
        qdrant_collection="c",
        embedder_name="Qwen/Qwen3-Embedding-4B",
    )

    class FakeQwen3Embedder:
        def encode(
            self, texts: list[str], *, batch_size: int, normalize_embeddings: bool
        ) -> np.ndarray:
            assert batch_size == 1
            assert normalize_embeddings is True
            return np.zeros((len(texts), 2560), dtype=np.float32)

        def get_sentence_embedding_dimension(self) -> int:
            return 2560

    client = FakeQueryClient()
    retriever = DenseQdrantRetriever(
        settings=settings, client=client, model=FakeQwen3Embedder()
    )
    retriever.retrieve("hello", top_k=2)

    assert len(client.calls) == 1
    query_vector = client.calls[0]["query"]
    assert len(query_vector) == 2560


def test_dense_retriever_legacy_minilm_mode() -> None:
    """Legacy MiniLM-L6 path stays functional: (384,) query vector."""

    import numpy as np

    settings = Settings(
        qdrant_collection="c",
        embedder_name="sentence-transformers/all-MiniLM-L6-v2",
    )

    class FakeMiniLMEmbedder:
        def encode(
            self, texts: list[str], *, batch_size: int, normalize_embeddings: bool
        ) -> np.ndarray:
            assert batch_size == 1
            assert normalize_embeddings is True
            return np.zeros((len(texts), 384), dtype=np.float32)

        def get_sentence_embedding_dimension(self) -> int:
            return 384

    client = FakeQueryClient()
    retriever = DenseQdrantRetriever(
        settings=settings, client=client, model=FakeMiniLMEmbedder()
    )
    retriever.retrieve("hello", top_k=2)

    assert len(client.calls) == 1
    query_vector = client.calls[0]["query"]
    assert len(query_vector) == 384


def test_build_embedder_qwen3_apple_silicon(monkeypatch) -> None:
    """Qwen3-Embedding on Apple Silicon loads with mps + float16 + wraps to float32."""

    import numpy as np
    import torch

    from src.retrieval import dense_index

    captured: dict[str, Any] = {}

    class FakeSentenceTransformer:
        def __init__(self, name: str, **kwargs: Any) -> None:
            captured["name"] = name
            captured["kwargs"] = kwargs

        def encode(self, texts, **_kwargs):
            # Return float16 so the wrapper has to cast back to float32.
            return np.zeros((len(texts), 2560), dtype=np.float16)

        def get_sentence_embedding_dimension(self) -> int:
            return 2560

    monkeypatch.setattr(dense_index, "_is_apple_silicon", lambda: True)
    monkeypatch.setattr(
        dense_index, "SentenceTransformer", FakeSentenceTransformer, raising=False
    )
    # Also intercept the top-level import inside build_embedder by inserting
    # the fake module into sys.modules so `from sentence_transformers import
    # SentenceTransformer` resolves to FakeSentenceTransformer.
    fake_module = SimpleNamespace(SentenceTransformer=FakeSentenceTransformer)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)

    embedder = dense_index.build_embedder("Qwen/Qwen3-Embedding-4B")

    assert captured["name"] == "Qwen/Qwen3-Embedding-4B"
    assert captured["kwargs"].get("model_kwargs") == {"torch_dtype": torch.float16}
    assert captured["kwargs"].get("device") == "mps"

    out = embedder.encode(["hello"])
    assert out.dtype == np.float32
    assert out.shape == (1, 2560)


def test_float32_wrapper_omits_batch_size_when_none() -> None:
    """Regression for VOI-249: the wrapper must NOT forward batch_size=None
    to SentenceTransformer.encode, which rejects None with a TypeError
    on '<=' check.

    Surfaced live on primary main after VOI-245 (PR #5) merged; the
    smoke `e.encode(['hello'])` (no batch_size kwarg) crashed before
    reaching the model.
    """
    import numpy as np

    from src.retrieval.dense_index import _Float32EncoderWrapper

    captured: dict[str, object] = {}

    class _FakeEncoder:
        def encode(self, texts, **kwargs):
            captured.update(kwargs)
            return np.zeros((len(texts), 4), dtype=np.float16)

    wrapper = _Float32EncoderWrapper(_FakeEncoder())
    out = wrapper.encode(["hello"])  # no batch_size kwarg

    assert "batch_size" not in captured, captured
    # Sanity: normalize_embeddings IS forwarded as a real value (default True).
    assert captured.get("normalize_embeddings") is True, captured
    # Sanity: wrapper still satisfies the float32 contract.
    assert out.dtype == np.float32
    assert out.shape == (1, 4)
