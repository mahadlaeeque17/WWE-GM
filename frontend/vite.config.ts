import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    strictPort: true,
    // Proxying keeps the browser on one origin, so CORS never enters the picture
    // and the launcher does not have to inject an API base URL.
    proxy: {
      '/api': { target: 'http://127.0.0.1:8010', changeOrigin: true },
    },
  },
})
