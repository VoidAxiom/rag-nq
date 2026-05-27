import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { Link } from 'react-router'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { fetchScoreboard } from '@/lib/api'
import type { ScoreboardRow } from '@/lib/types'

export function ScoreboardPage() {
  const { data, error, isError, isLoading } = useQuery({
    queryKey: ['scoreboard'],
    queryFn: fetchScoreboard,
  })

  if (isLoading) {
    return (
      <PageFrame>
        <StateCard title="Loading scoreboard" message="Fetching latest scoreboard rows." />
      </PageFrame>
    )
  }

  if (isError) {
    const message =
      error instanceof Error ? error.message : 'The scoreboard request failed.'

    return (
      <PageFrame>
        <StateCard title="Unable to load scoreboard" message={message} />
      </PageFrame>
    )
  }

  if (data === undefined || data.rows.length === 0) {
    return (
      <PageFrame>
        <StateCard
          title="Scoreboard"
          message="No scoreboard rows yet. Run an eval to populate."
        />
      </PageFrame>
    )
  }

  return (
    <PageFrame>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>phase</TableHead>
            <TableHead>pipeline</TableHead>
            <TableHead>benchmark</TableHead>
            <TableHead>split</TableHead>
            <TableHead>embedder</TableHead>
            <TableHead>reranker</TableHead>
            <TableHead>recall@10</TableHead>
            <TableHead>mrr@10</TableHead>
            <TableHead>f1</TableHead>
            <TableHead>faithfulness</TableHead>
            <TableHead>latency_p50 (ms)</TableHead>
            <TableHead>commit_sha[:7]</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.rows.map((row) => (
            <ScoreboardTableRow row={row} key={scoreboardRowKey(row)} />
          ))}
        </TableBody>
      </Table>
    </PageFrame>
  )
}

function PageFrame({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
      <header className="flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-muted-foreground">Evaluation</p>
          <h1 className="text-3xl font-semibold tracking-normal">Scoreboard</h1>
        </div>
        <Link className="text-sm font-medium text-muted-foreground hover:text-foreground" to="/">
          Home
        </Link>
      </header>
      {children}
    </main>
  )
}

function StateCard({ title, message }: { title: string; message: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground">{message}</p>
      </CardContent>
    </Card>
  )
}

function ScoreboardTableRow({ row }: { row: ScoreboardRow }) {
  return (
    <TableRow>
      <TableCell>{row.phase}</TableCell>
      <TableCell>{row.pipeline}</TableCell>
      <TableCell>{row.benchmark}</TableCell>
      <TableCell>{row.split}</TableCell>
      <TableCell>{row.models.embedder}</TableCell>
      <TableCell>{row.models.reranker}</TableCell>
      <TableCell>{formatMetric(row.retriever_metrics.recall_at_10)}</TableCell>
      <TableCell>{formatMetric(row.retriever_metrics.mrr_at_10)}</TableCell>
      <TableCell>{formatOptionalMetric(row.answer_metrics?.f1)}</TableCell>
      <TableCell>{formatOptionalMetric(row.quality_metrics?.faithfulness)}</TableCell>
      <TableCell>{formatLatencyMs(row.latency_ms.p50)}</TableCell>
      <TableCell>{row.commit_sha.slice(0, 7)}</TableCell>
    </TableRow>
  )
}

function scoreboardRowKey(row: ScoreboardRow): string {
  return `${row.phase}:${row.pipeline}:${row.benchmark}:${row.split}:${row.commit_sha}`
}

function formatOptionalMetric(value: number | undefined): string {
  return value === undefined ? '—' : formatMetric(value)
}

function formatMetric(value: number): string {
  return value.toFixed(3)
}

function formatLatencyMs(value: number): string {
  return `${Math.round(value)} ms`
}
