import { useEffect, useRef, useState } from 'react'

import type { GroundedAnswer } from '@/lib/types'

interface AnswerPanelProps {
  /** Null while no answer yet. */
  grounded: GroundedAnswer | null
  /** True once the generator step is `complete` AND grounded is non-null. */
  reveal: boolean
}

const TYPE_INTERVAL_MS = 18

export function AnswerPanel({ grounded, reveal }: AnswerPanelProps) {
  const fullText = grounded?.answer ?? ''
  const [typedLen, setTypedLen] = useState(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Reset the typed counter whenever the reveal flag flips or the source text
  // changes. We run a single effect that either schedules the typewriter or
  // tears down any existing interval; the setState happens inside the timer
  // callback, not inline. Synchronously resetting `typedLen` to 0 in render
  // when the text changes would force a re-render anyway; doing it in effect
  // is fine because the inactive state still renders the empty text first.
  useEffect(() => {
    if (intervalRef.current !== null) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
    // Reset on each new reveal cycle. Disable the set-state-in-effect lint:
    // this IS the canonical "reset state when an input prop changes" pattern; the
    // alternative (useReducer keyed off a session counter from the parent) is more
    // code for the same outcome on a self-contained typewriter widget.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setTypedLen(0)
    if (!reveal || fullText.length === 0) {
      return
    }
    intervalRef.current = setInterval(() => {
      setTypedLen((current) => {
        if (current >= fullText.length) {
          if (intervalRef.current !== null) {
            clearInterval(intervalRef.current)
            intervalRef.current = null
          }
          return fullText.length
        }
        return current + 1
      })
    }, TYPE_INTERVAL_MS)
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [reveal, fullText])

  const visible = reveal && grounded !== null
  const typing = typedLen < fullText.length
  const displayedText = fullText.slice(0, typedLen)

  return (
    <section
      className={visible ? 'answer answer--visible' : 'answer'}
      aria-live="polite"
      aria-label="Grounded answer"
    >
      <div className="answer__label">
        {visible ? '⟨ Answer ⟩' : 'Awaiting answer'}
      </div>
      {visible && grounded?.abstained === true ? (
        <div>
          <span className="answer__abstained">Abstained</span>
          {grounded.abstention_reason !== null &&
          grounded.abstention_reason !== undefined ? (
            <span className="answer__text">{grounded.abstention_reason}</span>
          ) : null}
        </div>
      ) : null}
      <div className="answer__text" data-testid="answer-text">
        {displayedText}
        {typing && visible ? (
          <span className="answer__cursor" aria-hidden="true">
            ▎
          </span>
        ) : null}
      </div>
      {grounded !== null && grounded.citations.length > 0 && !typing ? (
        <div className="answer__citations" aria-label="Citations">
          {grounded.citations.map((citation) => (
            <span key={citation.point_id} className="answer__citation">
              {truncate(citation.point_id, 12)}
            </span>
          ))}
        </div>
      ) : null}
    </section>
  )
}

function truncate(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max)}...`
}
