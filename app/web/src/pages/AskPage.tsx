import { useMutation, useQuery } from '@tanstack/react-query'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'
import { useSearchParams } from 'react-router'

import { AnswerPanel } from '@/components/ask/AnswerPanel'
import { AskSidebar } from '@/components/ask/AskSidebar'
import { GeneratorKnobs } from '@/components/ask/GeneratorKnobs'
import { PipelineBridge } from '@/components/ask/PipelineBridge'
import { PipelineStage } from '@/components/ask/PipelineStage'
import { PipelineTotal } from '@/components/ask/PipelineTotal'
import { RerankerKnobs } from '@/components/ask/RerankerKnobs'
import { RetrieverKnobs } from '@/components/ask/RetrieverKnobs'
import { fetchComponents, postQuery } from '@/lib/api'
import {
  runPipelineAnimation,
  type BridgeState,
  type StepState,
} from '@/lib/pipelineAnimation'
import type {
  CollectionChoice,
  ComponentsResponse,
  EvalQuestion,
  QueryResponse,
  RetrievalMode,
} from '@/lib/types'

interface AskSearchState {
  mode: RetrievalMode
  topK: number
  reranker: string
  generator: string
  collection: string
  qId: string | null
}

type SearchUpdate = Partial<{
  mode: RetrievalMode
  top_k: number
  reranker: string
  generator: string
  collection: string
  q_id: string | null
}>

interface PipelineUiState {
  retriever: StepState
  reranker: StepState
  generator: StepState
  retrieverMs: number | null
  rerankerMs: number | null
  generatorMs: number | null
  bridge0: BridgeState
  bridge1: BridgeState
  totalState: 'idle' | 'running' | 'complete'
  totalMs: number | null
}

const INITIAL_PIPELINE_STATE: PipelineUiState = {
  retriever: 'pending',
  reranker: 'pending',
  generator: 'pending',
  retrieverMs: null,
  rerankerMs: null,
  generatorMs: null,
  bridge0: 'idle',
  bridge1: 'idle',
  totalState: 'idle',
  totalMs: null,
}

export function AskPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [freeText, setFreeText] = useState('')
  const [selectedQuestion, setSelectedQuestion] = useState<EvalQuestion | null>(null)
  const componentsQuery = useQuery({
    queryKey: ['components'],
    queryFn: fetchComponents,
  })
  const queryMutation = useMutation({
    mutationFn: postQuery,
  })

  if (componentsQuery.isLoading) {
    return (
      <PageFrame>
        <div role="status" aria-busy="true" aria-label="Loading RAG explorer">
          Loading explorer…
        </div>
      </PageFrame>
    )
  }
  if (componentsQuery.isError || componentsQuery.data === undefined) {
    const message =
      componentsQuery.error instanceof Error
        ? componentsQuery.error.message
        : 'Failed to load explorer components.'
    return (
      <PageFrame>
        <p role="alert" className="theme-error">
          {message}
        </p>
      </PageFrame>
    )
  }

  return (
    <AskPageContent
      components={componentsQuery.data}
      freeText={freeText}
      onFreeTextChange={setFreeText}
      selectedQuestion={selectedQuestion}
      onSelectedQuestionChange={setSelectedQuestion}
      searchParams={searchParams}
      setSearchParams={setSearchParams}
      queryMutation={queryMutation}
    />
  )
}

interface AskPageContentProps {
  components: ComponentsResponse
  freeText: string
  onFreeTextChange: (text: string) => void
  selectedQuestion: EvalQuestion | null
  onSelectedQuestionChange: (question: EvalQuestion | null) => void
  searchParams: URLSearchParams
  setSearchParams: ReturnType<typeof useSearchParams>[1]
  queryMutation: ReturnType<typeof useMutation<QueryResponse, Error, Parameters<typeof postQuery>[0]>>
}

