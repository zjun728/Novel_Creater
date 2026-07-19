import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createPinia, setActivePinia } from 'pinia'
import { createSSRApp, defineComponent, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

import { useCreationAssetStore } from '../../src/stores/creationAssetStore.js'


const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveUiStubId = '\0creative-asset-naive-ui-stub'
const naiveUiStubPlugin = {
  name: 'creative-asset-naive-ui-stub',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveUiStubId
  },
  load(id) {
    if (id !== naiveUiStubId) return undefined
    return `
      import { defineComponent, h } from 'vue'
      const stub = (name, tag = 'div') => defineComponent({
        name,
        inheritAttrs: false,
        setup(_, { attrs, slots }) {
          return () => h(tag, attrs, [
            slots.default?.(),
            slots.action?.(),
            slots.header?.(),
            slots.footer?.(),
          ])
        },
      })
      export const NAlert = stub('NAlert', 'aside')
      export const NButton = stub('NButton', 'button')
      export const NDrawer = stub('NDrawer', 'aside')
      export const NDrawerContent = stub('NDrawerContent', 'section')
      export const NEmpty = stub('NEmpty', 'div')
      export const NInput = stub('NInput', 'input')
      export const NSelect = stub('NSelect', 'select')
      export const NSkeleton = stub('NSkeleton')
      export const NSpin = stub('NSpin')
      export const NTag = stub('NTag', 'span')
    `
  },
}

let vite
let StyleLibraryView
let ExperienceLibraryView
let AssetDetailDrawer

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('../../src', import.meta.url)),
      },
    },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin(), naiveUiStubPlugin],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  StyleLibraryView = (
    await vite.ssrLoadModule('/src/views/assets/StyleLibraryView.vue')
  ).default
  ExperienceLibraryView = (
    await vite.ssrLoadModule('/src/views/assets/ExperienceLibraryView.vue')
  ).default
  AssetDetailDrawer = (
    await vite.ssrLoadModule('/src/components/assets/AssetDetailDrawer.vue')
  ).default
})

test.after(async () => {
  await vite?.close()
})

async function renderView(component, state) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useCreationAssetStore()
  store.$patch(state)
  const app = createSSRApp(component)
  app.use(pinia)
  app.component('RouterLink', defineComponent({
    props: { to: { type: String, required: true } },
    setup(props, { slots, attrs }) {
      return () => h('a', { ...attrs, href: props.to }, slots.default?.())
    },
  }))
  return renderToString(app)
}

const inventory = {
  assetPackageVersion: 'writer-core-test-v9',
  taxonomyPackageVersion: 'recommendation-taxonomy-test-v3',
  styleCount: 10,
  experienceCardCount: 64,
  categories: ['dialogue'],
  genres: ['general'],
  channels: ['all'],
  creationStages: ['drafting'],
  writingPurposes: ['dialogue', 'style_direction'],
  prohibitedDirections: ['slow_burn'],
  statuses: ['active', 'archived'],
}

test('style library renders backend inventory, filters, and a read-only result', async () => {
  const html = await renderView(StyleLibraryView, {
    inventory,
    styleTemplates: [{
      id: 'style-1',
      stableKey: 'direct-propulsive',
      revision: 1,
      contentHash: 'a'.repeat(64),
      name: '直接推进型',
      readingExperience: '清晰而有推进力',
      applicability: ['长篇推进'],
      nonApplicability: ['静态资料'],
      eligibility: {
        genres: ['general'],
        channels: ['all'],
        creationStages: ['drafting'],
        writingPurposes: ['style_direction'],
        prohibitedDirections: [],
      },
    }],
    loadingStyles: false,
    styleError: '',
    inventoryError: '',
  })

  assert.match(html, /风格模板库/)
  assert.match(html, /writer-core-test-v9/)
  assert.match(html, />10</)
  assert.match(html, /直接推进型/)
  assert.match(html, /搜索风格/)
  assert.match(html, /题材|阶段|状态/)
  assert.doesNotMatch(html, /激活|发布|上架|审核/)
})

test('experience library renders backend count and explicit empty/error recovery', async () => {
  const empty = await renderView(ExperienceLibraryView, {
    inventory,
    experienceCards: [],
    loadingCards: false,
    cardError: '',
    inventoryError: '',
  })
  const failed = await renderView(ExperienceLibraryView, {
    inventory,
    experienceCards: [],
    loadingCards: false,
    cardError: '目录暂时不可用',
    inventoryError: '',
  })

  assert.match(empty, /经验卡库/)
  assert.match(empty, /recommendation-taxonomy-test-v3/)
  assert.match(empty, />64</)
  assert.match(empty, /没有匹配的经验卡/)
  assert.match(failed, /目录暂时不可用/)
  assert.match(failed, /重试/)
})

test('bounded detail drawer names the approved style and experience boundaries', async () => {
  const styleApp = createSSRApp({
    render: () => h(AssetDetailDrawer, {
      show: true,
      kind: 'style',
      detail: {
        name: '直接推进型',
        stableKey: 'direct-propulsive',
        revision: 1,
        payload: {
          approvedExample: '风格批准示例',
          completeUseExample: '完整应用示例',
          applicability: ['适用边界'],
          nonApplicability: ['不适用边界'],
          preferredTechniques: ['推荐写法'],
          risks: ['常见风险'],
        },
      },
    }),
  })
  const styleHtml = await renderToString(styleApp)
  const cardApp = createSSRApp({
    render: () => h(AssetDetailDrawer, {
      show: true,
      kind: 'experience',
      detail: {
        title: '围着真正需求讨价还价',
        stableKey: 'dialogue-bargain-real-need',
        revision: 1,
        payload: {
          method: '经验方法',
          positiveExample: '正向示例',
          negativeExamples: ['反例边界'],
          usage: ['使用场景'],
          nonApplicability: ['不使用场景'],
          risks: ['风险'],
        },
      },
    }),
  })
  const cardHtml = await renderToString(cardApp)

  assert.match(styleHtml, /批准示例|风格批准示例/)
  assert.match(styleHtml, /适用边界/)
  assert.match(styleHtml, /不适用边界/)
  assert.match(cardHtml, /方法/)
  assert.match(cardHtml, /正向示例/)
  assert.match(cardHtml, /反向示例|不适用/)
  assert.match(cardHtml, /使用范围|使用场景/)
})

test('canonical pages derive counts and versions without local constants', async () => {
  const sources = await Promise.all([
    readFile(new URL('../../src/views/assets/StyleLibraryView.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/views/assets/ExperienceLibraryView.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/assets/AssetDetailDrawer.vue', import.meta.url), 'utf8'),
  ])
  const combined = sources.join('\n')

  assert.doesNotMatch(
    combined,
    /writer-core-v1\.1\.0|EXPECTED_STYLE_COUNT|EXPECTED_CARD_COUNT|localStorage/,
  )
  assert.doesNotMatch(combined, /experienceCardProduct|realCorpusExperienceCards/)
})
