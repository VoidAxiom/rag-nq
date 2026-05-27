#!/usr/bin/env node
// PreToolUse guard on the `ScheduleWakeup` tool — parallelization gate.
//
// Forces a queue scan before allowing Claude to idle. Three times in the
// 2026-05-26 session, Claude ended a turn with ScheduleWakeup while Todo
// packets sat in the Phase queue with their deps content-available. Soft
// policies (memory rules, CLAUDE.md mandates, self-discipline) all failed.
// This hook is harness-enforced.
//
// Mechanics:
//   - Runs `scripts/queue-scan.sh`.
//   - Exit 0 → no dispatchable items → allow ScheduleWakeup.
//   - Exit 1 → dispatchable items exist → deny ScheduleWakeup with the
//     list. Claude must dispatch (or explicitly document why all
//     dispatchable items cannot be addressed) before retrying.
//   - Any other error / parse failure → allow (fail-open). The
//     write-scope-guard hook follows the same fail-open posture.
//
// Bypass: if you're SURE everything dispatchable is genuinely blocked
// for a non-stacked-PR reason and need to schedule a wakeup anyway,
// set QUEUE_SCAN_BYPASS=1 in the env for the ScheduleWakeup call. The
// bypass is logged to stderr so the action is traceable. Default no.
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import fs from 'node:fs'

let raw = ''
process.stdin.setEncoding('utf8')
process.stdin.on('data', (d) => (raw += d))
process.stdin.on('end', () => {
  const allow = () => process.exit(0)
  try {
    const j = JSON.parse(raw || '{}')
    if (j.tool_name !== 'ScheduleWakeup') return allow()

    if (process.env.QUEUE_SCAN_BYPASS === '1') {
      process.stderr.write('schedule-wakeup-guard: QUEUE_SCAN_BYPASS=1 — allowing ScheduleWakeup despite gate\n')
      return allow()
    }

    const projectDir = process.env.CLAUDE_PROJECT_DIR || process.cwd()
    const scanPath = path.join(projectDir, 'scripts/queue-scan.sh')

    if (!fs.existsSync(scanPath)) {
      // Gate not yet installed in this checkout — allow.
      return allow()
    }

    let scanOutput = ''
    let scanExit = 0
    try {
      scanOutput = execFileSync('bash', [scanPath], {
        encoding: 'utf8',
        cwd: projectDir,
        stdio: ['ignore', 'pipe', 'pipe'],
        timeout: 15_000,
      }).trim()
    } catch (e) {
      scanExit = typeof e.status === 'number' ? e.status : 1
      const out = (e.stdout && e.stdout.toString()) || ''
      const err = (e.stderr && e.stderr.toString()) || ''
      scanOutput = `${out}\n${err}`.trim()
    }

    if (scanExit === 1 && scanOutput) {
      const reason =
        `Parallelization gate — ScheduleWakeup BLOCKED.\n\n` +
        `${scanOutput}\n\n` +
        `Per parallel-by-default doctrine, dispatch each listed packet before idling:\n` +
        `  - Claude-direct (e.g. *.md, scripts/, hooks/, architecture/, .understand-anything/):\n` +
        `      start it inline on a fresh branch (or stacked off the dep's branch if not yet merged).\n` +
        `  - Impl-owned (production code / config / tests):\n` +
        `      bash scripts/worktree-new.sh <branch> <name> <base>\n` +
        `      then write .codex-runs/<packet-id>/{spec.md,scope.txt}\n` +
        `      then dispatch via the Task tool (subagent_type=implementer) in background.\n\n` +
        `If a listed packet genuinely cannot be dispatched (e.g. its dep is broken or its scope is\n` +
        `under spec-author review), say so plainly in user-facing text BEFORE retrying ScheduleWakeup,\n` +
        `OR set QUEUE_SCAN_BYPASS=1 for the call. Do NOT retry the same ScheduleWakeup without doing one\n` +
        `of those two things — that's the failure mode this gate exists to prevent.`
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: 'PreToolUse',
            permissionDecision: 'deny',
            permissionDecisionReason: reason,
          },
        }),
      )
      return process.exit(0)
    }

    if (scanExit !== 0 && scanExit !== 1) {
      // Configuration error in queue-scan.sh — log + fail-open.
      process.stderr.write(`schedule-wakeup-guard: queue-scan exited ${scanExit}; allowing (fail-open)\n${scanOutput}\n`)
    }
    return allow()
  } catch {
    return allow()
  }
})
