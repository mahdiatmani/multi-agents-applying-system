import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Cache bust comment
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
