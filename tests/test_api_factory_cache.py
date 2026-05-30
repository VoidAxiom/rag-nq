from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import ApiGenerator, ApiRetriever, _factory_cache_for_test, create_app
from src.config.settings import Settings
from src.models.query_schemas import (
    GroundedAnswer,
    PassageHit,
    RetrievalMetrics,
)
from src.retrieval import qdrant_retrievers as qdrant_module
from src.retrieval.qdrant_retrievers import Mode, QdrantModeRetriever


class FakeApiRetriever:
    def __init__(self, *, mode: Mode) -> None:
        self.mode = mode
        self.last_retrieval_metrics: RetrievalMetrics | None = RetrievalMetrics()

    def retrieve(self, query: str, top_k: int) -> list[PassageHit]:
        del query, top_k
        return []

    def retrieve_with_metrics(
        self, query: str, top_k: int
    ) -> tuple[list[PassageHit], RetrievalMetrics | None]:
        hits = self.retrieve(query, top_k)
        return hits, self.last_retrieval_metrics


class FakeApiGenerator:
    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer:
        del query, hits
        return GroundedAnswer(answer="ok")


class _StubInner:
    def __init__(
        self,
        hold_seconds: float = 0.02,
        thread_state: threading.local | None = None,
    ) -> None:
        self._hold_seconds = hold_seconds
        self._thread_state = thread_state

    def retrieve(self, query: str, top_k: int) -> list[PassageHit]:
        del query
        if self._thread_state is not None:
            self._thread_state.top_k = top_k
        time.sleep(self._hold_seconds)
        return [
            PassageHit(point_id=f"p-{i}", text=f"t-{i}", dense_rank=i + 1)
            for i in range(top_k)
        ]


