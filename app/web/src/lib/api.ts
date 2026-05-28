import type {
  AnswerMetrics,
  Citation,
  CollectionChoice,
  ComponentChoice,
  ComponentSet,
  ComponentsResponse,
  EvalQuestion,
  EvalQuestionsResponse,
  GroundedAnswer,
  LatencyBreakdown,
  LatencyMs,
  ModelSet,
  PassageHit,
  PerQueryMetrics,
  QualityMetrics,
  QueryRequest,
  QueryResponse,
  RetrievalMode,
  RetrieverMetrics,
  Scoreboard,
  ScoreboardRow,
} from '@/lib/types'

const scoreboardPath = '/api/scoreboard'
const componentsPath = '/api/components'
const evalQuestionsPathPrefix = '/api/eval_questions'
const queryPath = '/query'

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

export async function fetchComponents(): Promise<ComponentsResponse> {
  const response = await fetch(apiBaseUrl(componentsPath))

  if (!response.ok) {
    throw new Error(await buildFailureMessage(response, 'Failed to fetch components'))
  }

  const payload: unknown = await response.json()
  return parseComponentsResponse(payload)
}

export async function fetchEvalQuestions(
  benchmark: string,
): Promise<EvalQuestionsResponse> {
  const endpoint = apiBaseUrl(
    `${evalQuestionsPathPrefix}/${encodeURIComponent(benchmark)}`,
  )
  const response = await fetch(endpoint)

  if (!response.ok) {
    const detail = await readErrorDetail(response)

    if (response.status === 503 && detail !== '') {
      throw new Error(detail)
    }

    throw new Error(formatFailureMessage(response, 'Failed to fetch eval questions', detail))
  }

  const payload: unknown = await response.json()
  return parseEvalQuestionsResponse(payload)
}

export async function postQuery(req: QueryRequest): Promise<QueryResponse> {
  const response = await fetch(apiBaseUrl(queryPath), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(req),
  })

  if (!response.ok) {
    const detail = await readErrorDetail(response)

    if (response.status === 422 && detail !== '') {
      throw new Error(detail)
    }

    throw new Error(formatFailureMessage(response, 'Failed to run query', detail))
  }

  const payload: unknown = await response.json()
  return parseQueryResponse(payload)
}

function scoreboardEndpoint(): string {
  return apiBaseUrl(scoreboardPath)
}

function apiBaseUrl(path: string): string {
  const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? '').trim()

  if (baseUrl === '') {
    return path
  }

  return `${baseUrl.replace(/\/+$/, '')}${path}`
}

async function readErrorBody(response: Response): Promise<string> {
  try {
    return (await response.text()).trim()
  } catch {
    return ''
  }
}

async function readErrorDetail(response: Response): Promise<string> {
  const body = await readErrorBody(response)

  if (body === '') {
    return ''
  }

  try {
    const payload: unknown = JSON.parse(body)

    if (isRecord(payload) && 'detail' in payload) {
      const detail = payload.detail

      if (typeof detail === 'string') {
        return detail
      }

      return JSON.stringify(detail)
    }
  } catch {
    return body
  }

  return body
}

async function buildFailureMessage(
  response: Response,
  prefix: string,
): Promise<string> {
  return formatFailureMessage(response, prefix, await readErrorDetail(response))
}