function AskPageContent({
  components,
  freeText,
  onFreeTextChange,
  selectedQuestion,
  onSelectedQuestionChange,
  searchParams,
  setSearchParams,
  queryMutation,
}: AskPageContentProps) {
  const searchState = useMemo(
    () => readAskSearchState(searchParams, components),
    [components, searchParams],
  )
  const selectedCollection = findCollection(components.collections, searchState.collection)
  const derivedBenchmark =
    selectedCollection?.benchmark ?? components.collections[0]?.benchmark ?? ''

  useEffect(() => {
    const normalized = searchStateToParams(searchState, searchParams)
    if (normalized.toString() !== searchParams.toString()) {
      setSearchParams(normalized, { replace: true, preventScrollReset: true })
    }
  }, [searchParams, searchState, setSearchParams])

  useEffect(() => {
    if (searchState.qId === null) {
      onSelectedQuestionChange(null)
      return
    }
    if (selectedQuestion !== null && selectedQuestion.query_id !== searchState.qId) {
      onSelectedQuestionChange(null)
    }
  }, [onSelectedQuestionChange, searchState.qId, selectedQuestion])

  const updateSearch = useCallback(
    (updates: SearchUpdate) => {
      const next = new URLSearchParams(searchParams)
      if (updates.mode !== undefined) next.set('mode', updates.mode)
      if (updates.top_k !== undefined) next.set('top_k', String(updates.top_k))
      if (updates.reranker !== undefined) next.set('reranker', updates.reranker)
      if (updates.generator !== undefined) next.set('generator', updates.generator)
      if (updates.collection !== undefined) next.set('collection', updates.collection)
      if (updates.q_id !== undefined) {
        if (updates.q_id === null) next.delete('q_id')
        else next.set('q_id', updates.q_id)
      }
      setSearchParams(next, { replace: true, preventScrollReset: true })
    },
    [searchParams, setSearchParams],
  )

  const handlePickQuestion = useCallback(
    (question: EvalQuestion | null) => {
      onSelectedQuestionChange(question)
      const nextId = question?.query_id ?? null
      if (nextId !== searchState.qId) {
        updateSearch({ q_id: nextId })
      }
    },
    [onSelectedQuestionChange, searchState.qId, updateSearch],
  )

  const activeQuestion =
    searchState.qId !== null && selectedQuestion?.query_id === searchState.qId
      ? selectedQuestion
      : null
  const queryText =
    activeQuestion !== null
      ? activeQuestion.query
      : searchState.qId === null
        ? freeText
        : ''
  const trimmedQuery = queryText.trim()

  const [pipeline, setPipeline] = useState<PipelineUiState>(INITIAL_PIPELINE_STATE)
  const inFlightTokenRef = useRef<number>(0)

  // Whenever a new query lands, snap remaining ms to real values. The animation
  // scheduler handles step pacing; here we just expose final state on settle.
  const { isPending, data: queryData, error: queryError } = queryMutation
  const reveal = pipeline.generator === 'complete' && queryData?.grounded != null

  const handleSubmit = useCallback(
    (event?: FormEvent<HTMLFormElement>) => {
      if (event !== undefined) {
        event.preventDefault()
      }
      if (trimmedQuery === '' || isPending) {
        return
      }
      const myToken = inFlightTokenRef.current + 1
      inFlightTokenRef.current = myToken
      setPipeline({
        ...INITIAL_PIPELINE_STATE,
        totalState: 'running',
        totalMs: 0,
      })

      // Real timings arrive when the mutation resolves; we expose them via a
      // standalone promise so the scheduler can clamp pacing.
      let resolveReal: (t: { retriever: number; reranker: number; generator: number }) => void
      let rejectReal: (err: Error) => void
      const realPromise = new Promise<{ retriever: number; reranker: number; generator: number }>(
        (res, rej) => {
          resolveReal = res
          rejectReal = rej
        },
      )

      const mutationPromise = queryMutation.mutateAsync({
        query: activeQuestion?.query ?? trimmedQuery,
        top_k: searchState.topK,
        mode: searchState.mode,
        generate: true,
        collection: searchState.collection,
        overrides: buildOverrides(searchState.reranker, searchState.generator),
        gold_answers:
          activeQuestion !== null && activeQuestion.gold_answers.length > 0
            ? activeQuestion.gold_answers
            : null,
        supporting_passage_ids:
          activeQuestion !== null && activeQuestion.supporting_passage_ids.length > 0
            ? activeQuestion.supporting_passage_ids
            : null,
        query_id: activeQuestion?.query_id ?? null,
      })
      mutationPromise
        .then((response) => {
          if (inFlightTokenRef.current !== myToken) return
          const latency = response.latency_ms
          resolveReal({
            retriever: latency?.retrieval_ms ?? 0,
            reranker: latency?.rerank_ms ?? 0,
            generator: latency?.generation_ms ?? 0,
          })
        })
        .catch((err: unknown) => {
          if (inFlightTokenRef.current !== myToken) return
          rejectReal(err instanceof Error ? err : new Error(String(err)))
        })

      runPipelineAnimation({
        realTimings: realPromise,
        callbacks: {
          onStepState(step, state) {
            if (inFlightTokenRef.current !== myToken) return
            setPipeline((current) => ({ ...current, [step]: state }))
          },
          onStepMs(step, ms) {
            if (inFlightTokenRef.current !== myToken) return
            setPipeline((current) => ({
              ...current,
              [`${step}Ms`]: ms,
            }))
          },
          onBridgeState(idx, state) {
            if (inFlightTokenRef.current !== myToken) return
            setPipeline((current) => ({
              ...current,
              [`bridge${idx}`]: state,
            }))
          },
          onTotalMs(ms) {
            if (inFlightTokenRef.current !== myToken) return
            setPipeline((current) => ({ ...current, totalMs: ms }))
          },
        },
      })
        .then(() => {
          if (inFlightTokenRef.current !== myToken) return
          setPipeline((current) => ({ ...current, totalState: 'complete' }))
        })
        .catch(() => {
          if (inFlightTokenRef.current !== myToken) return
          setPipeline((current) => ({ ...current, totalState: 'idle' }))
        })
    },
    [activeQuestion, isPending, queryMutation, searchState, trimmedQuery],
  )

  const canSubmit = trimmedQuery.length > 0 && !isPending
  const mutationErrorMessage =
    queryError instanceof Error ? queryError.message : null

  function handleCollectionChange(collection: string): void {
    onSelectedQuestionChange(null)
    updateSearch({ collection, q_id: null })
  }

  return (
    <PageFrame>
      <form
        className="theme-query-bar"
        onSubmit={handleSubmit}
        aria-label="Query form"
      >
        <input
          className="theme-query-bar__input"
          type="text"
          placeholder="Ask anything…"
          value={queryText}
          onChange={(event) => onFreeTextChange(event.target.value)}
          disabled={activeQuestion !== null}
          aria-label="Question"
        />
        <button
          type="submit"
          className="theme-query-bar__submit"
          disabled={!canSubmit}
        >
          Ask
        </button>
      </form>

      {mutationErrorMessage !== null ? (
        <p role="alert" className="theme-error">
          {mutationErrorMessage}
        </p>
      ) : null}

      <div className="theme-grid theme-grid--ask">
        <div>
          <div className="pipeline" aria-label="Pipeline">
            <PipelineTotal state={pipeline.totalState} totalMs={pipeline.totalMs} />
            <div className="steps">
              <PipelineStage
                name="Retriever"
                accent={1}
                state={pipeline.retriever}
                ms={pipeline.retrieverMs}
              >
                <RetrieverKnobs
                  modes={components.modes}
                  mode={searchState.mode}
                  onModeChange={(mode) => updateSearch({ mode })}
                  topKChoices={components.top_k_choices}
                  topK={searchState.topK}
                  onTopKChange={(topK) => updateSearch({ top_k: topK })}
                  collection={searchState.collection}
                  collections={components.collections}
                  onCollectionChange={handleCollectionChange}
                />
              </PipelineStage>
              <PipelineBridge accent={1} state={pipeline.bridge0} />
              <PipelineStage
                name="Reranker"
                accent={2}
                state={pipeline.reranker}
                ms={pipeline.rerankerMs}
              >
                <RerankerKnobs
                  choices={components.rerankers}
                  value={searchState.reranker}
                  onChange={(reranker) => updateSearch({ reranker })}
                />
              </PipelineStage>
              <PipelineBridge accent={2} state={pipeline.bridge1} />
              <PipelineStage
                name="Generator"
                accent={3}
                state={pipeline.generator}
                ms={pipeline.generatorMs}
              >
                <GeneratorKnobs
                  choices={components.generators}
                  value={searchState.generator}
                  onChange={(generator) => updateSearch({ generator })}
                />
              </PipelineStage>
            </div>
          </div>

          <AnswerPanel
            grounded={queryData?.grounded ?? null}
            reveal={reveal}
          />
        </div>

        <AskSidebar
          benchmark={derivedBenchmark}
          questionId={searchState.qId}
          onPickQuestion={handlePickQuestion}
          onFreeText={onFreeTextChange}
          passages={queryData?.retrieved_passages ?? null}
          isLoading={isPending}
          supportingIds={activeQuestion?.supporting_passage_ids}
          metrics={queryData?.metrics ?? null}
        />
      </div>
    </PageFrame>
  )
}

