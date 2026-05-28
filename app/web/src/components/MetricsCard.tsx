import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import type {
  ComponentSet,
  LatencyBreakdown,
  PerQueryMetrics,
} from '@/lib/types'

interface MetricsCardProps {
  metrics: PerQueryMetrics | null
  components: ComponentSet | null
  latency: LatencyBreakdown | null
}

export function MetricsCard({ metrics, components, latency }: MetricsCardProps) {
  if (metrics === null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Per-query metrics</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No metrics — this query is free-text (no gold answers / no supporting
            passage IDs).
          </p>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Per-query metrics</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid gap-3 sm:grid-cols-3">
          <MetricValue label="EM" value={formatMetric(metrics.em)} />
          <MetricValue label="F1" value={formatMetric(metrics.f1)} />
          <MetricValue
            label="supporting_fact_recall_at_k"
            value={formatMetric(metrics.supporting_fact_recall_at_k)}
          />
        </div>

        <div className="grid gap-2 text-sm">
          <p className="font-medium">Components</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
            <span>mode={components?.mode ?? '—'}</span>
            <span>top_k={components?.top_k ?? '—'}</span>
            <span>reranker={components?.reranker ?? '—'}</span>
            <span>generator={components?.generator ?? '—'}</span>
          </div>
        </div>

        <div className="grid gap-2 text-sm">
          <p className="font-medium">Latency</p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-muted-foreground">
            <span>retrieval={formatOptionalMs(latency?.retrieval_ms)}</span>
            <span>rerank={formatOptionalMs(latency?.rerank_ms)}</span>
            <span>generation={formatOptionalMs(latency?.generation_ms)}</span>
            <span>total={formatOptionalMs(latency?.total_ms)}</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function MetricValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid gap-1 rounded-lg border p-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold tabular-nums">{value}</span>
    </div>
  )
}

function formatMetric(value: number | null): string {
  return value === null ? '—' : value.toFixed(3)
}

function formatOptionalMs(value: number | undefined): string {
  return value === undefined ? '—' : formatMs(value)
}

function formatMs(value: number): string {
  return `${value.toFixed(1)} ms`
}
