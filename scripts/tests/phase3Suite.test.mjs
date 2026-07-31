import assert from 'node:assert/strict'
import { PassThrough } from 'node:stream'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'
import { createServerLogObserver } from '../../frontend/e2e/server-log-observer.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const SPEC = 'frontend/e2e/phase3-story-planning.spec.ts'
const CONFIG = 'frontend/e2e/playwright.phase3.config.ts'
const RUNNER = 'frontend/e2e/run-phase3.mjs'

function workspace(relativePath) {
  return readFileSync(path.join(root, relativePath), 'utf8')
}

function playwrightReport(specs) {
  return { suites: [{ specs }] }
}

function playwrightSpec(scenario, tests) {
  return { title: `${scenario}: visible UI only`, tests }
}

test('Phase 3 has one closed formal UI browser suite and package entrypoint', () => {
  const packageJson = JSON.parse(workspace('package.json'))
  const frontendPackage = JSON.parse(workspace('frontend/package.json'))
  assert.equal(packageJson.scripts['test:browser:phase3'], 'node scripts/run-tests.mjs browser-phase3')
  assert.equal(frontendPackage.scripts['test:e2e:phase3'], 'node e2e/run-phase3.mjs')
  for (const file of [SPEC, CONFIG, RUNNER]) {
    assert.equal(existsSync(path.join(root, file)), true, `missing formal Phase 3 file: ${file}`)
  }
})

test('dispatcher owns the exact Phase 3 runner and validates MySQL first', () => {
  const calls = []
  const environment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }
  assert.equal(runSuites(['browser-phase3'], {
    rootDirectory: root,
    environment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  }), 0)
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase3.mjs']])
  assert.equal(calls[0].options.shell, false)

  let stderr = ''
  const incomplete = { ...environment }
  delete incomplete.TEST_MYSQL_PASSWORD
  assert.equal(runSuites(['browser-phase3'], {
    rootDirectory: root,
    environment: incomplete,
    stderr: { write(value) { stderr += String(value) } },
    spawnSyncImpl() { throw new Error('must not spawn') },
  }), 2)
  assert.match(stderr, /TEST_MYSQL_PASSWORD/u)
})

test('Phase 3 browser source graph is UI-only', () => {
  assertSafeBrowserGraph(SPEC, relativePath => workspace(relativePath))
  const source = workspace(SPEC)
  assert.doesNotMatch(source, /page\.request|page\.route|page\.evaluate|\bfetch\s*\(|\baxios\b/u)
  assert.doesNotMatch(source, /(?:api\/db\/client|stores\/.*(?:action|store)|database-residue)/u)
  assert.match(source, /observeRuntime/u)
  assert.match(source, /settleNavigationBoundary/u)
})

test('server access logs allow public routes but reject structured private evidence', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scan = text => {
    const child = { stdout: new PassThrough(), stderr: new PassThrough() }
    const values = [...runner.OWNED_SERVER_LOG_MARKERS, 'phase3-secret-value']
    const observer = createServerLogObserver(child, { sensitiveValues: values })
    child.stderr.write(text)
    return observer.finish(values).matchCount
  }
  assert.equal(scan('INFO: 127.0.0.1:1 - "GET /api/projects/p/corpus HTTP/1.1" 200'), 0)
  assert.equal(scan('INFO: 127.0.0.1:1 - "POST /api/projects/p/prompt-preview HTTP/1.1" 201'), 0)
  assert.ok(scan('Authorization: Bearer phase3-secret-value') > 0)
  assert.ok(scan('mysql://root:phase3-secret-value@127.0.0.1:3306/db') > 0)
  assert.ok(scan('rawProviderOutput={"x":"phase3-secret-value"}') > 0)
  for (const evidence of [
    'prompt=redacted',
    'manifest=redacted',
    'corpusText=redacted',
    'apiKey=redacted',
    'password=redacted',
    'dsn=redacted',
  ]) {
    assert.ok(scan(evidence) > 0, `structured server evidence must be rejected: ${evidence}`)
  }
})

