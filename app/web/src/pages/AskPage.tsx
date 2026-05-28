import {
  useMutation,
  useQuery,
  type UseMutationResult,
} from '@tanstack/react-query'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type MutableRefObject,
  type ReactNode,
} from 'react'
import { Link, useSearchParams } from 'react-router'

import { AnswerCard } from '@/components/AnswerCard'
import { CollectionSelector } from '@/components/CollectionSelector'
import { EvalQuestionPicker } from '@/components/EvalQuestionPicker'
import { MetricsCard } from '@/components/MetricsCard'
import { PipelineKnobs } from '@/components/PipelineKnobs'
import { RetrievedPassageList } from '@/components/RetrievedPassageList'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { TooltipProvider } from '@/components/ui/tooltip'
import { fetchComponents, postQuery } from '@/lib/api'
import type {
  CollectionChoice,
  ComponentsResponse,
  EvalQuestion,
  QueryRequest,
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

export function AskPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [freeText, setFreeText] = useState('')
  const [selectedQuestion, setSelectedQuestion] = useState<EvalQuestion | null>(null)
  const [rerankerAwaitingFirstQuery, setRerankerAwaitingFirstQuery] = useState(false)
  const previousRerankerRef = useRef<string | null>(null)
  const componentsQuery = useQuery({
    queryKey: ['components'],
    queryFn: fetchComponents,
  })
  const queryMutation = useMutation({
    mutationFn: postQuery,
    onSettled: () => {
      setRerankerAwaitingFirstQuery(false)
    },
  })

  if (componentsQuery.isLoading) {
    return (
      <PageFrame>
        <div
          role="status"
          aria-busy="true"
          aria-label="Loading RAG explorer"
          className="mx-auto grid w-full max-w-3xl gap-4 py-16"
        >
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-24 w-full" />
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
        <StateCard title="Unable to load RAG explorer" message={message} />
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
      rerankerAwaitingFirstQuery={rerankerAwaitingFirstQuery}
      onRerankerAwaitingFirstQueryChange={setRerankerAwaitingFirstQuery}
      previousRerankerRef={previousRerankerRef}
      queryMutation={queryMutation}
      searchParams={searchParams}
      setSearchParams={setSearchParams}
    />
  )
}

function AskPageContent({
  components,
  freeText,
  onFreeTextChange,
  selectedQuestion,
  onSelectedQuestionChange,
  rerankerAwaitingFirstQuery,
  onRerankerAwaitingFirstQueryChange,
  previousRerankerRef,
  queryMutation,
  searchParams,
  setSearchParams,
}: {
  components: ComponentsResponse
  freeText: string
  onFreeTextChange: (text: string) => void
  selectedQuestion: EvalQuestion | null
  onSelectedQuestionChange: (question: EvalQuestion | null) => void
  rerankerAwaitingFirstQuery: boolean
  onRerankerAwaitingFirstQueryChange: (value: boolean) => void
  previousRerankerRef: MutableRefObject<string | null>
  queryMutation: UseMutationResult<QueryResponse, Error, QueryRequest>
  searchParams: URLSearchParams
  setSearchParams: ReturnType<typeof useSearchParams>[1]
}) {
  const searchState = useMemo(
    () => readAskSearchState(searchParams, components),
    [components, searchParams],
  )
  const selectedCollection = findCollection(components.collections, searchState.collection)
  const derivedBenchmark = selectedCollection?.benchmark ?? components.collections[0]?.benchmark ?? ''

  useEffect(() => {
    const normalized = searchStateToParams(searchState)

    if (normalized.toString() !== searchParams.toString()) {
      setSearchParams(normalized, {
        replace: true,
        preventScrollReset: true,
      })
    }
  }, [searchParams, searchState, setSearchParams])

  useEffect(() => {
    if (previousRerankerRef.current === null) {
      previousRerankerRef.current = searchState.reranker
      return
    }

    if (previousRerankerRef.current !== searchState.reranker) {
      previousRerankerRef.current = searchState.reranker
      onRerankerAwaitingFirstQueryChange(searchState.reranker !== 'off')
    }
  }, [
    onRerankerAwaitingFirstQueryChange,
    previousRerankerRef,
    searchState.reranker,
  ])

  useEffect(() => {
    if (searchState.qId === null) {
      onSelectedQuestionChange(null)
      return
    }

    if (
      selectedQuestion !== null &&
      selectedQuestion.query_id !== searchState.qId
    ) {
      onSelectedQuestionChange(null)
    }
  }, [onSelectedQuestionChange, searchState.qId, selectedQuestion])

  const updateSearch = useCallback(
    (updates: SearchUpdate) => {
      const next = new URLSearchParams(searchParams)

      if (updates.mode !== undefined) {
        next.set('mode', updates.mode)
      }
      if (updates.top_k !== undefined) {
        next.set('top_k', String(updates.top_k))
      }
      if (updates.reranker !== undefined) {
        next.set('reranker', updates.reranker)
      }
      if (updates.generator !== undefined) {
        next.set('generator', updates.generator)
      }
      if (updates.collection !== undefined) {
        next.set('collection', updates.collection)
      }
      if (updates.q_id !== undefined) {
        if (updates.q_id === null) {
          next.delete('q_id')
        } else {
          next.set('q_id', updates.q_id)
        }
      }

      setSearchParams(next, {
        replace: true,
        preventScrollReset: true,
      })
    },
    [searchParams, setSearchParams],
  )

  const handlePickQuestion = useCallback(
    (question: EvalQuestion | null) => {
      onSelectedQuestionChange(question)
      const nextQueryId = question?.query_id ?? null

      if (nextQueryId !== searchState.qId) {
        updateSearch({ q_id: nextQueryId })
      }
    },
    [onSelectedQuestionChange, searchState.qId, updateSearch],
  )

  const activeQuestion =
    searchState.qId !== null && selectedQuestion?.query_id === searchState.qId
      ? selectedQuestion
      : null
  const queryText =
    activeQuestion !== null ? activeQuestion.query : searchState.qId === null ? freeText : ''
  const canSubmit = queryText.trim().length > 0 && !queryMutation.isPending
  const mutationErrorMessage =
    queryMutation.error instanceof Error
      ? queryMutation.error.message
      : 'The query request failed.'

  function handleCollectionChange(collection: string): void {
    onSelectedQuestionChange(null)
    updateSearch({ collection, q_id: null })
  }

  function handleSubmit(): void {
    const trimmedQuery = queryText.trim()

    if (trimmedQuery === '') {
      return
    }

    queryMutation.mutate({
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
  }

  return (
    <PageFrame>
      <section className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <Card>
          <CardHeader>
            <CardTitle>Ask a question</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-5">
            <CollectionSelector
              value={searchState.collection}
              choices={components.collections}
              onChange={handleCollectionChange}
            />

            <PipelineKnobs
              components={components}
              mode={searchState.mode}
              onModeChange={(mode) => updateSearch({ mode })}
              topK={searchState.topK}
              onTopKChange={(topK) => updateSearch({ top_k: topK })}
              reranker={searchState.reranker}
              onRerankerChange={(reranker) => updateSearch({ reranker })}
              generator={searchState.generator}
              onGeneratorChange={(generator) => updateSearch({ generator })}
              isModelLoading={rerankerAwaitingFirstQuery && queryMutation.isPending}
            />

            <EvalQuestionPicker
              benchmark={derivedBenchmark}
              value={searchState.qId}
              onPickQuestion={handlePickQuestion}
              onFreeText={onFreeTextChange}
            />

            <div className="flex flex-wrap items-center gap-3">
              <Button type="button" onClick={handleSubmit} disabled={!canSubmit}>
                Ask
              </Button>
              {queryMutation.isError ? (
                <p role="alert" className="text-sm text-destructive">
                  {mutationErrorMessage}
                </p>
              ) : null}
            </div>
          </CardContent>
        </Card>

        <div className="grid gap-4">
          <AnswerCard
            grounded={queryMutation.data?.grounded ?? null}
            isLoading={queryMutation.isPending}
          />
          <MetricsCard
            metrics={queryMutation.data?.metrics ?? null}
            components={queryMutation.data?.components_used ?? null}
            latency={queryMutation.data?.latency_ms ?? null}
          />
        </div>
      </section>

      <RetrievedPassageList
        passages={queryMutation.data?.retrieved_passages ?? null}
        isLoading={queryMutation.isPending}
        supportingIds={activeQuestion?.supporting_passage_ids}
      />
    </PageFrame>
  )
}

function PageFrame({ children }: { children: ReactNode }) {
  return (
    <TooltipProvider>
      <main className="mx-auto flex min-h-screen w-full max-w-7xl flex-col gap-6 px-4 py-8 sm:px-6 lg:px-8">
        <header className="flex flex-col gap-3 border-b pb-4 sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-sm font-medium text-muted-foreground">Interactive RAG</p>
            <h1 className="text-3xl font-semibold tracking-normal">RAG Explorer</h1>
          </div>
          <nav className="flex flex-wrap gap-4 text-sm font-medium text-muted-foreground">
            <Link className="hover:text-foreground" to="/">
              Home
            </Link>
            <Link className="hover:text-foreground" to="/scoreboard">
              Open scoreboard
            </Link>
          </nav>
        </header>
        {children}
      </main>
    </TooltipProvider>
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
      Number.isInteger(parsedTopK) && components.top_k_choices.includes(parsedTopK)
        ? parsedTopK
        : defaultTopK(components),
    reranker:
      rerankerParam !== null &&
      components.rerankers.some((choice) => choice.name === rerankerParam)
        ? rerankerParam
        : components.rerankers[0]?.name ?? 'off',
    generator:
      generatorParam !== null &&
      components.generators.some((choice) => choice.name === generatorParam)
        ? generatorParam
        : components.generators[0]?.name ?? 'heuristic',
    collection:
      collectionParam !== null &&
      components.collections.some((choice) => choice.collection === collectionParam)
        ? collectionParam
        : components.collections[0]?.collection ?? '',
    qId: qIdParam === null || qIdParam.trim() === '' ? null : qIdParam,
  }
}

function searchStateToParams(state: AskSearchState): URLSearchParams {
  const params = new URLSearchParams()
  params.set('mode', state.mode)
  params.set('top_k', String(state.topK))
  params.set('reranker', state.reranker)
  params.set('generator', state.generator)

  if (state.collection !== '') {
    params.set('collection', state.collection)
  }
  if (state.qId !== null) {
    params.set('q_id', state.qId)
  }

  return params
}

function defaultRetrievalMode(components: ComponentsResponse): RetrievalMode {
  if (components.modes.includes('hybrid')) {
    return 'hybrid'
  }

  return components.modes[0] ?? 'hybrid'
}

function isRetrievalMode(value: string): value is RetrievalMode {
  return value === 'dense' || value === 'sparse' || value === 'hybrid'
}

function defaultTopK(components: ComponentsResponse): number {
  if (components.top_k_choices.includes(10)) {
    return 10
  }

  return components.top_k_choices[0] ?? 10
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
