import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { computed, createSSRApp, h, ref, shallowRef } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'


const source = path => readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')

const root = fileURLToPath(new URL('../..', import.meta.url))
const naiveStubId = '\0finalization-panel-naive-stub'
const naiveStub = {
  name: 'finalization-panel-naive-stub',
  enforce: 'pre',
  resolveId: id => id === 'naive-ui' ? naiveStubId : undefined,
  load: id => id === naiveStubId ? `
    import { defineComponent, h } from 'vue'
    const children = slots => Object.values(slots).flatMap(slot => slot?.() || [])
    const stub = name => defineComponent({ name, setup(_, { attrs, slots }) { return () => h('div', attrs, children(slots)) } })
    export const NAlert = stub('NAlert')
    export const NCard = stub('NCard')
    export const NInput = stub('NInput')
    export const NTag = stub('NTag')
    export const NButton = defineComponent({ name: 'NButton', setup(_, { attrs, slots }) { return () => h('button', attrs, children(slots)) } })
  ` : undefined,
}

let vite
let FinalizationPanel
test.before(async () => {
  vite = await createServer({
    configFile: false,
    root,
    appType: 'custom',
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false, ws: false },
    plugins: [vuePlugin(), naiveStub],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  FinalizationPanel = (await vite.ssrLoadModule(
    '/src/components/writer/FinalizationPanel.vue',
  )).default
})
test.after(async () => { await vite?.close() })


test('Writer embeds one compact author-controlled finalization panel', async () => {
  const [view, panel] = await Promise.all([
    source('views/ChapterWriterView.vue'),
    source('components/writer/FinalizationPanel.vue'),
  ])

  assert.match(view, /components\/writer\/FinalizationPanel\.vue/)
  assert.match(view, /createFinalizationController/)
  assert.match(view, /<finalization-panel/)
  assert.match(view, /:planning-content="planningContent"/)
  assert.match(view, /finalization\.reset\(\)/)
  assert.match(view, /finalization\.load\(\)/)
  assert.match(view, /finalization\.dispose\(\)/)
  assert.match(view, /editorReadonly[\s\S]*finalization\.finalized\.value/)

  for (const label of [
    '审查并定稿', '确定性阻断', '质量建议', 'Canon 事实',
    '故事进度', '未来规划调整', '保存修正', '确认以上变更', '定稿本章',
    '放弃审查并返回修改',
  ]) assert.match(panel, new RegExp(label))
  assert.match(panel, /controller\.prepareCandidate/)
  assert.match(panel, /controller\.correctChangeSet/)
  assert.match(panel, /controller\.confirmChangeSet/)
  assert.match(panel, /controller\.commitChapter/)
  assert.match(panel, /controller\.cancelReview/)
  assert.match(panel, /planningContent/)
  assert.match(panel, /targetLabel\(item\)/)
  assert.doesNotMatch(panel, /item\.targetType\s*}}\s*·\s*{{\s*item\.targetId/)
  assert.match(panel, /previousCandidateIds/)
  assert.match(panel, /review\?\.status === 'failed'/)
  assert.match(panel, /审查未完成，正文和候选稿未受影响/)
  assert.equal(
    panel.match(/v-if="controller\.primaryAction\.value === 'confirm'"/g)?.length,
    2,
  )
  assert.doesNotMatch(
    panel,
    /v-else-if="controller\.primaryAction\.value === 'confirm'"/,
  )
  assert.doesNotMatch(panel, /通过分数|及格分|自动修复|自动定稿|partial approval/i)
  assert.doesNotMatch(panel, /<textarea[^>]*json|page\.request|page\.route|fetch\(|axios|page\.evaluate/i)
})


test('the panel renders evidence without exposing full candidate prose', async () => {
  const panel = await source('components/writer/FinalizationPanel.vue')

  assert.match(panel, /startScalar/)
  assert.match(panel, /endScalar/)
  assert.doesNotMatch(panel, /candidate\.content|workingDraft\.content|rawProvider|prompt|apiKey|dsn/i)
})


test('finalized panel stays in place and offers only verified explicit navigation', async () => {
  const panel = await source('components/writer/FinalizationPanel.vue')

  assert.match(panel, /controller\.postFinalization\.value/)
  assert.match(panel, /postFinalization\.currentAction\.state === 'available'/)
  assert.match(panel, /:to="postFinalization\.currentAction\.targetPath"/)
  assert.match(panel, /\{\{ postFinalization\.currentAction\.label \}\}/)
  assert.match(panel, /postFinalization\?\.finalizedChapterReadable/)
  assert.match(panel, /:to="postFinalization\.finalizedChapterPath"/)
  assert.match(panel, /查看本章定稿/)
  assert.match(panel, /controller\.refreshPostFinalization/)
  assert.match(panel, /:disabled="controller\.postBusy\.value"/)
  assert.match(panel, /v-if="!postFinalization"[\s\S]*正在读取定稿后的创作状态/)
  assert.match(panel, /currentAction\.state === 'archived'[\s\S]*项目当前为只读状态/)
  assert.match(panel, /\.panel-intro[^}]*color:\s*#675d51/)
  assert.match(panel, /\.finalized-action--primary span[^}]*color:\s*#675d51/)
  assert.match(panel, /\.muted[^}]*color:\s*#6f6559/)
  assert.doesNotMatch(panel, /未实现内容|router\.push|router\.replace|window\.location/)
})


test('finalized panel renders a loading state while post-commit refresh is pending', async () => {
  const controller = {
    review: shallowRef({ status: 'committed' }),
    result: shallowRef({ chapterNumber: 4 }),
    postFinalization: shallowRef(null),
    postBusy: computed(() => false),
    busy: computed(() => true),
    error: ref(''),
    hardBlocks: computed(() => []),
    finalized: computed(() => true),
    primaryAction: computed(() => 'done'),
    refreshPostFinalization: async () => {},
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { render: () => h('div') } }],
  })
  await router.push('/')
  await router.isReady()
  const app = createSSRApp(FinalizationPanel, { controller })
  app.use(router)

  const html = await renderToString(app)

  assert.match(html, /本章已定稿/)
  assert.match(html, /正在读取定稿后的创作状态/)
  assert.doesNotMatch(html, /项目当前为只读状态|重新读取创作状态/)
})
