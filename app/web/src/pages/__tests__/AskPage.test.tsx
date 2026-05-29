import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, useLocation } from 'react-router'

import { AskPage } from '@/pages/AskPage'
import { ThemeProvider } from '@/theme/ThemeProvider'
import { ThemePicker } from '@/theme/ThemePicker'
import type {
  ComponentsResponse,
  EvalQuestionsResponse,
  QueryResponse,
} from '@/lib/types'

function installLocalStoragePolyfillIfMissing(): void {
  if (typeof window === 'undefined') return
  if (
    typeof window.localStorage !== 'undefined' &&
    window.localStorage !== null
  ) {
    return
  }
  const store = new Map<string, string>()
  const memoryStorage = {
    get length() {
      return store.size
    },
    clear(): void {
      store.clear()
    },
    getItem(key: string): string | null {
      return store.has(key) ? (store.get(key) as string) : null
    },
    setItem(key: string, value: string): void {
      store.set(String(key), String(value))
    },
    removeItem(key: string): void {
      store.delete(key)
    },
    key(index: number): string | null {
      return Array.from(store.keys())[index] ?? null
    },
  } satisfies Storage
  Object.defineProperty(window, 'localStorage', {
    configurable: true,
    value: memoryStorage,
  })
}
installLocalStoragePolyfillIfMissing()

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  window.localStorage.clear()
  delete document.documentElement.dataset.style
  delete document.documentElement.dataset.palette
})

