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


test('server observer detects password database or DSN leaks after truncation without echo', async () => {
  const { browserSensitiveValues } = await import('../../frontend/e2e/run-milestone2.mjs')
  const { createServerLogObserver } = await import('../../frontend/e2e/server-log-observer.mjs')
  const environment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'browser:user',
    TEST_MYSQL_PASSWORD: 'p@ss:/word',
  }
  const database = 'novel_creator_test_0123456789abcdef0123456789abcdef'
  const root = 'C:\\Temp\\novel-creator-m2-corpus-sensitive'
  const values = browserSensitiveValues(environment, database, root)
  const rawDsn = `mysql://${environment.TEST_MYSQL_USER}:${environment.TEST_MYSQL_PASSWORD}`
    + `@${environment.TEST_MYSQL_HOST}:${environment.TEST_MYSQL_PORT}/${database}`
  const encodedDsn = `mysql://${encodeURIComponent(environment.TEST_MYSQL_USER)}`
    + `:${encodeURIComponent(environment.TEST_MYSQL_PASSWORD)}`
    + `@${environment.TEST_MYSQL_HOST}:${environment.TEST_MYSQL_PORT}/${database}`

  for (const leaked of [environment.TEST_MYSQL_PASSWORD, database, rawDsn, encodedDsn]) {
    const child = fakeChild()
    const observer = createServerLogObserver(child, { maxBytes: 8, sensitiveValues: values })
    child.stdout.emit('data', 'ordinary-prefix-that-truncates')
    child.stderr.emit('data', leaked)
    const result = observer.finish(values)
    assert.equal(result.matchCount > 0, true)
    assert.equal(result.truncated, true)
    assert.deepEqual(Object.keys(result), ['matchCount', 'truncated'])
    assert.equal(JSON.stringify(result).includes(leaked), false)
  }
})
