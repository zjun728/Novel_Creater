<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NEmpty,
  NModal,
  NSkeleton,
  NSpin,
  NTag,
} from 'naive-ui'

import { useCorpusStore } from '@/stores/corpusStore'

const PREVIEW_ITEM_LIMIT = 240
const PREVIEW_PAGE_BUDGET = 4_800
const DISCOVERY_LIMIT = 100

const corpusStore = useCorpusStore()
const rootStatus = ref('checking')
const workspaceLoading = ref(false)
const loadError = ref('')
const importErrors = ref({})
const importingPaths = ref({})
const activeImportIds = ref({})
const importKeys = new Map()
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const sourceDetail = ref(null)
const sourceChapters = ref([])
const activeChapter = ref(null)
let detailEpoch = 0
let chapterEpoch = 0

const discoveryItems = computed(() => (corpusStore.discovery?.items || [])
  .filter(item => isSafeRelativePath(item.relativePath)))
const safeSources = computed(() => corpusStore.sources
  .filter(source => isSafeRelativePath(source.relativePath)))
const importRuns = computed(() => Object.values(corpusStore.importRuns)
  .filter(run => isSafeRelativePath(run.relativePath))
  .sort((left, right) => String(right.importId).localeCompare(String(left.importId))))
const sourcePreview = computed(() => boundedPreview(sourceDetail.value?.preview))
const visibleFragments = computed(() => {
  let remaining = Math.max(0, PREVIEW_PAGE_BUDGET - sourcePreview.value.length)
  const rows = []
  for (const fragment of (corpusStore.fragmentPage?.items || []).slice(0, 20)) {
    if (remaining <= 0) break
    const preview = boundedPreview(fragment.preview, Math.min(PREVIEW_ITEM_LIMIT, remaining))
    remaining -= preview.length
    rows.push({ ...fragment, preview })
  }
  return rows
})
const displayedPreviewCharacters = computed(() => (
  sourcePreview.value.length
  + visibleFragments.value.reduce((total, fragment) => total + fragment.preview.length, 0)
))

function boundedPreview(value, limit = PREVIEW_ITEM_LIMIT) {
  return String(value || '').slice(0, Math.min(PREVIEW_ITEM_LIMIT, Math.max(0, limit)))
}

function shortHash(value) {
  return String(value || '').slice(0, 12)
}

function isSafeRelativePath(value) {
  const relativePath = String(value || '').trim()
  const segments = relativePath.split(/[\\/]+/u)
  return Boolean(
    relativePath
    && !/^[\\/]/u.test(relativePath)
    && !/^[a-z][a-z0-9+.-]*:/iu.test(relativePath)
    && !segments.some(segment => segment === '.' || segment === '..'),
  )
}

function publicMessage(error, fallback) {
  return error?.message || fallback
}

function newImportKey(relativePath) {
  if (importKeys.has(relativePath)) return importKeys.get(relativePath)
  const random = globalThis.crypto?.randomUUID?.().toLowerCase()
    || `corpus-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 18)}`
  importKeys.set(relativePath, random)
  return random
}

function importedSource(relativePath) {
  return safeSources.value.find(source => source.relativePath === relativePath) || null
}

function latestImportRun(relativePath) {
  const activeId = activeImportIds.value[relativePath]
  if (activeId && corpusStore.importRuns[activeId]) return corpusStore.importRuns[activeId]
  const runs = Object.values(corpusStore.importRuns)
  for (let index = runs.length - 1; index >= 0; index -= 1) {
    if (runs[index].relativePath === relativePath) return runs[index]
  }
  return null
}

function importStatus(relativePath) {
  return latestImportRun(relativePath)?.status || ''
}

function importActionLabel(relativePath) {
  const status = importStatus(relativePath)
  if (status === 'failed') return '重新导入'
  if (status === 'reserved' || status === 'running') return '读取同一命令'
  return '导入此文件'
}

function statusLabel(status) {
  return {
    reserved: '已受理',
    running: '处理中',
    succeeded: '已导入',
    failed: '失败',
  }[status] || status || '未导入'
}

function statusType(status) {
  if (status === 'succeeded') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'running' || status === 'reserved') return 'warning'
  return 'default'
}

