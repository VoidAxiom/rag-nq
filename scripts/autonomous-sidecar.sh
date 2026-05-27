#!/usr/bin/env bash
# Autonomous-mode sidecar for rag-nq-showcase.
#
# Prints a COMPACT (<30 line) tick: mantra → per-packet state + decision
# → trailer. Designed so each ~20-min tick costs minimal context.
#
# Usage: bash scripts/autonomous-sidecar.sh
# Read-only. Exit 0 always (unless self-error).

set -uo pipefail

# Derive REPO from script location so the sidecar works from any clone.
# Script lives at <repo>/scripts/autonomous-sidecar.sh, so two parents up
# is <repo>. Override with RAG_NQ_SHOWCASE_REPO if running from outside
# the tree (rare). Use cd + pwd to canonicalize without depending on
# bash-4-only realpath / GNU readlink.
_SIDECAR_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_SIDECAR_REPO_DEFAULT="$(cd "${_SIDECAR_SCRIPT_DIR}/.." && pwd)"
REPO="${RAG_NQ_SHOWCASE_REPO:-${_SIDECAR_REPO_DEFAULT}}"
# Worktrees default to siblings of the repo (per scripts/worktree-new.sh).
WT_ROOT="${RAG_NQ_SHOWCASE_WORKTREES:-$(dirname "${REPO}")/.rag-nq-showcase-worktrees}"
STALL_MIN="${SIDECAR_STALL_MIN:-15}"
GH_OWNER="${RAG_NQ_SHOWCASE_OWNER:-VoidAxiom}"
GH_REPO_NAME="${RAG_NQ_SHOWCASE_REPO_NAME:-rag-nq}"
COMMAND_CENTER="${RAG_NQ_SHOWCASE_COMMAND_CENTER:-VOI-243}"

cd "$REPO" 2>/dev/null || { echo "✗ sidecar: cannot cd $REPO" >&2; exit 1; }
# .codex-runs/ is gitignored and may not exist on a fresh checkout;
# the sidecar writes a couple of state markers into it. Create up
# front so the later `echo ... > "$MARKER"` redirections don't fail.
mkdir -p "$REPO/.codex-runs" 2>/dev/null || true
now=$(date +%s)

# Portable ISO-8601 ("2026-05-27T04:52:31Z") → epoch parser.
# Why python3: macOS ships BSD `date` (uses `-j -f <fmt>`), Linux ships
# GNU `date` (uses `-d <str>`); neither flag set works on the other.
# Python is already a dependency of this script (used for JSON parsing
# below), so reuse it for one consistent code path.
_iso_to_epoch() {
  python3 -c 'import datetime, sys
try:
    s = sys.argv[1]
    dt = datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
    print(int(dt.replace(tzinfo=datetime.timezone.utc).timestamp()))
except Exception:
    print(0)' "$1" 2>/dev/null || echo 0
}

# Fetch all pages of a GitHub list API and merge into one JSON array.
# `gh api --paginate` emits each page's body in sequence (concatenated
# JSON arrays); a `gh api --jq` filter applied across that stream would
# run per-page, breaking `sort_by | last` semantics across pages. We
# stream the concatenated bodies through python's JSONDecoder.raw_decode
# to extract each array, then merge them into a single array on stdout.
# Usage: _paginate_json <url> → one merged JSON array on stdout (or "[]"
# on any error). Caller can pipe through `python3 -c` for filtering.
_paginate_json() {
  # Capture gh output to a temp file so a gh failure doesn't get fed
  # to python (which would still print `[]` on empty input AND let the
  # outer `|| echo "[]"` fire too — producing `[]\n[]` on the caller's
  # stdin and breaking the downstream `json.load` parse). One round-trip
  # through a temp file lets us check `gh`'s exit code before parsing
  # and emit exactly one `[]` on any failure.
  local tmp
  tmp=$(mktemp 2>/dev/null) || { echo "[]"; return 0; }
  if ! gh api --paginate "$1" >"$tmp" 2>/dev/null; then
    rm -f "$tmp"
    echo "[]"
    return 0
  fi
  python3 -c '
import json, sys
text = open(sys.argv[1]).read().strip()
if not text:
    print("[]"); sys.exit(0)
decoder = json.JSONDecoder()
merged, idx = [], 0
while idx < len(text):
    rest = text[idx:].lstrip()
    if not rest: break
    idx += len(text[idx:]) - len(rest)
    try:
        obj, end = decoder.raw_decode(rest)
    except Exception:
        break
    if isinstance(obj, list):
        merged.extend(obj)
    else:
        merged.append(obj)
    idx += end
print(json.dumps(merged))
' "$tmp" 2>/dev/null || echo "[]"
  rm -f "$tmp"
}

