import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { readFile } from 'node:fs/promises'

import vuePlugin from '@vitejs/plugin-vue'
import { createSSRApp, ref } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
let vite
let component

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin()],
    optimizeDeps: { noDiscovery: true },
  })
  component = (await vite.ssrLoadModule('/src/components/projects/ProjectImportPanel.vue')).default
})

test.after(async () => { await vite?.close() })

async function render(controller) {
  return renderToString(createSSRApp(component, { controller }))
}

function controller(overrides = {}) {
  return {
    file: ref(new File(['private bytes'], '书稿备份.zip')),
    filename: ref('书稿备份.zip'),
    summary: ref({
      sourceTitle: '旧项目', proposedTitle: '旧项目（导入）',
      counts: {
        chapter: 12,
        'final-chapter': 7,
        asset: 3,
        'style-template': 5,
        'experience-card': 6,
      },
      hasFinalizedChapters: true, providerHistoryCount: 7,
      packageHash: 'private-package-hash', manifestHash: 'private-manifest-hash',
    }),
    title: ref('旧项目（导入）'),
    busy: ref(false), ready: ref(true), titleEditable: ref(true), error: ref(''),
    selectFile: async () => true, setTitle: () => true,
    importProject: async () => true, dispose: () => {},
    ...overrides,
  }
}

test('compact import panel uses only singular chapter and asset counts without subtype duplication', async () => {
  const html = await render(controller())
  assert.match(html, /导入项目备份/)
  assert.match(html, /书稿备份\.zip/)
  assert.match(html, /旧项目/)
  assert.match(html, />章节<\/dt><dd[^>]*>12<\/dd>/)
  assert.match(html, />素材<\/dt><dd[^>]*>3<\/dd>/)
  assert.equal((html.match(/>章节<\/dt>/g) || []).length, 1)
  assert.equal((html.match(/>素材<\/dt>/g) || []).length, 1)
  assert.match(html, /Provider Not Ready/)
  assert.match(html, /导入为新项目/)
  assert.match(html, /value="旧项目（导入）"/)
  assert.equal((html.match(/<button/g) || []).length, 1)
  assert.doesNotMatch(html, /private-package-hash|private-manifest-hash/)
})

test('panel exposes fixed error without payload preview or unsupported decisions', async () => {
  const html = await render(controller({ error: ref('项目导入失败，请重试。') }))
  assert.match(html, /role="alert"/)
  assert.match(html, /项目导入失败，请重试。/)
  assert.doesNotMatch(html, /合并|覆盖|目标项目|归档导入|选择 Provider|二次确认|取消|ZIP 内容|packageHash|manifestHash/)
})

test('chooser state has an accessible zip File boundary and no client preview', async () => {
  const html = await render(controller({
    file: ref(null), filename: ref(''), summary: ref(null), title: ref(''), ready: ref(false),
  }))
  assert.match(html, /type="file"/)
  assert.match(html, /accept="\.zip,application\/zip"/)
  assert.match(html, /选择项目备份/)
  assert.doesNotMatch(html, /导入为新项目/)

  const [panelSource, controllerSource] = await Promise.all([
    readFile(new URL('../../src/components/projects/ProjectImportPanel.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/application/project/projectImportController.js', import.meta.url), 'utf8'),
  ])
  assert.doesNotMatch(`${panelSource}\n${controllerSource}`, /FileReader|\.arrayBuffer\(|\.text\(|JSZip|zip\.js/)
})
