import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router'

import { AskPage } from '@/pages/AskPage'
import type {
  ComponentsResponse,
  EvalQuestionsResponse,
  QueryResponse,
} from '@/lib/types'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('AskPage', () => {
  it('renders loading state while components endpoint is pending', () => {
    const fetchMock = vi.fn<FetchHandler>(
      () => new Promise<Response>(() => undefined),
    )
    vi.stubGlobal('fetch', fetchMock)

    renderAskPage()

    expect(screen.getByRole('status', { name: /loading rag explorer/i })).toHaveAttribute(
      'aria-busy',
      'true',
    )
  })

  it('renders error state when components endpoint fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn<FetchHandler>(() =>
        Promise.resolve(new Response('Server failed', { status: 500 })),
      ),
    )

    renderAskPage()

    expect(await screen.findByText(/Failed to fetch components/i)).toBeInTheDocument()
  })

  it('displays question text after picking a curated eval question', async () => {
    const fetchMock = stubAskFetch()

    renderAskPage()

    await waitFor(() =>
      expect(fetchMock.mock.calls.some(([input]) => requestPath(input) === '/api/eval_questions/nq')).toBe(
        true,
      ),
    )
    fireEvent.click(screen.getByLabelText('Curated eval question'))

    expect(
      await screen.findByText(/Which scientist discovered radium\? \(nq-1\)/),
    ).toBeInTheDocument()
  })

  it('submits a query and renders the grounded answer', async () => {
    stubAskFetch({
      queryResponder: () => populatedQueryResponse(),
    })

    renderAskPage(['/ask?q_id=nq-1'])

    await screen.findByText(/Which scientist discovered radium\? \(nq-1\)/)
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(
      await screen.findByText('Marie Curie discovered radium.'),
    ).toBeInTheDocument()
  })

  it('buildOverrides sends generation_provider even when heuristic is selected', async () => {
    const fetchMock = stubAskFetch()

    renderAskPage(['/ask?q_id=nq-1'])

    await screen.findByText(/Which scientist discovered radium\? \(nq-1\)/)
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => requestPath(input) === '/query' && init?.method === 'POST',
        ),
      ).toBe(true),
    )
    const queryCall = fetchMock.mock.calls.find(
      ([input, init]) => requestPath(input) === '/query' && init?.method === 'POST',
    )
    if (queryCall === undefined) {
      throw new Error('Expected /query request body')
    }
    const [, init] = queryCall
    const body = parseBody(init)
    const overrides = body.overrides
    if (!isRecord(overrides)) {
      throw new Error('Expected overrides object')
    }
    expect(overrides.generation_provider).toBe('heuristic')
  })

  it('renders per-query metrics when gold_answers are present in the request', async () => {
    stubAskFetch({
      queryResponder: (request) => {
        const goldAnswers = request.gold_answers
        const hasGoldAnswers = Array.isArray(goldAnswers) && goldAnswers.length > 0

        return populatedQueryResponse({
          metrics: hasGoldAnswers
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

    await screen.findByText(/Which scientist discovered radium\? \(nq-1\)/)
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(await screen.findByText('0.750')).toBeInTheDocument()
    expect(screen.getByText('0.875')).toBeInTheDocument()
  })

  it('free-text query has no metrics card content', async () => {
    stubAskFetch({
      queryResponder: () =>
        populatedQueryResponse({
          metrics: null,
          query_id: null,
        }),
    })

    renderAskPage()

    fireEvent.change(await screen.findByLabelText('Question'), {
      target: { value: 'What is retrieval augmented generation?' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Ask' }))

    expect(
      await screen.findByText(/No metrics .*free-text/i),
    ).toBeInTheDocument()
  })

  it('OpenAI generator option is rendered as disabled', async () => {
    stubAskFetch({
      components: componentsFixture({
        openai_enabled: false,
      }),
    })

    renderAskPage()

    const generatorSelect = await screen.findByRole('combobox', {
      name: /generator/i,
    })
    fireEvent.pointerDown(generatorSelect, {
      button: 0,
      ctrlKey: false,
      pointerId: 1,
      pointerType: 'mouse',
    })

    expect(await screen.findByRole('option', { name: /OpenAI gpt-4o/i })).toHaveAttribute(
      'aria-disabled',
      'true',
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

    expect(
      await screen.findByRole('combobox', { name: /generator/i }),
    ).toHaveTextContent('Heuristic')
    await screen.findByText(/Which scientist discovered radium\? \(nq-1\)/)

    const askButton = screen.getByRole('button', { name: 'Ask' })
    expect(askButton).toBeEnabled()
    fireEvent.click(askButton)

    await waitFor(() =>
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => requestPath(input) === '/query' && init?.method === 'POST',
        ),
      ).toBe(true),
    )
    const queryCall = fetchMock.mock.calls.find(
      ([input, init]) => requestPath(input) === '/query' && init?.method === 'POST',
    )
    if (queryCall === undefined) {
      throw new Error('Expected /query request body')
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

    expect(
      await screen.findByRole('combobox', { name: /retrieval mode/i }),
    ).toHaveTextContent('sparse')
    expect(screen.getByRole('combobox', { name: /top k/i })).toHaveTextContent('20')
  })
})

function renderAskPage(initialEntries: string[] = ['/ask']): void {
  installRadixPointerMocks()

  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
      mutations: {
        retry: false,
      },
    },
  })

  render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <AskPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function installRadixPointerMocks(): void {
  if (!('hasPointerCapture' in window.HTMLElement.prototype)) {
    Object.defineProperty(window.HTMLElement.prototype, 'hasPointerCapture', {
      configurable: true,
      value: () => false,
    })
  }

  if (!('setPointerCapture' in window.HTMLElement.prototype)) {
    Object.defineProperty(window.HTMLElement.prototype, 'setPointerCapture', {
      configurable: true,
      value: () => undefined,
    })
  }

  if (!('releasePointerCapture' in window.HTMLElement.prototype)) {
    Object.defineProperty(window.HTMLElement.prototype, 'releasePointerCapture', {
      configurable: true,
      value: () => undefined,
    })
  }

  if (!('scrollIntoView' in window.HTMLElement.prototype)) {
    Object.defineProperty(window.HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: () => undefined,
    })
  }
}

interface StubAskFetchOptions {
  components?: ComponentsResponse
  questions?: EvalQuestionsResponse
  queryResponder?: (request: Record<string, unknown>) => QueryResponse
}

type FetchHandler = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

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

    if (method === 'POST' && path === '/query') {
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
    headers: {
      'Content-Type': 'application/json',
    },
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

function populatedQueryResponse(overrides: Partial<QueryResponse> = {}): QueryResponse {
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
