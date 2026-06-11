import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: '../webui',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/exams': 'http://localhost:8080',
      '/sse': 'http://localhost:8080',
      '/api': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
      '/debug': 'http://localhost:8080',
    }
  }
})
