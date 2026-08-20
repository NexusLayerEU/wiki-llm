import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createRequire } from 'module';

const require = createRequire(import.meta.url);

// Built straight into the Python package, which is what FastAPI serves as the SPA.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../wikiforge/static',
    emptyOutDir: true,
    assetsDir: 'assets',
  },
  server: {
    // Dev server proxies the API so the front end runs on 5173 against a local backend.
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
      '/capabilities': 'http://127.0.0.1:8000',
    },
  },
})