function PageFrame({ children }: { children: ReactNode }) {
  return <div className="theme-page">{children}</div>
}

function readAskSearchState(
  searchParams: URLSearchParams,
  components: ComponentsResponse,
): AskSearchState {
  const modeParam = searchParams.get('mode')
  const topKParam = searchParams.get('top_k')
  const rerankerParam = searchParams.get('reranker')
  const generatorParam = searchParams.get('generator')
  const collectionParam = searchParams.get('collection')
  const qIdParam = searchParams.get('q_id')
  const defaultMode = defaultRetrievalMode(components)
  const parsedTopK = topKParam === null ? NaN : Number(topKParam)

  return {
    mode:
      modeParam !== null &&
      isRetrievalMode(modeParam) &&
      components.modes.includes(modeParam)
        ? modeParam
        : defaultMode,
    topK:
      Number.isInteger(parsedTopK) &&
      components.top_k_choices.includes(parsedTopK)
        ? parsedTopK
        : defaultTopK(components),
    reranker:
      rerankerParam !== null &&
      components.rerankers.some((choice) => choice.name === rerankerParam)
        ? rerankerParam
        : components.rerankers[0]?.name ?? 'off',
    generator:
      generatorParam !== null &&
      components.generators.some(
        (choice) => choice.name === generatorParam && choice.enabled !== false,
      )
        ? generatorParam
        : components.generators.find((choice) => choice.enabled !== false)?.name ??
          'heuristic',
    collection:
      collectionParam !== null &&
      components.collections.some((choice) => choice.collection === collectionParam)
        ? collectionParam
        : components.collections[0]?.collection ?? '',
    qId: qIdParam === null || qIdParam.trim() === '' ? null : qIdParam,
  }
}

