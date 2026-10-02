import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { execFileSync } from 'node:child_process'
import { parseArgs } from 'node:util'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { resolveConfig } from '../../frontend/node_modules/vite/dist/node/index.js'

const root = fileURLToPath(new URL('../../', import.meta.url))
const frontend = path.join(root, 'frontend')
const scripts = JSON.parse(readFileSync(path.join(frontend, 'package.json'), 'utf8')).scripts
const batch = readFileSync(path.join(root, 'start_frontend.bat'), 'utf8')
const allowedOrigins = JSON.parse(execFileSync(process.env.PYTHON || 'python', [
  '-c', 'import json; from backend.config import load_cors_allowed_origins; print(json.dumps(load_cors_allowed_origins(environment={})))',
], { cwd: root, encoding: 'utf8', windowsHide: true }))

// Resolve the current entrypoints' actual CLI options through installed Vite.
function options(script, extra = '') {
  const args = `${script} ${extra}`.trim().split(/\s+/)
  assert.equal(args.shift(), 'vite')
  const section = args[0] === 'preview' ? (args.shift(), 'preview') : 'server'
  const { values } = parseArgs({ args, options: {
    host: { type: 'string' }, port: { type: 'string' }, strictPort: { type: 'boolean' },
  } })
  return { section, inline: { host: values.host,
    ...(values.port ? { port: Number(values.port) } : {}),
    ...(values.strictPort !== undefined ? { strictPort: values.strictPort } : {}),
  } }
}

async function resolved(script, extra) {
  const { section, inline } = options(script, extra)
  const isPreview = section === 'preview'
  const config = await resolveConfig({ root: frontend, configFile: path.join(frontend, 'vite.config.js'),
    [section]: inline,
  }, 'serve', isPreview ? 'production' : 'development', isPreview ? 'production' : 'development', isPreview)
  return config[section]
}

for (const name of ['dev', 'preview']) {
  test(`ordinary npm ${name} resolves one fixed allowed origin and rejects fallback`, async () => {
    const config = await resolved(scripts[name])
    assert.equal(config.host, '127.0.0.1')
    assert.equal(config.port, 5173)
    assert.equal(config.strictPort, true)
    assert.ok(allowedOrigins.includes(`http://${config.host}:${config.port}`))
  })
}

const batchLaunches = batch.split(/\r?\n/).flatMap(line => {
  const match = line.match(/\brun dev(?:\s+--\s+(.*))?$/)
  return match ? [match[1] || ''] : []
})
assert.equal(batchLaunches.length, 2, 'both installed-npm and PATH-npm batch branches must delegate to dev')
for (const [index, extra] of batchLaunches.entries()) {
  test(`batch branch ${index + 1} inherits the allowed origin and strict port`, async () => {
    const config = await resolved(scripts.dev, extra)
    assert.equal(config.strictPort, true)
    assert.ok(allowedOrigins.includes(`http://${config.host}:${config.port}`))
  })
}

test('explicit isolated dev and preview ports still override defaults without fallback', async () => {
  for (const name of ['dev', 'preview']) {
    const config = await resolved(scripts[name], '--port 15273')
    assert.equal(config.port, 15273)
    assert.equal(config.strictPort, true)
  }
})
