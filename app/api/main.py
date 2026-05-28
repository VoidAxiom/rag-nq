"""FastAPI app for Milestone 7 retrieval and grounded query endpoints."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import TypeAdapter, ValidationError
from starlette.staticfiles import StaticFiles

from app.api.schemas import (
    ArtifactStatus,
    CollectionChoice,
    ComponentChoice,
    ComponentsResponse,
    EvalQuestion,
    EvalQuestionsResponse,
    GenerationConfigMetadata,
    GeneratorChoice,
    HealthResponse,
    QueryApiRequest,
    RetrievalConfigMetadata,
    RetrieveRequest,
    RootResponse,
    RuntimeConfigResponse,
)
from src.config.settings import Settings
from src.evaluation.per_query_metrics import (
    compute_em,
    compute_f1,
    compute_supporting_fact_recall_at_k,
)
from src.evaluation.scoreboard import SCOREBOARD_PATH, Scoreboard, load_scoreboard
from src.generation.grounded import GroundedGenerator
from src.models.query_schemas import (
    ComponentSet,
    GroundedAnswer,
    LatencyBreakdown,
    PassageHit,
    PerQueryMetrics,
    QueryResponse,
    RetrievalMetrics,
)
from src.observability.logging_setup import setup_logging
from src.retrieval.qdrant_retrievers import Mode, QdrantModeRetriever

LOGGER = logging.getLogger(__name__)
VALID_EVAL_BENCHMARKS = {"nq", "hotpotqa", "2wikimhqa", "musique"}
TIER_1_OVERRIDE_KEYS = {
    "rerank_enabled",
    "rerank_model_name",
    "generation_provider",
    "generation_model_name",
}
_TIER_1_OVERRIDE_TYPES: dict[str, type] = {
    "rerank_enabled": bool,
    "rerank_model_name": str,
    "generation_provider": str,
    "generation_model_name": str,
}
_SUPPORTED_GENERATION_PROVIDERS: frozenset[str] = frozenset(
    {"heuristic", "http_json", "openai"}
)
OPENAI_OVERRIDE_ERROR = (
    "OpenAI generator requires both RAG_OPENAI_API_KEY and RAG_OPENAI_OPT_IN=1 to be set."
)
# mirrors src/ingestion/hotpotqa_loader.py::_COLLECTION_NAME — keep in sync
HOTPOTQA_COLLECTION = "hotpotqa_passages_qwen3_embed_4b"
# mirrors src/ingestion/twowikimhqa_loader.py::_COLLECTION_NAME — keep in sync
TWOWIKIMHQA_COLLECTION = "2wikimhqa_passages_qwen3_embed_4b"
# mirrors src/ingestion/musique_loader.py::_COLLECTION_NAME — keep in sync
MUSIQUE_COLLECTION = "musique_passages_qwen3_embed_4b"


class ApiRetriever(Protocol):
    """Retriever interface used by API endpoints and tests."""

    last_retrieval_metrics: RetrievalMetrics | None

    def retrieve(self, query: str, top_k: int) -> list[PassageHit]:
        """Return retrieved passage hits."""


class ApiGenerator(Protocol):
    """Grounded generator interface used by API endpoints and tests."""

    def generate(self, query: str, hits: list[PassageHit]) -> GroundedAnswer:
        """Return a grounded answer object."""


RetrieverFactory = Callable[[Settings, Mode], ApiRetriever]
GeneratorFactory = Callable[[Settings], ApiGenerator]
ScoreboardPathFactory = Callable[[], Path]


def create_app(
    *,
    settings: Settings | None = None,
    retriever_factory: RetrieverFactory | None = None,
    generator_factory: GeneratorFactory | None = None,
    scoreboard_path_factory: ScoreboardPathFactory | None = None,
) -> FastAPI:
    """Build the HTTP app with injectable dependencies for tests."""

    setup_logging()
    app_settings = settings or Settings.from_env()
    make_retriever = retriever_factory or _default_retriever_factory
    make_generator = generator_factory or _default_generator_factory

    app = FastAPI(
        title="RAG NQ Showcase API",
        version="0.1.0",
        description="Local API for retrieval diagnostics and grounded RAG queries.",
    )

    dist_path_env = os.environ.get("RAG_WEB_DIST_PATH")
    dist_path = Path(dist_path_env).expanduser().resolve() if dist_path_env else None
    spa_enabled = dist_path is not None and dist_path.is_dir()

    if not spa_enabled:
        @app.get("/", response_model=RootResponse)
        def root() -> RootResponse:
            return RootResponse()

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon() -> Response:
        return Response(status_code=204)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @app.get("/config", response_model=RuntimeConfigResponse)
    def config() -> RuntimeConfigResponse:
        return safe_runtime_config(app_settings)

    @app.post("/retrieve", response_model=QueryResponse)
    def retrieve(request: RetrieveRequest) -> QueryResponse:
        started_at = time.monotonic()
        try:
            retriever = make_retriever(app_settings, request.mode)
            hits = retriever.retrieve(request.query, top_k=request.top_k)
        except Exception as exc:
            LOGGER.exception("retrieval failed mode=%s", request.mode)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        metrics = retriever.last_retrieval_metrics or RetrievalMetrics()
        LOGGER.info(
            "retrieve complete mode=%s top_k=%s hits=%s elapsed_seconds=%.3f",
            request.mode,
            request.top_k,
            len(hits),
            time.monotonic() - started_at,
        )
        return QueryResponse(
            query=request.query,
            retrieved_passages=hits,
            retrieval_metrics=metrics,
            grounded=None,
        )

    @app.post("/query", response_model=QueryResponse)
    def query(request: QueryApiRequest) -> QueryResponse:
        effective_settings = _build_effective_settings(app_settings, request)
        retrieval_started_at = time.monotonic()
        try:
            retriever = make_retriever(effective_settings, request.mode)
            hits = retriever.retrieve(request.query, top_k=request.top_k)
        except Exception as exc:
            LOGGER.exception("retrieval failed mode=%s", request.mode)
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        retrieval_wall_ms = (time.monotonic() - retrieval_started_at) * 1000.0
        retrieval_metrics = retriever.last_retrieval_metrics or RetrievalMetrics()
        retrieval_ms, rerank_ms = _retrieval_latency_ms(retrieval_metrics, retrieval_wall_ms)

        grounded: GroundedAnswer | None = None
        generation_ms = 0.0
        if request.generate:
            generation_started_at = time.monotonic()
            try:
                generator = make_generator(effective_settings)
                grounded = generator.generate(request.query, hits)
            except Exception as exc:
                LOGGER.exception("grounded generation failed")
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            generation_ms = (time.monotonic() - generation_started_at) * 1000.0

        latency = LatencyBreakdown(
            retrieval_ms=retrieval_ms,
            rerank_ms=rerank_ms,
            generation_ms=generation_ms,
            total_ms=retrieval_ms + rerank_ms + generation_ms,
        )
        return QueryResponse(
            query=request.query,
            retrieved_passages=hits,
            retrieval_metrics=retrieval_metrics,
            grounded=grounded,
            metrics=_per_query_metrics(request, grounded, hits),
            components_used=_components_used(effective_settings, request),
            latency_ms=latency,
            query_id=request.query_id,
        )

    @app.get("/api/eval_questions/{benchmark}", response_model=EvalQuestionsResponse)
    def eval_questions(benchmark: str) -> EvalQuestionsResponse:
        if benchmark not in VALID_EVAL_BENCHMARKS:
            raise HTTPException(status_code=404, detail=f"Unknown benchmark {benchmark!r}.")
        path = app_settings.output_dir / "eval_questions" / f"{benchmark}.json"
        if not path.is_file():
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Eval questions file not found at {path}. "
                    "P1-F curation step not run yet."
                ),
            )
        try:
            questions = TypeAdapter(list[EvalQuestion]).validate_json(
                path.read_text(encoding="utf-8")
            )
        except ValidationError as exc:
            LOGGER.exception("eval questions file is invalid path=%s", path)
            raise HTTPException(
                status_code=503,
                detail=f"Eval questions file at {path} is invalid: {exc}",
            ) from exc
        return EvalQuestionsResponse(benchmark=benchmark, questions=questions)

    @app.get("/api/components", response_model=ComponentsResponse)
    def components() -> ComponentsResponse:
        openai_enabled, disabled_reason = _openai_availability()
        return ComponentsResponse(
            modes=["dense", "sparse", "hybrid"],
            top_k_choices=[5, 10, 20, 50],
            rerankers=[
                ComponentChoice(
                    name="BAAI/bge-reranker-v2-m3",
                    label="BGE-v2-m3 (default)",
                ),
                ComponentChoice(
                    name="cross-encoder/ms-marco-MiniLM-L-6-v2",
                    label="MiniLM-L-6-v2 (fast)",
                ),
                ComponentChoice(name="off", label="No rerank"),
            ],
            generators=[
                GeneratorChoice(
                    name="heuristic",
                    label="Heuristic (local, default)",
                    enabled=True,
                ),
                GeneratorChoice(
                    name="openai",
                    label="OpenAI GPT-4o (locked unless env opt-in)",
                    enabled=openai_enabled,
                    disabled_reason=None if openai_enabled else disabled_reason,
                ),
            ],
            collections=[
                CollectionChoice(benchmark="nq", collection=app_settings.qdrant_collection),
                CollectionChoice(benchmark="hotpotqa", collection=HOTPOTQA_COLLECTION),
                CollectionChoice(benchmark="2wikimhqa", collection=TWOWIKIMHQA_COLLECTION),
                CollectionChoice(benchmark="musique", collection=MUSIQUE_COLLECTION),
            ],
            openai_enabled=openai_enabled,
            embedder=app_settings.embedder_name,
        )

    @app.get("/api/scoreboard", response_model=Scoreboard)
    def scoreboard() -> Scoreboard:
        path = scoreboard_path_factory() if scoreboard_path_factory else SCOREBOARD_PATH
        return load_scoreboard(path)

    if spa_enabled and dist_path is not None:
        assets_path = dist_path / "assets"
        if assets_path.is_dir():
            app.mount(
                "/assets",
                StaticFiles(directory=assets_path),
                name="web-assets",
            )

        @app.get(
            "/{full_path:path}",
            include_in_schema=False,
            response_model=None,
        )
        def web_app(full_path: str) -> FileResponse | Response:
            if full_path.startswith("api/"):
                return Response(status_code=404)
            if full_path.startswith("assets/"):
                return Response(status_code=404)

            requested_path = (dist_path / full_path).resolve()
            if requested_path != dist_path and dist_path not in requested_path.parents:
                return Response(status_code=404)
            if requested_path.is_file():
                return FileResponse(requested_path)

            index_path = dist_path / "index.html"
            if index_path.is_file():
                return FileResponse(index_path, media_type="text/html")
            return Response(status_code=404)

    return app


def safe_runtime_config(settings: Settings) -> RuntimeConfigResponse:
    """Return runtime metadata that excludes secrets and raw environment values."""

    artifacts = {
        "raw_dataset": _artifact_status(settings.output_dir / settings.raw_dataset_jsonl),
        "index_chunks": _artifact_status(settings.index_chunks_path),
        "chunk_manifest": _artifact_status(settings.chunk_manifest_path),
        "dense_checkpoint": _artifact_status(settings.dense_checkpoint_path),
        "sparse_checkpoint": _artifact_status(settings.sparse_checkpoint_path),
        "sparse_pass1": _artifact_status(settings.sparse_pass1_path),
        "sparse_manifest": _artifact_status(settings.sparse_manifest_path),
        "retrieval_eval": _artifact_status(settings.output_dir / "retrieval_eval.json"),
    }
    generation_api_configured = bool(settings.generation_api_url)
    generation_key_env_configured = bool(settings.generation_api_key_env)
    return RuntimeConfigResponse(
        dataset_name=settings.dataset_name,
        dataset_split=settings.dataset_split,
        embedder_name=settings.embedder_name,
        qdrant_url=_safe_url(settings.qdrant_url),
        qdrant_collection=settings.qdrant_collection,
        qdrant_vector_name=settings.qdrant_vector_name,
        qdrant_sparse_vector_name=settings.qdrant_sparse_vector_name,
        retrieval=RetrievalConfigMetadata(
            retrieve_k=settings.retrieve_k,
            rerank_k=settings.rerank_k,
            rerank_enabled=settings.rerank_enabled,
            rerank_model_name=settings.rerank_model_name,
            rerank_context_token_budget=settings.rerank_context_token_budget,
            retrieval_dedupe_enabled=settings.retrieval_dedupe_enabled,
            hybrid_rrf_k=settings.hybrid_rrf_k,
            hybrid_dense_weight=settings.hybrid_dense_weight,
            hybrid_sparse_weight=settings.hybrid_sparse_weight,
        ),
        generation=GenerationConfigMetadata(
            generation_provider=settings.generation_provider,
            generation_model_name=settings.generation_model_name,
            generation_temperature=settings.generation_temperature,
            generation_max_tokens=settings.generation_max_tokens,
            generation_timeout_seconds=settings.generation_timeout_seconds,
            generation_context_token_budget=settings.generation_context_token_budget,
            generation_min_citations=settings.generation_min_citations,
            generation_api_configured=generation_api_configured,
            generation_api_key_env_configured=generation_key_env_configured,
        ),
        artifacts=artifacts,
    )


def _artifact_status(path: Path) -> ArtifactStatus:
    return ArtifactStatus(path=str(path), exists=path.is_file())


def _build_effective_settings(app_settings: Settings, request: QueryApiRequest) -> Settings:
    update_dict: dict[str, Any] = {}
    if request.collection is not None:
        update_dict["qdrant_collection"] = request.collection

    overrides = request.overrides or {}
    invalid_keys = sorted(set(overrides) - TIER_1_OVERRIDE_KEYS)
    if invalid_keys:
        rejected = ", ".join(invalid_keys)
        raise HTTPException(status_code=422, detail=f"Unsupported override key(s): {rejected}")

    for key, expected_type in _TIER_1_OVERRIDE_TYPES.items():
        if key in overrides:
            value = overrides[key]
            if expected_type is bool:
                if not isinstance(value, bool):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Override {key!r} must be a boolean; "
                            f"got {type(value).__name__}."
                        ),
                    )
            elif not isinstance(value, expected_type):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Override {key!r} must be a {expected_type.__name__}; "
                        f"got {type(value).__name__}."
                    ),
                )

    if "generation_provider" in overrides:
        provider_value = overrides["generation_provider"]
        if provider_value not in _SUPPORTED_GENERATION_PROVIDERS:
            supported = ", ".join(sorted(_SUPPORTED_GENERATION_PROVIDERS))
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Override 'generation_provider' must be one of: {supported}; "
                    f"got {provider_value!r}."
                ),
            )

    if overrides.get("generation_provider") == "openai":
        openai_enabled, _disabled_reason = _openai_availability()
        if not openai_enabled:
            raise HTTPException(status_code=422, detail=OPENAI_OVERRIDE_ERROR)

    if "rerank_enabled" in overrides:
        update_dict["rerank_enabled"] = overrides["rerank_enabled"]
    if "rerank_model_name" in overrides:
        rerank_model_name = str(overrides["rerank_model_name"])
        if rerank_model_name == "off":
            update_dict["rerank_enabled"] = False
        else:
            update_dict["rerank_model_name"] = rerank_model_name
            if "rerank_enabled" not in overrides:
                update_dict["rerank_enabled"] = True
    if "generation_provider" in overrides:
        provider = overrides["generation_provider"]
        update_dict["generation_provider"] = provider
        if provider == "openai":
            # Wire defaults that match /api/components's documented opt-in
            # (RAG_OPENAI_API_KEY + RAG_OPENAI_OPT_IN=1) and the dropdown
            # label ("OpenAI GPT-4o"); explicit overrides still win below.
            # generation_api_url is explicitly nulled to prevent a stale
            # http_json env URL from receiving the OpenAI bearer token.
            update_dict["generation_model_name"] = "gpt-4o"
            update_dict["generation_api_key_env"] = "RAG_OPENAI_API_KEY"
            update_dict["generation_api_url"] = None
    if "generation_model_name" in overrides:
        update_dict["generation_model_name"] = overrides["generation_model_name"]

    return app_settings.model_copy(update=update_dict)


def _retrieval_latency_ms(metrics: RetrievalMetrics, fallback_ms: float) -> tuple[float, float]:
    timings = metrics.timings
    if timings is None:
        return fallback_ms, 0.0
    rerank_ms = timings.rerank_seconds * 1000.0
    retrieval_ms = (
        timings.retrieve_seconds + timings.fusion_seconds + timings.dedupe_seconds
    ) * 1000.0
    if retrieval_ms == 0.0 and timings.total_seconds > 0.0:
        retrieval_ms = max((timings.total_seconds * 1000.0) - rerank_ms, 0.0)
    return retrieval_ms, rerank_ms


def _per_query_metrics(
    request: QueryApiRequest,
    grounded: GroundedAnswer | None,
    hits: list[PassageHit],
) -> PerQueryMetrics | None:
    if request.gold_answers is None and request.supporting_passage_ids is None:
        return None

    metrics = PerQueryMetrics()
    if request.gold_answers is not None and grounded is not None and not grounded.abstained:
        metrics.em = compute_em(grounded.answer, request.gold_answers)
        metrics.f1 = compute_f1(grounded.answer, request.gold_answers)
    if request.supporting_passage_ids is not None:
        retrieved_point_ids = [hit.point_id for hit in hits]
        k_used = request.top_k
        metrics.supporting_fact_recall_at_k = compute_supporting_fact_recall_at_k(
            retrieved_point_ids,
            request.supporting_passage_ids,
            k_used,
        )
        metrics.k_used = k_used
    return metrics


def _components_used(settings: Settings, request: QueryApiRequest) -> ComponentSet:
    rerank_applies = request.mode == "hybrid" and settings.rerank_enabled
    return ComponentSet(
        mode=request.mode,
        top_k=request.top_k,
        reranker=settings.rerank_model_name if rerank_applies else "off",
        generator=settings.generation_provider,
        embedder=settings.embedder_name,
        collection=settings.qdrant_collection,
    )


def _openai_availability() -> tuple[bool, str | None]:
    missing: list[str] = []
    if not os.environ.get("RAG_OPENAI_API_KEY"):
        missing.append("RAG_OPENAI_API_KEY")
    if os.environ.get("RAG_OPENAI_OPT_IN") != "1":
        missing.append("RAG_OPENAI_OPT_IN=1")
    if missing:
        return False, f"Missing {' and '.join(missing)}."
    return True, None


def _safe_url(value: str) -> str:
    parsed = urlsplit(value)
    if not parsed.hostname:
        return value
    netloc = parsed.hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _default_retriever_factory(settings: Settings, mode: Mode) -> ApiRetriever:
    return QdrantModeRetriever(settings=settings, mode=mode)


def _default_generator_factory(settings: Settings) -> ApiGenerator:
    return GroundedGenerator(settings=settings)


app = create_app()
