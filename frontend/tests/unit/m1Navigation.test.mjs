import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const readSource = relativePath => readFile(new URL(`../../src/${relativePath}`, import.meta.url), 'utf8')

async function readActiveDependencyTree(entry, visited = new Set()) {
  if (visited.has(entry)) return ''
  visited.add(entry)
  const source = await readSource(entry)
  const imports = [...source.matchAll(/from\s+['"](@\/[^'"]+|\.\.?\/[^'"]+)['"]/g)]
  const directory = entry.split('/').slice(0, -1)
  const children = []
  for (const [, specifier] of imports) {
    const rawParts = specifier.startsWith('@/')
      ? specifier.slice(2).split('/')
      : [...directory, ...specifier.split('/')]
    const normalized = []
    for (const part of rawParts) {
      if (part === '.' || !part) continue
      if (part === '..') normalized.pop()
      else normalized.push(part)
    }
    const path = normalized.join('/')
    for (const candidate of /\.[a-z]+$/i.test(path) ? [path] : [`${path}.js`, `${path}.vue`]) {
      try {
        children.push(await readActiveDependencyTree(candidate, visited))
        break
      } catch (error) {
        if (error?.code !== 'ENOENT') throw error
      }
    }
  }
  return `${entry}\n${source}\n${children.join('\n')}`
}

test('the writer route mounts the M5 chapter workspace without old provider or finalization paths', async () => {
  const router = await readSource('router/index.js')
  const workspace = await readSource('views/ChapterWriterView.vue')

  assert.match(router, /ChapterWriterView\.vue/)
  assert.doesNotMatch(router, /@\/views\/WriterView\.vue/)
  assert.match(workspace, /useChapterSessionStore/)
  assert.match(workspace, /创建章节会话/)
  assert.match(workspace, /保存工作稿/)
  assert.match(workspace, /AI 生成工作稿/)
  assert.match(workspace, /generateWorkingDraft/)
  assert.match(workspace, /作者临时要求/)
  assert.match(workspace, /保存为候选/)
  assert.match(workspace, /编辑不会自动生成候选/)
  assert.doesNotMatch(workspace, /chatCompletion|createAdapter|providerAdapter|applyAdapter|finalize|定稿|生成候选稿|AI 生成候选/)
})

test('the M3 project shell depends only on formal project writer core and planning reads', async () => {
  const projectView = await readSource('views/ProjectView.vue')
  for (const forbidden of [
    'useWriterStore', 'useNovelStore', 'useSettingStore', 'useVolumeStore',
    'useStoryBlockStore', 'useCorrectionTaskStore', 'WriterView',
  ]) {
    assert.equal(projectView.includes(forbidden), false, `legacy project dependency remains: ${forbidden}`)
  }
  assert.equal((projectView.match(/projectStore\.openProject\(/g) || []).length, 1)
  assert.equal((projectView.match(/seedStore\.loadSeeds\(/g) || []).length, 0)
  assert.equal((projectView.match(/api\.writerCore\.state\(/g) || []).length, 1)
  assert.match(projectView, /usePlanningStore/)
  assert.match(projectView, /planningStore\.load\(/)
  assert.match(projectView, /PlanningWorkspace/)
  assert.match(projectView, /watch\(\s*\(\)\s*=>\s*route\.params\.id/)
  assert.match(projectView, /createLatestRequestGuard/)
  assert.match(projectView, /onBeforeUnmount/)
  assert.match(projectView, /派生写作数据.*重置/s)
  assert.match(projectView, /进入写作台/)
  assert.match(projectView, /openWriterWorkspace/)
  assert.match(projectView, /planningStore\.planningReady/)
})

test('the formal project page mounts one five-step creation contract wizard', async () => {
  const [projectView, wizard, planning, seed, engine, style, assets, preview, head] = await Promise.all([
    readSource('views/ProjectView.vue'),
    readSource('components/project/CreationContractWizard.vue'),
    readSource('components/planning/PlanningWorkspace.vue'),
    readSource('components/project/contract/SeedSelectionStep.vue'),
    readSource('components/project/contract/StoryEngineStep.vue'),
    readSource('components/project/contract/StyleSelectionStep.vue'),
    readSource('components/project/contract/AssetScopeStep.vue'),
    readSource('components/project/contract/ContractPreviewStep.vue'),
    readSource('components/project/ContractHeadSummary.vue'),
  ])
  const componentTree = [wizard, seed, engine, style, assets, preview, head].join('\n')

  assert.match(projectView, /CreationContractWizard/)
  assert.match(projectView, /<creation-contract-wizard/)
  assert.match(projectView, /<planning-workspace/)
  assert.match(planning, /创建滚动规划/)
  assert.match(planning, /当前故事块/)
  assert.match(planning, /SceneTask/)
  assert.match(planning, /expectedContractRevision/)
  assert.equal((projectView.match(/seedStore\.loadSeeds\(/g) || []).length, 0)
  assert.match(wizard, /选择种子/)
  assert.match(wizard, /故事发动机/)
  assert.match(wizard, /风格契约/)
  assert.match(wizard, /素材范围/)
  assert.match(wizard, /冻结并确认/)
  assert.match(wizard, /ContractHeadSummary/)
  assert.match(wizard, /onBeforeRouteLeave/)
  assert.match(wizard, /onBeforeRouteUpdate/)
  assert.match(wizard, /beforeunload/)
  assert.match(wizard, /seedRevisionId/)
  assert.match(wizard, /selectedSeed\.revisionId/)
  assert.match(wizard, /seedHash/)
  assert.match(wizard, /selectedSeed\.contentHash/)
  assert.match(wizard, /writeBusy/)
  assert.match(wizard, /contractStore\.saving/)
  assert.match(wizard, /contractStore\.confirming/)
  assert.match(wizard, /contractStore\.cloning/)
  assert.match(wizard, /:disabled="writeBusy \|\| !canOpen/)
  assert.match(wizard, /:disabled="writeBusy" @click="loadWizard/)
  assert.match(seed, /busy-change/)
  assert.match(preview, /等待滚动规划/)
  assert.match(preview, /作者即将确认的创作约定/)
  assert.match(preview, /章节容量策略/)
  assert.match(preview, /喜欢的表现/)
  assert.match(preview, /明确避开/)
  assert.match(head, /创建新修订/)
  assert.match(engine, /store\.draft !== saved/)
  assert.match(style, /contractStore\.draft !== saved/)
  assert.match(assets, /contractStore\.draft !== saved/)
  for (const asyncStep of [style, assets]) {
    assert.match(asyncStep, /onBeforeUnmount/)
    assert.match(asyncStep, /loadEpoch \+= 1/)
    assert.match(asyncStep, /reloadContract: true/)
    assert.match(asyncStep, /if \(contractStore\.saving\) return/)
    assert.match(asyncStep, /contractStore\.requiresReload/)
  }

  for (const forbidden of [
    /\bfetch\s*\(/, /localStorage/, /createAdapter/, /chatCompletion/,
    /page\.request/, /ExperienceCardsView/, /experienceCardProduct/,
  ]) {
    assert.doesNotMatch(componentTree, forbidden)
  }
})

test('active navigation exposes no retired import export backup or provider call', async () => {
  const [home, app, providerSettings, seedStore, projectStore, binding, router, sidebarTree] = await Promise.all([
    readSource('views/HomeView.vue'),
    readSource('App.vue'),
    readSource('components/settings/ProviderSettings.vue'),
    readSource('stores/seedStore.js'),
    readSource('stores/projectStore.js'),
    readSource('components/settings/TaskModelBinding.vue'),
    readSource('router/index.js'),
    readActiveDependencyTree('components/layout/Sidebar.vue'),
  ])

  assert.doesNotMatch(home, /导入项目|导出|exportFull|importFull/)
  assert.match(home, /@click=.*handleOpen/)
  assert.doesNotMatch(home, /@dblclick/)
  assert.match(home, /class="card-open-area"/)
  assert.match(home, /删除失败/)
  assert.doesNotMatch(app, /BackupReminder/)
  assert.doesNotMatch(providerSettings, /testConnection|测试连接/)
  assert.doesNotMatch(seedStore, /clearSeeds|generateSeeds|chatCompletion|createAdapter|localStorage/)
  for (const formalMethod of ['list', 'selected', 'create', 'update', 'delete', 'select']) {
    assert.match(seedStore, new RegExp(`api\\.seeds\\.${formalMethod}\\(`))
  }
  assert.match(seedStore, /createLatestRequestGuard/)
  assert.match(seedStore, /seeds\.value = \[\]/)
  assert.match(seedStore, /invalidateLoadSeeds/)
  assert.match(projectStore, /createLatestRequestGuard/)
  assert.match(projectStore, /currentProject\.value = null/)
  assert.match(projectStore, /invalidateOpenProject/)
  assert.match(binding, /replaceBindings/)
  assert.match(binding, /一次保存八项绑定/)
  assert.match(binding, /expectedRevision/)
  assert.match(binding, /createLatestRequestGuard/)
  assert.match(binding, /项目列表加载失败/)
  assert.match(binding, /没有可配置的项目/)
  assert.doesNotMatch(binding, /@click="loadStatus"/)
  assert.doesNotMatch(binding, /@click="loadProjectsAndSelect"/)
  assert.match(providerSettings, /停用失败/)
  assert.doesNotMatch(router, /ExperienceCards|experience-cards/)
  assert.match(router, /path:\s*['"]\/:pathMatch\(\.\*\)\*['"].*redirect:\s*['"]\/['"]/s)
  assert.doesNotMatch(
    sidebarTree,
    /写作台|\/writer\/|ExperienceCards|['"`]\/experience-cards|创作经验卡/,
  )
})

test('the top bar explicitly imports the breadcrumb item it renders', async () => {
  const topBar = await readSource('components/layout/TopBar.vue')

  assert.match(topBar, /NBreadcrumbItem/)
  assert.match(topBar, /<n-breadcrumb-item/)
  assert.doesNotMatch(topBar, /\bNButton\b/)
})
