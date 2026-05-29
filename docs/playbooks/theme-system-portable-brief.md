# Theme + Palette System — Portable Brief for Another Claude

Paste this whole document into a new Claude session along with: "I want to add this theme system to my React app." Claude should be able to produce a working implementation from this brief alone.

---

## 1. What you're building

A **two-axis theming system** for a React app:

- **Style** = the visual *language* (layout density, typography, motion grammar, surface treatments like glows / blurs / gradients).
- **Palette** = the *colors* (3 accent colors + supporting background tints).

Ship **7 styles × 3 palettes = 21 combinations**. Both axes are independently swappable from a header picker. Selection persists to `localStorage`; a URL param (`?style=X&palette=Y`) can override for share-links.

This is the showcase pattern: a user lands on the default theme, then plays with the picker to find their look. The styles cover a wide aesthetic range deliberately — they're not all "tasteful corporate"; some are loud (Neon, Brutalist, Holographic) so the picker IS the demo.

## 2. Architecture

### 2.1 The DOM contract

Two attributes on `<html>` (or any root element):

```html
<html data-style="neon" data-palette="neon-tokyo">
```

A CSS file (`themes.css`) sets CSS custom properties on the cartesian product:

```css
[data-style="neon"][data-palette="neon-tokyo"] {
  --bg: #080013;
  --surface: rgba(20,0,40,0.6);
  --text: #e1d4ff;
  --accent-1: #ff2bd6;   /* first step / primary accent */
  --accent-2: #b94aff;   /* second step / secondary accent */
  --accent-3: #00ffe5;   /* third step / tertiary accent */
  --total-glow: 0 0 24px rgba(0,255,229,0.4);
  --motion-running: pulse-glow 1.2s ease-in-out infinite;
  --font-numeric: 'Orbitron', 'JetBrains Mono', monospace;
  --font-body: 'JetBrains Mono', ui-monospace, monospace;
  /* ...etc */
}
```

Components consume ONLY these tokens, never style-specific class names. That keeps `<MyComponent>` theme-agnostic — adding a new theme means appending one block to `themes.css`, not editing every component.

### 2.2 Universal selectors + per-style keyframes

Some effects (pulse, glow, fade) need `@keyframes`. Define them inside the style block:

```css
[data-style="neon"] {
  --motion-step-running: neon-pulse 1.2s ease-in-out infinite;
}
@keyframes neon-pulse { /* ... */ }

[data-style="editorial"] {
  --motion-step-running: none; /* editorial doesn't pulse */
}
```

Then components apply the token: `animation: var(--motion-step-running)`. When the style changes, the animation swaps automatically.

### 2.3 Light vs dark modes

Some palettes are light-mode (`editorial-print`, `holo-opal`, `glass-arctic-sunset`). Set `color-scheme` inside the selector so native controls (form inputs, scrollbars) match:

```css
[data-style="editorial"][data-palette="editorial-print"] {
  color-scheme: light;
  /* tokens... */
}
```

## 3. The 21 combos (canonical list)

