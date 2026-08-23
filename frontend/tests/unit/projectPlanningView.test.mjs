import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { parse as parseTemplate } from '@vue/compiler-dom'
import { createSSRApp, h, reactive } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const source = relativePath => readFile(
  new URL(`../../src/${relativePath}`, import.meta.url),
  'utf8',
)
const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const sourceRoot = fileURLToPath(new URL('../../src', import.meta.url))

async function createWriterVite() {
  return createServer({
    configFile: false,
    root: frontendRoot,
    resolve: { alias: { '@': sourceRoot } },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [
      {
        name: 'writer-candidate-render-stub',
        enforce: 'pre',
        transform(code, id) {
          if (!id.endsWith('ChapterWriterView.vue')) return null
          return code
            .replace(
              "import { computed, onBeforeUnmount, ref, watch } from 'vue'",
              "import { computed, h, onBeforeUnmount, ref, watch } from 'vue'",
            )
            .replace(
              /import\s*\{\s*onBeforeRouteLeave,[\s\S]*?\}\s*from 'vue-router'/u,
              "const useRoute = () => globalThis.__writerRoute; const useRouter = () => ({ push() {} }); const onBeforeRouteLeave = () => {}; const onBeforeRouteUpdate = () => {};",
            )
            .replace(
              /import\s*\{\s*NAlert,[\s\S]*?\}\s*from 'naive-ui'/u,
              "const container = tag => ({ inheritAttrs: false, setup(_, { attrs, slots }) { return () => h(tag, attrs, slots.default?.()) } }); const NAlert = container('section'); const NButton = container('button'); const NCard = container('section'); const NInput = container('textarea'); const NResult = container('section'); const NSkeleton = container('div'); const NStatistic = container('div'); const NTag = container('span');",
            )
            .replace(
              "import { useChapterSessionStore } from '@/stores/chapterSessionStore'",
              'const useChapterSessionStore = () => globalThis.__writerStore',
            )
            .replace(
              "import FinalizationPanel from '@/components/writer/FinalizationPanel.vue'",
              'const FinalizationPanel = { render: () => null }',
            )
            .replace('const loading = ref(true)', 'const loading = ref(false)')
            .replaceAll('loading.value = true', 'loading.value = false')
        },
      },
      vuePlugin(),
    ],
    optimizeDeps: { noDiscovery: true },
  })
}

async function renderWriterCandidates(candidates) {
  globalThis.__writerRoute = reactive({
    params: { projectId: 'project-1', chapterNumber: '1' },
  })
  globalThis.__writerStore = reactive({
    session: { chapterNum: 1, status: 'drafting' },
    workingDraft: { revision: 1 },
    candidates,
    hasSession: true,
    busy: false,
    writeBusy: false,
    generatingDraft: false,
    creating: false,
    savingDraft: false,
    savingCandidate: false,
    workspace: null,
    error: null,
    async openAuthoritative() { return null },
    invalidate() {},
  })
  const vite = await createWriterVite()
  try {
    const Writer = await vite.ssrLoadModule('/src/views/ChapterWriterView.vue')
    const app = createSSRApp(Writer.default)
    app.component('router-link', {
      setup(_, { attrs, slots }) {
        return () => h('a', attrs, slots.default?.())
      },
    })
    return await renderToString(app)
  } finally {
    await vite.close()
    delete globalThis.__writerRoute
    delete globalThis.__writerStore
  }
}
function hasPersistentOutlineLink(node, conditional = false) {
  if (!node || typeof node !== 'object') return false
  const nextConditional = conditional || (
    node.type === 1
    && node.props?.some(prop => (
      prop.type === 7 && ['if', 'else-if', 'else'].includes(prop.name)
    ))
  )
  if (
    node.type === 1
    && node.tag === 'router-link'
    && !nextConditional
    && node.props?.some(prop => (
      prop.type === 7
      && prop.name === 'bind'
      && prop.arg?.content === 'to'
      && prop.exp?.content === 'storyBlocksPath'
    ))
    && node.children?.some(child => (
      child.type === 2 && child.content.includes('调整本章小纲')
    ))
  ) return true
  return (node.children || []).some(child => (
    hasPersistentOutlineLink(child, nextConditional)
  ))
}

test('one project planning view hosts all three canonical tabs and the shared workspace', async () => {
  const [view, workspace, storyBlocks] = await Promise.all([
    source('views/ProjectPlanningView.vue'),
    source('components/planning/PlanningWorkspace.vue'),
    source('components/planning/StoryBlockEditor.vue'),
  ])

  assert.match(view, /ProjectPlanningVolumes/)
  assert.match(view, /ProjectPlanningPlots/)
  assert.match(view, /ProjectPlanningStoryBlocks/)
  assert.match(view, /<planning-workspace/)
  assert.match(view, /planningVolumesPath/)
  assert.match(view, /planningPlotsPath/)
  assert.match(view, /planningStoryBlocksPath/)
  assert.match(view, />\s*故事块\s*</)
  assert.match(workspace, /<volume-editor/)
  assert.match(workspace, /<plot-editor/)
  assert.match(workspace, /<story-block-editor/)
  assert.match(workspace, /activeTab === 'story-blocks'/)
  assert.match(workspace, /<planning-history-drawer/)
  assert.match(workspace, /只读流式模式/)
  assert.match(workspace, /完整规划摘要/)
  assert.match(workspace, /v-for="block in planningContent\.storyBlocks"/)
  assert.match(workspace, /volumeTitle\(block\.volumeRef\)/)
  assert.match(workspace, /plotTitles\(block\.plotRefs\)/)
  assert.doesNotMatch(workspace, /block\.plotRefs\?\.join/)
  assert.match(workspace, /stage\.sceneTasks/)
  assert.match(workspace, /createModalFocusManager/)
  assert.match(workspace, /trapTab/)
  assert.doesNotMatch(`${view}\n${workspace}\n${storyBlocks}`, /outlines|useStoryBlockStore/)
})

