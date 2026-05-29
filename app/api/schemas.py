"""HTTP-facing schemas for the Milestone 7 API."""

from __future__ import annotations

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.evaluation.eval_suite import (
    DatasetRef,
    SuiteConfig,
    SuiteEntry,
)
from src.evaluation.eval_suite import (
    EvalSuite as EvalSuite,
)
from src.retrieval.qdrant_retrievers import Mode


class RetrieveRequest(BaseModel):
    """Request body for retrieval-only diagnostics."""

    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=500)
    mode: Mode = "hybrid"


class QueryApiRequest(RetrieveRequest):
    """Request body for retrieve plus optional grounded generation."""

    generate: bool = True
    collection: str | None = None
    overrides: dict[str, Any] | None = None
    gold_answers: list[str] | None = None
    supporting_passage_ids: list[str] | None = None
    query_id: str | None = None


class EvalQuestion(BaseModel):
    """One curated question for interactive evaluation."""

    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    gold_answers: list[str]
    supporting_passage_ids: list[str]
    notes: str | None = None


class EvalQuestionsResponse(BaseModel):
    """Curated evaluation questions for one benchmark."""

    benchmark: Literal["nq", "hotpotqa", "2wikimhqa", "musique"]
    questions: list[EvalQuestion]


class SuiteSummary(BaseModel):
    """Summary payload for listing evaluation suites."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    config: SuiteConfig
    entry_count: int


class SuiteDetail(BaseModel):
    """Full evaluation suite payload."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime
    config: SuiteConfig
    entries: list[SuiteEntry]


class CreateSuiteRequest(BaseModel):
    """Request body for creating an evaluation suite."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str | None = None
    config: SuiteConfig


class UpdateSuiteRequest(BaseModel):
    """Request body for updating evaluation suite metadata/config."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    config: SuiteConfig | None = None


class AddEntryRequest(BaseModel):
    """Request body for adding a question to an evaluation suite."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1)
    gold_answers: list[str] = Field(default_factory=list)
    source: Literal["dataset", "authored"]
    dataset_ref: DatasetRef | None = None
    notes: str | None = None


class UpdateEntryRequest(BaseModel):
    """Request body for updating a suite question entry."""

    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, min_length=1)
    gold_answers: list[str] | None = None
    source: Literal["dataset", "authored"] | None = None
    dataset_ref: DatasetRef | None = None
    notes: str | None = None


class RunStatusResponse(BaseModel):
    """Status payload for an evaluation-suite run."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    suite_id: str
    status: Literal["queued", "running", "done", "error", "cancelled"]
    completed: int
    total: int
    started_at: datetime.datetime | None = None
    finished_at: datetime.datetime | None = None
    error: str | None = None


class ComponentChoice(BaseModel):
    """Named component option exposed to clients."""

    name: str
    label: str


class GeneratorChoice(ComponentChoice):
    """Named generation option with availability metadata."""

    enabled: bool
    disabled_reason: str | None = None


class CollectionChoice(BaseModel):
    """Benchmark-to-collection option exposed to clients."""

    benchmark: Literal["nq", "hotpotqa", "2wikimhqa", "musique"]
    collection: str


class ComponentsResponse(BaseModel):
    """Interactive query component options."""

    modes: list[Mode]
    top_k_choices: list[int]
    rerankers: list[ComponentChoice]
    generators: list[GeneratorChoice]
    collections: list[CollectionChoice]
    openai_enabled: bool
    embedder: str


class ArtifactStatus(BaseModel):
    """Safe existence metadata for local runtime artifacts."""

    path: str
    exists: bool


class HealthResponse(BaseModel):
    """Minimal health response with no secret-bearing fields."""

    status: Literal["ok"] = "ok"
    service: str = "rag-nq-showcase"


class RootResponse(BaseModel):
    """Discoverable landing payload for browser visits to the API root."""

    service: str = "rag-nq-showcase"
    docs_url: str = "/docs"
    health_url: str = "/health"
    config_url: str = "/config"
    retrieve_url: str = "/retrieve"
    query_url: str = "/query"


class RetrievalConfigMetadata(BaseModel):
    """Safe retrieval settings exposed for diagnostics."""

    retrieve_k: int
    rerank_k: int | None
    rerank_enabled: bool
    rerank_model_name: str
    rerank_context_token_budget: int
    retrieval_dedupe_enabled: bool
    hybrid_rrf_k: int
    hybrid_dense_weight: float
    hybrid_sparse_weight: float


class GenerationConfigMetadata(BaseModel):
    """Safe generation settings exposed for diagnostics."""

    generation_provider: str
    generation_model_name: str
    generation_temperature: float
    generation_max_tokens: int
    generation_timeout_seconds: float
    generation_context_token_budget: int
    generation_min_citations: int
    generation_api_configured: bool
    generation_api_key_env_configured: bool


class RuntimeConfigResponse(BaseModel):
    """Safe runtime metadata exposed by ``/config``."""

    dataset_name: str
    dataset_split: str
    embedder_name: str
    qdrant_url: str
    qdrant_collection: str
    qdrant_vector_name: str
    qdrant_sparse_vector_name: str
    retrieval: RetrievalConfigMetadata
    generation: GenerationConfigMetadata
    artifacts: dict[str, ArtifactStatus]
