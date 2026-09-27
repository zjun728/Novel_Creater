import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { once } from 'node:events'
import test from 'node:test'
import { spawnOwnedChild, terminateOwnedProcessTree } from '../../frontend/e2e/support/product-runner.mjs'

// Exercise the real supervisor and child; only the failed taskkill is injected.
test('Windows taskkill failure still closes the owned job and its child', { skip: process.platform !== 'win32', timeout: 20000 }, async () => {
  const child = spawnOwnedChild(process.execPath,
    ['-e', 'console.log(process.pid); setInterval(() => {}, 1000)'], {})
  const closed = once(child, 'close')
  try {
    const [chunk] = await once(child.stdout, 'data', { signal: AbortSignal.timeout(12000) })
    const pid = Number(chunk.toString().trim())
    assert.ok(Number.isSafeInteger(pid) && pid > 0)
    await terminateOwnedProcessTree(child, {
      timeoutMs: 3000,
      spawnImpl() {
        const failed = new EventEmitter()
        setImmediate(() => failed.emit('close', 1))
        return failed
      },
    })
    await closed
    assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' })
  } finally {
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
    await closed
  }
})
