import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import type { GroundedAnswer } from '@/lib/types'

interface AnswerCardProps {
  grounded: GroundedAnswer | null
  isLoading: boolean
}

export function AnswerCard({ grounded, isLoading }: AnswerCardProps) {
  if (isLoading) {
    return (
      <Card aria-busy="true">
        <CardHeader>
          <Skeleton className="h-5 w-40" />
        </CardHeader>
        <CardContent className="grid gap-3">
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-5/6" />
          <Skeleton className="h-4 w-2/3" />
        </CardContent>
      </Card>
    )
  }

  if (grounded === null) {
    return (
      <StateCard
        title="Grounded answer"
        message="Run a query to see the grounded answer here."
      />
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Grounded answer</CardTitle>
        <Badge variant="secondary">{grounded.citations.length} citations</Badge>
      </CardHeader>
      <CardContent className="grid gap-4">
        {grounded.abstained ? (
          <div className="flex flex-wrap items-center gap-2">
            <Badge className="border-yellow-300 bg-yellow-50 text-yellow-800">
              Abstained
            </Badge>
            {grounded.abstention_reason ? (
              <span className="text-sm text-muted-foreground">
                {grounded.abstention_reason}
              </span>
            ) : null}
          </div>
        ) : null}

        <p className="whitespace-pre-wrap text-sm leading-6">{grounded.answer}</p>

        {grounded.citations.length > 0 ? (
          <div className="flex flex-wrap gap-2" aria-label="Citations">
            {grounded.citations.map((citation) => (
              <Badge variant="outline" key={citation.point_id}>
                {truncatePointId(citation.point_id)}
              </Badge>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
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

function truncatePointId(pointId: string): string {
  if (pointId.length <= 12) {
    return pointId
  }

  return `${pointId.slice(0, 12)}...`
}
