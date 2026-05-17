import { defineConfig, createLogger } from 'vite'
import react from '@vitejs/plugin-react'

// A custom logger that filters out the noisy
//   [vite] http proxy error: /api/...
//   Error: connect ECONNREFUSED 127.0.0.1:8000
// stack traces that Vite logs natively whenever the backend isn't up yet.
// We collapse them to a single line per outage.
const logger = createLogger()
const originalError = logger.error.bind(logger)
let suppressed = false

logger.error = (msg, options) => {
  const text = typeof msg === 'string' ? msg : String(msg)
  if (text.includes('http proxy error') && (text.includes('ECONNREFUSED') || text.includes('connect ECONNREFUSED'))) {
    if (!suppressed) {
      // eslint-disable-next-line no-console
      console.warn(
        '[vite] backend offline at http://127.0.0.1:8000 — waiting for `python server.py` to come up. ' +
        'Suppressing further proxy ECONNREFUSED stacks until it does.'
      )
      suppressed = true
    }
    return
  }
  // Any unrelated error → assume backend is responsive again, reset the gate.
  suppressed = false
  originalError(msg, options)
}

export default defineConfig({
  customLogger: logger,
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // Send a clean 503 so the frontend can show the "Backend offline" banner instead
        // of a generic fetch failure.
        configure: (proxy) => {
          proxy.on('error', (err, req, res) => {
            if (err && err.code === 'ECONNREFUSED') {
              try {
                if (!res.headersSent) {
                  res.writeHead(503, { 'Content-Type': 'application/json' })
                }
                res.end(JSON.stringify({ error: 'backend_offline' }))
              } catch { /* socket gone */ }
            }
          })
          proxy.on('proxyRes', () => {
            // Reset the suppression gate so a fresh outage logs again.
            suppressed = false
          })
        },
      },
    },
  },
})
