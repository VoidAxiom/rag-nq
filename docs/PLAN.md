# rag_nq — Source of Truth (PLAN.md)

> This document is the **authoritative source of truth** for the `rag_nq`
> project. Per `CLAUDE.md` § "Spec authoring — load-bearing discipline",
> every packet `spec.md` MUST pull-quote the relevant section of this
> file verbatim. If the spec and this file diverge, this file wins and
> the spec is rewritten. If this file needs to change, change it here
> first, then re-author affected packet specs.

---

## §1 Mission

Demonstrate a **local-only, graph-augmented, iteratively-reasoning,
self-corrective RAG stack** on a MacBook M2 Max that pushes toward
published SOTA on the **multi-hop QA frontier** — where current open
RAG systems fall over.

Multi-hop is the load-bearing axis. Single-hop NQ stays as the fast
lane and the humility baseline (proves we didn't break what already
works). The entire stack runs locally; the showcase is reproducible by
anyone cloning the repo and running `docker compose up` + one
indexing script + `npm run dev` (or `npm run build` + `uvicorn`).

### Hero claim

Stack four published techniques into a super-additive pipeline:

1. **HippoRAG 2** graph retrieval (passage+phrase KG, Personalized
   PageRank, recognition-memory filtering).
2. **Adaptive-RAG** router (3-way classifier: no-retrieve /
   single-hop / multi-hop).
3. **Search-o1**-style iterative reasoning loop (`<search_query>` /
   `<search_result>` tokens, "Reason-in-Documents" summarization).
4. **CRAG**-style retrieval evaluator at each hop + per-sentence
   **NLI faithfulness verifier** on output.

Target deltas vs vanilla dense RAG and vs published HippoRAG 2:

| Benchmark | Vanilla dense | Published SOTA (HippoRAG 2) | Stack target |
|---|---:|---:|---:|
| **MuSiQue-Ans** (hardest, 2-4 hop compositional) | F1 ~20 | F1 48.6 | **F1 57-62** |
| **2WikiMultiHopQA** | R@5 ~76 | R@5 90.4 | **R@5 ≥ 90** |
| **HotpotQA fullwiki** | EM ~34 | EM ~50 (Search-o1 family) | **EM ≥ 50** |
| **NQ-dev (fast lane)** | strong baseline | — | strong Qwen3-Embed-4B + BGE-rerank baseline |

The "57-62" MuSiQue target is the project's headline number. It's
defensible from published deltas (HippoRAG 2 baseline 48.6 + iterative
reasoning gain typical of 5-8 F1 + CRAG gating typical of 2-3 F1 +
faithfulness verifier keeping EM honest under inspection). Whether we
land at 57, 60, or 62 is the experimental question the showcase
answers.

### Explicit non-goals

* Microsoft GraphRAG full pipeline (LazyGraphRAG only as a side-experiment,
  if any).
* RL-trained retrievers (R3-RAG, Search-R1) — RLHF infra overhead doesn't
  repay for a showcase.
* 70B+ local reasoning models — Qwen3-32B at 4-bit is the ceiling we'll
  touch; 14B is the working sweet spot.
* Single-hop-only "embedding bake-off" framing — covered as the fast lane,
  not the showcase center of gravity.
* Production-deployment hygiene (multi-env config, secrets management,
  deployment automation, backwards-compat shims, library packaging,
  rollback paths). Per `CLAUDE.md` § "Scope: production-realistic, NOT
  production-deployed".

---

## §2 Reference architecture

```
Query
  │
  ▼
[Adaptive-RAG Router]               DeBERTa-v3-base fine-tuned;
  │                                  3-way: no-retrieve / single-hop / multi-hop
  │
  ├─ no-retrieve  ──► Direct LLM answer (Qwen3-8B), abstain if uncertain
  │
  ├─ single-hop ──► [Hybrid + ColBERT rerank]
  │                  Qwen3-Embedding-4B (dense) ⊕ BM25 (sparse) → RRF →
  │                  jina-colbert-v2 MAX_SIM rerank → Top-K passages →
  │                  Qwen3-8B grounded answer
  │
  └─ multi-hop ───► [HippoRAG 2 graph retriever]
                     • passage+phrase KG built via OpenIE (Qwen3-14B premium
                       / GLiNER+GLiREL fast lane)
                     • query → triple matching via Qwen3-Embedding-4B
                     • recognition-memory filter (Qwen3-8B) drops irrelevant
                       triples
                     • Personalized PageRank over filtered seeds across
                       passage+phrase graph
                     • Top-N passages by PPR mass
                          │
                          ▼
                    [Search-o1 iterative reasoning loop]
                     • Qwen3-14B (MLX 4-bit) emits <search_query> tokens
                     • Each query → HippoRAG 2 retrieval
                     • "Reason-in-Documents" module summarizes retrieved
                       passages into reasoning stream (avoids context
                       dilution)
                     • Max 3 hops, configurable
                          │
                          ▼
                    [CRAG retrieval evaluator (per hop)]
                     • Lightweight evaluator scores top-K relevance
                     • {correct / incorrect / ambiguous} → action:
                       refine query / fallback (BM25 / different retriever)
                       / mix
                          │
                          ▼
                    [NLI faithfulness verifier (on final answer)]
                     • DeBERTa-v3-large-mnli per-sentence entailment
                     • Each answer sentence must be entailed by at least
                       one cited passage
                     • Failure → re-generate or abstain with reason
                          │
                          ▼
                    Answer + citations + (optional) abstention
```