test('each audited scenario includes the exact Task5 UI bootstrap write ledger', () => {
  const source = workspace(SPEC)
  assert.match(source, /function phase2PreparationWrites\(\)/u)
  for (const fragment of [
    "{ method: 'POST', path: '/api/projects', count: 1, statuses: [200] }",
    "path: `/api/projects/${PROJECT_ID}/seeds`, count: 1, statuses: [200]",
    "path: `/api/projects/${PROJECT_ID}/selected-seed`, count: 1, statuses: [200]",
    "path: `/api/projects/${PROJECT_ID}/story-engine-batches/manual`, count: 1, statuses: [201]",
    "path: `/api/projects/${PROJECT_ID}/contract-draft`, count: 4, statuses: [200]",
    "path: `/api/projects/${PROJECT_ID}/contracts/confirm`, count: 1, statuses: [201]",
    "path: `/api/projects/${PROJECT_ID}/bible/generate`, count: 1, statuses: [200]",
    "path: `/api/projects/${PROJECT_ID}/bible/confirm`, count: 1, statuses: [201]",
    "path: `/api/projects/${PROJECT_ID}/asset-recommendations`, statuses: [200], count: 2",
    "path: `/api/projects/${PROJECT_ID}/contracts/preview`, statuses: [200], count: 1",
  ]) assert.match(source, new RegExp(fragment.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'))
  const bindingWrite = "{ method: 'PUT', path: `/api/projects/${PROJECT_ID}/bindings`, count: 1, statuses: [200] }"
  assert.match(source, new RegExp(bindingWrite.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'))
  assert.equal((source.match(new RegExp(bindingWrite.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'gu')) || []).length, 1)
  assert.equal((source.match(/phase2PreparationWrites\(\)/gu) || []).length >= 7, true)
})

test('Task5 bootstrap ledger records its two manual recommendation initializations and preview write', () => {
  const phase3 = workspace(SPEC).replaceAll('\r\n', '\n')
  const phase3Facts = [
    "method: 'POST', path: `/api/projects/${PROJECT_ID}/asset-recommendations`, statuses: [200], count: 2",
    "method: 'POST', path: `/api/projects/${PROJECT_ID}/contracts/preview`, statuses: [200], count: 1",
  ]
  const phase3Start = phase3.indexOf('function phase2PreparationWrites()')
  const phase3Ledger = phase3.slice(phase3Start, phase3.indexOf('\n}', phase3Start))
  const preservesEvery = (ledger, facts) => facts.every(fact => ledger.includes(fact))
  assert.equal(preservesEvery(phase3Ledger, phase3Facts), true, 'Task5 must contain both exact manual-path writes')
  assert.equal(phase3Ledger.includes("method: 'POST', path: `/api/projects/${PROJECT_ID}/asset-recommendations`, statuses: [200], count: 1"), false, 'Task5 must retain both real manual-path recommendation initializations')
  for (const fact of phase3Facts) {
    assert.equal(preservesEvery(phase3Ledger.replace(fact, ''), phase3Facts), false, 'removing either exact Task5 fact must fail the ledger contract')
  }
})

test('Task5 bootstrap scopes every identical save control to its active step and waits for the next heading', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function completePhase2PreparationUi')
  const end = source.indexOf('\nasync function chooseVisibleSelectOption', start)
  const helper = source.slice(start, end)
  const ordered = (click, heading, label) => {
    const clickIndex = helper.indexOf(click)
    const headingIndex = helper.indexOf(heading, clickIndex)
    assert.ok(clickIndex >= 0 && headingIndex > clickIndex, label)
  }
  assert.doesNotMatch(helper, /await page\.getByRole\('button', \{ name: '保存草稿并继续' \}\)\.click\(\)/u)
  ordered("engine.getByRole('button', { name: '保存草稿并继续' }).click()", "getByRole('heading', { name: '先定阅读感受，再谈写法', exact: true })", 'Story Engine save must wait for Style heading')
  ordered("styleStep.getByRole('button', { name: '保存草稿并继续' }).click()", "getByRole('heading', { name: '逐项授权，片段级冻结', exact: true })", 'Style save must wait for Asset heading')
  ordered("assetScope.getByRole('button', { name: '保存草稿并继续' }).click()", "getByRole('heading', { name: '给长篇一副可调整的骨架', exact: true })", 'Asset save must wait for Capacity heading')
  ordered("capacity.getByRole('button', { name: '保存草稿并继续' }).click()", "getByRole('heading', { name: '预览全部变化，再一次确认', exact: true })", 'Capacity save must wait for Preview heading')
  assert.match(source, /const assetRecommendations = \(\) => `\/api\/projects\/\$\{PROJECT_ID\}\/asset-recommendations`/u)
  const engineWait = "const styleRecommendationsResponse = page.waitForResponse(response => isResponse(response, 'POST', assetRecommendations()))"
  const engineClick = "engine.getByRole('button', { name: '保存草稿并继续' }).click()"
  const styleHeading = "getByRole('heading', { name: '先定阅读感受，再谈写法', exact: true })"
  const styleStatus = 'expect((await styleRecommendationsResponse).status()).toBe(200)'
  const styleWait = "const assetRecommendationsResponse = page.waitForResponse(response => isResponse(response, 'POST', assetRecommendations()))"
  const styleClick = "styleStep.getByRole('button', { name: '保存草稿并继续' }).click()"
  const assetHeading = "getByRole('heading', { name: '逐项授权，片段级冻结', exact: true })"
  const assetStatus = 'expect((await assetRecommendationsResponse).status()).toBe(200)'
  const index = value => helper.indexOf(value)
  assert.ok(index(engineWait) >= 0 && index(engineWait) < index(engineClick) && index(engineClick) < index(styleHeading) && index(styleHeading) < index(styleStatus), 'Engine save must wait for the first exact asset recommendation POST after Style opens')
  assert.ok(index(styleWait) >= 0 && index(styleWait) < index(styleClick) && index(styleClick) < index(assetHeading) && index(assetHeading) < index(assetStatus) && index(assetStatus) < index("assetScope.getByRole('button', { name: '保存草稿并继续' }).click()"), 'Style save must wait for the second exact asset recommendation POST after Asset opens')
})

test('Phase 2 preparation closes its seed save and selection writes before continuing', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function completePhase2PreparationUi')
  const end = source.indexOf('\nasync function chooseVisibleSelectOption', start)
  const helper = source.slice(start, end)
  for (const fragment of [
    "const createdResponse = page.waitForResponse(response => isResponse(response, 'POST', `/api/projects/${PROJECT_ID}/seeds`))",
    "expect((await createdResponse).status()).toBe(200)",
    "await expect(card).toHaveCount(1)",
    "await expect(card).toBeVisible()",
    "await card.getByRole('button', { name: '确认这个种子并进入创作契约', exact: true }).click()",
    "const selectionDialog = page.locator('.seed-confirm-dialog').filter({ hasText: '确认创作种子' })",
    "await expect(selectionDialog).toBeVisible()",
    "await expect(selectionDialog.getByText('确认创作种子', { exact: true })).toBeVisible()",
    "const selectedResponse = page.waitForResponse(response => isResponse(response, 'PUT', `/api/projects/${PROJECT_ID}/selected-seed`))",
    "await selectionDialog.getByRole('button', { name: '确认这个种子并进入创作契约', exact: true }).click()",
    "expect((await selectedResponse).status()).toBe(200)",
    "await expect(page.getByText('选定代次 1', { exact: true })).toBeVisible()",
  ]) assert.ok(helper.includes(fragment), `Phase 2 seed bootstrap must include ${fragment}`)
  assert.ok(
    helper.indexOf('const createdResponse = page.waitForResponse')
      < helper.indexOf("seed.getByRole('button', { name: '保存种子', exact: true }).click()"),
    'seed creation waiter must precede the UI save click',
  )
  assert.ok(
    helper.indexOf('const selectedResponse = page.waitForResponse')
      < helper.indexOf("selectionDialog.getByRole('button', { name: '确认这个种子并进入创作契约', exact: true }).click()"),
    'seed selection waiter must precede the modal confirmation click',
  )
})

test('shared Phase 2 bootstrap settles the Bible confirmation before later navigation', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function completePhase2PreparationUi')
  const end = source.indexOf('\nasync function chooseVisibleSelectOption', start)
  const helper = source.slice(start, end)
  const confirmation = helper.indexOf("getByRole('dialog', { name: '确认创作圣经', exact: true }).getByRole('button', { name: '确认签印', exact: true }).click()")
  const settlement = helper.indexOf('await settleNavigationBoundary(page, runtime)', confirmation)
  assert.match(helper, /async function completePhase2PreparationUi\(page, runtime, \{ beforeBibleConfirm = null \} = \{\}\)/u)
  assert.match(helper, /if \(beforeBibleConfirm\) await beforeBibleConfirm\(\)/u)
  assert.ok(confirmation >= 0 && settlement > confirmation, 'Bible confirmation must settle before the helper returns')
  assert.equal((source.match(/runScenarioStage\('[^']+', 'phase2-preparation', \(\) => completePhase2PreparationUi\(page, runtime\)\)/gu) || []).length, 4)
  assert.match(source, /runScenarioStage\('baseline-lock', 'phase2-preparation', \(\) => completePhase2PreparationUi\(page, runtime, \{/u)
  assert.match(source, /runFoundationStage\('phase2-preparation', \(\) => completePhase2PreparationUi\(page, runtime\)\)/u)
  assert.match(source, /runScenarioStage\('revision-outline-session', 'phase2-preparation', \(\) => completePhase2PreparationUi\(page, runtime\)\)/u)
  assert.doesNotMatch(source, /await completePhase2PreparationUi\(page\)/u)
})

test('project creation settles its overview preparation read before shared bootstrap navigation', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function createProjectUi')
  const end = source.indexOf('\nasync function disablePlanningModelUi', start)
  const helper = source.slice(start, end)
  const create = helper.indexOf("getByRole('button', { name: '创建并打开', exact: true }).click()")
  const overview = helper.indexOf("expect.poll(() => new URL(page.url()).pathname).toMatch(/^\\/projects\\/[0-9a-f-]{36}\\/overview$/u)")
  const projectId = helper.indexOf("PROJECT_ID = new URL(page.url()).pathname.split('/')[2]")
  const settle = helper.indexOf('await settleNavigationBoundary(page, runtime)', projectId)
  assert.match(helper, /async function createProjectUi\(page, runtime\)/u)
  assert.ok(create >= 0 && overview > create && projectId > overview && settle > projectId, 'creation, overview, project identity, then settlement must remain ordered')
  assert.equal((source.match(/runScenarioStage\('[^']+', 'create-project', \(\) => createProjectUi\(page, runtime\)\)/gu) || []).length, 5)
  assert.match(source, /runFoundationStage\('create-project', \(\) => createProjectUi\(page, runtime\)\)/u)
  assert.match(source, /runScenarioStage\('revision-outline-session', 'create-project', \(\) => createProjectUi\(page, runtime\)\)/u)
  assert.doesNotMatch(source, /await createProjectUi\(page\)/u)
})

test('every Phase 3 product-write navigation boundary settles through its shared runtime', () => {
  const source = workspace(SPEC)
  const helper = (name, next) => {
    const start = source.indexOf(`async function ${name}`)
    const end = source.indexOf(next.startsWith('test(') ? `\n${next}` : `\nasync function ${next}`, start)
    assert.ok(start >= 0 && end > start, `missing ${name} helper`)
    return source.slice(start, end)
  }
  const ordered = (text, write, navigation, label) => {
    const writeIndex = text.indexOf(write)
    const settleIndex = text.indexOf('await settleNavigationBoundary(page, runtime)', writeIndex)
    const navigationIndex = text.indexOf(navigation, settleIndex)
    assert.ok(writeIndex >= 0 && settleIndex > writeIndex && navigationIndex > settleIndex, label)
  }
  const phase2 = helper('completePhase2PreparationUi', 'chooseVisibleSelectOption')
  ordered(phase2, "selectionDialog.getByRole('button', { name: '确认这个种子并进入创作契约', exact: true }).click()", 'await page.goto(`/projects/${PROJECT_ID}/contract`)', 'selected seed must settle before Contract navigation')
  ordered(phase2, "getByRole('button', { name: '一次确认完整契约' }).click()", 'await page.goto(`/projects/${PROJECT_ID}/bible`)', 'Contract confirmation must settle before Bible navigation')
  const model = helper('disablePlanningModelUi', 'createManualPlanning')
  assert.match(model, /async function disablePlanningModelUi\(page, runtime\)/u)
  assert.ok(model.indexOf("getByRole('button', { name: '保存完整八项' }).click()") < model.indexOf('await settleNavigationBoundary(page, runtime)'))
  const planning = helper('createManualPlanning', 'createOutline')
  ordered(planning, "getByRole('button', { name: '新增分卷' }).click()", "getByRole('link', { name: '情节线', exact: true }).click()", 'Planning volume write must settle before plot navigation')
  ordered(planning, "getByRole('button', { name: '新增情节线' }).click()", "getByRole('link', { name: '故事块', exact: true }).click()", 'Planning plot write must settle before block navigation')
  assert.match(planning, /async function createManualPlanning\(page, title: string, runtime\)/u)
  assert.ok(planning.lastIndexOf("getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()") < planning.lastIndexOf('await settleNavigationBoundary(page, runtime)'))
  const outline = helper('createOutline', 'createPlanningRevision')
  assert.match(outline, /async function createOutline\(page, goal: string, runtime, \{ confirm = true \} = \{\}\)/u)
  assert.ok(outline.lastIndexOf("getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()") < outline.lastIndexOf('await settleNavigationBoundary(page, runtime)'))
  const revision = helper('createPlanningRevision', "test('foundation-manual-r1")
  assert.match(revision, /async function createPlanningRevision\(page, title: string, runtime\)/u)
  assert.ok(revision.lastIndexOf("getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()") < revision.lastIndexOf('await settleNavigationBoundary(page, runtime)'))
  const archiveStart = source.indexOf("test('archived-navigation")
  const archive = source.slice(archiveStart)
  ordered(archive, "card.getByRole('button', { name: '归档', exact: true }).click()", 'await page.goto(volumes())', 'Archive must settle before Planning navigation')
  const revisionScenario = source.slice(source.indexOf("test('revision-outline-session"), source.indexOf("test('unused-outline-supersession"))
  ordered(revisionScenario, "getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()", 'await page.goto(writer())', 'Direct Outline confirmation must settle before Writer navigation')
  for (const [name, foundationStage] of [
    ['completePhase2PreparationUi', 'phase2-preparation'],
    ['disablePlanningModelUi', 'disable-planning-model'],
  ]) {
    assert.equal((source.match(new RegExp(`runScenarioStage\\('[^']+', '${foundationStage}', \\(\\) => ${name}\\(page, runtime\\)\\)`, 'gu')) || []).length, 4, `${name} must share every ordinary non-foundation scenario runtime`)
    assert.match(source, new RegExp(`runFoundationStage\\('${foundationStage}', \\(\\) => ${name}\\(page, runtime\\)\\)`, 'u'))
    assert.match(source, new RegExp(`runScenarioStage\\('revision-outline-session', '${foundationStage}', \\(\\) => ${name}\\(page, runtime\\)\\)`, 'u'))
    assert.doesNotMatch(source, new RegExp(`await ${name}\\(page\\)`, 'u'))
  }
  assert.equal((source.match(/runScenarioStage\('[^']+', 'manual-planning', \(\) => createManualPlanning\(page, [^,]+, runtime\)\)/gu) || []).length, 4, 'createManualPlanning must share every applicable non-foundation scenario runtime')
  assert.match(source, /runFoundationStage\('manual-planning', \(\) => createManualPlanning\(page, '手工规划 R1', runtime\)\)/u)
  assert.match(source, /runScenarioStage\('revision-outline-session', 'manual-planning', \(\) => createManualPlanning\(page, '规划 R1', runtime\)\)/u)
  assert.doesNotMatch(source, /await createManualPlanning\(page, [^,]+\)/u)
})

test('planning-model disablement uses the current visible model-settings route and save control', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function disablePlanningModelUi')
  const end = source.indexOf('\nasync function fillManualVolume', start)
  const helper = source.slice(start, end)
  assert.match(helper, /page\.goto\(`\/projects\/\$\{PROJECT_ID\}\/settings\/models`\)/u)
  assert.match(helper, /await expect\(page\.getByRole\('heading', \{ name: '项目模型绑定', exact: true \}\)\)\.toBeVisible\(\)/u)
  assert.match(helper, /const binding = page\.locator\('\.binding-ledger'\)/u)
  assert.match(helper, /binding\.getByRole\('button', \{ name: \/高级设置 · 分别绑定八项\/u \}\)\.click\(\)/u)
  assert.match(helper, /const planningBinding = binding\.locator\('\.binding-row'\)\.filter\(\{\s*hasText: '创作规划',\s*\}\)/u)
  assert.match(helper, /await expect\(planningBinding\)\.toHaveCount\(1\)/u)
  assert.match(helper, /await expect\(planningBinding\)\.toBeVisible\(\)/u)
  assert.match(helper, /const planningClear = planningBinding\.locator\('\.n-base-clear'\)/u)
  assert.match(helper, /await expect\(planningClear\)\.toHaveCount\(1\)/u)
  assert.match(helper, /await expect\(planningClear\)\.toBeVisible\(\)/u)
  const clear = helper.indexOf('await planningClear.click()')
  const savedResponse = helper.indexOf("const savedResponse = page.waitForResponse(response => isResponse(response, 'PUT', `/api/projects/${PROJECT_ID}/bindings`))")
  const save = helper.indexOf("binding.getByRole('button', { name: '保存完整八项', exact: true }).click()")
  const status = helper.indexOf('expect((await savedResponse).status()).toBe(200)')
  const confirmation = helper.indexOf("binding.getByText('完整八项快照已保存；当前仍有待恢复项。', { exact: true })")
  assert.ok(clear >= 0 && savedResponse > clear && save > savedResponse && status > save && confirmation > status)
  assert.doesNotMatch(helper, /getByRole\('checkbox'|page\.evaluate|Pinia|direct\s+db/u)
  const planningStart = source.indexOf('async function createManualPlanning')
  const planningEnd = source.indexOf('\nasync function createOutline', planningStart)
  assert.match(source.slice(planningStart, planningEnd), /getByRole\('button', \{ name: 'AI 生成当前规划工作稿' \}\)\)\.toBeDisabled\(\)/u)
})

test('Planning and Outline UI mutations wait for their exact create save and confirm responses', () => {
  const source = workspace(SPEC)
  const helper = (name, next) => {
    const start = source.indexOf(`async function ${name}`)
    const end = source.indexOf(next.startsWith('test(') ? `\n${next}` : `\nasync function ${next}`, start)
    assert.ok(start >= 0 && end > start, `missing ${name}`)
    return source.slice(start, end)
  }
  const assertResponseFlow = (text, path, createButton, saveButton, confirmButton, label) => {
    const expected = [
      ['createdResponse', `page.waitForResponse(response => isResponse(response, 'POST', ${path}))`, createButton, '201'],
      ['savedResponse', `page.waitForResponse(response => isResponse(response, 'PUT', draftPath(${path})))`, saveButton, '200'],
      ['confirmedResponse', `page.waitForResponse(response => isResponse(response, 'POST', confirmPath(${path})))`, confirmButton, '201'],
    ]
    for (const [responseName, wait, click, status] of expected) {
      const waitIndex = text.indexOf(wait)
      const clickIndex = text.indexOf(click, waitIndex)
      const statusExpectation = responseName === 'createdResponse' && text.includes('const createdStatus = created.status()')
        ? `if (createdStatus !== ${status})`
        : responseName === 'createdResponse' && (
          text.includes('const created = await createdResponse') || text.includes('return await createdResponse')
        )
          ? `expect(created.status()).toBe(${status})`
          : `expect((await ${responseName}).status()).toBe(${status})`
      const statusIndex = text.indexOf(statusExpectation, clickIndex)
      assert.ok(waitIndex >= 0 && clickIndex > waitIndex && statusIndex > clickIndex, `${label} ${status} response must bracket its UI mutation`)
    }
  }
  const manualPlanning = helper('createManualPlanning', 'createOutline')
  assertResponseFlow(manualPlanning, 'planningDrafts()', "getByRole('button', { name: '建立空白规划工作稿' }).click()", "getByRole('button', { name: '保存工作稿' }).click()", "getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()", 'manual Planning')
  const outline = helper('createOutline', 'createPlanningRevision')
  assertResponseFlow(outline, 'outlineDrafts()', "getByRole('button', { name: '建立新工作稿' }).click()", "getByRole('button', { name: '保存小纲工作稿' }).click()", "getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()", 'Outline')
  const revision = helper('createPlanningRevision', "test('foundation-manual-r1")
  assertResponseFlow(revision, 'planningDrafts()', "getByRole('button', { name: '建立空白规划工作稿' }).click()", "getByRole('button', { name: '保存工作稿' }).click()", "getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()", 'Planning revision')
  assert.doesNotMatch(revision, /基于当前版本建立新工作稿/u)
  assert.equal((source.match(/page\.waitForResponse\(response => isResponse\(response,/gu) || []).length, 15, 'exact response matcher must cover every remaining product write and the stale Bible conflict')
})

test('Outline creation fills the complete visible reference and content contract before its exact save flow', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function createOutline')
  const end = source.indexOf('\nasync function createPlanningRevision', start)
  assert.ok(start >= 0 && end > start, 'missing createOutline helper')
  const outline = source.slice(start, end)
  const ordered = [
    "let stage = 'navigation'",
    "stage = 'create-wait-registration'",
    "stage = 'create-click'",
    "stage = 'create-response'",
    "const outlineSheet = page.locator('.outline-sheet')",
    'await expect(outlineSheet).toHaveCount(1)',
    'await expect(outlineSheet).toBeVisible()',
    "const references = outlineSheet.locator('.reference-grid select')",
    'await expect(references).toHaveCount(2)',
    'await references.nth(0).selectOption({ index: 1 })',
    'await references.nth(1).selectOption({ index: 1 })',
    "const stageReferences = outlineSheet.getByRole('group', { name: '关联阶段', exact: true }).getByRole('checkbox')",
    'await expect(stageReferences).toHaveCount(1)',
    'await stageReferences.check()',
    "const sceneTaskReferences = outlineSheet.getByRole('group', { name: '关联场景任务', exact: true }).getByRole('checkbox')",
    'await expect(sceneTaskReferences).toHaveCount(1)',
    'await sceneTaskReferences.check()',
    "outlineSheet.getByLabel('本章目标', { exact: true }).fill(goal)",
    "outlineSheet.getByLabel('预计出场人物（每行一项）', { exact: true }).fill('沈砚\\n陆青禾')",
    "outlineSheet.getByLabel('承接的未完成情节（每行一项）', { exact: true }).fill('承接被困局面')",
    "outlineSheet.getByLabel('计划推进的任务（每行一项）', { exact: true }).fill('观察换岗')",
    "outlineSheet.getByLabel('主要场景（每行一项）', { exact: true }).fill('废弃驿站侦察')",
    "outlineSheet.getByLabel('不应提前发生的内容（每行一项）', { exact: true }).fill('不可提前揭示内应')",
    "stage = 'save-wait-registration'",
    "stage = 'save-click'",
    "stage = 'save-response'",
    "stage = 'preview-click'",
    "stage = 'confirm-wait-registration'",
    "stage = 'confirm-click'",
    "stage = 'confirm-response'",
    "stage = 'final-settlement'",
  ]
  let previous = -1
  for (const fragment of ordered) {
    const index = outline.indexOf(fragment, previous)
    assert.ok(index > previous, `Outline interaction must precede the next step: ${fragment}`)
    previous = index
  }
  assert.match(outline, /category=behavior leaf=outline-flow stage=\$\{stage\} method=unavailable path=unavailable status=unavailable/u)
  assert.doesNotMatch(outline, /\.first\(\)|page\.evaluate|Pinia|direct\s+db/u)
})

test('Planning revision and revision scenario scope all R1 evidence to unique semantic containers', () => {
  const source = workspace(SPEC)
  const revisionStart = source.indexOf('async function createPlanningRevision')
  const revisionEnd = source.indexOf('\nasync function runFoundationStage', revisionStart)
  assert.ok(revisionStart >= 0 && revisionEnd > revisionStart, 'missing createPlanningRevision helper')
  const revision = source.slice(revisionStart, revisionEnd)
  for (const fragment of [
    "const volumeCards = page.locator('.planning-editor .manuscript-card')",
    'await expect(volumeCards).toHaveCount(1)',
    'await expect(volumeCards).toBeVisible()',
    "volumeCards.getByLabel('卷名', { exact: true }).fill(title)",
  ]) assert.ok(revision.includes(fragment), `revision must use the unique visible planning card: ${fragment}`)
  for (const stage of [
    'navigation', 'create-wait-registration', 'create-click', 'create-response', 'volume-card', 'fill-title',
    'save-wait-registration', 'save-click', 'save-response', 'preview-click', 'confirm-wait-registration',
    'confirm-click', 'confirm-response', 'final-settlement',
  ]) assert.match(revision, new RegExp(`stage = '${stage}'`, 'u'))
  assert.match(revision, /category=behavior leaf=planning-revision-flow stage=\$\{stage\} method=unavailable path=unavailable status=unavailable/u)
  assert.doesNotMatch(revision, /\.first\(\)/u)

  const scenarioStart = source.indexOf("test('revision-outline-session")
  const scenarioEnd = source.indexOf("\ntest('unused-outline-supersession", scenarioStart)
  assert.ok(scenarioStart >= 0 && scenarioEnd > scenarioStart, 'missing revision scenario')
  const scenario = source.slice(scenarioStart, scenarioEnd)
  for (const fragment of [
    "const currentPlanningVersions = page.getByLabel('规划版本')",
    'await expect(currentPlanningVersions).toHaveCount(1)',
    "const currentR1 = currentPlanningVersions.getByText('R1', { exact: true })",
    'await expect(currentR1).toHaveCount(1)',
    "const planningHistory = page.getByRole('dialog', { name: '规划修订历史', exact: true })",
    'await expect(planningHistory).toHaveCount(1)',
    "const historicalR1 = planningHistory.getByText('R1', { exact: true })",
    'await expect(historicalR1).toHaveCount(1)',
  ]) assert.ok(scenario.includes(fragment), `revision scenario must scope exact R1 evidence: ${fragment}`)
  assert.doesNotMatch(scenario, /getByText\('R1', \{ exact: false \}\)/u)
})

test('Phase 3 spec contains the six ordered UI-only acceptance scenarios', () => {
  const source = workspace(SPEC)
  const scenarios = [
    'foundation-manual-r1',
    'revision-outline-session',
    'unused-outline-supersession',
    'pinned-session',
    'baseline-lock',
    'archived-navigation',
  ]
  let prior = -1
  for (const scenario of scenarios) {
    const index = source.indexOf(scenario)
    assert.notEqual(index, -1, `missing scenario ${scenario}`)
    assert.equal(index > prior, true, `scenario order changed at ${scenario}`)
    prior = index
  }
  for (const phrase of [
    '尚无已定稿事实',
    'zero Session POST before confirmation',
    'Planning R2',
    'Outline R1',
    'goBack',
    'goForward',
    'page.reload',
  ]) assert.match(source, new RegExp(phrase, 'u'))
  assert.doesNotMatch(source, /剧情线/u)
})

test('the fourteen roadmap outcomes are explicitly mapped to formal browser evidence', () => {
  const source = workspace(SPEC)
  const outcomes = [
    ['foundation-manual-r1', 'completePhase2PreparationUi', []],
    ['foundation-manual-r1', 'toBeDisabled', ['createManualPlanning']],
    ['foundation-manual-r1', '新增场景任务', ['createManualPlanning']],
    ['revision-outline-session', '规划修订历史', []],
    ['foundation-manual-r1', '建立空白规划工作稿', ['createManualPlanning']],
    ['revision-outline-session', '预览并确认小纲', ['createOutline']],
    ['revision-outline-session', 'zero Session POST before confirmation', []],
    ['unused-outline-supersession', '已被后续依据取代', []],
    ['pinned-session', 'Planning R1', []],
    ['baseline-lock', '保存冲突：本地编辑仍保留，请重新加载权威版本后再继续。', ['assertBaselineStaleBibleConfirmUi']],
    ['archived-navigation', 'page.goForward', []],
    ['foundation-manual-r1', '尚无已定稿事实', []],
    ['foundation-manual-r1', 'network-audit', ['runAudited', 'finishRuntime']],
    ['archived-navigation', 'assertExactWrites', ['runAudited', 'finishRuntime']],
  ]
  const declarations = text => [...text.matchAll(/test\('([a-z0-9-]+):/gu)].map(match => match[1])
  const scenarioSlice = (text, scenario) => {
    const start = text.indexOf(`test('${scenario}:`)
    const end = text.indexOf("\ntest('", start + 1)
    return start < 0 ? '' : text.slice(start, end < 0 ? text.length : end)
  }
  const helperSlice = (text, helper) => {
    const start = text.indexOf(`function ${helper}`) >= 0
      ? text.indexOf(`function ${helper}`)
      : text.indexOf(`async function ${helper}`)
    const end = text.indexOf('\nfunction ', start + 1)
    return start < 0 ? '' : text.slice(start, end < 0 ? text.length : end)
  }
  const assertMapped = text => {
    assert.deepEqual(declarations(text), [
      'foundation-manual-r1', 'revision-outline-session', 'unused-outline-supersession',
      'pinned-session', 'baseline-lock', 'archived-navigation',
    ])
    for (const [scenario, evidence, helpers] of outcomes) {
      const slice = scenarioSlice(text, scenario)
      const graph = [slice]
      let caller = slice
      for (const helper of helpers) {
        assert.ok(caller.includes(helper), `${scenario} helper graph must call ${helper}`)
        caller = helperSlice(text, helper)
        graph.push(caller)
      }
      assert.match(graph.join('\n'), new RegExp(evidence.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'))
    }
  }
  assert.equal(outcomes.length, 14)
  assertMapped(source)
  assert.throws(() => assertMapped(`${source}\ntest('extra-scenario: mutation', async () => {})`))
  assert.throws(() => assertMapped(source.replace("test('baseline-lock:", "test('baseline-lock-removed:")))
  assert.throws(() => assertMapped(source.replace('已被后续依据取代', '错放 outcome')))
})

test('Phase 3 runner stays closed, uses neutral support, and preserves lifecycle failures', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const source = workspace(RUNNER)
  assert.deepEqual(runner.FORMAL_SPECS, ['phase3-story-planning.spec.ts'])
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase3.config.ts')
  assert.equal(runner.resolveCommandLineSpecs([])[0], 'phase3-story-planning.spec.ts')
  assert.throws(() => runner.resolveCommandLineSpecs(['other.spec.ts']), /does not accept spec paths/iu)
  assert.doesNotMatch(source, /run-phase3[bc]|phase3[bc]-story|phase3[bc]-volumes/iu)
  assert.match(source, /\.\/support\/product-runner\.mjs/u)
  assert.match(source, /runOwnedProductLifecycle/u)
  assert.match(source, /export async function exercisePhase3Lifecycle[\s\S]*?return runOwnedProductLifecycle\(/u)
  assert.match(source, /lifecycleRunner = exercisePhase3Lifecycle/u)
  assert.match(source, /await lifecycleRunner\(\{/u)
  assert.match(source, /assertArtifacts = assertSafeFiles/u)
  assert.match(source, /assertSafeFile = assertSafeTextFile/u)
  assert.doesNotMatch(source, /assertSafeFiles\(ownedRoot, sensitiveValues\)/u)
  assert.match(source, /export function auditAndRemovePhase3Root\([\s\S]*?assertArtifacts\(artifactRoot, sensitiveValues\)[\s\S]*?removeRoot\(ownedRoot, OWNED_ROOT_PREFIX\)/u)
  assert.match(source, /async cleanupRoot\(ownedRoot\) \{[\s\S]*?auditAndRemovePhase3Root\([\s\S]*?removeRoot: ownedRootRemover/u)

  const calls = []
  const first = new Error('initialization sentinel')
  const second = new Error('cleanup sentinel')
  await assert.rejects(
    runner.exercisePhase3Lifecycle({
      registerRoot(lifecycle) {
        calls.push('root')
        lifecycle.setRoot('root')
        lifecycle.setDatabase('database')
        lifecycle.registerServer('server')
        lifecycle.registerReservation('reservation')
      },
      async initialize() { calls.push('initialize'); throw first },
      async cleanupServers() { calls.push('servers'); throw second },
      async cleanupReservations() { calls.push('reservations') },
      async cleanupDatabase() { calls.push('database') },
      async cleanupRoot() { calls.push('root-cleanup') },
    }),
    error => error instanceof AggregateError && error.errors.includes(first) && error.errors.includes(second),
  )
  assert.deepEqual(calls, ['root', 'initialize', 'servers', 'reservations', 'database', 'root-cleanup'])
})

test('Phase 3 runner accepts exactly one passed focused scenario from the browser report', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'revision-outline-session'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'passed' }] }])])
  assert.equal(runner.assertFocusedScenarioReport(report, 'revision-outline-session'), true)
  assert.throws(
    () => runner.assertFocusedScenarioReport({ suites: [] }, 'revision-outline-session'),
    /exactly one passed focused scenario/iu,
  )
  for (const malformed of [
    playwrightReport([
      playwrightSpec(scenario, [{ results: [{ status: 'passed' }] }]),
      playwrightSpec(scenario, [{ results: [{ status: 'passed' }] }]),
    ]),
    playwrightReport([
      playwrightSpec(scenario, []),
      playwrightSpec(scenario, [{ results: [{ status: 'passed' }] }]),
    ]),
    playwrightReport([playwrightSpec(scenario, [
      { results: [{ status: 'passed' }] }, { results: [{ status: 'passed' }] },
    ])]),
    playwrightReport([playwrightSpec(scenario, [{
      results: [{ status: 'passed' }, { status: 'passed' }],
    }])]),
    playwrightReport([playwrightSpec('wrong-scenario', [{ results: [{ status: 'passed' }] }])]),
  ]) {
    assert.throws(
      () => runner.assertFocusedScenarioReport(malformed, scenario),
      /exactly one passed focused scenario/iu,
    )
  }
  assert.equal(
    runner.assertScenarioReports(
      runner.FORMAL_SCENARIOS.map(item => playwrightReport([playwrightSpec(item, [{ results: [{ status: 'passed' }] }])])),
      runner.FORMAL_SCENARIOS,
    ),
    true,
  )
})

test('browser failure diagnostics identify only the closed scenario and a safe write category', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const report = playwrightReport([playwrightSpec('baseline-lock', [{
    results: [{ status: 'failed', errors: [{
      message: 'Unmatched runtime write: POST /api/projects/01234567-89ab-cdef-0123-456789abcdef/seeds secret=never-print',
    }] }],
  }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'baseline-lock', ['never-print']),
    error => (
      error instanceof Error
       && error.message.includes('scenario=baseline-lock')
      && error.message.includes('category=browser')
      && error.message.includes('browser.leaf=write-unmatched method=POST path=/api/projects/:id/seeds status=unmatched count=unexpected')
      && !error.message.includes('never-print')
    ),
  )
})

test('browser failure diagnostics retain only a strictly valid fixed spec projection', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const safeMessage = 'category=audit leaf=write-unmatched method=POST path=/api/projects/:id/seeds status=unmatched count=unexpected'
  const report = playwrightReport([playwrightSpec('foundation-manual-r1', [{
    results: [{ status: 'failed', errors: [{ message: safeMessage }] }],
  }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'foundation-manual-r1', ['never-print']),
    error => error?.message.includes(safeMessage),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = `${safeMessage} never-print`
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'foundation-manual-r1', ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
})

test('browser diagnostics accept exactly one Playwright AggregateError prefix before a fixed projection', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const projection = 'category=audit leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable'
  const message = `AggregateError: ${projection}`
  const report = playwrightReport([playwrightSpec('foundation-manual-r1', [{
    results: [{ status: 'failed', errors: [{ message }] }],
  }])])
  let failure
  try { runner.phase3BrowserFailure(report, 'foundation-manual-r1', ['never-print']) } catch (error) { failure = error }
  assert.match(failure.message, new RegExp(`scenario=foundation-manual-r1 ${projection}`, 'u'))
  assert.match(runner.formatPhase3CommandFailure(failure, { scenario: 'foundation-manual-r1' }), /category=audit/u)
  for (const unsafe of [
    `AggregateError: Error: ${projection}`,
    `prefix AggregateError: ${projection}`,
    `AggregateError: ${projection} never-print`,
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = unsafe
    assert.throws(
      () => runner.phase3BrowserFailure(report, 'foundation-manual-r1', ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
})

test('browser diagnostics admit only one safe first-line projection before a non-sensitive Playwright call log', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const projection = 'category=audit leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable'
  const benignCallLog = 'Call log:\n  - waiting for a response that never arrived'
  const report = playwrightReport([playwrightSpec(scenario, [{
    results: [{ status: 'failed', errors: [{ message: `Error: ${projection}\n${benignCallLog}` }] }],
  }])])

  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(`scenario=${scenario} ${projection}`)
      && !error.message.includes('Call log')
      && !error.message.includes('waiting for a response'),
  )

  for (const unsafe of [
    `Error: ${projection} extra=field`,
    `Error: ${projection.replace('leaf=unavailable', 'leaf=unknown')}\n${benignCallLog}`,
    `\nError: ${projection}\n${benignCallLog}`,
    `${benignCallLog}\nError: ${projection}`,
    `Error: ${projection}\nError: ${projection}`,
    `Error: ${projection}\n${benignCallLog} never-print`,
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = unsafe
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized')
        && !error.message.includes('never-print')
        && !error.message.includes('Call log')
        && !error.message.includes('waiting for a response'),
    )
  }
})

test('browser failure fallback projects only closed Playwright report structure', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const cases = [
    {
      label: 'test-missing',
      report: { suites: [{ specs: [{ tests: [] }] }] },
      expected: 'errorName=Unknown testCount=0 resultCount=0 errorCount=0 messageCount=0 topLevelErrorCount=0 topLevelCategory=unknown',
    },
    {
      label: 'failed-result-missing',
      report: playwrightReport([playwrightSpec(scenario, [{ results: [] }])]),
      expected: 'errorName=Unknown testCount=1 resultCount=0 errorCount=0 messageCount=0',
    },
    {
      label: 'error-object-missing',
      report: playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [] }] }])]),
      expected: 'errorName=Unknown testCount=1 resultCount=1 errorCount=0 messageCount=0',
    },
    {
      label: 'message-missing',
      report: playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ name: 'Error' }] }] }])]),
      expected: 'errorName=Error testCount=1 resultCount=1 errorCount=1 messageCount=0',
    },
    {
      label: 'message-unrecognized',
      report: playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ name: 'TimeoutError', message: 'Authorization: Bearer never-print' }] }] }])]),
      expected: 'errorName=TimeoutError testCount=1 resultCount=1 errorCount=1 messageCount=1',
    },
  ]
  for (const { label, report, expected } of cases) {
    let failure
    try {
      runner.phase3BrowserFailure(report, scenario, ['never-print'])
    } catch (error) {
      failure = error
    }
    const projection = `scenario=${scenario} category=browser leaf=report-${label} ${expected}`
    assert.match(failure?.message || '', new RegExp(projection, 'u'))
    assert.doesNotMatch(failure?.message || '', /Authorization|never-print|visible UI|stack|title|location|snippet|body|header/u)
    assert.match(
      runner.formatPhase3CommandFailure(failure, { scenario }),
      new RegExp(`category=browser[\\s\\S]*${projection}`, 'u'),
    )
  }
  const forged = new Error(
    `scenario=${scenario} category=browser leaf=report-test-missing errorName=Unknown testCount=0 resultCount=0 errorCount=0 messageCount=0 never-print`,
  )
  assert.doesNotMatch(
    runner.formatPhase3CommandFailure(forged, { scenario }),
    /never-print|leaf=report-test-missing/u,
  )
})

