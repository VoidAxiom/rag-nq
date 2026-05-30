import { useState, type ReactNode } from 'react'

import { EvalQuestionPicker } from '@/components/EvalQuestionPicker'
import { RetrievedPassageList } from '@/components/RetrievedPassageList'
import { GoldMetricsPanel } from '@/components/ask/GoldMetricsPanel'
import type {
  EvalQuestion,
  PassageHit,
  PerQueryMetrics,
} from '@/lib/types'

interface AskSidebarProps {
  benchmark: string
  questionId: string | null
  onPickQuestion: (question: EvalQuestion | null) => void
  onFreeText: (text: string) => void
  passages: PassageHit[] | null
  isLoading: boolean
  supportingIds?: string[]
  metrics: PerQueryMetrics | null
}

export function AskSidebar({
  benchmark,
  questionId,
  onPickQuestion,
  onFreeText,
  passages,
  isLoading,
  supportingIds = [],
  metrics,
}: AskSidebarProps) {
  const hasPassages = passages !== null && passages.length > 0
  const [passagesOpen, setPassagesOpen] = useState(true)

  // Auto-collapse once a populated result lands. The user can re-open manually.
  // Using state instead of derived "controlled" so user-toggle wins.
  // (Derived would constantly re-collapse on data change.)

  return (
    <aside className="sidebar" aria-label="Ask sidebar">
      <div className="sidebar__section">
        <span className="sidebar__title">Question</span>
        <EvalQuestionPicker
          benchmark={benchmark}
          value={questionId}
          onPickQuestion={onPickQuestion}
          onFreeText={onFreeText}
        />
      </div>
      <Collapsible
        title="Retrieved passages"
        open={passagesOpen}
        onToggle={() => setPassagesOpen((v) => !v)}
      >
        {hasPassages || isLoading ? (
          <RetrievedPassageList
            passages={passages}
            isLoading={isLoading}
            supportingIds={supportingIds}
          />
        ) : (
          <p className="theme-error" role="status">
            Run a query to see retrieved passages here.
          </p>
        )}
      </Collapsible>
      <GoldMetricsPanel metrics={metrics} />
    </aside>
  )
}

function Collapsible({
  title,
  open,
  onToggle,
  children,
}: {
  title: string
  open: boolean
  onToggle: () => void
  children: ReactNode
}) {
  return (
    <div className="sidebar__section">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="sidebar__title"
        style={{
          background: 'transparent',
          border: 'none',
          textAlign: 'left',
          padding: 0,
          cursor: 'pointer',
          color: 'inherit',
          letterSpacing: 'inherit',
          textTransform: 'inherit',
          fontFamily: 'inherit',
          fontSize: 'inherit',
        }}
      >
        {open ? '▼ ' : '▶ '}
        {title}
      </button>
      {open ? children : null}
    </div>
  )
}
