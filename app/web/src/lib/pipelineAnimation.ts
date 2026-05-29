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

      // Advance after the minimum duration even when real timings haven't
      // arrived yet — the API is one-shot, so under slow generators the
      // realPromise can resolve well after the animation should already be
      // showing reranker/generator. We use MIN_STEP_MS as the floor when real
      // ms is unknown, then clamp to max(real, MIN_STEP_MS) once known. The
      // final displayed ms still snaps to real (or the live wall-clock when
      // the request errors before resolving).
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
        // Wait for whichever of (MIN_STEP_MS elapsed, real timings arrived)
        // happens first. If real arrives first we may still need to wait
        // until max(real, MIN_STEP_MS) elapses. If MIN_STEP_MS fires first,
        // we advance with a placeholder real (the live wall-clock) and let
        // realPromise's later resolution be captured by other steps that
        // haven't started yet — the final pipeline reveal still anchors on
        // real total via the resolve path in startStep.
        return new Promise<StepResolution>((res, rej) => {
          let settled = false
          const minHandle = setTimer(() => {
            if (settled || cancelled) return
            if (timings !== null) {
              const realMs = timings[currentStep]
              const elapsed = now() - stepStart
              const remaining = Math.max(0, realMs - elapsed)
              if (remaining === 0) {
                settled = true
                res({ step: currentStep, realMs })
                return
              }
              const waitHandle = setTimer(() => {
                if (settled || cancelled) return
                settled = true
                res({ step: currentStep, realMs })
              }, remaining)
              stepTickHandle = waitHandle
              return
            }
            // Real ms still unknown; advance with the live wall-clock so the
            // animation keeps moving. realPromise will continue resolving in
            // the background; subsequent steps will pick up the real values.
            settled = true
            res({ step: currentStep, realMs: now() - stepStart })
          }, Math.max(0, MIN_STEP_MS))
          stepTickHandle = minHandle

          realPromise.then(
            (resolved) => {
              if (settled || cancelled) return
              const realMs = resolved[currentStep]
              const elapsed = now() - stepStart
              const remaining = Math.max(0, realMs - elapsed, MIN_STEP_MS - elapsed)
              if (remaining === 0) {
                settled = true
                clearTimer(minHandle)
                res({ step: currentStep, realMs })
                return
              }
              clearTimer(minHandle)
              const waitHandle = setTimer(() => {
                if (settled || cancelled) return
                settled = true
                res({ step: currentStep, realMs })
              }, remaining)
              stepTickHandle = waitHandle
            },
            (err) => {
              if (settled || cancelled) return
              settled = true
              clearTimer(minHandle)
              rej(err)
            },
          )
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
