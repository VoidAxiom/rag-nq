export type StyleId =
  | 'neon'
  | 'glass'
  | 'terminal'
  | 'editorial'
  | 'brut'
  | 'liquid'
  | 'holo'

export type PaletteId =
  // Neon
  | 'neon-tokyo'
  | 'neon-miami'
  | 'neon-vapor'
  // Glass
  | 'glass-aurora'
  | 'glass-arctic'
  | 'glass-sunset'
  // Terminal
  | 'terminal-matrix'
  | 'terminal-amber'
  | 'terminal-solarized'
  // Editorial
  | 'editorial-print'
  | 'editorial-inverted'
  | 'editorial-bloomberg'
  // Brutalist
  | 'brut-caution'
  | 'brut-construct'
  | 'brut-electric'
  // Liquid
  | 'liquid-ocean'
  | 'liquid-lava'
  | 'liquid-forest'
  // Holographic
  | 'holo-prism'
  | 'holo-opal'
  | 'holo-oilslick'

export interface StyleDescriptor {
  id: StyleId
  label: string
}

export interface PaletteDescriptor {
  id: PaletteId
  label: string
}

export interface ThemeSelection {
  style: StyleId
  palette: PaletteId
}

export const STYLES: readonly StyleDescriptor[] = [
  { id: 'neon', label: 'Neon Synthwave' },
  { id: 'glass', label: 'Glassmorphic' },
  { id: 'terminal', label: 'Terminal / CLI' },
  { id: 'editorial', label: 'Editorial' },
  { id: 'brut', label: 'Brutalist' },
  { id: 'liquid', label: 'Liquid / Organic' },
  { id: 'holo', label: 'Holographic' },
] as const

export const PALETTES: Record<StyleId, readonly PaletteDescriptor[]> = {
  neon: [
    { id: 'neon-tokyo', label: 'Tokyo (cyan + magenta)' },
    { id: 'neon-miami', label: 'Miami (pink + amber)' },
    { id: 'neon-vapor', label: 'Vapor (lilac + mint)' },
  ],
  glass: [
    { id: 'glass-aurora', label: 'Aurora (pastel)' },
    { id: 'glass-arctic', label: 'Arctic (ice + frost)' },
    { id: 'glass-sunset', label: 'Sunset (peach + coral)' },
  ],
  terminal: [
    { id: 'terminal-matrix', label: 'Matrix (phosphor green)' },
    { id: 'terminal-amber', label: 'Amber CRT' },
    { id: 'terminal-solarized', label: 'Solarized Dark' },
  ],
  editorial: [
    { id: 'editorial-print', label: 'Print (black on cream)' },
    { id: 'editorial-inverted', label: 'Inverted (cream on black)' },
    { id: 'editorial-bloomberg', label: 'Bloomberg (navy + orange)' },
  ],
  brut: [
    { id: 'brut-caution', label: 'Caution (yellow + black)' },
    { id: 'brut-construct', label: 'Construct (tomato + cobalt)' },
    { id: 'brut-electric', label: 'Electric (cobalt + neon)' },
  ],
  liquid: [
    { id: 'liquid-ocean', label: 'Ocean (teal + emerald)' },
    { id: 'liquid-lava', label: 'Lava (crimson + amber)' },
    { id: 'liquid-forest', label: 'Forest (moss + bronze)' },
  ],
  holo: [
    { id: 'holo-prism', label: 'Prism (CMY shift)' },
    { id: 'holo-opal', label: 'Opal (pearl pastel)' },
    { id: 'holo-oilslick', label: 'Oilslick (deep purple)' },
  ],
} as const

export const DEFAULT_THEME: ThemeSelection = {
  style: 'neon',
  palette: 'neon-tokyo',
}

export const STORAGE_KEY = 'ask-theme'

export function isStyleId(value: unknown): value is StyleId {
  return (
    typeof value === 'string' && STYLES.some((style) => style.id === value)
  )
}

export function isPaletteId(value: unknown): value is PaletteId {
  return (
    typeof value === 'string' &&
    Object.values(PALETTES).some((list) =>
      list.some((entry) => entry.id === value),
    )
  )
}

export function isValidCombo(style: unknown, palette: unknown): boolean {
  if (!isStyleId(style) || !isPaletteId(palette)) {
    return false
  }
  return PALETTES[style].some((entry) => entry.id === palette)
}

export function firstPaletteFor(style: StyleId): PaletteId {
  return PALETTES[style][0].id
}

export function palettesFor(style: StyleId): readonly PaletteDescriptor[] {
  return PALETTES[style]
}
