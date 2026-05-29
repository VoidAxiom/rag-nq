import { describe, expect, it } from 'vitest'

import {
  MIN_STEP_MS,
  runPipelineAnimation,
  type BridgeState,
  type StepId,
  type StepState,
} from '@/lib/pipelineAnimation'

interface ScheduledTimer {
  fireAt: number
  handler: () => void
  cancelled: boolean
}

interface FakeClock {
  now(): number
  setTimeoutFn: typeof setTimeout
  clearTimeoutFn: typeof clearTimeout
  advanceTo(t: number): void
}

function makeFakeClock(): FakeClock {
  let now = 0
  const timers: ScheduledTimer[] = []
  const setTimeoutFn = ((handler: () => void, delay: number) => {
    const timer: ScheduledTimer = {
      fireAt: now + Math.max(0, delay),
      handler,
      cancelled: false,
    }
    timers.push(timer)
    return timer as unknown as ReturnType<typeof setTimeout>
  }) as typeof setTimeout
  const clearTimeoutFn = ((handle: unknown) => {
    const timer = handle as unknown as ScheduledTimer
    if (timer !== null && typeof timer === 'object') {
      timer.cancelled = true
    }
  }) as typeof clearTimeout

  function advanceTo(t: number): void {
    let safety = 100000
    for (;;) {
      const pending = timers.filter((tm) => !tm.cancelled && tm.fireAt <= t)
      if (pending.length === 0) break
      pending.sort((a, b) => a.fireAt - b.fireAt)
      const next = pending[0]
      timers.splice(timers.indexOf(next), 1)
      now = next.fireAt
      next.handler()
      if (--safety <= 0) {
        throw new Error('timer flush loop exceeded safety bound')
      }
    }
    now = t
  }

  return {
    now: () => now,
    setTimeoutFn,
    clearTimeoutFn,
    advanceTo,
  }
}

interface RecordedEvents {
  stepStates: Array<{ step: StepId; state: StepState }>
  stepMs: Array<{ step: StepId; ms: number }>
  bridges: Array<{ idx: 0 | 1; state: BridgeState }>
  totalMs: number[]
}

describe('runPipelineAnimation', () => {
  it('marks every step complete in order and snaps to real timings', async () => {
    const clock = makeFakeClock()
    const events: RecordedEvents = {
      stepStates: [],
      stepMs: [],
      bridges: [],
      totalMs: [],
    }
    const realPromise = Promise.resolve({
      retriever: 400,
      reranker: 300,
      generator: 100,
    })

    const done = runPipelineAnimation({
      realTimings: realPromise,
      now: () => clock.now(),
      setTimeoutFn: clock.setTimeoutFn,
      clearTimeoutFn: clock.clearTimeoutFn,
      callbacks: {
        onStepState(step, state) {
          events.stepStates.push({ step, state })
        },
        onStepMs(step, ms) {
          events.stepMs.push({ step, ms })
        },
        onBridgeState(idx, state) {
          events.bridges.push({ idx, state })
        },
        onTotalMs(ms) {
          events.totalMs.push(ms)
        },
      },
    })

    // Flush all timers and microtasks across the simulated span.
    for (let t = 0; t <= 2500; t += 50) {
      clock.advanceTo(t)
      // Let queued microtasks resolve (the scheduler chains Promises).
      await Promise.resolve()
      await Promise.resolve()
    }
    await done

    // Order: retriever running → complete, then reranker, then generator.
    const stateOrder = events.stepStates.map((e) => `${e.step}:${e.state}`)
    expect(stateOrder).toEqual([
      'retriever:running',
      'retriever:complete',
      'reranker:running',
      'reranker:complete',
      'generator:running',
      'generator:complete',
    ])
    // Bridges flowed then completed.
    expect(events.bridges.find((b) => b.idx === 0 && b.state === 'flowing')).toBeDefined()
    expect(events.bridges.find((b) => b.idx === 0 && b.state === 'complete')).toBeDefined()
    expect(events.bridges.find((b) => b.idx === 1 && b.state === 'flowing')).toBeDefined()
    expect(events.bridges.find((b) => b.idx === 1 && b.state === 'complete')).toBeDefined()
    // Final ms per step is the real ms (last onStepMs per step).
    const lastByStep = new Map<StepId, number>()
    for (const e of events.stepMs) lastByStep.set(e.step, e.ms)
    expect(lastByStep.get('retriever')).toBe(400)
    expect(lastByStep.get('reranker')).toBe(300)
    expect(lastByStep.get('generator')).toBe(100)
  })

  it('honors MIN_STEP_MS floor even when the real step is fast', async () => {
    const clock = makeFakeClock()
    const events: RecordedEvents = {
      stepStates: [],
      stepMs: [],
      bridges: [],
      totalMs: [],
    }
    // Fast real timings — sub-MIN_STEP_MS — must still take >=MIN_STEP_MS each.
    const realPromise = Promise.resolve({
      retriever: 5,
      reranker: 5,
      generator: 5,
    })

    const done = runPipelineAnimation({
      realTimings: realPromise,
      now: () => clock.now(),
      setTimeoutFn: clock.setTimeoutFn,
      clearTimeoutFn: clock.clearTimeoutFn,
      callbacks: {
        onStepState(step, state) {
          events.stepStates.push({ step, state })
        },
        onStepMs(step, ms) {
          events.stepMs.push({ step, ms })
        },
        onBridgeState(idx, state) {
          events.bridges.push({ idx, state })
        },
        onTotalMs(ms) {
          events.totalMs.push(ms)
        },
      },
    })

    // Animation needs at least 3 * MIN_STEP_MS = 750ms total.
    // Advance just past MIN_STEP_MS — only retriever should be complete.
    clock.advanceTo(MIN_STEP_MS - 1)
    await Promise.resolve()
    await Promise.resolve()
    expect(events.stepStates.filter((e) => e.state === 'complete')).toHaveLength(0)

    // Flush through.
    for (let t = MIN_STEP_MS; t <= MIN_STEP_MS * 4; t += 25) {
      clock.advanceTo(t)
      await Promise.resolve()
      await Promise.resolve()
    }
    await done
    const completes = events.stepStates.filter((e) => e.state === 'complete')
    expect(completes.map((e) => e.step)).toEqual([
      'retriever',
      'reranker',
      'generator',
    ])
    // Each step's final displayed ms is the real (5), not the animation duration.
    const lastByStep = new Map<StepId, number>()
    for (const e of events.stepMs) lastByStep.set(e.step, e.ms)
    expect(lastByStep.get('retriever')).toBe(5)
    expect(lastByStep.get('reranker')).toBe(5)
    expect(lastByStep.get('generator')).toBe(5)
  })

  it('rejects if real timings reject', async () => {
    const clock = makeFakeClock()
    const realPromise = Promise.reject(new Error('boom'))

    const done = runPipelineAnimation({
      realTimings: realPromise,
      now: () => clock.now(),
      setTimeoutFn: clock.setTimeoutFn,
      clearTimeoutFn: clock.clearTimeoutFn,
      callbacks: {
        onStepState: () => undefined,
        onStepMs: () => undefined,
        onBridgeState: () => undefined,
        onTotalMs: () => undefined,
      },
    })

    clock.advanceTo(500)
    await expect(done).rejects.toThrow(/boom/)
  })
})
