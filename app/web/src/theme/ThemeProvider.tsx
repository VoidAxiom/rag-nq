import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'

import {
  DEFAULT_THEME,
  STORAGE_KEY,
  firstPaletteFor,
  isStyleId,
  isValidCombo,
  palettesFor,
  type PaletteId,
  type StyleId,
  type ThemeSelection,
} from '@/theme/themeRegistry'

interface StoredTheme {
  style: StyleId
  palette: PaletteId
}

interface ThemeContextValue {
  theme: ThemeSelection
  setStyle: (style: StyleId) => void
  setPalette: (palette: PaletteId) => void
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

function readUrlTheme(): ThemeSelection | null {
  if (typeof window === 'undefined') {
    return null
  }
  const params = new URLSearchParams(window.location.search)
  const urlStyle = params.get('style')
  const urlPalette = params.get('palette')
  if (urlStyle === null || urlPalette === null) {
    return null
  }
  if (!isValidCombo(urlStyle, urlPalette)) {
    return null
  }
  return { style: urlStyle as StyleId, palette: urlPalette as PaletteId }
}

function readStorageTheme(): ThemeSelection | null {
  if (typeof window === 'undefined') {
    return null
  }
  let raw: string | null
  try {
    raw = window.localStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
  if (raw === null) {
    return null
  }
  try {
    const parsed: unknown = JSON.parse(raw)
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'style' in parsed &&
      'palette' in parsed
    ) {
      const candidate = parsed as Partial<StoredTheme>
      if (isValidCombo(candidate.style, candidate.palette)) {
        return {
          style: candidate.style as StyleId,
          palette: candidate.palette as PaletteId,
        }
      }
    }
  } catch {
    return null
  }
  return null
}

function resolveInitialTheme(): ThemeSelection {
  const fromUrl = readUrlTheme()
  if (fromUrl !== null) {
    warnOnceForInvalidUrl()
    return fromUrl
  }
  warnOnceForInvalidUrl()
  const fromStorage = readStorageTheme()
  if (fromStorage !== null) {
    return fromStorage
  }
  warnOnceForInvalidStored()
  return DEFAULT_THEME
}

function warnOnceForInvalidStored(): void {
  if (typeof window === 'undefined') {
    return
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw === null) {
      return
    }
    const parsed: unknown = JSON.parse(raw)
    if (
      typeof parsed === 'object' &&
      parsed !== null &&
      'style' in parsed &&
      'palette' in parsed
    ) {
      const candidate = parsed as Partial<StoredTheme>
      if (!isValidCombo(candidate.style, candidate.palette)) {
        console.warn(
          `[theme] ignoring invalid stored selection ${JSON.stringify(parsed)}; falling back to default.`,
        )
      }
    } else {
      console.warn(
        '[theme] ignoring malformed stored selection; falling back to default.',
      )
    }
  } catch {
    console.warn(
      '[theme] ignoring unparseable stored selection; falling back to default.',
    )
  }
}

function warnOnceForInvalidUrl(): void {
  if (typeof window === 'undefined') {
    return
  }
  const params = new URLSearchParams(window.location.search)
  const urlStyle = params.get('style')
  const urlPalette = params.get('palette')
  if (urlStyle === null && urlPalette === null) {
    return
  }
  if (!isValidCombo(urlStyle, urlPalette)) {
    console.warn(
      `[theme] ignoring invalid URL combo style=${String(urlStyle)} palette=${String(urlPalette)}; falling back.`,
    )
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // useState's lazy initializer guarantees one-shot computation without a ref.
  const [theme, setTheme] = useState<ThemeSelection>(resolveInitialTheme)

  useEffect(() => {
    if (typeof document === 'undefined') {
      return
    }
    document.documentElement.dataset.style = theme.style
    document.documentElement.dataset.palette = theme.palette
  }, [theme])

  const persist = useCallback((next: ThemeSelection) => {
    if (typeof window === 'undefined') {
      return
    }
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
    } catch {
      // Storage unavailable (private mode / disk full / SSR). Tolerate silently.
    }
  }, [])

  const setStyle = useCallback(
    (style: StyleId) => {
      if (!isStyleId(style)) {
        return
      }
      setTheme((current) => {
        const palette = palettesFor(style).some(
          (entry) => entry.id === current.palette,
        )
          ? current.palette
          : firstPaletteFor(style)
        const next: ThemeSelection = { style, palette }
        persist(next)
        return next
      })
    },
    [persist],
  )

  const setPalette = useCallback(
    (palette: PaletteId) => {
      setTheme((current) => {
        if (!isValidCombo(current.style, palette)) {
          return current
        }
        const next: ThemeSelection = { style: current.style, palette }
        persist(next)
        return next
      })
    },
    [persist],
  )

  const value = useMemo<ThemeContextValue>(
    () => ({ theme, setStyle, setPalette }),
    [theme, setStyle, setPalette],
  )

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (ctx === null) {
    throw new Error('useTheme must be used within ThemeProvider')
  }
  return ctx
}