| Style ID | Palette ID | Description | Background base | Accent 1 | Accent 2 | Accent 3 |
|---|---|---|---|---|---|---|
| `neon` | `neon-tokyo` | cyan + magenta + violet | `#080013` | `#ff2bd6` magenta | `#b94aff` violet | `#00ffe5` cyan |
| `neon` | `neon-miami` | pink + orange + amber | `#1a0028` | `#ff6b9d` pink | `#ff8c42` orange | `#ffc857` amber |
| `neon` | `neon-vapor` | lilac + pink + mint | `#1a1530` | `#c8b6ff` lilac | `#ffb6e1` pink | `#b6ffd9` mint |
| `glass` | `glass-aurora` | pink + violet + mint pastels | `linear-gradient(135deg,#1a1f3a,#2d1f4a,#1a3a4a)` | `#ffb8d8` | `#d8b8ff` | `#b8ffd8` |
| `glass` | `glass-arctic` | ice + frost + silver | `linear-gradient(135deg,#2a3a4a,#3a4a5a,#4a5a6a)` | `#b4dcff` | `#dcebfa` | `#c8d2e1` |
| `glass` | `glass-sunset` | peach + coral + amber | `linear-gradient(135deg,#3a1f1a,#4a2a1f,#3a1f2a)` | `#ffb48c` | `#ff8c78` | `#ffc878` |
| `terminal` | `terminal-matrix` | phosphor green + amber | `#0a0e0a` | `#00ff66` green | `#ffcc00` amber | `#00ff66` green |
| `terminal` | `terminal-amber` | vintage amber + white | `#1a0d00` | `#ffaa00` amber | `#ffffff` white | `#ffaa00` amber |
| `terminal` | `terminal-solarized` | Solarized Dark | `#002b36` | `#268bd2` blue | `#b58900` yellow | `#6c71c4` violet |
| `editorial` | `editorial-print` | black on cream (light) | `#fafaf7` | `#1a1a1a` | `#1a1a1a` | `#1a1a1a` |
| `editorial` | `editorial-inverted` | cream on black | `#0a0a0a` | `#f5f0e8` | `#f5f0e8` | `#f5f0e8` |
| `editorial` | `editorial-bloomberg` | navy + orange | `#0a1530` | `#ff8800` orange | `#ff8800` | `#ff8800` |
| `brut` | `brut-caution` | yellow + black | `#fff200` | `#000000` | `#000000` | `#000000` |
| `brut` | `brut-construct` | tomato + cobalt + cream | `#fff8e7` | `#d83a3a` tomato | `#1f4ec2` cobalt | `#1a1a1a` |
| `brut` | `brut-electric` | cobalt + neon yellow | `#0033ff` | `#fcff00` neon yellow | `#000000` | `#fcff00` |
| `liquid` | `liquid-ocean` | teal + cerulean + emerald | `radial-gradient(ellipse at top,#003a4a,#001a2a 70%)` | `#7fdfff` teal | `#5fc0a8` cerulean | `#4fffc0` emerald |
| `liquid` | `liquid-lava` | crimson + amber + magenta | `radial-gradient(ellipse at top,#4a1a00,#2a0a00 70%)` | `#ff5050` crimson | `#ffa030` amber | `#ff3aa0` magenta |
| `liquid` | `liquid-forest` | moss + olive + bronze | `radial-gradient(ellipse at top,#1a3a20,#0a1f10 70%)` | `#a8d090` moss | `#c0b070` olive | `#d4a850` bronze |
| `holo` | `holo-prism` | CMY shift | `linear-gradient(135deg,#1a1a2e,#16213e,#0f3460)` | `#00f5ff` cyan | `#ff00ff` magenta | `#ffea00` yellow |
| `holo` | `holo-opal` | pearl pastel shift (light) | `linear-gradient(135deg,#f0e8ff,#ffe8f5,#e8fff5)` | `#9d7fd0` lavender | `#d09da0` pink | `#7fd0a0` mint |
| `holo` | `holo-oilslick` | deep purple + rainbow sheen | `linear-gradient(135deg,#0a0014,#14002a,#1a0033)` | `#9d7fff` violet | `#ff7fda` pink | `#7fffda` teal |

## 4. Per-style design DNA

What makes each style itself — the ingredients to bake into its CSS block.

### 4.1 Neon Synthwave
- **Backgrounds:** deep violet-black (`#080013`-ish).
- **Surfaces:** semi-transparent dark with thin glowing borders.
- **Typography:** `Orbitron` for big numerics; `JetBrains Mono` for body.
- **Effects:** strong `box-shadow` glows in accent colors; subtle scanline overlay via a fixed pseudo-element; `text-shadow` glows on bright text.
- **Motion:** pulsing glow (1.2s ease-in-out infinite), scrolling gradient on "data flow" lines, pulse-scale on active indicators.
- **Vibe:** maximalist, loud, 80s arcade. The picker default if you want "wow on first open."

### 4.2 Glassmorphic / Aurora
- **Backgrounds:** soft pastel linear gradients (3-color, 135deg).
- **Surfaces:** `background: rgba(255,255,255,0.08); backdrop-filter: blur(20px); border: 1px solid rgba(255,255,255,0.15);` — classic glass.
- **Typography:** `-apple-system, 'SF Pro Display'`, weight 200-500.
- **Effects:** soft drop shadows; large blurred radial-gradient "auroras" in the background.
- **Motion:** breathing scale (1.0 ↔ 1.02), opacity fades, blur transitions.
- **Vibe:** Apple-event premium. Restrained but rich.

