import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'

const manualWizardWrites = [
  { method: 'PUT', path: /\/selected-seed$/, count: 1, statuses: [200] },
  { method: 'POST', path: /\/story-engine-batches\/manual$/, count: 1, statuses: [201] },
  { method: 'PUT', path: /\/contract-draft$/, count: 3, statuses: [200] },
  { method: 'POST', path: /\/contracts\/preview$/, count: 1, statuses: [200] },
  { method: 'POST', path: /\/contracts\/confirm$/, count: 1, statuses: [201] },
]

const manualOptions = [
  {
    name: '潮钟追凶',
    storyPromise: '每次钟鸣都提前揭示一场海难，主角必须在预言应验前找出人为改钟者。',
    protagonistDesire: '找回失踪导师并证明潮汐钟不是灾祸源头。',
    sustainedPressure: '风暴季逼近，议会每隔七日封存一层钟室。',
    growthDirection: '从只相信测量误差，成长为能承担公共判断的守钟人。',
    conflictLoop: '发现异常刻度、追查港区线索、付出救援代价、暴露更深篡改。',
    ensembleRoles: [{ role: '港务书记', purpose: '提供制度阻力并保存旧航海档案。' }],
    advantageAndCost: '主角能读懂细微机械误差，但每次校正都会失去一段导师留下的记录。',
    satisfactionSources: ['用可验证的钟表证据推翻错误定论。'],
    longFormVariation: ['从单港事故扩展到群岛航路与百年潮墙。'],
    endingAnchor: '主角公开最后一组刻度，让全港共同决定是否敲响终钟。',
    risks: ['谜题必须持续给出可回收证据，不能只靠临时反转。'],
    differentiation: '把机械误差、港务制度和救援选择绑定成同一冲突循环。',
  },
  {
    name: '退潮远航',
    storyPromise: '每次异常退潮都会露出一段失落航道，主角带队抢在涨潮前完成一次探索。',
    protagonistDesire: '绘出一张能带所有渔船安全越过风暴带的新海图。',
    sustainedPressure: '可探索窗口越来越短，竞争船队也在争夺同一批航标。',
    growthDirection: '从独自校钟的学徒成长为能协调多船协作的领航者。',
    conflictLoop: '预测退潮、组织船队、争夺航标、带回发现并改变下一次路线。',
    ensembleRoles: [{ role: '纸帆船长', purpose: '挑战主角的保守判断并承担远航风险。' }],
    advantageAndCost: '潮钟能给出精确窗口，但公开预测会让竞争者同步获知航线。',
    satisfactionSources: ['在有限时间里完成协作探索并带回可见成果。'],
    longFormVariation: ['航道从近岸遗迹逐步延伸到移动群岛。'],
    endingAnchor: '新海图完成时，主角必须决定是否保留最后一条只属于导师的航线。',
    risks: ['探索地点需要改变人物关系，避免成为重复寻宝。'],
    differentiation: '用周期性退潮窗口驱动团队航海，而非单纯破解预言。',
  },
  {
    name: '潮墙公议',
    storyPromise: '潮墙每出现一道新刻度，港城就必须在三种互相冲突的防灾方案中公开选择。',
    protagonistDesire: '建立一套普通人也能核验的灾害判断方法。',
    sustainedPressure: '不同城区承担的代价不均，任何方案都会让一部分人先受损。',
    growthDirection: '从技术见证者成长为愿意解释、倾听并承担后果的公共决策者。',
    conflictLoop: '读取刻度、提出三案、公开质询、执行选择、检验后果。',
    ensembleRoles: [{ role: '盐堤代表', purpose: '迫使主角面对方案在底层城区造成的真实代价。' }],
    advantageAndCost: '主角拥有最完整测量记录，却因此成为各方争夺解释权的目标。',
    satisfactionSources: ['让证据、利益和人物选择在公开辩论中正面碰撞。'],
    longFormVariation: ['议题从一次风暴扩展到港城迁移与群岛联盟。'],
    endingAnchor: '最后一次公议不再等待潮钟给答案，而由全城共同承担选择。',
    risks: ['制度冲突必须落到具体行动，避免只有会议对白。'],
    differentiation: '把三方案比较直接变成长篇叙事结构与公共选择。',
  },
]

function requiredEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`Missing required browser test environment: ${name}`)
  return value
}

async function assertManualRuntime(observer: ReturnType<typeof observeRuntime>) {
  const evidence = await observer.finish()
  const expectedReadMiss = (entry: { method: string, status: number, url: string }) => (
    entry.method === 'GET'
    && entry.status === 404
    && /\/contract-draft$/.test(new URL(entry.url).pathname)
  )
  const unexpectedApiResponses = evidence.apiResponses.filter(entry => (
    (entry.status < 200 || entry.status >= 300) && !expectedReadMiss(entry)
  ))
  const unexpectedResponseFailures = evidence.responseFailures.filter(entry => (
    !/^404 GET .*\/contract-draft$/u.test(entry)
  ))
  const expectedConsoleErrors = evidence.consoleErrors.filter(entry => (
    /^error: Failed to load resource: the server responded with a status of 404 \(Not Found\)$/u.test(entry)
  ))
  const unexpectedConsoleErrors = evidence.consoleErrors.filter(entry => (
    !expectedConsoleErrors.includes(entry)
  ))

  expect(assertExactWrites(evidence, manualWizardWrites)).toEqual({ writeCount: 7 })
  expect(unexpectedApiResponses, 'only the absent initial draft may return 404').toEqual([])
  expect(unexpectedResponseFailures, 'page responses must be successful').toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.bodyReadError)).toEqual([])
  expect(evidence.apiResponses.filter(entry => entry.headersReadError)).toEqual([])
  expect(expectedConsoleErrors, 'the absent draft produces one browser 404 diagnostic').toHaveLength(1)
  expect(unexpectedConsoleErrors, 'no unexpected console.error is allowed').toEqual([])
  expect(evidence.pageErrors, 'uncaught page errors must stay empty').toEqual([])
  expect(evidence.requestFailures, 'network requests must not fail').toEqual([])
  expect(scanRuntimeEvidence(evidence, [
    ...runtimeSensitiveValues(),
    requiredEnvironment('BROWSER_TEST_DATABASE'),
  ])).toEqual({ matchCount: 0 })
}

test('completes and confirms the five-step wizard with manual three-engine options', async ({ page }) => {
  const observer = observeRuntime(page)

  await page.goto('/project/00000000-0000-0000-0000-000000000201')
  await expect(page.getByRole('heading', { name: '本书创作契约' })).toBeVisible()

  await page.getByRole('button', { name: /选择种子/ }).click()
  const seedCard = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: '雾港天文钟' }),
  })
  await seedCard.getByRole('button', { name: '选定并继续' }).click()

  await page.getByRole('button', { name: '高级手动 JSON' }).click()
  await page.getByRole('textbox').fill(JSON.stringify(manualOptions))
  await page.getByRole('button', { name: '建立手动三案' }).click()
  await expect(page.getByRole('radio')).toHaveCount(3)
  await page.getByRole('radio', { name: /潮钟追凶/ }).click()
  await page.getByRole('button', { name: '保存并继续' }).click()

  await expect(page.getByRole('heading', { name: '三个可比较的写作气质' })).toBeVisible()
  const styleCard = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: '克制悬疑型' }),
  })
  await styleCard.getByRole('button', { name: '设为主风格' }).click()
  await page.getByRole('button', { name: '保存并继续' }).click()

  await expect(page.getByRole('heading', { name: '作者明确允许参考的来源' })).toBeVisible()
  await page.getByRole('button', { name: '保存并继续' }).click()

  await expect(page.getByRole('heading', { name: '冻结快照' })).toBeVisible()
  await expect(page.getByText('可以签印', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '一次确认完整契约', exact: true }).click()

  const contractHead = page.getByRole('article').filter({
    has: page.getByRole('heading', { name: '当前生效的创作契约' }),
  })
  await expect(contractHead).toBeVisible()
  await expect(contractHead.getByRole('row', {
    name: '正式修订 R1 当前状态 等待滚动规划',
    exact: true,
  })).toBeVisible()
  await expect(page.getByRole('button', { name: '进入写作台' })).toBeDisabled()

  await assertManualRuntime(observer)
})