test('browser failure fallback projects only top-level Playwright report errors when its test is missing', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const base = { suites: [{ specs: [{ tests: [] }] }] }
  const cases = [
    {
      report: { ...base, errors: [{ name: 'SyntaxError', message: 'private source snippet never-print' }] },
      expected: 'category=browser leaf=report-test-missing errorName=Unknown testCount=0 resultCount=0 errorCount=1 messageCount=1 topLevelErrorCount=1 topLevelCategory=syntax',
    },
    {
      report: { ...base, errors: [{ name: 'Error', message: "Error: Cannot find module 'never-print'" }] },
      expected: 'category=browser leaf=report-test-missing errorName=Error testCount=0 resultCount=0 errorCount=1 messageCount=1 topLevelErrorCount=1 topLevelCategory=module-load',
    },
    {
      report: { ...base, errors: [{ name: 'TimeoutError', message: 'timeout body never-print' }, 'not-an-error'] },
      expected: 'category=browser leaf=report-test-missing errorName=TimeoutError testCount=0 resultCount=0 errorCount=1 messageCount=1 topLevelErrorCount=1 topLevelCategory=timeout',
    },
  ]
  for (const { report, expected } of cases) {
    let failure
    try { runner.phase3BrowserFailure(report, scenario, ['never-print']) } catch (error) { failure = error }
    assert.match(failure?.message || '', new RegExp(`scenario=${scenario} ${expected}`, 'u'))
    assert.doesNotMatch(failure?.message || '', /never-print|snippet|timeout body|message:|stack|location/u)
    assert.match(
      runner.formatPhase3CommandFailure(failure, { scenario }),
      new RegExp(`category=browser[\\s\\S]*scenario=${scenario} ${expected}`, 'u'),
    )
  }
  const projection = 'category=audit leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable'
  let projectedFailure
  try {
    runner.phase3BrowserFailure({ ...base, errors: [{ name: 'AggregateError', message: `AggregateError: ${projection}` }] }, scenario, ['never-print'])
  } catch (error) { projectedFailure = error }
  assert.match(projectedFailure?.message || '', new RegExp(`scenario=${scenario} ${projection}`, 'u'))
  assert.doesNotMatch(projectedFailure?.message || '', /never-print|AggregateError/u)
})

test('browser failure fallback ignores top-level Playwright errors when its test exists', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = {
    ...playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [] }] }])]),
    errors: [{ name: 'TypeError', message: 'never-print' }],
  }
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(
      'leaf=report-error-object-missing errorName=Unknown testCount=1 resultCount=1 errorCount=0 messageCount=0 topLevelErrorCount=0 topLevelCategory=unknown',
    ) && !error.message.includes('never-print'),
  )
})

test('finishRuntime projects a single safe top-level browser message', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('function normalizedRuntimeApiPath')
  const end = source.indexOf('\nasync function finishRuntime', start)
  assert.notEqual(start, -1, 'missing runtime failure projection')
  const projection = new Function(
    `${source.slice(start, end)}; return projectPhase3FailureMessage`,
  )()
  const bodyError = new Error('locator text must never print: never-print')
  const auditError = new Error(
    'Unmatched runtime write: POST /api/projects/01234567-89ab-cdef-0123-456789abcdef/seeds never-print',
  )
  const thrown = new Error(projection(bodyError, auditError, 'exact-writes'))
  assert.equal(
    thrown.message,
    'category=audit leaf=write-unmatched method=POST path=/api/projects/:id/seeds status=unmatched count=unexpected',
  )
  assert.doesNotMatch(thrown.message, /never-print|locator/u)
  assert.equal(Object.hasOwn(thrown, 'errors'), false)
  assert.equal(Object.hasOwn(thrown, 'cause'), false)
  assert.match(source, /const safeProjection = projectPhase3FailureMessage\(bodyError, auditFailure\?\.error, auditFailure\?\.stage, evidence, expectedWrites, resolvedRuntimeAuditOptions\)/u)
  assert.match(source, /if \(bodyError \|\| auditFailure\) throw new Error\(safeProjection\)/u)
})

test('write-count mismatches project only their exact safe allowlist rule and match count', async () => {
  const source = workspace(SPEC)
  const start = source.indexOf('function normalizedRuntimeApiPath')
  const end = source.indexOf('\nasync function finishRuntime', start)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(start, end)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const seedPath = `/api/projects/${id}/seeds`
  const evidence = { apiResponses: [{ method: 'POST', url: `http://127.0.0.1:43123${seedPath}`, status: 200 }] }
  const rules = [{ method: 'POST', path: seedPath, statuses: [200], count: 2 }]
  const mismatch = new Error('Runtime write count did not match allowlist entry 0')
  const projection = project(null, mismatch, 'exact-writes', evidence, rules)
  assert.equal(
    projection,
    'category=audit leaf=write-count ruleIndex=0 method=POST path=/api/projects/:id/seeds status=allowed expectedCount=2 actualCount=1',
  )
  assert.doesNotMatch(projection, /01234567|127\.0\.0\.1|header|body/u)
  const unavailable = 'category=audit leaf=write-count method=allowed path=allowed status=allowed count=mismatch'
  assert.equal(project(null, new Error('Runtime write count did not match allowlist entry 1'), 'exact-writes', evidence, rules), unavailable)
  assert.equal(project(null, mismatch, 'exact-writes', evidence, [{ ...rules[0], method: 'GET' }]), unavailable)
  assert.equal(project(null, mismatch, 'exact-writes', evidence, [rules[0], { ...rules[0] }]), unavailable)
  assert.equal(
    project(null, mismatch, 'exact-writes', evidence, [{ method: 'POST', path: /^\/api\/projects\/[^/]+\/seeds$/u, statuses: [200], count: 2 }]),
    'category=audit leaf=write-count ruleIndex=0 method=POST path=allowed status=allowed expectedCount=2 actualCount=1',
  )
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: projection }] }] }])])
  let failure
  try { runner.phase3BrowserFailure(report, scenario, ['never-print']) } catch (error) { failure = error }
  assert.match(failure?.message || '', new RegExp(projection, 'u'))
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = `${projection} never-print`
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = projection.replace('method=POST', 'method=TRACE')
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = projection.replace('path=/api/projects/:id/seeds', 'path=/api/projects/:id/never-print')
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
})

test('write-count metadata counts only safe loopback request and response records for its selected rule', async () => {
  const source = workspace(SPEC)
  const start = source.indexOf('function normalizedRuntimeApiPath')
  const end = source.indexOf('\nasync function finishRuntime', start)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(start, end)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const seedPath = `/api/projects/${id}/seeds`
  const mismatch = new Error('Runtime write count did not match allowlist entry 0')
  const rules = [{ method: 'POST', path: seedPath, statuses: [201], count: 1 }]
  const evidence = {
    apiResponses: [],
    requests: [
      { method: 'GET', url: 'data:text/plain,never-print', headers: { authorization: 'never-print' }, body: 'never-print' },
      { method: 'GET', url: 'blob:https://example.com/never-print', headers: { authorization: 'never-print' }, body: 'never-print' },
      { method: 'POST', url: `http://127.0.0.1:43123${seedPath}?authorization=never-print`, headers: { authorization: 'never-print' }, body: 'never-print', errorText: 'never-print' },
    ],
    responses: [
      { method: 'GET', url: 'data:text/plain,never-print', status: 200, headers: { authorization: 'never-print' }, body: 'never-print' },
      { method: 'GET', url: 'blob:https://example.com/never-print', status: 200, headers: { authorization: 'never-print' }, body: 'never-print' },
      { method: 'POST', url: `http://127.0.0.1:43123${seedPath}?authorization=never-print`, status: 201, headers: { authorization: 'never-print' }, body: 'never-print', errorText: 'never-print' },
    ],
  }
  const projection = project(null, mismatch, 'exact-writes', evidence, rules)
  assert.equal(
    projection,
    'category=audit leaf=write-count ruleIndex=0 method=POST path=/api/projects/:id/seeds status=allowed expectedCount=1 actualCount=0 requestMetadataCount=1 responseMetadataCount=1 normalizedRequestMetadataCount=1 normalizedResponseMetadataCount=1',
  )
  assert.doesNotMatch(projection, /01234567|127\.0\.0\.1|authorization|never-print|header|body|error/u)
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: projection }] }] }])])
  let failure
  try { runner.phase3BrowserFailure(report, scenario, ['never-print']) } catch (error) { failure = error }
  assert.match(failure?.message || '', new RegExp(projection, 'u'))
  for (const malformed of [
    projection.replace('requestMetadataCount=1', 'requestMetadataCount=-1'),
    projection.replace('requestMetadataCount=1', 'requestMetadataCount=1e2'),
    projection.replace('responseMetadataCount=1', 'responseMetadataCount=1.5'),
    projection.replace('normalizedRequestMetadataCount=1', 'normalizedRequestMetadataCount=-1'),
    projection.replace('normalizedResponseMetadataCount=1', 'normalizedResponseMetadataCount=1.5'),
    projection.replace('normalizedRequestMetadataCount=1 ', ''),
    `${projection} header=never-print`,
    projection.replace('path=/api/projects/:id/seeds', 'path=/api/projects/:id/seeds?authorization=never-print'),
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
  const alternateId = 'fedcba98-7654-3210-fedc-ba9876543210'
  const alternatePath = `/api/projects/${alternateId}/seeds`
  const normalizedOnly = project(null, mismatch, 'exact-writes', {
    ...evidence,
    requests: [{ ...evidence.requests[2], url: `http://127.0.0.1:43123${alternatePath}?authorization=never-print` }],
    responses: [{ ...evidence.responses[2], url: `http://127.0.0.1:43123${alternatePath}?authorization=never-print` }],
  }, rules)
  assert.equal(
    normalizedOnly,
    'category=audit leaf=write-count ruleIndex=0 method=POST path=/api/projects/:id/seeds status=allowed expectedCount=1 actualCount=0 requestMetadataCount=0 responseMetadataCount=0 normalizedRequestMetadataCount=1 normalizedResponseMetadataCount=1',
  )
  assert.doesNotMatch(normalizedOnly, /01234567|fedcba98|127\.0\.0\.1|authorization|never-print|header|body|error/u)
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = normalizedOnly
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(normalizedOnly) && !error.message.includes('never-print'),
  )
  const unavailable = 'category=audit leaf=write-count method=allowed path=allowed status=allowed count=mismatch'
  assert.equal(
    project(null, mismatch, 'exact-writes', {
      ...evidence,
      requests: [{ ...evidence.requests[0], url: `https://example.com${seedPath}` }],
    }, rules),
    unavailable,
  )
  assert.equal(
    project(null, mismatch, 'exact-writes', {
      ...evidence,
      responses: [{ ...evidence.responses[0], status: '201' }],
    }, rules),
    unavailable,
  )
  assert.equal(
    project(null, mismatch, 'exact-writes', {
      ...evidence,
      requests: [{ method: 'GET', url: 'not a URL' }],
    }, rules),
    unavailable,
  )
  assert.equal(
    project(null, mismatch, 'exact-writes', {
      ...evidence,
      requests: [{ method: 'TRACE', url: `http://127.0.0.1:43123${seedPath}` }],
    }, rules),
    unavailable,
  )
})

