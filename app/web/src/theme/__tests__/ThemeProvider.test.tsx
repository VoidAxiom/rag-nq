import { act, cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ThemeProvider, useTheme } from '@/theme/ThemeProvider'
import { STORAGE_KEY } from '@/theme/themeRegistry'

// vitest 4's jsdom no longer ships a default localStorage; install an
// in-memory polyfill here so theme persistence tests work end-to-end.
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

function Probe() {
  const { theme, setStyle, setPalette } = useTheme()
  return (
    <div>
      <span data-testid="theme-style">{theme.style}</span>
      <span data-testid="theme-palette">{theme.palette}</span>
      <button data-testid="set-glass" onClick={() => setStyle('glass')}>
        glass
      </button>
      <button
        data-testid="set-bloomberg"
        onClick={() => setPalette('editorial-bloomberg')}
      >
        bloomberg
      </button>
      <button data-testid="set-editorial" onClick={() => setStyle('editorial')}>
        editorial
      </button>
    </div>
  )
}

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  delete document.documentElement.dataset.style
  delete document.documentElement.dataset.palette
  window.history.replaceState({}, '', '/')
  vi.restoreAllMocks()
})

describe('ThemeProvider', () => {
  it('defaults to neon-tokyo on first visit and applies it to <html>', () => {
    const { getByTestId } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(getByTestId('theme-style').textContent).toBe('neon')
    expect(getByTestId('theme-palette').textContent).toBe('neon-tokyo')
    expect(document.documentElement.dataset.style).toBe('neon')
    expect(document.documentElement.dataset.palette).toBe('neon-tokyo')
  })

  it('reads a valid stored selection from localStorage', () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ style: 'glass', palette: 'glass-arctic' }),
    )
    const { getByTestId } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(getByTestId('theme-style').textContent).toBe('glass')
    expect(getByTestId('theme-palette').textContent).toBe('glass-arctic')
  })

  it('falls back to default + warns on invalid stored value', () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ style: 'banana', palette: 'banana-split' }),
    )
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const { getByTestId } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(getByTestId('theme-style').textContent).toBe('neon')
    expect(warn).toHaveBeenCalled()
  })

  it('honors URL ?style=&palette= over localStorage on initial load', () => {
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ style: 'glass', palette: 'glass-arctic' }),
    )
    window.history.replaceState(
      {},
      '',
      '/ask?style=editorial&palette=editorial-bloomberg',
    )
    const { getByTestId } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    expect(getByTestId('theme-style').textContent).toBe('editorial')
    expect(getByTestId('theme-palette').textContent).toBe('editorial-bloomberg')
    // URL did NOT overwrite localStorage.
    const stored = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) ?? 'null',
    ) as { style?: string; palette?: string } | null
    expect(stored?.style).toBe('glass')
    expect(stored?.palette).toBe('glass-arctic')
  })

  it('setStyle picks the first palette of the new style if current is invalid', () => {
    const { getByTestId } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    act(() => {
      getByTestId('set-glass').click()
    })
    expect(getByTestId('theme-style').textContent).toBe('glass')
    expect(getByTestId('theme-palette').textContent).toBe('glass-aurora')
  })

  it('changing the style persists to localStorage', () => {
    const { getByTestId } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    act(() => {
      getByTestId('set-editorial').click()
    })
    const stored = JSON.parse(
      window.localStorage.getItem(STORAGE_KEY) ?? 'null',
    ) as { style?: string; palette?: string } | null
    expect(stored?.style).toBe('editorial')
    expect(stored?.palette).toBe('editorial-print')
  })

  it('setPalette ignores invalid combos', () => {
    const { getByTestId } = render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    )
    act(() => {
      getByTestId('set-bloomberg').click()
    })
    expect(getByTestId('theme-style').textContent).toBe('neon')
    expect(getByTestId('theme-palette').textContent).toBe('neon-tokyo')
  })
})
