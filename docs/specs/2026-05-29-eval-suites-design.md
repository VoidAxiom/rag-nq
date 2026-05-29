# Eval Suites — design (source of truth)

**Status:** approved design, pre-implementation
**Author:** director (Claude) + Suresh, 2026-05-29
**Scope:** new user-facing feature — define, manage, and run named evaluation
suites from the browser and CLI, with results landing on the master scoreboard.

> This document is the **authoritative source of truth** for the Eval Suites
> feature. Per CLAUDE.md §"Spec authoring", every packet `spec.md` for this
> feature MUST pull-quote the relevant section of THIS file verbatim. If a
> packet spec and this file disagree, this file wins until explicitly revised.

---

## 1. Concept

An **eval suite** is a saved definition of `(question set × pipeline config)`.
Running a suite executes the existing evaluation engine over N questions and
emits an aggregate result. A single `/ask` query is the **N=1 special case** of
the same machinery: the explorer is "run one, inspect deeply"; a suite is "run
many, aggregate, compare."

The evaluation engine already exists and is reused, not rebuilt:

- `src/evaluation/retrieval_eval.py` — recall@k, MRR@k, nDCG@k, per-mode
  summaries, eval-case construction.
- `src/evaluation/per_query_metrics.py` — SQuAD-style EM, F1, supporting-fact
  recall@k (already powering `/ask`).
- `src/evaluation/scoreboard.py` — the immutable result-row model and atomic
  append helper.

This feature adds three things on top: the **suite abstraction** (definition +
persistence + CRUD), a **run path** (background run from the browser; headless
run from the CLI; both write the same scoreboard row), and a **management UI**
(a slide-in drawer on `/ask`).

### Non-goals (v1)

- No config **matrix / sweep** in a single run. One run = one config = one
  scoreboard row. The data model is shaped so a matrix mode can be added later
  without migration (see §3), but it is not built now.
- No **live-progress UI surface**. A run executes in the background; the user's
  feedback loop is "results appear on `/scoreboard` when the run completes." A
  run-status endpoint exists as plumbing (for the CLI and any future progress
  indicator) but no progress banner/table is built in v1.
- No separate `/suites` route. The entire suite UI is a slide-in drawer on
  `/ask`.
- No suite-run **history or status inside the drawer**. The drawer is
  pure suite *management*. All run history lives on `/scoreboard`.

---

## 2. User experience

### 2.1 The single page: `/ask`

`/ask` remains the single-query inspector it is today (question input + pipeline
knobs + answer card + metrics + retrieved-passage list). It gains **one new
affordance: a Suites drawer** that slides in from the side, hidden by default,
opened on demand.

### 2.2 The Suites drawer (management only)

The drawer shows exactly three things and nothing else:

1. **Suite list** — all saved suites; create a new suite; select one to open it.
2. **Suite detail = the entry list** — every question/task in the selected
   suite. Each entry row has three actions:
   - **▸ Run on /ask** — fills the `/ask` chat box with the entry's question and
     submits it, *identical to the user typing the question themselves* (no
     special "suite mode" rendering); the suite's `config` is loaded into the
     knobs first so the inspector reflects the suite's pipeline.
   - **✎ Edit** — edit the question text and/or its gold answer(s).
   - **🗑 Delete** — remove the entry from the suite.
   - Adding an entry appends to this list **live** (no reload), so iterative
     suite-building feels immediate.
3. **Run this suite** — a button on the selected suite that fires a **background
   run** and returns immediately. The user is told the run started and that
   results will appear on `/scoreboard`. No progress is shown in the drawer.

The drawer deliberately does **not** show: run status, run history, aggregate
results, or multi-run comparison. Those live on `/scoreboard`.

### 2.3 Add-current-question flow (the accretion path)

The primary way suites get built is by accretion from real exploration:

1. User asks a question in the `/ask` inspector and gets an answer.
2. **If they like the system's answer** → "Add to suite" captures the **returned
   answer as the gold answer** for a new entry.
3. **If they don't** → they type their **own expected answer** and add that
   instead.
4. Either way the entry is appended to a chosen (or newly created) suite and
   shows up immediately in that suite's entry list in the drawer.

Entries created this way have `source: "authored"`. Entries pulled from a
benchmark's gold set (via the eval-question picker) have `source: "dataset"` and
carry authoritative gold (see §4).

### 2.4 `/scoreboard` (existing page, evolved)

Every suite run — browser-launched or CLI-launched — appears as a scoreboard
row, grouped/filterable by suite, so re-running a suite under different configs
yields the comparison for free.

---

## 3. Data model

### 3.1 `EvalSuite` (new) — persisted at `artifacts/eval_suites/<id>.json`