### 4.3 Terminal / CLI
- **Backgrounds:** near-black (`#0a0e0a`, `#1a0d00`, or `#002b36`).
- **Surfaces:** pure black with 1-2px solid borders in the accent color. NO border-radius (use `border-radius: 0`).
- **Typography:** ALL `JetBrains Mono` or `Berkeley Mono`. No exceptions.
- **Effects:** `[✓]`, `[~]`, `[-]` ASCII state indicators. `--flag=value` config syntax. Blinking cursor for active fields.
- **Motion:** stepped reveals (`animation-timing-function: steps(N)`), blinks (`steps(2)`), no smooth transitions.
- **Vibe:** dev-tool honest. The pragmatist's choice.

### 4.4 Editorial / Typographic
- **Backgrounds:** off-white (`#fafaf7`) for `editorial-print`, near-black (`#0a0a0a`) for inverted, navy (`#0a1530`) for Bloomberg.
- **Surfaces:** transparent. Vertical hairlines (1px) replace borders.
- **Typography:** `Playfair Display` or `Georgia` for big numerics (weight 200-300 — thin elegance). `Inter` for body. Italic for captions.
- **Effects:** none. No shadows, no glows. `font-feature-settings: 'tnum'` for tabular numerics. `letter-spacing` and `font-weight` are the only "decoration."
- **Motion:** number tick-ups via JS interval; hairline extends via `width` or `height` transition. That's all.
- **Vibe:** NYT, Bloomberg, Stripe docs. The grown-up theme.

### 4.5 Brutalist
- **Backgrounds:** vivid flat color blocks (`#fff200` yellow, `#0033ff` cobalt, `#fff8e7` cream).
- **Surfaces:** solid flat blocks of contrasting color. 2-4px solid borders if any.
- **Typography:** `Space Grotesk` or any bold sans. Weight 700-900. Uppercase for labels.
- **Effects:** NO shadows, NO gradients, NO transparency. Sharp corners. Maybe a `transform: rotate(-2deg)` on one element for asymmetric energy.
- **Motion:** `transition: none` everywhere. State changes are instant flips between flat color blocks.
- **Vibe:** unapologetic, design-school-thesis, Are.na-board. The contrarian theme.

### 4.6 Liquid / Organic
- **Backgrounds:** `radial-gradient(ellipse at top, ...)` deep-color compositions.
- **Surfaces:** rounded blob shapes — generous `border-radius` (20-24px) — with subtle background gradients.
- **Typography:** `Inter` or `SF Pro Display`, weight 300.
- **Effects:** SVG blob shapes in the background with `filter: blur(40px)`. Gradient borders.
- **Motion:** A vertical SVG wave path that morphs over time and travels top-down through "stages" (state below the wave = complete, at the wave = running, above = pending). For non-pipeline apps, replace the wave with an organic blob that animates between key states.
- **Vibe:** spa app, meditation, fluid dynamics. Calm + premium.

### 4.7 Holographic / Iridescent
- **Backgrounds:** deep navy/purple gradients, OR pearl pastel gradients.
- **Surfaces:** `background-image: linear-gradient(135deg, #color1, #color2, #color3, #color4); background-size: 200% 200%;` with a slow `background-position` animation, OR `conic-gradient` with rotation.
- **Typography:** `Inter`, weight 600+. Color text with `background-clip: text; -webkit-text-fill-color: transparent` and a gradient background to get holographic text.
- **Effects:** `filter: hue-rotate(...)` animations. `mix-blend-mode: difference` for dramatic edges. Optionally a noise-texture SVG overlay at low opacity.
- **Motion:** hue rotates over 3-6 seconds infinite linear. Conic gradients rotate slowly. Backgrounds shift between palette colors via `background-position`.
- **Vibe:** Y2K revival, Apple's iOS 17 vibes. Maximal pop.

## 5. CSS token contract (recommended)

Every component reads only from these vars. Each style/palette combo sets all of them.

