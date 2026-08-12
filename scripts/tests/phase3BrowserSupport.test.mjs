import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import http from 'node:http'
import net from 'node:net'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { reserveLocalPort } from '../../frontend/e2e/support/product-runner.mjs'


const unsafeEvidence = [
  'https://outside.example/v1?token=browser-secret',
  'Authorization: Bearer browser-secret',
  'api_key=browser-secret',
  'C:\\private\\browser-secret.txt',
  'mysql://user:browser-secret@127.0.0.1:3306/private',
  'SELECT secret FROM private_table',
  'provider request body browser-secret',
]


function assertSafe(value) {
  const rendered = String(value)
  for (const evidence of unsafeEvidence) {
    assert.doesNotMatch(rendered, new RegExp(
      evidence.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'),
      'u',
    ))
  }
}


function request(options) {
  return new Promise((resolve, reject) => {
    const pending = http.request(options, response => {
      response.resume()
      response.once('end', () => resolve(response.statusCode))
    })
    pending.once('error', reject)
    pending.end()
  })
}


function connect(port) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ host: '127.0.0.1', port })
    let response = ''
    socket.setEncoding('utf8')
    socket.setTimeout(5_000)
    socket.once('error', reject)
    socket.once('timeout', () => {
      socket.destroy()
      reject(new Error('deny proxy CONNECT timed out'))
    })
    socket.on('data', chunk => {
      response += chunk
    })
    socket.once('connect', () => {
      socket.write(
        'CONNECT outside.example:443 HTTP/1.1\r\n'
          + 'Host: outside.example:443\r\n'
          + `Authorization: Bearer ${unsafeEvidence[0]}\r\n`
          + '\r\n',
      )
    })
    socket.once('end', () => resolve(response))
  })
}


async function waitForHealth(port, nonce) {
  const deadline = Date.now() + 5_000
  let lastError = null
  while (Date.now() < deadline) {
    try {
      const result = await new Promise((resolve, reject) => {
        http.get(`http://127.0.0.1:${String(port)}/health`, response => {
          const chunks = []
          response.on('data', chunk => chunks.push(chunk))
          response.once('end', () => resolve({
            status: response.statusCode,
            body: Buffer.concat(chunks).toString('utf8'),
          }))
        }).once('error', reject)
      })
      if (result.status === 200 && JSON.parse(result.body).browserRunNonce === nonce) {
        return
      }
    } catch (error) {
      lastError = error
    }
    await new Promise(resolve => setTimeout(resolve, 25))
  }
  throw lastError || new Error('deny proxy did not become healthy')
}


async function stopChild(child) {
  if (!child || child.exitCode !== null) return
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      reject(new Error('deny proxy child did not stop'))
    }, 5_000)
    child.once('exit', () => {
      clearTimeout(timer)
      resolve()
    })
    child.kill('SIGTERM')
  })
}


async function assertPortReleased(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer()
    probe.once('error', reject)
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      probe.close(error => error ? reject(error) : resolve())
    })
  })
}


async function runDenyProxyLifecycle({
  body,
  stopChildImpl = stopChild,
  releaseReservationImpl = reservation => reservation.release(),
  auditPortImpl = assertPortReleased,
  removeRootImpl = root => rmSync(root, { recursive: true, force: true }),
}) {
  const state = {
    child: null,
    reservation: null,
    port: null,
    root: null,
  }
  const errors = []
  try {
    await body(state)
  } catch (error) {
    errors.push(error)
  }
  const stages = [
    ['child', state.child !== null, () => stopChildImpl(state.child)],
    ['reservation', state.reservation !== null, () => (
      releaseReservationImpl(state.reservation)
    )],
    ['port', Number.isInteger(state.port), () => auditPortImpl(state.port)],
    ['root', state.root !== null, () => removeRootImpl(state.root)],
  ]
  for (const [_name, enabled, cleanup] of stages) {
    if (!enabled) continue
    try {
      await cleanup()
    } catch (error) {
      errors.push(error)
    }
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(errors, 'deny proxy test lifecycle cleanup failed')
  }
  return state
}


test('deny proxy lifecycle cleanup continues in order and preserves every original failure', async () => {
  const bodyError = new Error('body failed')
  const childError = new Error('child cleanup failed')
  const reservationError = new Error('reservation cleanup failed')
  const portError = new Error('port cleanup failed')
  const rootError = new Error('root cleanup failed')
  const calls = []
  let rejection = null
  try {
    await runDenyProxyLifecycle({
      async body(state) {
        state.child = {}
        state.reservation = {}
        state.port = 12345
        state.root = 'owned-root'
        throw bodyError
      },
      async stopChildImpl() {
        calls.push('child')
        throw childError
      },
      async releaseReservationImpl() {
        calls.push('reservation')
        throw reservationError
      },
      async auditPortImpl() {
        calls.push('port')
        throw portError
      },
      async removeRootImpl() {
        calls.push('root')
        throw rootError
      },
    })
  } catch (error) {
    rejection = error
  }
  assert.deepEqual(calls, ['child', 'reservation', 'port', 'root'])
  assert.ok(rejection instanceof AggregateError)
  assert.deepEqual(rejection.errors, [
    bodyError,
    childError,
    reservationError,
    portError,
    rootError,
  ])

  const single = new Error('single body failure')
  let singleRejection = null
  try {
    await runDenyProxyLifecycle({
      async body() {
        throw single
      },
    })
  } catch (error) {
    singleRejection = error
  }
  assert.equal(singleRejection, single)
})


