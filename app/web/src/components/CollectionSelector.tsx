import type { ChangeEvent } from 'react'

import type { CollectionChoice } from '@/lib/types'

interface CollectionSelectorProps {
  value: string
  choices: CollectionChoice[]
  onChange: (collection: string) => void
  /**
   * Emits the selected collection's benchmark so parents can fetch the matching
   * eval-question JSON without parsing display labels.
   */
  onBenchmarkChange?: (benchmark: string) => void
}

export function CollectionSelector({
  value,
  choices,
  onChange,
  onBenchmarkChange,
}: CollectionSelectorProps) {
  function handleChange(event: ChangeEvent<HTMLSelectElement>) {
    const collection = event.target.value
    onChange(collection)
    const selected = choices.find((choice) => choice.collection === collection)
    if (selected !== undefined) {
      onBenchmarkChange?.(selected.benchmark)
    }
  }

  return (
    <select
      className="knob-control"
      aria-label="Collection"
      value={value}
      onChange={handleChange}
      disabled={choices.length === 0}
    >
      {choices.length === 0 ? (
        <option value="">No collections</option>
      ) : null}
      {choices.map((choice) => (
        <option value={choice.collection} key={choice.collection}>
          {formatCollectionLabel(choice)}
        </option>
      ))}
    </select>
  )
}

function formatCollectionLabel(choice: CollectionChoice): string {
  return `${choice.benchmark}: ${choice.collection}`
}
