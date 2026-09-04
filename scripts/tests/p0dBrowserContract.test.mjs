import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const runnerPath = path.join(repositoryRoot, 'frontend', 'e2e', 'run-p0-d.mjs')
const specPath = path.join(repositoryRoot, 'frontend', 'e2e', 'p0-d-creative-foundation.spec.ts')

const TEST_ENVIRONMENT = Object.freeze({
  PATH: process.env.PATH || '',
  TEST_MYSQL_HOST: '127.0.0.1',
  TEST_MYSQL_PORT: '3307',
  TEST_MYSQL_USER: 'p0d-test-user',
  TEST_MYSQL_PASSWORD: 'p0d-test-password',
})

test('P0-D root setup failure retains its primary error and uses initialized cleanup authority', async () => {
  const runner = await import(`${new URL(`file:///${runnerPath.replaceAll('\\', '/')}`)}?case=early-root`)
  const commands = []

  await assert.rejects(
    runner.runP0D({
      environment: TEST_ENVIRONMENT,
      dependencies: {
        createOwnedRoot() {
          throw new Error('synthetic P0-D root setup failure')
        },
        async runBoundedOwnedCommand(command, args, options) {
          commands.push({ command, args, options })
        },
      },
    }),
    error => {
      assert.equal(error?.message, 'synthetic P0-D root setup failure')
      return true
    },
  )

  assert.equal(commands.length, 1)
  assert.deepEqual(commands[0].args.slice(0, 4), [
    '-m',
    'backend.scripts.prepare_product_shell_browser_db',
    '--database',
    commands[0].args.at(-2),
  ])
  assert.equal(commands[0].args.at(-1), '--drop')
  assert.match(commands[0].args.at(-2), /^novel_creator_test_[a-f0-9]{32}$/u)
  assert.equal(commands[0].options.env.TEST_MYSQL_PASSWORD, TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD)
})

test('P0-D browser contract closes runtime, persistence, and responsive audit gaps', async () => {
  const [runner, spec] = await Promise.all([
    readFile(runnerPath, 'utf8'),
    readFile(specPath, 'utf8'),
  ])

  assert.match(runner, /BROWSER_SECRET_SENTINEL:\s*PROVIDER_SECRET/u)
  assert.match(spec, /const\s+SENSITIVE_VALUES\s*=\s*runtimeSensitiveValues/u)
  assert.match(spec, /expect\(SENSITIVE_VALUES\.length\)\.toBeGreaterThan\(0\)/u)
  assert.match(spec, /assertRuntimeEvidenceHealthy\(evidence\)/u)
  assert.match(spec, /expect\(publicRuntimeDiagnostic\(evidence\)\.requestFailures\)\.toEqual\(\[\]\)/u)
  assert.match(runner, /target_words=2100000,\s*target_chapters=630/u)
  assert.match(runner, /project!=\{'target_words':2400000,'target_chapters':720\}/u)
  assert.match(spec, /expectCompleteConfirmedContract\(/u)
  assert.match(spec, /modelBindingRef:\s*\{\s*id:\s*preview\.bindingRef\.id,\s*revision:\s*preview\.bindingRef\.revision,\s*contentHash:\s*preview\.bindingRef\.contentHash,?\s*\}/u)
  assert.match(spec, /await expect\(page\.locator\('\.foundation-workspace'\)\)\.toBeVisible\(\)/u)
  assert.match(spec, /overflowingElements/u)
  assert.doesNotMatch(spec, /clipsOwnContent/u)
  assert.equal(
    spec.match(/await page\.waitForLoadState\('networkidle'\)\r?\n\s*await page\.reload\(\)/gu)?.length,
    4,
  )
})

test('P0-D embedded Python evidence source is syntactically valid', async () => {
  const runner = await readFile(runnerPath, 'utf8')
  const source = runner.match(/const VERIFY_SOURCE = String\.raw`([\s\S]*?)`\r?\n/u)?.[1]
  assert.ok(source, 'VERIFY_SOURCE must remain discoverable for syntax verification')

  const result = spawnSync('python', ['-c', "import sys; compile(sys.stdin.read(), '<VERIFY_SOURCE>', 'exec')"], {
    cwd: repositoryRoot,
    encoding: 'utf8',
    input: source,
  })

  assert.equal(result.status, 0, result.stderr)
})