```
EvalSuite:
  id:           str            # stable slug/uuid
  name:         str
  description:  str | None
  created_at:   datetime (UTC)
  updated_at:   datetime (UTC)
  config:       SuiteConfig    # the captured pipeline knobs (singular in v1)
  entries:      SuiteEntry[]

SuiteConfig:
  benchmark:    str            # e.g. "nq", "musique" — selects the collection
  collection:   str            # resolved Qdrant collection name
  mode:         "dense" | "sparse" | "hybrid"
  top_k:        int            # one of the components-endpoint choices
  reranker:     str            # reranker name or "off"
  generator:    str            # generator name (e.g. "heuristic")

SuiteEntry:
  id:            str
  question:      str
  gold_answers:  str[]                 # authoritative if dataset; user-typed if
                                       # authored; MAY be empty -> retrieval-only
  source:        "dataset" | "authored"
  dataset_ref:   {benchmark, question_id} | None   # present when source=dataset
  notes:         str | None
```

**Matrix-later shaping (non-goal now, no migration later):** `config` is
singular today. A future matrix mode introduces `configs: SuiteConfig[]` and a
run iterates the list, emitting one scoreboard row per config. The v1 schema
keeps `config` as a named object so the future field is purely additive.

### 3.2 Suite run result = the existing `ScoreboardRow`, extended

A suite run produces **one** `ScoreboardRow` (`src/evaluation/scoreboard.py`).
`ScoreboardRow` is `extra="forbid"` and the artifact is `schema_version:
Literal[1]`, so suite provenance is added as **optional fields with defaults**
(forward-compatible; existing rows remain valid under v1):

```
ScoreboardRow (added optional fields, all default None):
  suite_id:      str | None = None
  suite_name:    str | None = None
  run_id:        str | None = None
  num_questions: int | None = None
  launched_via:  "ui" | "cli" | None = None
```

Existing required fields are unchanged: `phase`, `pipeline`, `benchmark`,
`split`, `retriever_metrics`, `latency_ms`, `models`, `commit_sha`, plus optional
`answer_metrics`, `quality_metrics`, `notes`.

**Metric population.** A suite run scores each entry through the existing
pipeline and aggregates:
- `retriever_metrics` (recall@1/5/10, MRR@10, nDCG@10) — mean over entries that
  carry relevant-passage gold (dataset entries; authored entries without gold
  are excluded from retrieval metrics).
- `answer_metrics` (EM, F1, joint_f1) — mean over entries that carry
  `gold_answers`, when the generator produced an answer. `None` if no entry has
  gold answers.
- `quality_metrics` — `None` in v1 (judged metrics are out of scope here).
- `latency_ms` — p50/p95 over the per-entry query latencies.
- `models` — from the run's resolved `SuiteConfig` (embedder is fixed
  project-wide; reranker from config; reasoning_llm/verifier `None` for the
  heuristic generator).
- `pipeline` — derived label from the config, e.g. `"hybrid+rerank"`.
- `phase` — `"suite"` (distinguishes ad-hoc suite rows from phase-gate rows).
- `split` — the benchmark split the questions came from (e.g. `"dev"`), or
  `"mixed"` when a suite blends sources.

---

## 4. Prerequisite: wire gold data through the API

`/api/eval_questions/{benchmark}` returns **0 questions today** for both `nq`
and `musique`, so the existing eval-question picker on `/ask` is empty and the
dataset-backed half of "both, unified" has no source.

**Step 1 of this feature** surfaces the dataset eval slice through the API:
- The multi-hop loaders + NQ loader already carry questions, gold answers, and
  supporting facts.
- `/api/eval_questions/{benchmark}` returns a bounded sample of
  `{question_id, question, gold_answers, supporting_facts?}` for the benchmark.
- This both **fills the existing question picker** and **supplies dataset-backed
  suite entries** (which carry `dataset_ref` → authoritative recall + EM/F1).

Only `nq` and `musique` have populated collections today, so only those return
data initially; `hotpotqa`/`2wikimhqa` return empty until P1-OPS lands their
ingests. The endpoint must degrade cleanly (empty list, not error) for
unpopulated benchmarks.

---

## 5. API surface (new + changed)

New, under the existing `/api/*` prefix (per VOI-302 migration):

- `GET    /api/suites` — list suite summaries (id, name, entry count, config).
- `POST   /api/suites` — create a suite (name, description, config).
- `GET    /api/suites/{id}` — one suite with full entry list.
- `PUT    /api/suites/{id}` — update name/description/config.
- `DELETE /api/suites/{id}` — delete a suite.
- `POST   /api/suites/{id}/entries` — add an entry (question, gold_answers,
  source, dataset_ref?).
