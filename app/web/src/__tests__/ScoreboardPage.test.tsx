import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'

import { ScoreboardPage } from '@/pages/ScoreboardPage'
import type { Scoreboard, ScoreboardRow } from '@/lib/types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ScoreboardPage', () => {
  it('renders the empty scoreboard state', async () => {
    stubFetchScoreboard({
      schema_version: 1,
      generated_at: '2026-05-27T00:00:00Z',
      rows: [],
    })

    renderScoreboardPage()

    expect(
      await screen.findByText('No scoreboard rows yet. Run an eval to populate.'),
    ).toBeInTheDocument()
  })

  it('renders populated scoreboard rows from the API response', async () => {
    const row = populatedScoreboardRow()

    stubFetchScoreboard({
      schema_version: 1,
      generated_at: '2026-05-27T00:00:00Z',
      rows: [row],
    })

    renderScoreboardPage()

    expect(await screen.findByText(row.phase)).toBeInTheDocument()
    expect(screen.getByText(row.commit_sha.slice(0, 7))).toBeInTheDocument()
    expect(
      screen.getByText(row.retriever_metrics.recall_at_10.toFixed(3)),
    ).toBeInTheDocument()
    expect(screen.getByText(row.answer_metrics.f1.toFixed(3))).toBeInTheDocument()
    expect(
      screen.getByText(row.quality_metrics.faithfulness.toFixed(3)),
    ).toBeInTheDocument()
    expect(screen.getByText('42 ms')).toBeInTheDocument()
  })
})

function renderScoreboardPage(): void {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <ScoreboardPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function stubFetchScoreboard(scoreboard: Scoreboard): void {
  const fetchMock = vi.fn<() => Promise<Response>>(() =>
    Promise.resolve(
      new Response(JSON.stringify(scoreboard), {
        status: 200,
        headers: {
          'Content-Type': 'application/json',
        },
      }),
    ),
  )

  vi.stubGlobal('fetch', fetchMock)
}

function populatedScoreboardRow() {
  return {
    phase: 'P0-D',
    pipeline: 'bm25-baseline',
    benchmark: 'nq-retrieval',
    split: 'dev',
    retriever_metrics: {
      recall_at_1: 0.321,
      recall_at_5: 0.765,
      recall_at_10: 0.876,
      mrr_at_10: 0.432,
      ndcg_at_10: 0.543,
    },
    answer_metrics: {
      em: 0.123,
      f1: 0.654,
      joint_f1: 0.456,
    },
    quality_metrics: {
      faithfulness: 0.789,
      context_precision: 0.678,
      context_recall: 0.567,
      hallucination_rate_judged: 0.111,
      abstention_rate: 0.222,
    },
    latency_ms: {
      p50: 42,
      p95: 84,
    },
    models: {
      embedder: 'bge-small-en-v1.5',
      reranker: 'cross-encoder/ms-marco-MiniLM-L-6-v2',
      reasoning_llm: null,
      verifier: null,
    },
    commit_sha: 'abcdef1234567890',
    notes: null,
  } satisfies ScoreboardRow
}
