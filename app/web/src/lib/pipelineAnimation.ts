/*
 * Scripted pipeline animation scheduler.
 *
 * The animation runs in parallel with the /api/query fetch. It always shows
 * three steps in sequence (retriever → reranker → generator) with a minimum
 * visible duration per step. When real timings arrive (callback below or as
 * the resolved promise's source-of-truth), the scheduler clamps the per-step
 * pacing to the real wall-clock floor; the DISPLAYED ms is always the real
 * ms (or the live wall-clock if the API hasn't returned yet).
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
   * scheduler uses these to clamp per-step pacing and to display the canonical
   * ms reading once known.
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

interface StepResolution {
  step: StepId
  realMs: number
}

const STEPS: readonly StepId[] = ['retriever', 'reranker', 'generator']

/**
 * Runs the scripted pipeline animation. Returns a promise that resolves once
 * every step has reached `complete`. If `realTimings` rejects, the running
 * step is left as-is (caller decides how to surface the error) and the
 * returned promise rejects.
 */
export function runPipelineAnimation(opts: SchedulerOptions): Promise<void> {
  const now = opts.now ?? defaultNow
  const setTimer = opts.setTimeoutFn ?? defaultSetTimeout
  const clearTimer = opts.clearTimeoutFn ?? defaultClearTimeout

  return new Promise<void>((resolve, reject) => {
    let cancelled = false
    let totalTickHandle: ReturnType<typeof defaultSetTimeout> | null = null
    let stepTickHandle: ReturnType<typeof defaultSetTimeout> | null = null
    let nextStepHandle: ReturnType<typeof defaultSetTimeout> | null = null
    const start = now()

    let timings: StepTimings | null = null
    const realPromise = opts.realTimings.then(
      (resolved) => {
        timings = resolved
        return resolved
      },
      (err) => {
        cancelled = true
        cleanup()
        reject(err)
        throw err
      },
    )

    function cleanup() {
      if (totalTickHandle !== null) clearTimer(totalTickHandle)
      if (stepTickHandle !== null) clearTimer(stepTickHandle)
      if (nextStepHandle !== null) clearTimer(nextStepHandle)
      totalTickHandle = null
      stepTickHandle = null
      nextStepHandle = null
    }

    function tickTotal() {
      if (cancelled) return
      opts.callbacks.onTotalMs(Math.round(now() - start))
      totalTickHandle = setTimer(tickTotal, 33)
    }
    totalTickHandle = setTimer(tickTotal, 0)

    function startStep(idx: number) {
      if (cancelled) return
      if (idx >= STEPS.length) {
        cleanup()
        // Final snap: render the real total if known.
        if (timings !== null) {
          opts.callbacks.onTotalMs(
            Math.round(timings.retriever + timings.reranker + timings.generator),
          )
        }
        resolve()
        return
      }
      const step = STEPS[idx]
      opts.callbacks.onStepState(step, 'running')

      // Outgoing bridge (the one between this step and the next) flows.
      if (idx < STEPS.length - 1) {
        opts.callbacks.onBridgeState(
          idx === 0 ? 0 : 1,
          'flowing',
        )
      }

      const stepStart = now()
      function liveTick() {
        if (cancelled) return
        const real = timings === null ? null : timings[step]
        const wall = now() - stepStart
        // While real ms unknown OR running step hasn't yet reached its real
        // duration, show the live wall-clock count. Once real is known and
        // the wall has reached/passed it, freeze on real.
        if (real !== null && wall >= real) {
          opts.callbacks.onStepMs(step, Math.round(real))
        } else {
          opts.callbacks.onStepMs(step, Math.round(wall))
        }
        stepTickHandle = setTimer(liveTick, 33)
      }
      stepTickHandle = setTimer(liveTick, 0)

      // Wait for both: (a) the real timing to be known, and (b) the
      // animated minimum duration (max(real, MIN_STEP_MS)) to elapse.
      resolveStepAfterMinimum(step).then((resolution) => {
        if (cancelled) return
        if (stepTickHandle !== null) clearTimer(stepTickHandle)
        stepTickHandle = null
        opts.callbacks.onStepMs(step, Math.round(resolution.realMs))
        opts.callbacks.onStepState(step, 'complete')
        if (idx < STEPS.length - 1) {
          opts.callbacks.onBridgeState(idx === 0 ? 0 : 1, 'complete')
        }
        nextStepHandle = setTimer(() => startStep(idx + 1), 0)
      }, (err) => {
        if (!cancelled) {
          cancelled = true
          cleanup()
          reject(err)
        }
      })

      function resolveStepAfterMinimum(currentStep: StepId): Promise<StepResolution> {
        return realPromise.then((resolved) => {
          const realMs = resolved[currentStep]
          const elapsed = now() - stepStart
          const remaining = Math.max(0, realMs - elapsed, MIN_STEP_MS - elapsed)
          if (remaining === 0) {
            return { step: currentStep, realMs }
          }
          return new Promise<StepResolution>((res) => {
            const handle = setTimer(() => {
              res({ step: currentStep, realMs })
            }, remaining)
            // capture so cleanup() can clear it if cancelled mid-wait
            stepTickHandle = handle
          })
        })
      }
    }

    startStep(0)
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