describe('AskPage', () => {
  it('renders loading state while components endpoint is pending', () => {
    const fetchMock = vi.fn<FetchHandler>(
      () => new Promise<Response>(() => undefined),
    )
    vi.stubGlobal('fetch', fetchMock)
    renderAskPage()
    expect(
      screen.getByRole('status', { name: /loading rag explorer/i }),
    ).toHaveAttribute('aria-busy', 'true')
  })

  it('renders error state when components endpoint fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<FetchHandler>(() =>
        Promise.resolve(new Response('Server failed', { status: 500 })),
      ),
    )
    renderAskPage()
    expect(
      await screen.findByText(/Failed to fetch components/i),
    ).toBeInTheDocument()
  })

  it('displays question text after picking a curated eval question', async () => {
    const fetchMock = stubAskFetch()
    renderAskPage()
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input]) => requestPath(input) === '/api/eval_questions/nq',
        ),
      ).toBe(true),
    )
    fireEvent.click(screen.getByLabelText(/Curated eval question/i))
    expect(
      await screen.findByRole('option', {
        name: /Which scientist discovered radium\?/i,
      }),
    ).toBeInTheDocument()
  })

  it('submits a query, drives the pipeline, and renders the grounded answer', async () => {
    stubAskFetch({ queryResponder: () => populatedQueryResponse() })
    renderAskPage(['/ask?q_id=nq-1'])
    // Wait until the curated question is loaded into the input via select.
    await waitFor(() =>
      expect(
        (screen.getByLabelText('Question') as HTMLInputElement).value,
      ).toContain('Which scientist discovered radium?'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    // Animation: real timings (12.25 / 0 / 4.5 ms) but MIN_STEP_MS=250 floor →
    // ≥ 750ms for the pipeline + typewriter beats. Allow up to 4s.
    await waitFor(
      () => {
        expect(screen.getByTestId('answer-text').textContent).toContain(
          'Marie Curie discovered radium.',
        )
      },
      { timeout: 4000 },
    )
  })

  it('sends generation_provider in the request body', async () => {
    const fetchMock = stubAskFetch()
    renderAskPage(['/ask?q_id=nq-1'])
    await waitFor(() =>
      expect(
        (screen.getByLabelText('Question') as HTMLInputElement).value,
      ).toContain('Which scientist discovered radium?'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            requestPath(input) === '/api/query' && init?.method === 'POST',
        ),
      ).toBe(true),
    )
    const queryCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        requestPath(input) === '/api/query' && init?.method === 'POST',
    )
    if (queryCall === undefined) {
      throw new Error('Expected /api/query request body')
    }
    const [, init] = queryCall
    const body = parseBody(init)
    const overrides = body.overrides
    if (!isRecord(overrides)) {
      throw new Error('Expected overrides object')
    }
    expect(overrides.generation_provider).toBe('heuristic')
  })

  it('renders gold metrics when the active question carries gold_answers', async () => {
    stubAskFetch({
      queryResponder: (request) => {
        const goldAnswers = request.gold_answers
        const hasGold = Array.isArray(goldAnswers) && goldAnswers.length > 0
        return populatedQueryResponse({
          metrics: hasGold
            ? {
                em: 0.75,
                f1: 0.875,
                supporting_fact_recall_at_k: 1,
                k_used: 10,
              }
            : null,
        })
      },
    })
    renderAskPage(['/ask?q_id=nq-1'])
    await waitFor(() =>
      expect(
        (screen.getByLabelText('Question') as HTMLInputElement).value,
      ).toContain('Which scientist discovered radium?'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(
      () => expect(screen.getByText('0.750')).toBeInTheDocument(),
      { timeout: 4000 },
    )
    expect(screen.getByText('0.875')).toBeInTheDocument()
  })

  it('free-text query produces no gold metrics panel', async () => {
    stubAskFetch({
      queryResponder: () =>
        populatedQueryResponse({ metrics: null, query_id: null }),
    })
    renderAskPage()
    const inputs = await screen.findAllByLabelText('Question')
    const inputBox = inputs.find(
      (el) => (el as HTMLElement).tagName === 'INPUT',
    ) as HTMLInputElement | undefined
    if (inputBox === undefined) {
      throw new Error('Expected a free-text input')
    }
    fireEvent.change(inputBox, { target: { value: 'What is RAG?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(
      () =>
        expect(screen.queryByLabelText('Gold metrics')).not.toBeInTheDocument(),
      { timeout: 4000 },
    )
  })

  it('falls back to heuristic when URL ?generator=openai but openai is disabled', async () => {
    const fetchMock = stubAskFetch({
      components: componentsFixture({
        generators: [
          { name: 'heuristic', label: 'Heuristic', enabled: true },
          {
            name: 'openai',
            label: 'OpenAI gpt-4o',
            enabled: false,
            disabled_reason: 'OpenAI is not enabled.',
          },
        ],
        openai_enabled: false,
      }),
    })
    renderAskPage(['/ask?generator=openai&q_id=nq-1'])
    const generator = (await screen.findByLabelText(
      'Generator',
    )) as HTMLSelectElement
    expect(generator.value).toBe('heuristic')
    await waitFor(() =>
      expect(
        (screen.getByLabelText('Question') as HTMLInputElement).value,
      ).toContain('Which scientist discovered radium?'),
    )
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))
    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            requestPath(input) === '/api/query' && init?.method === 'POST',
        ),
      ).toBe(true),
    )
    const queryCall = fetchMock.mock.calls.find(
      ([input, init]) =>
        requestPath(input) === '/api/query' && init?.method === 'POST',
    )
    if (queryCall === undefined) {
      throw new Error('Expected /api/query request body')
    }
    const [, init] = queryCall
    const body = parseBody(init)
    const overrides = body.overrides
    if (!isRecord(overrides)) {
      throw new Error('Expected overrides object')
    }
    expect(overrides.generation_provider).toBe('heuristic')
  })

  it('URL params reflect knob selections', async () => {
    stubAskFetch()
    renderAskPage(['/ask?mode=sparse&top_k=20'])
    const mode = (await screen.findByLabelText(
      'Retrieval mode',
    )) as HTMLSelectElement
    expect(mode.value).toBe('sparse')
    const topK = (await screen.findByLabelText('Top K')) as HTMLSelectElement
    expect(topK.value).toBe('20')
  })

  it('theme picker round-trip changes <html> data-style', async () => {
    stubAskFetch()
    renderAskPage()
    const styleSelect = (await screen.findByLabelText(
      'Style',
    )) as HTMLSelectElement
    fireEvent.change(styleSelect, { target: { value: 'editorial' } })
    expect(document.documentElement.dataset.style).toBe('editorial')
    expect(document.documentElement.dataset.palette).toBe('editorial-print')
  })

  it('URL theme params survive Ask-state normalization', async () => {
    stubAskFetch()
    renderAskPage(['/ask?style=editorial&palette=editorial-bloomberg'])
    // Wait for the components fetch + normalization effect to settle.
    await screen.findByLabelText('Retrieval mode')
    const search = await screen.findByTestId('current-search')
    const params = new URLSearchParams(search.textContent ?? '')
    // Ask params get filled in by normalization.
    expect(params.get('mode')).not.toBeNull()
    // Theme params are preserved so the URL stays shareable.
    expect(params.get('style')).toBe('editorial')
    expect(params.get('palette')).toBe('editorial-bloomberg')
  })
})

function LocationProbe() {
  const location = useLocation()
  return <div data-testid="current-search">{location.search.replace(/^\?/, '')}</div>
}

