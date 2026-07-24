import assert from 'node:assert/strict'
import { existsSync, readdirSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'


const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
)


function readWorkspaceFile(relativePath) {
  return readFileSync(path.join(repositoryRoot, relativePath), 'utf8')
}


const CURRENT_RUNTIME_ROOTS = Object.freeze([
  'backend',
  'frontend/src',
  'scripts',
])
const CURRENT_RUNTIME_EXTENSIONS = new Set([
  '.js',
  '.mjs',
  '.py',
  '.sql',
  '.vue',
])
const EXCLUDED_RUNTIME_DIRECTORIES = new Set([
  'backend/tests',
  'scripts/tests',
])


function currentRuntimeFiles() {
  const files = []
  const visit = (absolutePath) => {
    const relativePath = path.relative(repositoryRoot, absolutePath).replaceAll('\\', '/')
    if (EXCLUDED_RUNTIME_DIRECTORIES.has(relativePath)) {
      return
    }
    for (const entry of readdirSync(absolutePath, { withFileTypes: true })) {
      if (entry.name === '__pycache__' || entry.name === 'node_modules') {
        continue
      }
      const child = path.join(absolutePath, entry.name)
      if (entry.isDirectory()) {
        visit(child)
      } else if (CURRENT_RUNTIME_EXTENSIONS.has(path.extname(entry.name))) {
        files.push(child)
      }
    }
  }
  for (const relativeRoot of CURRENT_RUNTIME_ROOTS) {
    visit(path.join(repositoryRoot, relativeRoot))
  }
  return files.sort()
}


function retiredSqlPattern(tableName) {
  const identifier = '(?:`[^`\\r\\n]+`|[A-Za-z_][A-Za-z0-9_$]*)'
  const qualifier = `(?:${identifier}\\s*\\.\\s*)?`
  const table = `(?:\`${tableName}\`|${tableName})`
  const gap = '(?:\\s|/\\*[\\s\\S]*?\\*/|--[^\\r\\n]*(?:\\r?\\n|$)|#[^\\r\\n]*(?:\\r?\\n|$))+'
  return new RegExp(
    `(?:FROM|JOIN|INTO|UPDATE|(?:CREATE${gap})?TABLE|TRUNCATE(?:${gap}TABLE)?)${gap}${qualifier}${table}(?=\\s|$|[),;])`,
    'iu',
  )
}


function containsRetiredSql(source, tableName) {
  const identifier = '(?:`[^`\\r\\n]+`|[A-Za-z_][A-Za-z0-9_$]*)'
  const table = `(?:\`${tableName}\`|${tableName})`
  const withoutPythonYield = source.replace(
    new RegExp(`\\byield\\s+from\\s+(?:${identifier}\\s*\\.\\s*)?${table}\\b`, 'giu'),
    '',
  )
  return retiredSqlPattern(tableName).test(withoutPythonYield)
}


test('full Phase 2 is the default and Phase 2C remains an explicit regression entrypoint', () => {
  const rootPackage = JSON.parse(readWorkspaceFile('package.json'))
  const frontendPackage = JSON.parse(readWorkspaceFile('frontend/package.json'))

  assert.equal(rootPackage.scripts['test:browser'], 'node scripts/run-tests.mjs browser-phase2')
  assert.equal(
    rootPackage.scripts['test:browser:phase2c'],
    'node scripts/run-tests.mjs browser-phase2c',
  )
  assert.equal(
    rootPackage.scripts['test:browser:phase2'],
    'node scripts/run-tests.mjs browser-phase2',
  )
  assert.equal(frontendPackage.scripts['test:e2e'], 'node e2e/run-phase2.mjs')
  assert.equal(frontendPackage.scripts['test:e2e:phase2c'], 'node e2e/run-phase2c.mjs')
  assert.equal(frontendPackage.scripts['test:e2e:phase2'], 'node e2e/run-phase2.mjs')
})


test('Phase 2 acceptance report records only fresh bounded evidence', () => {
  const reportPath = path.join(
    repositoryRoot,
    'docs',
    'acceptance',
    '2026-07-23-phase-2-creative-foundation.md',
  )
  assert.equal(existsSync(reportPath), true, 'Phase 2 acceptance report must exist')
  const report = readFileSync(reportPath, 'utf8')
  assert.doesNotMatch(report, /Phase 3 Ready:\s*(?:true|ready)/iu)

  for (const required of [
    '999c1b5fd09798eb2e459f7bda74dcf6b4660f57',
    '包含本报告的提交',
    'writer-core-v1.4.0',
    'd4ca983a7748cdf1e05867a2ab4ccb958e76bf82a59aab8e56398693af4dc428',
    '7c2e6fb458774282b11a08b726b6c9c10bc61e32e212736e02e9c060879a9333',
    '60f7c6a713167a26d737b91a62c43012e5f77c8a9bb89e7b877099bf8f6e995b',
    '62e23d68422d35446bb8d60a817786ee44c8f745d6355df23fd96e1673a2284d',
    'Spec review：Critical 0 / Important 0 / Minor 0',
    'Quality review 最终：Critical 0 / Important 0 / Minor 0',
    '44/44 steps',
    'provider-attempt=4',
    'asset-ranking=2',
    'bible-success=1',
    'bible-failure=1',
    'provider-rejected-auth=0',
    'provider-rejected-json=0',
    'provider-rejected-classify=0',
    'provider-rejected-content=0',
    'prompt output leak=0',
    'raw-provider output leak=0',
    'corpus output leak=0',
    'forbidden-outbound=0',
    'phase2_browser: scenarios=1',
    'browser disposable_mysql: created=1 / cleaned=1 / remaining=0',
    'browser ports: reserved=3 / released=3 / remaining=0',
    'browser temp_roots: created=1 / cleaned=1 / remaining=0',
    '收口后使用默认入口 `npm run test:browser` fresh 复核',
    'testDB=0',
    'temp=0',
    'owned process=0',
    'Python 2199 passed / 6 skipped',
    'Node scripts 187 passed',
    'frontend 347 passed',
    'integration 285 passed',
    'created=284 / cleaned=284 / remaining=0',
    '独立残留复核=0',
    '2937 modules transformed',
    'git diff --check：exit 0',
    'Product DB Ready: not evaluated',
    'Real Provider Ready: not evaluated',
    'Content Quality Ready: not evaluated',
    'page.request',
    'page.route',
    'page.evaluate',
    'fetch',
    'axios',
    'fake 只替换外部边界',
    '明文 API key',
    'prompt',
    'raw provider',
    'corpus',
  ]) {
    assert.equal(report.includes(required), true, `missing report evidence: ${required}`)
  }
  assert.doesNotMatch(
    report,
    /(?:Product DB Ready|Real Provider Ready|Content Quality Ready):\s*(?:通过|ready|pass)/iu,
  )
  assert.doesNotMatch(report, /待主控使用 fresh 默认 browser 输出核验/u)
  assert.doesNotMatch(report, /最终验收提交：\s*[0-9a-f]{40}/iu)
})


