import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { PipelineStage } from '@/components/ask/PipelineStage'
import type { StepState } from '@/lib/pipelineAnimation'

afterEach(cleanup)

describe('PipelineStage (amended VOI-368 r2)', () => {
  it('renders pending state with em-dash time', () => {
    render(
      <PipelineStage name="Retriever" accent={1} state="pending" ms={null} />,
    )
    expect(screen.getByTestId('step-time-retriever').textContent).toBe('—')
    const section = screen.getByLabelText('Retriever step')
    expect(section.className).toContain('step--pending')
  })

  it('renders running state with no number (neutral … indicator)', () => {
    // Even if ms is non-null, the formatter MUST NOT show it during running —
    // attributing wall-clock to a step before the real timing lands lies
    // about which stage owns the elapsed time.
    render(
      <PipelineStage name="Reranker" accent={2} state="running" ms={12345} />,
    )
    expect(screen.getByTestId('step-time-reranker').textContent).toBe('…')
    const section = screen.getByLabelText('Reranker step')
    expect(section.className).toContain('step--running')
  })

  it('renders complete state with the real ms in ms format under 1000', () => {
    render(
      <PipelineStage name="Generator" accent={3} state="complete" ms={42} />,
    )
    expect(screen.getByTestId('step-time-generator').textContent).toBe('42 ms')
    const section = screen.getByLabelText('Generator step')
    expect(section.className).toContain('step--complete')
  })

  it('renders complete state with seconds format at >= 1000 ms', () => {
    render(
      <PipelineStage name="Reranker" accent={2} state="complete" ms={17730} />,
    )
    expect(screen.getByTestId('step-time-reranker').textContent).toBe('17.73 s')
  })

  it('renders the children inside the step body', () => {
    render(
      <PipelineStage name="Retriever" accent={1} state="pending" ms={null}>
        <span>knob-child</span>
      </PipelineStage>,
    )
    expect(screen.getByText('knob-child')).toBeInTheDocument()
  })
})

describe('PipelineStage formatter — T6 boundary table (rendered)', () => {
  // Distinct step name per render so testids don't collide within the table.
  const STAGE_NAMES: Record<number, string> = {
    0: 'Retriever',
    1: 'Reranker',
    2: 'Generator',
  }
  const cases: Array<[number | null, StepState, string]> = [
    // pending → em-dash regardless of ms.
    [null, 'pending', '—'],
    [0, 'pending', '—'],
    [9999, 'pending', '—'],
    // running → neutral … regardless of ms (no number, no suffix).
    [null, 'running', '…'],
    [0, 'running', '…'],
    [123, 'running', '…'],
    [1000, 'running', '…'],
    [17730, 'running', '…'],
    // complete fallback (null) → '0 ms'.
    [null, 'complete', '0 ms'],
    // complete + finite values: ms format below 1000, s format at/above.
    [0, 'complete', '0 ms'],
    [999, 'complete', '999 ms'],
    [1000, 'complete', '1.00 s'],
    [17730, 'complete', '17.73 s'],
  ]

  cases.forEach(([ms, state, expected], idx) => {
    it(`renders (${ms === null ? 'null' : ms}, '${state}') as '${expected}'`, () => {
      // Stable, deterministic per-case name; cleanup() after each render keeps
      // testids unique even though all cases run against the same DOM.
      const name = STAGE_NAMES[idx % 3]
      render(
        <PipelineStage
          name={name}
          accent={1}
          state={state}
          ms={ms}
        />,
      )
      const cell = screen.getByTestId(`step-time-${name.toLowerCase()}`)
      expect(cell.textContent).toBe(expected)
      cleanup()
    })
  })
})