async function loadWorkspace() {
  workspaceLoading.value = true
  rootStatus.value = 'checking'
  loadError.value = ''
  try {
    await corpusStore.loadSources()
  } catch (error) {
    loadError.value = publicMessage(error, '已导入语料列表加载失败')
  }

  try {
    await corpusStore.discover({ limit: DISCOVERY_LIMIT })
    rootStatus.value = 'configured'
  } catch (error) {
    if (error?.code === 'CorpusRequestInvalid') {
      rootStatus.value = 'not-configured'
    } else {
      rootStatus.value = 'error'
      if (!loadError.value) loadError.value = publicMessage(error, '本机语料发现失败')
    }
  } finally {
    workspaceLoading.value = false
  }
}

async function importDiscovered(item) {
  if (!item?.relativePath || importingPaths.value[item.relativePath]) return
  const relativePath = item.relativePath
  const priorRun = latestImportRun(relativePath)
  if (priorRun?.status === 'failed') importKeys.delete(relativePath)
  importingPaths.value = { ...importingPaths.value, [relativePath]: true }
  importErrors.value = { ...importErrors.value, [relativePath]: '' }
  try {
    const result = await corpusStore.importSource({
      idempotencyKey: newImportKey(relativePath),
      relativePath,
    })
    if (result?.importId) {
      activeImportIds.value = { ...activeImportIds.value, [relativePath]: result.importId }
    }
    if (result?.status === 'succeeded') await corpusStore.loadSources()
  } catch (error) {
    if (error?.code === 'CorpusImportFailed') importKeys.delete(relativePath)
    importErrors.value = {
      ...importErrors.value,
      [relativePath]: publicMessage(error, '语料导入失败'),
    }
  } finally {
    importingPaths.value = { ...importingPaths.value, [relativePath]: false }
  }
}

async function refreshImport(run) {
  if (!run?.importId) return
  try {
    const result = await corpusStore.getImport(run.importId)
    if (result?.importId) {
      activeImportIds.value = { ...activeImportIds.value, [run.relativePath]: result.importId }
    }
    if (result?.status === 'succeeded') await corpusStore.loadSources()
  } catch (error) {
    importErrors.value = {
      ...importErrors.value,
      [run.relativePath]: publicMessage(error, '导入状态读取失败'),
    }
  }
}

async function openSource(source) {
  const epoch = ++detailEpoch
  chapterEpoch += 1
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = ''
  sourceDetail.value = null
  sourceChapters.value = []
  activeChapter.value = null
  corpusStore.clearFragments()
  try {
    const [detail, chapters] = await Promise.all([
      corpusStore.getSource(source.id, source.revision, source.contentHash),
      corpusStore.loadChapters(source.id, source.revision, source.contentHash),
    ])
    if (epoch !== detailEpoch) return
    if (!isSafeRelativePath(detail.relativePath)) {
      throw new Error('语料来源标识无效，请重新加载')
    }
    sourceDetail.value = detail
    sourceChapters.value = chapters
  } catch (error) {
    if (epoch === detailEpoch) detailError.value = publicMessage(error, '语料安全预览加载失败')
  } finally {
    if (epoch === detailEpoch) detailLoading.value = false
  }
}

async function loadChapterFragments(chapter) {
  const epoch = ++chapterEpoch
  activeChapter.value = chapter
  detailError.value = ''
  try {
    await corpusStore.loadFragments(chapter.id, { cursor: 0, limit: 20 })
  } catch (error) {
    if (epoch === chapterEpoch) {
      detailError.value = publicMessage(error, '章节片段加载失败')
    }
  }
}

async function loadNextFragmentPage() {
  const cursor = corpusStore.fragmentPage?.nextCursor
  if (!activeChapter.value || cursor === null || cursor === undefined) return
  const epoch = chapterEpoch
  const chapterId = activeChapter.value.id
  detailError.value = ''
  try {
    await corpusStore.loadFragments(chapterId, { cursor, limit: 20 })
  } catch (error) {
    if (epoch === chapterEpoch && activeChapter.value?.id === chapterId) {
      detailError.value = publicMessage(error, '下一页片段加载失败')
    }
  }
}

onMounted(loadWorkspace)
</script>

