import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'


function fakeChild() {
  return { stdout: new EventEmitter(), stderr: new EventEmitter() }
}


test('server observer captures bounded streams and reports only sensitive match count', async () => {
  const { createServerLogObserver } = await import('../../frontend/e2e/server-log-observer.mjs')
  const child = fakeChild()
  const secret = 'private-server-value'
  const observer = createServerLogObserver(child, { maxBytes: 32 })

  child.stdout.emit('data', Buffer.from(`prefix ${secret} suffix`))
  child.stderr.emit('data', Buffer.from('x'.repeat(128)))
  const result = observer.finish([secret])

  assert.equal(result.matchCount, 1)
  assert.equal(result.truncated, true)
  assert.deepEqual(Object.keys(result), ['matchCount', 'truncated'])
  assert.equal(JSON.stringify(result).includes(secret), false)
  assert.equal(child.stdout.listenerCount('data'), 0)
  assert.equal(child.stderr.listenerCount('data'), 0)
})


test('server observer counts fixed and dynamic sentinels without echoing either', async () => {
  const { createServerLogObserver } = await import('../../frontend/e2e/server-log-observer.mjs')
  const child = fakeChild()
  const observer = createServerLogObserver(child)
  const fixed = 'browser-secret-must-not-leak'
  const dynamic = 'C:\\Temp\\novel-creator-m2-corpus-private'

  child.stdout.emit('data', `${fixed}\n${dynamic}\n${fixed}`)
  const result = observer.finish([fixed, dynamic])

  assert.deepEqual(result, { matchCount: 3, truncated: false })
  assert.equal(JSON.stringify(result).includes(fixed), false)
  assert.equal(JSON.stringify(result).includes(dynamic), false)
})


test('server observer scans the full stream even after bounded capture truncates', async () => {
  const { createServerLogObserver } = await import('../../frontend/e2e/server-log-observer.mjs')
  const child = fakeChild()
  const secret = 'late-private-value'
  const observer = createServerLogObserver(child, {
    maxBytes: 16,
    sensitiveValues: [secret],
  })

  child.stdout.emit('data', 'ordinary-prefix'.repeat(20))
  child.stdout.emit('data', 'late-private-')
  child.stdout.emit('data', 'value')

  assert.deepEqual(observer.finish([secret]), { matchCount: 1, truncated: true })
})
