// Use vitest/config's defineConfig: it's a superset of vite's that also types the `test:` key. Avoids TS2769.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // All FastAPI endpoints are now reached via /api/* in unified-serve
      // mode (where FastAPI's StaticFiles fallback at / serves the SPA on
      // unknown paths). The single /api proxy forwards everything; future
      // API endpoints don't need to be added here per-path. Existing API
      // endpoints (/retrieve, /query, /health, /config) currently stay at
      // their root paths in this packet — their migration under /api/* will
      // land in the packet that wires the matching React routes (e.g. P0-C
      // bringing /config and /compare React routes online).
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/__tests__/setup.ts'],
  },
})