# ── ALWAYS fetch latest main from origin (every tick, no exception) ──
# Without this, the sidecar reads a stale local origin/main and misses
# merges Claude made in another worktree or that landed via squash-
# merge from a PR. That makes "newly merged" detection below useless.
git fetch origin main --quiet 2>/dev/null || true

# ── backup-tick skip ──
# Cron fires 3 ticks at 1-min spacing per cycle so a socket-error-killed
# Claude turn gets retried within 60-120s. If the prior tick completed
# end-to-end (Claude wrote the marker at end-of-turn), this tick is a
# backup we don't need — exit fast with a SKIP signal so Claude's turn
# ends immediately.
MARKER="$REPO/.codex-runs/sidecar-last-success.txt"
if [ -f "$MARKER" ]; then
  marker_epoch=$(cat "$MARKER" 2>/dev/null || echo 0)
  age=$(( now - marker_epoch ))
  if [ "$age" -lt 90 ]; then
    echo "BACKUP-TICK SKIP — prior tick succeeded ${age}s ago (<90s); end turn, no work needed"
    exit 0
  fi
fi

# ── tick header + mantra ──
# Mirrors CLAUDE.md §"Autonomous mode" → "The mantra" verbatim so the
# operating sidecar tick is the source-of-truth for the loop's discipline.
echo "=== AUTONOMOUS sidecar tick @ $(date +%H:%M:%S) ==="
echo "mantra: You deliver a working LIVE PRODUCT, not code. A merged PR is not"
echo "  the deliverable; the artifact running on primary at spec scale producing"
echo "  the measurable outcome IS the deliverable."
echo "  ACT, DON'T NARRATE. Every stall is a failure to act."
echo "  · Impl silent → TaskList check; alive=wait, dead=re-dispatch"
echo "  · Codex 👀'd → wait verdict; not 👀'd & past wait-helper's 120s ackWaitSec → review-gate.sh wait auto-retriggers; this sidecar's coarser fallback re-triggers at >${STALL_MIN}min"
echo "  · PR clean → final-head mechanical re-gate → squash-merge → pull main →"
echo "    live-verify on primary against the merged-in code → re-open on mismatch"
echo "  · Queue has next → dispatch (ONLY after current packet's live-on-primary passes)"
echo "  · Genuinely external-blocked & nothing pending → end turn cleanly"
echo

# ── primary (1 line) ──
main_head=$(git log --oneline -1 origin/main 2>/dev/null | cut -c1-72)
echo "primary: $main_head"

# ── newly-merged PRs since last tick (cross-tick state) ──
# Compares current origin/main HEAD to the SHA we saw last tick. Any new
# commits on main are squash-merges from PRs (per repo policy). For each,
# pull the PR number from the conventional "(#N)" subject suffix and
# emit an ACT-NOW so Claude dispatches impls on any newly-unblocked work.
LAST_MAIN_MARKER="$REPO/.codex-runs/sidecar-last-known-main.txt"
cur_main_sha=$(git rev-parse origin/main 2>/dev/null || echo "")
prev_main_sha=""
[ -f "$LAST_MAIN_MARKER" ] && prev_main_sha=$(cat "$LAST_MAIN_MARKER" 2>/dev/null | head -c 40)
merged_voi_list=""
merged_pr_list=""
saw_merge=""
if [ -n "$prev_main_sha" ] && [ "$prev_main_sha" != "$cur_main_sha" ]; then
  # Walk new commits oldest→newest; extract VOI-N from "Closes VOI-N" or
  # the conventional "(#PR)" squash-merge suffix. Per the squash-merge
  # convention the conventional commit subject is title-only (no VOI
  # token) and `Closes VOI-N` lives in the PR body, which `gh pr merge
  # --squash` carries into the merge commit body. Per-commit, scan
  # %B (subject + body) for the VOI token so body-only closures are
  # detected; the subject is still used for the display line.
  new_merges=$(git log --pretty='%H %s' "$prev_main_sha..origin/main" 2>/dev/null | head -50)
  if [ -n "$new_merges" ]; then
    echo
    echo "merged since last tick:"
    while IFS= read -r line; do
      sha=${line:0:7}
      full_sha=${line:0:40}
      subject=${line:41}
      pr_num=$(echo "$subject" | grep -oE '\(#[0-9]+\)' | tr -d '(#)' | head -1)
      # Scan the full commit body (%B) for VOI tokens; %s alone misses
      # `Closes VOI-N` trailers carried into the squash-merge body.
      voi_num=$(git -C "$REPO" log -1 --pretty='%B' "$full_sha" 2>/dev/null | grep -oE 'VOI-[0-9]+' | head -1)
      echo "  + $sha PR#${pr_num:-?} ${voi_num:-?}: $(echo "$subject" | cut -c1-60)"
      saw_merge="yes"
      [ -n "$voi_num" ] && merged_voi_list="$merged_voi_list $voi_num"
      [ -z "$voi_num" ] && [ -n "$pr_num" ] && merged_pr_list="$merged_pr_list #$pr_num"
    done <<< "$new_merges"
  fi
