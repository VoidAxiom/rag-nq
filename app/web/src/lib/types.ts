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
