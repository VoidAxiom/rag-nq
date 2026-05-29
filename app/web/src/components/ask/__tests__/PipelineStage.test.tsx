import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { PipelineStage } from '@/components/ask/PipelineStage'

afterEach(cleanup)

describe('PipelineStage', () => {
  it('renders pending state with em-dash time', () => {
    render(
      <PipelineStage name="Retriever" accent={1} state="pending" ms={null} />,
    )
    expect(screen.getByTestId('step-time-retriever').textContent).toBe('—')
    const section = screen.getByLabelText('Retriever step')
    expect(section.className).toContain('step--pending')
  })

  it('renders running state with ms… suffix and the live ms', () => {
    render(
      <PipelineStage name="Reranker" accent={2} state="running" ms={123} />,
    )
    expect(screen.getByTestId('step-time-reranker').textContent).toBe('123 ms…')
    const section = screen.getByLabelText('Reranker step')
    expect(section.className).toContain('step--running')
  })

  it('renders complete state with the real ms', () => {
    render(
      <PipelineStage name="Generator" accent={3} state="complete" ms={42} />,
    )
    expect(screen.getByTestId('step-time-generator').textContent).toBe('42 ms')
    const section = screen.getByLabelText('Generator step')
    expect(section.className).toContain('step--complete')
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