test('current reset and verifier contain no retired mutable-planning contract', () => {
  const reset = readWorkspaceFile('backend/scripts/reset_writer_core_data.py')
  const verifier = readWorkspaceFile('backend/scripts/verify_milestone2_product.py')
  const runtimeFiles = currentRuntimeFiles()

  assert.doesNotMatch(
    reset,
    /writer-core-v1\.[14]\.0|v1\.[14]-(?:source|target)|V11_TABLE_NAMES/u,
  )
  assert.doesNotMatch(reset, /frozen_writer_core_v11/u)
  for (const tableName of [
    'volume_plans',
    'story_blocks',
    'story_stages',
    'scene_tasks',
  ]) {
    const retiredSql = retiredSqlPattern(tableName)
    for (const filePath of runtimeFiles) {
      assert.equal(
        containsRetiredSql(readFileSync(filePath, 'utf8'), tableName),
        false,
        `retired SQL contract in ${path.relative(repositoryRoot, filePath)}`,
      )
    }
  }
  for (const retired of [
    '/planning/initial',
    'expected_story_block_revision',
    'planning_manifest_hash',
    'planning_snapshot_json',
    'create_initial_plan',
  ]) {
    for (const filePath of runtimeFiles) {
      assert.equal(
        readFileSync(filePath, 'utf8').includes(retired),
        false,
        `retired runtime contract in ${path.relative(repositoryRoot, filePath)}`,
      )
    }
  }
  assert.match(verifier, /project_planning_heads/u)
  assert.match(verifier, /project_chapter_outline_heads/u)
  assert.match(verifier, /orphan_planning/u)
})


test('retired-contract inventory scans only the closed current runtime surface', () => {
  const relativePaths = currentRuntimeFiles().map((absolutePath) => (
    path.relative(repositoryRoot, absolutePath).replaceAll('\\', '/')
  ))

  assert.equal(relativePaths.includes('backend/scripts/reset_writer_core_data.py'), true)
  assert.equal(relativePaths.includes('backend/scripts/verify_milestone2_product.py'), true)
  assert.equal(relativePaths.includes('backend/domain/planning.py'), true)
  assert.equal(relativePaths.includes('frontend/src/stores/planningStore.js'), true)
  assert.equal(relativePaths.some((value) => value.startsWith('backend/tests/')), false)
  assert.equal(relativePaths.some((value) => value.startsWith('scripts/tests/')), false)
  assert.equal(relativePaths.some((value) => value.startsWith('docs/')), false)
})


test('retired SQL matcher covers quoted and schema-qualified table names only in SQL context', () => {
  for (const sql of [
    'FROM story_blocks',
    'JOIN `story_blocks` block ON block.id=ref.id',
    'INSERT INTO archive.story_blocks (id) VALUES (1)',
    'UPDATE `legacy`.`story_blocks` SET title=?',
    'CREATE TABLE `legacy`.story_blocks (id CHAR(36))',
    'TABLE legacy.`story_blocks`',
    'TRUNCATE story_blocks',
    'FROM /* optimizer hint */ `legacy`.`story_blocks`',
    'FROM -- optimizer hint\n story_blocks',
    'FROM # optimizer hint\n `story_blocks`',
    'from story_blocks',
    'JoIn legacy.story_blocks block ON block.id=ref.id',
  ]) {
    assert.equal(containsRetiredSql(sql, 'story_blocks'), true)
  }
  for (const domainText of [
    'story_blocks = planning.story_blocks',
    'yield \t  from planning.story_blocks',
    '"storyBlocks": []',
    'The story_blocks domain collection is current.',
  ]) {
    assert.equal(containsRetiredSql(domainText, 'story_blocks'), false)
  }
})


test('dispatcher validates Phase 2 MySQL authority before starting only its runner', () => {
  const calls = []
  const completeEnvironment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }

  assert.equal(runSuites(['browser-phase2'], {
    rootDirectory: repositoryRoot,
    environment: completeEnvironment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  }), 0)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].args, ['frontend/e2e/run-phase2.mjs'])
  assert.equal(calls[0].options.shell, false)

  calls.length = 0
  const incompleteEnvironment = { ...completeEnvironment }
  delete incompleteEnvironment.TEST_MYSQL_PASSWORD
  assert.equal(runSuites(['browser-phase2'], {
    rootDirectory: repositoryRoot,
    environment: incompleteEnvironment,
    stderr: { write() {} },
    spawnSyncImpl() {
      calls.push('spawned')
      return { status: 0 }
    },
  }), 2)
  assert.deepEqual(calls, [])
})


test('Phase 2 runner owns one exact spec and fails closed before allocating resources', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const expected = ['e2e/phase2-creative-foundation.spec.ts']

  assert.deepEqual(runner.FORMAL_SPECS, expected)
  assert.deepEqual(runner.resolveCommandLineSpecs([]), expected)
  assert.throws(
    () => runner.resolveCommandLineSpecs(['e2e/arbitrary.spec.ts']),
    /does not accept spec paths/iu,
  )

  const allocations = []
  await assert.rejects(runner.runPhase2({
    environment: {
      TEST_MYSQL_HOST: '127.0.0.1',
      TEST_MYSQL_PORT: '33060',
      TEST_MYSQL_USER: 'root',
    },
    databaseNameFactory() { allocations.push('database') },
    ownedRootFactory() { allocations.push('root') },
    portReservationFactory() { allocations.push('port') },
  }), /TEST_MYSQL_PASSWORD/u)
  assert.deepEqual(allocations, [])
})


