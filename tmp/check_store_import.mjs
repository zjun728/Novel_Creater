import { spawn } from 'node:child_process'
import { mkdirSync, rmSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'

const ROOT = resolve('.')
const APP_URL = 'http://127.0.0.1:5173'
const CHROME_PATH = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const PROFILE_DIR = join(ROOT, 'tmp', 'store-import-profile')

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function waitForHttp(url, timeoutMs = 15000) {
  const started = Date.now()
  let last = ''
  while (Date.now() - started < timeoutMs) {
    try {
      const res = await fetch(url, { signal: AbortSignal.timeout(2000) })
      if (res.ok) return true
      last = `HTTP ${res.status}`
    } catch (e) {
      last = e.message
    }
    await sleep(300)
  }
  throw new Error(`wait timeout: ${url}; ${last}`)
}

class CdpClient {
  constructor(wsUrl) {
    this.wsUrl = wsUrl
    this.nextId = 1
    this.pending = new Map()
  }

  async connect() {
    this.ws = new WebSocket(this.wsUrl)
    this.ws.onmessage = event => {
      const msg = JSON.parse(event.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        if (msg.error) reject(new Error(msg.error.message))
        else resolve(msg.result)
      }
    }
    await new Promise((resolve, reject) => {
      this.ws.onopen = resolve
      this.ws.onerror = reject
    })
  }

  send(method, params = {}) {
    const id = this.nextId++
    this.ws.send(JSON.stringify({ id, method, params }))
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }))
  }

  close() {
    this.ws?.close()
  }
}

async function main() {
  if (existsSync(PROFILE_DIR)) rmSync(PROFILE_DIR, { recursive: true, force: true })
  mkdirSync(PROFILE_DIR, { recursive: true })
  const port = 9300 + Math.floor(Math.random() * 500)
  const chrome = spawn(CHROME_PATH, [
    '--headless=new',
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${PROFILE_DIR}`,
    '--disable-gpu',
    '--disable-dev-shm-usage',
    '--no-sandbox',
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-extensions',
    'about:blank'
  ], { stdio: 'ignore', windowsHide: true })

  try {
    await waitForHttp(`http://127.0.0.1:${port}/json/version`)
    const tabs = await fetch(`http://127.0.0.1:${port}/json/list`).then(r => r.json())
    const page = tabs.find(t => t.type === 'page') || tabs[0]
    const cdp = new CdpClient(page.webSocketDebuggerUrl)
    await cdp.connect()
    await cdp.send('Page.enable')
    await cdp.send('Runtime.enable')
    await cdp.send('Page.navigate', { url: APP_URL })
    await sleep(1200)
    const result = await cdp.send('Runtime.evaluate', {
      expression: `(async () => {
        const providerModule = await import('${APP_URL}/src/stores/providerStore.js')
        const store = providerModule.useProviderStore()
        await store.ensureProvidersLoaded()
        return {
          ok: true,
          providerCount: store.providers.length,
          providers: store.providers.map(p => ({ name: p.name, model: p.model }))
        }
      })()`,
      awaitPromise: true,
      returnByValue: true
    })
    if (result.exceptionDetails) {
      console.log(JSON.stringify({ ok: false, error: result.exceptionDetails.text, details: result.exceptionDetails }, null, 2))
    } else {
      console.log(JSON.stringify(result.result.value, null, 2))
    }
    cdp.close()
  } finally {
    chrome.kill()
    await sleep(500)
    try {
      rmSync(PROFILE_DIR, { recursive: true, force: true, maxRetries: 3, retryDelay: 300 })
    } catch {
      // Chrome may keep a profile handle briefly; this diagnostic script can leave it behind.
    }
  }
}

main().catch(err => {
  console.error(err.stack || err.message)
  process.exit(1)
})
