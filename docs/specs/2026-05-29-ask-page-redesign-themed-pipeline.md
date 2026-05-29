# /ask page redesign — themed pipeline visualization (design)

> **Status:** design accepted 2026-05-29 (brainstorming session w/ visual-companion mockups in `.superpowers/brainstorm/13349-1780068449/content/`). Source of truth for the implementation packet.

## 1. Concept

Rebuild `/ask` around a **vertical pipeline** that makes the RAG run feel alive: each step (Retriever → Reranker → Generator) is a card with its own knobs + live latency readout; a glowing **total card** on the left holds the headline metric; an **answer panel** types out the result below. Ship the rebuild with a **theme + palette picker** in the header that swaps between **7 visual styles × 3 color palettes = 21 combinations**, with the user's choice persisted to localStorage.

The page is both a working /ask UX AND a showcase of the RAG pipeline + the project's visual range. It is the project's hero page.

## 2. Scope

**Ships:**
- Full `/ask` page rebuild around the pipeline metaphor.
- Theme + palette picker in the header. 21 combos selectable. localStorage persistence.
- Per-step latency display, sourced from the API's existing `latency_ms` response field.
- Sidebar (right column on wide screens, collapsible/stacked on narrow screens) holding the collection selector, eval question picker, retrieved passages list, and gold-vs-answer metrics.
- `framer-motion` for React-driven transitions; CSS keyframes for always-on style-specific effects.