```css
/* Surfaces */
--bg                /* page background */
--surface           /* card/panel background */
--surface-raised    /* hover/active card background */
--border-base       /* default border color */
--border-active     /* active/highlighted border */

/* Text */
--text              /* primary text */
--text-muted        /* secondary text */
--text-on-accent    /* text drawn over an accent-colored background */

/* Accents (per palette) */
--accent-1          /* primary accent */
--accent-2          /* secondary accent */
--accent-3          /* tertiary accent */

/* Effects */
--glow-accent-1     /* box-shadow value, e.g. "0 0 16px rgba(255,43,214,0.4)" */
--glow-accent-2
--glow-accent-3
--text-shadow-glow  /* "0 0 6px currentColor" or "none" */

/* Motion */
--motion-running    /* animation shorthand for "active" elements */
--motion-flowing    /* animation for "data flow" indicators */
--motion-appear     /* transition for elements entering */
--motion-snap       /* "0s" for brutalist, otherwise smooth */

/* Typography */
--font-numeric      /* for big numbers */
--font-body         /* for body text */
--font-mono         /* always mono */

/* Surface shape */
--radius-card       /* card border-radius — 0 for terminal/brut, 6-8 for most, 20+ for liquid */
--radius-sm         /* small elements */

/* Borders */
--border-width-card /* 1-2px for most, 3-4px for brutalist */
```

Components reference them: `background: var(--surface); border: var(--border-width-card) solid var(--border-base);`

## 6. The picker UI

Header strip, always visible. Two dropdowns side by side:

```tsx
<header>
  <select value={style} onChange={e => setStyle(e.target.value)}>
    <option value="neon">Neon</option>
    <option value="glass">Glass</option>
    <option value="terminal">Terminal</option>
    <option value="editorial">Editorial</option>
    <option value="brut">Brutalist</option>
    <option value="liquid">Liquid</option>
    <option value="holo">Holographic</option>
  </select>
  <select value={palette} onChange={e => setPalette(e.target.value)}>
    {PALETTES[style].map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
  </select>
</header>
```

When `style` changes, auto-set `palette` to the first palette of the new style (so no invalid combos). Keep a `PALETTES: Record<StyleId, {id, label}[]>` map.

The `<select>` elements themselves consume theme tokens for their background/text — `select { background: var(--surface); color: var(--text); }` — so they look right in every theme.

## 7. ThemeProvider + persistence

```tsx
// ThemeProvider.tsx
const STORAGE_KEY = 'theme';
const DEFAULT_STYLE = 'neon';
const DEFAULT_PALETTE = 'neon-tokyo';

export function ThemeProvider({ children }) {
  const [theme, setTheme] = useState(() => {
    // 1. URL param wins (for share links). Do NOT persist URL theme.
    const params = new URLSearchParams(location.search);
    const urlStyle = params.get('style');
    const urlPalette = params.get('palette');
    if (urlStyle && urlPalette && isValid(urlStyle, urlPalette)) {
      return { style: urlStyle, palette: urlPalette, fromUrl: true };
    }
    // 2. localStorage second.
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null');
      if (stored && isValid(stored.style, stored.palette)) return { ...stored, fromUrl: false };
    } catch {}
    // 3. Default.
    return { style: DEFAULT_STYLE, palette: DEFAULT_PALETTE, fromUrl: false };
  });

  useEffect(() => {
    document.documentElement.dataset.style = theme.style;
    document.documentElement.dataset.palette = theme.palette;
  }, [theme]);

  const set = (next) => {
    setTheme({ ...next, fromUrl: false });
    if (!next.fromUrl) localStorage.setItem(STORAGE_KEY, JSON.stringify({ style: next.style, palette: next.palette }));
  };

  return <ThemeContext.Provider value={{ theme, set }}>{children}</ThemeContext.Provider>;
}
```

Rules locked:
- URL param overrides localStorage on load, but does NOT write to localStorage.
- Any picker change writes to localStorage.
- Invalid stored value → silent fall-back to default + one console warn.
- First-visit default = `neon` + `neon-tokyo`.

## 8. Implementation order

If you're starting fresh on a new app:

1. **Token contract** — decide your component-level token names (use §5 as a starting point). Strip unused ones.
2. **`themes.css`** — populate ALL 21 blocks with token values. This is the longest file; write it before any components.
3. **`ThemeProvider` + `ThemePicker`** — wire URL+localStorage+attribute flip. Verify in the browser by manually toggling dropdowns; backgrounds and text should swap immediately.
4. **One signature component** (e.g. a "primary card" or "hero panel") — implement it consuming only tokens. Verify it looks right across all 21 themes. This is your reference component; copy its pattern for the rest.
5. **Motion components** — anything with state changes (loading → ready, idle → active). Implement universal classes (`.running`, `.complete`, etc.) that read motion tokens. Verify each style's keyframes hook up.
6. **Existing components** — restyle one at a time. Replace hard-coded colors with tokens. Add `data-state` attrs where state-driven motion applies.
7. **Polish pass** — light-mode `color-scheme` setting; native control styling; scrollbar theming; font-loading fallbacks.

