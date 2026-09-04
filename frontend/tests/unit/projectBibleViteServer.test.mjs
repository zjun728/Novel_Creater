import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { projectBibleViteConfig } from '../support/projectBibleViteServer.mjs'

test('Project Bible Vite test servers disable dependency discovery', () => {
  const config = projectBibleViteConfig()

  assert.equal(config.configFile, false)
  assert.equal(config.server.middlewareMode, true)
  assert.equal(config.server.hmr, false)
  assert.equal(config.server.ws, false)
  assert.equal(config.appType, 'custom')
  assert.equal(config.logLevel, 'error')
  assert.deepEqual(config.optimizeDeps, { noDiscovery: true })
  assert.equal(config.plugins.length, 1)
  assert.ok(config.resolve.alias['@'])
})

test('Project Bible view tests create Vite servers only through the cache-safe helper', async () => {
  const suite = await readFile(new URL('./projectBibleView.test.mjs', import.meta.url), 'utf8')

  assert.doesNotMatch(suite, /from\s+['"]vite['"]/)
  assert.doesNotMatch(suite, /\bcreateServer\s*\(/)
  assert.equal(suite.match(/\bcreateProjectBibleViteServer\s*\(\s*\)/g)?.length, 13)
})