**Removed (absorbed):**
- `MetricsCard` (its content is now part of the sidebar's gold-vs-answer block).
- `AnswerCard` (the new answer panel replaces it).
- `PipelineKnobs` as a single component (its knobs distribute across the three step cards).

**Restyled (kept):**
- `RetrievedPassageList` — moves to the sidebar; gets theme tokens applied.
- `EvalQuestionPicker` — moves to the sidebar; gets theme tokens applied.
- `CollectionSelector` — moves into the Retriever step card (inline).

**Out of scope (deferred):**
- Streaming the generator's tokens (current API is one-shot; the typewriter effect is a UI flourish on the final answer string, not a real stream).
- The `/scoreboard` page redesign (separate work).
- The Suites drawer (VOI-333, separate work).
- Mobile-first responsive design beyond "doesn't break under 640px"; the showcase target is desktop.

## 3. Source-of-truth alignment

The brainstorming mockups live at `.superpowers/brainstorm/13349-1780068449/content/`:
- `layout-options.html` — three layouts (A spine gauge, B inline dots, **C connected cards** ← picked).
- `aesthetic-directions.html` — Neon, Glass, Terminal, Editorial.
- `styles-and-colors.html` — the full 7-style × 3-palette matrix.
- `motion-demo.html` — animated Neon Tokyo demo (auto-run on load).

The matrix is the **canonical list of 21 themes** the implementation must support.

## 4. Page layout

Top-to-bottom on the primary column (the pipeline column):

1. **Header strip** — left: project mark / nav. Right: `[Style ▾] [Palette ▾]` dropdowns. Always visible.
2. **Query bar** — input + Ask button. Themed prominently.
3. **Pipeline** — two-column subgrid:
   - **Left (~140px):** Total card. Big tabular-numerics total-seconds. Pulses while a query is running, settles to final value when done.
   - **Right (flex):** Three step cards stacked vertically, each `~80–110px` tall:
     - **Retriever** — knobs: mode dropdown, top_k slider, collection selector (existing component).
     - **Reranker** — knobs: reranker model dropdown, rerank context budget number.
     - **Generator** — knobs: generator provider dropdown, temperature, max_tokens.
   - Steps are connected by short colored **bridges** (vertical 2px tracks) between them.
4. **Answer panel** — fades + slides in below the pipeline once the generator step completes. The answer text uses a typewriter reveal (~18ms/char) terminated by a blinking cursor that disappears when the typing finishes.

Right column (sidebar, ~320px on viewports ≥1024px; stacks below the main column on narrow viewports):

- **Eval question picker** — dropdown listing curated eval questions per benchmark.
- **Retrieved passages** — collapsible accordion (collapsed by default after first answer; expanded on first load is empty so no flicker).
- **Gold metrics** — only renders when the active question carries `gold_answers` from the eval-question picker or a suite. Shows EM, F1, recall@k (when `supporting_passage_ids` is also present).

The header + sidebar are present in all themes; the styles only affect look-and-feel, not structure.

## 5. Theme system

### 5.1 Style vs palette separation

- **Style** = layout density, typography, motion language, surface treatments (gradients, blurs, glows, borders).
- **Palette** = 3 accent colors (one per step: `--accent-retr`, `--accent-rerk`, `--accent-gen`) + supporting backgrounds where the palette colors them (e.g. gradients).

The 7 styles + 3 palettes per style yield 21 combos. Both dropdowns are always selectable; not every combo will look equally polished, but all must be functional.

### 5.2 The 21 combos (canonical list)

| Style | Palette IDs |
|---|---|
| **1. Neon Synthwave** | `neon-tokyo` (cyan + magenta + violet) · `neon-miami` (pink + orange + amber) · `neon-vapor` (lilac + pink + mint) |
| **2. Glassmorphic** | `glass-aurora` (pink + violet + mint) · `glass-arctic` (ice + frost + silver) · `glass-sunset` (peach + coral + amber) |
| **3. Terminal / CLI** | `terminal-matrix` (green + amber) · `terminal-amber` (vintage amber + white) · `terminal-solarized` (blue + yellow + violet) |
| **4. Editorial** | `editorial-print` (black on cream, light mode) · `editorial-inverted` (cream on black) · `editorial-bloomberg` (navy + orange) |
| **5. Brutalist** | `brut-caution` (yellow + black) · `brut-construct` (tomato + cobalt + cream) · `brut-electric` (cobalt + neon yellow) |
| **6. Liquid / Organic** | `liquid-ocean` (teal + cerulean + emerald) · `liquid-lava` (crimson + amber + magenta) · `liquid-forest` (moss + olive + bronze) |
| **7. Holographic** | `holo-prism` (CMY shift) · `holo-opal` (pearl pastel shift) · `holo-oilslick` (deep purple + rainbow sheen) |

Default first-visit theme: **Neon Tokyo** (`style=neon`, `palette=neon-tokyo`).

### 5.3 CSS architecture

- A `data-style` attribute on `<html>` selects the style; `data-palette` selects the palette.
- A central `themes.css` defines CSS custom properties on `[data-style="X"][data-palette="Y"]` selectors. The cartesian product is enumerated, not algorithmic — explicit is fine for 21 entries.
- All UI components consume **only token vars** (`--bg`, `--surface`, `--text`, `--accent-retr/rerk/gen`, `--border-pending/running/complete`, `--motion-pulse`, `--font-numeric`, `--font-body`, etc.). No theme-specific class names in components.
- Per-style motion keyframes live in the style's CSS block (e.g. `[data-style="neon"]` defines its own `@keyframes neon-step-pulse` and binds it to `.step--running { animation: neon-step-pulse … }` via a `--motion-step-running` custom property).
- Light-mode styles (`editorial-print`, `glass-arctic`, `holo-opal`, etc.) override the global `color-scheme` to `light` for native-control theming.

### 5.4 Picker UI

Two `<select>` elements styled as theme-aware dropdowns in the header. Both update the `<html>` attributes immediately and dispatch a `themechange` custom event. Selecting a new style auto-picks the first palette of that style (e.g. selecting "Neon" sets palette to `neon-tokyo`); the palette dropdown then offers the 3 palettes of the new style. No invalid combos can be selected.

## 6. Pipeline visualization — motion grammar

The motion **grammar** is shared across all styles; the **vocabulary** is per-style.

### 6.1 Shared grammar (universal selectors)

Each step has three states: `pending`, `running`, `complete`. Bridges have two: `idle`, `flowing`, `complete`. The total card has two: `idle/running`, `complete`.

```
.step                 — base
.step--pending        — dim, awaiting upstream
.step--running        — currently processing; live ms ticker
.step--complete       — finished; shows final ms

.bridge               — base (2px vertical track between steps)
.bridge--flowing      — animated; data is flowing through
.bridge--complete     — steady glow in the upstream step's color

.total                — base
.total--running       — pulses; live elapsed counter
.total--complete      — settles; shows final total

.answer               — base (hidden)
.answer--visible      — fades + slides in; types out the text
```

### 6.2 Per-style vocabulary

Each style ships a CSS module that binds the universal selectors to style-appropriate effects. Quick reference (full set in `themes.css`):

- **Neon:** `--motion-step-running` = `neon-pulse-glow 1.2s ease-in-out infinite`; bridges flow with a 1s linear scrolling gradient; total glows pulses with a 1.2s glow-intensity oscillation.
- **Glass:** breathing pulse via `transform: scale()` with low amplitude; bridges fade in via opacity transition (1.2s cubic-bezier); answer slides in with subtle blur drop.
- **Terminal:** no smooth pulse — uses a 0.8s `steps(2)` blink on the active dot. Bridges fill via a typewriter-style stepped reveal. Answer types out (already universal, just matches the aesthetic perfectly here).
- **Editorial:** no glow at all. Live ms counter uses a `font-feature-settings: 'tnum'` + a 0.3s ease transition on the number; running state is signaled only by a thin sliding cursor at the bottom of the active step's hairline. Refined, restrained.
- **Brutalist:** snap transitions (`transition: none`). State changes are instant flips between flat color blocks. The "motion" is the absence of motion.
- **Liquid:** a vertical wave SVG travels top-down through the pipeline. Below the wave = complete; at the wave = running; above = pending. The wave's path morphs smoothly.
- **Holographic:** running step does a `hue-rotate` animation (3s linear infinite); bridges have a CMY gradient that scrolls; total card has a conic-gradient background that rotates.

### 6.3 Driving the animation from API data

The API returns one final `latency_ms` after the query completes:
```json
{
  "latency_ms": { "retrieval_ms": 1075, "rerank_ms": 1240, "generation_ms": 85, "total_ms": 2400 }
}
```

Because there is no streaming endpoint, the UI runs a **scripted animation** that mimics the pipeline's actual durations:
1. On submit: enter `running` state, start a wall-clock total counter, set step 1 (`retriever`) to `running`.
2. After `retrieval_ms` wall-clock ms (or `min(retrieval_ms, soft-cap)` if the run is very fast — see §6.4): mark retriever `complete` with `retrieval_ms`, start bridge 1 `flowing`, set reranker `running`.
3. Same for reranker → bridge 2 → generator.
4. After generator `complete`: reveal answer, type it out.

If the API responds **before** the scripted animation finishes (e.g. the heuristic generator returns in 50ms but our minimum-step-anim is 200ms), the animation finishes its current beat with the real ms and snaps the remaining steps to their real ms quickly. If the API responds **after** (e.g. a cold-start hits the 30s timeout while the animation expected 2.4s), the running step's ms counter keeps ticking past the expected value until the API actually returns.

### 6.4 Minimum animation duration

Per-step animation must be visible (≥250ms) even when the real step took <250ms, otherwise the motion is invisible and the design falls apart. Implementation: `actualStepMs = max(real_ms, MIN_STEP_MS)` where `MIN_STEP_MS = 250`. The displayed ms reading is always the real ms; only the wall-clock animation pacing is floored.

## 7. Data flow

```
[QueryBar submit]
      │
      ▼
  fetch /api/query  ─────────────────────────────────────┐
      │                                                  │
      ▼                                                  ▼
  start scripted animation (3 steps, sequential)    response = QueryResponse
      │                                                  │
      ▼                                                  │
  per-step: update total counter, step state         apply final timings + answer
      │                                                  │
      └──────────────────────────────────────────────────┘
                            │
                            ▼
                  reveal answer panel + type out
                  populate sidebar (passages, gold metrics)
                  scoreboard update via global listener
```

API contract unchanged. The page consumes existing `/api/query`, `/api/config`, `/api/components`, `/api/eval_questions/{benchmark}` endpoints.

## 8. Component decomposition

New files:

- `app/web/src/pages/AskPage.tsx` — rewritten. Holds page state, query submission, animation scheduling.
- `app/web/src/components/ask/PipelineStage.tsx` — one of the three step cards. Props: `name`, `accentVar`, `state`, `ms`, `children` (knobs).
- `app/web/src/components/ask/PipelineTotal.tsx` — total card.
- `app/web/src/components/ask/PipelineBridge.tsx` — single bridge between two stages.
- `app/web/src/components/ask/AnswerPanel.tsx` — typewriter-revealed answer.
- `app/web/src/components/ask/RetrieverKnobs.tsx`, `RerankerKnobs.tsx`, `GeneratorKnobs.tsx` — the inline knob sets per step.
- `app/web/src/components/ask/AskSidebar.tsx` — wraps existing `EvalQuestionPicker`, `RetrievedPassageList`, and the new `GoldMetricsPanel`.
- `app/web/src/components/ask/GoldMetricsPanel.tsx` — shows EM/F1/recall@k when gold is available (replaces the metrics half of `MetricsCard`).
- `app/web/src/theme/themes.css` — the 21-combo CSS module.
- `app/web/src/theme/ThemeProvider.tsx` — reads `?style=&palette=` from URL, falls back to localStorage, falls back to default `(neon, neon-tokyo)`. Applies `data-style` + `data-palette` to `<html>`. Saves selection to localStorage on change.
- `app/web/src/theme/ThemePicker.tsx` — the two header dropdowns.
- `app/web/src/lib/pipelineAnimation.ts` — the scripted-animation scheduler (`runPipelineAnimation(timings, callbacks)` returns a Promise).

Modified files:

- `app/web/src/App.tsx` — wrap routes in `<ThemeProvider>`; include `<ThemePicker>` in the header strip.
- `app/web/src/components/CollectionSelector.tsx`, `EvalQuestionPicker.tsx`, `RetrievedPassageList.tsx` — replace hard-coded colors with theme tokens.

Deleted files:

- `app/web/src/components/AnswerCard.tsx`, `MetricsCard.tsx`, `PipelineKnobs.tsx`.

Test files (vitest + RTL):
- `app/web/src/components/ask/__tests__/PipelineStage.test.tsx`
- `app/web/src/components/ask/__tests__/AnswerPanel.test.tsx`
- `app/web/src/theme/__tests__/ThemeProvider.test.tsx`
- `app/web/src/lib/__tests__/pipelineAnimation.test.ts`
- `app/web/src/pages/__tests__/AskPage.test.tsx` — extend; cover happy-path query, theme switch round-trip, sidebar collapse, gold-metrics-when-present.

## 9. Persistence

- **localStorage key:** `ask-theme` — value `{"style":"neon","palette":"neon-tokyo"}` (JSON string).
- **URL param precedence:** if `?style=X&palette=Y` is in the URL, use that; do NOT write it to localStorage (URL is share-link mode).
- **First-visit default:** `style=neon`, `palette=neon-tokyo`.
- **Invalid combo handling:** if localStorage or URL has an unrecognized style/palette, fall back to default. Log a warning to console once.
- **Theme change:** any picker change writes immediately to localStorage. No "apply" button — selection IS application.

## 10. Acceptance

### Mechanical

- `cd app/web && pnpm tsc --noEmit` — no new errors beyond the pre-existing `tsconfig.json TS5101 baseUrl deprecation` line.
- `cd app/web && pnpm test` — all RTL tests pass.
- `cd app/web && pnpm lint` — clean (or no new violations).
- `cd app/web && pnpm build` — production build succeeds.
- `uv run pytest -x` — backend tests still pass (we change nothing on the API side).

### Runtime verification (per CLAUDE.md §"Deliver a working product")

This packet is not done when code merges. It's done when, on primary:

1. Vite dev server starts via `cd app/web && pnpm dev`; `/ask` loads at http://localhost:5173/ask with the **Neon Tokyo** theme on first visit (no localStorage, no URL param).
2. Submitting a real query (e.g. against the running primary uvicorn) renders the full animation sequence: total counter ticks, each step transitions running→complete with its real ms, bridges flow, answer types out.
3. Each of the 21 combos is selectable via the picker. Verify a representative sample (~5 covering each style family) renders without console errors and the pipeline animation works in each.
4. Theme change is persisted across reload (refresh the page, theme stays).
5. `?style=editorial&palette=editorial-bloomberg` URL param applies that theme on load AND does not overwrite the localStorage value. Removing the URL param reverts to the localStorage value.
6. Sidebar collapses to below-the-pipeline stacking on viewports <1024px; pipeline remains usable on viewports as narrow as 640px.

## 11. Out-of-scope items pre-emptively rejected (cite verbatim per implementer.md §8e)

- **Theme picker as a settings drawer (gear icon)** → REJECT — design §4 verbatim: "Always visible header strip with style + palette dropdowns."
- **Random-on-each-visit default** → REJECT — design §9 verbatim default is `(neon, neon-tokyo)` with localStorage persistence.
- **GSAP** → REJECT for v1 — framer-motion + CSS keyframes cover the motion grammar; GSAP only if a future packet introduces timeline-orchestration needs.
- **Streaming the generator's tokens** → REJECT — out of scope per §2; the typewriter is a UI flourish on the complete answer string.
- **Mobile-first responsive overhaul** → REJECT — out of scope per §2; the showcase is desktop-first; must not break under 640px.
- **Per-theme custom font loading from CDN** → REJECT — use system fonts + safely-fallback stacks. Orbitron/Playfair are nice-to-have but not blocking; if not on the system, the font-family stack falls back to the closest available.
- **A11y audit / WCAG AA contrast for all 21 combos** → REJECT for v1 — some palettes (e.g. holo-prism) are designed-to-impress, not for low-vision contrast. v1 ships with reasonable defaults; a future packet can add a "high-contrast" override style.
- **Refactoring `app/web/src/pages/HomePage.tsx` or `ScoreboardPage.tsx`** → REJECT — out of scope; those pages get the theme tokens applied incidentally but no functional redesign.

## 12. Build decomposition

Single packet. One impl. Suggested implementation order (within one codex run if it fits, else multiple rounds within the packet):

1. Theme system foundations: `themes.css`, `ThemeProvider.tsx`, `ThemePicker.tsx`, persistence wiring. Verify `data-style`/`data-palette` flip works on a placeholder page.
2. Pipeline UI components: `PipelineStage`, `PipelineTotal`, `PipelineBridge`. Static-styled in Neon Tokyo first; verify all 21 combos render with the tokens.
3. `pipelineAnimation.ts` scheduler + framer-motion integration. Verify on a synthetic timings input.
4. `AnswerPanel` + typewriter.
5. AskPage rebuild — query bar, pipeline column, sidebar column, full data flow against real `/api/query`.
6. Restyle existing kept components (`CollectionSelector`, `EvalQuestionPicker`, `RetrievedPassageList`) to use theme tokens.
7. Delete the 3 absorbed components; remove their imports.
8. RTL tests for new components + extend `AskPage.test.tsx`.

## 13. Notes for impl

- Dev server port: Vite dev server defaults to **5173**. The backend API runs on primary's **8000**. Vite's proxy in `app/web/vite.config.ts` already forwards `/api/*` to `8000`.
- All work is under `app/web/**` (production frontend code) — the impl gets one Linear issue, one branch off `origin/main`.
- `framer-motion` needs adding to `app/web/package.json` (latest stable). No GSAP. No other animation libs.
- Hard cap: **3 codex rounds** per packet doctrine. Spec is detailed; if a 4th would be needed for a genuinely new spec-vs-source contradiction, escalate.
- No `Co-Authored-By` / `🤖` / Claude credit in commits, PRs, comments.