function formatFailureMessage(response: Response, prefix: string, detail: string): string {
  const statusText = response.statusText.trim()
  const status = statusText ? `${response.status} ${statusText}` : `${response.status}`
  const detailSuffix = detail === '' ? '' : `: ${detail}`

  return `${prefix} (${status})${detailSuffix}`
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

function parseComponentsResponse(value: unknown): ComponentsResponse {
  const response = requireApiRecord(value, 'components response')

  return {
    modes: requireArray(response, 'modes').map(parseRetrievalMode),
    top_k_choices: requireArray(response, 'top_k_choices').map((item) =>
      parsePositiveInteger(item, 'top_k_choices item'),
    ),
    rerankers: requireArray(response, 'rerankers').map(parseComponentChoice),
    generators: requireArray(response, 'generators').map(parseComponentChoice),
    collections: requireArray(response, 'collections').map(parseCollectionChoice),
    openai_enabled: requireBoolean(response, 'openai_enabled'),
    embedder: requireApiString(response, 'embedder'),
  }
}

function parseEvalQuestionsResponse(value: unknown): EvalQuestionsResponse {
  const response = requireApiRecord(value, 'eval questions response')

  return {
    benchmark: requireApiString(response, 'benchmark'),
    questions: requireArray(response, 'questions').map(parseEvalQuestion),
  }
}

function parseQueryResponse(value: unknown): QueryResponse {
  const response = requireApiRecord(value, 'query response')

  return {
    query: requireApiString(response, 'query'),
    retrieved_passages: parseNullableApiArray(
      response.retrieved_passages,
      'retrieved_passages',
      parsePassageHit,
    ),
    grounded: parseNullableApiRecord(response.grounded, 'grounded', parseGroundedAnswer),
    metrics: parseNullableApiRecord(response.metrics, 'metrics', parsePerQueryMetrics),
    components_used: parseNullableApiRecord(
      response.components_used,
      'components_used',
      parseComponentSet,
    ),
    latency_ms: parseNullableApiRecord(
      response.latency_ms,
      'latency_ms',
      parseLatencyBreakdown,
    ),
    query_id: requireApiNullableString(response, 'query_id'),
  }
}

function parseRetrievalMode(value: unknown): RetrievalMode {
  if (value === 'dense' || value === 'sparse' || value === 'hybrid') {
    return value
  }

  throw new Error('Invalid API payload: retrieval mode is invalid')
}

function parseComponentChoice(value: unknown): ComponentChoice {
  const choice = requireApiRecord(value, 'component choice')
  const parsed: ComponentChoice = {
    name: requireApiString(choice, 'name'),
    label: requireApiString(choice, 'label'),
  }
  const enabled = choice.enabled
  const disabledReason = choice.disabled_reason

  if (enabled !== undefined) {
    parsed.enabled = requireBoolean(choice, 'enabled')
  }

  if (disabledReason !== undefined) {
    parsed.disabled_reason = requireApiNullableString(choice, 'disabled_reason')
  }

  return parsed
}

function parseCollectionChoice(value: unknown): CollectionChoice {
  const choice = requireApiRecord(value, 'collection choice')

  return {
    benchmark: requireApiString(choice, 'benchmark'),
    collection: requireApiString(choice, 'collection'),
  }
}

function parseEvalQuestion(value: unknown): EvalQuestion {
  const question = requireApiRecord(value, 'eval question')
  const parsed: EvalQuestion = {
    query_id: requireApiString(question, 'query_id'),
    query: requireApiString(question, 'query'),
    gold_answers: requireStringArray(question, 'gold_answers'),
    supporting_passage_ids: requireStringArray(question, 'supporting_passage_ids'),
  }
  const notes = question.notes

  if (notes !== undefined) {
    parsed.notes = requireApiNullableString(question, 'notes')
  }

  return parsed
}

function parsePerQueryMetrics(value: Record<string, unknown>): PerQueryMetrics {
  return {
    em: requireNullableRate(value, 'em'),
    f1: requireNullableRate(value, 'f1'),
    supporting_fact_recall_at_k: requireNullableRate(
      value,
      'supporting_fact_recall_at_k',
    ),
    k_used: requireNullableNonNegativeNumber(value, 'k_used'),
  }
}

function parseComponentSet(value: Record<string, unknown>): ComponentSet {
  return {
    mode: parseRetrievalMode(value.mode),
    top_k: parsePositiveInteger(value.top_k, 'top_k'),
    reranker: requireApiString(value, 'reranker'),
    generator: requireApiString(value, 'generator'),
    embedder: requireApiString(value, 'embedder'),
    collection: requireApiString(value, 'collection'),
  }
}

function parseLatencyBreakdown(value: Record<string, unknown>): LatencyBreakdown {
  return {
    retrieval_ms: requireApiNonNegativeNumber(value, 'retrieval_ms'),
    rerank_ms: requireApiNonNegativeNumber(value, 'rerank_ms'),
    generation_ms: requireApiNonNegativeNumber(value, 'generation_ms'),
    total_ms: requireApiNonNegativeNumber(value, 'total_ms'),
  }
}

function parsePassageHit(value: unknown): PassageHit {
  const passage = requireApiRecord(value, 'passage hit')

  return {
    point_id: requireApiString(passage, 'point_id'),
    text: requireApiString(passage, 'text'),
    context_text: optionalNullableString(passage, 'context_text'),
    title: optionalNullableString(passage, 'title'),
    document_url: optionalNullableString(passage, 'document_url'),
    dense_rank: optionalNullableNumber(passage, 'dense_rank'),
    sparse_rank: optionalNullableNumber(passage, 'sparse_rank'),
    fusion_rank: optionalNullableNumber(passage, 'fusion_rank'),
    rerank_rank: optionalNullableNumber(passage, 'rerank_rank'),
    dense_score: optionalNullableNumber(passage, 'dense_score'),
    sparse_score: optionalNullableNumber(passage, 'sparse_score'),
    rerank_score: optionalNullableNumber(passage, 'rerank_score'),
  }
}

function parseCitation(value: unknown): Citation {
  const citation = requireApiRecord(value, 'citation')

  return {
    point_id: requireApiString(citation, 'point_id'),
  }
}

function parseGroundedAnswer(value: Record<string, unknown>): GroundedAnswer {
  const parsed: GroundedAnswer = {
    answer: requireApiString(value, 'answer'),
    citations: requireArray(value, 'citations').map(parseCitation),
    abstained: requireBoolean(value, 'abstained'),
    supporting_point_ids: requireStringArray(value, 'supporting_point_ids'),
  }
  const reason = value.abstention_reason

  if (reason !== undefined) {
    parsed.abstention_reason = requireApiNullableString(value, 'abstention_reason')
  }

  return parsed
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

function requireApiRecord(value: unknown, fieldName: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid API payload: ${fieldName} must be an object`)
  }

  return value
}

function requireArray(record: Record<string, unknown>, fieldName: string): unknown[] {
  const value = record[fieldName]

  if (!Array.isArray(value)) {
    throw new Error(`Invalid API payload: ${fieldName} must be an array`)
  }

  return value
}

function parseNullableApiArray<T>(
  value: unknown,
  fieldName: string,
  parser: (item: unknown) => T,
): T[] | null {
  if (value === null) {
    return null
  }

  if (!Array.isArray(value)) {
    throw new Error(`Invalid API payload: ${fieldName} must be an array or null`)
  }

  return value.map(parser)
}

function parseNullableApiRecord<T>(
  value: unknown,
  fieldName: string,
  parser: (record: Record<string, unknown>) => T,
): T | null {
  if (value === null) {
    return null
  }

  return parser(requireApiRecord(value, fieldName))
}

function requireApiString(record: Record<string, unknown>, fieldName: string): string {
  const value = record[fieldName]

  if (typeof value !== 'string') {
    throw new Error(`Invalid API payload: ${fieldName} must be a string`)
  }

  return value
}

function requireApiNullableString(
  record: Record<string, unknown>,
  fieldName: string,
): string | null {
  const value = record[fieldName]

  if (value === null) {
    return null
  }

  if (typeof value !== 'string') {
    throw new Error(`Invalid API payload: ${fieldName} must be a string or null`)
  }

  return value
}

function optionalNullableString(
  record: Record<string, unknown>,
  fieldName: string,
): string | null | undefined {
  if (record[fieldName] === undefined) {
    return undefined
  }

  return requireApiNullableString(record, fieldName)
}

function requireStringArray(
  record: Record<string, unknown>,
  fieldName: string,
): string[] {
  return requireArray(record, fieldName).map((item) => {
    if (typeof item !== 'string') {
      throw new Error(`Invalid API payload: ${fieldName} items must be strings`)
    }

    return item
  })
}

function requireBoolean(record: Record<string, unknown>, fieldName: string): boolean {
  const value = record[fieldName]

  if (typeof value !== 'boolean') {
    throw new Error(`Invalid API payload: ${fieldName} must be a boolean`)
  }

  return value
}

function parsePositiveInteger(value: unknown, fieldName: string): number {
  if (
    typeof value !== 'number' ||
    !Number.isInteger(value) ||
    !Number.isFinite(value) ||
    value <= 0
  ) {
    throw new Error(`Invalid API payload: ${fieldName} must be a positive integer`)
  }

  return value
}

function requireNullableRate(
  record: Record<string, unknown>,
  fieldName: string,
): number | null {
  const value = record[fieldName]

  if (value === null) {
    return null
  }

  const number = requireApiNumber(record, fieldName)

  if (number < 0 || number > 1) {
    throw new Error(`Invalid API payload: ${fieldName} must be between 0 and 1`)
  }

  return number
}

function requireNullableNonNegativeNumber(
  record: Record<string, unknown>,
  fieldName: string,
): number | null {
  const value = record[fieldName]

  if (value === null) {
    return null
  }

  return requireApiNonNegativeNumber(record, fieldName)
}

function requireApiNonNegativeNumber(
  record: Record<string, unknown>,
  fieldName: string,
): number {
  const value = requireApiNumber(record, fieldName)

  if (value < 0) {
    throw new Error(`Invalid API payload: ${fieldName} must be non-negative`)
  }

  return value
}

function optionalNullableNumber(
  record: Record<string, unknown>,
  fieldName: string,
): number | null | undefined {
  if (record[fieldName] === undefined) {
    return undefined
  }

  const value = record[fieldName]

  if (value === null) {
    return null
  }

  return requireApiNumber(record, fieldName)
}

function requireApiNumber(record: Record<string, unknown>, fieldName: string): number {
  const value = record[fieldName]

  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(`Invalid API payload: ${fieldName} must be a finite number`)
  }

  return value
}