- `PUT    /api/suites/{id}/entries/{entry_id}` — edit an entry.
- `DELETE /api/suites/{id}/entries/{entry_id}` — delete an entry.
- `POST   /api/suites/{id}/runs` — launch a background run; returns `{run_id}`
  immediately.
- `GET    /api/suites/runs/{run_id}` — run status/progress
  (`{status, completed, total}`); plumbing for CLI + future UI, not surfaced in
  v1 drawer.

Changed:
- `GET /api/eval_questions/{benchmark}` — now returns the dataset eval slice
  (§4).
- `GET /api/scoreboard` — now includes suite rows (no shape change beyond the
  optional fields in §3.2).

---

## 6. Background run engine

- An **in-process run registry** maps `run_id → {status, completed, total,
  started_at, finished_at, error?}`. Status ∈ `queued | running | done |
  error | cancelled`.
- A worker (thread or asyncio task) iterates the suite's entries, runs each
  through the **existing query pipeline** (the same code path `/api/query`
  uses), computes per-entry metrics via `per_query_metrics` + the retrieval
  metric helpers, aggregates per §3.2, and on completion calls
  `scoreboard.add_row(...)` with the suite-provenance fields populated.
- Local-dev only, single user: the registry is in-memory and does **not**
  survive a server restart. That is acceptable per the project's local-dev
  scope; the **durable** record of a run is the scoreboard row it writes, not
  the registry entry.
- Memory discipline: the run path reuses the singleton model/embedder already
  loaded by the API process — it does **not** spawn a second Qwen3-Embed-4B
  load. (Consistent with VOI-301 lazy-load + single-model hygiene.)

---

## 7. CLI parity

`python -m src.scripts.run_eval_suite --suite <id|name>`:
- Loads the suite definition JSON, runs the same engine, writes the same
  `ScoreboardRow` with `launched_via: "cli"`.
- Prints a human-readable per-entry + aggregate summary to stdout.
- Headless: no API server required (reads the suite artifact + Qdrant directly).

This is the CLI half of "scoreboard tracks suite performance from both CLI and
UI."

---

## 8. Build decomposition (3 packets, dependency-ordered)

This whole feature lands **before** the deepen-`/ask` polish, per the agreed
priority. Packets are dependency-ordered; A unblocks B and C.

### Packet A — backend foundation
- Wire `/api/eval_questions/{benchmark}` to return the dataset eval slice (§4).
- `EvalSuite` / `SuiteEntry` / `SuiteConfig` models + JSON persistence at
  `artifacts/eval_suites/<id>.json`.
- Suite + entry CRUD endpoints (§5, excluding the run endpoints).
- Unit tests: persistence round-trip, CRUD, eval-questions slice for nq +
  musique (and clean-empty for unpopulated benchmarks).
- Runtime verification: `curl` each CRUD endpoint live; `/api/eval_questions/nq`
  and `/api/eval_questions/musique` return non-empty, well-formed slices.

### Packet B — run engine + scoreboard extension + CLI
- Extend `ScoreboardRow` with the optional suite-provenance fields (§3.2).
- In-process run registry + background worker (§6); `POST /api/suites/{id}/runs`
  and `GET /api/suites/runs/{run_id}`.
- Aggregation logic (§3.2) reusing `retrieval_eval` + `per_query_metrics`.
- `src/scripts/run_eval_suite.py` CLI (§7).
- Unit tests: aggregation math on fixtures, registry state transitions, CLI
  writes a valid row.
- Runtime verification: launch a real ≤5-question suite over `musique` via the
  API, confirm a scoreboard row appears with correct aggregate metrics; run the
  same suite via CLI, confirm a second row with `launched_via: "cli"`.

### Packet C — frontend (drawer + scoreboard evolution)
- The `/ask` Suites drawer (§2.2): suite list, entry list with run-on-/ask /
  edit / delete, add-current-question flow (§2.3), Run-this-suite button.
- "Run on /ask" wiring: populate the chat box + load config into knobs + submit,
  matching the manual-ask UX exactly (§2.2).
- `/scoreboard` evolution: surface suite rows, grouped/filterable by suite.
- Component + MSW tests; tests through the actual proxied path (per the VOI-302
  runtime-verification lesson).
- Runtime verification: in the browser, build a suite by accretion, run an entry
  on /ask, launch a suite run, see the row land on /scoreboard.

---

## 9. Acceptance (feature-level)

The feature is done when, on primary, a user can: open the drawer on `/ask`,
create a suite, add questions both from a dataset gold set and by authoring
their own answer, edit/delete/run-on-/ask individual entries, hit "Run this
suite," and see an aggregate result row appear on `/scoreboard` — and can
reproduce the same result row headlessly via the CLI. Mechanical gates (ruff,
pytest, tsc, build) are necessary but not sufficient; each packet's live
runtime-verification block is the sufficient gate.
