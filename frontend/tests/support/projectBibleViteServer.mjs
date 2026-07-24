import { fileURLToPath } from 'node:url'

import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const sourceRoot = fileURLToPath(new URL('../../src', import.meta.url))

export function projectBibleViteConfig() {
  return {
    configFile: false,
    root: frontendRoot,
    resolve: { alias: { '@': sourceRoot } },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin()],
    optimizeDeps: { noDiscovery: true },
  }
}

export function createProjectBibleViteServer() {
  return createServer(projectBibleViteConfig())
}