test('finishRuntime category follows the audit channel even when its leaf is unavailable', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('function normalizedRuntimeApiPath')
  const end = source.indexOf('\nasync function finishRuntime', start)
  const projection = new Function(
    'runtimeFailureDiagnostic',
    `${source.slice(start, end)}; return projectPhase3FailureMessage`,
  )(() => null)
  const bodyError = new Error('body never-print')
  const auditError = new Error('audit never-print')
  assert.equal(
    projection(null, auditError),
    'category=audit leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable',
  )
  assert.equal(
    projection(bodyError, null),
    'category=behavior leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable',
  )
  assert.equal(
    projection(bodyError, auditError),
    'category=audit leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable',
  )
  const aggregate = new AggregateError([bodyError, auditError], projection(bodyError, auditError))
  assert.deepEqual(aggregate.errors, [bodyError, auditError])
  assert.doesNotMatch(aggregate.message, /never-print/u)
})

test('strict Task5 body diagnostics outrank exact-write audit projections without trusting other body errors', async () => {
  const source = workspace(SPEC)
  const start = source.indexOf('function normalizedRuntimeApiPath')
  const end = source.indexOf('\nasync function finishRuntime', start)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(start, end)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const path = `/api/projects/${id}/seeds`
  const auditError = new Error('Runtime write count did not match allowlist entry 0')
  const evidence = { apiResponses: [{ method: 'POST', url: `http://127.0.0.1:43123${path}`, status: 200 }] }
  const writes = [{ method: 'POST', path, statuses: [200], count: 2 }]
  const auditProjection = 'category=audit leaf=write-count ruleIndex=0 method=POST path=/api/projects/:id/seeds status=allowed expectedCount=2 actualCount=1'
  const probe = new Error('category=behavior leaf=observer-progress method=POST path=/api/projects/:id/planning/drafts status=201 requestStage=scheduled responseStage=metadata')
  assert.equal(project(probe, auditError, 'exact-writes', evidence, writes), probe.message)
  for (const bodyError of [
    new Error(`${probe.message} secret=never-print`),
    new Error('category=behavior leaf=unknown secret=never-print'),
  ]) {
    const projection = project(bodyError, auditError, 'exact-writes', evidence, writes)
    assert.equal(projection, auditProjection)
    assert.doesNotMatch(projection, /never-print/u)
  }
})

test('planning create flow stages outrank concurrent audits and remain a closed behavior projection', async () => {
  const source = workspace(SPEC)
  const projectionStart = source.indexOf('function normalizedRuntimeApiPath')
  const projectionEnd = source.indexOf('\nasync function finishRuntime', projectionStart)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(projectionStart, projectionEnd)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const path = `/api/projects/${id}/seeds`
  const auditError = new Error('Runtime write count did not match allowlist entry 0')
  const evidence = { responses: [{ method: 'POST', url: `http://127.0.0.1:43123${path}`, status: 200 }] }
  const writes = [{ method: 'POST', path, statuses: [200], count: 2 }]
  const flowProjection = 'category=behavior leaf=planning-create-flow stage=button-click method=POST path=/api/projects/:id/planning/drafts status=unavailable'
  assert.equal(project(new Error(flowProjection), auditError, 'exact-writes', evidence, writes), flowProjection)
  for (const stage of ['navigation', 'listener-check', 'wait-registration', 'button-click', 'response-wait']) {
    const projection = flowProjection.replace('stage=button-click', `stage=${stage}`)
    assert.equal(project(new Error(projection), auditError, 'exact-writes', evidence, writes), projection)
  }

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: flowProjection }] }] }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(flowProjection) && !error.message.includes('never-print'),
  )
  for (const malformed of [
    flowProjection.replace('stage=button-click', 'stage=other'),
    flowProjection.replace('method=POST', 'method=PUT'),
    flowProjection.replace('path=/api/projects/:id/planning/drafts', 'path=/api/projects/:id/never-print'),
    flowProjection.replace('status=unavailable', 'status=201'),
    flowProjection.replace('stage=button-click method=POST', 'method=POST stage=button-click'),
    `${flowProjection} secret=never-print`,
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
})

test('planning create status outranks concurrent audits and remains a closed behavior projection', async () => {
  const source = workspace(SPEC)
  const projectionStart = source.indexOf('function normalizedRuntimeApiPath')
  const projectionEnd = source.indexOf('\nasync function finishRuntime', projectionStart)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(projectionStart, projectionEnd)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const path = `/api/projects/${id}/seeds`
  const auditError = new Error('Runtime write count did not match allowlist entry 0')
  const evidence = { responses: [{ method: 'POST', url: `http://127.0.0.1:43123${path}`, status: 200 }] }
  const writes = [{ method: 'POST', path, statuses: [200], count: 2 }]
  const statusProjection = 'category=behavior leaf=planning-create-status method=POST path=/api/projects/:id/planning/drafts status=503'
  assert.equal(project(new Error(statusProjection), auditError, 'exact-writes', evidence, writes), statusProjection)
  for (const status of [100, 201, 503, 599]) {
    const projection = statusProjection.replace('status=503', `status=${status}`)
    assert.equal(project(new Error(projection), auditError, 'exact-writes', evidence, writes), projection)
  }

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: statusProjection }] }] }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(statusProjection) && !error.message.includes('never-print'),
  )
  for (const malformed of [
    statusProjection.replace('method=POST', 'method=PUT'),
    statusProjection.replace('path=/api/projects/:id/planning/drafts', 'path=/api/projects/:id/never-print'),
    statusProjection.replace('status=503', 'status=99'),
    statusProjection.replace('status=503', 'status=600'),
    statusProjection.replace('status=503', 'status=unavailable'),
    statusProjection.replace('method=POST path=', 'path=/api/projects/:id/planning/drafts method=POST path='),
    `${statusProjection} secret=never-print`,
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
})

test('planning manual flow stages outrank concurrent audits and remain a closed behavior projection', async () => {
  const source = workspace(SPEC)
  const projectionStart = source.indexOf('function normalizedRuntimeApiPath')
  const projectionEnd = source.indexOf('\nasync function finishRuntime', projectionStart)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(projectionStart, projectionEnd)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const path = `/api/projects/${id}/seeds`
  const auditError = new Error('Runtime write count did not match allowlist entry 0')
  const evidence = { responses: [{ method: 'POST', url: `http://127.0.0.1:43123${path}`, status: 200 }] }
  const writes = [{ method: 'POST', path, statuses: [200], count: 2 }]
  const stages = [
    'ai-disabled', 'add-volume', 'fill-volume', 'settle-volume', 'open-plots', 'add-plot', 'fill-plot',
    'settle-plot', 'open-blocks', 'add-block', 'fill-block', 'add-stage', 'fill-stage', 'add-scene-task',
    'fill-scene-task', 'activate-block', 'save-wait-registration', 'save-click', 'save-response',
    'preview-click', 'confirm-wait-registration', 'confirm-click', 'confirm-response', 'final-settlement',
  ]
  const flowProjection = 'category=behavior leaf=planning-manual-flow stage=add-plot method=unavailable path=unavailable status=unavailable'
  assert.equal(project(new Error(flowProjection), auditError, 'exact-writes', evidence, writes), flowProjection)
  for (const stage of stages) {
    const projection = flowProjection.replace('stage=add-plot', `stage=${stage}`)
    assert.equal(project(new Error(projection), auditError, 'exact-writes', evidence, writes), projection)
  }

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: flowProjection }] }] }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(flowProjection) && !error.message.includes('never-print'),
  )
  for (const malformed of [
    flowProjection.replace('stage=add-plot', 'stage=other'),
    flowProjection.replace('method=unavailable', 'method=POST'),
    flowProjection.replace('path=unavailable', 'path=/api/projects/:id/planning/drafts'),
    flowProjection.replace('status=unavailable', 'status=200'),
    flowProjection.replace('stage=add-plot method=unavailable', 'method=unavailable stage=add-plot'),
    `${flowProjection} secret=never-print`,
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
})

test('outline flow stages outrank concurrent audits and remain a closed behavior projection', async () => {
  const source = workspace(SPEC)
  const projectionStart = source.indexOf('function normalizedRuntimeApiPath')
  const projectionEnd = source.indexOf('\nasync function finishRuntime', projectionStart)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(projectionStart, projectionEnd)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const path = `/api/projects/${id}/seeds`
  const auditError = new Error('Runtime write count did not match allowlist entry 0')
  const evidence = { responses: [{ method: 'POST', url: `http://127.0.0.1:43123${path}`, status: 200 }] }
  const writes = [{ method: 'POST', path, statuses: [200], count: 2 }]
  const stages = [
    'navigation', 'create-wait-registration', 'create-click', 'create-response', 'outline-sheet',
    'reference-selects', 'stage-references', 'scene-task-references', 'fill-goal', 'fill-characters',
    'fill-continuation', 'fill-tasks', 'fill-scenes', 'fill-forbidden', 'save-wait-registration',
    'save-click', 'save-response', 'preview-click', 'confirm-wait-registration', 'confirm-click',
    'confirm-response', 'final-settlement',
  ]
  const flowProjection = 'category=behavior leaf=outline-flow stage=fill-goal method=unavailable path=unavailable status=unavailable'
  for (const stage of stages) {
    const projection = flowProjection.replace('stage=fill-goal', `stage=${stage}`)
    assert.equal(project(new Error(projection), auditError, 'exact-writes', evidence, writes), projection)
  }

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'revision-outline-session'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: flowProjection }] }] }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(flowProjection) && !error.message.includes('never-print'),
  )
  for (const malformed of [
    flowProjection.replace('stage=fill-goal', 'stage=other'),
    flowProjection.replace('method=unavailable', 'method=POST'),
    flowProjection.replace('path=unavailable', 'path=/api/projects/:id/outlines/drafts'),
    flowProjection.replace('status=unavailable', 'status=200'),
    `${flowProjection} secret=never-print`,
  ]) {
    const projected = project(new Error(malformed), auditError, 'exact-writes', evidence, writes)
    assert.notEqual(projected, malformed)
    assert.doesNotMatch(projected, /other|never-print/u)
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
})

test('foundation stages outrank concurrent audits and remain a closed behavior projection', async () => {
  const source = workspace(SPEC)
  const projectionStart = source.indexOf('function normalizedRuntimeApiPath')
  const projectionEnd = source.indexOf('\nasync function finishRuntime', projectionStart)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(projectionStart, projectionEnd)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const path = `/api/projects/${id}/seeds`
  const auditError = new Error('Runtime write count did not match allowlist entry 0')
  const evidence = { responses: [{ method: 'POST', url: `http://127.0.0.1:43123${path}`, status: 200 }] }
  const writes = [{ method: 'POST', path, statuses: [200], count: 2 }]
  const stages = ['create-project', 'phase2-preparation', 'disable-planning-model', 'manual-planning', 'post-planning']
  const projection = 'category=behavior leaf=foundation-stage stage=disable-planning-model method=unavailable path=unavailable status=unavailable'
  assert.equal(project(new Error(projection), auditError, 'exact-writes', evidence, writes), projection)
  for (const stage of stages) {
    const projected = projection.replace('stage=disable-planning-model', `stage=${stage}`)
    assert.equal(project(new Error(projected), auditError, 'exact-writes', evidence, writes), projected)
  }

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: projection }] }] }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(projection) && !error.message.includes('never-print'),
  )
  for (const malformed of [
    projection.replace('stage=disable-planning-model', 'stage=other'),
    projection.replace('method=unavailable', 'method=POST'),
    projection.replace('path=unavailable', 'path=/api/projects/:id/planning/drafts'),
    projection.replace('status=unavailable', 'status=201'),
    projection.replace('stage=disable-planning-model method=unavailable', 'method=unavailable stage=disable-planning-model'),
    `${projection} secret=never-print`,
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
})

test('revision-outline-session stages preserve safe nested failures and close unknown failures', async () => {
  const source = workspace(SPEC)
  const stages = [
    'create-project', 'phase2-preparation', 'disable-planning-model', 'manual-planning', 'verify-r1',
    'planning-revision', 'history-r1', 'outline-before-confirm', 'outline-confirm', 'writer-session',
  ]
  const projectionStart = source.indexOf('function normalizedRuntimeApiPath')
  const projectionEnd = source.indexOf('\nasync function finishRuntime', projectionStart)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(projectionStart, projectionEnd)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const path = `/api/projects/${id}/seeds`
  const auditError = new Error('Runtime write count did not match allowlist entry 0')
  const evidence = { responses: [{ method: 'POST', url: `http://127.0.0.1:43123${path}`, status: 200 }] }
  const writes = [{ method: 'POST', path, statuses: [200], count: 2 }]
  const projection = 'category=behavior leaf=revision-outline-session stage=verify-r1 method=unavailable path=unavailable status=unavailable'
  for (const stage of stages) {
    const projected = projection.replace('stage=verify-r1', `stage=${stage}`)
    assert.equal(project(new Error(projected), auditError, 'exact-writes', evidence, writes), projected)
  }

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'revision-outline-session'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: projection }] }] }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(projection) && !error.message.includes('never-print'),
  )
  for (const malformed of [
    projection.replace('stage=verify-r1', 'stage=other'),
    projection.replace('method=unavailable', 'method=POST'),
    projection.replace('path=unavailable', 'path=/api/projects/:id/never-print'),
    projection.replace('status=unavailable', 'status=200'),
    `${projection} secret=never-print`,
  ]) {
    const projected = project(new Error(malformed), auditError, 'exact-writes', evidence, writes)
    assert.notEqual(projected, malformed)
    assert.doesNotMatch(projected, /other|never-print/u)
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }

  const wrapperStart = source.indexOf('async function runScenarioStage')
  const wrapperEnd = source.indexOf('\ntest(\'foundation-manual-r1', wrapperStart)
  const wrapper = source.slice(wrapperStart, wrapperEnd)
  assert.match(wrapper, /if \(strictSafeBehaviorProjection\(error\)\) throw error/u)
  assert.match(wrapper, /category=behavior leaf=\$\{kind\} stage=\$\{stage\} method=unavailable path=unavailable status=unavailable/u)
  const strictStart = source.indexOf('function strictSafeBehaviorProjection')
  const strictEnd = source.indexOf('\nfunction projectPhase3FailureMessage', strictStart)
  const { runScenarioStage } = new Function(
    `${source.slice(strictStart, strictEnd)}${wrapper}; return { runScenarioStage }`,
  )()
  const nestedSafe = 'category=behavior leaf=outline-flow stage=fill-goal method=unavailable path=unavailable status=unavailable'
  await assert.rejects(
    runScenarioStage('revision-outline-session', 'outline-before-confirm', async () => { throw new Error(nestedSafe) }),
    error => error?.message === nestedSafe,
  )
  const revisionNestedSafe = 'category=behavior leaf=planning-revision-flow stage=save-click method=unavailable path=unavailable status=unavailable'
  await assert.rejects(
    runScenarioStage('revision-outline-session', 'planning-revision', async () => { throw new Error(revisionNestedSafe) }),
    error => error?.message === revisionNestedSafe,
  )
  await assert.rejects(
    runScenarioStage('revision-outline-session', 'verify-r1', async () => { throw new Error('never-print') }),
    error => error?.message === 'category=behavior leaf=revision-outline-session stage=verify-r1 method=unavailable path=unavailable status=unavailable',
  )
  const scenarioStart = source.indexOf("test('revision-outline-session")
  const scenarioEnd = source.indexOf("\ntest('unused-outline-supersession", scenarioStart)
  const scenarioSource = source.slice(scenarioStart, scenarioEnd)
  let previous = -1
  for (const stage of stages) {
    const index = scenarioSource.indexOf(`runScenarioStage('revision-outline-session', '${stage}'`, previous)
    assert.ok(index > previous, `revision scenario stage order must include ${stage}`)
    previous = index
  }
})

test('planning revision flow allows only its closed stages through spec and runner diagnostics', async () => {
  const source = workspace(SPEC)
  const strictStart = source.indexOf('function strictSafeBehaviorProjection')
  const strictEnd = source.indexOf('\nfunction projectPhase3FailureMessage', strictStart)
  const strictSafeBehaviorProjection = new Function(
    `${source.slice(strictStart, strictEnd)}; return strictSafeBehaviorProjection`,
  )()
  const stages = [
    'navigation', 'create-wait-registration', 'create-click', 'create-response', 'volume-card', 'fill-title',
    'save-wait-registration', 'save-click', 'save-response', 'preview-click', 'confirm-wait-registration',
    'confirm-click', 'confirm-response', 'final-settlement',
  ]
  const projection = 'category=behavior leaf=planning-revision-flow stage=fill-title method=unavailable path=unavailable status=unavailable'
  for (const stage of stages) {
    const expected = projection.replace('stage=fill-title', `stage=${stage}`)
    assert.equal(strictSafeBehaviorProjection(new Error(expected)), expected)
  }

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'revision-outline-session'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: projection }] }] }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(projection) && !error.message.includes('never-print'),
  )
  for (const malformed of [
    projection.replace('stage=fill-title', 'stage=unknown'),
    projection.replace('method=unavailable', 'method=POST'),
    projection.replace('path=unavailable', 'path=/api/projects/:id/never-print'),
    projection.replace('status=unavailable', 'status=200'),
    `${projection} secret=never-print`,
  ]) {
    assert.equal(strictSafeBehaviorProjection(new Error(malformed)), null)
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
})

