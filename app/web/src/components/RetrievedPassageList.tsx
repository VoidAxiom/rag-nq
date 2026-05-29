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
      <div aria-busy="true" className="passages-list" role="status">
        <div className="passage-card">Retrieving passages…</div>
      </div>
    )
  }

  if (passages === null || passages.length === 0) {
    return (
      <p className="theme-error" role="status">
        No passages retrieved.
      </p>
    )
  }

  const supportingIdSet = new Set(supportingIds)

  return (
    <section className="passages-list" aria-label="Retrieved passages">
      {passages.map((passage) => {
        const isSupporting = supportingIdSet.has(passage.point_id)
        return (
          <article key={passage.point_id} className="passage-card">
            <header className="passage-card__head">
              <div className="passage-card__title">
                {formatDisplayRank(passage)}
                <span> </span>
                {passage.title ?? truncate(passage.point_id, 14)}
                {isSupporting ? (
                  <span className="passage-card__supporting">supporting</span>
                ) : null}
              </div>
              <div className="passage-card__rank">{passage.point_id}</div>
            </header>
            <p className="passage-card__body">{truncatePassageText(passage.text)}</p>
            <div className="passage-card__badges">
              {rankBadges(passage).map((rank) => (
                <span key={rank} className="passage-card__badge">
                  {rank}
                </span>
              ))}
            </div>
          </article>
        )
      })}
    </section>
  )
}

function formatDisplayRank(passage: PassageHit): string {
  const rank =
    passage.rerank_rank ??
    passage.fusion_rank ??
    passage.dense_rank ??
    passage.sparse_rank
  if (rank === null || rank === undefined) return '#-'
  return `#${rank}`
}

function truncatePassageText(text: string): string {
  if (text.length <= 280) return text
  return `${text.slice(0, 279).trimEnd()}...`
}

function truncate(value: string, max: number): string {
  return value.length <= max ? value : `${value.slice(0, max)}...`
}

function rankBadges(passage: PassageHit): string[] {
  return [
    formatStageRank('dense', passage.dense_rank),
    formatStageRank('sparse', passage.sparse_rank),
    formatStageRank('fusion', passage.fusion_rank),
    formatStageRank('rerank', passage.rerank_rank),
  ].filter((rank): rank is string => rank !== null)
}

function formatStageRank(
  label: string,
  rank: number | null | undefined,
): string | null {
  if (rank === null || rank === undefined) return null
  return `${label}=#${rank}`
}