def test_default_retriever_factory_is_cached_across_calls_with_same_settings(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    calls = 0

    def stub(s: Settings, mode: Mode) -> ApiRetriever:
        nonlocal calls
        del s
        calls += 1
        return FakeApiRetriever(mode=mode)

    monkeypatch.setattr("app.api.main._default_retriever_factory", stub)
    app = create_app(
        settings=settings,
        retriever_factory=None,
        generator_factory=lambda s: FakeApiGenerator(),
    )
    client = TestClient(app)

    for _ in range(2):
        response = client.post(
            "/api/retrieve",
            json={"query": "q", "top_k": 1, "mode": "dense"},
        )
        assert response.status_code == 200

    assert calls == 1


def test_different_mode_creates_distinct_cached_instances(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    calls = 0

    def stub(s: Settings, mode: Mode) -> ApiRetriever:
        nonlocal calls
        del s
        calls += 1
        return FakeApiRetriever(mode=mode)

    monkeypatch.setattr("app.api.main._default_retriever_factory", stub)
    app = create_app(
        settings=settings,
        retriever_factory=None,
        generator_factory=lambda s: FakeApiGenerator(),
    )
    client = TestClient(app)

    dense_response = client.post(
        "/api/retrieve",
        json={"query": "q", "top_k": 1, "mode": "dense"},
    )
    sparse_response = client.post(
        "/api/retrieve",
        json={"query": "q", "top_k": 1, "mode": "sparse"},
    )

    assert dense_response.status_code == 200
    assert sparse_response.status_code == 200
    assert calls == 2


def test_different_embedder_name_creates_distinct_cached_instance(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    calls = 0

    def stub(s: Settings, mode: Mode) -> ApiRetriever:
        nonlocal calls
        del s
        calls += 1
        return FakeApiRetriever(mode=mode)

    monkeypatch.setattr("app.api.main._default_retriever_factory", stub)
    app = create_app(settings=settings, retriever_factory=None, generator_factory=None)
    cached_retriever, _cached_generator = _factory_cache_for_test(app)

    cached_retriever(settings, "dense")
    cached_retriever(settings.model_copy(update={"embedder_name": "other-model"}), "dense")

    assert calls == 2


def test_explicit_retriever_factory_bypasses_cache_completely(
    tmp_path: Path,
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    calls = 0

    def factory(s: Settings, mode: Mode) -> ApiRetriever:
        nonlocal calls
        del s
        calls += 1
        return FakeApiRetriever(mode=mode)

    app = create_app(
        settings=settings,
        retriever_factory=factory,
        generator_factory=lambda s: FakeApiGenerator(),
    )
    client = TestClient(app)

    for _ in range(2):
        response = client.post(
            "/api/retrieve",
            json={"query": "q", "top_k": 1, "mode": "dense"},
        )
        assert response.status_code == 200

    assert calls == 2
    with pytest.raises(AttributeError):
        _factory_cache_for_test(app)


def test_default_generator_factory_is_cached_keyed_on_provider_and_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    generator_calls = 0

    def retriever_stub(s: Settings, mode: Mode) -> ApiRetriever:
        del s
        return FakeApiRetriever(mode=mode)

    def generator_stub(s: Settings) -> ApiGenerator:
        nonlocal generator_calls
        del s
        generator_calls += 1
        return FakeApiGenerator()

    monkeypatch.setattr("app.api.main._default_retriever_factory", retriever_stub)
    monkeypatch.setattr("app.api.main._default_generator_factory", generator_stub)
    app = create_app(settings=settings, retriever_factory=None, generator_factory=None)
    client = TestClient(app)

    for _ in range(2):
        response = client.post(
            "/api/query",
            json={"query": "q", "top_k": 1, "mode": "dense", "generate": True},
        )
        assert response.status_code == 200

    assert generator_calls == 1

    _cached_retriever, cached_generator = _factory_cache_for_test(app)
    cached_generator(settings.model_copy(update={"generation_provider": "http_json"}))

    assert generator_calls == 2


def test_cached_retriever_serializes_concurrent_first_touch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    calls = 0

    def stub(s: Settings, mode: Mode) -> ApiRetriever:
        nonlocal calls
        del s
        calls += 1
        time.sleep(0.1)
        return FakeApiRetriever(mode=mode)

    monkeypatch.setattr("app.api.main._default_retriever_factory", stub)
    app = create_app(settings=settings, retriever_factory=None, generator_factory=None)
    cached_retriever, _cached_generator = _factory_cache_for_test(app)

    with ThreadPoolExecutor(max_workers=4) as executor:
        instances = list(
            executor.map(lambda _: cached_retriever(settings, "dense"), range(4))
        )

    assert calls == 1
    assert len({id(instance) for instance in instances}) == 1


def test_retrieve_with_metrics_returns_atomic_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    thread_state = threading.local()

    def fake_monotonic() -> float:
        return float(getattr(thread_state, "top_k", 0))

    monkeypatch.setattr(qdrant_module.time, "monotonic", fake_monotonic)
    settings = Settings(
        output_dir=tmp_path / "artifacts",
        retrieve_k=1,
        retrieval_dedupe_enabled=False,
    )
    retriever = QdrantModeRetriever(
        settings=settings,
        mode="dense",
        dense=_StubInner(thread_state=thread_state),
    )

    def call(top_k: int) -> tuple[int, int, RetrievalMetrics]:
        thread_state.top_k = 0
        hits, metrics = retriever.retrieve_with_metrics("q", top_k=top_k)
        assert metrics is not None
        assert metrics.timings is not None
        assert len(hits) == int(round(metrics.timings.total_seconds))
        assert len(hits) == top_k
        return top_k, len(hits), metrics

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(call, [1, 2, 3, 4]))

    assert sorted(result[0] for result in results) == [1, 2, 3, 4]
    assert all(result[1] == result[0] for result in results)


def test_post_init_eagerly_constructs_inner_retriever(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "artifacts",
        rerank_enabled=False,
    )
    dense = _StubInner()
    sparse = _StubInner()

    dense_retriever = QdrantModeRetriever(
        settings=settings,
        mode="dense",
        dense=dense,
        eager_init=True,
    )
    sparse_retriever = QdrantModeRetriever(
        settings=settings,
        mode="sparse",
        sparse=sparse,
        eager_init=True,
    )
    hybrid_retriever = QdrantModeRetriever(
        settings=settings,
        mode="hybrid",
        dense=dense,
        sparse=sparse,
        eager_init=True,
    )

    assert dense_retriever.dense is dense
    assert sparse_retriever.sparse is sparse
    assert hybrid_retriever.hybrid is not None
    assert hybrid_retriever.hybrid.dense is dense
    assert hybrid_retriever.hybrid.sparse is sparse