function renderAskPage(initialEntries: string[] = ['/ask']): void {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  render(
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <MemoryRouter initialEntries={initialEntries}>
          <AskPage />
          {/* Render the theme picker so the round-trip test can target it. */}
          <ThemePicker />
          <LocationProbe />
        </MemoryRouter>
      </ThemeProvider>
    </QueryClientProvider>,
  )
}


interface StubAskFetchOptions {
  components?: ComponentsResponse
  questions?: EvalQuestionsResponse
  queryResponder?: (request: Record<string, unknown>) => QueryResponse
}

type FetchHandler = (
  input: RequestInfo | URL,
  init?: RequestInit,
) => Promise<Response>

function stubAskFetch({
  components = componentsFixture(),
  questions = evalQuestionsFixture(),
  queryResponder = () => populatedQueryResponse(),
}: StubAskFetchOptions = {}) {
  const fetchMock = vi.fn<FetchHandler>((input, init) => {
    const path = requestPath(input)
    const method = init?.method ?? 'GET'
    if (method === 'GET' && path === '/api/components') {
      return Promise.resolve(jsonResponse(components))
    }
    if (method === 'GET' && path === '/api/eval_questions/nq') {
      return Promise.resolve(jsonResponse(questions))
    }
    if (method === 'POST' && path === '/api/query') {
      return Promise.resolve(jsonResponse(queryResponder(parseBody(init))))
    }
    return Promise.resolve(new Response('Not found', { status: 404 }))
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

function requestPath(input: RequestInfo | URL): string {
  const rawUrl =
    typeof input === 'string'
      ? input
      : input instanceof URL
        ? input.toString()
        : input.url
  const url = new URL(rawUrl, 'http://localhost')
  return url.pathname
}

function parseBody(init: RequestInit | undefined): Record<string, unknown> {
  if (typeof init?.body !== 'string') {
    throw new Error('Expected JSON request body')
  }
  const payload: unknown = JSON.parse(init.body)
  if (!isRecord(payload)) {
    throw new Error('Expected object request body')
  }
  return payload
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function componentsFixture(
  overrides: Partial<ComponentsResponse> = {},
): ComponentsResponse {
  return {
    modes: ['dense', 'sparse', 'hybrid'],
    top_k_choices: [5, 10, 20],
    rerankers: [
      { name: 'off', label: 'No rerank', enabled: true },
      { name: 'mini-reranker', label: 'Mini reranker', enabled: true },
    ],
    generators: [
      { name: 'heuristic', label: 'Heuristic', enabled: true },
      {
        name: 'gpt-4o',
        label: 'OpenAI gpt-4o',
        enabled: false,
        disabled_reason: 'OpenAI is not enabled.',
      },
    ],
    collections: [{ benchmark: 'nq', collection: 'nq-dev' }],
    openai_enabled: false,
    embedder: 'bge-small-en-v1.5',
    ...overrides,
  }
}

function evalQuestionsFixture(): EvalQuestionsResponse {
  return {
    benchmark: 'nq',
    questions: [
      {
        query_id: 'nq-1',
        query: 'Which scientist discovered radium?',
        gold_answers: ['Marie Curie'],
        supporting_passage_ids: ['passage-1'],
        notes: null,
      },
    ],
  }
}

function populatedQueryResponse(
  overrides: Partial<QueryResponse> = {},
): QueryResponse {
  return {
    query: 'Which scientist discovered radium?',
    retrieved_passages: [
      {
        point_id: 'passage-1',
        title: 'Radium',
        text: 'Marie Curie and Pierre Curie discovered radium in 1898.',
        dense_rank: 2,
        sparse_rank: 3,
        fusion_rank: 1,
        rerank_rank: 1,
        dense_score: 0.8,
        sparse_score: 12,
        rerank_score: 0.95,
      },
    ],
    grounded: {
      answer: 'Marie Curie discovered radium.',
      citations: [{ point_id: 'passage-1' }],
      abstained: false,
      abstention_reason: null,
      supporting_point_ids: ['passage-1'],
    },
    metrics: {
      em: 1,
      f1: 1,
      supporting_fact_recall_at_k: 1,
      k_used: 10,
    },
    components_used: {
      mode: 'hybrid',
      top_k: 10,
      reranker: 'off',
      generator: 'heuristic',
      embedder: 'bge-small-en-v1.5',
      collection: 'nq-dev',
    },
    latency_ms: {
      retrieval_ms: 12.25,
      rerank_ms: 0,
      generation_ms: 4.5,
      total_ms: 16.75,
    },
    query_id: 'nq-1',
    ...overrides,
  }
}
