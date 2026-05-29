import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AnswerPanel } from '@/components/ask/AnswerPanel'
import type { GroundedAnswer } from '@/lib/types'

const GROUNDED: GroundedAnswer = {
  answer: 'Marie Curie discovered radium.',
  citations: [{ point_id: 'p-1' }, { point_id: 'long-passage-id-xyz' }],
  abstained: false,
  supporting_point_ids: ['p-1'],
}

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  cleanup()
})

describe('AnswerPanel', () => {
  it('is hidden until reveal is true', () => {
    render(<AnswerPanel grounded={GROUNDED} reveal={false} />)
    const panel = screen.getByLabelText('Grounded answer')
    expect(panel.className).not.toContain('answer--visible')
    expect(screen.getByTestId('answer-text').textContent).toBe('')
  })

  it('types out the answer when reveal flips true', () => {
    const { rerender } = render(
      <AnswerPanel grounded={GROUNDED} reveal={false} />,
    )
    rerender(<AnswerPanel grounded={GROUNDED} reveal={true} />)
    // Advance enough for the full string to type.
    act(() => {
      vi.advanceTimersByTime(GROUNDED.answer.length * 30)
    })
    expect(screen.getByTestId('answer-text').textContent).toContain(
      GROUNDED.answer,
    )
    // Citations appear once typing completes.
    expect(screen.getByLabelText('Citations')).toBeInTheDocument()
  })

  it('renders abstained state', () => {
    const abstained: GroundedAnswer = {
      ...GROUNDED,
      abstained: true,
      abstention_reason: 'Insufficient context',
    }
    render(<AnswerPanel grounded={abstained} reveal={true} />)
    expect(screen.getByText('Abstained')).toBeInTheDocument()
    expect(screen.getByText('Insufficient context')).toBeInTheDocument()
  })
})
