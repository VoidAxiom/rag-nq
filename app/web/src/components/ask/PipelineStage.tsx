import type { ReactNode } from 'react'

import type { StepState } from '@/lib/pipelineAnimation'

interface PipelineStageProps {
  name: string
  accent: 1 | 2 | 3
  state: StepState
  /** Milliseconds to display. null → show em-dash. */
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
  if (ms === null) {
    return state === 'pending' ? '—' : '0 ms'
  }
  const suffix = state === 'running' ? ' ms…' : ' ms'
  return `${Math.round(ms)}${suffix}`
}
