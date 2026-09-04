import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { runSuites } from '../run-tests.mjs'


const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const source = relative => readFileSync(path.join(root, relative), 'utf8')


test('Topic Center live gate is registered as one explicit browser suite', async () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(
    rootPackage.scripts['test:browser:topic-center-live'],
    'node scripts/run-tests.mjs browser-topic-center-live',
  )
  assert.equal(
    frontendPackage.scripts['test:e2e:topic-center-live'],
    'node e2e/run-topic-center-live.mjs --base-url http://127.0.0.1:5173',
  )
  assert.equal(
    frontendPackage.scripts['test:browser:topic-center-live'],
    'node ../scripts/run-tests.mjs browser-topic-center-live',
  )
  assert.equal(existsSync(path.join(root, 'frontend/e2e/run-topic-center-live.mjs')), true)

  const calls = []
  const result = runSuites(['browser-topic-center-live'], {
    rootDirectory: root,
    environment: {},
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
    pytestTempLifecycle: { prepare() {}, cleanupStage() {}, cleanupAll() {} },
  })
  assert.equal(result, 0)
  assert.deepEqual(calls.map(call => [call.command, call.args]), [[
    process.execPath,
    [
      'frontend/e2e/run-topic-center-live.mjs',
      '--base-url',
      'http://127.0.0.1:5173',
    ],
  ]])
  assert.equal(calls[0].options.shell, false)
})


test('live runner accepts only an exact loopback base URL', async () => {
  const runner = await import('../../frontend/e2e/run-topic-center-live.mjs')

  assert.equal(
    runner.parseBaseURL(['--base-url', 'http://127.0.0.1:5173']),
    'http://127.0.0.1:5173',
  )
  for (const argv of [
    [],
    ['--base-url', 'http://127.0.0.1:5173/'],
    ['--base-url', ' http://127.0.0.1:5173'],
    ['--base-url', 'http://localhost:5173'],
    ['--base-url', 'http://2130706433:5173'],
    ['--base-url', 'http://127.0.0.1:5173/%2e'],
    ['--base-url', 'https://example.com'],
    ['--base-url', 'http://127.0.0.1:5173/path'],
    ['--base-url', 'http://user@127.0.0.1:5173'],
    ['--base-url', 'http://127.0.0.1:5173', '--extra'],
  ]) assert.throws(() => runner.parseBaseURL(argv), /loopback base URL/u)
})


test('live runner uses truthful verified source identities and only browser UI actions', async () => {
  const runner = await import('../../frontend/e2e/run-topic-center-live.mjs')
  assert.deepEqual(runner.VERIFIED_SOURCES, [
    ['qq-reading.male-popular', 'QQ 阅读男生人气榜'],
    ['qimao.public-catalog', '七猫男生更新榜'],
    ['heiyan.daily-recommendation', '黑岩每日推荐榜'],
    ['readnovel.original-monthly-ticket', '小说阅读网原创月票榜'],
    ['xxsy.xiaoxiang-ticket', '潇湘票榜'],
  ])
  assert.equal(Object.isFrozen(runner.VERIFIED_SOURCES), true)
  assert.equal(runner.VERIFIED_SOURCES.every(Object.isFrozen), true)

  const body = source('frontend/e2e/run-topic-center-live.mjs')
  for (const marker of [
    "page.goto(`${baseURL}/topics/market`)",
    "name: `刷新${name}`",
    "name: `查看榜单作品：${evidenceName}`",
    "getByRole('list', { name: '榜单作品' })",
    "getByLabel('新讨论标题')",
    "getByLabel('继续讨论')",
    "name: '保存为方向'",
    "name: '保存为候选种子'",
    "name: '创建项目并检查种子'",
    "getByText('待确认'",
  ]) assert.equal(body.includes(marker), true, marker)
  assert.doesNotMatch(
    body,
    /page\.(?:route|request|evaluate)|route\.fulfill|\bfetch\s*\(|\baxios\b|\/api\//u,
  )
  assert.doesNotMatch(body, /provider.{0,30}(?:config|setting)|(?:config|setting).{0,30}provider/iu)
})


test('stale available snapshot cannot satisfy a refresh gate', async () => {
  const runner = await import('../../frontend/e2e/run-topic-center-live.mjs')
  const before = {
    snapshotId: 'old-snapshot', capturedAt: 100, entryCount: 20,
    lastSucceededAt: 100,
  }

  assert.equal(runner.freshSnapshotEvidence(before, before), false)
  assert.equal(runner.freshSnapshotEvidence(before, {
    ...before, lastSucceededAt: 200,
  }), true)
  assert.equal(runner.freshSnapshotEvidence(before, {
    ...before, capturedAt: 101, lastSucceededAt: 200,
  }), false)
  assert.equal(runner.freshSnapshotEvidence(before, {
    snapshotId: 'new-snapshot', capturedAt: 200, entryCount: 20,
    lastSucceededAt: 200,
  }), true)
  assert.equal(runner.freshSnapshotEvidence(before, {
    snapshotId: 'new-snapshot', capturedAt: 200, entryCount: 9,
    lastSucceededAt: 200,
  }), false)

  const body = source('frontend/e2e/run-topic-center-live.mjs')
  const busy = body.indexOf("toHaveAttribute('data-market-source-busy', 'true'")
  const idle = body.indexOf("toHaveAttribute('data-market-source-busy', 'false'")
  const available = body.indexOf("toHaveAttribute('data-market-source-status', 'available'")
  const freshness = body.lastIndexOf('freshSnapshotEvidence(before, after)')
  assert.equal(busy >= 0, true)
  assert.equal(idle > busy, true)
  assert.equal(available > idle, true)
  assert.equal(freshness > available, true)
})