## 9. Gotchas / learned along the way

- **Brutalist's "no motion" is intentional**, not a bug. Don't add fallback transitions. The snap IS the point.
- **Editorial light-mode** needs `color-scheme: light` on its `<html>` selector or the user's OS dark mode will fight with form-control colors.
- **Glass `backdrop-filter`** is heavy on lower-end devices. Add a `@media (prefers-reduced-motion: reduce)` or `@supports not (backdrop-filter: blur(1px))` fallback (solid rgba background, no blur).
- **Holographic hue-rotate** loops can be epileptic-trigger territory at high speeds. Keep the rotation duration ≥3s.
- **Terminal** must use `border-radius: 0` everywhere or it looks wrong. Make a `--radius-card: 0` token override in the terminal block.
- **Neon's `text-shadow` glows** stack with `box-shadow` — be careful on overlapping cards or you'll get unintended halos.
- **Liquid's wave** is the hardest to implement well. If you can't get an SVG wave right, fall back to gradient-position animation (`background-position: 0 0% → 0 100%` on a linear gradient).
- **Picker UX:** put the style dropdown LEFT of the palette dropdown. Users mentally pick style first ("loud or quiet") then color second.
- **Don't over-engineer the picker** — a `<select>` element styled with tokens looks better than a custom popover in 80% of cases and is keyboard-accessible by default.
- **Test the default theme on first visit**. localStorage being empty IS a state worth verifying explicitly (delete localStorage in DevTools → reload → confirm default).
- **Share-link URL params don't pollute localStorage** — important. Otherwise users sharing a "look at this theme!" link mess up the recipient's saved preference.

## 10. Naming conventions

- Style IDs are single-word lowercase: `neon`, `glass`, `terminal`, `editorial`, `brut`, `liquid`, `holo`.
- Palette IDs are `<style>-<short-name>`: `neon-tokyo`, `terminal-matrix`, `holo-oilslick`.
- Token vars use kebab-case with `--` prefix: `--accent-1`, `--motion-running`.
- Component state classes use BEM-ish double-dash: `.step--running`, `.bridge--flowing`.

## 11. Optional: add an 8th style

The 7 styles above span the aesthetic range deliberately. If you want to extend, here are ideas the user already considered and rejected, plus new ones:

- **Vaporwave** (rejected — too close to Neon Vapor palette).
- **Cyberpunk Glitch** — RGB-split text, noise overlay, occasional `clip-path` glitches. Cool but accessibility-hostile.
- **Memphis** — 80s pattern-heavy with squiggles, dots, geometric shapes. Hard to balance.
- **Origami / Paper** — folded paper, soft shadows, off-white. Could work alongside Editorial.
- **Wireframe / Schematic** — blueprint blue + white linework, monospace, technical-drawing feel. Distinct from Terminal.
- **Pixel Art** — chunky 8-bit aesthetic, pixelated fonts (`Press Start 2P`). Strong commit; not for everyone.

Pick whichever extends YOUR app's mood; the architecture above is identical regardless of how many styles you add.

---

## 12. Hand-off instructions to the next Claude

Copy the section above into a new Claude session along with: "Build this theme system for my React + [Vite/Next/CRA] app. Start with `themes.css` populated for all 21 combos, then `ThemeProvider`, then `ThemePicker`. Show me one signature component (e.g. a Card) using the tokens before scaling out."

Expect the next Claude to ask:
- What's the existing app's component shape (so it can pick a signature component to demo first)?
- Are there any existing components that already have hard-coded colors that need migrating?
- Any styles you want to add/remove from the 7? (You can drop any of them — the architecture isn't load-bearing on a specific count.)

Good luck. The system was designed by Claude in a brainstorming session on 2026-05-29 for the `rag_nq` showcase project; if you want the original visual mockups for inspiration, ask the source-app maintainer for `.superpowers/brainstorm/13349-1780068449/content/` (those mockups are HTML and run standalone).