test('remaining Phase 3 scenarios expose only their closed ordered stages', async () => {
  const source = workspace(SPEC)
  const contracts = [
    ['unused-outline-supersession', [
      'create-project', 'phase2-preparation', 'disable-planning-model', 'manual-planning',
      'outline', 'planning-revision', 'supersession-navigation', 'history-open',
      'history-dialog', 'history-status', 'history-close', 'readonly-note',
      'save-absent', 'final-settlement',
    ]],
    ['pinned-session', ['create-project', 'phase2-preparation', 'disable-planning-model', 'manual-planning', 'outline', 'writer-before', 'planning-revision', 'writer-after']],
    ['baseline-lock', ['create-project', 'phase2-preparation', 'seed-lock-view', 'contract-lock-view', 'bible-lock-view', 'stale-bible-confirm', 'stale-bible-reload', 'final-baseline-reload']],
    ['archived-navigation', ['create-project', 'phase2-preparation', 'disable-planning-model', 'manual-planning', 'outline', 'archive', 'volumes-readonly', 'plots-navigation', 'browser-history', 'blocks-readonly']],
  ]
  const strictStart = source.indexOf('function strictSafeBehaviorProjection')
  const strictEnd = source.indexOf('\nfunction projectPhase3FailureMessage', strictStart)
  const wrapperStart = source.indexOf('async function runScenarioStage')
  const wrapperEnd = source.indexOf("\ntest('foundation-manual-r1", wrapperStart)
  const { strictSafeBehaviorProjection, runScenarioStage } = new Function(
    `${source.slice(strictStart, strictEnd)}${source.slice(wrapperStart, wrapperEnd)}; return { strictSafeBehaviorProjection, runScenarioStage }`,
  )()
  const runner = await import('../../frontend/e2e/run-phase3.mjs')

  for (const [scenario, stages] of contracts) {
    const scenarioStart = source.indexOf(`test('${scenario}`)
    const scenarioEnd = source.indexOf("\ntest('", scenarioStart + 1)
    const scenarioSource = source.slice(scenarioStart, scenarioEnd)
    let previous = -1
    for (const stage of stages) {
      const index = scenarioSource.indexOf(`runScenarioStage('${scenario}', '${stage}'`, previous)
      assert.ok(index > previous, `${scenario} must wrap ${stage} in order`)
      previous = index
    }

    const projection = `category=behavior leaf=${scenario} stage=${stages[0]} method=unavailable path=unavailable status=unavailable`
    for (const stage of stages) {
      const expected = projection.replace(`stage=${stages[0]}`, `stage=${stage}`)
      assert.equal(strictSafeBehaviorProjection(new Error(expected)), expected)
    }
    await assert.rejects(
      runScenarioStage(scenario, stages[0], async () => { throw new Error(projection) }),
      error => error?.message === projection,
    )

    const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: projection }] }] }])])
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes(projection) && !error.message.includes('never-print'),
    )
    for (const malformed of [
      projection.replace(`stage=${stages[0]}`, 'stage=unknown'),
      projection.replace('method=unavailable', 'method=POST'),
      projection.replace('path=unavailable', 'path=/api/projects/:id/never-print'),
      projection.replace('status=unavailable', 'status=200'),
      `${projection} secret=never-print`,
    ]) {
      assert.equal(strictSafeBehaviorProjection(new Error(malformed)), null)
      report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
      assert.throws(
        () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
        error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
      )
    }
  }
})

