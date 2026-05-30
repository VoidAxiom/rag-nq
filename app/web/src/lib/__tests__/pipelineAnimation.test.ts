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
  stepStates: Array<{ at: number; step: StepId; state: StepState }>
  stepMs: Array<{ at: number; step: StepId; ms: number }>
  bridges: Array<{ at: number; idx: 0 | 1; state: BridgeState }>
  totalMs: Array<{ at: number; ms: number }>
}

function recordEvents(clock: FakeClock): { events: RecordedEvents; callbacks: Parameters<typeof runPipelineAnimation>[0]['callbacks'] } {
  const events: RecordedEvents = {
    stepStates: [],
    stepMs: [],
    bridges: [],
    totalMs: [],
  }
  const callbacks = {
    onStepState(step: StepId, state: StepState) {
      events.stepStates.push({ at: clock.now(), step, state })
    },
    onStepMs(step: StepId, ms: number) {
      events.stepMs.push({ at: clock.now(), step, ms })
    },
    onBridgeState(idx: 0 | 1, state: BridgeState) {
      events.bridges.push({ at: clock.now(), idx, state })
    },
    onTotalMs(ms: number) {
      events.totalMs.push({ at: clock.now(), ms })
    },
  }
  return { events, callbacks }
}

async function tick(): Promise<void> {
  // Drain microtasks (Promise chains) at least twice so the scheduler's
  // realPromise.then handlers run before the next clock advance.
  await Promise.resolve()
  await Promise.resolve()
}