The fast-lane and heavy-lane share the **same** retrieval primitives
(Qwen3-Embedding-4B, BM25, jina-colbert-v2, BGE-reranker-v2-m3) — only
the orchestration above them differs. This is intentional: the
showcase demonstrates that the same primitives serve both lanes,
routed appropriately.

---

## §3 Datasets

| Dataset | Role | Status | Notes |
|---|---|---|---|
| `sentence-transformers/NQ-retrieval` | NQ baseline (single-hop fast lane) | Already loaded: `nq_passages` (213K passages, MiniLM-L6 384-dim) and `nq_passages_bge_base_v15` (1.27M passages, BGE-base-v1.5 768-dim) | The BGE collection is leftover from a partial upgrade attempt; we'll standardize on a single corpus in P0 |
| **HotpotQA fullwiki** | 2-hop bridge + comparison multi-hop | To be loaded (P1) | Wikipedia-based; ~500K-passage standard eval subset |
| **2WikiMultiHopQA** | Comparison / inference / compositional / bridge-comparison with KB-triple paths | To be loaded (P1) | ~430K context paragraphs; structure matches HippoRAG 2's graph retrieval design |
| **MuSiQue-Ans** | 2-4 hop compositional, *hardest*, single-hop questions filtered by construction | To be loaded (P1) | ~100K passages; this is the hero benchmark |

NQ stays as the easy lane. The three multi-hop benchmarks are where
the showcase pushes. **MuSiQue is the diagnostic primary** — every
published gain on it (HippoRAG 2 +7 F1, PropRAG +2.8, BELLE +7.6)
reflects real architectural lift, not benchmark hacking.

Each multi-hop benchmark's eval-time context corpus is loaded into a
**separate Qdrant collection**. Total disk footprint estimate:
~25-40GB across NQ + the three multi-hop corpora + ColBERT
multivector indexes + KG storage.

### Held-out splits

Each dataset has a held-out **dev split** used for scoreboard
reporting. Eval is deterministic: seed-fixed, no leakage from training
into eval at any phase.

---

## §4 Local model stack

| Role | Primary model | Alt / fast-lane | Size on disk (Metal-friendly) |
|---|---|---|---:|
| Dense embedding (primary) | **Qwen3-Embedding-4B** (fp16) | Qwen3-Embedding-0.6B (fast-lane) | ~8 GB / ~1.5 GB |
| Sparse | **BM25** (rank-bm25 / Qdrant sparse) | — | trivial |
| Reranker | **BGE-reranker-v2-m3** (568M, fp16) | — | ~1.6 GB |
| Late interaction | **jina-colbert-v2** via FastEmbed | answerai-colbert-small-v1 | ~0.5 GB |
| Reasoning LLM (heavy lane) | **Qwen3-14B-Instruct** (MLX 4-bit) | Qwen3-8B for faster hops; Qwen3-32B 4-bit if explicit upgrade warranted | ~9 GB / ~5 GB / ~18 GB |
| Direct-answer LLM (single-hop / no-retrieve) | **Qwen3-8B-Instruct** (MLX 4-bit) | — | ~5 GB |
| Entity + relation extraction (fast-lane KG) | **GLiNER** + **GLiREL** (sub-100M each) | — | ~0.4 GB combined |
| Entity + relation extraction (premium KG) | **Qwen3-14B** with JSON-schema OpenIE prompts | — | reuses 9 GB above |
| Adaptive-RAG router | **DeBERTa-v3-base** fine-tuned | — | ~0.7 GB |
| Faithfulness verifier | **DeBERTa-v3-large-mnli** | Bespoke-MiniCheck-7B (heavier, higher quality) | ~1.5 GB / ~5 GB |

### RAM headroom (M2 Max, 64GB)

| Operating mode | Peak RAM | Headroom |
|---|---:|---:|
| Fast lane only (single-hop) | ~14 GB | ample |
| Heavy lane (multi-hop reasoning) | ~30 GB | ample |
| KG construction batch (overnight) | ~12 GB | ample |
| All models hot concurrently (worst case) | ~32-40 GB | ample |

Per-phase RAM verification is part of each phase's runtime acceptance gate.

### LLM API usage

Some phases use **GPT-4o-mini** (via OpenAI API) for one-time batch
jobs and milestone judge-LLM evaluations. All **runtime** calls in
the deployed stack are local. The API is used for:

* Premium-quality OpenIE KG construction on a "demo quality" subset
  (P3) — comparison against the local GLiNER+GLiREL fast lane.
* Synthetic training labels for the Adaptive-RAG router classifier (P4).
* Judge-LLM evaluation runs at phase-completion milestones (faithfulness,
  context precision/recall, answer correctness).