<template>
  <section class="corpus-ledger" aria-labelledby="corpus-settings-heading">
    <header class="ledger-heading">
      <div>
        <p>LOCAL CORPUS REGISTER</p>
        <h3 id="corpus-settings-heading">本机语料册</h3>
        <span>只发现配置目录里的相对文件，并保存可追溯的不可变修订。</span>
      </div>
      <n-tag
        :type="rootStatus === 'configured' ? 'success' : (rootStatus === 'not-configured' ? 'warning' : 'default')"
        round
        :bordered="false"
      >
        {{ rootStatus === 'configured' ? '语料根目录已配置' : (rootStatus === 'not-configured' ? '语料根目录未配置' : '正在检查配置') }}
      </n-tag>
    </header>

    <n-alert type="info" :bordered="false" class="privacy-note">
      页面不显示本机根目录，也不接受手工路径。只能从后端返回的相对文件清单发起导入。
    </n-alert>
    <n-alert v-if="rootStatus === 'not-configured'" type="warning" class="state-alert">
      尚未配置本机语料根目录。完成本机配置并重启后端后，再从这里发现可导入的文本文件。
    </n-alert>
    <n-alert v-if="loadError" type="error" class="state-alert">
      {{ loadError }}
      <template #action><n-button size="small" @click="loadWorkspace">重新加载</n-button></template>
    </n-alert>

    <template v-if="workspaceLoading">
      <div class="loading-grid" aria-busy="true" aria-label="正在读取本机语料状态">
        <n-skeleton height="120px" />
        <n-skeleton height="120px" />
      </div>
    </template>

    <template v-else>
      <section class="register-section" aria-labelledby="discovery-heading">
        <div class="section-heading">
          <div>
            <p>DISCOVERY</p>
            <h4 id="discovery-heading">可导入的相对文件</h4>
          </div>
          <span v-if="corpusStore.discovery">{{ corpusStore.discovery.scanStrategy }} · {{ discoveryItems.length }} 项</span>
        </div>

        <n-empty v-if="!discoveryItems.length" description="没有发现可展示的文本文件" class="empty-state" />
        <div v-else class="discovery-list">
          <article v-for="item in discoveryItems" :key="item.relativePath" class="discovery-row">
            <div class="file-mark" aria-hidden="true">TXT</div>
            <div class="file-main">
              <strong>{{ item.relativePath }}</strong>
              <span>{{ item.byteSize.toLocaleString() }} bytes · {{ item.preflightStatus }}</span>
              <small v-if="importErrors[item.relativePath]" role="alert">{{ importErrors[item.relativePath] }}</small>
            </div>
            <n-tag v-if="importedSource(item.relativePath)" type="success" size="small">已入库</n-tag>
            <n-tag v-else-if="importStatus(item.relativePath)" :type="statusType(importStatus(item.relativePath))" size="small">
              {{ statusLabel(importStatus(item.relativePath)) }}
            </n-tag>
            <n-button
              size="small"
              :loading="Boolean(importingPaths[item.relativePath])"
              :disabled="item.preflightStatus !== 'eligible' || Boolean(importedSource(item.relativePath))"
              @click="importDiscovered(item)"
            >{{ importedSource(item.relativePath) ? '已导入' : importActionLabel(item.relativePath) }}</n-button>
          </article>
        </div>
      </section>

      <section v-if="importRuns.length" class="register-section" aria-labelledby="import-runs-heading">
        <div class="section-heading">
          <div>
            <p>IMPORT COMMANDS</p>
            <h4 id="import-runs-heading">幂等导入状态</h4>
          </div>
          <span>状态刷新不会重复创建导入命令</span>
        </div>
        <div class="run-list">
          <article v-for="run in importRuns" :key="run.importId" class="run-row">
            <div>
              <strong>{{ run.relativePath }}</strong>
              <span>{{ run.importId }} · {{ run.shortHash || '尚无摘要' }}</span>
            </div>
            <n-tag :type="statusType(run.status)" size="small">{{ statusLabel(run.status) }}</n-tag>
            <n-button
              v-if="run.status === 'reserved' || run.status === 'running'"
              size="tiny"
              secondary
              @click="refreshImport(run)"
            >刷新状态</n-button>
          </article>
        </div>
      </section>

      <section class="register-section" aria-labelledby="sources-heading">
        <div class="section-heading">
          <div>
            <p>IMPORTED SOURCES</p>
            <h4 id="sources-heading">已导入语料修订</h4>
          </div>
          <span>{{ safeSources.length }} 个来源</span>
        </div>

        <n-empty v-if="!safeSources.length" description="尚无已导入语料" class="empty-state" />
        <div v-else class="source-grid">
          <article v-for="source in safeSources" :key="source.id" class="source-card">
            <div class="source-topline">
              <n-tag size="small" :type="source.state === 'analyzed' ? 'success' : 'default'">
                {{ source.state }}
              </n-tag>
              <code>{{ source.shortHash }}</code>
            </div>
            <h5>{{ source.name }}</h5>
            <p>{{ source.relativePath }}</p>
            <dl>
              <div><dt>修订</dt><dd>r{{ source.revision }}</dd></div>
              <div><dt>编码</dt><dd>{{ source.encoding }}</dd></div>
              <div><dt>章节</dt><dd>{{ source.chapterCount }}</dd></div>
              <div><dt>片段</dt><dd>{{ source.fragmentCount }}</dd></div>
            </dl>
            <n-button size="small" secondary @click="openSource(source)">打开有界预览</n-button>
          </article>
        </div>
      </section>
    </template>

    <n-modal v-model:show="detailOpen" preset="card" title="语料有界预览" style="width: min(960px, 95vw)">
      <n-spin :show="detailLoading || corpusStore.loadingFragments">
        <n-alert v-if="detailError" type="error" class="state-alert">{{ detailError }}</n-alert>
        <article v-if="sourceDetail" class="preview-sheet">
          <header>
            <div>
              <span>revision {{ sourceDetail.revision }} · {{ sourceDetail.encoding }}</span>
              <h3>{{ sourceDetail.name }}</h3>
              <p>{{ sourceDetail.relativePath }}</p>
            </div>
            <div class="preview-budget">
              <strong>{{ displayedPreviewCharacters }} / {{ PREVIEW_PAGE_BUDGET }}</strong>
              <span>本页预览字符</span>
            </div>
          </header>

          <section class="source-preview">
            <span>来源开头节选 · 最多 {{ PREVIEW_ITEM_LIMIT }} 字符</span>
            <p>{{ sourcePreview || '此来源没有可展示的开头节选。' }}</p>
          </section>

          <section class="chapter-register" aria-labelledby="chapter-register-heading">
            <div class="subheading">
              <h4 id="chapter-register-heading">章节索引</h4>
              <span>{{ sourceChapters.length }} 章</span>
            </div>
            <n-empty v-if="!sourceChapters.length" description="没有可展示的章节索引" class="empty-state" />
            <div v-else class="chapter-list">
              <button
                v-for="chapter in sourceChapters"
                :key="chapter.id"
                type="button"
                :class="{ active: activeChapter?.id === chapter.id }"
                @click="loadChapterFragments(chapter)"
              >
                <span>{{ String(chapter.order).padStart(3, '0') }}</span>
                <strong>{{ chapter.title }}</strong>
                <code>{{ chapter.shortHash }}</code>
              </button>
            </div>
          </section>

          <section v-if="activeChapter" class="fragment-register" aria-labelledby="fragment-register-heading">
            <div class="subheading">
              <h4 id="fragment-register-heading">{{ activeChapter.title }} · 片段预览</h4>
              <span>每页最多 20 段，每段最多 {{ PREVIEW_ITEM_LIMIT }} 字符</span>
            </div>
            <n-empty v-if="!visibleFragments.length" description="此页没有可展示片段" class="empty-state" />
            <div v-else class="fragment-list">
              <article v-for="fragment in visibleFragments" :key="fragment.id">
                <header><span>片段 {{ fragment.order }}</span><code>{{ fragment.shortHash }}</code></header>
                <p>{{ fragment.preview }}</p>
              </article>
            </div>
            <n-button
              v-if="corpusStore.fragmentPage?.nextCursor !== null && corpusStore.fragmentPage?.nextCursor !== undefined"
              secondary
              size="small"
              class="next-page"
              @click="loadNextFragmentPage"
            >读取下一页 20 段</n-button>
          </section>
        </article>
      </n-spin>
    </n-modal>
  </section>
