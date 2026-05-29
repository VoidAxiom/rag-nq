import type { ChangeEvent } from 'react'

import { useTheme } from '@/theme/ThemeProvider'
import {
  PALETTES,
  STYLES,
  isPaletteId,
  isStyleId,
  type PaletteId,
  type StyleId,
} from '@/theme/themeRegistry'

export function ThemePicker() {
  const { theme, setStyle, setPalette } = useTheme()

  function handleStyleChange(event: ChangeEvent<HTMLSelectElement>) {
    const next = event.target.value
    if (isStyleId(next)) {
      setStyle(next as StyleId)
    }
  }

  function handlePaletteChange(event: ChangeEvent<HTMLSelectElement>) {
    const next = event.target.value
    if (isPaletteId(next)) {
      setPalette(next as PaletteId)
    }
  }

  const paletteChoices = PALETTES[theme.style]

  return (
    <div className="theme-picker" role="group" aria-label="Theme picker">
      <label className="theme-picker__field">
        <span className="theme-picker__label">Style</span>
        <select
          aria-label="Style"
          value={theme.style}
          onChange={handleStyleChange}
          className="theme-picker__select"
        >
          {STYLES.map((style) => (
            <option key={style.id} value={style.id}>
              {style.label}
            </option>
          ))}
        </select>
      </label>
      <label className="theme-picker__field">
        <span className="theme-picker__label">Palette</span>
        <select
          aria-label="Palette"
          value={theme.palette}
          onChange={handlePaletteChange}
          className="theme-picker__select"
        >
          {paletteChoices.map((palette) => (
            <option key={palette.id} value={palette.id}>
              {palette.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
