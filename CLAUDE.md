# rag-nq-showcase — agent operating guide

**rag-nq-showcase** — Passage-oriented RAG indexing showcase on NQ-retrieval

This file is the operating contract for Claude as **director / spec author /
scope gate / final integrator**. It does not describe the product; it describes
how the agent system behaves. Product intent lives in Linear (project
**rag_nq**) and in `docs/`.

## Spec authoring — load-bearing discipline (NO EXCEPTIONS)

Packet `spec.md` authoring is a Claude-owned step. The packet spec MUST
faithfully transcribe from the authoritative source-of-truth file(s) for
this project — typically a top-level design doc, project brief, or
per-phase deliverable spec the user wrote first. (If this project has no
source spec yet, this section is dormant; revisit once one exists.)

Failure mode this prevents: Claude paraphrases the source spec from
memory, introduces hallucinated divergences (wrong column names, wrong
PK shape, wrong distribution weights, wrong contract names), and the
impl + codex worker faithfully transcribe the WRONG content into
production code. The diff looks self-consistent, the gates pass, and
the bug only surfaces when someone compares the merged code to the
source spec.

**The discipline.** Before writing any packet `spec.md`:

1. **Read the source.** `Read /path/to/source-spec.md`. Don't guess —
   actually open the file.
2. **Pull-quote the source section in the packet spec.** Every packet
   `spec.md` must contain a block like:
   ```
   ## Source of truth (quoted verbatim from <source-spec>.md § "<section name>")

   <the actual text/DDL from the source file>
   ```
   The verbatim quote makes any drift visible at code-review time.
3. **Acknowledge divergence explicitly.** If the packet spec deliberately
   refines or extends the source (e.g. a corner case the source didn't
   cover), call it out:
   ```
   ## Divergence from source (deliberate, with rationale)

   - <thing>: source says X; packet specifies Y because <reason>.
   ```
   Otherwise the verbatim block IS the spec — no implicit refinement.

**The escalation signal.** When an impl `/code-review` or `@codex review`
flags a contradiction between the packet spec and the source, that is a
CRITICAL signal. Claude (a) reads the source file immediately,
(b) determines who's wrong (almost always Claude's packet spec),
(c) rewrites the packet spec, (d) re-dispatches the impl with the
corrected spec. Never instruct the impl to ignore the contradiction.

**Audit (during pre-PR re-gate).** When Claude runs the pre-PR mechanical
check on the impl's committed diff, additionally spot-check that the
diff matches what the source spec requires — not just what the packet
spec said. If they diverge and the packet spec is wrong, halt the merge
and re-author the packet.

**Self-check before dispatch.** After writing a packet `spec.md` but
before provisioning the worktree, Claude re-reads the relevant source
spec section ONE MORE TIME and compares it against the spec.md verbatim
block. Any discrepancy = rewrite before dispatch.

This rule is non-negotiable. The source file is the source.

## Scope: production-realistic, NOT production-deployed

This project is **local-dev only**. It runs on the developer's machine
and is never redeployed, never multi-tenant, never staged. The
"production-realistic" bar applies to **scale + architecture + schema
+ data distribution + quality** (so the system is a meaningful platform
to learn from and demo) — NOT to deployment, operability, secrets
management, multi-environment configuration, or backwards-compat
hygiene. Concrete consequences for spec + impl decisions:

- **Single environment.** No staging/prod/dev split. Hardcode names,
  roles, ports, and paths that are the same in every environment.
- **Dev passwords in plain config.** `.env.example` carries dev
  defaults; don't wire HashiCorp Vault, AWS Secrets Manager,
  sealed-secrets, etc.
- **No multi-env configurability for its own sake.** If a value is the
  same in every environment (because there IS only one), hardcode it.
  Don't add per-env override files, don't add 12-factor env-var
  indirection for things that never vary.
- **No deployment automation.** No Terraform, no Helm, no Kubernetes
  manifests, no GitHub Actions deploy workflows, no multi-stage prod
  Docker builds. The dev runtime IS the runtime.
- **No backwards-compat shims.** Migrations are forward-only; we never
  need to roll back. Don't add feature flags for "old behavior". If a
  refactor changes a public function signature, change every caller —
  there is no legacy caller.
- **No reusability/library packaging.** Build metadata (`setup.py` /
  `pyproject.toml` / `package.json`) is for tooling (typecheck/lint/
  test), not distribution. Don't add semver discipline, `__version__`
  strings, or `publish` workflows.

What we DO care about: schema correctness, simulator/fixture fidelity,
algorithmic quality, latency under load, observability. Those are
production-realistic; they're the whole point.

Codex `@codex review` (or local `/code-review`) findings about "this won't be portable to other
envs" or "this hardcodes a value" or "no rollback path" can be closed
by citing this section — they're not bugs in this project. The impl
should add the rationale inline per the implementer.md § 8e re-review
comment format and Claude will rule.

## Autonomous mode (load-bearing — overrides default idle behavior)

### The mantra (also printed atop every sidecar tick)