test('deny proxy executable permits only owned loopback health and safely records HTTP and CONNECT denial', async () => {
  const { DENY_PROXY_SOURCE, assertDenyProxyLedger } = await import(
    '../../frontend/e2e/support/deny-proxy.mjs'
  )
  let root = null
  const nonce = 'deny-proxy-test-nonce'
  await runDenyProxyLifecycle({
    async body(state) {
      root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-deny-proxy-'))
      state.root = root
      const sourcePath = path.join(root, 'deny-proxy.cjs')
      const ledgerPath = path.join(root, 'deny-proxy.log')
      state.reservation = await reserveLocalPort()
      state.port = state.reservation.port
      writeFileSync(sourcePath, DENY_PROXY_SOURCE, { encoding: 'utf8', flag: 'wx' })
      writeFileSync(ledgerPath, '', { encoding: 'utf8', flag: 'wx' })
      await state.reservation.release()
      state.child = spawn(process.execPath, [sourcePath, String(state.port)], {
        env: {
          ...process.env,
          M2_BROWSER_RUN_NONCE: nonce,
          BROWSER_DENY_PROXY_LEDGER_PATH: ledgerPath,
        },
        shell: false,
        stdio: 'ignore',
        windowsHide: true,
      })
      await waitForHealth(state.port, nonce)
      assert.equal(await request({
        host: '127.0.0.1',
        port: state.port,
        method: 'GET',
        path: unsafeEvidence[0],
        headers: { authorization: unsafeEvidence[1] },
      }), 502)
      assert.match(
        await connect(state.port),
        /^HTTP\/1\.1 502 Bad Gateway\r?\n/u,
      )
      const ledger = readFileSync(ledgerPath, 'utf8')
      assert.deepEqual(ledger.split(/\r?\n/u).filter(Boolean), [
        'http-denied',
        'connect-denied',
      ])
      assertSafe(ledger)
      assert.deepEqual(assertDenyProxyLedger(ledger, {
        expectedHttpCount: 1,
        expectedConnectCount: 1,
      }), {
        deniedHttpCount: 1,
        deniedConnectCount: 1,
        liveWebsiteAccessCount: 0,
      })
    },
  })
  assert.equal(existsSync(root), false)
})


test('database residue accepts only the exact owned disposable database and reports only counters', async () => {
  const { assertDatabaseResidue } = await import(
    '../../frontend/e2e/support/database-residue.mjs'
  )
  const ownedDatabaseName = `novel_creator_test_${'a'.repeat(32)}`
  const otherDisposableName = `novel_creator_test_${'b'.repeat(32)}`
  const counters = { created: 1, cleaned: 1, remaining: 0 }

  assert.deepEqual(
    assertDatabaseResidue(ownedDatabaseName, ownedDatabaseName, counters),
    counters,
  )
  for (const actualDatabaseName of [
    otherDisposableName,
    'novel_creator_test_fixed',
    `${ownedDatabaseName}x`,
    unsafeEvidence[4],
  ]) {
    assert.throws(
      () => assertDatabaseResidue(
        ownedDatabaseName,
        actualDatabaseName,
        counters,
      ),
      error => {
        assertSafe(error?.message)
        assert.doesNotMatch(error?.message || '', new RegExp(ownedDatabaseName, 'u'))
        assert.doesNotMatch(error?.message || '', new RegExp(otherDisposableName, 'u'))
        return error?.message === 'database residue accounting is invalid'
      },
    )
  }
  assert.throws(
    () => assertDatabaseResidue(ownedDatabaseName, ownedDatabaseName, {
      created: 1,
      cleaned: 0,
      remaining: 1,
    }),
    error => {
      assertSafe(error?.message)
      return error?.message === 'database residue accounting is invalid'
    },
  )
})


test('safe lifecycle diagnostics preserve explicit stage categories for every flattened leaf without evidence', async () => {
  const { formatSafeLifecycleDiagnostics } = await import(
    '../../frontend/e2e/support/safe-diagnostics.mjs'
  )
  const diagnostics = formatSafeLifecycleDiagnostics([
    { category: 'initialization', error: new Error(unsafeEvidence[0]) },
    {
      category: 'browser',
      error: new AggregateError([
        new Error(unsafeEvidence[1]),
        new TypeError(unsafeEvidence[2]),
      ], unsafeEvidence[3]),
    },
    { category: 'audit', error: new Error(unsafeEvidence[4]) },
    { category: 'cleanup', error: new Error(unsafeEvidence[5]) },
    { category: 'untrusted', error: new Error(unsafeEvidence[6]) },
  ])
  assert.deepEqual(diagnostics, {
    errorCount: 6,
    categories: [
      'initialization',
      'browser',
      'browser',
      'audit',
      'cleanup',
      'lifecycle',
    ],
  })
  assertSafe(JSON.stringify(diagnostics))
})


