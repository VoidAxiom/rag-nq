import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { ThemeProvider, useTheme } from '@/theme/ThemeProvider'
import { ThemePicker } from '@/theme/ThemePicker'

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

function CurrentTheme() {
  const { theme } = useTheme()
  return (
    <span data-testid="current-theme">
      {theme.style}/{theme.palette}
    </span>
  )
}

afterEach(() => {
  cleanup()
  window.localStorage.clear()
  delete document.documentElement.dataset.style
  delete document.documentElement.dataset.palette
})

describe('ThemePicker', () => {
  it('renders the 7 style options and the active palette options', () => {
    render(
      <ThemeProvider>
        <ThemePicker />
      </ThemeProvider>,
    )
    const styleSelect = screen.getByLabelText('Style') as HTMLSelectElement
    expect(styleSelect.options).toHaveLength(7)
    expect(styleSelect.value).toBe('neon')
    const paletteSelect = screen.getByLabelText('Palette') as HTMLSelectElement
    expect(paletteSelect.options).toHaveLength(3)
    expect(paletteSelect.value).toBe('neon-tokyo')
  })

  it('changing the style swaps the palette dropdown and resets palette', () => {
    render(
      <ThemeProvider>
        <ThemePicker />
        <CurrentTheme />
      </ThemeProvider>,
    )
    const styleSelect = screen.getByLabelText('Style') as HTMLSelectElement
    fireEvent.change(styleSelect, { target: { value: 'editorial' } })
    const paletteSelect = screen.getByLabelText('Palette') as HTMLSelectElement
    expect(paletteSelect.value).toBe('editorial-print')
    expect(screen.getByTestId('current-theme').textContent).toBe(
      'editorial/editorial-print',
    )
  })

  it('changing the palette updates the active theme', () => {
    render(
      <ThemeProvider>
        <ThemePicker />
        <CurrentTheme />
      </ThemeProvider>,
    )
    fireEvent.change(screen.getByLabelText('Palette'), {
      target: { value: 'neon-miami' },
    })
    expect(screen.getByTestId('current-theme').textContent).toBe(
      'neon/neon-miami',
    )
  })
})
