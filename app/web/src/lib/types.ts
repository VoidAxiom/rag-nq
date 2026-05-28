export interface Scoreboard {
  schema_version: 1
  generated_at: string
  rows: ScoreboardRow[]
}

export interface ScoreboardRow {
  phase: string
  pipeline: string
  benchmark: string
  split: string
  retriever_metrics: RetrieverMetrics
  answer_metrics: AnswerMetrics | null
  quality_metrics: QualityMetrics | null
  latency_ms: LatencyMs
  models: ModelSet
  commit_sha: string
  notes: string | null
}

export interface RetrieverMetrics {
  recall_at_1: number
  recall_at_5: number
  recall_at_10: number
  mrr_at_10: number
  ndcg_at_10: number
}

export interface AnswerMetrics {
  em: number
  f1: number
  joint_f1: number
}

export interface QualityMetrics {
  faithfulness: number
  context_precision: number
  context_recall: number
  hallucination_rate_judged: number
  abstention_rate: number
}

export interface LatencyMs {
  p50: number
  p95: number
}

export interface ModelSet {
  embedder: string
  reranker: string
  reasoning_llm: string | null
  verifier: string | null
}

export type RetrievalMode = 'dense' | 'sparse' | 'hybrid'

export interface ComponentChoice {
  name: string
  label: string
  enabled?: boolean
  disabled_reason?: string | null
}

export interface CollectionChoice {
  benchmark: string
  collection: string
}

export interface ComponentsResponse {
  modes: RetrievalMode[]
  top_k_choices: number[]
  rerankers: ComponentChoice[]
  generators: ComponentChoice[]
  collections: CollectionChoice[]
  openai_enabled: boolean
  embedder: string
}

export interface EvalQuestion {
  query_id: string
  query: string
  gold_answers: string[]
  supporting_passage_ids: string[]
  notes?: string | null
}

export interface EvalQuestionsResponse {
  benchmark: string
  questions: EvalQuestion[]
}

export interface PerQueryMetrics {
  em: number | null
  f1: number | null
  supporting_fact_recall_at_k: number | null
  k_used: number | null
}

export interface ComponentSet {
  mode: RetrievalMode
  top_k: number
  reranker: string
  generator: string
  embedder: string
  collection: string
}

export interface LatencyBreakdown {
  retrieval_ms: number
  rerank_ms: number
  generation_ms: number
  total_ms: number
}

export interface PassageHit {
  point_id: string
  text: string
  context_text?: string | null
  title?: string | null
  document_url?: string | null
  dense_rank?: number | null
  sparse_rank?: number | null
  fusion_rank?: number | null
  rerank_rank?: number | null
  dense_score?: number | null
  sparse_score?: number | null
  rerank_score?: number | null
}

export interface Citation {
  point_id: string
}

export interface GroundedAnswer {
  answer: string
  citations: Citation[]
  abstained: boolean
  abstention_reason?: string | null
  supporting_point_ids: string[]
}

export interface QueryRequest {
  query: string
  top_k: number
  mode: RetrievalMode
  generate: boolean
  collection?: string | null
  overrides?: Record<string, unknown> | null
  gold_answers?: string[] | null
  supporting_passage_ids?: string[] | null
  query_id?: string | null
}

export interface QueryResponse {
  query: string
  retrieved_passages: PassageHit[] | null
  grounded: GroundedAnswer | null
  metrics: PerQueryMetrics | null
  components_used: ComponentSet | null
  latency_ms: LatencyBreakdown | null
  query_id: string | null
}
