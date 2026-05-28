from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.api.main import create_app, safe_runtime_config
from src.config.settings import Settings
from src.models.query_schemas import Citation, GroundedAnswer, PassageHit, RetrievalMetrics
from src.retrieval.qdrant_retrievers import Mode


class FakeRetriever:
    def __init__(self, *, mode: Mode) -> None:
        self.mode = mode
        self.last_retrieval_metrics = RetrievalMetrics()

    def retrieve(self, query: str, top_k: int) -> list[PassageHit]:
        return [
            PassageHit(
                point_id=f"{self.mode}-1",
                text=f"Evidence for {query}",
                title="Doc",
                dense_rank=1 if self.mode in {"dense", "hybrid"} else None,
                sparse_rank=1 if self.mode in {"sparse", "hybrid"} else None,
            )
        ][:top_k]


class FakeGenerator:
    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer:
        return GroundedAnswer(
            answer=f"Grounded answer for {query}",
            citations=[Citation(point_id=hits[0].point_id)],
            abstained=False,
            supporting_point_ids=[hits[0].point_id],
            supporting_evidence=hits[:1],
        )


def test_root_endpoint_points_to_api_docs_and_core_routes(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "service": "rag-nq-showcase",
        "docs_url": "/docs",
        "health_url": "/health",
        "config_url": "/config",
        "retrieve_url": "/retrieve",
        "query_url": "/query",
    }