function searchStateToParams(
  state: AskSearchState,
  current: URLSearchParams,
): URLSearchParams {
  // Start from the current params so unrelated keys (e.g. style/palette from a
  // shared URL) survive the Ask-state normalization round trip.
  const params = new URLSearchParams(current)
  params.set('mode', state.mode)
  params.set('top_k', String(state.topK))
  params.set('reranker', state.reranker)
  params.set('generator', state.generator)
  if (state.collection !== '') params.set('collection', state.collection)
  else params.delete('collection')
  if (state.qId !== null) params.set('q_id', state.qId)
  else params.delete('q_id')
  return params
}

function defaultRetrievalMode(components: ComponentsResponse): RetrievalMode {
  if (components.modes.includes('hybrid')) return 'hybrid'
  return components.modes[0] ?? 'hybrid'
}

function defaultTopK(components: ComponentsResponse): number {
  if (components.top_k_choices.includes(10)) return 10
  return components.top_k_choices[0] ?? 10
}

function isRetrievalMode(value: string): value is RetrievalMode {
  return value === 'dense' || value === 'sparse' || value === 'hybrid'
}

function findCollection(
  collections: CollectionChoice[],
  collectionName: string,
): CollectionChoice | undefined {
  return collections.find((choice) => choice.collection === collectionName)
}

function buildOverrides(reranker: string, generator: string): Record<string, unknown> {
  const overrides: Record<string, unknown> =
    reranker === 'off'
      ? { rerank_enabled: false }
      : { rerank_enabled: true, rerank_model_name: reranker }
  overrides.generation_provider = generator
  return overrides
}
