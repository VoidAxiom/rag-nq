import { CheckIcon } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'
import type { PassageHit } from '@/lib/types'

interface RetrievedPassageListProps {
  passages: PassageHit[] | null
  isLoading: boolean
  supportingIds?: string[]
}

export function RetrievedPassageList({
  passages,
  isLoading,
  supportingIds = [],
}: RetrievedPassageListProps) {
  if (isLoading) {
    return (
      <div aria-busy="true" className="grid gap-3">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-28 w-full" />
      </div>
    )
  }

  if (passages === null || passages.length === 0) {
    return <StateCard title="Retrieved passages" message="No passages retrieved" />
  }

  const supportingIdSet = new Set(supportingIds)

  return (
    <section className="grid gap-3" aria-label="Retrieved passages">
      {passages.map((passage) => {
        const isSupporting = supportingIdSet.has(passage.point_id)

        return (
          <Card key={passage.point_id}>
            <CardHeader className="flex flex-row items-start justify-between gap-3">
              <div className="min-w-0">
                <CardTitle className="flex flex-wrap items-center gap-2">
                  <span>{formatDisplayRank(passage)}</span>
                  <span className="truncate">{passage.title ?? passage.point_id}</span>
                </CardTitle>
              </div>
              {isSupporting ? (
                <Badge
                  className={cn(
                    'border-green-300 bg-green-50 text-green-800',
                    'shrink-0',
                  )}
                >
                  <CheckIcon />
                  Supporting
                </Badge>
              ) : null}
            </CardHeader>
            <CardContent>
              <p className="text-sm leading-6 text-muted-foreground">
                {truncatePassageText(passage.text)}
              </p>
            </CardContent>
            <CardFooter>
              <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
                {rankBadges(passage).map((rank) => (
                  <Badge variant="outline" key={rank}>
                    {rank}
                  </Badge>
                ))}
              </div>
            </CardFooter>
          </Card>
        )
      })}
    </section>
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

function formatDisplayRank(passage: PassageHit): string {
  const rank =
    passage.rerank_rank ?? passage.fusion_rank ?? passage.dense_rank ?? passage.sparse_rank

  return rank === null || rank === undefined ? '#-' : `#${rank}`
}

function truncatePassageText(text: string): string {
  if (text.length <= 280) {
    return text
  }

  return `${text.slice(0, 279).trimEnd()}...`
}

function rankBadges(passage: PassageHit): string[] {
  return [
    formatStageRank('dense', passage.dense_rank),
    formatStageRank('sparse', passage.sparse_rank),
    formatStageRank('fusion', passage.fusion_rank),
    formatStageRank('rerank', passage.rerank_rank),
  ].filter((rank): rank is string => rank !== null)
}

function formatStageRank(label: string, rank: number | null | undefined): string | null {
  if (rank === null || rank === undefined) {
    return null
  }

  return `${label}=#${rank}`
}
