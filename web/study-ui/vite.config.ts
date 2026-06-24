import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8097',
      '/healthz': 'http://127.0.0.1:8097',
      '/grafana': 'http://127.0.0.1:3000'
    }
  }
})
