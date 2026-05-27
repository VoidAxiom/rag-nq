# RAG NQ Showcase

Local RAG demo on `sentence-transformers/NQ-retrieval` with Qdrant retrieval,
FastAPI endpoints, and a Vite + React + TypeScript web UI.

## Setup

```bash
cd rag-nq-showcase
uv sync
cp .env.example .env
```

Edit `.env` only if you need to override defaults such as `RAG_QDRANT_URL`,
`RAG_QDRANT_COLLECTION`, or generation provider settings.

## Run Qdrant

```bash
docker compose up -d
uv run python -m src.scripts.doctor
```

To stop Qdrant without deleting stored vectors:

```bash
docker compose stop
```

## Build Indexes

Use the all-in-one command for a normal local run:

```bash
uv run python -m src.scripts.build_indexes
```

Or run the stages explicitly:

```bash
uv run python -m src.ingestion.ingest_raw
uv run python -m src.scripts.ingest_chunks
uv run python -m src.scripts.index_dense
uv run python -m src.scripts.index_sparse
```

For a smaller smoke-test corpus, set `RAG_MAX_PASSAGES` in `.env` before
building indexes.

## Run the API

```bash
uv run uvicorn app.api.main:app --reload
```

Open:

- API docs: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`
- Config: `http://127.0.0.1:8000/config`

Example retrieval request:

```bash
curl -s http://127.0.0.1:8000/retrieve \
  -H "Content-Type: application/json" \
  -d '{"query":"What is the capital of France?","mode":"hybrid","top_k":5}' \
  | python -m json.tool
```

Example query request:

```bash
curl -s http://127.0.0.1:8000/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What is the capital of France?","mode":"hybrid","top_k":5,"generate":true}' \
  | python -m json.tool
```

## Run the Web UI

Two modes — pick one.

**Dev (with hot reload, Vite proxy → FastAPI):**

```bash
cd app/web
npm install   # first time only
npm run dev
```

Then open `http://localhost:5173`. Vite proxies `/api/*` to FastAPI on
`http://127.0.0.1:8000`, so start the API in a separate terminal first.

**Production (FastAPI serves built bundle):**

```bash
docker compose up -d qdrant
(cd app/web && npm install && npm run build)
RAG_WEB_DIST_PATH=app/web/dist uv run uvicorn app.api.main:app
```

Then open `http://127.0.0.1:8000`. FastAPI serves the SPA at `/` and the
JSON API at `/api/*`. The `(cd app/web && ...)` subshell keeps the outer
shell at the repo root so `uvicorn`'s Python import path resolves
`app.api.main` correctly and the `RAG_WEB_DIST_PATH` relative path
resolves to `<repo>/app/web/dist`.

Pages (more added per phase):

- `/` — Home / Ask
- `/scoreboard` — master sortable table reading `GET /api/scoreboard`

## Evaluate Retrieval

```bash
uv run python -m src.scripts.eval_retrieval \
  --k-values 1,5,10,20 \
  --modes dense,sparse,hybrid \
  --max-queries 200 \
  --output artifacts/retrieval_eval.json
```

## Run Tests and Lint

```bash
uv run pytest
uv run ruff check .
```
