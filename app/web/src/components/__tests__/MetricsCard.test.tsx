import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { MetricsCard } from '@/components/MetricsCard'
import type {
  ComponentSet,
  LatencyBreakdown,
  PerQueryMetrics,
} from '@/lib/types'

afterEach(() => {
  cleanup()
})

describe('MetricsCard', () => {
  it('renders n/a for em and f1 when only supporting_passage_ids was supplied', () => {
    renderMetricsCard({
      em: null,
      f1: null,
      supporting_fact_recall_at_k: 0.5,
      k_used: 10,
    })

    expect(screen.getAllByText('n/a')).toHaveLength(2)
    expect(screen.getByText('0.500')).toBeInTheDocument()
  })

  it('renders formatted em and f1 when both metrics are provided', () => {
    renderMetricsCard({
      em: 1.0,
      f1: 1.0,
      supporting_fact_recall_at_k: 1.0,
      k_used: 10,
    })

    expect(screen.getAllByText('1.000')).toHaveLength(3)
    expect(screen.queryByText('n/a')).not.toBeInTheDocument()
  })
})

function renderMetricsCard(metrics: PerQueryMetrics): void {
  render(
    <MetricsCard
      metrics={metrics}
      components={componentsFixture()}
      latency={latencyFixture()}
    />,
  )
}

function componentsFixture(): ComponentSet {
  return {
    mode: 'hybrid',
    top_k: 10,
    reranker: 'off',
    generator: 'heuristic',
    embedder: 'bge-small-en-v1.5',
    collection: 'nq-dev',
  }
}

function latencyFixture(): LatencyBreakdown {
  return {
    retrieval_ms: 12.25,
    rerank_ms: 0,
    generation_ms: 4.5,
    total_ms: 16.75,
  }
}
