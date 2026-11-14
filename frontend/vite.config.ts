import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

/**
 * `--mode live` (npm run dev:live / build:live): every feature whose backend endpoint exists.
 * Privacy and audit stay on demo data until those endpoints land; then build with
 * VITE_USE_MOCK=false (or add them to VITE_LIVE).
 */
const LIVE_NOW = 'agent,assets,bad_actors,risk,work_orders,inspections,summary,failure_modes,mtbf,upload,documents'

// The FastAPI backend runs on :8000. In dev, /api is proxied there, so the
// frontend never calls an absolute URL and works the same behind the gateway.
export default defineConfig(({ mode }) => {
  if (mode === 'live') process.env.VITE_LIVE ??= LIVE_NOW
  return {
    plugins: [react(), tailwindcss()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: process.env.VITE_BACKEND_URL ?? 'http://127.0.0.1:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
