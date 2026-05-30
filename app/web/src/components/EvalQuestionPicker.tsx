import { useQuery } from '@tanstack/react-query'
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
} from 'react'

import { fetchEvalQuestions } from '@/lib/api'
import type { EvalQuestion } from '@/lib/types'

interface EvalQuestionPickerProps {
  benchmark: string
  value: string | null
  onPickQuestion: (q: EvalQuestion | null) => void
  onFreeText: (text: string) => void
}

export function EvalQuestionPicker({
  benchmark,
  value,
  onPickQuestion,
  onFreeText,
}: EvalQuestionPickerProps) {
  const [freeText, setFreeText] = useState('')
  const shouldPickFirstWhenReadyRef = useRef(false)
  const mode = value === null ? 'free' : 'curated'
  const { data, error, isError, isLoading } = useQuery({
    queryKey: ['evalQuestions', benchmark],
    queryFn: () => fetchEvalQuestions(benchmark),
    enabled: benchmark.trim() !== '',
  })
  const questions = useMemo(() => data?.questions ?? [], [data?.questions])
  const selectedQuestion = questions.find((question) => question.query_id === value)

  useEffect(() => {
    if (value !== null && selectedQuestion !== undefined) {
      onPickQuestion(selectedQuestion)
    }
  }, [onPickQuestion, selectedQuestion, value])

  useEffect(() => {
    if (!shouldPickFirstWhenReadyRef.current) return
    const firstQuestion = questions[0]
    if (firstQuestion !== undefined) {
      onPickQuestion(firstQuestion)
      shouldPickFirstWhenReadyRef.current = false
    }
  }, [onPickQuestion, questions])

  function handleModeChange(event: ChangeEvent<HTMLInputElement>): void {
    const nextMode = event.target.value
    if (nextMode === 'free') {
      shouldPickFirstWhenReadyRef.current = false
      onPickQuestion(null)
      return
    }
    const firstQuestion = questions[0]
    if (firstQuestion !== undefined) {
      shouldPickFirstWhenReadyRef.current = false
      onPickQuestion(firstQuestion)
      return
    }
    shouldPickFirstWhenReadyRef.current = true
  }

  function handleQuestionChange(event: ChangeEvent<HTMLSelectElement>): void {
    const question = questions.find((q) => q.query_id === event.target.value)
    if (question !== undefined) {
      onPickQuestion(question)
    }
  }

  function handleFreeTextChange(event: ChangeEvent<HTMLInputElement>): void {
    const nextText = event.target.value
    setFreeText(nextText)
    onFreeText(nextText)
  }

  const errorMessage =
    isError && error instanceof Error
      ? error.message
      : 'Unable to load curated eval questions.'

  return (
    <div className="knob-group" role="group" aria-label="Question input mode">
      <div className="knob-row" role="radiogroup" aria-label="Question input mode">
        <label className="knob-label" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <input
            type="radio"
            name="ask-mode"
            value="curated"
            checked={mode === 'curated'}
            onChange={handleModeChange}
            id="ask-mode-curated"
          />
          <span>Curated eval question</span>
        </label>
        <label className="knob-label" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
          <input
            type="radio"
            name="ask-mode"
            value="free"
            checked={mode === 'free'}
            onChange={handleModeChange}
            id="ask-mode-free"
          />
          <span>Free text</span>
        </label>
      </div>

      {mode === 'free' ? (
        <label className="knob-row">
          <span className="knob-label">Question</span>
          <input
            id="ask-free-text"
            className="knob-control"
            type="text"
            placeholder="Ask anything..."
            value={freeText}
            onChange={handleFreeTextChange}
            aria-label="Question"
          />
        </label>
      ) : (
        <label className="knob-row">
          <span className="knob-label">Eval question</span>
          {isLoading ? (
            <span aria-busy="true" role="status">Loading…</span>
          ) : (
            <select
              className="knob-control"
              aria-label="Eval question"
              value={value ?? ''}
              onChange={handleQuestionChange}
            >
              <option value="" disabled>
                Select an eval question
              </option>
              {questions.map((question) => (
                <option value={question.query_id} key={question.query_id}>
                  {formatQuestionLabel(question)}
                </option>
              ))}
            </select>
          )}
        </label>
      )}
      {isError ? (
        <p role="alert" className="theme-error">
          {errorMessage}
        </p>
      ) : null}
    </div>
  )
}

function formatQuestionLabel(question: EvalQuestion): string {
  const trimmedQuery = question.query.trim()
  const label =
    trimmedQuery.length > 96 ? `${trimmedQuery.slice(0, 95).trimEnd()}...` : trimmedQuery
  return `${label} (${question.query_id})`
}
