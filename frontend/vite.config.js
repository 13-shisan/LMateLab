import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import process from 'node:process'
import { fileURLToPath, URL } from 'node:url'

const appEntry = process.env.VITE_LMATELAB_EDITION === '107cup'
  ? './src/App107Cup.jsx'
  : './src/App.jsx'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@lmatelab-app': fileURLToPath(new URL(appEntry, import.meta.url)),
    },
  },
})