test('planning view owns one local aggregate and exact leave/load boundaries', async () => {
  const view = await source('views/ProjectPlanningView.vue')

  assert.match(view, /createPlanningWorkspaceController/)
  assert.match(view, /planningStore\.ensureLoaded/)
  assert.match(view, /onBeforeRouteLeave/)
  assert.match(view, /onBeforeRouteUpdate/)
  assert.match(view, /requestRouteLeave/)
  assert.match(view, /beforeunload/)
  assert.match(view, /useAppMessage/)
  assert.match(view, /message\.success/)
  assert.match(
    view,
    /onBeforeRouteLeave\(to => controller\.requestRouteLeave\(to\)\)/,
  )
  assert.match(
    view,
    /onBeforeRouteUpdate\(to => controller\.requestRouteLeave\(to\)\)/,
  )
  assert.doesNotMatch(view, /sameProjectPlanningRoute|requestPlanningRouteLeave/)
  assert.doesNotMatch(
    view,
    /useVolumeStore|usePlotStore|useStoryBlockStore|PlanningWorkspaceV2/,
  )
})

test('history is immutable and retired duplicate planning surfaces stay absent', async () => {
  const history = await source('components/planning/PlanningHistoryDrawer.vue')

  assert.match(history, /只读/)
  assert.doesNotMatch(history, /@(?:click|input|change)[^>\n]*(?:clone|edit|save)/)
  assert.doesNotMatch(history, /emit\(['"](?:clone|edit|save)/)
  for (const retired of [
    'components/planning/PlanningWorkspaceV2.vue',
    'stores/volumeStore.js',
    'stores/plotStore.js',
  ]) {
    await assert.rejects(access(new URL(`../../src/${retired}`, import.meta.url)))
  }
})

test('writer keeps the outline router link visible while the workspace loads', async () => {
  const writer = await source('views/ChapterWriterView.vue')
  const template = writer.match(/<template>([\s\S]*)<\/template>/u)?.[1]
  const ast = parseTemplate(template || '')

  assert.equal(hasPersistentOutlineLink(ast), true)
})

test('writer renders current and stale candidate basis badges', async () => {
  const html = await renderWriterCandidates([
    {
      id: 'candidate-current',
      workingDraftRevision: 1,
      basisStatus: 'current',
      content: '当前候选',
      contentHash: 'a'.repeat(64),
      createdAt: 1_700_000_000_000,
    },
    {
      id: 'candidate-stale',
      workingDraftRevision: 2,
      basisStatus: 'stale',
      content: '旧依据候选',
      contentHash: 'b'.repeat(64),
      createdAt: 1_700_000_001_000,
    },
  ])

  assert.match(
    html,
    /候选 1[\s\S]*?<span class="candidate-basis candidate-basis--current"[^>]*>依据当前小纲<\/span>[\s\S]*?4 字 · aaaaaaaa/,
  )
  assert.match(
    html,
    /候选 2[\s\S]*?<span class="candidate-basis candidate-basis--stale"[^>]*>依据旧小纲，不能定稿<\/span>[\s\S]*?5 字 · bbbbbbbb/,
  )
})

test('planning editors expose only their owned fields and no reverse IDs', async () => {
  const [volume, plot, storyBlock] = await Promise.all([
    source('components/planning/VolumeEditor.vue'),
    source('components/planning/PlotEditor.vue'),
    source('components/planning/StoryBlockEditor.vue'),
  ])

  for (const field of [
    'title', 'coreChange', 'mainPressure', 'ensembleFocus', 'forbiddenEvents',
  ]) {
    assert.match(volume, new RegExp(field))
  }
  assert.doesNotMatch(volume, /plotRefs|plotIds|storyBlock/i)

  for (const field of [
    'title', 'plotType', 'storyQuestion', 'futureDirection',
    'expectedPayoff', 'relatedCharacters',
  ]) {
    assert.match(plot, new RegExp(field))
  }
  for (const plotType of ['main', 'character', 'relationship', 'conflict', 'mystery', 'other']) {
    assert.match(plot, new RegExp(`value="${plotType}"`))
  }
  assert.doesNotMatch(plot, /value="(?:growth|world)"/)
  assert.doesNotMatch(plot, /storyBlock/i)

  for (const field of [
    'title', 'volumeRef', 'plotRefs', 'entrySituation', 'blockGoal',
    'mainPressure', 'expectedChange', 'openQuestions', 'involvedCharacters',
    'purpose', 'dramaticQuestion', 'task', 'completionEvidence',
  ]) {
    assert.match(storyBlock, new RegExp(field))
  }
  assert.doesNotMatch(
    storyBlock,
    /targetChapterCount|completed|actualProgress|volumeId|plotIds|storyBlockId|stageId/,
  )
  assert.match(storyBlock, /emit\('add'/)
  assert.match(storyBlock, /emit\('remove'/)
  assert.match(storyBlock, /emit\('move'/)
  assert.match(storyBlock, /emit\('select'/)
  assert.match(storyBlock, /emit\('undo'/)
  assert.match(storyBlock, /emit\('add-stage'/)
  assert.match(storyBlock, /emit\('add-scene-task'/)
})
