import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const readWorkspaceFile = async relativePath => {
  try {
    return await readFile(new URL(`../../${relativePath}`, import.meta.url), 'utf8')
  } catch (error) {
    if (error?.code === 'ENOENT') return ''
    throw error
  }
}

test('Playwright config owns two isolated loopback servers and repository artifacts', async () => {
  const source = await readWorkspaceFile('frontend/playwright.config.ts')

  assert.match(source, /defineConfig/)
  assert.match(source, /baseURL:\s*['"]http:\/\/127\.0\.0\.1:5173['"]/)
  assert.match(source, /127\.0\.0\.1.*8000/)
  assert.match(source, /127\.0\.0\.1.*5173/)
  assert.equal((source.match(/reuseExistingServer:\s*false/g) || []).length, 2)
  assert.match(source, /outputDir:\s*['"]\.\.\/output\/playwright\/test-results['"]/)
  assert.match(source, /trace:\s*['"]retain-on-failure['"]/)
  assert.match(source, /screenshot:\s*['"]only-on-failure['"]/)
  assert.match(source, /process\.env\.PYTHON\s*\|\|\s*['"]python['"]/)
  assert.match(source, /shellQuoteExecutable/)
  assert.match(source, /command:\s*`\$\{pythonExecutable\}\s+-m\s+uvicorn/)
})

test('M1 browser spec defines exactly two real-page goals with no direct API writes', async () => {
  const source = await readWorkspaceFile('frontend/e2e/milestone1.spec.ts')

  assert.equal((source.match(/\btest\s*\(/g) || []).length, 2)
  assert.match(source, /page\.goto\(['"]\/['"]\)/)
  assert.match(source, /page\.goto\(['"]\/writer\/project-1\/1['"]\)/)
  assert.doesNotMatch(source, /page\.request|request\.(?:post|put|patch|delete)\s*\(|fetch\s*\(|route\.(?:fulfill|continue)\s*\(/)
})

test('M1 browser spec awaits every API body and rejects runtime failures and leaks', async () => {
  const source = await readWorkspaceFile('frontend/e2e/milestone1.spec.ts')

  for (const required of [
    "page.on('response'", "page.on('console'", "page.on('pageerror'",
    "page.on('requestfailed'", 'apiBodyPromises.push', 'response.text()',
    'Promise.all(apiBodyPromises)', 'response.status()', 'consoleErrors',
    'response.request().method()', 'consoleMessages', 'pageErrors',
    'requestFailures', 'responseFailures', 'apiFailures', 'apiWriteMethods',
    'apiBodyReadFailures', 'bodyReadError', 'requiredTestEnvironment',
    'BROWSER_SECRET_SENTINEL', 'BROWSER_PRIVATE_PROVIDER_URL',
    'BROWSER_TEST_DATABASE', 'api[_-]?key',
  ]) {
    assert.equal(source.includes(required), true, `missing browser diagnostic contract: ${required}`)
  }
  assert.match(source, /READ_METHODS\.has\(response\.method\)/)
  assert.match(source, /expect\(apiWriteMethods[^]*?\.toEqual\(\[\]\)/)
  assert.match(source, /expect\(apiBodyReadFailures[^]*?\.toEqual\(\[\]\)/)
  assert.match(source, /expect\(responseFailures[^]*?\.toEqual\(\[\]\)/)
  assert.doesNotMatch(source, /browser-secret-must-not-leak|private-provider\.example/)
})

test('M1 browser goals cover foundation state, disabled writer, settings read and old URL return', async () => {
  const source = await readWorkspaceFile('frontend/e2e/milestone1.spec.ts')

  for (const required of [
    '永乐大典', '永乐长明', '文渊山海', '典镇山河', '已选定',
    'writer-core-v1.0.0', 'Canon 0', 'Projection 0', '状态同步',
    '进入写作台', 'toBeDisabled', '设置', '写作内核尚未开放',
    '旧章节、临时草稿和版本定稿链已停用', '返回项目',
    'toHaveURL',
  ]) {
    assert.equal(source.includes(required), true, `missing M1 browser assertion: ${required}`)
  }
  assert.match(
    source,
    /getByRole\(['"]menuitem['"],\s*\{\s*name:\s*['"]项目库['"]\s*\}\)\.click\(\)[^]*?getByRole\(['"]heading['"],\s*\{\s*name:\s*['"]永乐大典['"]/,
  )
  assert.doesNotMatch(
    source,
    /getByRole\(['"]menuitem['"],\s*\{\s*name:\s*['"]永乐大典['"]/,
  )
})

test('frontend exposes only the guarded runner as its e2e command', async () => {
  const packageJson = JSON.parse(await readWorkspaceFile('frontend/package.json'))

  assert.equal(packageJson.scripts?.['test:e2e'], 'node e2e/run-milestone1.mjs')
})

test('runner injects fixture leak sentinels while the spec contains no literal values', async () => {
  const [runner, prepare, spec] = await Promise.all([
    readWorkspaceFile('frontend/e2e/run-milestone1.mjs'),
    readWorkspaceFile('backend/scripts/prepare_milestone1_browser_db.py'),
    readWorkspaceFile('frontend/e2e/milestone1.spec.ts'),
  ])
  const fixtures = [
    ['BROWSER_SECRET_SENTINEL', 'browser-secret-must-not-leak'],
    ['BROWSER_PRIVATE_PROVIDER_URL', 'https://private-provider.example/v1'],
  ]
  for (const [environmentName, value] of fixtures) {
    assert.equal(runner.includes(environmentName), true)
    assert.equal(runner.includes(value), true)
    assert.equal(prepare.includes(value), true)
    assert.equal(spec.includes(value), false)
  }
  assert.match(runner, /BROWSER_TEST_DATABASE:\s*databaseName/)
})