test('foundation wraps its five top-level stages in order', () => {
  const source = workspace(SPEC)
  const start = source.indexOf("test('foundation-manual-r1")
  const end = source.indexOf("\ntest('revision-outline-session", start)
  const foundation = source.slice(start, end)
  const calls = [
    ["'create-project'", 'createProjectUi(page, runtime)'],
    ["'phase2-preparation'", 'completePhase2PreparationUi(page, runtime)'],
    ["'disable-planning-model'", 'disablePlanningModelUi(page, runtime)'],
    ["'manual-planning'", "createManualPlanning(page, '手工规划 R1', runtime)"],
    ["'post-planning'", 'await settleNavigationBoundary(page, runtime)'],
  ]
  let previous = -1
  for (const [stage, action] of calls) {
    const stageIndex = foundation.indexOf(`runFoundationStage(${stage}`, previous)
    const actionIndex = foundation.indexOf(action, stageIndex)
    assert.ok(stageIndex > previous && actionIndex > stageIndex, `${stage} must wrap its top-level action`)
    previous = actionIndex
  }
  const postPlanningStart = foundation.indexOf("runFoundationStage('post-planning'")
  const postPlanning = foundation.slice(postPlanningStart)
  for (const fragment of [
    "const planningVersions = page.getByLabel('规划版本')",
    'await expect(planningVersions).toHaveCount(1)',
    'await expect(planningVersions).toBeVisible()',
    "const confirmedRevision = planningVersions.getByText('R1', { exact: true })",
    'await expect(confirmedRevision).toHaveCount(1)',
    'await expect(confirmedRevision).toBeVisible()',
    "const actualProgress = page.getByRole('complementary', { name: '正文已发生', exact: true })",
    'await expect(actualProgress).toHaveCount(1)',
    'await expect(actualProgress).toBeVisible()',
    "const canonZero = actualProgress.getByText('尚无已定稿事实', { exact: true })",
    'await expect(canonZero).toHaveCount(1)',
    'await expect(canonZero).toBeVisible()',
  ]) assert.ok(postPlanning.includes(fragment), `post-planning must scope exact UI evidence: ${fragment}`)
  assert.doesNotMatch(postPlanning, /page\.getByText\('R1', \{ exact: false \}\)/u)
  assert.match(source, /async function runFoundationStage\(stage, action\) \{\s*try \{ return await action\(\) \} catch \(error\) \{/u)
  assert.match(source, /category=behavior leaf=foundation-stage stage=\$\{stage\} method=unavailable path=unavailable status=unavailable/u)
})

test('foundation stages preserve already-safe planning diagnostics while closing raw errors', async () => {
  const source = workspace(SPEC)
  const strictStart = source.indexOf('function strictSafeBehaviorProjection')
  const strictEnd = source.indexOf('\nfunction projectPhase3FailureMessage', strictStart)
  const stageStart = source.indexOf('async function runFoundationStage')
  const stageEnd = source.indexOf("\ntest('foundation-manual-r1", stageStart)
  const { runFoundationStage } = new Function(
    `${source.slice(strictStart, strictEnd)}${source.slice(stageStart, stageEnd)}; return { runFoundationStage }`,
  )()
  const safe = 'category=behavior leaf=planning-create-flow stage=response-wait method=POST path=/api/projects/:id/planning/drafts status=unavailable'
  await assert.rejects(
    runFoundationStage('manual-planning', async () => { throw new Error(safe) }),
    error => error?.message === safe,
  )
  await assert.rejects(
    runFoundationStage('disable-planning-model', async () => { throw new Error('never-print') }),
    error => error?.message === 'category=behavior leaf=foundation-stage stage=disable-planning-model method=unavailable path=unavailable status=unavailable',
  )
})

test('Task5 listener checkpoints retain observer identities and emit only a fixed detached projection', async () => {
  const source = workspace(SPEC)
  const runStart = source.indexOf('async function runAudited')
  const runEnd = source.indexOf('\nasync function completePhase2PreparationUi', runStart)
  const runAudited = source.slice(runStart, runEnd)
  const observer = runAudited.indexOf('observeRuntime(page, { allowedOrigins })')
  assert.ok(observer >= 0, 'runtime observation must remain shared by every audited flow')
  assert.doesNotMatch(runAudited, /listenerRefs|\.at\(-1\)|Object\.assign\(Object\.create\(observedRuntime\)/u)
  assert.match(source, /function assertRuntimeListenersAttached\(runtime, stage\) \{\s*if \(runtime\.listenersAttached\(\)\) return/u)
  const modelStart = source.indexOf('async function disablePlanningModelUi')
  const modelEnd = source.indexOf('\nasync function createManualPlanning', modelStart)
  const model = source.slice(modelStart, modelEnd)
  assert.ok(model.indexOf('await settleNavigationBoundary(page, runtime)') < model.indexOf("assertRuntimeListenersAttached(runtime, 'after-model-settings')"))
  const planningStart = source.indexOf('async function createManualPlanning')
  const planningEnd = source.indexOf('\nasync function createOutline', planningStart)
  const planning = source.slice(planningStart, planningEnd)
  const navigationStage = planning.indexOf("let stage = 'navigation'")
  const goto = planning.indexOf('await page.goto(volumes())')
  const listenerStage = planning.indexOf("stage = 'listener-check'")
  const listenerCheck = planning.indexOf("assertRuntimeListenersAttached(runtime, 'before-planning-create')")
  const registrationStage = planning.indexOf("stage = 'wait-registration'")
  const waiter = planning.indexOf("page.waitForResponse(response => isResponse(response, 'POST', planningDrafts()))")
  const buttonStage = planning.indexOf("stage = 'button-click'")
  const buttonClick = planning.indexOf("page.getByRole('button', { name: '建立空白规划工作稿' }).click()")
  const responseWaitStage = planning.indexOf("stage = 'response-wait'")
  const created = planning.indexOf('return await createdResponse')
  const catchIndex = planning.indexOf('} catch (error)')
  assert.ok(navigationStage >= 0 && goto > navigationStage && listenerStage > goto && listenerCheck > listenerStage && registrationStage > listenerCheck && waiter > registrationStage && buttonStage > waiter && buttonClick > buttonStage && responseWaitStage > buttonClick && created > responseWaitStage && catchIndex > created)
  const createdStatus = planning.indexOf('const createdStatus = created.status()')
  const createdStatusFailure = planning.indexOf('if (createdStatus !== 201)')
  const createdStatusProjection = planning.indexOf('category=behavior leaf=planning-create-status method=POST path=/api/projects/:id/planning/drafts status=${createdStatus}')
  const requestStage = planning.indexOf('const requestStage = runtime.observationStage(created.request())')
  const observerResponseStage = planning.indexOf('const responseStage = runtime.observationStage(created)')
  const progressThrow = planning.indexOf('category=behavior leaf=observer-progress method=POST path=/api/projects/:id/planning/drafts status=201 requestStage=${requestStage} responseStage=${responseStage}')
  const requestMatch = planning.indexOf("const requestMatch = Number(runtime.requestObservationMatches(created.request(), 'POST', planningDrafts()))")
  const responseMatch = planning.indexOf("const responseMatch = Number(runtime.responseObservationMatches(created, 'POST', planningDrafts(), 201))")
  const metadataThrow = planning.indexOf('category=behavior leaf=observer-metadata method=POST path=/api/projects/:id/planning/drafts status=201 requestMatch=${requestMatch} responseMatch=${responseMatch}')
  assert.ok(createdStatus > catchIndex && createdStatusFailure > createdStatus && createdStatusProjection > createdStatusFailure && requestStage > createdStatusProjection && observerResponseStage > requestStage && progressThrow > observerResponseStage)
  assert.ok(progressThrow < requestMatch && responseMatch > requestMatch && metadataThrow > responseMatch && metadataThrow < planning.indexOf("assertRuntimeListenersAttached(runtime, 'after-planning-create')"))
  const afterPlanningCreate = planning.indexOf("assertRuntimeListenersAttached(runtime, 'after-planning-create')")
  const manualStages = [
    ["let stage = 'ai-disabled'", "await expect(page.getByRole('button', { name: 'AI 生成当前规划工作稿' })).toBeDisabled()"],
    ["stage = 'add-volume'", "page.getByRole('button', { name: '新增分卷' }).click()"],
    ["stage = 'fill-volume'", 'fillManualVolume(page, title)'],
    ["stage = 'settle-volume'", 'await settleNavigationBoundary(page, runtime)'],
    ["stage = 'open-plots'", "page.getByRole('link', { name: '情节线', exact: true }).click()"],
    ["stage = 'add-plot'", "page.getByRole('button', { name: '新增情节线' }).click()"],
    ["stage = 'fill-plot'", 'fillManualPlot(page)'],
    ["stage = 'settle-plot'", 'await settleNavigationBoundary(page, runtime)'],
    ["stage = 'open-blocks'", "page.getByRole('link', { name: '故事块', exact: true }).click()"],
    ["stage = 'add-block'", "page.getByRole('button', { name: '新增故事块' }).click()"],
    ["stage = 'fill-block'", 'fillManualStoryBlock(page)'],
    ["stage = 'add-stage'", "block.getByRole('button', { name: '新增阶段' }).click()"],
    ["stage = 'fill-stage'", "stageCard.getByLabel('阶段标题', { exact: true }).fill('寻找缺口')"],
    ["stage = 'add-scene-task'", "stageCard.getByRole('button', { name: '新增场景任务' }).click()"],
    ["stage = 'fill-scene-task'", "task.getByLabel('场景任务', { exact: true }).fill('观察换岗。')"],
    ["stage = 'activate-block'", "block.getByRole('button', { name: '设为当前活动块', exact: true })"],
    ["stage = 'save-wait-registration'", "page.waitForResponse(response => isResponse(response, 'PUT', draftPath(planningDrafts())))"],
    ["stage = 'save-click'", "page.getByRole('button', { name: '保存工作稿' }).click()"],
    ["stage = 'save-response'", 'expect((await savedResponse).status()).toBe(200)'],
    ["stage = 'preview-click'", "page.getByRole('button', { name: '预览并确认' }).click()"],
    ["stage = 'confirm-wait-registration'", "page.waitForResponse(response => isResponse(response, 'POST', confirmPath(planningDrafts())))"],
    ["stage = 'confirm-click'", "page.getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()"],
    ["stage = 'confirm-response'", 'expect((await confirmedResponse).status()).toBe(201)'],
    ["stage = 'final-settlement'", 'await settleNavigationBoundary(page, runtime)'],
  ]
  let manualPrevious = afterPlanningCreate
  for (const [stage, operation] of manualStages) {
    const stageIndex = planning.indexOf(stage, manualPrevious)
    const operationIndex = planning.indexOf(operation, stageIndex)
    assert.ok(stageIndex > manualPrevious && operationIndex > stageIndex, `${stage} must precede its operation`)
    manualPrevious = operationIndex
  }
  const manualCatch = planning.indexOf('} catch (error)', manualPrevious)
  const manualProjection = planning.indexOf('category=behavior leaf=planning-manual-flow stage=${stage} method=unavailable path=unavailable status=unavailable')
  assert.ok(manualCatch > manualPrevious && manualProjection > manualCatch)
  const projectionStart = source.indexOf('function normalizedRuntimeApiPath')
  const projectionEnd = source.indexOf('\nasync function finishRuntime', projectionStart)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(projectionStart, projectionEnd)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const projection = 'category=behavior leaf=runtime-listener stage=after-planning-create state=detached'
  assert.equal(project(new Error(projection), null), projection)
  const progressProjection = 'category=behavior leaf=observer-progress method=POST path=/api/projects/:id/planning/drafts status=201 requestStage=scheduled responseStage=metadata'
  assert.equal(project(new Error(progressProjection), null), progressProjection)
  const metadataProjection = 'category=behavior leaf=observer-metadata method=POST path=/api/projects/:id/planning/drafts status=201 requestMatch=1 responseMatch=0'
  assert.equal(project(new Error(metadataProjection), null), metadataProjection)
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'failed', errors: [{ message: projection }] }] }])])
  let failure
  try { runner.phase3BrowserFailure(report, scenario, ['never-print']) } catch (error) { failure = error }
  assert.match(failure?.message || '', new RegExp(projection, 'u'))
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = progressProjection
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(progressProjection) && !error.message.includes('never-print'),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = metadataProjection
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes(metadataProjection) && !error.message.includes('never-print'),
  )
  for (const malformed of [
    projection.replace('after-planning-create', 'other'),
    `${projection} secret=never-print`,
    projection.replace('state=detached', 'state=attached'),
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
  for (const malformed of [
    progressProjection.replace('method=POST', 'method=PUT'),
    progressProjection.replace('path=/api/projects/:id/planning/drafts', 'path=/api/projects/:id/never-print'),
    progressProjection.replace('status=201', 'status=200'),
    progressProjection.replace('requestStage=scheduled', 'requestStage=other'),
    progressProjection.replace('requestStage=scheduled responseStage=metadata', 'responseStage=metadata requestStage=scheduled'),
    `${progressProjection} secret=never-print`,
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
  for (const malformed of [
    metadataProjection.replace('method=POST', 'method=PUT'),
    metadataProjection.replace('path=/api/projects/:id/planning/drafts', 'path=/api/projects/:id/never-print'),
    metadataProjection.replace('status=201', 'status=200'),
    metadataProjection.replace('requestMatch=1 responseMatch=0', 'responseMatch=0 requestMatch=1'),
    `${metadataProjection} stage=scheduled secret=never-print`,
  ]) {
    report.suites[0].specs[0].tests[0].results[0].errors[0].message = malformed
    assert.throws(
      () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
      error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
    )
  }
})

test('manual Planning creation builds one complete user-visible volume, plot, block, stage, and scene task', () => {
  const source = workspace(SPEC)
  const helpersStart = source.indexOf('async function fillManualVolume')
  const manualStart = source.indexOf('async function createManualPlanning')
  const manualEnd = source.indexOf('\nasync function createOutline', manualStart)
  assert.ok(helpersStart >= 0 && manualStart > helpersStart && manualEnd > manualStart)
  const helpers = source.slice(helpersStart, manualStart)
  const manual = source.slice(manualStart, manualEnd)
  for (const fragment of [
    "const volumeCards = page.locator('.planning-editor .manuscript-card')",
    'await expect(volumeCards).toHaveCount(1)',
    "getByLabel('卷名', { exact: true }).fill(title)",
    "getByLabel('核心变化', { exact: true }).fill('主角从逃亡者变成能保护同伴的人。')",
    "getByLabel('主要压力', { exact: true }).fill('旧敌封锁北境商路。')",
    "getByLabel('群像焦点（每行一项）', { exact: true }).fill('沈砚\\n陆青禾')",
    "getByLabel('本卷禁区（每行一项）', { exact: true }).fill('不提前揭露幕后人')",
    "const plotCards = page.locator('.planning-editor .manuscript-card')",
    'await expect(plotCards).toHaveCount(1)',
    "getByLabel('情节线名称', { exact: true }).fill('残卷来历')",
    "getByLabel('故事问题', { exact: true }).fill('残卷为何只在沈砚手中显字？')",
    "getByLabel('未来走向', { exact: true }).fill('线索从边城指向京城旧档。')",
    "getByLabel('预期回报', { exact: true }).fill('揭开第一层来历。')",
    "getByLabel('相关人物（每行一项）', { exact: true }).fill('沈砚\\n陆青禾')",
    "const block = page.locator('.story-block-card')",
    'await expect(block).toHaveCount(1)',
    "getByLabel('故事块标题', { exact: true }).fill('夜渡封锁线')",
    "getByLabel('进入情境', { exact: true }).fill('二人被困在废弃驿站。')",
    "getByLabel('故事块目标', { exact: true }).fill('穿过封锁线。')",
    "getByLabel('主要压力', { exact: true }).fill('追兵压缩路线。')",
    "getByLabel('预期变化', { exact: true }).fill('二人建立信任。')",
    "getByLabel('开放问题（每行一项）', { exact: true }).fill('内应是谁')",
    "getByLabel('涉及人物（每行一项）', { exact: true }).fill('沈砚\\n陆青禾')",
    "block.locator('.block-fields select')",
    "getByRole('checkbox')",
    "stageCard.getByLabel('阶段标题', { exact: true }).fill('寻找缺口')",
    "stageCard.getByLabel('阶段目的', { exact: true }).fill('确认封锁薄弱处。')",
    "stageCard.getByLabel('戏剧问题', { exact: true }).fill('能否在暴露前找到缺口？')",
    "task.getByLabel('场景任务', { exact: true }).fill('观察换岗。')",
    "task.getByLabel('完成证据', { exact: true }).fill('取得换岗间隔。')",
  ]) assert.ok(`${helpers}\n${manual}`.includes(fragment), `missing complete manual-planning interaction: ${fragment}`)
  assert.ok(manual.indexOf("stage = 'add-volume'") < manual.indexOf('fillManualVolume(page, title)'))
  assert.ok(manual.indexOf("stage = 'add-plot'") < manual.indexOf('fillManualPlot(page)'))
  assert.ok(manual.indexOf("stage = 'add-block'") < manual.indexOf('fillManualStoryBlock(page)'))
  assert.match(manual, /getByRole\('link', \{ name: '情节线', exact: true \}\)\.click\(\)/u)
  assert.match(manual, /getByRole\('button', \{ name: '新增情节线' \}\)\.click\(\)/u)
  assert.doesNotMatch(manual, /剧情线/u)
  assert.doesNotMatch(`${helpers}\n${manual}`, /getByLabel\('卷名', \{ exact: true \}\)\.first\(\)/u)
})

test('shared Phase 3 audit options admit the linked first contract-draft 404 and explicit stale Bible 409 only', async () => {
  const source = workspace(SPEC)
  const start = source.indexOf('const CONTRACT_DRAFT_404_MESSAGE')
  const end = source.indexOf('\nfunction phase2PreparationWrites', start)
  assert.notEqual(start, -1, 'missing shared contract-draft audit options')
  const auditOptions = new Function(
    'projectId', 'options',
    `${source.slice(start, end)}; return phase3RuntimeAuditOptions(projectId, options)`,
  )('01234567-89ab-cdef-0123-456789abcdef', undefined)
  const contractDraftPath = '/api/projects/01234567-89ab-cdef-0123-456789abcdef/contract-draft'
  const consoleMessage = 'error: Failed to load resource: the server responded with a status of 404 (Not Found)'
  assert.deepEqual(auditOptions, {
    responseFailureAllowlist: [{ status: 404, method: 'GET', pathname: contractDraftPath, count: 1 }],
    consoleErrorAllowlist: [{
      message: consoleMessage,
      count: 1,
      linkedResponseFailure: { status: 404, method: 'GET', pathname: contractDraftPath },
    }],
  })
  const { assertRuntimeEvidenceHealthy } = await import('../../frontend/e2e/runtime-observer.mjs')
  const validEvidence = {
    responseFailures: [`404 GET http://127.0.0.1:5173${contractDraftPath}`],
    consoleErrors: [consoleMessage], pageErrors: [], requestFailures: [], apiResponses: [], requests: [],
  }
  assert.doesNotThrow(() => assertRuntimeEvidenceHealthy(validEvidence, auditOptions))
  const staleBiblePath = '/api/projects/01234567-89ab-cdef-0123-456789abcdef/bible/confirm'
  const staleAuditOptions = new Function(
    'projectId', 'options',
    `${source.slice(start, end)}; return phase3RuntimeAuditOptions(projectId, options)`,
  )('01234567-89ab-cdef-0123-456789abcdef', { allowStaleBibleConfirm409: true })
  assert.deepEqual(staleAuditOptions.responseFailureAllowlist, [
    { status: 404, method: 'GET', pathname: contractDraftPath, count: 1 },
    { status: 409, method: 'POST', pathname: staleBiblePath, count: 1 },
  ])
  assert.doesNotThrow(() => assertRuntimeEvidenceHealthy({
    ...validEvidence,
    responseFailures: [...validEvidence.responseFailures, `409 POST http://127.0.0.1:5173${staleBiblePath}`],
  }, staleAuditOptions))
  const baselineAuditOptions = new Function(
    'projectId', 'options',
    `${source.slice(start, end)}; return phase3RuntimeAuditOptions(projectId, options)`,
  )('01234567-89ab-cdef-0123-456789abcdef', {
    allowStaleBibleConfirm409: true,
    contractDraft404Count: 3,
  })
  assert.deepEqual(baselineAuditOptions.responseFailureAllowlist, [
    { status: 404, method: 'GET', pathname: contractDraftPath, count: 3 },
    { status: 409, method: 'POST', pathname: staleBiblePath, count: 1 },
  ])
  assert.deepEqual(baselineAuditOptions.consoleErrorAllowlist, [{
    message: consoleMessage,
    count: 3,
    linkedResponseFailure: { status: 404, method: 'GET', pathname: contractDraftPath },
  }])
  assert.doesNotThrow(() => assertRuntimeEvidenceHealthy({
    ...validEvidence,
    responseFailures: [
      ...validEvidence.responseFailures,
      ...validEvidence.responseFailures,
      ...validEvidence.responseFailures,
      `409 POST http://127.0.0.1:5173${staleBiblePath}`,
    ],
    consoleErrors: [consoleMessage, consoleMessage, consoleMessage],
  }, baselineAuditOptions))
  for (const contractDraft404Count of [0, -1, 1.5, 2, 4, '3', Number.NaN]) {
    assert.throws(() => new Function(
      'projectId', 'options',
      `${source.slice(start, end)}; return phase3RuntimeAuditOptions(projectId, options)`,
    )('01234567-89ab-cdef-0123-456789abcdef', { contractDraft404Count }))
  }
  for (const evidence of [
    { ...validEvidence, responseFailures: [`500 GET http://127.0.0.1:5173${contractDraftPath}`] },
    { ...validEvidence, responseFailures: [`404 GET http://127.0.0.1:5173/api/projects/other/contract-draft`] },
    { ...validEvidence, consoleErrors: ['error: arbitrary never-print'] },
    { ...validEvidence, responseFailures: [...validEvidence.responseFailures, ...validEvidence.responseFailures] },
  ]) assert.throws(() => assertRuntimeEvidenceHealthy(evidence, auditOptions))
  assert.match(source, /assertRuntimeEvidenceHealthy\(evidence, resolvedRuntimeAuditOptions \|\| phase3RuntimeAuditOptions\(PROJECT_ID\)\)/u)
})

test('baseline runtime audit options resolve only after its UI body establishes the current project', async () => {
  const source = workspace(SPEC)
  const runStart = source.indexOf('async function runAudited')
  const runEnd = source.indexOf('\nasync function completePhase2PreparationUi', runStart)
  assert.match(source, /runtimeAuditOptions: \(\) => phase3RuntimeAuditOptions\(PROJECT_ID, \{ allowStaleBibleConfirm409: true, contractDraft404Count: 3 \}\)/u)
  const runAudited = new Function(
    'observeRuntime', 'finishRuntime', 'allowedOrigins',
    `${source.slice(runStart, runEnd).replace('bodyError: unknown', 'bodyError')}; return runAudited`,
  )(
    () => ({}),
    async (_runtime, _bodyError, _writes, options) => {
      assert.equal(bodyCompleted, true)
      assert.equal(typeof options, 'function')
      assert.deepEqual(options(), { projectId: 'current-project' })
    },
    [],
  )
  const injectedPage = {
    context() {
      return {
        pages: () => [injectedPage],
        on() {},
      }
    },
  }
  let bodyCompleted = false
  await runAudited(injectedPage, [], async () => { bodyCompleted = true }, {
    runtimeAuditOptions: () => ({ projectId: 'current-project' }),
  })
  const finishStart = source.indexOf('async function finishRuntime')
  const finishEnd = source.indexOf('\nfunction assertRuntimeListenersAttached', finishStart)
  const finish = source.slice(finishStart, finishEnd)
  assert.match(finish, /typeof runtimeAuditOptions === 'function'\s*\?\s*runtimeAuditOptions\(\)\s*:\s*runtimeAuditOptions/u)
  assert.match(finish, /assertRuntimeEvidenceHealthy\(evidence, resolvedRuntimeAuditOptions \|\| phase3RuntimeAuditOptions\(PROJECT_ID\)\)/u)
})

test('runtime-health failures emit a closed evidence summary without runtime contents', async () => {
  const source = workspace(SPEC)
  const start = source.indexOf('function normalizedRuntimeApiPath')
  const end = source.indexOf('\nasync function finishRuntime', start)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(start, end)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const evidence = {
    responseFailures: ['500 GET http://127.0.0.1:43123/api/projects/01234567-89ab-cdef-0123-456789abcdef/contract-draft?authorization=never-print'],
    consoleErrors: ['error: never-print'],
    pageErrors: ['page never-print'],
    requestFailures: ['POST http://127.0.0.1:43123/api/projects/01234567-89ab-cdef-0123-456789abcdef/seeds authorization=never-print'],
    apiResponses: [{
      url: 'http://127.0.0.1:43123/api/projects/01234567-89ab-cdef-0123-456789abcdef/contract-draft?authorization=never-print',
      method: 'GET', status: 500, headersReadError: 'never-print', bodyReadError: 'never-print',
    }],
    requests: [{
      url: 'http://127.0.0.1:43123/api/projects/01234567-89ab-cdef-0123-456789abcdef/seeds',
      headersReadError: 'never-print', bodyReadError: 'never-print',
    }],
    networkAccess: { forbiddenRequestCount: 2, forbiddenResponseCount: 3 },
  }
  const projection = project(null, new Error('health never-print'), 'runtime-health', evidence)
  assert.equal(
    projection,
    'category=audit leaf=runtime-health-summary responseFailureCount=1 consoleErrorCount=1 pageErrorCount=1 requestFailureCount=1 apiReadErrorCount=2 requestReadErrorCount=2 forbiddenRequestCount=2 forbiddenResponseCount=3 responseMethod=GET responsePath=/api/projects/:id/contract-draft responseStatus=500 requestMethod=POST requestPath=/api/projects/:id/seeds requestStatus=unavailable readMethod=GET readPath=/api/projects/:id/contract-draft readStatus=500 responseInventory=GET:/api/projects/:id/contract-draft:500:1 unavailableCount=0 inventoryOmittedCount=0 consoleKnownLinkedCount=0 consoleOtherCount=1',
  )
  assert.doesNotMatch(projection, /never-print|authorization|127\.0\.0\.1|body|header|url/u)
  assert.equal(
    project(null, new Error('Unmatched runtime write: POST /api/projects/01234567-89ab-cdef-0123-456789abcdef/seeds never-print'), 'runtime-health', evidence),
    'category=audit leaf=write-unmatched method=POST path=/api/projects/:id/seeds status=unmatched count=unexpected',
  )
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = playwrightReport([playwrightSpec(scenario, [{
    results: [{ status: 'failed', errors: [{ message: projection }] }],
  }])])
  let failure
  try { runner.phase3BrowserFailure(report, scenario, ['never-print']) } catch (error) { failure = error }
  assert.match(failure?.message || '', new RegExp(`scenario=${scenario} ${projection}`, 'u'))
  assert.match(runner.formatPhase3CommandFailure(failure, { scenario }), new RegExp(projection, 'u'))
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = `${projection} never-print`
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = projection.replace('responseMethod=GET', 'responseMethod=TRACE')
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = projection.replace('readMethod=GET', 'readMethod=TRACE')
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = projection.replace('readPath=/api/projects/:id/contract-draft', 'readPath=/api/projects/:id/contract-draft?authorization=never-print')
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
})

test('runtime-health inventory emits only bounded safe response groups and fixed console linkage counts', async () => {
  const source = workspace(SPEC)
  const start = source.indexOf('function normalizedRuntimeApiPath')
  const end = source.indexOf('\nasync function finishRuntime', start)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(start, end)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const id = '01234567-89ab-cdef-0123-456789abcdef'
  const linkedConsoleSentinel = 'console-sentinel-never-print'
  const otherConsoleSentinel = 'other-console-sentinel-never-print'
  const safePath = `/api/projects/${id}/contract-draft`
  const evidence = {
    responseFailures: [
      `500 GET https://127.0.0.1:43123${safePath}?query=body-sentinel-never-print`,
      `500 TRACE http://127.0.0.1:43123${safePath}?query=body-sentinel-never-print`,
      `500 GET https://untrusted-host.invalid${safePath}?query=body-sentinel-never-print`,
      'malformed-response-sentinel-never-print',
    ],
    consoleErrors: [linkedConsoleSentinel, otherConsoleSentinel],
    pageErrors: [], requestFailures: [], apiResponses: [], requests: [],
    networkAccess: { forbiddenRequestCount: 0, forbiddenResponseCount: 0 },
  }
  const options = {
    responseFailureAllowlist: [{ status: 500, method: 'GET', pathname: `/api/projects/${id}/contract-draft`, count: 1 }],
    consoleErrorAllowlist: [{
      message: linkedConsoleSentinel,
      count: 1,
      linkedResponseFailure: { status: 500, method: 'GET', pathname: `/api/projects/${id}/contract-draft` },
    }],
  }
  const projection = project(null, new Error('health sentinel'), 'runtime-health', evidence, undefined, options)
  assert.match(
    projection,
    /responseInventory=GET:\/api\/projects\/:id\/contract-draft:500:1 unavailableCount=3 inventoryOmittedCount=0 consoleKnownLinkedCount=1 consoleOtherCount=1$/u,
  )
  assert.doesNotMatch(projection, /sentinel|body|query|127\.0\.0\.1|untrusted-host|https?:/u)

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const report = playwrightReport([playwrightSpec(scenario, [{
    results: [{ status: 'failed', errors: [{ message: projection }] }],
  }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, [linkedConsoleSentinel]),
    error => error?.message.includes(`scenario=${scenario} ${projection}`),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = projection.replace(
    'responseInventory=GET:/api/projects/:id/contract-draft:500:1',
    'responseInventory=GET:https://untrusted-host.invalid/api/projects/:id/contract-draft:500:1',
  )
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, [linkedConsoleSentinel]),
    error => error?.message.includes('leaf=report-message-unrecognized')
      && !error.message.includes(linkedConsoleSentinel)
      && !error.message.includes('untrusted-host'),
  )

  const boundedProjection = project(null, new Error('health sentinel'), 'runtime-health', {
    ...evidence,
    responseFailures: Array.from({ length: 9 }, (_, index) => (
      `500 GET http://127.0.0.1:43123/api/projects/${id}/inventory-${index}`
    )),
    consoleErrors: [],
  })
  const boundedInventory = /responseInventory=([^ ]+) unavailableCount=0 inventoryOmittedCount=1/u.exec(boundedProjection)?.[1]
  assert.equal(boundedInventory?.split('|').length, 8)
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = boundedProjection
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, []),
    error => error?.message.includes(`scenario=${scenario} ${boundedProjection}`),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = boundedProjection.replace(
    ' inventoryOmittedCount=1',
    '|GET:/api/projects/:id/inventory-overflow:500:1 inventoryOmittedCount=1',
  )
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, []),
    error => error?.message.includes('leaf=report-message-unrecognized'),
  )
})

