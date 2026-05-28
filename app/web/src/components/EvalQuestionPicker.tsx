import { useQuery } from '@tanstack/react-query'
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'

import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
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
    if (!shouldPickFirstWhenReadyRef.current) {
      return
    }

    const firstQuestion = questions[0]
    if (firstQuestion !== undefined) {
      onPickQuestion(firstQuestion)
      shouldPickFirstWhenReadyRef.current = false
    }
  }, [onPickQuestion, questions])

  function handleModeChange(nextMode: string): void {
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

  function handleQuestionChange(queryId: string): void {
    const question = questions.find((candidate) => candidate.query_id === queryId)

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
    <div className="grid gap-4">
      <RadioGroup
        value={mode}
        onValueChange={handleModeChange}
        className="grid gap-3 sm:grid-cols-2"
        aria-label="Question input mode"
      >
        <div className="flex items-center gap-2">
          <RadioGroupItem value="curated" id="ask-mode-curated" />
          <Label htmlFor="ask-mode-curated">Curated eval question</Label>
        </div>
        <div className="flex items-center gap-2">
          <RadioGroupItem value="free" id="ask-mode-free" />
          <Label htmlFor="ask-mode-free">Free text</Label>
        </div>
      </RadioGroup>

      {mode === 'free' ? (
        <div className="grid gap-2">
          <Label htmlFor="ask-free-text">Question</Label>
          <Input
            id="ask-free-text"
            placeholder="Ask anything..."
            value={freeText}
            onChange={handleFreeTextChange}
          />
        </div>
      ) : (
        <div className="grid gap-2">
          <Label id="ask-eval-question-label">Eval question</Label>
          {isLoading ? (
            <Skeleton aria-busy="true" className="h-8 w-full" />
          ) : (
            <Select value={value ?? ''} onValueChange={handleQuestionChange}>
              <SelectTrigger
                aria-labelledby="ask-eval-question-label"
                className="w-full justify-between"
              >
                <SelectValue placeholder="Select an eval question" />
              </SelectTrigger>
              <SelectContent className="max-w-[min(42rem,calc(100vw-2rem))]">
                {questions.map((question) => (
                  <SelectItem value={question.query_id} key={question.query_id}>
                    {formatQuestionLabel(question)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          {isError ? (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage}
            </p>
          ) : null}
        </div>
      )}
    </div>
  )
}

function formatQuestionLabel(question: EvalQuestion): string {
  const trimmedQuery = question.query.trim()
  const label =
    trimmedQuery.length > 96 ? `${trimmedQuery.slice(0, 95).trimEnd()}...` : trimmedQuery

  return `${label} (${question.query_id})`
}