fi
# Update marker for next tick — but only when there's nothing new to act
# on. If we just emitted ACT-NOW for newly-merged PRs and the turn dies
# before Claude dispatches the unblocked work, advancing the marker now
# would hide those merges on the backup tick and defeat the retry path
# (the success-marker skip wouldn't fire either because Claude never
# wrote it). Leave the marker on the old SHA so the next tick re-detects
# the merges; advance it only on a quiet tick (no merges this turn —
# `saw_merge` covers both VOI-tagged and PR-only merges, like META PRs).
if [ -z "$saw_merge" ]; then
  echo "$cur_main_sha" > "$LAST_MAIN_MARKER"
fi
echo

# ── packets (per-worktree + per-PR, condensed) ──
WTS=$(git worktree list --porcelain | awk '/^worktree / {print $2}' | grep "^$WT_ROOT" || true)
# Don't silently coalesce `gh` failures (no auth, rate-limit, `gh`
# unavailable, transient API error) into `[]` — that would make the
# "between packets" branch fire and tell Claude to dispatch new work
# while open PRs may still need action. Capture stderr separately and
# flag PR_COUNT=? so the decision branch can route to ACT-NOW [verify]
# instead of the empty-queue path.
PRS_STDERR=$(mktemp)
PRS_JSON=$(gh pr list --state open --json number,headRefName,headRefOid,title 2>"$PRS_STDERR")
gh_rc=$?
if [ $gh_rc -ne 0 ] || [ -z "$PRS_JSON" ]; then
  PR_COUNT="?"
  PRS_JSON='[]'
  PRS_ERR=$(head -c 200 < "$PRS_STDERR" 2>/dev/null || true)
else
  PR_COUNT=$(echo "$PRS_JSON" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))')
  PRS_ERR=""
fi
rm -f "$PRS_STDERR"

actions_now=0
verify_owed=0
in_flight=0

if [ "$PR_COUNT" = "?" ]; then
  echo "packets: (gh pr list FAILED rc=$gh_rc — ${PRS_ERR:-no stderr captured})"
  echo "  → ACT-NOW: verify gh auth / network / rate-limit; do NOT dispatch new packets until PR queue is observable"
  actions_now=1
elif [ -z "$WTS" ] && [ "$PR_COUNT" = "0" ]; then
  echo "packets: (none in flight — between packets)"
  echo "  → ACT-NOW: read $COMMAND_CENTER (command center) + active phase issue, dispatch next packet"
  actions_now=1
