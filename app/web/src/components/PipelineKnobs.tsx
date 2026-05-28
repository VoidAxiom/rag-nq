import type { ReactNode } from 'react'

import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import type {
  ComponentChoice,
  ComponentsResponse,
  RetrievalMode,
} from '@/lib/types'

interface PipelineKnobsProps {
  components: ComponentsResponse
  mode: RetrievalMode
  onModeChange: (mode: RetrievalMode) => void
  topK: number
  onTopKChange: (k: number) => void
  reranker: string
  onRerankerChange: (name: string) => void
  generator: string
  onGeneratorChange: (name: string) => void
  isModelLoading?: boolean
}

export function PipelineKnobs({
  components,
  mode,
  onModeChange,
  topK,
  onTopKChange,
  reranker,
  onRerankerChange,
  generator,
  onGeneratorChange,
  isModelLoading = false,
}: PipelineKnobsProps) {
  return (
    <div className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <KnobField label="Retrieval mode" labelId="ask-mode-label">
          <Select value={mode} onValueChange={(next) => handleModeChange(next, onModeChange)}>
            <SelectTrigger aria-labelledby="ask-mode-label" className="w-full">
              <SelectValue placeholder="Mode" />
            </SelectTrigger>
            <SelectContent>
              {components.modes.map((choice) => (
                <SelectItem value={choice} key={choice}>
                  {choice}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </KnobField>

        <KnobField label="Top K" labelId="ask-top-k-label">
          <Select value={String(topK)} onValueChange={(next) => onTopKChange(Number(next))}>
            <SelectTrigger aria-labelledby="ask-top-k-label" className="w-full">
              <SelectValue placeholder="Top K" />
            </SelectTrigger>
            <SelectContent>
              {components.top_k_choices.map((choice) => (
                <SelectItem value={String(choice)} key={choice}>
                  {choice}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </KnobField>

        <KnobField label="Reranker" labelId="ask-reranker-label">
          <Select value={reranker} onValueChange={onRerankerChange}>
            <SelectTrigger aria-labelledby="ask-reranker-label" className="w-full">
              <SelectValue placeholder="Reranker" />
            </SelectTrigger>
            <SelectContent>
              {components.rerankers.map((choice) => (
                <SelectItem value={choice.name} key={choice.name}>
                  {formatRerankerLabel(choice)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </KnobField>

        <KnobField label="Generator" labelId="ask-generator-label">
          <Select value={generator} onValueChange={onGeneratorChange}>
            <SelectTrigger aria-labelledby="ask-generator-label" className="w-full">
              <SelectValue placeholder="Generator" />
            </SelectTrigger>
            <SelectContent>
              {components.generators.map((choice) => (
                <GeneratorSelectItem choice={choice} key={choice.name} />
              ))}
            </SelectContent>
          </Select>
        </KnobField>
      </div>

      {isModelLoading ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading reranker...
        </p>
      ) : null}
    </div>
  )
}

function KnobField({
  label,
  labelId,
  children,
}: {
  label: string
  labelId: string
  children: ReactNode
}) {
  return (
    <div className="grid gap-2">
      <Label id={labelId}>{label}</Label>
      {children}
    </div>
  )
}

function GeneratorSelectItem({ choice }: { choice: ComponentChoice }) {
  const disabled = choice.enabled === false
  const label = choice.label
  const reason = choice.disabled_reason ?? 'This generator is disabled.'

  return (
    <SelectItem value={choice.name} disabled={disabled} aria-label={label}>
      {disabled ? (
        <Tooltip>
          <TooltipTrigger asChild>
            <span className={cn('inline-flex min-w-0 items-center gap-1', 'truncate')}>
              {label}
            </span>
          </TooltipTrigger>
          <TooltipContent>{reason}</TooltipContent>
        </Tooltip>
      ) : (
        label
      )}
    </SelectItem>
  )
}

function formatRerankerLabel(choice: ComponentChoice): string {
  if (choice.name === 'off') {
    return 'No rerank'
  }

  return choice.label
}

function handleModeChange(
  value: string,
  onModeChange: (mode: RetrievalMode) => void,
): void {
  if (value === 'dense' || value === 'sparse' || value === 'hybrid') {
    onModeChange(value)
  }
}