* Long-context comparison baseline (P7).

No per-query metered runtime spend. The deployed showcase is free to run.

---

## §5 Phase-by-phase plan

Each phase ships a **runnable React route** under `app/web/src/pages/`
that updates the master scoreboard. The scoreboard is the project's
primary delivery vehicle — see §6, §7.

**NOTE on phase descriptions below**: Streamlit references in the
P0..P7 descriptions are legacy from the pre-pivot plan (the project
originally used Streamlit for the UI; switched to Vite + React +
Tailwind + shadcn/ui per director decision 2026-05-27 — see §7 for the
canonical stack). For any packet not yet spec'd, transpose Streamlit
references in the description below to their React equivalents:
`app/streamlit_app.py` → `app/web/src/main.tsx` + `app/web/src/App.tsx`;
Streamlit "page" → React route at `/<page>`; `uv run streamlit run ...`
→ `cd app/web && npm run dev` (or `npm run build` + `uvicorn` with
`RAG_WEB_DIST_PATH=app/web/dist`). The packet's own `.codex-runs/<id>/spec.md`
authoring re-aligns the allowlist to the React tree.

Every phase's acceptance includes the runtime verification step
mandated by `CLAUDE.md` § "Deliver a working product". Mechanical
gates (typecheck, tests, lint) are necessary but never sufficient.

---

### §5.0 — P0 NQ Foundation Refresh + Scoreboard Spine

**Owner:** impl (Claude authors the packet spec).

**What ships:**

* Single canonical NQ corpus in Qdrant (consolidate the duplicate
  `nq_passages` + `nq_passages_bge_base_v15` situation; P0 decides which
  embedder is canonical for the project — almost certainly Qwen3-Embedding-4B,
  which means a full re-index).
* `src/retrieval/qdrant_retrievers.py` updated to support
  Qwen3-Embedding-4B as a primary mode (alongside existing MiniLM mode
  kept as historical baseline).
* `src/retrieval/rerank.py` default upgraded from ms-marco-MiniLM-L-6-v2
  (2020) to **BGE-reranker-v2-m3**; rerank ON by default.
* `src/evaluation/scoreboard.py` (new) — produces a single
  `artifacts/scoreboard.json` that aggregates every benchmark × every
  config combination tested so far, with retriever metrics (Recall@K,
  MRR@10, NDCG@10) and (when generation is enabled) answer metrics
  (EM, F1, faithfulness, context precision/recall).
* `app/streamlit_app.py` — new "Scoreboard" page reading
  `artifacts/scoreboard.json` and rendering a sortable table.
* NQ-dev baseline run committed: vanilla → Qwen3-Embed-4B + BGE-rerank
  → scoreboard row.

**Why:**

The project needs (a) **one canonical NQ corpus** to ground everything
against, (b) **a frontier-grade single-hop baseline** so we don't
falsely attribute multi-hop gains to fixing single-hop sloppiness, and
(c) **a scoreboard infrastructure** that every later phase contributes
to. Without the spine, later phases lack a shared yardstick.

**Acceptance — Mechanical:**

* `uv run ruff check` clean.
* `uv run pytest` clean (covers settings + scoreboard schema +
  retriever-mode routing tests).
* NQ-dev eval reproducible deterministically: re-running
  `src/scripts/eval_retrieval.py` on the same split returns identical
  Recall@K and MRR@10 to ≥ 4 decimal places.

