interface PipelineBridgeProps {
  /** 1 → between retriever & reranker (uses accent-1); 2 → between reranker & generator (uses accent-2). */
  accent: 1 | 2
  state: 'idle' | 'flowing' | 'complete'
}

export function PipelineBridge({ accent, state }: PipelineBridgeProps) {
  const classNames = ['bridge']
  if (state === 'flowing') classNames.push('bridge--flowing')
  if (state === 'complete') classNames.push('bridge--complete')
  return (
    <div
      className={classNames.join(' ')}
      data-accent={String(accent)}
      aria-hidden="true"
    />
  )
}