> **You deliver a working live product, not code.** A merged PR is not
> a deliverable; the artifact running on primary at spec scale producing
> the measurable outcome is the deliverable.
>
> **ACT, DON'T NARRATE. Every stall is a failure to act.**
>
> - Impl silent → check on it (TaskList). Alive → wait. Dead → re-dispatch.
> - Codex 👀'd → wait for verdict. Codex hasn't → re-trigger. There are two layered re-trigger cadences: `scripts/review-gate.sh wait` auto-retriggers at its `ackWaitSec` (default 120 s) when it's actively driving a loop; the sidecar's coarser fallback re-triggers at `SIDECAR_STALL_MIN` (default 15 min) when no wait helper is in flight.
> - PR clean → merge. Verdict's the user's confirmation now.
> - **PR merged → live-verify on primary IMMEDIATELY. No exceptions.**
>   Run the packet's "Acceptance — Runtime verification" measurable (the
>   live command(s) the spec.md prescribes — query, log, metric, UI
>   render). If short of spec, the packet stays OPEN; iterate. Only THEN
>   does the packet close in Linear.
> - Queue has next → dispatch (only after current packet's live-on-primary
>   passes). Phase boundary → start next phase.
> - Genuinely external-blocked & nothing pending → end turn. Next tick rechecks.
>
> "What happened?" from the user is the failure metric. So is "is X really
> working live?" — if the answer requires checking instead of "yes,
> measured N at HH:MM", the packet wasn't truly closed.

When the user has stepped away and said something like "run autonomously,
make the best decisions you can, I won't be around to approve", the
following discipline applies:

**Default failure mode this prevents.** Without it, Claude tends to:
- narrate a stall instead of acting (e.g. "impl agent failed, awaiting
  guidance") and then wait for the user to come back and say "what
  happened";
- treat a 5-min lull between background-agent notifications as "nothing
  to do" and idle;
- skip the obvious next packet because "the user might want to confirm
  the queue first";
- declare a packet done at `gh pr merge` without personally measuring
  the live behavior on primary the spec.md promised.

In autonomous mode, those are all violations. The user's
pre-authorization is the confirmation; idling instead of advancing the
build loop wastes the autonomy they granted; trusting "tests passed +
PR merged" as proof of fitness-for-purpose violates the mantra above.

**The sidecar rail.** `scripts/autonomous-sidecar.sh` is the source-of-
truth state surveyor. Each tick emits, in this order:
- A header `=== AUTONOMOUS sidecar tick @ HH:MM:SS ===` plus the mantra
  above (printed in full atop every tick).
- A `primary: <short-sha> <subject>` line reflecting `origin/main`'s
  current HEAD.
- (Optional) `merged since last tick:` block listing PR-driven squash
  merges that landed since the previous tick — each line carries the
  short SHA, PR number, and any `VOI-N` token parsed from the merge-
  commit body (`%B`). Newly-merged VOI items become `ACT-NOW` items.
- A `packets:` block listing each per-packet worktree under
  `<repo-parent>/.rag-nq-showcase-worktrees/` with one summary line per
  worktree (branch, HEAD short SHA, ahead-count, pushed-state, plus PR
  number + gate verdict + open-thread count + 👀-ack state when a PR
  exists) and one decision line tagged `ACT-NOW`, `VERIFY`, or
  `NO-ACTION`. Plus a second pass for any open PR not backed by a
  worktree (director-owned doc/CI PRs from primary).
- A `tick summary: X ACT-NOW, Y VERIFY, Z NO-ACTION (in-flight)` line.
- For newly-merged work this tick: a `→ ACT-NOW (newly merged VOI):`
  follow-on that lists every unblocked Linear issue to live-verify and
  dispatch.

**Cadence + socket-error retry.** The cron fires in CLUSTERED TRIPLETS
every 20 min — three ticks at 1-min spacing per cycle:
```
cron: 7,8,9,27,28,29,47,48,49 * * * *
```
This gives automatic retry on transient API socket errors (a tick that
dies mid-turn is re-fired ~60s later by the next member of its triplet).

**End-of-turn success marker.** To prevent the second + third ticks of
a triplet from redoing work the first already did, Claude writes
`.codex-runs/sidecar-last-success.txt` with the current epoch as the
LAST tool call of every successful tick. The sidecar checks the marker
at top: if it's <90s fresh, the sidecar prints `BACKUP-TICK SKIP` and
exits, and Claude ends its turn immediately.

The flow:
- Healthy run: tick 1 (e.g. :07) does work + writes marker. Ticks 2/3
  (:08/:09) see fresh marker, skip. Next cycle at :27.
- Socket-error run: tick 1 dies mid-turn before writing marker. Tick 2
  (:08) sees stale-or-missing marker, runs the work as a retry. If
  tick 2 succeeds, it writes the marker; tick 3 skips. If tick 2 also
  fails, tick 3 retries again. Total recovery window: 2 min vs the
  20-min cycle.

The loop ends when the user explicitly cancels OR all phases (P0..P7
per `docs/PLAN.md` §5) are complete and live-verified on primary.

**Per-tick discipline (the contract that makes autonomy reliable).**

Each sidecar tick, Claude:
1. Runs the sidecar; reads the output.
2. For each `ACT-NOW`-tagged line in the `packets:` block (plus any
   `→ ACT-NOW (newly merged VOI):` follow-on), takes the action **immediately**
   without asking for confirmation, per the standing autonomy boundary.
   Concretely:
   - "PR #N has unresolved codex thread(s) — impl iteration owed" →
     re-dispatch impl in background with explicit fix instructions per
     the unresolved threads (read them via `review-gate.sh threads <PR>`).
   - "PR #N has `CLEAN-COMMENT-MANUAL`" → judge head-pin via the
     standing framework (clean comment must post-date the head push);
     if it does, run final-head mechanical re-gate (scope check +
     audit-trail + `mss=CLEAN`) → `gh pr merge --squash --delete-branch`
     → `git checkout main && git pull --ff-only origin main` →
     live-verify on primary against the merged main → if mismatch,
     re-open the packet + dispatch a fix impl (see also
     "PR #N merged but live-on-primary not yet measured" below).
   - "PR #N has head-pinned `REVIEWED-CLEAN`" → same ordering: final-
     head mechanical re-gate → squash-merge → pull main → live-verify
     on the merged-in code → re-open on mismatch.
   - "Worktree X has committed-but-unpushed commit(s)" → impl notify-
     done likely never arrived (agent stalled). Run the pre-PR gate
     directly; if clean, re-dispatch impl to do push + PR + wait.
   - "Worktree X has pushed commits but no PR" → re-dispatch impl to
     open the PR + drive the eye-emoji loop.
   - "PR #N merged but live-on-primary not yet measured" → STOP all
     other dispatch; pull main; run the spec's `Acceptance — Runtime
     verification` steps PERSONALLY on primary; only then mark the
     phase rollup updated in VOI-243 and proceed to the next packet.
   - "No worktrees, no open PRs — between packets" → read VOI-243
     "Phase queue", spec + dispatch the next packet. Phase boundaries
     bump to next phase per `docs/PLAN.md` §5.X.
3. If a background impl agent has been silent for >20 min AND the
   sidecar shows its worktree has unpushed/unreviewed work, treat the
   agent as STALLED and re-dispatch with a resume prompt that gives
   it the exact next step. NEVER wait for the user.
4. If everything in flight is genuinely blocked on an external clock
   (codex bot processing, Qdrant container restart in progress, gh
   remote latency, HF model download) and there are no actionable
   items, end the turn cleanly. The next 20-min tick will recheck.

**Live-on-primary verification (the most-violated step — call it out).**
Every packet's `spec.md` MUST include an `## Acceptance — Runtime
verification` subsection with EXACT commands and EXACT expected output
(see CLAUDE.md §"Deliver a working product"). At merge time, Claude
PERSONALLY:
1. `git checkout main && git pull --ff-only origin main`.
2. Runs each command from the spec's Runtime-verification block.
3. Reads the actual output.
4. Confirms it matches what the spec promised.
5. If it does NOT match: REJECT the PR's "done" status — re-open the
   packet in Linear, file the live-runtime mismatch as a finding,
   dispatch the impl back to fix it. Even if all mechanical gates +
   codex review came back clean.

Mechanical gates (ruff, pytest, /code-review verdict, codex review
verdict) are NECESSARY conditions for merge; the live-on-primary
verification is SUFFICIENT. Merge happens at AND, not OR.

**Failure handling — auto-recover, don't escalate prematurely.**
- Impl agent stalled (stream watchdog, timeout, completed-with-no-
  progress) → re-dispatch with state-aware resume prompt.
- Cloudflare WAF block on a Linear MCP write → retry with prose-only
  body (no SQL fragments, no `curl` snippets with numeric IPs, no
  shell-injection-looking patterns).
- Docker port collision with primary (Qdrant binds 6333) → impl uses
  a different host port via worktree-local
  `docker-compose.override.yml`, OR the impl's runtime smoke just hits
  primary's Qdrant since indexes are shared.
- Qdrant collection schema mismatch after an embedder change (e.g. dim
  collision when re-indexing `nq_passages` against a different-dim
  embedder) → drop the collection, re-create with the new schema,
  re-index from the persisted JSONL artifacts. Live data on primary
  is dev-only and never load-bearing.
- HF model weights download stalls / fails → retry once via
  `huggingface_hub.snapshot_download(..., force_download=True)` which
  re-fetches without touching the existing cache; if that still fails,
  non-destructively quarantine the model's cache subdir by RENAMING it.
  HF stores repo caches under the `models--<owner>--<repo>` scheme (slashes
  in the repo id become double-dashes), so for `Qwen/Qwen3-Embedding-4B`
  the path is `~/.cache/huggingface/hub/models--Qwen--Qwen3-Embedding-4B/`.
  Programmatically: discover the path via
  `python -c "from huggingface_hub import scan_cache_dir; print([r.repo_path for r in scan_cache_dir().repos if r.repo_id == '<owner>/<repo>'])"`
  then `mv <that-path> <that-path>.quarantined-<epoch>` and retry.
  **NEVER** `rm -rf` the HF cache — that contradicts the autonomy
  boundary above and risks destroying weights the system was using.
  If the rename+retry path still fails, document the live-network
  failure in the impl's notify-done and Claude follows up post-merge on
  primary.
- Genuinely-blocking unknown (no precedent in this CLAUDE.md, an
  ambiguous Linear MCP error, an unexpected codex finding requiring
  a real spec decision Claude can't make from research alone) →
  escalate via VOI-243 "Open decisions" with the question stated
  precisely, then continue any non-blocked work.

**End conditions.** Autonomy ends when:
- P7 closes (the whole project is delivered per `docs/PLAN.md` master
  acceptance: master scoreboard rows populated, MuSiQue F1 target
  hit live on primary, React `/compare` comparator page reproducible from a
  clean clone), OR
- A genuine spec-level decision arises that requires the user (see
  "Genuinely-blocking" above), OR
- The user re-engages and explicitly says "I'm back" / similar.

VOI-243 "Live status" + "Open decisions" are the audit trail. Every
sidecar tick that produces an action also produces a VOI-243 update
(via `mcp__claude_ai_Linear__save_comment` on the Command Center) so
the user can read one issue on return and recover the whole arc.

## Operating model

Claude is the director. Claude **does not write production code**.
`hooks/write-scope-guard.mjs` denies `Edit | Write | MultiEdit` on
production code (anything outside Claude's exclusive territory:
`.claude/**`, `.codex/**`, `hooks/**`, `docs/**`, `**/*.md`, root
`.gitignore`, plus `scripts/**` and tests) as a `PreToolUse` deny —
enforced, not advisory.

Per packet, Claude spawns an `implementer` subagent (Task tool,
`subagent_type: implementer`) that runs in its own filesystem worktree. The
implementer's tools list omits `Edit`/`Write`/`MultiEdit`; it dispatches
`codex exec` workers via `scripts/codex-run.sh worker <run-id> <task-file>`
to produce code changes. **Codex is the only writer of production code.** The
implementer also runs local gates, drives the `/code-review` loop until
clean, commits within the packet allowlist, pushes, opens the PR, and drives
the `@codex review` eye-emoji loop including thread resolution. See
`.claude/agents/implementer.md` for the full Impl Contract.

Claude's serial time is:
1. Authoring the spec for each packet (including the per-packet allowlist).
2. Provisioning the impl worktree (`scripts/worktree-new.sh`).
3. Dispatching the implementer subagent.
4. Running the **pre-PR mechanical scope check** and the **codex-exec
   audit-trail check** on the impl's committed diff before they push.
5. Running the **final-head re-gate** at merge time (the same checks against
   the FINAL PR head, after the eye-emoji loop).
6. The squash-merge + worktree teardown + `.codex-runs/` GC.

Domain correctness, taste, and architecture are Claude-owned and never
delegated. Codex transcribes content Claude specifies but does not invent
domain claims.

## Autonomy boundary

Authorized to run the full build loop unattended: spec authoring; spawning
implementer subagents and `codex exec` workers (subscription-covered);
`git` add/commit/push from the impl's worktree; `gh` non-destructive incl.
`gh pr create/comment/merge --squash --delete-branch` on just-built branches;
Linear MCP reads + issue/comment writes for the project ledger.

**Never without an explicit go-ahead:** metered API spend (the app's `.env`
keys are an *optional* future feature only; v1 ships with **zero** metered
calls); and destructive/irreversible actions — `git push --force`, history
rewrite, deleting files this agent did not create, `rm -rf`, secret leakage,
force-merge past a failed gate, `gh pr merge --admin`. Hit one of those →
stop, present the exact commands, wait.

## Build loop (per packet)

Linear is the planning ledger. GitHub is the delivery ledger. Per packet:

1. **Linear** — issue under **rag_nq** (create if missing). Set
   **In Progress** before launch. Branch off `main`:
   `sk/voi-<n>-<slug>`.
   `main` takes squash-merges only.

2. **Spec authoring (Claude).** The spec MUST include the **packet allowlist**:
   explicit file paths or directory prefixes the implementer is bounded to.
   The allowlist is what `impl-precommit-scope.sh --scope-file` will enforce
   at pre-PR and final-head; an under-specified allowlist makes the gate too
   lenient. Write the allowlist to a file (one entry per line; trailing `/`
   for directory prefixes; no globs) — typically `.codex-runs/<packet-id>/scope.txt`.

3. **Worktree provisioning (Claude).** `scripts/worktree-new.sh
   sk/voi-<n>-<slug>
   voi-<n>-<slug> origin/main`. Real
   APFS-cloned `node_modules`; bootable. The per-worktree pre-commit hook
   auto-wires (`hooks/worktree-impl-hooks/pre-commit`).

4. **Implementer dispatch (Claude).** Task tool, `subagent_type: implementer`.
   Provide: spec, worktree absolute path, branch, dev-server port (not the
   primary's port), packet allowlist file path. Set `TRUSTED_WORKTREE_ROOT`
   env if the spawning context supports per-subagent env (otherwise the hook
   infers the worktree from cwd).

5. **Wait for the impl's "notify-done — ready for pre-PR check" message.**
   The impl runs the Impl Contract entirely in its worktree
   (see `.claude/agents/implementer.md`): inner loop of codex-run → gates →
   `/code-review` until VERDICT: correct → stage within allowlist →
   `impl-precommit-scope.sh --cached` → commit. The impl does NOT push or
   open a PR before notifying you.

6. **Pre-PR scope check (Claude).**
   - `bash scripts/impl-precommit-scope.sh --base origin/main
     --worktree <impl worktree path> --scope-file <packet allowlist>`. Both
     flags REQUIRED — without `--worktree` the script cwd-derives and
     silently validates main; without `--scope-file` the role allowlist
     alone is too broad. Exit 2 → REQUEST CHANGES; the impl re-enters the
     Impl Contract.
   - **codex-exec audit-trail check:** every file in `git -C <worktree>
     diff --name-only origin/main...HEAD` MUST appear in at
     least one `.codex-runs/<run-id>/git_diff.patch` on the branch. Any
     source change not traceable → REQUEST CHANGES (the impl bypassed
     codex-exec via Bash; this breaks the production-code-only-from-codex
     invariant).

7. **APPROVE → tell the impl to proceed.** The implementer pushes, creates
   the PR with `Closes VOI-N` in the body, posts a bare
   standalone `@codex review` PR comment, drives the eye-emoji loop (see
   `implementer.md`), and notifies Claude on `REVIEWED-CLEAN` or
   `CLEAN-COMMENT-MANUAL`.

8. **Final-head re-gate (Claude, at merge time).**
   - Rerun `bash scripts/impl-precommit-scope.sh --base
     origin/main --worktree <path> --scope-file <allowlist>`
     against the FINAL PR head. Codex-response commits can drift; the
     final-head re-gate is non-negotiable.
   - Rerun the codex-exec audit-trail check against the FINAL head.
   - Verify head-pinned Codex verdict + zero unresolved threads via
     `bash scripts/review-gate.sh status <pr>` showing `GATE: CLEAN`.
   - **Never merge on `review-gate.sh CLEAN` alone** — verify the head-pin
     (`commit.oid == headRefOid`). **Never auto-merge on `GATE:
     CLEAN-COMMENT-MANUAL`** — that requires explicit operator
     confirmation that the clean comment answered a request issued AFTER
     the current head was pushed.

9. **Merge (Claude).** `gh pr merge --squash --delete-branch`. The
   `Closes VOI-N` auto-transitions the Linear issue to Done
   (verify, don't assume).

10. **Teardown (Claude).** `git worktree remove <path>`; `git branch -D
    <branch>` if local lingers; `bash scripts/codex-runs-gc.sh --aggressive
    --days 3`. Conservative-mode GC is a no-op in this template (no
    autonomous loop writes `loop-status.txt`) — always run aggressive. The
    slug-protection check inside the GC script ensures live work is never
    collected.

**No commit, PR title, PR body, or Linear comment carries `Co-Authored-By`,
`🤖`, "Generated with Claude Code", or any Claude/Anthropic credit
footer.** Overrides any harness/tooling default.

## Deliver a working product (load-bearing — overrides "tests pass = done")

The deliverable is a **LIVE WORKING SYSTEM**, not a code drop. Every
packet's acceptance MUST include a **runtime verification step** that
exercises the user-visible behavior on the dev box — not just CI-style
mechanical gates (pytest, ruff, build). "Tests pass" / "ruff clean" /
"typecheck OK" are NECESSARY but never SUFFICIENT.

**The mantra (verbatim from the 2026-05-26 user directive):**

> "You are not delivering code, you are delivering a working project.
> That involves running things, bringing systems live, ensure they
> work. You deliver a live product that you ensure works, not code."

**How every packet spec.md MUST be written.**

The `## Acceptance` section MUST include a `### Runtime verification`
subsection listing:

1. The **EXACT command(s)** Claude (or the impl) runs on the dev box
   to exercise the user-visible behavior. Generic phrasing ("runs
   without errors") is INSUFFICIENT — be specific enough to detect
   regressions.
2. The **EXACT observable output** that confirms the system works.
   For executable scripts: actual stdout content + an exit code +
   a side-effect (file created, port listening, browser-renderable
   artifact present). For UI/visual deliverables: Claude opens the
   artifact in the intended viewer and visually confirms the
   spec-promised behavior.
3. For docs/architecture/knowledge-graph deliverables: the artifact
   loads + renders correctly in its intended viewer (browser, IDE,
   markdown preview, `/understand-dashboard`, etc.).

**Pull-quote for spec headers (use verbatim):**

> **Runtime verification (per CLAUDE.md §"Deliver a working product"):**
> This packet is not done when code merges. It's done when
> `[exact command(s)]` runs cleanly AND `[exact observable behavior]`.

**Pre-merge gate adds the runtime check.**

At final-head re-gate (the squash-merge step), Claude additionally
runs the live-verification step from the spec. If the live-run fails
or the output doesn't match what the spec promised, REJECT the PR
with the failure trace — even if all the mechanical gates passed.

**Phase exit gates (§"Build loop" + PLAN.md §2.3) get a new step:**

> 7. Claude has personally run the integrated phase deliverable
>    end-to-end and confirmed it works as advertised. Per-packet
>    mechanical gates do NOT substitute for this — the integrated
>    system, end-user-visible, must be alive.

For each phase: confirm all deliverables render, run, and behave as
advertised — not just that each packet's tests passed. A phase doesn't
close just because each packet's PR squash-merged.

**Anti-pattern this rule names.** Declaring a packet done because
tests returned 0 while never opening the artifact it produces;
merging a UI packet without actually running the interface;
shipping a demo packet without exercising the user-facing workflow
end-to-end.

## Evidence (no change merges without it)

Any number/claim a change asserts (computed outputs, metrics, behaviours)
**must be really produced by real logic** — never fabricated, hardcoded, or
mocked. The logic that produces it is unit-tested so "it is real" is
enforced, not asserted. The implementer subagent's Impl Contract enforces
this at the worker level; Claude verifies at pre-PR.

Per change:
- `uv run ruff check && uv run pytest` clean (typecheck + tests, incl. any determinism tests).
- `uv run ruff check` clean.
- If a visual/runtime inspection harness exists, `` — say
  what you observed and judged.
- **Runtime verification step from the spec's `## Acceptance` §
  "Runtime verification" — Claude runs it and confirms the output
  matches what was promised. Mandatory per the "Deliver a working
  product" doctrine above.**

## Internal review loop

One local reviewer + one PR reviewer = cross-family adversarial
coverage with minimum friction. Claude (`claude-opus-4-7` via the built-in
`/code-review` slash command) is the local reviewer; Codex
(`@codex review` after push) is the PR reviewer. Different families,
different surfaces (local diff vs PR commit), different lenses. One
plugin runs silently in the background for security hygiene.

**1. `/code-review --effort high` (Claude Code built-in, blocking,
local).** Runs on the impl's working-tree diff BEFORE commit.
Subscription-covered via OAuth (not metered API spend). Posts
severity-tagged findings in the P0/P1/P2/P3 scheme. The impl reads
the verdict, fixes `[P0]`/`[P1]` mandatory, judges `[P2]`. Iterate
until VERDICT: correct (or `NO BLOCKING ISSUES`). Pushing first and
letting the PR `@codex` bot find what local review would have caught
is the exact failure this rail prevents.

The impl's own `/code-review` is the load-bearing local gate for
production code; the rule extends to Claude when Claude is in the
implementer role for its own scope (rails / scripts / hooks / docs).

**2. `@codex review` on the PR (gpt-5.5, blocking via the merge gate).**
Cross-family vs Claude's local reviewer. Runs after push as the
official PR-level reviewer; its head-pinned verdict is part of the
merge gate. The impl drives the eye-emoji loop per § 7 + § 8e of
`.claude/agents/implementer.md`.

**3. `/security-review` (Claude Code plugin, auto-running,
non-blocking).** Install once via
`claude plugin install security-guidance@claude-plugins-official`.
Runs silently per-edit + on commit / push; auto-fixes flagged
vulnerabilities in the same session. No invocation needed; treated as
background hygiene.

**Deprecated:** the previous local-codex reviewer (`/codex:review`,
`scripts/codex-review.sh`, `codex-companion.mjs`) is deprecated as
of this section. The script + plugin stay installed for anyone who
wants to run codex locally on demand, but the impl loop no longer
requires it — codex review happens once, on the PR, via `@codex review`.
Same logic on the PR side: there is **no** PR-level `@claude review`
in this project — Claude's PR-reviewer GH-Actions workflow is
disabled at the trigger level (kept on `main` as `on: workflow_dispatch`
for documentation; never fires automatically).

**GH connector hygiene (avoid phantom cloud tasks).** Any `@codex` PR
comment other than the two accepted trigger forms below spawns a Codex
cloud task that narrates sandbox commits/PRs which do **NOT** land in
this repo. The accepted trigger forms:

1. **First review** (initial PR review request): a bare standalone
   **`@codex review`** and nothing else.
2. **Re-review** (after a fix iteration on the same PR): a comment
   whose first line is exactly `@codex review`, followed by the
   rationale block per `.claude/agents/implementer.md` § 8e —
   a "Changes since last review" enumeration and a "Not changed
   deliberately" enumeration. The rationale block prevents the
   reviewer from re-raising findings the impl already addressed.

Patterns that are NOT trigger forms:
- Fix narration (acknowledging a finding without re-running review) →
  comment with **NO** `@codex` mention; resolve the thread.
- Free-form `@codex …` mentions inside prose, code blocks, or thread
  replies → phantom-cloud-task vectors. Don't.

Treat the connector as an adversarial *reader* only — act on its
findings text; never on its self-reported commits/PRs/tests; verify
repo state if in doubt (`gh pr list --state all`,
`gh api …/commits/<sha>`).

**Claude is NOT a PR-level reviewer in this project.** The GH-Actions
workflow at `.github/workflows/claude-review.yml` is kept on `main`
for documentation but is disabled (`on: workflow_dispatch`, manual-
only). Claude's reviewer role is exercised LOCALLY in the impl loop
via the built-in Claude Code slash command `/code-review --effort
high` (subscription-covered, runs against the impl's working-tree
diff). See § "Internal review loop" below for the full local-reviewer
stack.

**`@codex review` re-trigger guard — the 👍 skip rule.** Codex's no-issues
verdicts contain `:+1:` (👍) in the review comment body. Before posting
**any** `@codex review` re-trigger, check the most recent codex bot
comment/review on the current PR head:
- If it contains 👍 / `:+1:` → it's a head-pinned no-issues verdict;
  **do NOT post `@codex review`.** The PR is review-clean for the current
  head; further codex calls just burn cycles and risk flaky non-deterministic
  flips.
- If no codex comment exists on the current head, or the most recent
  comment lacks 👍 → re-trigger is legitimate.
- A new commit pushed after a 👍 invalidates the 👍 (it was about the old
  head); the next re-trigger is allowed.

Check before triggering — delegate to the canonical helper, which
queries BOTH shapes (issue comments + PR Reviews) AND pins each
verdict to the current head SHA (`review.commit.oid == headRefOid`):

```bash
bash scripts/review-gate.sh status "$PR" | grep -qE '^GATE: CLEAN( |$)' && echo "skip" || echo "ok-to-trigger"
```

`GATE: CLEAN` means there is a head-pinned Codex review on the current
head, zero unresolved threads, and `mergeStateStatus = CLEAN`. Anything
else (`BLOCKED`, `CLEAN-COMMENT-MANUAL`, etc.) is ok-to-trigger.

**Caveat — when CLEAN is NOT a real clean verdict** (P1 hole codex
correctly flagged on PR #23 round 4): Codex posts findings as a
*Review* (head-pinned, body lists the findings) plus per-line review
comments. When Claude resolves those threads on a "rationale" /
"not changed deliberately" basis WITHOUT a fresh codex re-review,
the gate flips to CLEAN because the mechanical conditions are
satisfied (review is on head, threads are resolved, mss is CLEAN) —
but Codex never agreed with the rationale. So:

- If you're skipping changes on a finding ("not changed deliberately"),
  re-trigger via the §8e re-review format AFTER resolving the threads
  so Codex gets a chance to reject your rationale. Don't trust
  `GATE: CLEAN` after pure thread resolution.
- The mechanically robust path is: push → bare `@codex review`
  trigger → wait for codex's verdict (findings → fix → re-trigger
  with §8e block; no findings → CLEAN-COMMENT-MANUAL with a clean
  comment post-dating the current head).

The one-liner above is sufficient for the "Codex posted no findings
since the most recent push" case, but always trips through the
`/code-review` local pass first to surface anything codex might
not catch.

A hand-rolled one-liner over `issues/<n>/comments` is **not** sufficient:
- It misses Codex Reviews (the common no-issues shape after a fix
  iteration) — fails open on stale-Review verdicts.
- It doesn't pin to head SHA — a new commit after a 👍 still finds the
  old 👍 in the comments list and skips, contradicting the doctrine bullet
  above ("a new commit pushed after a 👍 invalidates the 👍").

Always delegate to `scripts/review-gate.sh status`. Don't hand-roll.

**Detecting the Codex verdict — use the canonical tool, never hand-roll.**
The Codex bot interacts with PRs in two shapes — both must be tracked:
- **Issue-comment verdicts** (PR issue comments): `gh pr view <n>
  --comments` or `gh api repos/.../issues/<n>/comments`.
- **Inline review threads** (file-line-anchored): `gh api
  repos/.../pulls/<n>/comments` (review comments). Must be **resolved** via
  `gh api graphql ... resolveReviewThread` once addressed; the merge gate
  requires zero unresolved codex threads.
- **Login form differs by API:** REST `user.login` =
  `chatgpt-codex-connector[bot]`; GraphQL `author.login` =
  `chatgpt-codex-connector` (no `[bot]`). Match **both** forms — narrow
  to one and a gate silently never recognizes the GraphQL-fetched review.

Use `scripts/review-gate.sh wait <pr>` (polls ~15s, returns the instant
Codex acts), `status <pr>`, `threads <pr>`. The merge gate is a **fresh
head-pinned Codex verdict (review.commit.oid == headRefOid) + zero
unresolved Codex threads + `mergeStateStatus = CLEAN`**. Never
`review-gate.sh CLEAN` alone. `CLEAN-COMMENT-MANUAL` is NEVER auto-clean
— it requires explicit operator confirmation that the comment answered an
`@codex review` issued after the current head was pushed.

Before hand-rolling any workflow mechanism, check `scripts/` for the
canonical helper. If a mode is missing, extend the script — don't
improvise a one-off.

## File-scope contract (Claude's own scope)

Claude itself is bounded by `hooks/write-scope-guard.mjs`. Allowed Claude
writes:
- `scripts/**`, `**/*.test.*` (orchestration tooling, tests)
- `.claude/**`, `.codex/**`, `.codex-runs/**`, `hooks/**` (agent
  behaviour surface + per-packet orchestration artifacts)
- `docs/**`, `**/*.md` (documentation; this CLAUDE.md, AGENTS.md, etc.)
- `architecture/**` (LikeC4 source — architecture-as-code, a docs
  deliverable rendered to `docs/architecture/*.svg`)
- `.understand-anything/**` (committed Understand-Anything knowledge graph,
  regenerated end-of-phase per PLAN.md — a docs deliverable, not source)
- `.gitignore` (root only — anchored exact-file rule, not `*.gitignore`)
- `~/.claude/projects/<encoded-key>/memory/**` (Claude Code project memory
  — outside the project root by design)

Anything else (production code, config, infra, fixtures — anything
outside the allowlist above) is denied. To change production code,
dispatch the implementer subagent. The hook explains in its deny
message which subagent_type to spawn.

The `architecture/**` and `.understand-anything/**` prefixes are also
Claude-exclusive in the impl's blocklist mode — the impl cannot write
LikeC4 source or knowledge-graph JSON via codex exec, mirroring how
`docs/**` is handled. Architecture-as-code and the committed graph are
authoring decisions, not transcription tasks.

The implementer subagent's tools list strips `Edit`/`Write`/`MultiEdit`
entirely (defense-in-depth — even if the hook were bypassed, the impl has
no tool to write a file directly). The impl writes via codex exec, period.

## Recurring failure classes (earned; kept current)

Self-review every substantive diff against these — each came from a real
past finding:

1. **Contracts / single source of truth** — shared values have one source;
   no self-referential config; cross-layer math matches reality. A component
   reused across layouts scopes its interaction styles per variant.
2. **Authored-intent correctness** — content/behaviour matches the spec;
   numbers really computed & unit-tested.
3. **Determinism** — no nondeterministic source (RNG/clock) in render/layout;
   seeded; same seed ⇒ same output.
4. **A11y / UX** — interactive elements are real controls with accessible
   names; keyboard + reduced-motion; responsive, no overflow at small sizes.
5. **Scope matchers must be anchored, not lenient** — when authoring any
   path/scope rule (hooks, gates, scope files), canonicalize the path
   first (`path.resolve` to collapse `..`), anchor to the active write
   root, then allow ONLY by: a strict prefix from the project root
   (`rel === p` or `rel.startsWith(p + '/')`), an explicit file path
   (`rel === '.gitignore'`), or a basename rule combined with a directory
   rule. NEVER allow by substring-anywhere (`.includes('/x/')`) — lets
   `src/components/scripts/evil.ts` pass as "scripts/". NEVER allow by
   extension-only (`/\.css$/.test(base)` standalone) — lets `.claude/hack.css`
   pass.

When a Codex finding reflects a class we *could* have caught ourselves, fold
it back — prefer an automated gate over a checklist line. The harness gets
harder to fool over time.

## Anti-rot (load-bearing)

- *Earned, not speculative* — every gate traces to a real past finding.
- *Trustworthy or gone* — a flaky / false-positive-prone gate is worse
  than none; fix it the same session or remove it. Never train the team
  to ignore a red gate.
- *Prune* — at each milestone boundary, re-judge the gate set; delete
  checks whose defect class is structurally impossible now, or that only
  duplicate a cheaper check.
- *Budget* — keep the gate suite fast and high-signal; speed keeps it used.

Faster shipping of *correct* work, not ceremony.

## Delegation & parallelism

Per-packet implementer subagents in their own worktrees are the parallelism
mechanism. Dispatch impls in parallel when work naturally parallelizes
(disjoint surfaces — each packet owns its files); serial is fine when it
doesn't. Idle Claude during a serial fan-in is acceptable if there's no
parallelizable work — say so plainly, don't fake the count.

**Disjoint surfaces.** Per packet, the spec's allowlist defines what files
the impl owns. The only shared touch tolerated is a 1-line registry/index
entry, reconciled by rebase at fan-in. If work isn't genuinely disjoint, it
isn't a parallel packet — engineer the seam (Claude-owned arch) first.

**Fan-in = Claude judgement only.** Mechanical (typecheck/tests/build,
local /code-review, eye-emoji loop) lives inside the implementer's Impl
Contract. Claude's serial time is the pre-PR scope check + audit-trail
check, the merge-time re-gate, and the squash-merge.

**Impl silent-death — RE-DISPATCH, never take over.** The Claude Code
subagent framework occasionally exits an implementer early after the impl
dispatched a codex worker but before the impl ran gates / staged /
committed / pushed. The visible symptom: codex-run artifacts present
(`exit_code.txt`, `git_diff.patch`), files modified in the worktree, but
no commit, no PR comment, and no notify-done message to Claude. The
INSTINCT is to take over the gates/commit/push/PR sequence from the
worktree — that violates the doctrine and accumulates Claude-as-impl
work that isn't audit-traced to the implementer contract.

The CORRECT response:
1. Confirm the codex worker fully exited (`exit_code.txt` present).
2. Re-dispatch a fresh `implementer` subagent with a continuation prompt
   that points at the worktree, names the completed codex run id(s),
   says "the codex worker for `voi-N-rK` exited successfully — your job
   starts at step 3 of the Impl Contract (run gates, stage, commit,
   notify Claude)", and references the spec.
3. The fresh impl runs gates, commits, and notifies — exactly the
   contract path. The audit trail stays intact (only impl-driven
   commits within the allowlist).

Do NOT manually run `uv run pytest` + `git add` + `git commit` + `git
push` from Claude as a shortcut. The pattern is the failure mode, not
the speed-up. Re-dispatch costs ~30s of overhead; protects the
delegation-first contract. The `.claude/agents/implementer.md`
subagent contract documents the continuation prompt shape.

**The flywheel.** A subagent miss is a *system* signal, not just a patch.
Every recurring fan-in fix → generalize the rule and fold it into
`.claude/agents/implementer.md` (subagent contract) and/or `AGENTS.md`
(codex worker contract), so worker output trends toward Claude's taste and
review load decays over time.

**Quality tripwire.** Track per-PR Codex + Claude fan-in fixes (by
severity) in `.codex-runs/parallel-metrics.tsv` if generated. If P0/P1
appears or P2/fix-rate trends up vs baseline, **throttle** concurrency and
clear backlog before widening again. Faking parallelism or merging past
the factual gate is never allowed.

## Worktrees & run artifacts

Per-packet worktrees are the standard — no shared checkout for any
production-code work. Provision via `scripts/worktree-new.sh <branch>
<name> <base>` (real APFS-cloned `node_modules` so the worktree is
immediately bootable; SHA-pinned base via `git fetch` first to avoid
stale-base artifacts). Override stale-fetch with `ALLOW_STALE_BASE=1`.
Worktrees sit at `<repo-parent>/.rag-nq-showcase-worktrees/<name>/`
(sibling-of-primary, out-of-repo so tooling in main doesn't see them).

After merge: `git worktree remove <path>`; `git branch -D <branch>` if
local lingers. `.codex-runs/` (gitignored, local-only) bloats fast — GC
with `bash scripts/codex-runs-gc.sh --aggressive --days 3` at milestone
boundaries / when slots recycle. **Always use `--aggressive`** in this
template: there is no autonomous bash loop writing `loop-status.txt`, so
conservative-mode GC never fires. The slug-protection check inside the
script still prevents collecting any family with an alive non-merged
branch — `--aggressive` just means "if no protective branch and older
than --days, collect."

`parallel-metrics.tsv` (durable synthesis signal) is never touched by GC.

## Project specifics

- Build/test/inspect commands: see "Evidence" above (configured at
  template instantiation; edit here as the project evolves).
- `.env` (gitignored) holds optional keys for a *possible* future feature.
  Never commit/log them; never spend them without an explicit go-ahead.
- See `~/.claude` project memory for goal/architecture/autonomy notes.
