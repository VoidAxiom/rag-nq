import type { ChangeEvent } from 'react'

import { CollectionSelector } from '@/components/CollectionSelector'
import type {
  CollectionChoice,
  RetrievalMode,
} from '@/lib/types'

interface RetrieverKnobsProps {
  modes: readonly RetrievalMode[]
  mode: RetrievalMode
  onModeChange: (mode: RetrievalMode) => void
  topKChoices: readonly number[]
  topK: number
  onTopKChange: (topK: number) => void
  collection: string
  collections: CollectionChoice[]
  onCollectionChange: (collection: string) => void
}

export function RetrieverKnobs({
  modes,
  mode,
  onModeChange,
  topKChoices,
  topK,
  onTopKChange,
  collection,
  collections,
  onCollectionChange,
}: RetrieverKnobsProps) {
  function handleModeChange(event: ChangeEvent<HTMLSelectElement>) {
    const next = event.target.value
    if (isRetrievalMode(next)) {
      onModeChange(next)
    }
  }

  function handleTopKChange(event: ChangeEvent<HTMLSelectElement>) {
    onTopKChange(Number(event.target.value))
  }

  return (
    <div className="knob-group" role="group" aria-label="Retriever knobs">
      <label className="knob-row">
        <span className="knob-label">Mode</span>
        <select
          className="knob-control"
          aria-label="Retrieval mode"
          value={mode}
          onChange={handleModeChange}
        >
          {modes.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      <label className="knob-row">
        <span className="knob-label">Top K</span>
        <select
          className="knob-control"
          aria-label="Top K"
          value={String(topK)}
          onChange={handleTopKChange}
        >
          {topKChoices.map((value) => (
            <option key={value} value={String(value)}>
              {value}
            </option>
          ))}
        </select>
      </label>
      <div className="knob-row">
        <span className="knob-label">Collection</span>
        <div>
          <CollectionSelector
            value={collection}
            choices={collections}
            onChange={onCollectionChange}
          />
        </div>
      </div>
    </div>
  )
}

function isRetrievalMode(value: string): value is RetrievalMode {
  return value === 'dense' || value === 'sparse' || value === 'hybrid'
}