test('finishRuntime projects six closed audit stages without retaining raw failures for serialization', async () => {
  const source = workspace(SPEC)
  const stageStart = source.indexOf('const AUDIT_STAGES')
  const stageEnd = source.indexOf('\nasync function finishRuntime', stageStart)
  assert.notEqual(stageStart, -1, 'missing closed audit stages')
  const { auditStages, runRuntimeAuditStages } = new Function(
    `${source.slice(stageStart, stageEnd)}; return { auditStages: AUDIT_STAGES, runRuntimeAuditStages }`,
  )()
  const projectionStart = source.indexOf('function normalizedRuntimeApiPath')
  const projectionEnd = source.indexOf('\nasync function finishRuntime', projectionStart)
  const { publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(projectionStart, projectionEnd)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  for (const stage of auditStages) {
    const original = new Error(`never-print ${stage}`)
    const failure = await runRuntimeAuditStages(
      auditStages.map((name) => ({
        stage: name,
        run: async () => {
          if (name === stage) throw original
        },
      })),
    )
    assert.equal(failure.stage, stage)
    assert.equal(failure.error, original)
    const projected = new Error(project(null, failure.error, failure.stage))
    assert.equal(
      projected.message,
      stage === 'runtime-health'
        ? 'category=audit leaf=runtime-health-summary responseFailureCount=0 consoleErrorCount=0 pageErrorCount=0 requestFailureCount=0 apiReadErrorCount=0 requestReadErrorCount=0 forbiddenRequestCount=0 forbiddenResponseCount=0 responseMethod=unavailable responsePath=unavailable responseStatus=unavailable requestMethod=unavailable requestPath=unavailable requestStatus=unavailable readMethod=unavailable readPath=unavailable readStatus=unavailable responseInventory=none unavailableCount=0 inventoryOmittedCount=0 consoleKnownLinkedCount=0 consoleOtherCount=0'
        : `category=audit leaf=audit-stage stage=${stage} method=unavailable path=unavailable status=unavailable count=1`,
    )
    assert.doesNotMatch(projected.message, /never-print/u)
    assert.equal(Object.hasOwn(projected, 'errors'), false)
    assert.equal(Object.hasOwn(projected, 'cause'), false)
  }
  assert.match(source, /const auditFailure = await runRuntimeAuditStages\(/u)
  assert.match(source, /const safeProjection = projectPhase3FailureMessage\(bodyError, auditFailure\?\.error, auditFailure\?\.stage, evidence, expectedWrites, resolvedRuntimeAuditOptions\)/u)
  assert.match(source, /if \(bodyError \|\| auditFailure\) throw new Error\(safeProjection\)/u)
  const finishStart = source.indexOf('async function finishRuntime')
  const finishEnd = source.indexOf('\nfunction assertRuntimeListenersAttached', finishStart)
  const auditSecret = new Error('audit-secret-never-print')
  const bodySecret = new Error('body-secret-never-print')
  const safeProjection = 'category=audit leaf=audit-stage stage=exact-writes method=unavailable path=unavailable status=unavailable count=1'
  const finishRuntime = new Function(
    'runRuntimeAuditStages', 'scanRuntimeEvidence', 'runtimeSensitiveValues', 'assertNoPrivateEvidenceMarkers',
    'assertRuntimeEvidenceHealthy', 'phase3RuntimeAuditOptions', 'assertExactWrites', 'expect', 'test',
    'projectPhase3FailureMessage',
    `${source.slice(finishStart, finishEnd).replace('bodyError: unknown', 'bodyError')}; return finishRuntime`,
  )(
    async () => ({ stage: 'exact-writes', error: auditSecret }), () => ({ matchCount: 0 }), () => [],
    () => {}, () => ({ networkAccess: {} }), () => ({}), () => {}, () => ({ toEqual() {}, toMatchObject() {} }),
    { info: () => ({ annotations: [] }) },
    (bodyError, auditError, auditStage) => {
      assert.equal(bodyError, bodySecret)
      assert.equal(auditError, auditSecret)
      assert.equal(auditStage, 'exact-writes')
      return safeProjection
    },
  )
  let thrown
  await assert.rejects(finishRuntime({}, bodySecret, []), error => { thrown = error; return true })
  assert.equal(thrown?.message, safeProjection)
  assert.equal(thrown instanceof AggregateError, false)
  assert.equal(Object.hasOwn(thrown, 'errors'), false)
  assert.equal(Object.hasOwn(thrown, 'cause'), false)
  const serialized = JSON.stringify(thrown, Object.getOwnPropertyNames(thrown))
  assert.doesNotMatch(serialized, /body-secret-never-print|audit-secret-never-print/u)
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const report = playwrightReport([playwrightSpec('revision-outline-session', [{
    results: [{ status: 'failed', errors: [{ message: thrown.message }] }],
  }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'revision-outline-session', ['never-print']),
    error => error?.message.includes(safeProjection) && !error.message.includes('secret-never-print'),
  )
})

test('runner and CLI accept only a closed audit-stage projection', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const scenario = 'foundation-manual-r1'
  const projection = 'category=audit leaf=audit-stage stage=network-access method=unavailable path=unavailable status=unavailable count=1'
  const report = playwrightReport([playwrightSpec(scenario, [{
    results: [{ status: 'failed', errors: [{ message: projection }] }],
  }])])
  let failure
  try { runner.phase3BrowserFailure(report, scenario, ['never-print']) } catch (error) { failure = error }
  assert.match(failure?.message || '', new RegExp(`scenario=${scenario} ${projection}`, 'u'))
  assert.match(runner.formatPhase3CommandFailure(failure, { scenario }), new RegExp(projection, 'u'))
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = `${projection} never-print`
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = projection.replace('stage=network-access', 'stage=other')
  assert.throws(
    () => runner.phase3BrowserFailure(report, scenario, ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
})

test('runner and command diagnostics preserve a validated audit or behavior projection', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  for (const category of ['audit', 'behavior']) {
    const message = `category=${category} leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable`
    const report = playwrightReport([playwrightSpec('foundation-manual-r1', [{
      results: [{ status: 'failed', errors: [{ message }] }],
    }])])
    let failure
    try { runner.phase3BrowserFailure(report, 'foundation-manual-r1', ['never-print']) } catch (error) { failure = error }
    assert.match(failure.message, new RegExp(`scenario=foundation-manual-r1 category=${category} leaf=unavailable`, 'u'))
    const diagnostic = runner.formatPhase3CommandFailure(failure, { scenario: 'foundation-manual-r1' })
    assert.match(diagnostic, new RegExp(`category=${category}`, 'u'))
    assert.doesNotMatch(diagnostic, /never-print/u)
  }
})

test('command diagnostics retain a closed scenario and fixed category without raw failure text', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const diagnostic = runner.formatPhase3CommandFailure(
    new AggregateError([new Error('Authorization: Bearer never-print')]),
    { scenario: 'baseline-lock', environment: { TEST_MYSQL_PASSWORD: 'never-print' } },
  )
  assert.match(diagnostic, /scenario=baseline-lock/u)
  assert.match(diagnostic, /category=audit/u)
  assert.doesNotMatch(diagnostic, /never-print|Authorization/u)
})

test('the non-focused gate requires six ordered passing scenario reports', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const seen = []
  const environment = {
    TEST_MYSQL_HOST: '127.0.0.1', TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root', TEST_MYSQL_PASSWORD: 'test-only',
  }
  assert.equal(await runner.runPhase3({
    environment,
    runOneScenarioImpl: async ({ scenario }) => {
      seen.push(scenario)
      return playwrightReport([playwrightSpec(scenario, [{ results: [{ status: 'passed' }] }])])
    },
  }), 0)
  assert.deepEqual(seen, [...runner.FORMAL_SCENARIOS])
  await assert.rejects(
    runner.runPhase3({
      environment,
      runOneScenarioImpl: async () => ({ suites: [] }),
    }),
    /exactly one passed focused scenario/u,
  )
})

test('runner retains the original initialization failure when residue accounting also fails', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const original = new Error('owned root initialization sentinel')
  await assert.rejects(
    runner.runOneScenario({
      spec: 'phase3-story-planning.spec.ts',
      scenario: 'foundation-manual-r1',
      environment: {},
      databaseNameFactory: () => 'novel_creator_test_0123456789abcdef0123456789abcdef',
      ownedRootFactory() { throw original },
    }),
    error => error instanceof AggregateError && error.errors.includes(original),
  )
})

test('database-name factory failure follows root registration and still cleans the owned root', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const original = new Error('database-name factory sentinel')
  const events = []
  await assert.rejects(
    runner.runOneScenario({
      spec: 'phase3-story-planning.spec.ts',
      scenario: 'foundation-manual-r1',
      environment: {},
      ownedRootFactory() {
        events.push('root-factory')
        return 'novel-creator-phase3-injected-root'
      },
      databaseNameFactory() {
        events.push('database-factory')
        throw original
      },
      lifecycleRunner: async ({ registerRoot, initialize, cleanupRoot }) => {
        const lifecycle = {
          setRoot(value) {
            events.push('set-root')
            return value
          },
          setDatabase(value) {
            events.push('set-database')
            return value
          },
        }
        try {
          registerRoot(lifecycle)
          await initialize(lifecycle)
        } finally {
          await cleanupRoot('novel-creator-phase3-injected-root')
        }
      },
      ownedRootRemover() { events.push('remove-root') },
    }),
    error => error === original,
  )
  assert.deepEqual(events, ['root-factory', 'set-root', 'database-factory', 'remove-root'])
})

