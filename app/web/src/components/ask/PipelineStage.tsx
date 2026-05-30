import type { ReactNode } from 'react'

import type { StepState } from '@/lib/pipelineAnimation'

interface PipelineStageProps {
  name: string
  accent: 1 | 2 | 3
  state: StepState
  /** Milliseconds to display. Ignored while state==='running' (the formatter
   * intentionally suppresses any numeric attribution before the real timing
   * lands, to avoid misattributing wall-clock time to the wrong stage). */
  ms: number | null
  /** Knobs row inside the step body. */
  children?: ReactNode
}

export function PipelineStage({ name, accent, state, ms, children }: PipelineStageProps) {
  const classNames = ['step', `step--${state}`]
  return (
    <section
      className={classNames.join(' ')}
      data-accent={String(accent)}
      aria-label={`${name} step`}
    >
      <header className="step__head">
        <span>
          <span className="step__dot" aria-hidden="true" />
          <span className="step__name">{name}</span>
        </span>
        <span className="step__time" data-testid={`step-time-${name.toLowerCase()}`}>
          {formatMs(ms, state)}
        </span>
      </header>
      {children !== undefined && children !== null ? (
        <div className="step__body">{children}</div>
      ) : null}
    </section>
  )
}

function formatMs(ms: number | null, state: StepState): string {
  // Pending: nothing to show.
  if (state === 'pending') return '—'
  // Running: the cascade is animating but no real ms is known yet. Show a
  // neutral indicator with NO number — attributing wall-clock to a specific
  // step before the API responds is a lie (cf. VOI-368 user feedback).
  if (state === 'running') return '…'
  // Complete: snap to the real ms.
  if (ms === null) return '0 ms'
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`
  return `${Math.round(ms)} ms`
}