else
  echo "packets:"
  # Track branches covered by worktree iteration so the second pass can
  # process open PRs whose branch has no worktree (director-owned doc/CI
  # PRs from primary, cherry-pick branches, etc).
  covered_branches=""
  for wt in $WTS; do
    wt_name=$(basename "$wt")
    branch=$(git -C "$wt" rev-parse --abbrev-ref HEAD 2>/dev/null)
    head_full=$(git -C "$wt" rev-parse HEAD 2>/dev/null)
    head_short=${head_full:0:7}
    ahead=$(git -C "$wt" rev-list --count origin/main..HEAD 2>/dev/null)

    # pushed?
    pushed="unpushed"
    if git -C "$wt" ls-remote --exit-code origin "$branch" >/dev/null 2>&1; then
      remote_head=$(git -C "$wt" ls-remote origin "$branch" 2>/dev/null | awk '{print $1}')
      [ "$remote_head" = "$head_full" ] && pushed="pushed" || pushed="local-ahead"
    fi

    # PR for branch?
    pr_num=$(echo "$PRS_JSON" | python3 -c "
import json,sys
for p in json.load(sys.stdin):
    if p['headRefName']=='$branch':
        print(p['number']); break
")

    # liveness: max(last commit, newest .codex-runs artifact)
    last_commit=$(git -C "$wt" log -1 --format=%ct 2>/dev/null || echo 0)
    newest_run=0
    if [ -d "$wt/.codex-runs" ]; then
      # Portable mtime via python3 — BSD `stat -f %m` and GNU `stat -c %Y`
      # differ in flag conventions, and the prior `stat -f %m` path silently
      # emitted filesystem-status text on GNU stat, breaking the numeric
      # comparison and mis-classifying active impls as stalled.
      newest_run=$(find "$wt/.codex-runs" -type f -print0 2>/dev/null \
        | python3 -c 'import os, sys
chunks = sys.stdin.buffer.read().split(b"\0")
best = 0
for p in chunks:
    if not p: continue
    try:
        m = int(os.path.getmtime(p.decode("utf-8", "surrogateescape")))
        if m > best: best = m
    except Exception:
        pass
print(best)' 2>/dev/null || echo 0)
      newest_run=${newest_run:-0}
    fi
    last_local=$last_commit
    [ "$newest_run" -gt "$last_local" ] && last_local=$newest_run
    local_age=$(( (now - last_local) / 60 ))

    # PR-side data
    pr_age="?"
    gate="?"
    threads_open=0
    acked="?"
    if [ -n "$pr_num" ]; then
      last_comment_iso=$(_paginate_json "repos/$GH_OWNER/$GH_REPO_NAME/issues/$pr_num/comments" \
        | python3 -c 'import json,sys
try:
    a = json.load(sys.stdin)
    print(max((c.get("updated_at","") for c in a), default=""))
except Exception:
    pass' 2>/dev/null)
      if [ -n "$last_comment_iso" ]; then
        last_comment_epoch=$(_iso_to_epoch "$last_comment_iso")
        pr_age=$(( (now - last_comment_epoch) / 60 ))
      fi
      status_out=$(bash "$REPO/scripts/review-gate.sh" status "$pr_num" 2>&1)
      gate=$(echo "$status_out" | grep -oE 'GATE: [A-Z-]+( \(.*\))?' | head -1 || echo "?")
      threads_open=$(echo "$status_out" | grep -oE '[0-9]+ UNRESOLVED' | grep -oE '^[0-9]+' || echo 0)
      # 👀-ack on latest non-codex @codex review request (all pages)
      latest_rr=$(_paginate_json "repos/$GH_OWNER/$GH_REPO_NAME/issues/$pr_num/comments" \
        | python3 -c 'import json,sys
try:
    a = json.load(sys.stdin)
    f = [c for c in a if (c.get("body","").startswith("@codex review"))
         and (c.get("user",{}).get("login") not in ("chatgpt-codex-connector","chatgpt-codex-connector[bot]"))]
    print(json.dumps(sorted(f, key=lambda c: c.get("created_at",""))[-1]) if f else "null")
except Exception:
    print("null")' 2>/dev/null)
      eyes_age="-"; rr_age="-"
      if [ -n "$latest_rr" ] && [ "$latest_rr" != "null" ]; then
        rr_id=$(echo "$latest_rr" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' 2>/dev/null)
        rr_at=$(echo "$latest_rr" | python3 -c 'import json,sys; print(json.load(sys.stdin)["created_at"])' 2>/dev/null)
        if [ -n "$rr_at" ]; then
          rr_epoch=$(_iso_to_epoch "$rr_at")
          rr_age=$(( (now - rr_epoch) / 60 ))
        fi
        if [ -n "$rr_id" ]; then
          # Fetch the 👀 reaction's created_at (not just count) — the
          # verdict-wait timer for `acked=yes` must be measured from the
          # 👀 timestamp, not local/comment activity. Otherwise, if codex
          # 👀s a long-stale request on a PR with no threads, the
          # `recent`-based comparison already exceeds STALL_MIN at the
          # moment of the 👀 and immediately re-dispatches before the
          # verdict is in flight. Symmetric with the orphan-PR pass.
          eyes_at=$(gh api "repos/$GH_OWNER/$GH_REPO_NAME/issues/comments/$rr_id/reactions" \
            --jq '[.[] | select(.content=="eyes") | select(.user.login=="chatgpt-codex-connector[bot]" or .user.login=="chatgpt-codex-connector")] | sort_by(.created_at) | last.created_at // ""' 2>/dev/null)
          if [ -n "$eyes_at" ] && [ "$eyes_at" != "null" ]; then
            acked="yes"
            eyes_epoch=$(_iso_to_epoch "$eyes_at")
            eyes_age=$(( (now - eyes_epoch) / 60 ))
          else
            acked="no"
          fi
        fi
      fi
    fi

    # most recent activity (local or PR) — used for "no 👀" stall calc.
    recent=$local_age
    [ "$pr_age" != "?" ] && [ "$pr_age" -lt "$recent" ] && recent=$pr_age

    # decision
    if [ -n "$pr_num" ]; then
      if echo "$gate" | grep -q 'CLEAN (' && [ "$pushed" = "local-ahead" ]; then
        # Don't recommend merge while the worktree has unpushed commits — the
        # gate describes the PR head, not the local head, so merging would
        # silently omit the local-ahead commits. Push first, then re-gate.
        decision="ACT-NOW: head-pinned CLEAN on PR head — but worktree is local-ahead (unpushed). Push first, then re-gate"
        actions_now=$((actions_now+1))
      elif echo "$gate" | grep -q 'CLEAN ('; then
        decision="ACT-NOW: head-pinned CLEAN — final-head mechanical re-gate → squash-merge → pull main → live-verify on primary per spec.md Runtime-verification"
        actions_now=$((actions_now+1))
      elif echo "$gate" | grep -q 'CLEAN-COMMENT-MANUAL' && [ "$pushed" = "local-ahead" ]; then
        decision="ACT-NOW: CLEAN-COMMENT-MANUAL on PR head — but worktree is local-ahead (unpushed). Push first, then re-judge timeline + re-gate"
        actions_now=$((actions_now+1))
      elif echo "$gate" | grep -q 'CLEAN-COMMENT-MANUAL'; then
        decision="ACT-NOW: CLEAN-COMMENT-MANUAL — judge timeline (clean comment must post-date current head) → squash-merge → pull main → live-verify on primary per spec.md Runtime-verification"
        actions_now=$((actions_now+1))
      elif [ "$threads_open" -gt 0 ]; then
        # FINDINGS arrived (threads_open > 0 IS terminal per review-gate.sh
        # wait, not "in flight"). The actionable step is TaskList check on
        # the impl + re-dispatch if dead — NOT waiting on the 👀. Skip the
        # 👀-grace branches; the 👀 was the ack for the original review
        # request, but findings are now what need acting on.
        if [ "$recent" -lt "$STALL_MIN" ]; then
          decision="VERIFY: $threads_open unresolved findings + ${recent}min idle — TaskList alive? else re-dispatch with state-aware resume"
          verify_owed=$((verify_owed+1))
        else
          decision="ACT-NOW: $threads_open unresolved findings + ${recent}min silent — re-dispatch impl"
          actions_now=$((actions_now+1))
        fi
      else
        # threads=0, waiting on first review
        if [ "$acked" = "yes" ] && [ "$eyes_age" != "-" ] && [ "$eyes_age" -lt 30 ] 2>/dev/null; then
          decision="NO-ACTION: codex 👀'd ${eyes_age}min ago, verdict in flight (≤30min per review-gate.sh wait)"
          in_flight=$((in_flight+1))
        elif [ "$acked" = "yes" ] && [ "$eyes_age" != "-" ]; then
          decision="ESCALATE: codex 👀'd ${eyes_age}min ago, no verdict past 30min verdictMaxSec — notify operator, do NOT re-trigger (would queue redundant cloud task per review-gate.sh §Phase 2)"
          actions_now=$((actions_now+1))
        elif [ "$rr_age" != "-" ] && [ "$rr_age" -ge "$STALL_MIN" ] 2>/dev/null; then
          # Un-acked @codex review request older than STALL_MIN — re-trigger (Phase 1).
          decision="ACT-NOW: @codex review ${rr_age}min ago + no 👀 (> ${STALL_MIN}min STALL_MIN) — re-trigger (codex may have missed)"
          actions_now=$((actions_now+1))
        elif [ "$recent" -lt "$STALL_MIN" ]; then
          decision="NO-ACTION: ${recent}min idle, in wait helper grace window"
          in_flight=$((in_flight+1))
        else
          decision="ACT-NOW: ${recent}min silent + no 👀 — re-dispatch wait"
          actions_now=$((actions_now+1))
        fi
      fi
    else
      # no PR
      if [ "$ahead" -gt 0 ] && [ "$pushed" = "unpushed" ]; then
        if [ "$recent" -lt "$STALL_MIN" ]; then
          decision="VERIFY: $ahead unpushed commits, ${recent}min idle — impl about to notify? else pre-PR + re-dispatch"
          verify_owed=$((verify_owed+1))
        else
          decision="ACT-NOW: $ahead unpushed + ${recent}min silent — pre-PR gate + re-dispatch push"
          actions_now=$((actions_now+1))
        fi
      elif [ "$ahead" -gt 0 ] && [ "$pushed" = "local-ahead" ]; then
        decision="ACT-NOW: $ahead commits + worktree is local-ahead (remote branch exists but local HEAD moved) — push first, then open PR (else PR would review/merge the stale remote branch and omit local commits)"
        actions_now=$((actions_now+1))
      elif [ "$ahead" -gt 0 ]; then
        decision="ACT-NOW: $ahead commits pushed, no PR — re-dispatch impl to open PR"
        actions_now=$((actions_now+1))
      else
        if [ "$recent" -lt "$STALL_MIN" ]; then
          decision="NO-ACTION: 0 commits, ${recent}min activity — impl in inner loop"
          in_flight=$((in_flight+1))
        else
          decision="VERIFY: 0 commits + ${recent}min silent — impl stalled in inner loop?"
          verify_owed=$((verify_owed+1))
        fi
      fi
    fi

    # 1-line packet summary
    if [ -n "$pr_num" ]; then
      pr_tag="PR#$pr_num $gate threads:$threads_open 👀:$acked"
    else
      pr_tag="no PR"
    fi
    echo "  $wt_name [$head_short $ahead-ahead $pushed] $pr_tag"
    echo "    → $decision"
    covered_branches="$covered_branches|$branch|"
  done

  # ── second pass: open PRs not backed by a worktree (director-owned
  # branches from primary checkout, cherry-pick branches, etc).
  # Without this, PRs that don't map to a worktree are invisible to the
  # sidecar and rot unattended — exact failure mode that left PR #23's
  # codex 15-thread set sitting for 30+ min on 2026-05-26.
  while IFS=$'\t' read -r pr_num branch head_sha; do
    case "$covered_branches" in *"|$branch|"*) continue ;; esac
    head_short=${head_sha:0:7}

    # Ownership: who's supposed to be driving this PR?
    # Claude (director) owns PRs whose ENTIRE changed-file set is in
    # Claude's exclusive territory: .claude/**, .codex/**, hooks/**,
    # docs/**, scripts/**, architecture/**, .understand-anything/**,
    # **/*.md, root .gitignore. Otherwise the PR touches production
    # code → impl-owned.
    owner="impl"
    changed_files=$(gh pr view "$pr_num" --json files --jq '.files[].path' 2>/dev/null)
    if [ -n "$changed_files" ]; then
      owner="claude"
      while IFS= read -r f; do
        case "$f" in
          .claude/*|.codex/*|hooks/*|docs/*|scripts/*|architecture/*|.understand-anything/*|*.md|.gitignore) ;;
          *) owner="impl"; break ;;
        esac
      done <<< "$changed_files"
    fi

    # Impl-presence: any IMPL worktree (under $WT_ROOT) for this branch?
    # Excludes the primary checkout — git worktree list reports primary
    # too, but primary on a branch ≠ impl dispatched on that branch. The
    # convention is impl worktrees live at $WT_ROOT/<name>/. If owner=impl
    # AND impl_present=no, impl was never dispatched OR died and the
    # worktree was torn down — director must spawn a fresh impl.
    impl_present="no"
    if [ -d "$WT_ROOT" ]; then
      while read -r wt_path; do
        case "$wt_path" in "$WT_ROOT"/*)
          wt_branch=$(git -C "$wt_path" rev-parse --abbrev-ref HEAD 2>/dev/null)
          [ "$wt_branch" = "$branch" ] && impl_present="yes" && break
          ;;
        esac
      done < <(git worktree list --porcelain | awk '/^worktree / {print $2}')
    fi

    # PR-side state (head SHA, gate, threads, 👀, codex-clean-on-head)
    status_out=$(bash "$REPO/scripts/review-gate.sh" status "$pr_num" 2>&1)
    gate=$(echo "$status_out" | grep -oE 'GATE: [A-Z-]+( \(.*\))?' | head -1 || echo "?")
    threads_open=$(echo "$status_out" | grep -oE '[0-9]+ UNRESOLVED' | grep -oE '^[0-9]+' || echo 0)

    # Latest @codex review request from a non-bot (all pages, timestamp + 👀)
    latest_rr=$(_paginate_json "repos/$GH_OWNER/$GH_REPO_NAME/issues/$pr_num/comments" \
      | python3 -c 'import json,sys
try:
    a = json.load(sys.stdin)
    f = [c for c in a if (c.get("body","").startswith("@codex review"))
         and (c.get("user",{}).get("login") not in ("chatgpt-codex-connector","chatgpt-codex-connector[bot]"))]
    print(json.dumps(sorted(f, key=lambda c: c.get("created_at",""))[-1]) if f else "null")
except Exception:
    print("null")' 2>/dev/null)
    acked="?"; rr_age="-"; eyes_age="-"
    if [ -n "$latest_rr" ] && [ "$latest_rr" != "null" ]; then
      rr_id=$(echo "$latest_rr" | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])' 2>/dev/null)
      rr_at=$(echo "$latest_rr" | python3 -c 'import json,sys; print(json.load(sys.stdin)["created_at"])' 2>/dev/null)
      if [ -n "$rr_id" ]; then
        # Fetch the 👀 reaction's created_at (not just count) — the stall
        # timer for `acked=yes` must be measured from the 👀 timestamp, not
        # the request timestamp. Otherwise, if codex 👀s a long-stale request,
        # rr_age can already exceed STALL_MIN at the moment of the 👀,
        # immediately tripping a re-trigger before the verdict is in flight.
        eyes_at=$(gh api "repos/$GH_OWNER/$GH_REPO_NAME/issues/comments/$rr_id/reactions" \
          --jq '[.[] | select(.content=="eyes") | select(.user.login=="chatgpt-codex-connector[bot]" or .user.login=="chatgpt-codex-connector")] | sort_by(.created_at) | last.created_at // ""' 2>/dev/null)
        if [ -n "$eyes_at" ] && [ "$eyes_at" != "null" ]; then
          acked="yes"
          eyes_epoch=$(_iso_to_epoch "$eyes_at")
          eyes_age=$(( (now - eyes_epoch) / 60 ))
        else
          acked="no"
        fi
      fi
      if [ -n "$rr_at" ]; then
        rr_epoch=$(_iso_to_epoch "$rr_at")
        rr_age=$(( (now - rr_epoch) / 60 ))
      fi
    fi

    # Decision: owner directs who does the work.
    # - Claude-owned (doc/CI): Claude drives everything — fix findings via
    #   Edit/Bash, post @codex review, merge.
    # - Impl-owned: if impl_present=yes, impl is alive (or was) → check
    #   in via TaskList, re-dispatch if dead. If impl_present=no, the PR
    #   was opened without a worktree (e.g. you took over an impl-scope
    #   change directly, which violates the cardinal rule) — spawn a
    #   fresh impl for the fix and stop hand-editing impl-scope files.
    if echo "$gate" | grep -q 'CLEAN ('; then
      decision="ACT-NOW [$owner]: head-pinned CLEAN — final-head mechanical re-gate → squash-merge → pull main → live-verify on primary per spec.md Runtime-verification"
      actions_now=$((actions_now+1))
    elif echo "$gate" | grep -q 'CLEAN-COMMENT-MANUAL'; then
      decision="ACT-NOW [$owner]: CLEAN-COMMENT-MANUAL — judge timeline (push < @codex review < clean comment) → squash-merge → pull main → live-verify on primary per spec.md Runtime-verification"
      actions_now=$((actions_now+1))
    elif [ "$threads_open" -gt 0 ]; then
      if [ "$owner" = "claude" ]; then
        decision="ACT-NOW [claude]: $threads_open unresolved threads on doc/CI PR — read findings, fix via Edit/Bash, commit/push, resolve, re-trigger"
      elif [ "$impl_present" = "yes" ]; then
        decision="ACT-NOW [impl]: $threads_open unresolved threads — check impl via TaskList; alive=let them iterate, dead=re-dispatch with state-aware resume"
      else
        decision="ACT-NOW [impl ORPHANED]: $threads_open unresolved + impl-scope files but NO worktree — spawn a fresh impl for the fix; do NOT hand-edit impl-scope yourself"
      fi
      actions_now=$((actions_now+1))
    elif [ "$acked" = "yes" ]; then
      # Phase 2 of review-gate.sh wait: once 👀 lands, STOP re-triggering
      # (would queue redundant cloud tasks). Wait until ≤30min
      # (verdictMaxSec default); past that, ESCALATE to operator —
      # do NOT re-trigger.
      if [ "$eyes_age" != "-" ] && [ "$eyes_age" -ge 30 ] 2>/dev/null; then
        decision="ESCALATE [$owner]: codex 👀'd ${eyes_age}min ago, no verdict past 30min verdictMaxSec — notify operator, do NOT re-trigger (would queue redundant cloud task per review-gate.sh §Phase 2)"
        actions_now=$((actions_now+1))
      else
        decision="NO-ACTION [$owner]: codex 👀'd ${eyes_age}min ago — verdict in flight (≤30min per review-gate.sh wait)"
        in_flight=$((in_flight+1))
      fi
    elif [ "$rr_age" = "-" ]; then
      decision="ACT-NOW [$owner]: PR open + no @codex review yet — post bare @codex review"
      actions_now=$((actions_now+1))
    elif [ "$rr_age" -ge "$STALL_MIN" ] 2>/dev/null; then
      decision="ACT-NOW [$owner]: @codex review posted ${rr_age}min ago + no 👀 (≥ ${STALL_MIN}min STALL_MIN) — re-trigger (codex may have missed)"
      actions_now=$((actions_now+1))
    else
      decision="NO-ACTION [$owner]: @codex review posted ${rr_age}min ago + no 👀, grace window (≤ ${STALL_MIN}min STALL_MIN)"
      in_flight=$((in_flight+1))
    fi

    echo "  orphan-PR $branch [$head_short] PR#$pr_num $gate threads:$threads_open 👀:$acked rr:${rr_age}min"
    echo "    → $decision"
  done < <(echo "$PRS_JSON" | python3 -c '
import json, sys
for p in json.load(sys.stdin):
    n, b, o = p["number"], p["headRefName"], p["headRefOid"]
    print("\t".join([str(n), b, o]))
' 2>/dev/null)
fi

# Bump ACT-NOW if anything merged this tick BEFORE printing the summary,
# so the compact "X ACT-NOW" line reflects the merge-driven action that
# wrapper scripts and operators rely on. Both VOI-tagged merges (phase
# packets) and PR-only merges (META PRs without VOI IDs) qualify.
if [ -n "$saw_merge" ]; then
  actions_now=$((actions_now+1))
fi
echo
echo "tick summary: ${actions_now} ACT-NOW, ${verify_owed} VERIFY, ${in_flight} NO-ACTION (in-flight)"
if [ -n "$saw_merge" ]; then
  if [ -n "$merged_voi_list" ]; then
    echo "→ ACT-NOW (newly merged VOI):${merged_voi_list}"
  fi
  if [ -n "$merged_pr_list" ]; then
    echo "→ ACT-NOW (newly merged PRs, no VOI tag):${merged_pr_list}"
  fi
  echo "  - Live-verify each on primary per packet acceptance (Outcome over output)."
  echo "  - Read $COMMAND_CENTER + active phase issue + spec/PHASE_*.md DAG; any issue"
  echo "    whose deps just closed is now unblocked — dispatch impl(s) immediately,"
  echo "    in parallel where file surfaces are disjoint."
  echo
fi
if [ "$actions_now" = "0" ] && [ "$verify_owed" = "0" ]; then
  echo "→ end turn cleanly; next tick in ~20min"
fi
echo
echo "→ Claude: write BOTH end-of-turn markers as your LAST action:"
echo "    echo $(date +%s) > $MARKER"
if [ -n "$saw_merge" ] && [ -n "$cur_main_sha" ]; then
  # Also advance LAST_MAIN_MARKER to the current origin/main SHA — we
  # deferred this advance up-top to keep the backup tick honest, but
  # if Claude is closing the turn cleanly they must persist the SHA
  # here so the NEXT normal tick doesn't re-report the same merges
  # and prompt duplicate packet dispatch. Both VOI-tagged and PR-only
  # merges qualify (saw_merge covers both).
  echo "    echo $cur_main_sha > $LAST_MAIN_MARKER"
fi
