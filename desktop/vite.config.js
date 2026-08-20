import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { createRequire } from 'module';

const require = createRequire(import.meta.url);

export default defineConfig({
  plugins: [react()],
  // Tauri serves the built assets from a file:// context, so paths must be relative.
  base: './',
  build: { outDir: 'dist', emptyOutDir: true },
  server: { port: 5174, strictPort: true },
  clearScreen: false,
})