test('Phase 2 runner composes the shared lifecycle and observers', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2.mjs')

  assert.match(source, /from '\.\/support\/product-runner\.mjs'/u)
  assert.match(source, /\brunOwnedProductLifecycle\b/u)
  assert.match(source, /\brunBoundedOwnedCommand\b/u)
  assert.match(source, /\bstartOwnedServer\b/u)
  assert.match(source, /\bstopOwnedServer\b/u)
  assert.match(source, /from '\.\/runtime-observer\.mjs'/u)
  assert.match(source, /\bruntimeSensitiveValues\b/u)
  assert.match(source, /from '\.\/server-log-observer\.mjs'/u)
  assert.match(source, /\bcreateServerLogObserver\b/u)
  assert.match(
    source,
    /backend\.scripts\.prepare_phase2_browser_db/u,
  )
  assert.doesNotMatch(
    source,
    /function\s+(?:runOwnedProductLifecycle|startOwnedServer|stopOwnedServer)\s*\(/u,
  )
})


test('Phase 2 Playwright source is UI-only and uses the runtime observer', () => {
  const entry = 'frontend/e2e/phase2-creative-foundation.spec.ts'
  assertSafeBrowserGraph(entry, relativePath => readWorkspaceFile(relativePath))
  const source = readWorkspaceFile(entry)

  assert.match(source, /\bobserveRuntime\b/u)
  assert.match(source, /\bassertRuntimeEvidenceHealthy\b/u)
  assert.match(
    source,
    /const contractDraftPath = `\/api\/projects\/\$\{projectId\}\/contract-draft`/u,
  )
  assert.match(
    source,
    /assertRuntimeEvidenceHealthy\(evidence,\s*\{[\s\S]*?responseFailureAllowlist:\s*\[\{[\s\S]*?status:\s*404,[\s\S]*?method:\s*'GET',[\s\S]*?pathname:\s*contractDraftPath,[\s\S]*?count:\s*1,[\s\S]*?\}\],[\s\S]*?consoleErrorAllowlist:\s*\[\{[\s\S]*?message:\s*'error: Failed to load resource: the server responded with a status of 404 \(Not Found\)',[\s\S]*?count:\s*1,[\s\S]*?linkedResponseFailure:\s*\{[\s\S]*?status:\s*404,[\s\S]*?method:\s*'GET',[\s\S]*?pathname:\s*contractDraftPath,[\s\S]*?\}[\s\S]*?\}\],[\s\S]*?\}\)/u,
  )
  assert.doesNotMatch(source, /responseFailures:\s*\[\]/u)
  assert.doesNotMatch(source, /consoleErrors:\s*\[\]/u)
  assert.match(source, /\bassertExactWrites\b/u)
  assert.match(source, /\bscanRuntimeEvidence\b/u)
  assert.match(source, /BROWSER_VITE_ORIGIN/u)
  assert.match(source, /BROWSER_BACKEND_ORIGIN/u)
  assert.match(source, /runnerOrigins\.has\(new URL\(entry\.url\)\.origin\)/u)
  assert.match(source, /new URL\(entry\.url\)\.origin === BACKEND_ORIGIN/u)
  assert.match(source, /BROWSER_TRANSCRIPT_SENTINEL/u)
  assert.match(source, /BROWSER_QIDIAN_SNAPSHOT_PATH/u)
  assert.match(source, /BROWSER_QQ_SNAPSHOT_PATH/u)
  assert.match(source, /BROWSER_CORPUS_FILE/u)
  assert.match(source, /BROWSER_PROMPT_SENTINEL/u)
  assert.match(source, /BROWSER_RAW_PROVIDER_SENTINEL/u)
  assert.match(source, /BROWSER_CORPUS_TEXT_SENTINEL/u)
  assert.match(source, /\bOUTPUT_ONLY_SENTINELS\b/u)
  assert.equal(
    source.match(/recordStep\('browser-test-started'\)/gu)?.length,
    1,
  )
  assert.match(
    source,
    /test\('accepts the complete Phase 2 creative foundation through real UI',[\s\S]*?\) => \{\s+test\.setTimeout\(240_000\)\s+recordStep\('browser-test-started'\)\s+const runtime = observeRuntime\(page\)/u,
  )
  assert.doesNotMatch(
    source,
    /function recordStep\(step: string\) \{[\s\S]*?\}\s+recordStep\('browser-test-started'\)/u,
  )
  assert.match(
    source,
    /scanRuntimeEvidence\(\{\s*\.\.\.audited,\s*requests:\s*\[\],\s*\}, OUTPUT_ONLY_SENTINELS\)/u,
  )
  assert.match(
    source,
    /保持人物欲望、群像关系和现实代价具体。 \$\{PROMPT_SENTINEL\}/u,
  )
  assert.match(source, /FAIL_SAFE \$\{PROMPT_SENTINEL\}/u)
  assert.equal(
    source.match(
      /generationPanel\.getByLabel\('作者补充要求（可选）'\)\s+\.fill\(''\)/gu,
    )?.length,
    2,
  )
  assert.match(
    source,
    /recordStep\('bible-generation-succeeded'\)\s+await generationPanel\.getByLabel\('作者补充要求（可选）'\)\s+\.fill\(''\)\s+await bibleScalar\(page, '主角'\)\.fill/u,
  )
  assert.match(
    source,
    /const failedResponse = await failed\s+await generationPanel\.getByLabel\('作者补充要求（可选）'\)\s+\.fill\(''\)\s+recordStep\('bible-failure-returned'\)\s+expect\(failedResponse\.status\(\)\)/u,
  )
  assert.match(
    source,
    /async function bibleEditorSnapshot\(scope\) \{\s+const textareas = scope\.locator\('textarea'\)\s+const fields = await textareas\.all\(\)\s+return \{\s+textareaCount: fields\.length,\s+textareaValues: await Promise\.all\(\s*fields\.map\(field => field\.inputValue\(\)\),\s*\),\s+\}\s+\}/u,
  )
  assert.match(
    source,
    /const preserved = await bibleEditorSnapshot\(bibleEditor\(page\)\)[\s\S]*?expect\(preserved\.textareaCount\)\.toBeGreaterThanOrEqual\(11\)[\s\S]*?expect\(await bibleEditorSnapshot\(bibleEditor\(page\)\)\)\s+\.toEqual\(preserved\)/u,
  )
  assert.match(
    source,
    /expect\(preserved\.textareaCount\)\.toBeGreaterThanOrEqual\(11\)\s+recordStep\('bible-failure-state-captured'\)[\s\S]*?\.fill\(`FAIL_SAFE \$\{PROMPT_SENTINEL\}`\)\s+recordStep\('bible-failure-instructions-set'\)[\s\S]*?await expect\(failureButton\)\.toBeEnabled\(\)\s+recordStep\('bible-failure-ready'\)[\s\S]*?await failureButton\.click\(\)\s+recordStep\('bible-failure-submitted'\)\s+const failedResponse = await failed[\s\S]*?recordStep\('bible-failure-returned'\)/u,
  )
  assert.match(
    source,
    /const expectedRevisionTwo = await bibleEditorSnapshot\(bibleEditor\(page\)\)[\s\S]*?history\.locator\('\.history-detail'\)[\s\S]*?expect\(await bibleEditorSnapshot\(\s*history\.locator\('\.history-detail'\),\s*\)\)\.toEqual\(expectedRevisionTwo\)/u,
  )
  assert.match(source, /BROWSER_RUNTIME_AUDIT_DIAGNOSTIC/u)
  assert.match(source, /\bwriteRuntimeAuditDiagnostic\b/u)
  assert.match(source, /\bpathnameCategory\b/u)
  assert.match(source, /\bhealthErrors\b/u)
  assert.match(source, /\brequestFailureDetails\b/u)
  assert.match(source, /\bapiResponseBodyReadErrorDetails\b/u)
  assert.match(
    source,
    /const evidence = await runtime\.finish\(\)\s+writeRuntimeAuditDiagnostic\(evidence, projectId\)\s+await auditRuntime\(evidence, checkpoints, projectId, \{\s+recordProgress: bodyError === null,\s*\}\)/u,
  )
  assert.match(source, /selectSeed\(page, projectId, '雾港错钟', 3\)/u)
  assert.match(
    source,
    /async function confirmContract\(page, projectId: string\) \{[\s\S]*?recordStep\('contract-workspace-visible'\)[\s\S]*?await fillManualEngines\(page, projectId\)[\s\S]*?recordStep\('story-engines-recorded'\)[\s\S]*?recordStep\('asset-recommendations-returned'\)[\s\S]*?await enterCapacity\(page, projectId\)[\s\S]*?recordStep\('contract-scope-selected'\)[\s\S]*?recordStep\('contract-confirmed'\)/u,
  )
  assert.match(
    source,
    /async function auditRuntime\(evidence, checkpoints, projectId: string, \{\s*recordProgress = false,\s*\} = \{\}\)/u,
  )
  assert.equal(
    source.match(/if \(recordProgress\) recordStep\('audit-[^']+'\)/gu)?.length,
    5,
  )
  assert.match(
    source,
    /await auditRuntime\(evidence, checkpoints, projectId, \{\s*recordProgress: bodyError === null,\s*\}\)/u,
  )
  assert.match(source, /生成创作圣经/u)
  assert.match(source, /FAIL_SAFE/u)
  assert.match(source, /调整未来设计/u)
  assert.match(source, /修订历史/u)
  assert.match(source, /phase_boundary_planning/u)
  assert.match(source, /page\.reload\(/u)
  assert.match(source, /page\.goBack\(/u)
  assert.match(source, /page\.goForward\(/u)
  assert.match(source, /page\.setViewportSize\(/u)
  assert.match(
    source,
    /async function settleNavigationBoundary\(page, runtime\) \{\s+await page\.waitForLoadState\('networkidle'\)\s+await runtime\.settle\(\)\s+\}/u,
  )
  assert.match(
    source,
    /async function verifyNavigationAndPreparation\(page, projectId: string, runtime\)/u,
  )
  assert.match(
    source,
    /async function archiveAndVerifyReadOnly\(page, projectId: string, runtime\)/u,
  )
  assert.equal(
    source.match(/await settleNavigationBoundary\(page, runtime\)/gu)?.length,
    12,
  )
  assert.match(
    source,
    /await verifyNavigationAndPreparation\(page, projectId, runtime\)/u,
  )
  assert.match(
    source,
    /await archiveAndVerifyReadOnly\(page, projectId, runtime\)/u,
  )
  assert.match(source, /归档/u)
  assert.match(source, /此入口已升级或不存在/u)
  assert.doesNotMatch(
    source,
    /page\.request|page\.route|page\.evaluate|allInputValues|evaluateAll|\bfetch\s*\(|\baxios\b/u,
  )
})


test('Phase 2 Playwright config is serial, loopback-only, and retains no media', () => {
  const source = readWorkspaceFile('frontend/playwright.phase2.config.ts')

  assert.match(source, /\^http:\\\/\\\/127\\\.0\\\.0\\\.1:\\d\+\$/u)
  assert.match(source, /fullyParallel:\s*false/u)
  assert.match(source, /workers:\s*1/u)
  assert.match(source, /trace:\s*'off'/u)
  assert.match(source, /screenshot:\s*'off'/u)
  assert.match(source, /video:\s*'off'/u)
  assert.match(source, /preserveOutput:\s*'never'/u)
})


test('Phase 2 browser progress ledger is closed and contains no diagnostics', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')

  assert.deepEqual(
    runner.summarizeBrowserStepLedger(''),
    {
      lineCount: 0,
      firstMismatchIndex: null,
      expected: 'none',
      actual: 'none',
      duplicateCount: 0,
    },
  )
  assert.deepEqual(
    runner.summarizeBrowserStepLedger(
      'browser-test-started\nassets-visible\n',
    ),
    {
      lineCount: 2,
      firstMismatchIndex: 1,
      expected: 'library-visible',
      actual: 'assets-visible',
      duplicateCount: 0,
    },
  )
  assert.deepEqual(
    runner.summarizeBrowserStepLedger(
      'browser-test-started\nbrowser-test-started\nlibrary-visible\n',
    ),
    {
      lineCount: 3,
      firstMismatchIndex: 1,
      expected: 'library-visible',
      actual: 'browser-test-started',
      duplicateCount: 1,
    },
  )
  assert.deepEqual(
    runner.summarizeBrowserStepLedger(
      'browser-test-started\nprivate-raw-line\n',
    ),
    {
      lineCount: 2,
      firstMismatchIndex: 1,
      expected: 'library-visible',
      actual: 'unknown',
      duplicateCount: 0,
    },
  )
  assert.deepEqual(
    runner.verifyBrowserStepLedger(
      'browser-test-started\nlibrary-visible\nproject-created\n',
    ),
    [
      'browser-test-started',
      'library-visible',
      'project-created',
    ],
  )
  assert.throws(
    () => runner.verifyBrowserStepLedger('library-visible\nsecret=value\n'),
    /progress ledger/iu,
  )
  assert.throws(
    () => runner.verifyBrowserStepLedger(
      'browser-test-started\nassets-visible\n',
    ),
    /progress ledger/iu,
  )
  assert.throws(
    () => runner.verifyBrowserStepLedger('project-created\n'),
    /progress ledger/iu,
  )
  const fullLedger = runner.ALLOWED_BROWSER_STEPS
    .map(step => `${step}\n`)
    .join('')
  assert.deepEqual(
    runner.verifyBrowserStepLedger(fullLedger, { requireComplete: true }),
    runner.ALLOWED_BROWSER_STEPS,
  )
  assert.throws(
    () => runner.verifyBrowserStepLedger(
      'browser-test-started\nlibrary-visible\nproject-created\n',
      { requireComplete: true },
    ),
    /progress ledger/iu,
  )
  assert.equal(runner.ALLOWED_BROWSER_STEPS[0], 'browser-test-started')
  assert.deepEqual(
    runner.ALLOWED_BROWSER_STEPS.slice(9, 14),
    [
      'contract-workspace-visible',
      'story-engines-recorded',
      'asset-recommendations-returned',
      'contract-scope-selected',
      'contract-confirmed',
    ],
  )
  assert.deepEqual(
    runner.ALLOWED_BROWSER_STEPS.slice(21, 27),
    [
      'bible-adjustment-created',
      'bible-failure-state-captured',
      'bible-failure-instructions-set',
      'bible-failure-ready',
      'bible-failure-submitted',
      'bible-failure-returned',
    ],
  )
  const runnerSource = readWorkspaceFile('frontend/e2e/run-phase2.mjs')
  assert.match(
    runnerSource,
    /const ledgerSummary = summarizeBrowserStepLedger\(ledger\)[\s\S]*?verifyBrowserStepLedger\(ledger\)[\s\S]*?phase2StepLedgerSummary = ledgerSummary/u,
  )
})


test('Phase 2 CLI failure classification is recursive and secret-safe', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const cases = [
    ['Phase 2 browser test process exited with status 1', 'browser-process-exit'],
    [
      'Phase 2 browser test process log contained runtime-sensitive values',
      'browser-log-sensitive',
    ],
    ['Phase 2 browser progress ledger is invalid', 'step-ledger'],
    ['Phase 2 gateway call ledger has unexpected formal counts', 'gateway-counts'],
    ['Phase 2 gateway call ledger contains an unknown type', 'gateway-unknown'],
    ['Phase 2 forbidden outbound ledger is not empty', 'forbidden-outbound'],
    ['Phase 2 database evidence process exited with status 1', 'database-evidence'],
    ['Runtime evidence contains response failures', 'runtime-audit'],
    ['Runtime evidence contains console errors', 'runtime-audit'],
    ['Runtime evidence contains page errors', 'runtime-audit'],
    ['Runtime evidence contains request failures', 'runtime-audit'],
    ['Runtime API response headers could not be read', 'runtime-audit'],
    ['Runtime API response bodies could not be read', 'runtime-audit'],
    ['Runtime request headers could not be read', 'runtime-audit'],
    ['Runtime request bodies could not be read', 'runtime-audit'],
    [
      'fake Provider gateway log contained runtime-sensitive values',
      'server-cleanup',
    ],
    ['fake Provider gateway stop, drain, or log audit failed', 'server-cleanup'],
    ['backend log contained runtime-sensitive values', 'server-cleanup'],
    ['backend stop, drain, or log audit failed', 'server-cleanup'],
    ['vite log contained runtime-sensitive values', 'server-cleanup'],
    ['vite stop, drain, or log audit failed', 'server-cleanup'],
    ['Phase 2 database cleanup process failed to start', 'database-cleanup'],
    ['Phase 2 database cleanup process exited with status 1', 'database-cleanup'],
    [
      'Phase 2 database cleanup process log contained runtime-sensitive values',
      'database-cleanup',
    ],
  ]
  for (const [message, category] of cases) {
    assert.equal(runner.classifyPhase2Failure(new Error(message)), category)
  }

  const rawMarker = 'raw-secret-must-never-render'
  const nested = new AggregateError(
    [
      new Error(rawMarker),
      new Error('Phase 2 browser test process exited with status 1', {
        cause: new Error(rawMarker),
      }),
    ],
    rawMarker,
  )
  const stopped = new Error(
    'Phase 2 browser stopped after browser-test-started',
    { cause: nested },
  )
  assert.equal(runner.classifyPhase2Failure(stopped), 'browser-process-exit')
  assert.equal(
    runner.renderPhase2CliFailure(stopped),
    'Phase 2 browser acceptance failed after browser-test-started; '
      + 'category=browser-process-exit.\n',
  )
  assert.equal(runner.renderPhase2CliFailure(stopped).includes(rawMarker), false)
  assert.equal(runner.classifyPhase2Failure(new Error(rawMarker)), 'unknown')
  for (const [message, category] of [
    ['fake Provider gateway stop, drain, or log audit failed', 'server-cleanup'],
    ['backend stop, drain, or log audit failed', 'server-cleanup'],
    ['vite stop, drain, or log audit failed', 'server-cleanup'],
    ['Phase 2 database cleanup process exited with status 1', 'database-cleanup'],
  ]) {
    const cleanup = new Error(message, { cause: new Error(rawMarker) })
    assert.equal(
      runner.renderPhase2CliFailure(cleanup),
      `Phase 2 browser acceptance failed; category=${category}.\n`,
    )
    assert.equal(runner.renderPhase2CliFailure(cleanup).includes(rawMarker), false)
  }
  const ledgerFailure = new Error('Phase 2 browser progress ledger is invalid')
  ledgerFailure.phase2StepLedgerSummary = runner.summarizeBrowserStepLedger(
    'browser-test-started\nprivate-raw-line\n',
  )
  assert.equal(
    runner.renderPhase2CliFailure(ledgerFailure),
    'Phase 2 browser acceptance failed; category=step-ledger; '
      + 'stepLedger[lineCount=2,firstMismatchIndex=1,'
      + 'expected=library-visible,actual=unknown,duplicateCount=0].\n',
  )
  assert.equal(
    runner.renderPhase2CliFailure(ledgerFailure).includes('private-raw-line'),
    false,
  )
  assert.equal(
    runner.renderPhase2CliFailure(
      new Error('Phase 2 browser stopped after corpus-imported'),
    ),
    'Phase 2 browser acceptance failed after corpus-imported; category=unknown.\n',
  )
  assert.equal(
    runner.renderPhase2CliFailure(
      new Error('Phase 2 browser stopped after secret=value'),
    ),
    'Phase 2 browser acceptance failed; category=unknown.\n',
  )
})


test('Phase 2 lifecycle cleanup boundaries replace raw single errors', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const source = readWorkspaceFile('frontend/e2e/run-phase2.mjs')
  const rawMarker = 'raw-owned-cleanup-detail-must-never-render'
  const cases = [
    ['server', 'server-cleanup', 'vite close failed'],
    ['server', 'server-cleanup', 'fake gateway drain failed'],
    ['server', 'server-cleanup', 'vite exited before cleanup'],
    ['server', 'server-cleanup', 'Windows process terminator failed'],
    ['reservation', 'reservation-cleanup', 'reservation release failed'],
    ['database', 'database-cleanup', 'database cleanup deadline exceeded'],
    ['database', 'database-cleanup', 'database cleanup exited nonzero'],
    ['root', 'root-cleanup', 'root namespace validation failed'],
    ['root', 'root-cleanup', 'root remove failed'],
  ]

  for (const [kind, category, detail] of cases) {
    const rawError = new Error(`${rawMarker}:${detail}`)
    assert.equal(runner.classifyPhase2Failure(rawError), 'unknown')
    await assert.rejects(
      runner.runPhase2CleanupBoundary(kind, async () => {
        throw rawError
      }),
      error => {
        assert.equal(error.cause, rawError)
        assert.equal(runner.classifyPhase2Failure(error), category)
        assert.equal(
          runner.renderPhase2CliFailure(error),
          `Phase 2 browser acceptance failed; category=${category}.\n`,
        )
        assert.equal(
          runner.renderPhase2CliFailure(error).includes(rawMarker),
          false,
        )
        return true
      },
    )
  }

  await assert.rejects(
    runner.runPhase2CleanupBoundary(rawMarker, async () => {}),
    error => {
      assert.equal(error.message, 'Invalid Phase 2 cleanup boundary kind')
      assert.equal(error.message.includes(rawMarker), false)
      return true
    },
  )

  for (const [callback, kind] of [
    ['stopServer', 'server'],
    ['releaseReservation', 'reservation'],
    ['dropDatabase', 'database'],
    ['removeRoot', 'root'],
  ]) {
    assert.match(
      source,
      new RegExp(
        `${callback}:\\s*[a-z]+\\s*=>\\s*runPhase2CleanupBoundary\\(`
          + `\\s*'${kind}',`,
        'u',
      ),
    )
  }
})


test('Phase 2 resource summaries are aggregated, strict, and safe to render', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const source = readWorkspaceFile('frontend/e2e/run-phase2.mjs')
  const first = {
    scenarios: 1,
    disposableMysql: { created: 1, cleaned: 1, remaining: 0 },
    ports: { reserved: 3, released: 3, remaining: 0 },
    tempRoots: { created: 1, cleaned: 1, remaining: 0 },
  }
  const second = {
    scenarios: 2,
    disposableMysql: { created: 2, cleaned: 2, remaining: 0 },
    ports: { reserved: 6, released: 6, remaining: 0 },
    tempRoots: { created: 2, cleaned: 2, remaining: 0 },
  }
  const aggregate = runner.aggregatePhase2ResourceSummaries([first, second])
  assert.deepEqual(aggregate, {
    scenarios: 3,
    disposableMysql: { created: 3, cleaned: 3, remaining: 0 },
    ports: { reserved: 9, released: 9, remaining: 0 },
    tempRoots: { created: 3, cleaned: 3, remaining: 0 },
  })
  assert.equal(
    runner.formatPhase2ResourceSummary(first),
    'phase2_browser: scenarios=1\n'
      + 'disposable_mysql: created=1 cleaned=1 remaining=0\n'
      + 'ports: reserved=3 released=3 remaining=0\n'
      + 'temp_roots: created=1 cleaned=1 remaining=0\n',
  )
  assert.match(
    runner.formatPhase2ResourceSummary(first),
    /^phase2_browser: scenarios=\d+\ndisposable_mysql: created=\d+ cleaned=\d+ remaining=\d+\nports: reserved=\d+ released=\d+ remaining=\d+\ntemp_roots: created=\d+ cleaned=\d+ remaining=\d+\n$/u,
  )

  for (const invalid of [
    { ...first, scenarios: -1 },
    { ...first, scenarios: 1.5 },
    {
      ...first,
      disposableMysql: { created: -1, cleaned: 0, remaining: -1 },
    },
    {
      ...first,
      ports: { reserved: 3.5, released: 3, remaining: 0.5 },
    },
    {
      ...first,
      tempRoots: { created: 1, cleaned: 1, remaining: 1 },
    },
    { ...first, rawMarker: 'must-not-render' },
    {
      ...first,
      ports: {
        reserved: 3,
        released: 3,
        remaining: 0,
        port: 5173,
      },
    },
  ]) {
    assert.throws(
      () => runner.formatPhase2ResourceSummary(invalid),
      /resource summary/iu,
    )
    assert.throws(
      () => runner.aggregatePhase2ResourceSummaries([invalid]),
      /resource summary/iu,
    )
  }

  const runSummary = await runner.runPhase2({
    environment: {
      TEST_MYSQL_HOST: '127.0.0.1',
      TEST_MYSQL_PORT: '33060',
      TEST_MYSQL_USER: 'root',
      TEST_MYSQL_PASSWORD: 'test-only',
    },
    async runOneScenarioImpl() {
      return first
    },
  })
  assert.deepEqual(runSummary, first)

  const scenarioStart = source.indexOf('async function runOneScenario')
  const scenarioEnd = source.indexOf('export async function runPhase2', scenarioStart)
  const scenarioSource = source.slice(scenarioStart, scenarioEnd)
  const reservationStart = scenarioSource.indexOf(
    'const reservation = await portReservationFactory()',
  )
  const reservationCount = scenarioSource.indexOf(
    'resourceCounts.ports.reserved += 1',
    reservationStart,
  )
  const reservationRegister = scenarioSource.indexOf(
    'lifecycle.registerReservation(reservation)',
    reservationCount,
  )
  assert.equal(
    reservationStart >= 0
      && reservationStart < reservationCount
      && reservationCount < reservationRegister,
    true,
  )

  for (const [startToken, successToken, countToken, endToken] of [
    [
      'await runBoundedOwnedCommand(',
      "label: 'Phase 2 database preparation'",
      'resourceCounts.disposableMysql.created += 1',
      'await lifecycle.releaseReservation',
    ],
    [
      'releaseReservation: reservation =>',
      'await reservation.release()',
      'resourceCounts.ports.released += 1',
      'dropDatabase: database =>',
    ],
    [
      'dropDatabase: database =>',
      'await runBoundedOwnedCommand(',
      'resourceCounts.disposableMysql.cleaned += 1',
      'removeRoot: root =>',
    ],
    [
      'removeRoot: root =>',
      'await removeOwnedRoot(',
      'resourceCounts.tempRoots.cleaned += 1',
      '\n  })',
    ],
  ]) {
    const start = scenarioSource.indexOf(startToken)
    const success = scenarioSource.indexOf(successToken, start)
    const count = scenarioSource.indexOf(countToken, success)
    const end = scenarioSource.indexOf(endToken, count)
    assert.equal(start >= 0 && start < success && success < count && count < end, true)
  }
  const rootFactory = scenarioSource.indexOf('ownedRootFactory()')
  const rootCreated = scenarioSource.indexOf(
    'resourceCounts.tempRoots.created += 1',
    rootFactory,
  )
  assert.equal(rootFactory >= 0 && rootFactory < rootCreated, true)
  assert.match(
    scenarioSource,
    /return summarizePhase2ResourceCounts\(resourceCounts\)/u,
  )
})


test('Phase 2 runtime audit diagnostics expose only fixed safe categories', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const diagnostic = JSON.stringify({
    responseFailures: [
      {
        status: 404,
        method: 'GET',
        pathnameCategory: 'contract-draft',
        count: 2,
      },
    ],
    consoleErrors: [
      { category: 'resource-404', count: 1 },
      { category: 'ui-error-boundary', count: 1 },
    ],
    healthErrors: [
      { category: 'page-error', count: 1 },
      { category: 'request-failure', count: 2 },
    ],
    requestFailureDetails: [
      {
        method: 'GET',
        pathCategory: 'assets',
        errorCategory: 'cancelled',
        count: 2,
      },
    ],
    apiResponseBodyReadErrorDetails: [
      {
        method: 'GET',
        status: 200,
        pathCategory: 'project',
        errorCategory: 'protocol-no-resource',
        count: 1,
      },
    ],
  })

  assert.equal(
    runner.verifyRuntimeAuditDiagnostic(diagnostic),
    'response[404:GET:contract-draft=2];'
      + 'console[resource-404=1,ui-error-boundary=1];'
      + 'health[page-error=1,request-failure=2];'
      + 'requestFailures[GET:assets:cancelled=2];'
      + 'apiBodyReadErrors[GET:200:project:protocol-no-resource=1]',
  )
  assert.throws(
    () => runner.verifyRuntimeAuditDiagnostic(JSON.stringify({
      responseFailures: [{
        status: 404,
        method: 'GET',
        pathnameCategory: '/api/projects/private/contract-draft',
        count: 1,
      }],
      consoleErrors: [],
      healthErrors: [],
      requestFailureDetails: [],
      apiResponseBodyReadErrorDetails: [],
    })),
    /audit diagnostic/iu,
  )
  assert.throws(
    () => runner.verifyRuntimeAuditDiagnostic(JSON.stringify({
      responseFailures: [],
      consoleErrors: [{
        category: 'resource-404',
        count: 1,
        message: 'raw console text',
      }],
      healthErrors: [],
      requestFailureDetails: [],
      apiResponseBodyReadErrorDetails: [],
    })),
    /audit diagnostic/iu,
  )

  const error = new Error(
    'Phase 2 browser stopped after not-found-visible',
    { cause: new Error('Runtime evidence contains response failures') },
  )
  error.phase2AuditDiagnostic = diagnostic
  assert.equal(
    runner.renderPhase2CliFailure(error),
    'Phase 2 browser acceptance failed after not-found-visible; '
      + 'category=runtime-audit; '
      + 'audit[response[404:GET:contract-draft=2];'
      + 'console[resource-404=1,ui-error-boundary=1];'
      + 'health[page-error=1,request-failure=2];'
      + 'requestFailures[GET:assets:cancelled=2];'
      + 'apiBodyReadErrors[GET:200:project:protocol-no-resource=1]].\n',
  )
  const rawMarker = 'raw-runtime-detail-must-never-render'
  const invalidDiagnostic = new Error(
    'Runtime evidence contains console errors',
    { cause: new Error(rawMarker) },
  )
  invalidDiagnostic.phase2AuditDiagnostic = JSON.stringify({
    responseFailures: [],
    consoleErrors: [{
      category: 'resource-404',
      count: 1,
      message: rawMarker,
    }],
    healthErrors: [],
    requestFailureDetails: [],
    apiResponseBodyReadErrorDetails: [],
  })
  assert.equal(
    runner.renderPhase2CliFailure(invalidDiagnostic),
    'Phase 2 browser acceptance failed; category=runtime-audit.\n',
  )
  assert.equal(
    runner.renderPhase2CliFailure(invalidDiagnostic).includes(rawMarker),
    false,
  )
  assert.throws(
    () => runner.verifyRuntimeAuditDiagnostic(JSON.stringify({
      responseFailures: [],
      consoleErrors: [],
      healthErrors: [],
      requestFailureDetails: [{
        method: 'GET',
        pathCategory: 'assets',
        errorCategory: 'cancelled',
        count: 1,
        errorText: 'raw browser error',
      }],
      apiResponseBodyReadErrorDetails: [],
    })),
    /audit diagnostic/iu,
  )
})


test('Phase 2 runner scans private gateway and transcript sentinels', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const source = readWorkspaceFile('frontend/e2e/run-phase2.mjs')
  const corpusFixture = runner.buildSyntheticCorpusFixture()
  const corpusMarker = 'phase2-browser-corpus-text-must-not-leak'
  const markerIndex = corpusFixture.indexOf(corpusMarker)
  const secondChapterIndex = corpusFixture.indexOf('第二章 纸带回声')

  assert.equal(corpusFixture.startsWith('第一章 雾港错钟'), true)
  assert.equal(markerIndex > 240, true)
  assert.equal(markerIndex < secondChapterIndex, true)
  assert.equal(markerIndex < 1200, true)
  assert.match(source, /BROWSER_PRIVATE_PROVIDER_URL:\s*gatewayUrl/u)
  assert.match(source, /BROWSER_TRANSCRIPT_SENTINEL/u)
  assert.match(
    source,
    /\.\.\.runtimeSensitiveValues\(environments\.sensitiveController\)/u,
  )
  assert.match(
    source,
    /environments\.sensitiveController\.BROWSER_TRANSCRIPT_SENTINEL/u,
  )
  for (const [constant, environmentName] of [
    ['PROMPT_SENTINEL', 'BROWSER_PROMPT_SENTINEL'],
    ['RAW_PROVIDER_SENTINEL', 'BROWSER_RAW_PROVIDER_SENTINEL'],
    ['CORPUS_TEXT_SENTINEL', 'BROWSER_CORPUS_TEXT_SENTINEL'],
  ]) {
    assert.match(source, new RegExp(`const ${constant} = `, 'u'))
    assert.match(
      source,
      new RegExp(`${environmentName}: ${constant}`, 'u'),
    )
    assert.match(
      source,
      new RegExp(
        `environments\\.sensitiveController\\.${environmentName}`,
        'u',
      ),
    )
  }
  assert.match(
    source,
    /writeFileSync\(\s*corpusPath,\s*buildSyntheticCorpusFixture\(\),/u,
  )
})


test('Phase 2 runner owns snapshots and validates the exact fake gateway calls', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const source = readWorkspaceFile('frontend/e2e/run-phase2.mjs')

  assert.match(source, /qidian-public-snapshot\.json/u)
  assert.match(source, /qq-public-snapshot\.json/u)
  assert.match(source, /BROWSER_QIDIAN_SNAPSHOT_PATH/u)
  assert.match(source, /BROWSER_QQ_SNAPSHOT_PATH/u)
  assert.match(source, /BROWSER_FAKE_COUNTER_PATH/u)
  assert.match(source, /Generate one complete creation Bible/u)
  assert.match(source, /Rank only the supplied eligible asset and corpus candidates/u)
  assert.match(source, /bible-success/u)
  assert.match(source, /bible-failure/u)
  assert.match(
    source,
    /request\.method === 'POST'[\s\S]*?request\.url === '\/v1\/chat\/completions'[\s\S]*?\{\s+recordCounter\('provider-attempt'\)\s+if \(request\.headers\.authorization/u,
  )
  for (const token of [
    'provider-rejected-auth',
    'provider-rejected-json',
    'provider-rejected-classify',
    'provider-rejected-content',
  ]) {
    assert.match(source, new RegExp(`recordCounter\\('${token}'\\)`, 'u'))
  }
  assert.match(source, /const promptSentinel = process\.env\.BROWSER_PROMPT_SENTINEL/u)
  assert.match(
    source,
    /const rawProviderSentinel = process\.env\.BROWSER_RAW_PROVIDER_SENTINEL/u,
  )
  assert.match(
    source,
    /const corpusTextSentinel = process\.env\.BROWSER_CORPUS_TEXT_SENTINEL/u,
  )
  assert.match(
    source,
    /classified\.kind === 'bible'[\s\S]*?JSON\.stringify\(body\.messages\)[\s\S]*?includes\(promptSentinel\)[\s\S]*?includes\(corpusTextSentinel\)[\s\S]*?recordCounter\('provider-rejected-content'\)[\s\S]*?sendJson\(response, 422/u,
  )
  assert.match(
    source,
    /sendJson\(response, 200, \{\s+rawProviderSentinel,/u,
  )
  assert.doesNotMatch(source, /appendFileSync\([^\n]*(?:messages|body|content)/u)

  assert.deepEqual(
    runner.verifyGatewayCounterLedger(
      'provider-attempt\nasset-ranking\n'
        + 'provider-attempt\nasset-ranking\n'
        + 'provider-attempt\nbible-success\n'
        + 'provider-attempt\nbible-failure\n',
    ),
    {
      'provider-attempt': 4,
      'asset-ranking': 2,
      'bible-success': 1,
      'bible-failure': 1,
      'provider-rejected-auth': 0,
      'provider-rejected-json': 0,
      'provider-rejected-classify': 0,
      'provider-rejected-content': 0,
    },
  )
  for (const invalid of [
    '',
    'asset-ranking\nbible-success\nbible-failure\n',
    'provider-attempt\nprovider-attempt\nprovider-attempt\n'
      + 'asset-ranking\nasset-ranking\nbible-success\nbible-failure\n',
    'provider-attempt\nprovider-attempt\nprovider-attempt\nprovider-attempt\n'
      + 'provider-attempt\nasset-ranking\nasset-ranking\n'
      + 'bible-success\nbible-failure\n',
    'provider-attempt\nprovider-attempt\nprovider-attempt\nprovider-attempt\n'
      + 'asset-ranking\nasset-ranking\nbible-success\nbible-failure\n'
      + 'provider-rejected-auth\n',
    'provider-attempt\nprovider-attempt\nprovider-attempt\nprovider-attempt\n'
      + 'asset-ranking\nasset-ranking\nbible-success\nbible-failure\nunknown\n',
  ]) {
    assert.throws(
      () => runner.verifyGatewayCounterLedger(invalid),
      /gateway call ledger/iu,
    )
  }
})
