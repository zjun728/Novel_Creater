import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { access, readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const repositoryRoot = path.dirname(frontendRoot)
const sourceRoot = path.join(frontendRoot, 'src')

const CANONICAL_ROUTES = [
  ['/', undefined],
  ['/projects', 'ProjectLibrary'],
  ['/topics/market', 'TopicMarket'],
  ['/topics/discussions', 'TopicDiscussions'],
  ['/topics/directions', 'TopicDirections'],
  ['/topics/candidates', 'TopicCandidates'],
  ['/projects/archived', 'ArchivedProjects'],
  ['/assets/styles', 'StyleLibrary'],
  ['/assets/experience', 'ExperienceLibrary'],
  ['/assets/corpus', 'CorpusLibrary'],
  ['/projects/:projectId/overview', 'ProjectOverview'],
  ['/projects/:projectId/settings/models', 'ProjectModelSettings'],
  ['/projects/:projectId/settings/export', 'ProjectExport'],
  ['/projects/:projectId/seeds', 'ProjectSeeds'],
  ['/projects/:projectId/contract', 'ProjectContract'],
  ['/projects/:projectId/bible', 'ProjectBible'],
  ['/projects/:projectId/planning/volumes', 'ProjectPlanningVolumes'],
  ['/projects/:projectId/planning/plots', 'ProjectPlanningPlots'],
  ['/projects/:projectId/planning/story-blocks', 'ProjectPlanningStoryBlocks'],
  ['/projects/:projectId/manuscript', 'ProjectManuscript'],
  ['/projects/:projectId/manuscript/chapters/:chapterNumber([1-9]\\d*)', 'FinalChapterReader'],
  ['/projects/:projectId/write/chapters/:chapterNumber([1-9]\\d*)', 'ChapterWriter'],
  ['/settings/providers', 'ProviderSettings'],
  ['/settings/application', 'ApplicationSettings'],
  ['/not-found', 'NotFound'],
  ['/:pathMatch(.*)*', 'NotFoundFallback'],
]

const RETIRED_RUNTIME = [
  'stores/novelStore.js',
  'stores/settingStore.js',
  'stores/memoryStore.js',
  'stores/volumeStore.js',
  'stores/plotStore.js',
  'stores/storyBlockStore.js',
  'stores/compareStore.js',
  'stores/writerStore.js',
  'stores/correctionTaskStore.js',
  'api/ai/index.js',
  'api/ai/adapterBase.js',
  'api/ai/anthropicAdapter.js',
  'api/ai/openaiCompatibleAdapter.js',
  'application/writer-flow/beat-plan-command.js',
  'application/writer-flow/chapter-title-command.js',
  'application/writer-flow/context-session.js',
  'application/writer-flow/draft-generation-command.js',
  'application/writer-flow/draft-repair-pipeline.js',
  'application/writer-flow/finalization-command.js',
  'application/writer-flow/finalization-marker-action.js',
  'application/writer-flow/preconditions.js',
  'application/writer-flow/save-beat-plan-command.js',
  'application/writer-flow/version-creation-command.js',
  'domain/chapter-draft/ai-content.js',
  'domain/chapter-title/index.js',
  'domain/chapter-title/policy.js',
  'domain/chapter-title/ranker.js',
  'domain/chapter-title/source-extractor.js',
  'components/writer/AIActionPanel.vue',
  'components/writer/CanonReviewPanel.vue',
  'components/writer/ChapterVersionList.vue',
  'components/writer/CompareInline.vue',
  'components/writer/CompareModal.vue',
  'components/writer/ContextMemoryPanel.vue',
  'components/writer/ContextPreviewModal.vue',
  'components/writer/FusionPanel.vue',
  'components/writer/PacingChart.vue',
  'components/writer/StoryBlockPanel.vue',
  'components/writer/StyleAnalysisPanel.vue',
  'components/writer/VersionDiffModal.vue',
  'components/chapter/RollingPlanningPanel.vue',
  'components/chapter/VolumePlanner.vue',
  'components/correction/CorrectionTaskBoard.vue',
  'components/settings-library/SettingLibrary.vue',
  'components/settings/projectBindingSelection.js',
  'components/story-block/StoryBlockCard.vue',
  'components/story-block/StoryBlockList.vue',
  'components/story-block/StoryBlockStageList.vue',
  'composables/useResetConfirmation.js',
  'data/localWritingSampleReport.json',
  'data/realCorpusExperienceCardsV3.js',
  'data/sampleMicroDemoCards.js',
  'data/sampleMicroDemoCards.v2_1.json',
  'data/sampleMicroDemoCards.v2_2.json',
  'data/writingFingerprints.js',
  'data/writingSampleAnalyzer.js',
  'data/writingSampleReview.js',
  'data/writingStyleStandards.js',
  'prompts/aiTraceReview.js',
  'prompts/audit.js',
  'prompts/brainstorm.js',
  'prompts/chapter.js',
  'prompts/chapterDraftPrompt.js',
  'prompts/chapterPlanPrompt.js',
  'prompts/chapterRevisionPrompt.js',
  'prompts/correctionDraft.js',
  'prompts/correctionPatch.js',
  'prompts/extraction.js',
  'prompts/globalAudit.js',
  'prompts/outline.js',
  'prompts/pacing.js',
  'prompts/rewrite.js',
  'prompts/settingExtraction.js',
  'prompts/storyBlockPrompt.js',
  'prompts/style.js',
  'prompts/summary.js',
  'prompts/volumeAudit.js',
  'prompts/volumePlan.js',
  'prompts/volumeSummary.js',
  'quality/writingQualityPrompt.js',
  'quality/writingQualityScoring.js',
  'quality/writingQualityStandard.js',
  'utils/auditLabels.js',
  'utils/auditRevisionTools.js',
  'utils/canonFactFallback.js',
  'utils/chapterStateLedger.js',
  'utils/chapterWordTarget.js',
  'utils/characterFactMatcher.js',
  'utils/contextBuilder.js',
  'utils/contextPackV2.js',
  'utils/correctionManualClosure.js',
  'utils/correctionTaskDenoise.js',
  'utils/correctionTaskRules.js',
  'utils/export.js',
  'utils/finalizationGuard.js',
  'utils/finalizationProtocol.js',
  'utils/literaryQualityEvaluator.js',
  'utils/localRevisionPatch.js',
  'utils/narrativeVoiceContract.js',
  'utils/plotThreadClassifier.js',
  'utils/projectHealthCheck.js',
  'utils/proseRhythmGuard.js',
  'utils/sceneExecutionContract.js',
  'utils/seedParser.js',
  'utils/settingChangeDedup.js',
  'utils/settingChangeRisk.js',
  'utils/settingEntityFilters.js',
  'utils/stateProvenance.js',
  'utils/storyBlockGranularity.js',
  'utils/storyBlockSnapshot.js',
  'utils/storyBlockStageSettlement.js',
  'views/WriterUnavailableView.vue',
  'views/WriterView.vue',
  'components/bible/CreativeBible.vue',
  'components/bible/CharacterArcView.vue',
  'components/bible/PlotThreadBoard.vue',
  'prompts/bibleFromSeed.js',
  'prompts/settingsFromBible.js',
]

const CANONICAL_RUNTIME = [
  'stores/bibleStore.js',
  'stores/chapterSessionStore.js',
  'stores/creationContractStore.js',
  'application/contracts/contractDocumentSections.js',
  'stores/planningStore.js',
  'application/writer/draftOperationCoordinator.js',
  'components/planning/PlanningWorkspace.vue',
  'components/planning/StoryBlockEditor.vue',
  'api/ai/providerPresets.js',
  'components/projects/NovelDownloadPanel.vue',
]

const CANONICAL_ROUTE_VIEWS = [
  'views/ProjectLibraryView.vue',
  'views/TopicCenterView.vue',
  'views/ArchivedProjectsView.vue',
  'views/ProjectOverviewView.vue',
  'views/ProjectSeedsView.vue',
  'views/ProjectContractView.vue',
  'views/ProjectBibleView.vue',
  'views/ProjectPlanningView.vue',
  'views/ManuscriptIndexView.vue',
  'views/FinalChapterReaderView.vue',
  'views/assets/StyleLibraryView.vue',
  'views/assets/ExperienceLibraryView.vue',
  'views/assets/CorpusLibraryView.vue',
  'views/ChapterWriterView.vue',
  'views/ProviderSettingsView.vue',
  'views/ApplicationSettingsView.vue',
  'views/ProjectModelSettingsView.vue',
  'views/ProjectExportView.vue',
  'views/NotFoundView.vue',
]

const PRESERVED_FUTURE_RUNTIME = [
  'components/project/ContractHeadSummary.vue',
  'components/project/WriterCoreStateCard.vue',
  'components/manuscript/ManuscriptSummaryLink.vue',
  'views/ArchivedProjectStatusView.vue',
]

test('planning foundation keeps one store, one workspace and the active story-block editor without outlines', async () => {
  const readSource = relativePath => readFile(
    path.join(sourceRoot, relativePath),
    'utf8',
  )
  const [client, store, workspace] = await Promise.all([
    readSource('api/db/client.js'),
    readSource('stores/planningStore.js'),
    readSource('components/planning/PlanningWorkspace.vue'),
  ])

  assert.doesNotMatch(client, /createInitial|planning\/initial/)
  assert.doesNotMatch(store, /createInitial|usePlanningStoreV2/)
  assert.doesNotMatch(workspace, /创建滚动规划|createInitial/)
  assert.match(workspace, /故事规划工作台/)
  assert.match(workspace, /完整规划摘要/)
  assert.match(workspace, /planning-load-failure/)
  assert.match(workspace, /重新加载/)
  assert.match(workspace, /v-else-if="!store\.state"/)
  assert.doesNotMatch(workspace, /useVolumeStore|usePlotStore/)
  assert.match(workspace, /StoryBlockEditor/)
  assert.doesNotMatch(workspace, /outlines|useStoryBlockStore/)
  await assert.rejects(
    access(path.join(sourceRoot, 'components/planning/PlanningWorkspaceV2.vue')),
  )
})

test('chapter writer has one exact-outline session path and no legacy StoryBlock creation input', async () => {
  const readSource = relativePath => readFile(
    path.join(sourceRoot, relativePath),
    'utf8',
  )
  const [client, store, writer, controller] = await Promise.all([
    readSource('api/db/client.js'),
    readSource('stores/chapterSessionStore.js'),
    readSource('views/ChapterWriterView.vue'),
    readSource('application/writer/chapterWriterController.js'),
  ])

  for (const [name, source] of [
    ['client', client],
    ['store', store],
    ['writer', writer],
  ]) {
    assert.doesNotMatch(
      source,
      /expectedStoryBlockRevision/,
      `${name} still carries the retired StoryBlock-only session command`,
    )
  }
  assert.doesNotMatch(writer, /planningStore|usePlanningStore/)
  assert.doesNotMatch(writer, /watch\(\s*workingDraft/)
  assert.match(writer, /createWorkingDraftAutosave/)
  assert.match(writer, /createChapterWriterController/)
  assert.match(controller, /createDraftOperationCoordinator/)
  assert.match(writer, /PlainTextDraftEditor/)
  assert.match(writer, /onBeforeRouteLeave\(async/)
  assert.match(writer, /onBeforeRouteUpdate\(async/)
  assert.doesNotMatch(writer, /chapterEditorState|createChapterEditorState|decideChapterNavigation/)
  assert.match(store, /const busy = computed\(/)
  assert.match(store, /const commandBusy = computed\(/)
  assert.match(store, /function assertWriteAvailable\(/)
  assert.match(writer, /请先完成并确认本章小纲/)
  assert.match(
    writer,
    /<n-button\s+v-if="!session"[\s\S]*?:disabled="true"/,
  )
  assert.match(
    writer,
    /watch\(\s*\(\)\s*=>\s*\[route\.params\.projectId,\s*route\.params\.chapterNumber\]/,
  )
  assert.doesNotMatch(client, /chapterSessions\/current|chapterSessions:\s*\{[\s\S]*?current:/)
  assert.doesNotMatch(client, /generateWorkingDraft|generate-working-draft/)
  assert.doesNotMatch(store, /generateWorkingDraft|generate-working-draft/)
  assert.doesNotMatch(writer, /chapterSessionStore\.generateWorkingDraft/)
  assert.match(store, /api\.chapterSessions\.createDraftOperation/)
  assert.match(store, /api\.chapterSessions\.readDraftOperation/)
  assert.match(store, /api\.chapterSessions\.listDraftOperationEvents/)
  assert.match(writer, /chapterSessionStore\.reloadCurrentWorkspace/)
  assert.equal((writer.match(/chapterSessionStore\.saveWorkingDraft/g) ?? []).length, 1)
  assert.match(store, /const chapterNumber = ref\(0\)/)
  assert.match(
    store,
    /api\.chapterSessions\.get\(\s*targetProjectId,\s*targetChapterNumber,/,
  )
  await assert.rejects(
    access(path.join(sourceRoot, 'views/ChapterWriterViewV2.vue')),
  )
})

const RETIRED_CROSS_RUNTIME_FILES = [
  'backend/routers/experience_cards.py',
  'backend/routers/control_plane_draft_writes.py',
  'backend/migrations/20260710_control_plane_draft_write_batches.sql',
  'backend/migrations/20260710_control_plane_draft_write_batches_rollback.sql',
  'backend/control_plane/__init__.py',
  'backend/control_plane/restricted_jcs.py',
  'backend/control_plane/draft_write_errors.py',
  'backend/control_plane/draft_write_models.py',
  'backend/control_plane/draft_write_repository.py',
  'backend/control_plane/draft_write_service.py',
  'backend/control_plane/draft_write_transaction.py',
  'backend/tests/control_plane/__init__.py',
  'backend/tests/control_plane/fakes.py',
  'backend/tests/control_plane/mysql_harness.py',
  'backend/tests/control_plane/mysql_integration_test.py',
  'backend/tests/control_plane/test_app.py',
  'backend/tests/control_plane/test_draft_write_migration.py',
  'backend/tests/control_plane/test_draft_write_models.py',
  'backend/tests/control_plane/test_draft_write_router.py',
  'backend/tests/control_plane/test_draft_write_service.py',
  'backend/tests/control_plane/test_draft_write_transaction.py',
  'backend/tests/control_plane/test_mysql_harness.py',
  'backend/tests/control_plane/test_provider_public_boundary.py',
  'backend/tests/control_plane/test_restricted_jcs.py',
  'backend/tests/control_plane/fixtures/control_plane_minimal_schema.sql',
  'tools/control-plane-qa/ai-proxy-gateway.mjs',
  'tools/control-plane-qa/restricted-jcs.mjs',
  'tools/control-plane-qa/fixtures/rfc8785-restricted-vectors.json',
  'tools/control-plane-qa/tests/ai-proxy-gateway.test.mjs',
  'tools/control-plane-qa/tests/provider-security.test.mjs',
  'tools/control-plane-qa/tests/restricted-jcs.test.mjs',
]

const RETIRED_CROSS_RUNTIME_TOKENS = [
  'experience_cards.py',
  'localwritingsamplereport.json',
  'samplemicrodemocards.v2_1.json',
  'samplemicrodemocards.v2_2.json',
  'control_plane',
  'control-plane',
  'rfc8785-restricted-vectors.json',
  'test:control-plane',
]

const CROSS_RUNTIME_ROOTS = ['backend', 'frontend/src', 'scripts', 'tools', 'package.json']
const CROSS_RUNTIME_SOURCE_EXTENSION = /\.(?:py|sql|js|mjs|cjs|ts|tsx|vue|json)$/u
const CROSS_RUNTIME_TEST_PATH = /^(?:backend\/tests|frontend\/tests|scripts\/tests|tools\/(?:.+\/)?tests)(?:\/|$)/u

const normalizedRelativePath = file => path
  .relative(sourceRoot, file)
  .split(path.sep)
  .join('/')

const repositoryPath = relativePath => path.join(
  repositoryRoot,
  ...relativePath.split('/'),
)

async function trackedProductionSources() {
  const result = spawnSync('git', ['ls-files', '-z', '--', ...CROSS_RUNTIME_ROOTS], {
    cwd: repositoryRoot,
    encoding: 'utf8',
    shell: false,
  })
  if (result.error || result.status !== 0) throw new Error('tracked source inventory failed')

  const paths = result.stdout.split('\0').filter(Boolean)
  const sources = []
  for (const relativePath of paths) {
    if (
      CROSS_RUNTIME_TEST_PATH.test(relativePath)
      || (relativePath !== 'package.json' && !CROSS_RUNTIME_SOURCE_EXTENSION.test(relativePath))
    ) continue
    try {
      sources.push([
        relativePath,
        await readFile(repositoryPath(relativePath), 'utf8'),
      ])
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
  }
  return sources
}

async function createInventoryServer() {
  return createServer({
    configFile: false,
    root: frontendRoot,
    resolve: {
      alias: {
        '@': sourceRoot,
      },
    },
    server: {
      middlewareMode: true,
      hmr: false,
      ws: false,
    },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin()],
    optimizeDeps: {
      noDiscovery: true,
    },
  })
}

async function sourceModulePaths(directory = sourceRoot) {
  const entries = await readdir(directory, { withFileTypes: true })
  const paths = await Promise.all(entries.map(entry => {
    const absolutePath = path.join(directory, entry.name)
    if (entry.isDirectory()) return sourceModulePaths(absolutePath)
    return /\.(?:js|vue)$/.test(entry.name) ? [absolutePath] : []
  }))
  return paths.flat()
}

async function loadProductionGraph() {
  const vite = await createInventoryServer()

  try {
    const { projectRoutes } = await import('../../src/router/projectRoutes.js')
    const activeFiles = new Set()
    const pending = ['/src/main.js']
    const visited = new Set()

    while (pending.length) {
      const url = pending.pop()
      if (visited.has(url)) continue
      visited.add(url)
      await vite.transformRequest(url)
      const module = await vite.moduleGraph.getModuleByUrl(url)
      if (!module) throw new Error(`Vite did not register ${url}`)
      if (module.file && path.resolve(module.file).startsWith(`${path.resolve(sourceRoot)}${path.sep}`)) {
        activeFiles.add(normalizedRelativePath(module.file))
      }
      for (const dependency of module.importedModules) {
        if (
          dependency.file
          && path.resolve(dependency.file).startsWith(`${path.resolve(sourceRoot)}${path.sep}`)
        ) {
          pending.push(dependency.url)
        }
      }
    }

    return { activeFiles, projectRoutes }
  } finally {
    await vite.close()
  }
}

async function loadAllSourceImporters() {
  const vite = await createInventoryServer()
  try {
    const importers = new Map()
    const files = await sourceModulePaths()
    for (const file of files) {
      const url = `/src/${normalizedRelativePath(file)}`
      await vite.transformRequest(url)
      const module = await vite.moduleGraph.getModuleByUrl(url)
      if (!module) throw new Error(`Vite did not register ${url}`)
      const importer = normalizedRelativePath(file)
      for (const dependency of module.importedModules) {
        if (
          dependency.file
          && path.resolve(dependency.file).startsWith(`${path.resolve(sourceRoot)}${path.sep}`)
        ) {
          const imported = normalizedRelativePath(dependency.file)
          const callers = importers.get(imported) ?? new Set()
          callers.add(importer)
          importers.set(imported, callers)
        }
      }
    }
    return importers
  } finally {
    await vite.close()
  }
}

test('production app and lazy route graph contain only canonical product destinations', async () => {
  const { activeFiles, projectRoutes } = await loadProductionGraph()

  assert.deepEqual(
    projectRoutes.map(route => [route.path, route.name]),
    CANONICAL_ROUTES,
  )
  assert.ok(activeFiles.has('App.vue'))
  assert.ok(activeFiles.has('router/projectRoutes.js'))
  for (const canonicalPath of [...CANONICAL_RUNTIME, ...CANONICAL_ROUTE_VIEWS]) {
    assert.ok(
      activeFiles.has(canonicalPath),
      `${canonicalPath} must remain reachable from the production app/route graph`,
    )
  }
  for (const retiredPath of RETIRED_RUNTIME) {
    assert.equal(
      activeFiles.has(retiredPath),
      false,
      `${retiredPath} is reachable from the production app/route graph`,
    )
  }
})

test('the proven-dead browser runtime is physically absent while provider presets remain', async () => {
  for (const retiredPath of RETIRED_RUNTIME) {
    await assert.rejects(access(path.join(sourceRoot, retiredPath)), retiredPath)
  }
  for (const canonicalPath of [...CANONICAL_RUNTIME, ...PRESERVED_FUTURE_RUNTIME]) {
    await access(path.join(sourceRoot, canonicalPath))
  }
})

test('every source caller of a retired module belongs to the same closed dead cluster', async () => {
  const retired = new Set(RETIRED_RUNTIME)
  const importers = await loadAllSourceImporters()
  const liveCallers = []

  for (const retiredPath of retired) {
    for (const caller of importers.get(retiredPath) ?? []) {
      if (!retired.has(caller)) liveCallers.push(`${caller} -> ${retiredPath}`)
    }
  }

  assert.deepEqual(liveCallers.sort(), [])
})

test('the only source modules outside the active graph are explicit future canonical surfaces', async () => {
  const [{ activeFiles }, files] = await Promise.all([
    loadProductionGraph(),
    sourceModulePaths(),
  ])
  const retired = new Set(RETIRED_RUNTIME)
  const preserved = new Set(PRESERVED_FUTURE_RUNTIME)
  const sourceFiles = files.map(normalizedRelativePath)
  const unexpectedInactive = sourceFiles
    .filter(file => !activeFiles.has(file) && !retired.has(file) && !preserved.has(file))

  assert.deepEqual(unexpectedInactive.sort(), [])
  for (const preservedPath of preserved) {
    assert.ok(sourceFiles.includes(preservedPath), `${preservedPath} must remain present`)
    assert.equal(activeFiles.has(preservedPath), false)
  }
})

test('retired cross-runtime control planes have no files, public entries, or production references', async () => {
  const existingFiles = []
  for (const relativePath of RETIRED_CROSS_RUNTIME_FILES) {
    try {
      await access(repositoryPath(relativePath))
      existingFiles.push(relativePath)
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
  }

  const packageValues = JSON.parse(await readFile(repositoryPath('package.json'), 'utf8'))
  const publicEntries = Object.keys(packageValues.scripts ?? {})
    .filter(name => name.startsWith('test:control-plane'))
  const productionReferences = []
  for (const [relativePath, source] of await trackedProductionSources()) {
    const searchable = `${relativePath}\n${source}`.toLowerCase()
    if (RETIRED_CROSS_RUNTIME_TOKENS.some(token => searchable.includes(token))) {
      productionReferences.push(relativePath)
    }
  }

  assert.deepEqual({
    existingFiles,
    productionReferences: [...new Set(productionReferences)].sort(),
    publicEntries: publicEntries.sort(),
  }, {
    existingFiles: [],
    productionReferences: [],
    publicEntries: [],
  })
})
