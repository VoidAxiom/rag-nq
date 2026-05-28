import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
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
  function handleValueChange(collection: string): void {
    onChange(collection)

    const selected = choices.find((choice) => choice.collection === collection)
    if (selected !== undefined) {
      onBenchmarkChange?.(selected.benchmark)
    }
  }

  return (
    <div className="grid gap-2">
      <Label id="ask-collection-label">Collection</Label>
      <Select
        value={value}
        onValueChange={handleValueChange}
        disabled={choices.length === 0}
      >
        <SelectTrigger
          aria-labelledby="ask-collection-label"
          className="w-full justify-between"
        >
          <SelectValue placeholder="Select a collection" />
        </SelectTrigger>
        <SelectContent>
          {choices.map((choice) => (
            <SelectItem value={choice.collection} key={choice.collection}>
              {formatCollectionLabel(choice)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

function formatCollectionLabel(choice: CollectionChoice): string {
  return `${choice.benchmark}: ${choice.collection}`
}
