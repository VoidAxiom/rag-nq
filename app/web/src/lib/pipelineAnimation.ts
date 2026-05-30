/*
 * Scripted pipeline animation scheduler.
 *
 * The animation runs in parallel with the /api/query fetch. It plays a
 * scripted cascade — retriever → reranker → generator — at MIN_STEP_MS
 * intervals to show "the pipeline is moving", but per-step ms displays are
 * INTENTIONALLY suppressed while a step is `running`. The UI shows a neutral
 * indicator (`…`) for any running step; no wall-clock number is attributed
 * to a step before its real timing is known, because such attribution lies
 * (e.g. the generator slot ticking up while the work is actually in the
 * reranker, then snapping to "0 s" on resolve while reranker jumps to ~30s).
 *
 * The only ticking number on the page during the wait is the Total card,
 * which ticks from t=0 until realPromise resolves (or rejects).
 *
 * On resolve: each step snaps to its real ms (via onStepMs) and transitions
 * to `complete` (via onStepState), in cascade order, with bridges completing
 * in sequence. On reject: every timer is torn down and the returned promise
 * rejects; no further callbacks fire.
 */

export const MIN_STEP_MS = 250

export type StepId = 'retriever' | 'reranker' | 'generator'

export type StepState = 'pending' | 'running' | 'complete'
export type BridgeState = 'idle' | 'flowing' | 'complete'

export interface StepTimings {
  retriever: number
  reranker: number
  generator: number
}

export interface PipelineAnimationCallbacks {
  onStepState(step: StepId, state: StepState): void
  onStepMs(step: StepId, ms: number): void
  onBridgeState(bridgeIndex: 0 | 1, state: BridgeState): void
  onTotalMs(ms: number): void
}

interface SchedulerOptions {
  /**
   * Resolve when the real API timings arrive (or reject on error). The
   * scheduler waits for this before transitioning any step to `complete` and
   * before emitting per-step ms — both events are post-snap only.
   */
  realTimings: Promise<StepTimings>
  callbacks: PipelineAnimationCallbacks
  /** Override for tests. */
  now?: () => number
  /** Override for tests. */
  setTimeoutFn?: typeof setTimeout
  /** Override for tests. */
  clearTimeoutFn?: typeof clearTimeout
}

const STEPS: readonly StepId[] = ['retriever', 'reranker', 'generator']

/**
 * Runs the scripted pipeline animation. Returns a promise that resolves once
 * every step has reached `complete` (which only happens after realTimings
 * resolves). If `realTimings` rejects, all timers are cleared and the
 * returned promise rejects.
 */
export function runPipelineAnimation(opts: SchedulerOptions): Promise<void> {
  const now = opts.now ?? defaultNow
  const setTimer = opts.setTimeoutFn ?? defaultSetTimeout
  const clearTimer = opts.clearTimeoutFn ?? defaultClearTimeout

  return new Promise<void>((resolve, reject) => {
    let cancelled = false
    let totalTickHandle: ReturnType<typeof defaultSetTimeout> | null = null
    const cascadeHandles: Array<ReturnType<typeof defaultSetTimeout>> = []
    const start = now()

    // Track which steps have entered `running` from the cascade. On resolve we
    // walk this list to snap + complete; any step the cascade hadn't reached
    // gets fast-forwarded through pending → running → complete in the snap.
    const runningEntered = new Set<StepId>()

    function clearCascade(): void {
      for (const h of cascadeHandles) clearTimer(h)
      cascadeHandles.length = 0
    }

    function clearAll(): void {
      if (totalTickHandle !== null) {
        clearTimer(totalTickHandle)
        totalTickHandle = null
      }
      clearCascade()
    }

    function tickTotal(): void {
      if (cancelled) return
      opts.callbacks.onTotalMs(Math.round(now() - start))
      totalTickHandle = setTimer(tickTotal, 33)
    }
    totalTickHandle = setTimer(tickTotal, 0)

    // Schedule the cascade transitions: each step enters `running` at
    // idx * MIN_STEP_MS; the outgoing bridge for that step flows immediately.
    // No step transitions to `complete` here — that only happens in the
    // post-resolve snap below.
    function scheduleCascade(idx: number): void {
      const fireAt = idx * MIN_STEP_MS
      const h = setTimer(() => {
        if (cancelled) return
        const step = STEPS[idx]
        runningEntered.add(step)
        opts.callbacks.onStepState(step, 'running')
        if (idx < STEPS.length - 1) {
          opts.callbacks.onBridgeState(idx === 0 ? 0 : 1, 'flowing')
        }
      }, fireAt)
      cascadeHandles.push(h)
    }
    for (let i = 0; i < STEPS.length; i++) scheduleCascade(i)

    opts.realTimings.then(
      (resolved) => {
        if (cancelled) return
        // Stop the wall-clock total ticker BEFORE the real-sum snap, so a
        // queued tick can't fire after the snap and overwrite the Total card
        // with the animation's wall-clock value.
        if (totalTickHandle !== null) {
          clearTimer(totalTickHandle)
          totalTickHandle = null
        }
        // The cascade may not have reached every step yet (fast-API path).
        // Cancel any pending cascade transitions; we'll synthesize the
        // remaining `running` transitions inline below so every step is in
        // `running` before it snaps to `complete`.
        clearCascade()

        opts.callbacks.onTotalMs(
          Math.round(resolved.retriever + resolved.reranker + resolved.generator),
        )

        // Snap each step to its real ms and transition to complete in cascade
        // order. Bridges complete between steps. If a step never reached
        // `running` (cascade was still pending), transition it through
        // running first so the state machine stays consistent for consumers.
        for (let i = 0; i < STEPS.length; i++) {
          const step = STEPS[i]
          if (!runningEntered.has(step)) {
            runningEntered.add(step)
            opts.callbacks.onStepState(step, 'running')
            if (i < STEPS.length - 1) {
              opts.callbacks.onBridgeState(i === 0 ? 0 : 1, 'flowing')
            }
          }
          opts.callbacks.onStepMs(step, Math.round(resolved[step]))
          opts.callbacks.onStepState(step, 'complete')
          if (i < STEPS.length - 1) {
            opts.callbacks.onBridgeState(i === 0 ? 0 : 1, 'complete')
          }
        }
        resolve()
      },
      (err) => {
        if (cancelled) return
        cancelled = true
        clearAll()
        reject(err)
      },
    )
  })
}

function defaultNow(): number {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now()
  }
  return Date.now()
}

function defaultSetTimeout(handler: () => void, ms: number): ReturnType<typeof setTimeout> {
  return setTimeout(handler, ms)
}

function defaultClearTimeout(handle: ReturnType<typeof setTimeout>): void {
  clearTimeout(handle)
}