test('unused Outline supersession is bootstrapped through UI and has no Session write', () => {
  const source = workspace(SPEC)
  const start = source.indexOf("test('unused-outline-supersession")
  const end = source.indexOf("test('pinned-session", start)
  const scenario = source.slice(start, end)
  for (const fragment of [
    'createProjectUi(page, runtime)',
    'completePhase2PreparationUi(page, runtime)',
    "createManualPlanning(page, '规划 R1', runtime)",
    "createOutline(page, '未使用的小纲', runtime)",
    "createPlanningRevision(page, '推进 Planning Head', runtime)",
    '已被后续依据取代',
  ]) assert.match(scenario, new RegExp(fragment.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'))
  assert.doesNotMatch(scenario, /path:\s*session\(/u)

  const stages = [
    ['supersession-navigation', 'await page.goto(blocks())'],
    ['history-open', "page.getByRole('button', { name: '小纲历史', exact: true }).click()"],
    ['history-dialog', "const outlineHistory = page.getByRole('dialog', { name: '章节小纲历史', exact: true })"],
    ['history-status', "const supersededOutline = outlineHistory.getByText('已被后续依据取代', { exact: true })"],
    ['history-close', "outlineHistory.getByRole('button', { name: '关闭', exact: true }).click()"],
    ['readonly-note', "page.getByText('旧内容保持只读；新工作稿不会自动确认或创建写作会话。', { exact: true })"],
    ['save-absent', "page.getByRole('button', { name: '保存小纲工作稿' })"],
    ['final-settlement', 'await settleNavigationBoundary(page, runtime)'],
  ]
  let previous = -1
  for (const [stage, fragment] of stages) {
    const stageStart = scenario.indexOf(`runScenarioStage('unused-outline-supersession', '${stage}'`, previous)
    assert.ok(stageStart > previous, `missing supersession diagnostic stage ${stage}`)
    const nextStage = scenario.indexOf("runScenarioStage('unused-outline-supersession'", stageStart + 1)
    const stageSource = scenario.slice(stageStart, nextStage < 0 ? scenario.length : nextStage)
    assert.ok(stageSource.includes(fragment), `${stage} must own ${fragment}`)
    previous = stageStart
  }
  assert.doesNotMatch(scenario, /page\.getByText\('已被后续依据取代'/u)
})

test('pinned Session is created through UI before Planning R2 advances its head', () => {
  const source = workspace(SPEC)
  const start = source.indexOf("test('pinned-session")
  const end = source.indexOf("test('baseline-lock", start)
  const scenario = source.slice(start, end)
  for (const fragment of [
    'createProjectUi(page, runtime)',
    'completePhase2PreparationUi(page, runtime)',
    "createManualPlanning(page, '规划 R1', runtime)",
    "createOutline(page, 'R1 小纲', runtime)",
    'page.goto(writer())',
    "createPlanningRevision(page, '规划 R2', runtime)",
    'page.reload()',
    'Planning R1',
    'Outline R1',
    'path: session()',
  ]) assert.match(scenario, new RegExp(fragment.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'))
  const writerBefore = scenario.indexOf("runScenarioStage('pinned-session', 'writer-before'")
  const planningRevision = scenario.indexOf("runScenarioStage('pinned-session', 'planning-revision'", writerBefore)
  const pinnedRead = scenario.indexOf("await expect(page.getByText('Outline R1')).toBeVisible()", writerBefore)
  const settled = scenario.indexOf('await settleNavigationBoundary(page, runtime)', pinnedRead)
  assert.ok(writerBefore >= 0 && pinnedRead > writerBefore, 'writer-before must prove the pinned Outline')
  assert.ok(settled > pinnedRead && settled < planningRevision, 'Writer reads must settle before Planning navigation')
  const writerAfter = scenario.indexOf("runScenarioStage('pinned-session', 'writer-after'", planningRevision)
  const writerNavigation = scenario.indexOf('await page.goto(writer())', writerAfter)
  const writerNavigationSettled = scenario.indexOf('await settleNavigationBoundary(page, runtime)', writerNavigation)
  const writerReload = scenario.indexOf('await page.reload()', writerNavigation)
  assert.ok(writerAfter > planningRevision && writerNavigation > writerAfter, 'writer-after must return to Writer')
  assert.ok(
    writerNavigationSettled > writerNavigation && writerNavigationSettled < writerReload,
    'Writer navigation must settle before refresh',
  )
})

test('baseline lock proves immutable visible UI and a stale public Bible confirmation conflict', async () => {
  const source = workspace(SPEC)
  const start = source.indexOf("test('baseline-lock")
  const end = source.indexOf("test('archived-navigation", start)
  const scenario = source.slice(start, end)
  const seedLockStart = source.indexOf('async function assertBaselineSeedLockUi')
  const seedLockEnd = source.indexOf('\nasync function chooseVisibleSelectOption', seedLockStart)
  const seedLock = source.slice(seedLockStart, seedLockEnd)
  const staleBibleStart = source.indexOf('async function assertBaselineStaleBibleConfirmUi')
  const staleBibleEnd = source.indexOf('\nasync function chooseVisibleSelectOption', staleBibleStart)
  const staleBible = source.slice(staleBibleStart, staleBibleEnd)
  for (const fragment of [
    'baselineLockWrites',
    "page.context().newPage()",
    "getByRole('dialog', { name: '确认创作圣经', exact: true })",
    "waitForResponse(response => isResponse(response, 'POST', `/api/projects/${PROJECT_ID}/bible/confirm`))",
    'if (status !== 409)',
    "getByText('保存冲突：本地编辑仍保留，请重新加载权威版本后再继续。', { exact: true })",
    "getByRole('button', { name: '重新加载权威版本', exact: true })",
    "getByRole('button', { name: '新建种子', exact: true })).toHaveCount(0)",
    "const edit = page.getByRole('button', { name: '编辑', exact: true })",
    'await expect(edit).toBeDisabled()',
    "getByText('IMMUTABLE REVISION · R1', { exact: true })",
    "getByRole('button', { name: '一次确认完整契约', exact: true })).toHaveCount(0)",
    "getByRole('button', { name: '生成创作圣经', exact: true })).toHaveCount(0)",
    "getByRole('button', { name: '预览并确认', exact: true })).toHaveCount(0)",
    "getByText('Revision 1', { exact: true })).toHaveCount(1)",
  ]) assert.ok(`${scenario}\n${seedLock}\n${staleBible}`.includes(fragment), `baseline lock must retain visible evidence: ${fragment}`)
  assert.match(scenario, /runScenarioStage\('baseline-lock', 'seed-lock-view', \(\) => assertBaselineSeedLockUi\(page, runtime\)\)/u)
  assert.doesNotMatch(source, /Creation Bible is already confirmed/u)
  for (const removed of [
    ['selection', 'aba'].join('-'),
    ['selection', 'Aba'].join(''),
    ['seed', 'MutationPaths'].join(''),
    ['select', 'SeedUi'].join(''),
    ['createAndSelect', 'SeedUi'].join(''),
    ['seed', 'create-flow'].join('-'),
  ]) assert.equal(source.includes(removed), false, `legacy ABA artifact remains: ${removed}`)

  const writesStart = source.indexOf('function baselineLockWrites')
  const writesEnd = source.indexOf('\nfunction phase2SeedSelectionFailure', writesStart)
  const writes = source.slice(writesStart, writesEnd)
  assert.match(writes, /count: 2, statuses: \[201, 409\]/u)
  assert.match(writes, /\/bible\/confirm/u)
  const ledgerStart = source.indexOf('function phase2PreparationWrites')
  const { phase2PreparationWrites, baselineLockWrites } = new Function(
    'PROJECT_ID',
    `${source.slice(ledgerStart, writesEnd)}; return { phase2PreparationWrites, baselineLockWrites }`,
  )('01234567-89ab-cdef-0123-456789abcdef')
  assert.deepEqual(
    phase2PreparationWrites().filter(rule => rule.path.endsWith('/bindings')),
    [{ method: 'PUT', path: '/api/projects/01234567-89ab-cdef-0123-456789abcdef/bindings', count: 1, statuses: [200] }],
  )
  assert.equal(baselineLockWrites().some(rule => rule.path.endsWith('/bindings')), false)
  assert.deepEqual(
    baselineLockWrites().filter(rule => rule.path.endsWith('/bible/confirm')),
    [{ method: 'POST', path: '/api/projects/01234567-89ab-cdef-0123-456789abcdef/bible/confirm', count: 2, statuses: [201, 409] }],
  )
  assert.doesNotMatch(scenario, /disablePlanningModelUi\(page, runtime\)/u)
  for (const ordinaryScenario of [
    'foundation-manual-r1', 'revision-outline-session', 'unused-outline-supersession', 'pinned-session', 'archived-navigation',
  ]) {
    const ordinaryStart = source.indexOf(`test('${ordinaryScenario}`)
    const ordinaryEnd = source.indexOf("\ntest('", ordinaryStart + 1)
    const ordinary = source.slice(ordinaryStart, ordinaryEnd === -1 ? source.length : ordinaryEnd)
    assert.match(ordinary, /phase2PreparationWrites\(\)/u)
    assert.match(ordinary, /disablePlanningModelUi\(page, runtime\)/u)
  }

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const projection = 'category=behavior leaf=baseline-lock stage=stale-bible-confirm method=unavailable path=unavailable status=unavailable'
  const report = playwrightReport([playwrightSpec('baseline-lock', [{
    results: [{ status: 'failed', errors: [{ message: projection }] }],
  }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'baseline-lock', ['never-print']),
    error => error?.message.includes(projection) && !error.message.includes('never-print'),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = `${projection} never-print`
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'baseline-lock', ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
})

test('baseline Seed lock emits only closed navigation-to-disabled diagnostics', async () => {
  const source = workspace(SPEC)
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const stages = ['navigation', 'settlement', 'saved-section', 'generation', 'new-absent', 'select-absent', 'edit-count', 'edit-disabled']
  const expected = 'category=behavior leaf=baseline-seed-lock stage=edit-disabled method=unavailable path=unavailable status=unavailable'
  const start = source.indexOf('async function assertBaselineSeedLockUi')
  const end = source.indexOf('\nasync function chooseVisibleSelectOption', start)
  const helper = source.slice(start, end)
  assert.match(source, /leaf=baseline-seed-lock stage=\(navigation\|settlement\|saved-section\|generation\|new-absent\|select-absent\|edit-count\|edit-disabled\)/u)
  assert.match(workspace(RUNNER), /leaf=baseline-seed-lock stage=\(navigation\|settlement\|saved-section\|generation\|new-absent\|select-absent\|edit-count\|edit-disabled\)/u)
  for (const stage of stages) assert.ok(helper.includes(`'${stage}'`), `missing closed Seed-lock stage ${stage}`)
  assert.ok(helper.indexOf("stage = 'settlement'") < helper.indexOf('await settleNavigationBoundary(page, runtime)'))
  assert.ok(helper.indexOf('await settleNavigationBoundary(page, runtime)') < helper.indexOf("stage = 'saved-section'"))
  assert.ok(helper.indexOf("stage = 'saved-section'") < helper.indexOf("getByRole('button', { name: /已存种子/u }).click()"))
  assert.ok(helper.indexOf("getByRole('button', { name: /已存种子/u }).click()") < helper.indexOf("stage = 'generation'"))
  const report = playwrightReport([playwrightSpec('baseline-lock', [{
    results: [{ status: 'failed', errors: [{ message: expected }] }],
  }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'baseline-lock', ['never-print']),
    error => error?.message.includes(expected) && !error.message.includes('never-print'),
  )
})

test('baseline stale Bible confirmation emits only its closed public conflict diagnostics', async () => {
  const source = workspace(SPEC)
  const runnerSource = workspace(RUNNER)
  const stages = ['wait-registration', 'click', 'response', 'status', 'public-error', 'reload-action']
  const helperStart = source.indexOf('async function assertBaselineStaleBibleConfirmUi')
  const helperEnd = source.indexOf('\nasync function chooseVisibleSelectOption', helperStart)
  const helper = source.slice(helperStart, helperEnd)
  for (const stage of stages) assert.ok(helper.includes(`'${stage}'`), `missing stale Bible stage ${stage}`)
  for (const text of [source, runnerSource]) {
    assert.ok(text.includes('leaf=baseline-stale-bible stage=(wait-registration|click|response) method=POST'))
    assert.ok(text.includes('leaf=baseline-stale-bible stage=status method=POST'))
    assert.ok(text.includes('leaf=baseline-stale-bible stage=(public-error|reload-action) method=POST'))
  }
  assert.doesNotMatch(source, /Creation Bible is already confirmed/u)
})

test('Phase 2 preparation exposes only closed safe diagnostic stages', async () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function completePhase2PreparationUi')
  const end = source.indexOf('\nasync function chooseVisibleSelectOption', start)
  const helper = source.slice(start, end)
  const stages = [
    'seed-navigation',
    'seed-editor',
    'seed-save',
    'seed-select',
    'seed-settlement',
    'contract-navigation',
    'contract-manual',
    'engine-save',
    'style-save',
    'asset-save',
    'capacity-save',
    'contract-confirm',
    'contract-settlement',
    'bible-navigation',
    'bible-generate',
    'bible-preview',
    'bible-confirm',
    'final-settlement',
  ]
  for (const stage of stages) assert.ok(helper.includes(`stage = '${stage}'`), `missing Phase 2 diagnostic stage ${stage}`)
  assert.ok(helper.includes('leaf=phase2-preparation-flow stage=${stage}'))
  const closedStages = stages.join('|')
  assert.match(source, new RegExp(`leaf=phase2-preparation-flow stage=\\(${closedStages}\\)`, 'u'))
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const projection = 'category=behavior leaf=phase2-preparation-flow stage=seed-settlement method=unavailable path=unavailable status=unavailable'
  const report = playwrightReport([playwrightSpec('pinned-session', [{
    results: [{ status: 'failed', errors: [{ message: projection }] }],
  }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'pinned-session', ['never-print']),
    error => error?.message.includes(projection) && !error.message.includes('never-print'),
  )
  report.suites[0].specs[0].tests[0].results[0].errors[0].message = `${projection} never-print`
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'pinned-session', ['never-print']),
    error => error?.message.includes('leaf=report-message-unrecognized') && !error.message.includes('never-print'),
  )
})

test('Phase 2 Bible confirmation uses the current accessible dialog contract', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function completePhase2PreparationUi')
  const end = source.indexOf('\nasync function chooseVisibleSelectOption', start)
  const helper = source.slice(start, end)
  assert.match(helper, /getByRole\('dialog', \{ name: '确认创作圣经', exact: true \}\)\.getByRole\('button', \{ name: '确认签印', exact: true \}\)\.click\(\)/u)
  assert.doesNotMatch(source, /确认新的未来设计/u)
})

test('shared Phase 2 seed-selection bootstrap retains its closed safe substage diagnostic', async () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function completePhase2PreparationUi')
  const next = source.indexOf('\nasync function chooseVisibleSelectOption', start)
  const helper = source.slice(start, next)
  assert.match(helper, /phase2SeedSelectionFailure\(selectionStage\)/u)
  assert.match(helper, /page\.locator\('\.seed-confirm-dialog'\)\.filter\(\{ hasText: '确认创作种子' \}\)/u)
  assert.match(helper, /expect\(selectionDialog\.getByText\('确认创作种子', \{ exact: true \}\)\)\.toBeVisible\(\)/u)
  assert.match(helper, /selectionDialog\.getByRole\('button', \{ name: '确认这个种子并进入创作契约', exact: true \}\)\.click\(\)/u)
  assert.doesNotMatch(helper, /getByRole\('dialog', \{ name: '确认创作种子', exact: true \}\)/u)
  assert.match(source, /function phase2SeedSelectionFailure\(stage\)/u)
  assert.match(source, /stage=\$\{stage\} method=\$\{method\} path=\$\{path\} status=unavailable/u)
  assert.match(source, /card-count\|card-visible\|card-click\|modal-visible\|wait-registration\|confirm-click\|response\|generation\|settlement/u)

  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const projection = 'category=behavior leaf=phase2-seed-selection-flow stage=modal-visible method=unavailable path=unavailable status=unavailable'
  const report = playwrightReport([playwrightSpec('foundation-manual-r1', [{
    results: [{ status: 'failed', errors: [{ message: projection }] }],
  }])])
  assert.throws(
    () => runner.phase3BrowserFailure(report, 'foundation-manual-r1', ['never-print']),
    error => error?.message.includes(projection) && !error.message.includes('never-print'),
  )
})

test('archived navigation proves three canonical Planning routes stay read-only across history and refresh', () => {
  const source = workspace(SPEC)
  const start = source.indexOf("test('archived-navigation")
  const scenario = source.slice(start)
  for (const fragment of [
    'createProjectUi(page, runtime)',
    'completePhase2PreparationUi(page, runtime)',
    "createManualPlanning(page, '规划 R1', runtime)",
    "createOutline(page, '归档前小纲', runtime)",
    "path: `/api/projects/${PROJECT_ID}/archive`",
    'await expect(card).toHaveCount(1)',
    'await expect(card).toBeVisible()',
    "card.getByText('更多', { exact: true }).click()",
    "const archivedResponse = page.waitForResponse(response => isResponse(response, 'POST', `/api/projects/${PROJECT_ID}/archive`))",
    'expect((await archivedResponse).status()).toBe(200)',
    "page.goto(volumes())",
    "getByRole('link', { name: '情节线'",
    "getByRole('link', { name: '故事块'",
    'page.goBack()',
    'page.goForward()',
    'page.reload()',
    '当前项目或规划修订为只读状态',
    '当前小纲为只读权威记录',
  ]) assert.match(scenario, new RegExp(fragment.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'))
  assert.ok(
    scenario.indexOf("const archivedResponse = page.waitForResponse(response => isResponse(response, 'POST', `/api/projects/${PROJECT_ID}/archive`))")
      < scenario.indexOf("card.getByRole('button', { name: '归档', exact: true }).click()"),
    'archive response waiter must be registered before its UI click',
  )

})

test('Phase 3 runner registers its owned root before database identity or nonce initialization', () => {
  const source = workspace(RUNNER)
  const start = source.indexOf('export async function runOneScenario')
  const end = source.indexOf('\nexport async function runPhase3', start)
  const runner = source.slice(start, end)
  const root = runner.indexOf('lifecycle.setRoot(ownedRootFactory(OWNED_ROOT_PREFIX))')
  const database = runner.indexOf('databaseNameFactory()')
  const nonce = runner.indexOf('randomUUID()')
  const setDatabase = runner.indexOf('lifecycle.setDatabase(databaseName)')
  assert.ok(root >= 0 && database > root && nonce > database && setDatabase > nonce)
  assert.match(runner, /async cleanupRoot\(ownedRoot\) \{[\s\S]*?auditAndRemovePhase3Root\([\s\S]*?removeRoot: ownedRootRemover/u)
})

test('Phase 3 cleanup audits the deny ledger even when browser execution has already failed', () => {
  const source = workspace(RUNNER)
  const start = source.indexOf('export async function runOneScenario')
  const end = source.indexOf('\nexport async function runPhase3', start)
  const runner = source.slice(start, end)
  const cleanupRoot = runner.slice(runner.indexOf('async cleanupRoot'), runner.indexOf('\n      },\n    })'))
  const auditRoot = source.slice(source.indexOf('export function auditAndRemovePhase3Root'), source.indexOf('\nexport async function exercisePhase3Lifecycle'))
  assert.match(cleanupRoot, /auditAndRemovePhase3Root\([\s\S]*?denyLedgerPath/u)
  assert.match(auditRoot, /denyAudit = assertDenyLedger\(readFile\(denyLedgerPath, 'utf8'\)\)/u)
  assert.ok(auditRoot.indexOf('assertDenyLedger') < auditRoot.indexOf('removeRoot'))
  assert.doesNotMatch(runner, /if \(!scenarioError && \(!rootRemoved/u)
})

test('deny-ledger audit failure survives alongside a browser failure after root cleanup', async () => {
  const runner = await import('../../frontend/e2e/run-phase3.mjs')
  const forbidden = new Error('deny ledger sentinel')
  const audit = runner.auditAndRemovePhase3Root({
    ownedRoot: 'novel-creator-phase3-injected-root',
    denyLedgerPath: 'deny-ledger',
    artifactRoot: null,
    safeAuditPaths: [],
    sensitiveValues: [],
    readFile: () => 'forbidden request',
    assertDenyLedger: () => { throw forbidden },
    removeRoot: () => {},
    rootExists: () => false,
  })
  assert.equal(audit.denyAuditChecked, true)
  assert.equal(audit.rootRemoved, true)
  assert.deepEqual(audit.errors, [forbidden])

  const browserFailure = new Error('browser failure sentinel')
  const cleanupFailure = new AggregateError(audit.errors, 'Phase 3 root audit and cleanup failed')
  await assert.rejects(
    runner.exercisePhase3Lifecycle({
      registerRoot(lifecycle) { lifecycle.setRoot('novel-creator-phase3-injected-root') },
      initialize() { throw browserFailure },
      cleanupServers() {},
      cleanupReservations() {},
      cleanupDatabase() {},
      cleanupRoot() { throw cleanupFailure },
    }),
    error => error instanceof AggregateError
      && error.errors.includes(browserFailure)
      && error.errors.includes(cleanupFailure)
      && cleanupFailure.errors.includes(forbidden),
  )
})

test('archived volumes proves read-only state again after a settled reload', () => {
  const source = workspace(SPEC)
  const slice = (stage, nextStage) => {
    const start = source.indexOf(`runScenarioStage('archived-navigation', '${stage}'`)
    const end = source.indexOf(`runScenarioStage('archived-navigation', '${nextStage}'`, start)
    return source.slice(start, end)
  }
  const volumes = slice('volumes-readonly', 'plots-navigation')
  const firstGoto = volumes.indexOf('await page.goto(volumes())')
  const firstSettle = volumes.indexOf('await settleNavigationBoundary(page, runtime)', firstGoto)
  const reload = volumes.indexOf('await page.reload()', firstSettle)
  const secondSettle = volumes.indexOf('await settleNavigationBoundary(page, runtime)', reload)
  const readonlyAgain = volumes.indexOf("getByRole('button', { name: '建立空白规划工作稿' })).toHaveCount(0)", secondSettle)
  assert.ok(firstGoto >= 0 && firstSettle > firstGoto && reload > firstSettle && secondSettle > reload && readonlyAgain > secondSettle)

  const plots = slice('plots-navigation', 'browser-history')
  assert.match(plots, /getByRole\('link', \{ name: '情节线', exact: true \}\)\.click\(\)/u)
  assert.match(plots, /toHaveURL\(new RegExp\(`\$\{plots\(\)\}\$`, 'u'\)\)/u)
  assert.match(plots, /只读状态；可以查阅正文规划与历史/u)

  const history = slice('browser-history', 'blocks-readonly')
  assert.match(history, /await page\.goBack\(\)[\s\S]*?\$\{volumes\(\)\}\$/u)
  assert.match(history, /await page\.goForward\(\)[\s\S]*?\$\{plots\(\)\}\$/u)
  assert.match(history, /await page\.reload\(\)[\s\S]*?只读状态；可以查阅正文规划与历史/u)

  const blocks = slice('blocks-readonly', 'missing-stage')
  assert.match(blocks, /getByRole\('link', \{ name: '故事块', exact: true \}\)\.click\(\)/u)
  assert.match(blocks, /toHaveURL\(new RegExp\(`\$\{blocks\(\)\}\$`, 'u'\)\)/u)
  assert.match(blocks, /await page\.goBack\(\)[\s\S]*?\$\{plots\(\)\}\$/u)
  assert.match(blocks, /await page\.goForward\(\)[\s\S]*?\$\{blocks\(\)\}\$/u)
  assert.match(blocks, /await page\.reload\(\)[\s\S]*?当前小纲为只读权威记录/u)
  assert.match(blocks, /await settleNavigationBoundary\(page, runtime\)/u)
})

test('Phase 3 runtime wrapper attaches page-only audits to every context page without duplicating network listeners', () => {
  const source = workspace(SPEC)
  const start = source.indexOf('async function runAudited')
  const end = source.indexOf('\nasync function completePhase2PreparationUi', start)
  const runAudited = source.slice(start, end)
  assert.match(source, /function observePhase3Runtime\(page\)/u)
  assert.match(source, /context\.on\('page', attachPageEvidence\)/u)
  assert.match(source, /secondaryPageContents/u)
  assert.match(runAudited, /const runtime = observePhase3Runtime\(page\)/u)
  assert.doesNotMatch(source, /context\.on\('response', onSecondary/u)
})

test('secondary Page console, error, and DOM evidence fail the Phase 3 private audit without entering diagnostics', async () => {
  const source = workspace(SPEC)
  const wrapperStart = source.indexOf('function observePhase3Runtime')
  const wrapperEnd = source.indexOf('\nasync function completePhase2PreparationUi', wrapperStart)
  const handlers = new Map()
  const secondaryHandlers = new Map()
  const context = {
    pages: () => [main, secondary],
    on(event, listener) { handlers.set(event, listener) },
  }
  const main = { context: () => context }
  const secondary = {
    on(event, listener) { secondaryHandlers.set(event, listener) },
    async content() { return '<main>apiKey=secondary-secret-never-print</main>' },
  }
  const observePhase3Runtime = new Function(
    'observeRuntime', 'allowedOrigins',
    `${source.slice(wrapperStart, wrapperEnd)}; return observePhase3Runtime`,
  )(() => ({
    async finish() {
      return {
        consoleMessages: [], consoleErrors: [], pageErrors: [], pageContent: '<main>primary</main>',
      }
    },
  }), [])
  const runtime = observePhase3Runtime(main)
  const evidence = await runtime.finish()
  secondaryHandlers.get('console')({ type: () => 'error', text: () => 'Authorization: Bearer console-secret-never-print' })
  secondaryHandlers.get('pageerror')({ message: 'rawProviderOutput=page-secret-never-print' })
  const audited = await runtime.finish()
  assert.ok(evidence.pageContent.includes('secondary-secret-never-print'))
  assert.ok(audited.consoleErrors.includes('Authorization: Bearer console-secret-never-print'))
  assert.ok(audited.pageErrors.includes('rawProviderOutput=page-secret-never-print'))
  const { assertNoPrivateEvidenceMarkers, publicRuntimeDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  assert.throws(() => assertNoPrivateEvidenceMarkers([
    ...audited.consoleErrors, ...audited.pageErrors, audited.pageContent,
  ]))
  const projectionStart = source.indexOf('function normalizedRuntimeApiPath')
  const projectionEnd = source.indexOf('\nasync function finishRuntime', projectionStart)
  const project = new Function(
    'runtimeFailureDiagnostic', 'publicRuntimeDiagnostic',
    `${source.slice(projectionStart, projectionEnd)}; return projectPhase3FailureMessage`,
  )(() => null, publicRuntimeDiagnostic)
  const projection = project(null, new Error('private audit failed'), 'private-marker', audited)
  assert.equal(projection, 'category=audit leaf=audit-stage stage=private-marker method=unavailable path=unavailable status=unavailable count=1')
  assert.doesNotMatch(projection, /secondary-secret|console-secret|page-secret/u)
})
