import type { ChangeEvent } from 'react'

import type { ComponentChoice } from '@/lib/types'

interface GeneratorKnobsProps {
  choices: readonly ComponentChoice[]
  value: string
  onChange: (name: string) => void
}

export function GeneratorKnobs({ choices, value, onChange }: GeneratorKnobsProps) {
  function handleChange(event: ChangeEvent<HTMLSelectElement>) {
    const next = event.target.value
    const selected = choices.find((c) => c.name === next)
    if (selected === undefined || selected.enabled === false) {
      return
    }
    onChange(next)
  }

  return (
    <div className="knob-group" role="group" aria-label="Generator knobs">
      <label className="knob-row">
        <span className="knob-label">Provider</span>
        <select
          className="knob-control"
          aria-label="Generator"
          value={value}
          onChange={handleChange}
        >
          {choices.map((choice) => (
            <option
              key={choice.name}
              value={choice.name}
              disabled={choice.enabled === false}
              title={choice.enabled === false ? choice.disabled_reason ?? 'Disabled' : undefined}
            >
              {choice.label}
              {choice.enabled === false ? ' (disabled)' : ''}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