</template>

<style scoped>
.corpus-ledger { --ink: #302b24; --muted: #786e60; --rule: #d9cdb8; color: var(--ink); }
.ledger-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid var(--rule); }
.ledger-heading p, .section-heading p { margin: 0; color: #8f7048; font-size: 10px; font-weight: 800; letter-spacing: .17em; }
.ledger-heading h3 { margin: 4px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 25px; }
.ledger-heading span { display: block; margin-top: 7px; color: var(--muted); font-size: 12px; }
.privacy-note, .state-alert { margin-top: 15px; }
.loading-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 13px; margin-top: 22px; }
.register-section { margin-top: 28px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 13px; }
.section-heading h4 { margin: 3px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 20px; }
.section-heading > span { color: #8c8070; font-size: 10px; }
.discovery-list, .run-list { display: grid; gap: 8px; }
.discovery-row { display: grid; grid-template-columns: 44px minmax(180px, 1fr) auto auto; align-items: center; gap: 13px; padding: 13px 15px; border: 1px solid #ddd2bf; border-radius: 9px; background: rgba(255, 253, 248, .82); }
.file-mark { display: grid; width: 38px; height: 44px; place-items: center; border: 1px solid #c8b89e; color: #8d704b; background: #f4ecdc; font-family: Georgia, serif; font-size: 9px; }
.file-main { display: grid; min-width: 0; gap: 3px; }
.file-main strong, .file-main span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-main strong { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; }
.file-main span { color: #877c6d; font-size: 10px; }
.file-main small { color: #a13e34; font-size: 10px; }
.run-row { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 12px; padding: 11px 14px; border-left: 3px solid #8b7555; background: #f7f2e7; }
.run-row > div { display: grid; min-width: 0; gap: 3px; }
.run-row strong, .run-row span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-row strong { font-size: 12px; }
.run-row span { color: #897e6e; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 9px; }
.source-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(235px, 1fr)); gap: 11px; }
.source-card { display: flex; min-height: 225px; flex-direction: column; padding: 16px; border: 1px solid #ddd2bf; border-radius: 4px 12px 12px 4px; background: rgba(255, 253, 248, .86); }
.source-topline { display: flex; align-items: center; justify-content: space-between; gap: 9px; }
.source-card code, .preview-sheet code { color: #847968; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 9px; }
.source-card h5 { margin: 15px 0 4px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 18px; }
.source-card > p { overflow: hidden; margin: 0; color: #7f7465; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.source-card dl { display: grid; grid-template-columns: repeat(2, 1fr); gap: 9px; margin: 15px 0; }
.source-card dl div { display: grid; gap: 2px; }
.source-card dt { color: #978a78; font-size: 9px; }
.source-card dd { margin: 0; color: #5f574d; font-size: 11px; font-weight: 650; }
.source-card > .n-button { align-self: flex-start; margin-top: auto; }
.empty-state { padding: 34px 0; }
.preview-sheet > header { display: flex; align-items: end; justify-content: space-between; gap: 18px; padding-bottom: 17px; border-bottom: 1px solid #ded4c3; }
.preview-sheet > header span { color: #8f754f; font-size: 9px; letter-spacing: .08em; }
.preview-sheet > header h3 { margin: 5px 0 2px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 25px; }
.preview-sheet > header p { margin: 0; color: #7f7465; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10px; }
.preview-budget { display: grid; flex: 0 0 auto; gap: 2px; text-align: right; }
.preview-budget strong { font-family: Georgia, serif; font-size: 19px; }
.source-preview { margin-top: 16px; padding: 16px; border-left: 3px solid #59745f; background: #f3f0e7; }
.source-preview > span { color: #8d7048; font-size: 9px; font-weight: 750; letter-spacing: .07em; }
.source-preview p { margin: 8px 0 0; color: #4f483f; font-family: Georgia, 'Noto Serif SC', serif; font-size: 13px; line-height: 1.85; white-space: pre-wrap; }
.chapter-register, .fragment-register { margin-top: 22px; }
.subheading { display: flex; align-items: end; justify-content: space-between; gap: 14px; margin-bottom: 9px; }
.subheading h4 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 17px; }
.subheading span { color: #887d6d; font-size: 9px; }
.chapter-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.chapter-list button { display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 8px; padding: 9px 11px; border: 1px solid #ded4c3; border-radius: 7px; color: #5e564c; text-align: left; background: #fffdf8; cursor: pointer; }
.chapter-list button.active { border-color: #5c7561; box-shadow: inset 3px 0 0 #5c7561; }
.chapter-list button > span { color: #9b8769; font-family: Georgia, serif; font-size: 9px; }
.chapter-list button > strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.fragment-list { display: grid; gap: 7px; }
.fragment-list article { padding: 12px 14px; border: 1px solid #e1d7c7; border-radius: 8px; background: #fcf8ef; }
.fragment-list header { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #8d724d; font-size: 9px; }
.fragment-list p { margin: 7px 0 0; color: #564f46; font-size: 11px; line-height: 1.75; white-space: pre-wrap; }
.next-page { margin-top: 11px; }
@media (max-width: 760px) { .discovery-row { grid-template-columns: 44px 1fr auto; } .discovery-row > .n-button { grid-column: 2 / -1; } .chapter-list { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .ledger-heading, .section-heading, .preview-sheet > header, .subheading { align-items: flex-start; flex-direction: column; } .loading-grid { grid-template-columns: 1fr; } .discovery-row { grid-template-columns: 1fr; } .discovery-row > .n-button { grid-column: auto; } .file-mark { display: none; } .run-row { grid-template-columns: 1fr auto; } .preview-budget { text-align: left; } }
</style>