def test_favicon_endpoint_avoids_browser_404_noise(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/favicon.ico")

    assert response.status_code == 204
    assert response.content == b""


def test_health_endpoint_returns_ok(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "rag-nq-showcase"}


def test_config_endpoint_exposes_safe_runtime_metadata(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "artifacts",
        qdrant_url="https://user:password@qdrant.example:6333",
        generation_api_url="https://provider.example",
        generation_api_key_env="OPENAI_API_KEY",
    )
    settings.index_chunks_path.parent.mkdir(parents=True, exist_ok=True)
    settings.index_chunks_path.write_text("{}\n", encoding="utf-8")
    client = _client(tmp_path, settings=settings)

    response = client.get("/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["qdrant_collection"] == settings.qdrant_collection
    assert payload["qdrant_url"] == "https://qdrant.example:6333"
    assert payload["retrieval"]["hybrid_dense_weight"] == 0.5
    assert payload["generation"]["generation_api_configured"] is True
    assert payload["generation"]["generation_api_key_env_configured"] is True
    assert payload["artifacts"]["index_chunks"]["exists"] is True
    assert "password" not in response.text
    assert "OPENAI_API_KEY" not in response.text
    assert "provider.example" not in response.text


def test_retrieve_endpoint_returns_hits_and_metrics(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/retrieve",
        json={"query": "What is Paris?", "top_k": 1, "mode": "sparse"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "What is Paris?"
    assert payload["grounded"] is None
    assert payload["retrieved_passages"][0]["point_id"] == "sparse-1"
    assert payload["retrieval_metrics"] == {"dedupe": None, "timings": None}


def test_query_endpoint_can_generate_grounded_answer(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={"query": "What is Paris?", "top_k": 1, "mode": "hybrid", "generate": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["retrieved_passages"][0]["point_id"] == "hybrid-1"
    assert payload["grounded"]["answer"] == "Grounded answer for What is Paris?"
    assert payload["grounded"]["citations"] == [{"point_id": "hybrid-1"}]


def test_query_endpoint_can_skip_generation(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={"query": "What is Paris?", "top_k": 1, "mode": "dense", "generate": False},
    )

    assert response.status_code == 200
    assert response.json()["grounded"] is None


def test_retrieve_endpoint_maps_runtime_failures_to_503(tmp_path: Path) -> None:
    def failing_retriever_factory(settings: Settings, mode: Mode):
        del settings, mode
        return SimpleNamespace(
            last_retrieval_metrics=None,
            retrieve=lambda query, top_k: (_ for _ in ()).throw(RuntimeError("qdrant down")),
        )

    client = _client(tmp_path, retriever_factory=failing_retriever_factory)

    response = client.post("/retrieve", json={"query": "q", "top_k": 1, "mode": "dense"})

    assert response.status_code == 503
    assert response.json()["detail"] == "qdrant down"


def test_safe_runtime_config_does_not_expose_secret_names_or_urls(tmp_path: Path) -> None:
    settings = Settings(
        output_dir=tmp_path / "artifacts",
        qdrant_url="https://user:password@qdrant.example:6333",
        generation_api_url="https://provider.example",
        generation_api_key_env="SECRET_ENV_NAME",
    )

    payload = safe_runtime_config(settings).model_dump_json()

    assert "SECRET_ENV_NAME" not in payload
    assert "provider.example" not in payload
    assert "password" not in payload
    assert "https://qdrant.example:6333" in payload
    assert "generation_api_configured" in payload


def _client(
    tmp_path: Path,
    *,
    settings: Settings | None = None,
    retriever_factory=None,
) -> TestClient:
    app = create_app(
        settings=settings or Settings(output_dir=tmp_path / "artifacts"),
        retriever_factory=(
            retriever_factory
            or (lambda settings, mode: FakeRetriever(mode=mode))
        ),
        generator_factory=lambda settings: FakeGenerator(),
    )
    return TestClient(app)


def test_eval_questions_endpoint_returns_curated_nq_json(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    questions_dir = settings.output_dir / "eval_questions"
    questions_dir.mkdir(parents=True)
    (questions_dir / "nq.json").write_text(
        """[
          {
            "query_id": "nq-1",
            "query": "What is the capital of France?",
            "gold_answers": ["Paris"],
            "supporting_passage_ids": ["nq-passage-1"],
            "notes": "fixture"
          }
        ]""",
        encoding="utf-8",
    )
    client = _client(tmp_path, settings=settings)

    response = client.get("/api/eval_questions/nq")

    assert response.status_code == 200
    assert response.json() == {
        "benchmark": "nq",
        "questions": [
            {
                "query_id": "nq-1",
                "query": "What is the capital of France?",
                "gold_answers": ["Paris"],
                "supporting_passage_ids": ["nq-passage-1"],
                "notes": "fixture",
            }
        ],
    }


def test_eval_questions_endpoint_unknown_benchmark_returns_404(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/eval_questions/unknown")

    assert response.status_code == 404


def test_eval_questions_endpoint_missing_file_returns_503(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/eval_questions/nq")

    assert response.status_code == 503
    assert "Eval questions file not found at" in response.json()["detail"]
    assert "P1-F curation step not run yet." in response.json()["detail"]


def test_components_endpoint_reports_openai_disabled_when_env_unset(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("RAG_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAG_OPENAI_OPT_IN", raising=False)
    client = _client(tmp_path)

    response = client.get("/api/components")

    assert response.status_code == 200
    payload = response.json()
    assert payload["modes"] == ["dense", "sparse", "hybrid"]
    assert payload["top_k_choices"] == [5, 10, 20, 50]
    assert payload["rerankers"] == [
        {"name": "BAAI/bge-reranker-v2-m3", "label": "BGE-v2-m3 (default)"},
        {
            "name": "cross-encoder/ms-marco-MiniLM-L-6-v2",
            "label": "MiniLM-L-6-v2 (fast)",
        },
        {"name": "off", "label": "No rerank"},
    ]
    assert payload["collections"] == [
        {"benchmark": "nq", "collection": "nq_passages_qwen3_embed_4b"},
        {"benchmark": "hotpotqa", "collection": "hotpotqa_passages_qwen3_embed_4b"},
        {"benchmark": "2wikimhqa", "collection": "2wikimhqa_passages_qwen3_embed_4b"},
        {"benchmark": "musique", "collection": "musique_passages_qwen3_embed_4b"},
    ]
    assert payload["openai_enabled"] is False
    openai_generator = next(item for item in payload["generators"] if item["name"] == "openai")
    assert openai_generator["enabled"] is False
    assert "RAG_OPENAI_API_KEY" in openai_generator["disabled_reason"]
    assert "RAG_OPENAI_OPT_IN=1" in openai_generator["disabled_reason"]
    assert payload["embedder"] == "Qwen/Qwen3-Embedding-4B"


def test_components_endpoint_reports_openai_enabled_only_when_both_env_vars_set(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RAG_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("RAG_OPENAI_OPT_IN", "1")
    client = _client(tmp_path)

    response = client.get("/api/components")

    assert response.status_code == 200
    payload = response.json()
    assert payload["openai_enabled"] is True
    openai_generator = next(item for item in payload["generators"] if item["name"] == "openai")
    assert openai_generator["enabled"] is True
    assert openai_generator["disabled_reason"] is None


def test_query_endpoint_computes_em_and_f1_for_matching_gold_answer(tmp_path: Path) -> None:
    client = _client_with_answer(tmp_path, answer="Paris")

    response = client.post(
        "/query",
        json={
            "query": "What is the capital of France?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": True,
            "gold_answers": ["paris"],
        },
    )

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["em"] == 1.0
    assert metrics["f1"] == 1.0


def test_query_endpoint_computes_zero_em_and_f1_for_mismatched_gold_answer(
    tmp_path: Path,
) -> None:
    client = _client_with_answer(tmp_path, answer="Paris")

    response = client.post(
        "/query",
        json={
            "query": "What is the capital of France?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": True,
            "gold_answers": ["london"],
        },
    )

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["em"] == 0.0
    assert metrics["f1"] == 0.0


def test_query_endpoint_computes_supporting_fact_recall_at_k(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "sparse",
            "generate": False,
            "supporting_passage_ids": ["sparse-1"],
        },
    )

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["supporting_fact_recall_at_k"] == 1.0
    assert metrics["k_used"] == 1


def test_query_supporting_recall_uses_request_top_k_not_returned_count(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={
            "query": "What is Paris?",
            "top_k": 10,
            "mode": "sparse",
            "generate": False,
            "supporting_passage_ids": ["sparse-1", "sparse-2"],
        },
    )

    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["supporting_fact_recall_at_k"] == 0.5
    assert metrics["k_used"] == 10


def test_query_endpoint_accepts_rerank_enabled_override(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"rerank_enabled": False},
        },
    )

    assert response.status_code == 200
    assert response.json()["components_used"]["reranker"] == "off"


def test_query_rerank_enabled_false_wins_over_rerank_model_name(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {
                "rerank_enabled": False,
                "rerank_model_name": "BAAI/bge-reranker-v2-m3",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["components_used"]["reranker"] == "off"


def test_query_endpoint_accepts_rerank_model_name_override(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"rerank_model_name": "cross-encoder/ms-marco-MiniLM-L-6-v2"},
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["components_used"]["reranker"]
        == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    )


def test_query_endpoint_rejects_openai_override_when_env_not_opted_in(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.delenv("RAG_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("RAG_OPENAI_OPT_IN", raising=False)
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"generation_provider": "openai"},
        },
    )

    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "OpenAI generator requires both RAG_OPENAI_API_KEY and RAG_OPENAI_OPT_IN=1 "
        "to be set."
    )


def test_query_endpoint_rejects_unknown_override_key(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"invalid_key": "x"},
        },
    )

    assert response.status_code == 422
    assert "invalid_key" in response.json()["detail"]


def test_query_endpoint_passes_collection_override_to_retriever_factory(tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def capturing_retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        captured["collection"] = settings.qdrant_collection
        return FakeRetriever(mode=mode)

    client = _client(tmp_path, retriever_factory=capturing_retriever_factory)

    response = client.post(
        "/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "collection": "custom-collection",
        },
    )

    assert response.status_code == 200
    assert captured["collection"] == "custom-collection"


def test_query_endpoint_reports_latency_breakdown_when_generation_runs(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={"query": "What is Paris?", "top_k": 1, "mode": "hybrid", "generate": True},
    )

    assert response.status_code == 200
    latency = response.json()["latency_ms"]
    assert latency["retrieval_ms"] >= 0.0
    assert latency["generation_ms"] >= 0.0
    assert latency["total_ms"] >= latency["retrieval_ms"] + latency["generation_ms"] - 0.5


def test_query_endpoint_echoes_query_id(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "query_id": "abc-123",
        },
    )

    assert response.status_code == 200
    assert response.json()["query_id"] == "abc-123"


class FixedAnswerGenerator:
    def __init__(self, *, answer: str) -> None:
        self.answer = answer

    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer:
        del query
        return GroundedAnswer(
            answer=self.answer,
            citations=[Citation(point_id=hits[0].point_id)],
            abstained=False,
            supporting_point_ids=[hits[0].point_id],
            supporting_evidence=hits[:1],
        )


def _client_with_answer(tmp_path: Path, *, answer: str) -> TestClient:
    app = create_app(
        settings=Settings(output_dir=tmp_path / "artifacts"),
        retriever_factory=lambda settings, mode: FakeRetriever(mode=mode),
        generator_factory=lambda settings: FixedAnswerGenerator(answer=answer),
    )
    return TestClient(app)
