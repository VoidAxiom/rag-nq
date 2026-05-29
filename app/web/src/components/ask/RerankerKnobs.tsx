import type { ChangeEvent } from 'react'

import type { ComponentChoice } from '@/lib/types'

interface RerankerKnobsProps {
  choices: readonly ComponentChoice[]
  value: string
  onChange: (name: string) => void
}

export function RerankerKnobs({ choices, value, onChange }: RerankerKnobsProps) {
  function handleChange(event: ChangeEvent<HTMLSelectElement>) {
    onChange(event.target.value)
  }

  return (
    <div className="knob-group" role="group" aria-label="Reranker knobs">
      <label className="knob-row">
        <span className="knob-label">Model</span>
        <select
          className="knob-control"
          aria-label="Reranker"
          value={value}
          onChange={handleChange}
        >
          {choices.map((choice) => (
            <option key={choice.name} value={choice.name}>
              {formatLabel(choice)}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}

function formatLabel(choice: ComponentChoice): string {
  if (choice.name === 'off') {
    return 'No rerank'
  }
  return choice.label
}