describe('runPipelineAnimation (amended VOI-368 r2)', () => {
  // T1 — Total keeps ticking while no step shows a number.
  it('T1: Total ticks during the wait; no per-step onStepMs fires until response', async () => {
    const clock = makeFakeClock()
    const { events, callbacks } = recordEvents(clock)
    let resolveReal: (t: { retriever: number; reranker: number; generator: number }) => void = () => undefined
    const realPromise = new Promise<{
      retriever: number
      reranker: number
      generator: number
    }>((res) => {
      resolveReal = res
    })

    const done = runPipelineAnimation({
      realTimings: realPromise,
      now: () => clock.now(),
      setTimeoutFn: clock.setTimeoutFn,
      clearTimeoutFn: clock.clearTimeoutFn,
      callbacks,
    })

    // Walk to t=5000 in 100ms steps without resolving realPromise.
    for (let t = 0; t <= 5000; t += 100) {
      clock.advanceTo(t)
      await tick()
    }
    // Pre-resolve: NO onStepMs calls fired for any step.
    expect(events.stepMs).toHaveLength(0)
    // Total fired repeatedly, monotonically non-decreasing.
    expect(events.totalMs.length).toBeGreaterThan(20)
    for (let i = 1; i < events.totalMs.length; i++) {
      expect(events.totalMs[i].ms).toBeGreaterThanOrEqual(events.totalMs[i - 1].ms)
    }
    // Total grew past 1000 (1.00s boundary) and past 3000 (3.00s boundary).
    expect(events.totalMs.some((e) => e.ms >= 1000)).toBe(true)
    expect(events.totalMs.some((e) => e.ms >= 3000)).toBe(true)

    // Resolve at t=5000. Walk a bit further to let snap callbacks fire.
    resolveReal({ retriever: 100, reranker: 4700, generator: 50 })
    for (let t = 5000; t <= 5500; t += 50) {
      clock.advanceTo(t)
      await tick()
    }
    await done

    // Post-resolve: each step got exactly one onStepMs call carrying its real ms.
    const stepMsByStep = new Map<StepId, number[]>()
    for (const e of events.stepMs) {
      const arr = stepMsByStep.get(e.step) ?? []
      arr.push(e.ms)
      stepMsByStep.set(e.step, arr)
    }
    expect(stepMsByStep.get('retriever')).toEqual([100])
    expect(stepMsByStep.get('reranker')).toEqual([4700])
    expect(stepMsByStep.get('generator')).toEqual([50])

    // Total's FINAL value is the real sum.
    expect(events.totalMs[events.totalMs.length - 1].ms).toBe(4850)
  })

  // T2 — Steps stay running until response.
  it('T2: each step transitions pending→running pre-resolve; complete only post-resolve', async () => {
    const clock = makeFakeClock()
    const { events, callbacks } = recordEvents(clock)
    let resolveReal: (t: { retriever: number; reranker: number; generator: number }) => void = () => undefined
    const realPromise = new Promise<{
      retriever: number
      reranker: number
      generator: number
    }>((res) => {
      resolveReal = res
    })

    const done = runPipelineAnimation({
      realTimings: realPromise,
      now: () => clock.now(),
      setTimeoutFn: clock.setTimeoutFn,
      clearTimeoutFn: clock.clearTimeoutFn,
      callbacks,
    })

    // Pre-resolve: walk to t=5000. No `complete` transitions should fire.
    for (let t = 0; t <= 5000; t += 100) {
      clock.advanceTo(t)
      await tick()
    }
    const preResolveCompletes = events.stepStates.filter((e) => e.state === 'complete')
    expect(preResolveCompletes).toHaveLength(0)

    // Each step transitioned to `running` exactly once pre-resolve.
    const runningByStep = new Map<StepId, number>()
    for (const e of events.stepStates) {
      if (e.state === 'running') {
        runningByStep.set(e.step, (runningByStep.get(e.step) ?? 0) + 1)
      }
    }
    expect(runningByStep.get('retriever')).toBe(1)
    expect(runningByStep.get('reranker')).toBe(1)
    expect(runningByStep.get('generator')).toBe(1)

    // Resolve.
    resolveReal({ retriever: 100, reranker: 4700, generator: 50 })
    for (let t = 5000; t <= 5500; t += 50) {
      clock.advanceTo(t)
      await tick()
    }
    await done

    // Post-resolve: each step transitioned to `complete` exactly once.
    const completeByStep = new Map<StepId, number>()
    for (const e of events.stepStates) {
      if (e.state === 'complete') {
        completeByStep.set(e.step, (completeByStep.get(e.step) ?? 0) + 1)
      }
    }
    expect(completeByStep.get('retriever')).toBe(1)
    expect(completeByStep.get('reranker')).toBe(1)
    expect(completeByStep.get('generator')).toBe(1)
  })

  // T3 — Cascade transitions on schedule.
  it('T3: cascade transitions step→running at idx * MIN_STEP_MS', async () => {
    const clock = makeFakeClock()
    const { events, callbacks } = recordEvents(clock)
    let resolveReal: (t: { retriever: number; reranker: number; generator: number }) => void = () => undefined
    const realPromise = new Promise<{
      retriever: number
      reranker: number
      generator: number
    }>((res) => {
      resolveReal = res
    })

    runPipelineAnimation({
      realTimings: realPromise,
      now: () => clock.now(),
      setTimeoutFn: clock.setTimeoutFn,
      clearTimeoutFn: clock.clearTimeoutFn,
      callbacks,
    })

    for (let t = 0; t <= MIN_STEP_MS * 3; t += 25) {
      clock.advanceTo(t)
      await tick()
    }

    const runningAt = new Map<StepId, number>()
    for (const e of events.stepStates) {
      if (e.state === 'running' && !runningAt.has(e.step)) {
        runningAt.set(e.step, e.at)
      }
    }
    expect(runningAt.get('retriever')).toBe(0)
    expect(runningAt.get('reranker')).toBe(MIN_STEP_MS)
    expect(runningAt.get('generator')).toBe(MIN_STEP_MS * 2)

    // Resolve so the test's done promise can settle cleanly.
    resolveReal({ retriever: 1, reranker: 1, generator: 1 })
    await tick()
  })

  // T4 — Fast-API path snaps correctly when realPromise resolves before cascade completes.
  it('T4: fast-API path — all steps end in complete with real ms after resolve', async () => {
    const clock = makeFakeClock()
    const { events, callbacks } = recordEvents(clock)
    // Real promise that's already resolved.
    const realPromise = Promise.resolve({
      retriever: 30,
      reranker: 40,
      generator: 20,
    })

    const done = runPipelineAnimation({
      realTimings: realPromise,
      now: () => clock.now(),
      setTimeoutFn: clock.setTimeoutFn,
      clearTimeoutFn: clock.clearTimeoutFn,
      callbacks,
    })

    // The realPromise.then handler runs on the next microtask, well before
    // the t=MIN_STEP_MS cascade tick. Walk a bit to drain.
    for (let t = 0; t <= 50; t += 10) {
      clock.advanceTo(t)
      await tick()
    }
    await done

    // Final state per step: complete.
    const finalState = new Map<StepId, StepState>()
    for (const e of events.stepStates) finalState.set(e.step, e.state)
    expect(finalState.get('retriever')).toBe('complete')
    expect(finalState.get('reranker')).toBe('complete')
    expect(finalState.get('generator')).toBe('complete')

    // Final ms per step: real value.
    const lastMs = new Map<StepId, number>()
    for (const e of events.stepMs) lastMs.set(e.step, e.ms)
    expect(lastMs.get('retriever')).toBe(30)
    expect(lastMs.get('reranker')).toBe(40)
    expect(lastMs.get('generator')).toBe(20)

    // Total snapped to real sum.
    expect(events.totalMs[events.totalMs.length - 1].ms).toBe(90)
  })

  // T5 — Error path halts everything.
  it('T5: rejection halts onTotalMs / onStepMs / onStepState callbacks', async () => {
    const clock = makeFakeClock()
    const { events, callbacks } = recordEvents(clock)
    let rejectReal: (err: Error) => void = () => undefined
    const realPromise = new Promise<{
      retriever: number
      reranker: number
      generator: number
    }>((_, rej) => {
      rejectReal = rej
    })

    const done = runPipelineAnimation({
      realTimings: realPromise,
      now: () => clock.now(),
      setTimeoutFn: clock.setTimeoutFn,
      clearTimeoutFn: clock.clearTimeoutFn,
      callbacks,
    })

    // Walk to t=2000, then reject.
    for (let t = 0; t <= 2000; t += 100) {
      clock.advanceTo(t)
      await tick()
    }
    rejectReal(new Error('boom'))
    await expect(done).rejects.toThrow(/boom/)

    const countsAtRejection = {
      total: events.totalMs.length,
      stepMs: events.stepMs.length,
      stepStates: events.stepStates.length,
      bridges: events.bridges.length,
    }
    // Walk further; no new callbacks should fire.
    for (let t = 2000; t <= 4000; t += 100) {
      clock.advanceTo(t)
      await tick()
    }
    expect(events.totalMs.length).toBe(countsAtRejection.total)
    expect(events.stepMs.length).toBe(countsAtRejection.stepMs)
    expect(events.stepStates.length).toBe(countsAtRejection.stepStates)
    expect(events.bridges.length).toBe(countsAtRejection.bridges)
  })
})
