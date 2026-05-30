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

    def retrieve_with_metrics(
        self, query: str, top_k: int
    ) -> tuple[list[PassageHit], RetrievalMetrics | None]:
        hits = self.retrieve(query, top_k)
        return hits, self.last_retrieval_metrics


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
        "health_url": "/api/health",
        "config_url": "/api/config",
        "retrieve_url": "/api/retrieve",
        "query_url": "/api/query",
    }


def test_favicon_endpoint_avoids_browser_404_noise(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/favicon.ico")

    assert response.status_code == 204
    assert response.content == b""


def test_health_endpoint_returns_ok(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/health")

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

    response = client.get("/api/config")

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
        "/api/retrieve",
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
        "/api/query",
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
        "/api/query",
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
            retrieve_with_metrics=lambda query, top_k: (_ for _ in ()).throw(
                RuntimeError("qdrant down")
            ),
        )

    client = _client(tmp_path, retriever_factory=failing_retriever_factory)

    response = client.post("/api/retrieve", json={"query": "q", "top_k": 1, "mode": "dense"})

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


def test_eval_questions_endpoint_missing_file_returns_empty(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.get("/api/eval_questions/nq")

    assert response.status_code == 200
    assert response.json() == {"benchmark": "nq", "questions": []}


def test_suite_crud_endpoints_roundtrip(tmp_path: Path) -> None:
    settings = Settings(output_dir=tmp_path / "artifacts")
    client = _client(tmp_path, settings=settings)
    config = {
        "benchmark": "nq",
        "collection": "nq_passages_qwen3_embed_4b",
        "mode": "hybrid",
        "top_k": 10,
        "reranker": "BAAI/bge-reranker-v2-m3",
        "generator": "heuristic",
    }

    create_response = client.post(
        "/api/suites",
        json={
            "name": "NQ Smoke Suite",
            "description": "Small deterministic suite",
            "config": config,
        },
    )

    assert create_response.status_code == 201
    suite = create_response.json()
    suite_id = suite["id"]
    suite_path = settings.output_dir / "eval_suites" / f"{suite_id}.json"
    assert tmp_path in suite_path.parents
    assert suite_path.is_file()
    assert suite["name"] == "NQ Smoke Suite"
    assert suite["entries"] == []

    list_response = client.get("/api/suites")
    assert list_response.status_code == 200
    summary = next(item for item in list_response.json() if item["id"] == suite_id)
    assert summary["entry_count"] == 0
    assert summary["config"] == config

    detail_response = client.get(f"/api/suites/{suite_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["entries"] == []

    updated_config = {**config, "top_k": 5}
    update_suite_response = client.put(
        f"/api/suites/{suite_id}",
        json={
            "name": "NQ Smoke Suite Updated",
            "description": "Updated description",
            "config": updated_config,
        },
    )
    assert update_suite_response.status_code == 200
    assert update_suite_response.json()["name"] == "NQ Smoke Suite Updated"
    assert update_suite_response.json()["config"] == updated_config

    add_entry_response = client.post(
        f"/api/suites/{suite_id}/entries",
        json={
            "question": "What is the capital of France?",
            "gold_answers": ["Paris"],
            "source": "dataset",
            "dataset_ref": {"benchmark": "nq", "question_id": "nq-1"},
            "notes": "fixture",
        },
    )

    assert add_entry_response.status_code == 201
    entry_suite = add_entry_response.json()
    assert len(entry_suite["entries"]) == 1
    entry = next(iter(entry_suite["entries"]))
    entry_id = entry["id"]
    assert entry["question"] == "What is the capital of France?"
    assert entry["gold_answers"] == ["Paris"]

    detail_with_entry_response = client.get(f"/api/suites/{suite_id}")
    assert detail_with_entry_response.status_code == 200
    assert detail_with_entry_response.json()["entries"] == [entry]

    update_entry_response = client.put(
        f"/api/suites/{suite_id}/entries/{entry_id}",
        json={
            "question": "Which city is France's capital?",
            "gold_answers": ["Paris", "City of Paris"],
            "notes": "updated",
        },
    )

    assert update_entry_response.status_code == 200
    updated_entry = next(iter(update_entry_response.json()["entries"]))
    assert updated_entry["id"] == entry_id
    assert updated_entry["question"] == "Which city is France's capital?"
    assert updated_entry["gold_answers"] == ["Paris", "City of Paris"]
    assert updated_entry["notes"] == "updated"

    delete_entry_response = client.delete(f"/api/suites/{suite_id}/entries/{entry_id}")
    assert delete_entry_response.status_code == 200
    assert delete_entry_response.json()["entries"] == []

    delete_suite_response = client.delete(f"/api/suites/{suite_id}")
    assert delete_suite_response.status_code == 204
    assert delete_suite_response.content == b""
    assert not suite_path.exists()

    missing_detail_response = client.get(f"/api/suites/{suite_id}")
    assert missing_detail_response.status_code == 404


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
        "/api/query",
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
        "/api/query",
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
        "/api/query",
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
        "/api/query",
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
        "/api/query",
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
        "/api/query",
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


def test_query_components_used_reports_reranker_off_for_dense_mode(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "dense",
            "generate": False,
            "overrides": {
                "rerank_enabled": True,
                "rerank_model_name": "BAAI/bge-reranker-v2-m3",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["components_used"]["reranker"] == "off"


def test_query_components_used_reports_reranker_off_for_sparse_mode(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "sparse",
            "generate": False,
            "overrides": {
                "rerank_enabled": True,
                "rerank_model_name": "BAAI/bge-reranker-v2-m3",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["components_used"]["reranker"] == "off"


def test_query_components_used_reports_reranker_for_hybrid_mode(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {
                "rerank_enabled": True,
                "rerank_model_name": "BAAI/bge-reranker-v2-m3",
            },
        },
    )

    assert response.status_code == 200
    assert (
        response.json()["components_used"]["reranker"]
        == "BAAI/bge-reranker-v2-m3"
    )


def test_query_endpoint_accepts_rerank_model_name_override(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
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
        "/api/query",
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


def test_query_openai_override_defaults_to_gpt4o_and_rag_key_env(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RAG_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("RAG_OPENAI_OPT_IN", "1")
    captured: dict[str, Settings] = {}

    def capturing_retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        captured["retriever"] = settings
        return FakeRetriever(mode=mode)

    def capturing_generator_factory(settings: Settings) -> FakeGenerator:
        captured["generator"] = settings
        return FakeGenerator()

    app = create_app(
        settings=Settings(output_dir=tmp_path / "artifacts"),
        retriever_factory=capturing_retriever_factory,
        generator_factory=capturing_generator_factory,
    )
    client = TestClient(app)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": True,
            "overrides": {"generation_provider": "openai"},
        },
    )

    assert response.status_code == 200
    assert "retriever" in captured
    assert "generator" in captured
    settings = captured["generator"]
    assert settings.generation_provider == "openai"
    assert settings.generation_model_name == "gpt-4o"
    assert settings.generation_api_key_env == "RAG_OPENAI_API_KEY"


def test_query_openai_override_clears_stale_generation_api_url(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RAG_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("RAG_OPENAI_OPT_IN", "1")
    captured: dict[str, Settings] = {}

    def capturing_retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        captured["retriever"] = settings
        return FakeRetriever(mode=mode)

    def capturing_generator_factory(settings: Settings) -> FakeGenerator:
        captured["generator"] = settings
        return FakeGenerator()

    app = create_app(
        settings=Settings(
            output_dir=tmp_path / "artifacts",
            generation_api_url="http://localhost:11434/v1/chat/completions",
        ),
        retriever_factory=capturing_retriever_factory,
        generator_factory=capturing_generator_factory,
    )
    client = TestClient(app)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": True,
            "overrides": {"generation_provider": "openai"},
        },
    )

    assert response.status_code == 200
    assert "generator" in captured
    settings = captured["generator"]
    assert settings.generation_provider == "openai"
    assert settings.generation_api_url is None


def test_query_openai_override_respects_explicit_model_name(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("RAG_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("RAG_OPENAI_OPT_IN", "1")
    captured: dict[str, Settings] = {}

    def capturing_retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        captured["retriever"] = settings
        return FakeRetriever(mode=mode)

    def capturing_generator_factory(settings: Settings) -> FakeGenerator:
        captured["generator"] = settings
        return FakeGenerator()

    app = create_app(
        settings=Settings(output_dir=tmp_path / "artifacts"),
        retriever_factory=capturing_retriever_factory,
        generator_factory=capturing_generator_factory,
    )
    client = TestClient(app)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": True,
            "overrides": {
                "generation_provider": "openai",
                "generation_model_name": "gpt-4o-mini",
            },
        },
    )

    assert response.status_code == 200
    assert "retriever" in captured
    assert "generator" in captured
    settings = captured["generator"]
    assert settings.generation_provider == "openai"
    assert settings.generation_model_name == "gpt-4o-mini"
    assert settings.generation_api_key_env == "RAG_OPENAI_API_KEY"


def test_query_endpoint_rejects_unknown_override_key(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
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


def test_query_rejects_non_boolean_rerank_enabled_override(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"rerank_enabled": "false"},
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "rerank_enabled" in detail
    assert "str" in detail


def test_query_rejects_int_for_rerank_enabled_override(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"rerank_enabled": 1},
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "rerank_enabled" in detail
    assert "int" in detail


def test_query_rejects_non_string_rerank_model_name_override(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"rerank_model_name": 42},
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "rerank_model_name" in detail
    assert "int" in detail


def test_query_rejects_non_string_generation_provider_override(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"generation_provider": None},
        },
    )

    assert response.status_code == 422
    assert "generation_provider" in response.json()["detail"]


def test_query_accepts_valid_typed_overrides(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {
                "rerank_enabled": False,
                "rerank_model_name": "BAAI/bge-reranker-v2-m3",
                "generation_provider": "heuristic",
                "generation_model_name": "local-grounded-heuristic",
            },
        },
    )

    assert response.status_code == 200


def test_query_endpoint_passes_collection_override_to_retriever_factory(tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    def capturing_retriever_factory(settings: Settings, mode: Mode) -> FakeRetriever:
        captured["collection"] = settings.qdrant_collection
        return FakeRetriever(mode=mode)

    client = _client(tmp_path, retriever_factory=capturing_retriever_factory)

    response = client.post(
        "/api/query",
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
        "/api/query",
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
        "/api/query",
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


def test_query_rejects_unsupported_generation_provider_value(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"generation_provider": "bogus"},
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "generation_provider" in detail
    assert "bogus" in detail
    assert "heuristic" in detail
    assert "http_json" in detail
    assert "openai" in detail


def test_query_accepts_http_json_generation_provider_override(tmp_path: Path) -> None:
    client = _client(tmp_path)

    response = client.post(
        "/api/query",
        json={
            "query": "What is Paris?",
            "top_k": 1,
            "mode": "hybrid",
            "generate": False,
            "overrides": {"generation_provider": "http_json"},
        },
    )

    assert response.status_code == 200


def test_all_api_routes_are_namespaced_under_api_prefix(tmp_path: Path) -> None:
    """Regression guard for VOI-302: every non-SPA route must live under /api/*.

    VOI-293 P1-F shipped a frontend that calls /query, but Vite's dev proxy
    only forwards /api/*. The mismatch broke /ask in production. This test
    ensures no future route lands at the root path again.
    """
    from starlette.routing import Mount

    app = create_app(settings=Settings(output_dir=tmp_path / "artifacts"))
    for route in app.routes:
        path = getattr(route, "path", None)
        if path is None:
            continue
        # SPA mount, favicon, FastAPI docs, and the StaticFiles catch-all are
        # allowed at root. Everything else MUST be under /api/*.
        if path in {
            "/",
            "/favicon.ico",
            "/openapi.json",
            "/docs",
            "/docs/oauth2-redirect",
            "/redoc",
        }:
            continue
        if isinstance(route, Mount):
            # Static-asset mounts (e.g. /assets via StaticFiles) and the
            # SPA fallback are not /api/* endpoints; the SPA test above
            # already covers the fallback shape.
            continue
        if path.startswith("/{") or path == "/{full_path:path}":
            # SPA catch-all path-parameter route.
            continue
        assert path.startswith("/api/"), (
            f"Route {path!r} is not under /api/*; Vite dev proxy will 404. "
            f"Add it under /api/* or extend the allowed-non-api list."
        )


def test_suite_run_endpoint_launches_background_run_and_writes_scoreboard(
    tmp_path: Path,
) -> None:
    import datetime
    import json
    import time

    from src.evaluation import eval_suite
    from src.evaluation.eval_suite import DatasetRef, EvalSuite, SuiteConfig, SuiteEntry
    from src.evaluation.eval_suite_registry import EvalSuiteRegistry
    from src.evaluation.scoreboard import load_scoreboard

    settings = Settings(output_dir=tmp_path / "artifacts")
    scoreboard_path = tmp_path / "scoreboard.json"
    eval_questions_dir = settings.output_dir / "eval_questions"
    eval_questions_dir.mkdir(parents=True)
    (eval_questions_dir / "nq.json").write_text(
        json.dumps(
            [
                {
                    "query_id": "q1",
                    "query": "What is Paris?",
                    "gold_answers": ["Grounded answer for What is Paris?"],
                    "supporting_passage_ids": ["hybrid-1"],
                    "notes": None,
                }
            ]
        ),
        encoding="utf-8",
    )
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)  # noqa: UP017
    suite = EvalSuite(
        id="suite-1",
        name="Suite One",
        description=None,
        created_at=now,
        updated_at=now,
        config=SuiteConfig(
            benchmark="nq",
            collection="nq_passages_qwen3_embed_4b",
            mode="hybrid",
            top_k=5,
            reranker="off",
            generator="heuristic",
        ),
        entries=[
            SuiteEntry(
                id="entry-1",
                question="What is Paris?",
                gold_answers=["Grounded answer for What is Paris?"],
                source="dataset",
                dataset_ref=DatasetRef(benchmark="nq", question_id="q1"),
            )
        ],
    )
    eval_suite.save_suite(suite, settings.output_dir / "eval_suites")
    registry = EvalSuiteRegistry()
    app = create_app(
        settings=settings,
        retriever_factory=lambda settings, mode: FakeRetriever(mode=mode),
        generator_factory=lambda settings: FakeGenerator(),
        scoreboard_path_factory=lambda: scoreboard_path,
        run_registry=registry,
    )
    client = TestClient(app)

    start_response = client.post("/api/suites/suite-1/runs")

    assert start_response.status_code == 202
    run_id = start_response.json()["run_id"]
    assert start_response.json()["suite_id"] == "suite-1"
    assert start_response.json()["total"] == 1

    status_payload = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        status_response = client.get(f"/api/suites/runs/{run_id}")
        assert status_response.status_code == 200
        status_payload = status_response.json()
        if status_payload["status"] in {"done", "error"}:
            break
        time.sleep(0.05)

    assert status_payload is not None
    assert status_payload["status"] == "done"
    assert status_payload["completed"] == 1
    scoreboard = load_scoreboard(scoreboard_path)
    assert len(scoreboard.rows) == 1
    row = scoreboard.rows[0]
    assert row.suite_id == "suite-1"
    assert row.run_id == run_id
    assert row.launched_via == "ui"
    assert row.num_questions == 1
    assert row.retriever_metrics.recall_at_5 == 1.0


def test_suite_run_endpoint_rejects_missing_empty_and_authored_only_suites(
    tmp_path: Path,
) -> None:
    import datetime

    from src.evaluation import eval_suite
    from src.evaluation.eval_suite import EvalSuite, SuiteConfig, SuiteEntry
    from src.evaluation.eval_suite_registry import EvalSuiteRegistry

    settings = Settings(output_dir=tmp_path / "artifacts")
    registry = EvalSuiteRegistry()
    app = create_app(
        settings=settings,
        retriever_factory=lambda settings, mode: FakeRetriever(mode=mode),
        generator_factory=lambda settings: FakeGenerator(),
        run_registry=registry,
    )
    client = TestClient(app)

    missing_response = client.post("/api/suites/missing/runs")

    assert missing_response.status_code == 404

    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)  # noqa: UP017
    empty_suite = EvalSuite(
        id="empty-suite",
        name="Empty Suite",
        description=None,
        created_at=now,
        updated_at=now,
        config=SuiteConfig(
            benchmark="nq",
            collection="nq_passages_qwen3_embed_4b",
            mode="hybrid",
            top_k=5,
            reranker="off",
            generator="heuristic",
        ),
        entries=[],
    )
    authored_suite = empty_suite.model_copy(
        update={
            "id": "authored-suite",
            "name": "Authored Suite",
            "entries": [
                SuiteEntry(
                    id="entry-1",
                    question="What is Paris?",
                    gold_answers=["Paris"],
                    source="authored",
                    dataset_ref=None,
                )
            ],
        }
    )
    eval_suite.save_suite(empty_suite, settings.output_dir / "eval_suites")
    eval_suite.save_suite(authored_suite, settings.output_dir / "eval_suites")

    empty_response = client.post("/api/suites/empty-suite/runs")
    authored_response = client.post("/api/suites/authored-suite/runs")

    assert empty_response.status_code == 422
    assert empty_response.json()["detail"] == "Suite has no entries."
    assert authored_response.status_code == 422
    assert "supporting-passage gold" in authored_response.json()["detail"]


def test_suite_run_status_endpoint_returns_404_for_unknown_run(tmp_path: Path) -> None:
    from src.evaluation.eval_suite_registry import EvalSuiteRegistry

    app = create_app(
        settings=Settings(output_dir=tmp_path / "artifacts"),
        retriever_factory=lambda settings, mode: FakeRetriever(mode=mode),
        generator_factory=lambda settings: FakeGenerator(),
        run_registry=EvalSuiteRegistry(),
    )
    client = TestClient(app)

    response = client.get("/api/suites/runs/missing")

    assert response.status_code == 404
