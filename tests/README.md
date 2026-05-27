# Test Suite Taxonomy

The default suite is intentionally fast and deterministic. Many tests use fakes because they are
contract tests, not real-system quality evaluations.

## Layers

- `unit`: isolated logic such as schema validation, metric math, prompt construction, parsing,
  and deterministic helper functions.
- `contract`: stable boundaries such as protocols, API payloads, trace shapes, and provider request
  formatting. Fakes are usually appropriate here.
- `integration`: multiple local components composed together, such as fixture ingestion through
  indexing and in-memory Qdrant retrieval.
- `eval`: report-building and evaluation harness tests. These validate the harness by default,
  not necessarily live model quality.
- `live_network`: opt-in tests that hit external network services.
- `live_llm`: opt-in tests that call configured LLM providers.
- `local_server`: opt-in tests that require a running local API/server.

## When Fakes Are Appropriate

Use fakes for:

- protocol conformance and response-shape checks;
- deterministic graph/orchestration invariants;
- retriever/generator failures that need predictable exceptions;
- LLM output parsing, citation validation, and typed post-processing.

Avoid treating fake-backed tests as proof of:

- real retrieval quality on the NQ-derived index;
- real Pydantic AI structured-output compliance;
- real grounded-answer quality;
- latency, rate limits, 503s, or provider failures.

Those belong in opt-in evals that write machine-readable reports under `artifacts/`.

## Common Commands

```bash
uv run pytest tests
uv run pytest -m integration
RAG_RUN_LIVE_NETWORK_TESTS=1 uv run pytest -m live_network
RAG_RUN_LIVE_LLM_TESTS=1 uv run pytest -m live_llm
RAG_RUN_LOCAL_SERVER_TESTS=1 uv run pytest -m local_server
```

Agentic QA quality should be checked with:

```bash
uv run python -m src.scripts.eval_agentic_reasoning --max-queries 20
```
