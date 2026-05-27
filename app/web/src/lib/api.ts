import type {
  AnswerMetrics,
  LatencyMs,
  ModelSet,
  QualityMetrics,
  RetrieverMetrics,
  Scoreboard,
  ScoreboardRow,
} from '@/lib/types'

const scoreboardPath = '/scoreboard'

export async function fetchScoreboard(): Promise<Scoreboard> {
  const response = await fetch(scoreboardEndpoint())

  if (!response.ok) {
    const body = await readErrorBody(response)
    const statusText = response.statusText.trim()
    const status = statusText
      ? `${response.status} ${statusText}`
      : `${response.status}`
    const detail = body === '' ? '' : `: ${body}`

    throw new Error(`Failed to fetch scoreboard (${status})${detail}`)
  }

  const payload: unknown = await response.json()
  return parseScoreboard(payload)
}

function scoreboardEndpoint(): string {
  const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').trim()

  if (baseUrl === '') {
    return scoreboardPath
  }

  return `${baseUrl.replace(/\/+$/, '')}${scoreboardPath}`
}

async function readErrorBody(response: Response): Promise<string> {
  try {
    return (await response.text()).trim()
  } catch {
    return ''
  }
}

function parseScoreboard(value: unknown): Scoreboard {
  const scoreboard = requireRecord(value, 'scoreboard')
  const schemaVersion = scoreboard.schema_version
  const generatedAt = requireString(scoreboard, 'generated_at')
  const rows = scoreboard.rows

  if (schemaVersion !== 1) {
    throw new Error('Invalid scoreboard payload: schema_version must be 1')
  }

  if (!Array.isArray(rows)) {
    throw new Error('Invalid scoreboard payload: rows must be an array')
  }

  return {
    schema_version: 1,
    generated_at: generatedAt,
    rows: rows.map(parseScoreboardRow),
  }
}

function parseScoreboardRow(value: unknown): ScoreboardRow {
  const row = requireRecord(value, 'scoreboard row')

  return {
    phase: requireString(row, 'phase'),
    pipeline: requireString(row, 'pipeline'),
    benchmark: requireString(row, 'benchmark'),
    split: requireString(row, 'split'),
    retriever_metrics: parseRetrieverMetrics(
      requireRecord(row.retriever_metrics, 'retriever_metrics'),
    ),
    answer_metrics: parseNullableRecord(row.answer_metrics, 'answer_metrics', parseAnswerMetrics),
    quality_metrics: parseNullableRecord(
      row.quality_metrics,
      'quality_metrics',
      parseQualityMetrics,
    ),
    latency_ms: parseLatencyMs(requireRecord(row.latency_ms, 'latency_ms')),
    models: parseModelSet(requireRecord(row.models, 'models')),
    commit_sha: requireString(row, 'commit_sha'),
    notes: requireNullableString(row, 'notes'),
  }
}

function parseRetrieverMetrics(value: Record<string, unknown>): RetrieverMetrics {
  return {
    recall_at_1: requireRate(value, 'recall_at_1'),
    recall_at_5: requireRate(value, 'recall_at_5'),
    recall_at_10: requireRate(value, 'recall_at_10'),
    mrr_at_10: requireRate(value, 'mrr_at_10'),
    ndcg_at_10: requireRate(value, 'ndcg_at_10'),
  }
}

function parseAnswerMetrics(value: Record<string, unknown>): AnswerMetrics {
  return {
    em: requireRate(value, 'em'),
    f1: requireRate(value, 'f1'),
    joint_f1: requireRate(value, 'joint_f1'),
  }
}

function parseQualityMetrics(value: Record<string, unknown>): QualityMetrics {
  return {
    faithfulness: requireRate(value, 'faithfulness'),
    context_precision: requireRate(value, 'context_precision'),
    context_recall: requireRate(value, 'context_recall'),
    hallucination_rate_judged: requireRate(value, 'hallucination_rate_judged'),
    abstention_rate: requireRate(value, 'abstention_rate'),
  }
}

function parseLatencyMs(value: Record<string, unknown>): LatencyMs {
  return {
    p50: requireNonNegativeNumber(value, 'p50'),
    p95: requireNonNegativeNumber(value, 'p95'),
  }
}

function parseModelSet(value: Record<string, unknown>): ModelSet {
  return {
    embedder: requireString(value, 'embedder'),
    reranker: requireString(value, 'reranker'),
    reasoning_llm: requireNullableString(value, 'reasoning_llm'),
    verifier: requireNullableString(value, 'verifier'),
  }
}

function parseNullableRecord<T>(
  value: unknown,
  fieldName: string,
  parser: (record: Record<string, unknown>) => T,
): T | null {
  if (value === null) {
    return null
  }

  return parser(requireRecord(value, fieldName))
}

function requireRecord(value: unknown, fieldName: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid scoreboard payload: ${fieldName} must be an object`)
  }

  return value
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function requireString(record: Record<string, unknown>, fieldName: string): string {
  const value = record[fieldName]

  if (typeof value !== 'string') {
    throw new Error(`Invalid scoreboard payload: ${fieldName} must be a string`)
  }

  return value
}

function requireNullableString(
  record: Record<string, unknown>,
  fieldName: string,
): string | null {
  const value = record[fieldName]

  if (value === null) {
    return null
  }

  if (typeof value !== 'string') {
    throw new Error(
      `Invalid scoreboard payload: ${fieldName} must be a string or null`,
    )
  }

  return value
}

function requireRate(record: Record<string, unknown>, fieldName: string): number {
  const value = requireNumber(record, fieldName)

  if (value < 0 || value > 1) {
    throw new Error(`Invalid scoreboard payload: ${fieldName} must be between 0 and 1`)
  }

  return value
}

function requireNonNegativeNumber(
  record: Record<string, unknown>,
  fieldName: string,
): number {
  const value = requireNumber(record, fieldName)

  if (value < 0) {
    throw new Error(`Invalid scoreboard payload: ${fieldName} must be non-negative`)
  }

  return value
}

function requireNumber(record: Record<string, unknown>, fieldName: string): number {
  const value = record[fieldName]

  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid scoreboard payload: ${fieldName} must be a finite number`)
  }

  return value
}
