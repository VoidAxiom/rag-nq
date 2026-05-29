interface PipelineTotalProps {
  state: 'idle' | 'running' | 'complete'
  totalMs: number | null
}

export function PipelineTotal({ state, totalMs }: PipelineTotalProps) {
  const seconds = totalMs === null ? 0 : totalMs / 1000
  const classNames = ['total']
  if (state === 'running') classNames.push('total--running')
  if (state === 'complete') classNames.push('total--complete')

  let sub: string
  if (state === 'running') sub = '// running'
  else if (state === 'complete') sub = '// complete'
  else sub = '// idle'

  return (
    <div className={classNames.join(' ')} aria-live="polite">
      <div className="total__label">Total</div>
      <div>
        <span className="total__num">{seconds.toFixed(2)}</span>
        <span className="total__unit">s</span>
      </div>
      <div className="total__sub">{sub}</div>
    </div>
  )
}