**Acceptance — Runtime verification** (per CLAUDE.md §"Deliver a
working product"):

This packet is not done when code merges. It's done when:

1. `docker compose up -d` brings Qdrant up clean.
2. `uv run python -m src.scripts.build_indexes` (or whichever entry the
   spec settles on) produces the single canonical Qwen3-Embedding-4B
   collection on the full NQ corpus, with progress logs ending in a
   success summary line.
3. `uv run python -m src.scripts.eval_retrieval --modes hybrid
   --max-queries 500 --output artifacts/retrieval_eval_p0.json`
   completes and `artifacts/retrieval_eval_p0.json` contains
   `recall@10 > <previous-MiniLM-baseline-recall@10>` (we expect a
   measurable lift from MiniLM to Qwen3-4B).
4. `uv run streamlit run app/streamlit_app.py`, the Scoreboard page
   loads, and rows for the new baseline are visible.

**Packet allowlist (P0):**

* `src/config/settings.py`
* `src/retrieval/qdrant_retrievers.py`
* `src/retrieval/rerank.py`
* `src/retrieval/dense_index.py` (re-indexing logic for new embedder)
* `src/scripts/build_indexes.py`
* `src/scripts/index_dense.py`
* `src/scripts/eval_retrieval.py`
* `src/evaluation/scoreboard.py` (new file)
* `app/streamlit_app.py`
* `app/api/main.py` (no behavioral change beyond exposing new mode)
* `tests/test_retrieval_eval.py`
* `tests/test_scoreboard.py` (new file)
* `pyproject.toml` (dependency adds: `mlx`, `mlx-lm` if Qwen3 served via MLX)
* `uv.lock`

---

### §5.1 — P1 Multi-hop Dataset Ingestion + Vanilla-RAG Baseline

**Owner:** impl.

**What ships:**

* HotpotQA, 2WikiMultiHopQA, MuSiQue eval-time context corpora loaded
  into **separate Qdrant collections** (one per benchmark): one dense
  vector field (Qwen3-Embedding-4B), one sparse (BM25).
* `src/evaluation/multihop_eval.py` (new) — runs each benchmark's
  standard eval on the vanilla dense + hybrid pipelines, computes EM,
  F1, Joint F1, Recall@K per benchmark spec.
* `artifacts/scoreboard.json` updated with vanilla-RAG baselines for
  all three multi-hop benchmarks. **This is the project's humility
  line** — expected MuSiQue F1 ≈ 20 with vanilla dense; we deliberately
  set the low bar so subsequent phases' lifts are visible.
* Streamlit Scoreboard page now shows all four benchmarks (NQ + 3
  multi-hop).

**Why:**

Without the baselines, lift claims are unfalsifiable. Loading the
benchmarks in their own collections (rather than mixing into NQ) makes
each lift attributable.

**Acceptance — Runtime verification:**

1. `uv run python -m src.scripts.ingest_multihop --dataset hotpotqa`
   etc. produces three new Qdrant collections, point counts logged.
2. `uv run python -m src.scripts.eval_multihop --benchmark musique`
   produces `artifacts/eval_musique_p1.json` with non-trivial F1 (>0)
   on the vanilla pipeline.
3. Scoreboard renders the new rows, MuSiQue F1 visibly low (~20-25 expected).

**Packet allowlist (P1):**

* `src/ingestion/multihop_loader.py` (new)
* `src/ingestion/passage_store.py` (extension)
* `src/scripts/ingest_multihop.py` (new)
* `src/scripts/eval_multihop.py` (new)
* `src/evaluation/multihop_eval.py` (new)
* `app/streamlit_app.py`
* `tests/test_multihop_loader.py` (new)
* `tests/test_multihop_eval.py` (new)
* `pyproject.toml`, `uv.lock`

---

### §5.2 — P2 Hybrid + ColBERT Late Interaction

**Owner:** impl.

**What ships:**

* Qdrant collections re-configured to add a **multivector** field for
  ColBERT-style late interaction (using `MAX_SIM` comparator). The
  primary collection types now have: dense (Qwen3-Embed-4B) + sparse
  (BM25) + multivector (jina-colbert-v2).
* `src/retrieval/colbert_retriever.py` (new) — late-interaction
  retriever conforming to the existing `Retriever` protocol.
* Hybrid retriever extended: dense + sparse fusion → ColBERT-v2 rerank
  pass on the top-N → final top-K.
* Streamlit retrieval-trace visualization: for a query, show overlap
  Venn (dense top-K vs sparse top-K vs ColBERT top-K), MaxSim heatmap
  for the ColBERT pass.
* Scoreboard updated: hybrid+ColBERT rows added for NQ and all three
  multi-hop benchmarks. Expected modest lift on multi-hop recall (~5-10
  points).

**Why:**

Late interaction is the most popular cross-encoder-quality retrieval
technique that still scales. Multivector indexing in Qdrant is native
and turns this into a clean drop-in. The visualization is part of the
showcase value.

**Acceptance — Runtime verification:**

1. Qdrant collection schemas show the multivector field; `curl`-ing
   collection metadata confirms `multivectors.colbert` present.
2. `uv run python -m src.scripts.index_colbert` populates the
   multivector field for all four collections; per-passage indexing
   throughput logged.
3. Eval re-run shows measurable lift on MuSiQue Recall@5 vs P1 vanilla
   (target: +5 points minimum).
4. Streamlit query trace page renders the Venn + heatmap.

**Packet allowlist (P2):**

* `src/retrieval/colbert_retriever.py` (new)
* `src/retrieval/qdrant_retrievers.py` (extension)
* `src/scripts/index_colbert.py` (new)
* `src/scripts/migrate_collections_add_multivector.py` (new)
* `app/streamlit_app.py`, `app/ui/display.py`
* `tests/test_colbert_retriever.py` (new)
* `pyproject.toml`, `uv.lock` (fastembed addition)

---

### §5.3 — P3 HippoRAG 2 Graph Retriever (load-bearing)

**Owner:** impl (with intensive Claude direction).

**What ships:**

* Knowledge graph index built per multi-hop corpus: passage nodes +
  phrase nodes (subject/object of OpenIE triples) in a unified graph.
* Two KG construction paths:
  * **Fast lane (default):** GLiNER (entity extraction) + GLiREL
    (relation classification) run locally; overnight indexing on the
    full multi-hop corpora.
  * **Premium lane (optional, for a demo-quality subset):** Qwen3-14B
    with strict JSON-schema OpenIE prompts, locally — OR GPT-4o-mini
    via API for the subset variant to compare quality.
* `src/retrieval/hipporag_retriever.py` (new) — implements the
  HippoRAG 2 query path:
  1. Query → dense embedding → top-K triple matches (over phrase nodes
     in the KG).
  2. Recognition-memory filter (Qwen3-8B) drops triples judged
     unhelpful for the query.
  3. Filtered triples seed a Personalized PageRank walk over the
     unified passage+phrase graph (NetworkX or igraph).
  4. Top-N passages by PPR mass returned.
* `app/streamlit_app.py` — graph visualizer page (cytoscape / d3): for
  a query, show the seeded triples and the PPR walk's top-mass nodes.
* Scoreboard updated: HippoRAG 2 rows for the three multi-hop benchmarks.
  **Target: MuSiQue F1 ≥ 45, 2WikiMHQA Recall@5 ≥ 90** (match published
  HippoRAG 2 within tolerance).

**Why:**

Graph-augmented retrieval is the single largest-magnitude lever for
multi-hop. The published HippoRAG 2 deltas (MuSiQue 45.7 → 48.6 over
NV-Embed-v2, 2Wiki 76.5 → 90.4 R@5) are the reference points. This is
the project's load-bearing phase.

**Acceptance — Runtime verification:**

1. KG construction script runs to completion overnight on a
   representative multi-hop corpus (e.g. MuSiQue); logs show triple
   counts in the expected magnitude (tens of thousands of phrase nodes
   for a ~100K-passage corpus).
2. `uv run python -m src.scripts.eval_multihop --pipeline hipporag2`
   produces a scoreboard row meeting or exceeding the target floor.
3. Streamlit graph visualizer renders for at least 5 hand-picked
   MuSiQue queries; visible cluster of relevant phrase nodes around
   the PPR-top passages.

**Packet allowlist (P3):**

* `src/retrieval/hipporag_retriever.py` (new)
* `src/retrieval/kg/` (new dir: openie.py, graph_builder.py, ppr.py)
* `src/scripts/build_kg.py` (new)
* `src/scripts/eval_multihop.py` (extension)
* `app/streamlit_app.py`, `app/ui/graph_viz.py` (new)
* `tests/test_hipporag_retriever.py` (new)
* `tests/test_kg_builder.py` (new)
* `pyproject.toml`, `uv.lock` (networkx / igraph, gliner, glirel)

---

### §5.4 — P4 Adaptive-RAG Router

**Owner:** impl.

**What ships:**

* Synthetic training-label generation: GPT-4o-mini labels a few
  thousand queries from a mix of NQ + the three multi-hop benchmarks
  with `{no-retrieve, single-hop, multi-hop}` based on the
  Adaptive-RAG paper's criteria.
* `src/reasoning/adaptive_router.py` (new) — fine-tuned DeBERTa-v3-base
  classifier loaded as a single transformers pipeline, predicting the
  3-way label.
* `app/api/main.py` — `/query` now optionally routes through the
  router (selectable; default off for backwards comparison).
* Scoreboard: routes vs always-heavy-lane vs always-fast-lane on each
  benchmark, plotted as a Pareto curve (latency × accuracy).

**Why:**

Adaptive-RAG published numbers: ~35% latency reduction, 28% cost
reduction, +8% accuracy by avoiding heavy-lane overkill on easy
queries. The Pareto curve is part of the showcase: "we know what we
don't know."

**Acceptance — Runtime verification:**

1. Router training script runs end-to-end on the synthetic labels;
   classifier checkpoint saved to `artifacts/router/`.
2. `/query` endpoint with `adaptive=true` correctly routes 5 hand-picked
   queries (visible in API response trace).
3. Streamlit scoreboard now has a "Adaptive vs Always-Heavy vs
   Always-Fast" Pareto plot.

**Packet allowlist (P4):**

* `src/reasoning/adaptive_router.py` (new)
* `src/reasoning/__init__.py` (new, exports router only)
* `src/scripts/train_adaptive_router.py` (new)
* `src/scripts/label_synthetic_queries.py` (new — calls GPT-4o-mini for labels)
* `app/api/main.py` (route extension)
* `tests/test_adaptive_router.py` (new)
* `pyproject.toml`, `uv.lock`

---

### §5.5 — P5 Search-o1 Iterative Reasoning Loop

**Owner:** impl.

**What ships:**

* `src/reasoning/search_o1.py` (new) — agentic loop:
  1. Reasoning prompt sent to Qwen3-14B (MLX 4-bit).
  2. Model emits `<search_query>...</search_query>` tokens; loop
     intercepts, runs HippoRAG 2 retrieval against the query.
  3. Retrieved passages summarized by a "Reason-in-Documents" module
     (a separate Qwen3-8B call) — the summary, not raw chunks, goes
     back into the reasoning stream. This avoids context dilution.
  4. Loop continues for up to 3 iterations or until the model emits
     a final answer.
* `app/streamlit_app.py` — trace viewer page: for any query, render
  each hop's emitted query, retrieved passages (collapsible), the
  Reason-in-Documents summary, and the running reasoning delta.
* Scoreboard updated: Search-o1 rows for multi-hop benchmarks.
  **Target: MuSiQue F1 ≥ 55, HotpotQA EM ≥ 50.**

**Why:**

Iterative reasoning is the other half of the multi-hop equation. The
graph layer gets the right passages into the candidate set; the
iterative loop assembles the multi-hop chain. Published Search-o1
deltas (HotpotQA EM 34.2 → 45.2 on QwQ-32B; MuSiQue EM 10.6 → 16.6)
are the reference points. The Reason-in-Documents summarizer is the
key innovation — naive concatenation of retrieved passages kills the
reasoning stream.

**Acceptance — Runtime verification:**

1. `/query` with `pipeline=search_o1` returns multi-hop answers that
   show >1 iteration trace.
2. Trace viewer renders all hops for at least 5 hand-picked MuSiQue
   queries.
3. Scoreboard row meets the target floor.

**Packet allowlist (P5):**

* `src/reasoning/search_o1.py` (new)
* `src/reasoning/reason_in_documents.py` (new)
* `src/reasoning/llm_client.py` (new — local MLX client; abstracted for
  Qwen3-8B / 14B)
* `app/streamlit_app.py`, `app/ui/trace_viewer.py` (new)
* `tests/test_search_o1.py` (new)
* `tests/test_reason_in_documents.py` (new)
* `pyproject.toml`, `uv.lock`

---

### §5.6 — P6 CRAG Retrieval Gating + NLI Faithfulness Verifier

**Owner:** impl.

**What ships:**

* `src/reasoning/crag_evaluator.py` (new) — per-hop retrieval
  evaluator: scores top-K passages relative to the current hop's query;
  outputs `{correct, incorrect, ambiguous}`. Implemented as a small
  fine-tuned T5-base or distilled cross-encoder (synthetic-labeled).
  Actions: `incorrect` → query rewrite; `ambiguous` → mix; `correct` →
  proceed.
* `src/reasoning/faithfulness_verifier.py` (new) — per-sentence NLI
  entailment check using DeBERTa-v3-large-mnli. Each answer sentence
  must be entailed by at least one cited passage; failures trigger
  re-generation or abstention with reason.
* `src/generation/grounded.py` extended to invoke the verifier before
  returning.
* Scoreboard updated: hallucination rate (judged on a 100-sample slice)
  and abstention rate per pipeline variant.

**Why:**

Multi-hop answers are uniquely vulnerable to post-rationalization (the
model answers from parametric memory and then scans retrieved passages
for plausible-looking citations). Published work shows ~57% of
"correctly cited" multi-hop answers are causally unfaithful. CRAG-style
gating closes ~10-15 F1 on its eponymous benchmark; NLI faithfulness
keeps EM honest under inspection.

**Acceptance — Runtime verification:**

1. CRAG evaluator trained and integrated; per-hop action logs visible in
   trace viewer.
2. Faithfulness verifier triggers re-generation or abstention on at
   least 3 hand-crafted "hallucination bait" queries (where the model
   would otherwise post-rationalize).
3. Judged 100-sample slice on MuSiQue: pipeline-with-verifier vs
   pipeline-without shows lower judged-hallucination rate.

**Packet allowlist (P6):**

* `src/reasoning/crag_evaluator.py` (new)
* `src/reasoning/faithfulness_verifier.py` (new)
* `src/reasoning/search_o1.py` (extension)
* `src/generation/grounded.py` (extension)
* `src/scripts/train_crag_evaluator.py` (new)
* `tests/test_crag_evaluator.py` (new)
* `tests/test_faithfulness_verifier.py` (new)
* `pyproject.toml`, `uv.lock`

---

### §5.7 — P7 Long-context Comparator + Final Master Scoreboard

**Owner:** impl.

**What ships:**

* `src/reasoning/long_context_baseline.py` (new) — dumps top-50
  retrieved passages into a 128K-context model (GPT-4o-mini via API
  for the comparison baseline; Qwen3 + YaRN locally as a secondary
  comparator) and asks for the answer in one shot.
* Scoreboard updated with long-context rows. The showcase claim: RAG
  graph+iterative wins on cross-document synthesis (the multi-hop
  regime); long-context wins on simple lookup. This is the *honest
  comparator*.
* Final Streamlit pages:
  * **Master Scoreboard** — every benchmark × every pipeline variant ×
    latency p50/p95 × answer quality. Sortable, filterable.
  * **Compare Two Pipelines** — pick any query, pick any two pipeline
    configs, see retrieval traces and final answers stacked side by
    side.
* `README.md` rewrite: the project's public-facing "what is this and
  how to run it" doc, with screenshots.

**Why:**

The long-context comparator is the honest control: it answers
"why bother with graphs and iterative reasoning when models have 1M-token
context windows?" The master scoreboard is the showcase's primary
artifact — anyone visiting the project should be able to see, in one
page, the quantitative case for each technique on each benchmark.

**Acceptance — Runtime verification:**

1. Long-context baseline runs cleanly on all four benchmarks (API +
   local); scoreboard rows added.
2. Master scoreboard renders all rows from all phases without errors.
3. Compare-two-pipelines page works for at least 10 hand-picked queries
   per multi-hop benchmark.
4. `README.md` end-to-end "clone → docker compose up → build_indexes →
   streamlit run" instructions reproduce the showcase on a clean machine
   (in a clean clone, by Claude personally).

**Packet allowlist (P7):**

* `src/reasoning/long_context_baseline.py` (new)
* `src/evaluation/scoreboard.py` (final aggregation)
* `app/streamlit_app.py`, `app/ui/scoreboard_page.py`, `app/ui/compare_page.py`
* `README.md`
* `tests/test_long_context_baseline.py` (new)
* `tests/test_scoreboard_aggregation.py` (new)

---

## §6 Master scoreboard schema

`artifacts/scoreboard.json` is the project's evolving source of truth
for measurable results. Schema (versioned; v1 here):

```json
{
  "schema_version": 1,
  "generated_at": "<ISO-8601>",
  "rows": [
    {
      "phase": "P3",
      "pipeline": "hipporag2",
      "benchmark": "musique-ans",
      "split": "dev",
      "retriever_metrics": {
        "recall_at_1": 0.43,
        "recall_at_5": 0.72,
        "recall_at_10": 0.81,
        "mrr_at_10": 0.55,
        "ndcg_at_10": 0.62
      },
      "answer_metrics": {
        "em": 0.41,
        "f1": 0.49,
        "joint_f1": 0.44
      },
      "quality_metrics": {
        "faithfulness": 0.92,
        "context_precision": 0.78,
        "context_recall": 0.84,
        "hallucination_rate_judged": 0.06,
        "abstention_rate": 0.04
      },
      "latency_ms": {
        "p50": 1240,
        "p95": 2810
      },
      "models": {
        "embedder": "Qwen3-Embedding-4B",
        "reranker": "BGE-reranker-v2-m3",
        "reasoning_llm": "Qwen3-14B-Instruct (MLX 4-bit)",
        "verifier": "DeBERTa-v3-large-mnli"
      },
      "commit_sha": "<git rev-parse HEAD>",
      "notes": "..."
    }
  ]
}
```

Every phase's eval script appends rows; rows are immutable once
written. The React `/scoreboard` route reads this file (via the
FastAPI `GET /scoreboard` endpoint) and renders it as a sortable
shadcn-ui `<Table>`.

---

## §7 Web UI IA / showcase delivery contract

**Stack** (per director decision 2026-05-27 — replaced an earlier
Streamlit-based UI when the ambition for visualizers + side-by-side
comparison views outgrew Streamlit's primitive surface):

* **Vite + React 19 + TypeScript** at `app/web/`. SPA, no SSR (local-
  dev only).
* **Tailwind 4** for styling (CSS-first config via `@tailwindcss/vite`).
* **shadcn/ui** (radix base, nova preset) for primitives — `Table`,
  `Card`, `Button`, plus components added as needed per page.
* **React Router v7** (`react-router`, the unified package — not the
  older `react-router-dom`) for SPA routing.
* **TanStack Query v5** for FastAPI data fetching, cache,
  loading/error states, and suspense-compatible refetches.
* **Recharts** for tabular + chart visuals (Pareto plots, latency
  distributions, scoreboard sparklines).
* **Vitest + React Testing Library + jsdom** for component tests.
* **Graph viz**: `react-force-graph-2d` or Cytoscape via
  `react-cytoscapejs` for the HippoRAG 2 PPR walk (P3+).
* **Heatmaps**: small canvas or `@nivo/heatmap` for the ColBERT MaxSim
  matrix (P2+).

**Backend coupling** *(planned; lands as VOI-247 P0-D — until that
packet merges, `app/web/` and the FastAPI `GET /scoreboard` +
StaticFiles mount do not exist on `main`)*: the React app will be
served at runtime by FastAPI when `RAG_WEB_DIST_PATH` env var is set
to `app/web/dist/`. In dev, `npm run dev` runs Vite at port 5173 with
proxy to FastAPI on 8000. For one-command demo from a clean clone (post-VOI-247), run from the
repo root: `docker compose up -d qdrant && (cd app/web && npm install
&& npm run build) && RAG_WEB_DIST_PATH=app/web/dist uv run uvicorn
app.api.main:app`. The `-d` (detached) flag is essential —
without it `docker compose up` blocks the terminal in the foreground
and the chained `&&` never proceeds to the web build + uvicorn. The `(cd app/web && ...)` subshell keeps the
outer shell at the repo root so `uvicorn`'s Python import path
resolves the `app.api.main` package correctly AND the
`RAG_WEB_DIST_PATH` relative path resolves to `<repo>/app/web/dist`
rather than `<repo>/app/web/app/web/dist`.

**Pages** (routes; each lands in its phase's packet):

1. **`/`** — Home / Ask. Query interface; pick a pipeline; see answer
   + citations + retrieval trace. Wired in later packets (post-P0).
2. **`/scoreboard`** — master sortable table reading from
   `GET /scoreboard` FastAPI endpoint; renders the schema from §6.
   Landed in P0-D (VOI-247).
3. **`/compare`** — side-by-side comparison view (P7). Pick any query,
   pick any two pipeline configs, see retrieval traces + final answers
   stacked.
4. **`/graph`** — HippoRAG 2 PPR walk visualization for a query (P3+).
   Cytoscape or react-force-graph showing seeded triples + top-mass
   nodes + edge weights.
5. **`/trace`** — Search-o1 iterative reasoning hops viewer (P5+). Per-
   hop emitted query + retrieved passages (collapsible) +
   Reason-in-Documents summary + running reasoning delta.
6. **`/config`** — view current settings, indexes loaded, models
   available (reads `GET /config`).

**Component generation aid**: the project's MCP plugin set includes
`mcp__magic__21st_magic_component_builder` which authors polished
shadcn-style React components. For higher-order pages (Trace Viewer,
Graph Visualizer) Claude may invoke that plugin during spec authoring
to prototype the layout, then codex transcribes into the final tree.

The showcase is judged not just by scoreboard numbers, but by the
**reproducibility and intelligibility** of the live UI. A visitor
clones, runs, picks a hard MuSiQue query, watches the graph +
iterative reasoning hops, sees the answer with citations, and
understands why this stack does better than vanilla RAG. That visual
+ quantitative story is the showcase.

---

## §8 Operating-model notes (cross-references)

* **Director / spec authoring / scope gate / integration:** Claude.
  See `CLAUDE.md`.
* **Implementer subagent contract:** `.claude/agents/implementer.md`.
  One per-packet implementer in its own worktree, drives gates +
  commits + PR + eye-emoji loop. Writes production code via
  `codex exec` only.
* **Codex worker contract:** `AGENTS.md`. Transcribes Claude-authored
  task files; does not invent domain claims.
* **Build loop, scope guards, Linear-as-ledger, GitHub-as-delivery,
  squash-merge discipline:** `CLAUDE.md`.

For each packet:

1. Claude authors `packet-spec.md` (under
   `.codex-runs/<packet-id>/spec.md`), pull-quoting verbatim from
   the relevant §5 subsection of this file.
2. Claude provisions worktree via `scripts/worktree-new.sh`.
3. Claude dispatches `implementer` subagent.
4. Impl runs gates + commits within allowlist; notifies "ready for
   pre-PR check".
5. Claude runs pre-PR scope + audit-trail check.
6. Approve → impl pushes, opens PR, drives `@codex review` eye-emoji
   loop.
7. Claude runs final-head re-gate + runtime verification step from
   the phase's `## Acceptance — Runtime verification` block above.
8. Squash-merge → Linear auto-transitions issue to Done via
   `Closes VOI-N` in the PR body.

---

## §9 References

The reference list backing this plan's architecture and target
numbers:

* HippoRAG 2 (Gutiérrez et al., 2025) — *From RAG to Memory: Non-Parametric Continual Learning for Large Language Models*. https://arxiv.org/html/2502.14802v1
* HippoRAG (Gutiérrez et al., NeurIPS 2024) — https://arxiv.org/pdf/2405.14831
* HippoRAG repo — https://github.com/OSU-NLP-Group/HippoRAG
* Search-o1 (Li et al., EMNLP 2025) — https://arxiv.org/abs/2501.05366
* Search-o1 repo — https://github.com/RUC-NLPIR/Search-o1
* Adaptive-RAG (Jeong et al., 2024) — https://arxiv.org/html/2403.14403
* Corrective RAG / CRAG (Yan et al., 2024) — https://arxiv.org/abs/2401.15884
* CRAG Comprehensive Benchmark (Yang et al., 2024) — https://arxiv.org/abs/2406.04744
* MuSiQue (Trivedi et al., TACL 2022) — https://github.com/stonybrooknlp/musique
* 2WikiMultiHopQA (Ho et al., COLING 2020) — https://github.com/Alab-NII/2wikimultihop
* HotpotQA (Yang et al., EMNLP 2018) — https://hotpotqa.github.io/
* Qwen3 Embedding (2025) — https://arxiv.org/abs/2506.05176, https://huggingface.co/Qwen/Qwen3-Embedding-4B
* BGE-reranker-v2-m3 — https://huggingface.co/BAAI/bge-reranker-v2-m3
* jina-colbert-v2 — https://huggingface.co/jinaai/jina-colbert-v2
* GLiNER (Zaratiana et al., NAACL 2024) — https://github.com/urchade/GLiNER
* GLiREL (NAACL 2025) — https://aclanthology.org/2025.naacl-long.418.pdf
* Qdrant multivectors (ColBERT) — https://qdrant.tech/documentation/tutorials-search-engineering/using-multivector-representations/
* Qdrant FastEmbed ColBERT integration — https://qdrant.tech/documentation/fastembed/fastembed-colbert/
* MLX-LM (Apple) — https://qwen.readthedocs.io/en/latest/run_locally/mlx-lm.html
* Long-context vs RAG (Yu et al., 2025) — https://arxiv.org/html/2501.01880v1
* LaRA — https://openreview.net/forum?id=CLF25dahgA

---

*PLAN.md is a living document. When the plan changes, change this file
first, then re-author affected packet specs to track. Every change to
this file is a project decision that future sessions should be able to
reconstruct from the commit history.*