test('safe lifecycle diagnostics reject malformed entries and count cyclic aggregates safely', async () => {
  const { formatSafeLifecycleDiagnostics } = await import(
    '../../frontend/e2e/support/safe-diagnostics.mjs'
  )
  for (const invalid of [
    null,
    'not-an-entry-list',
    {},
    [null],
    ['not-an-entry'],
    [{ category: 'audit' }],
  ]) {
    assert.throws(
      () => formatSafeLifecycleDiagnostics(invalid),
      error => {
        assert.equal(error?.name, 'TypeError')
        assert.equal(error?.message, 'safe lifecycle diagnostics entries are invalid')
        assertSafe(error?.message)
        return true
      },
    )
  }
  const selfReferential = new AggregateError([], unsafeEvidence[0])
  selfReferential.errors.push(selfReferential)
  assert.deepEqual(formatSafeLifecycleDiagnostics([
    { category: 'audit', error: selfReferential },
  ]), {
    errorCount: 0,
    categories: [],
  })

  const shared = new Error(unsafeEvidence[1])
  const nested = new AggregateError([shared], unsafeEvidence[2])
  const root = new AggregateError([shared, nested], unsafeEvidence[3])
  assert.deepEqual(formatSafeLifecycleDiagnostics([
    { category: 'browser', error: root },
  ]), {
    errorCount: 1,
    categories: ['browser'],
  })
})


test('Phase 3C resource accounting folds database residue helper errors into the contextual aggregate contract', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const root = path.join(os.tmpdir(), 'novel-creator-phase3c-resource-accounting')
  const databaseName = `novel_creator_test_${'d'.repeat(32)}`
  let rejection = null

  try {
    runner.assertPhase3CResourceAccounting({
      databaseName,
      databaseCreated: 1,
      databaseCleaned: 1,
      databaseRemaining: 0,
      ownedRootRemoved: true,
      browserNetworkAudit: {
        forbiddenRequestCount: 0,
        forbiddenResponseCount: 0,
      },
      denyProxyAudit: {
        deniedHttpCount: 0,
        deniedConnectCount: 0,
        liveWebsiteAccessCount: 0,
      },
      scenario: 'manual',
      ownedRoot: root,
      artifactRoot: path.join(root, 'artifacts'),
      resultPath: path.join(root, 'browser-result.json'),
      sensitiveValues: [databaseName, unsafeEvidence[0]],
      assertDatabaseResidueImpl() {
        throw new Error(unsafeEvidence[0])
      },
    })
  } catch (error) {
    rejection = error
  }

  assert.ok(rejection instanceof AggregateError)
  assert.equal(rejection.message, 'Phase 3C resource accounting failed')
  const diagnostic = runner.formatPhase3CCommandFailure(rejection, {
    environment: { PHASE3C_GREP: '@manual' },
  })
  assert.match(diagnostic, /scenario=manual/u)
  assert.match(diagnostic, /trace=/u)
  assert.match(diagnostic, /result=/u)
  assertSafe(diagnostic)
})


test('Phase 3C command diagnostics retain baseline fields while redacting configured sensitive evidence', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const root = path.join(os.tmpdir(), 'novel-creator-phase3c-diagnostics')
  const error = new Error(unsafeEvidence.join('\n'))
  runner.attachPhase3CFailureContext(error, {
    scenario: 'manual',
    ownedRoot: root,
    artifactRoot: path.join(root, 'artifacts'),
    resultPath: path.join(root, 'browser-result.json'),
    sensitiveValues: unsafeEvidence,
  })
  const diagnostic = runner.formatPhase3CCommandFailure(error, {
    environment: {
      PHASE3C_GREP: '@manual',
      TEST_MYSQL_PASSWORD: 'browser-secret',
      BROWSER_TEST_DATABASE: `novel_creator_test_${'c'.repeat(32)}`,
    },
  })
  assert.match(diagnostic, /^Phase 3C browser runner failed\./u)
  assert.match(diagnostic, /scenario=manual/u)
  assert.match(diagnostic, /error\.count=1/u)
  assert.match(diagnostic, /error\[1\]\.name=Error/u)
  assert.match(diagnostic, /error\[1\]\.message=/u)
  assert.match(diagnostic, /error\[1\]\.stack=/u)
  assert.match(diagnostic, /trace=/u)
  assert.match(diagnostic, /result=/u)
  assertSafe(diagnostic)
})
