import type { PerQueryMetrics } from '@/lib/types'

interface GoldMetricsPanelProps {
  metrics: PerQueryMetrics | null
}

/**
 * Shows EM / F1 / supporting_fact_recall@k whenever the active query carried
 * gold_answers / supporting_passage_ids. Renders nothing when metrics is null.
 */
export function GoldMetricsPanel({ metrics }: GoldMetricsPanelProps) {
  if (metrics === null) {
    return null
  }
  return (
    <div className="sidebar__section" aria-label="Gold metrics">
      <span className="sidebar__title">Gold metrics</span>
      <div className="gold-metrics">
        <Metric label="EM" value={formatRate(metrics.em)} />
        <Metric label="F1" value={formatRate(metrics.f1)} />
        <Metric
          label={`Recall@${metrics.k_used ?? 'k'}`}
          value={formatRate(metrics.supporting_fact_recall_at_k)}
        />
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="gold-metric">
      <div className="gold-metric__label">{label}</div>
      <div className="gold-metric__value">{value}</div>
    </div>
  )
}

function formatRate(value: number | null): string {
  if (value === null) return 'n/a'
  return value.toFixed(3)
}
