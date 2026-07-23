import assert from 'node:assert/strict'
import { access, readdir } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const sourceRoot = path.join(frontendRoot, 'src')

const CANONICAL_ROUTES = [
  ['/', undefined],
  ['/projects', 'ProjectLibrary'],
  ['/projects/archived', 'ArchivedProjects'],
  ['/assets/styles', 'StyleLibrary'],
  ['/assets/experience', 'ExperienceLibrary'],
  ['/assets/corpus', 'CorpusLibrary'],
  ['/projects/:projectId/overview', 'ProjectOverview'],
  ['/projects/:projectId/settings/models', 'ProjectModelSettings'],
  ['/projects/:projectId/seeds', 'ProjectSeeds'],
  ['/projects/:projectId/contract', 'ProjectContract'],
  ['/projects/:projectId/bible', 'ProjectBible'],
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
  'stores/planningStore.js',
  'api/ai/providerPresets.js',
]

const CANONICAL_ROUTE_VIEWS = [
  'views/ProjectLibraryView.vue',
  'views/ArchivedProjectsView.vue',
  'views/ProjectOverviewView.vue',
  'views/ProjectSeedsView.vue',
  'views/ProjectContractView.vue',
  'views/ProjectBibleView.vue',
  'views/assets/StyleLibraryView.vue',
  'views/assets/ExperienceLibraryView.vue',
  'views/assets/CorpusLibraryView.vue',
  'views/ChapterWriterView.vue',
  'views/ProviderSettingsView.vue',
  'views/ApplicationSettingsView.vue',
  'views/ProjectModelSettingsView.vue',
  'views/NotFoundView.vue',
]

const PRESERVED_FUTURE_RUNTIME = [
  'components/planning/PlanningWorkspace.vue',
  'components/project/ContractHeadSummary.vue',
  'components/project/WriterCoreStateCard.vue',
]

const normalizedRelativePath = file => path
  .relative(sourceRoot, file)
  .split(path.sep)
  .join('/')

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

test('production app and lazy route graph contain only canonical Phase 2 destinations', async () => {
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
