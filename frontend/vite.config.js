import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

const projectRoot = fileURLToPath(new URL('.', import.meta.url))

export function m2BrowserOwnershipPlugin(nonce) {
  return {
    name: 'm2-browser-ownership',
    configureServer(server) {
      server.middlewares.use('/__m2-browser-owner', (request, response, next) => {
        if (request.method !== 'GET') {
          next()
          return
        }
        response.statusCode = 200
        response.setHeader('content-type', 'application/json; charset=utf-8')
        response.end(JSON.stringify({ browserRunNonce: nonce }))
      })
    },
  }
}

const browserRunNonce = process.env.M2_BROWSER_RUN_NONCE

export default defineConfig({
  root: projectRoot,
  plugins: [
    vue(),
    tailwindcss(),
    ...(browserRunNonce ? [m2BrowserOwnershipPlugin(browserRunNonce)] : []),
  ],
  // Keep ordinary entrypoints aligned with the backend's explicit CORS origins.
  // Custom CLI ports must be paired with CORS_ALLOWED_ORIGINS on the backend.
  server: {
    port: 5173,
    strictPort: true,
  },
  preview: {
    port: 5173,
    strictPort: true,
  },
  build: {
    emptyOutDir: true
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  }
})
