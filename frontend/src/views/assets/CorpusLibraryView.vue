<script setup>
import {
  NAlert,
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NInput,
  NSelect,
  NSkeleton,
  NSpin,
  NTag,
} from 'naive-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import CorpusImportDialog from '@/components/assets/CorpusImportDialog.vue'
import CorpusLifecycleMenu from '@/components/assets/CorpusLifecycleMenu.vue'
import { useCorpusStore } from '@/stores/corpusStore'

const PREVIEW_CHARS = 1200
const store = useCorpusStore()
const search = ref('')
const state = ref('active')
const listError = ref('')
const detailError = ref('')
const detailOpen = ref(false)
const detailLoading = ref(false)
const lifecycleBusy = ref(false)
const importOpen = ref(false)
const versionImportOpen = ref(false)
const selected = ref(null)
const detail = ref(null)
const versions = ref([])
const versionCursor = ref(null)
const chapters = ref([])
const fragmentPage = computed(() => store.fragmentPage)
let searchTimer = null
let detailEpoch = 0

const stateOptions = [
  { label: '当前馆藏', value: 'active' },
  { label: '已归档', value: 'archived' },
  { label: '全部状态', value: 'all' },
]
const activeCount = computed(() => store.sources.filter(item => item.state === 'active').length)
const referencedCount = computed(() => store.sources.filter(item => (
  Number(item.referenceCount || 0) + Number(item.historicalReferenceCount || 0) > 0
)).length)

function query() {
  return {
    search: search.value.trim() || undefined,
    state: state.value,
  }
}

async function loadSources() {
  listError.value = ''
  try {
    await store.loadSources(query())
  } catch (failure) {
    listError.value = failure?.message || '语料馆藏加载失败'
  }
}

function scheduleList() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => void loadSources(), 220)
}

async function openDetail(source) {
  const epoch = ++detailEpoch
  selected.value = source
  detail.value = null
  versions.value = []
  versionCursor.value = null
  chapters.value = []
  store.clearFragments()
  detailError.value = ''
  detailLoading.value = true
  detailOpen.value = true
  try {
    const [sourceDetail, versionPage, sourceChapters] = await Promise.all([
      store.getSource(source.id, source.revision, source.contentHash),
      store.loadVersions(source.id, { force: true, limit: 50 }),
      store.loadChapters(source.id, source.revision, source.contentHash),
    ])
    if (epoch !== detailEpoch) return
    detail.value = sourceDetail
    versions.value = versionPage.items
    versionCursor.value = versionPage.nextCursor
    chapters.value = sourceChapters
  } catch (failure) {
    if (epoch === detailEpoch) {
      detailError.value = failure?.message || '语料详情加载失败'
    }
  } finally {
    if (epoch === detailEpoch) detailLoading.value = false
  }
}

async function showFragments(chapter) {
  detailError.value = ''
  try {
    await store.loadFragments(chapter.id, { cursor: 0, limit: 20 })
  } catch (failure) {
    detailError.value = failure?.message || '片段预览加载失败'
  }
}

async function loadMoreVersions() {
  if (!selected.value || versionCursor.value == null) return
  detailError.value = ''
  try {
    const page = await store.loadVersions(selected.value.id, {
      cursor: versionCursor.value,
      limit: 50,
    })
    versions.value = page.items
    versionCursor.value = page.nextCursor
  } catch (failure) {
    detailError.value = failure?.message || '版本历史加载失败'
  }
}

async function runLifecycle(command) {
  if (!selected.value) return
  lifecycleBusy.value = true
  detailError.value = ''
  try {
    const current = selected.value
    if (command === 'delete') {
      await store.permanentlyDeleteSource(current.id, current.revision, true)
      detailOpen.value = false
      selected.value = null
      await loadSources()
      return
    }
    const result = command === 'archive'
      ? await store.archiveSource(current.id, current.revision)
      : await store.restoreSource(current.id, current.revision)
    selected.value = result
    detail.value = detail.value ? { ...detail.value, ...result } : result
    const versionPage = await store.loadVersions(
      result.id, { force: true, limit: 50 },
    )
    versions.value = versionPage.items
    versionCursor.value = versionPage.nextCursor
    await loadSources()
  } catch (failure) {
    detailError.value = failure?.message || '生命周期操作失败，请刷新后重试'
  } finally {
    lifecycleBusy.value = false
  }
}

async function importCompleted() {
  versionImportOpen.value = false
  await loadSources()
  if (selected.value) {
    detailOpen.value = false
    selected.value = null
  }
}

watch([search, state], scheduleList)
onMounted(loadSources)
onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  detailEpoch += 1
  store.clearFragments()
})
</script>

<template>
  <section class="corpus-library" aria-labelledby="corpus-library-title">
    <header class="library-hero">
      <div>
        <p class="eyebrow">CREATIVE ASSETS · MANAGED CORPUS</p>
        <h1 id="corpus-library-title">语料档案室</h1>
        <span>将参考文本编目为不可变版本，查看受控节选，并清楚掌握每一次创作引用。</span>
      </div>
      <n-button type="primary" @click="importOpen = true">导入语料</n-button>
    </header>

    <section class="ledger" aria-label="语料馆藏概览">
      <div>
        <span>VISIBLE RECORDS</span>
        <strong>{{ store.sources.length }}</strong>
      </div>
      <div>
        <span>ACTIVE</span>
        <strong>{{ activeCount }}</strong>
      </div>
      <div>
        <span>REFERENCED</span>
        <strong>{{ referencedCount }}</strong>
      </div>
      <p>所有正文预览均限制在 {{ PREVIEW_CHARS }} 字符；原始字节与受管路径不进入界面。</p>
    </section>

    <section class="filter-ribbon" aria-label="语料筛选">
      <n-input
        v-model:value="search"
        clearable
        placeholder="搜索馆藏名称、来源标签或参考标签"
        aria-label="搜索语料"
      />
      <n-select v-model:value="state" :options="stateOptions" aria-label="按状态筛选语料" />
    </section>

    <n-alert v-if="listError" type="error" class="state-alert">
      {{ listError }}
      <template #action><n-button size="small" @click="loadSources">重试</n-button></template>
    </n-alert>

    <div v-if="store.loadingSources" class="loading-grid" aria-busy="true">
      <n-skeleton v-for="index in 6" :key="index" height="210px" />
    </div>
    <n-empty
      v-else-if="!listError && !store.sources.length"
      description="这组筛选条件下还没有语料"
      class="empty-state"
    >
      <template #extra><n-button secondary @click="importOpen = true">导入第一份语料</n-button></template>
    </n-empty>
    <div v-else-if="!listError" class="source-grid">
      <article
        v-for="(source, index) in store.sources"
        :key="`${source.id}:${source.revision}:${source.contentHash}`"
        class="source-card"
        :class="{ archived: source.state === 'archived' }"
      >
        <div class="folio">{{ String(index + 1).padStart(2, '0') }}</div>
        <div class="card-body">
          <div class="card-meta">
            <span>{{ source.sourceLabel }}</span>
            <n-tag size="small" :bordered="false" :type="source.state === 'archived' ? 'default' : 'success'">
              {{ source.state === 'archived' ? '已归档' : `r${source.revision}` }}
            </n-tag>
          </div>
          <h2>{{ source.name }}</h2>
          <div class="hash-line">
            <code>{{ source.shortHash }}</code>
            <span>{{ source.chapterCount }} 章 · {{ source.fragmentCount }} 片段</span>
          </div>
          <div class="tags">
            <span v-for="tag in source.referenceTags" :key="tag">{{ tag }}</span>
            <span v-if="!source.referenceTags.length">未分类</span>
          </div>
          <div class="reference-line">
            当前引用 {{ source.referenceCount }} · 历史引用 {{ source.historicalReferenceCount }}
          </div>
          <n-button secondary @click="openDetail(source)">打开档案 →</n-button>
        </div>
      </article>
    </div>

    <n-drawer v-model:show="detailOpen" :width="680" placement="right">
      <n-drawer-content :title="selected?.name || '语料档案'" closable>
        <n-spin :show="detailLoading">
          <n-alert v-if="detailError" type="error" class="drawer-alert">
            {{ detailError }}
            <template #action>
              <n-button v-if="selected" size="small" @click="openDetail(selected)">重试</n-button>
            </template>
          </n-alert>
          <template v-if="detail">
            <div class="detail-stamp">
              <span>{{ detail.sourceLabel }}</span>
              <code>{{ detail.shortHash }}</code>
              <n-tag size="small">{{ detail.encoding }}</n-tag>
            </div>
            <CorpusLifecycleMenu
              :source="detail"
              :busy="lifecycleBusy"
              @archive="runLifecycle('archive')"
              @restore="runLifecycle('restore')"
              @delete="runLifecycle('delete')"
            />

            <section class="detail-section">
              <div class="section-heading">
                <div><span>BOUNDED EXCERPT</span><h3>受控节选</h3></div>
                <n-button size="small" secondary @click="versionImportOpen = true">导入新版本</n-button>
              </div>
              <pre class="preview">{{ detail.preview || '暂无可显示节选' }}</pre>
              <p v-if="detail.notes" class="notes">{{ detail.notes }}</p>
            </section>

            <section class="detail-section">
              <div class="section-heading">
                <div><span>VERSION REGISTER</span><h3>版本历史</h3></div>
              </div>
              <ol class="version-list">
                <li v-for="version in versions" :key="`${version.id}:${version.revision}`">
                  <div><strong>r{{ version.revision }}</strong><code>{{ version.shortHash }}</code></div>
                  <span>referenceCount {{ version.referenceCount }}</span>
                  <n-tag v-if="version.isCurrent" size="small" type="success">当前</n-tag>
                </li>
              </ol>
              <n-button
                v-if="versionCursor != null"
                class="more-versions"
                size="small"
                secondary
                @click="loadMoreVersions"
              >
                加载更早版本
              </n-button>
            </section>

            <section class="detail-section">
              <div class="section-heading">
                <div><span>CHAPTER MAP</span><h3>章节与片段</h3></div>
              </div>
              <div class="chapter-list">
                <button v-for="chapter in chapters" :key="chapter.id" @click="showFragments(chapter)">
                  <span>{{ String(chapter.order).padStart(2, '0') }}</span>
                  <strong>{{ chapter.title }}</strong>
                </button>
              </div>
              <div v-if="fragmentPage?.items?.length" class="fragment-list">
                <p v-for="fragment in fragmentPage.items" :key="fragment.id">
                  <span>#{{ fragment.order }}</span>{{ fragment.preview }}
                </p>
              </div>
            </section>
          </template>
        </n-spin>
      </n-drawer-content>
    </n-drawer>

    <CorpusImportDialog v-model:show="importOpen" @imported="importCompleted" />
    <CorpusImportDialog
      v-model:show="versionImportOpen"
      :source="selected"
      @imported="importCompleted"
    />
  </section>
</template>

<style scoped>
.corpus-library {
  min-height: 100%;
  padding: clamp(24px, 4vw, 46px);
  color: #302a23;
  background:
    linear-gradient(90deg, transparent 49.9%, rgba(117, 92, 63, .035) 50%, transparent 50.1%),
    radial-gradient(circle at 91% 3%, rgba(49, 91, 71, .11), transparent 25rem),
    linear-gradient(180deg, #fbf8f1 0%, #f5eee2 100%);
}
.library-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; }
.eyebrow { margin: 0; color: #637f69; font: 750 10px Georgia, serif; letter-spacing: .17em; }
.library-hero h1 { margin: 7px 0 0; font: 650 clamp(34px, 5vw, 54px) 'Noto Serif SC', 'Songti SC', Georgia, serif; letter-spacing: -.045em; }
.library-hero span { display: block; max-width: 670px; margin-top: 9px; color: #776c5f; font-size: 13px; line-height: 1.7; }
.ledger { display: grid; grid-template-columns: repeat(3, minmax(100px, .4fr)) minmax(260px, 1.8fr); margin-top: 30px; border-block: 1px solid #d6c9b6; }
.ledger > div { display: grid; gap: 5px; padding: 15px 18px; border-right: 1px solid #ddd1bf; }
.ledger span { color: #8d765d; font: 750 9px Georgia, serif; letter-spacing: .12em; }
.ledger strong { color: #355d48; font: 27px Georgia, serif; }
.ledger p { align-self: center; margin: 0; padding: 14px 18px; color: #82776a; font-size: 11px; line-height: 1.7; }
.filter-ribbon { display: grid; grid-template-columns: minmax(240px, 1fr) 180px; gap: 10px; margin-top: 24px; }
.state-alert { margin-top: 16px; }
.loading-grid, .source-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 24px; }
.source-card { display: grid; grid-template-columns: 54px minmax(0, 1fr); min-height: 230px; border: 1px solid #d7cbb9; background: rgba(255, 253, 248, .9); transition: transform .16s ease, box-shadow .16s ease; }
.source-card:hover { transform: translateY(-2px); box-shadow: 0 15px 32px rgba(68, 55, 40, .08); }
.source-card.archived { opacity: .76; filter: saturate(.72); }
.folio { padding-top: 21px; border-right: 1px solid #e0d5c4; color: #a9957c; text-align: center; font: 18px Georgia, serif; }
.card-body { display: flex; min-width: 0; flex-direction: column; padding: 19px; }
.card-meta, .hash-line, .reference-line { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: #817361; font-size: 10px; }
.card-meta > span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.card-body h2 { margin: 18px 0 10px; font: 650 21px 'Noto Serif SC', 'Songti SC', Georgia, serif; }
.hash-line code, .detail-stamp code, .version-list code { color: #557060; font: 10px ui-monospace, Consolas, monospace; }
.tags { display: flex; flex-wrap: wrap; gap: 5px; margin: 18px 0 12px; }
.tags span { padding: 3px 7px; border: 1px solid #ddd1be; border-radius: 999px; color: #796d5e; font-size: 9px; }
.reference-line { justify-content: flex-start; margin-bottom: 15px; }
.card-body :deep(.n-button) { align-self: flex-start; margin-top: auto; }
.empty-state { padding: 70px 0; }
.drawer-alert { margin-bottom: 16px; }
.detail-stamp { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; margin-bottom: 18px; color: #776b5c; font-size: 11px; }
.detail-section { margin-top: 30px; padding-top: 21px; border-top: 1px solid #e0d4c3; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; }
.section-heading span { color: #718371; font: 750 9px Georgia, serif; letter-spacing: .13em; }
.section-heading h3 { margin: 5px 0 0; font: 650 20px 'Noto Serif SC', 'Songti SC', Georgia, serif; }
.preview { max-height: 320px; margin: 14px 0 0; overflow: auto; padding: 18px; color: #443e36; background: #f6f0e6; white-space: pre-wrap; font: 12px/1.85 'Noto Serif SC', 'Songti SC', serif; }
.notes { color: #756a5e; font-size: 11px; line-height: 1.7; }
.version-list { display: grid; gap: 0; margin: 14px 0 0; padding: 0; list-style: none; border-top: 1px solid #e5dac9; }
.version-list li { display: grid; grid-template-columns: 1fr auto auto; align-items: center; gap: 12px; padding: 11px 2px; border-bottom: 1px solid #e5dac9; color: #786c60; font-size: 10px; }
.version-list li div { display: flex; gap: 10px; }
.chapter-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin-top: 14px; }
.chapter-list button { display: flex; gap: 9px; padding: 10px; border: 1px solid #ded2c1; color: #463f36; background: #fffdf8; text-align: left; cursor: pointer; }
.chapter-list button span { color: #8e795f; font: 12px Georgia, serif; }
.fragment-list { margin-top: 13px; padding: 3px 14px; border-left: 2px solid #768b78; background: #f7f2e9; }
.fragment-list p { color: #5f574e; font-size: 11px; line-height: 1.7; }
.fragment-list span { margin-right: 8px; color: #687b69; font-family: ui-monospace, Consolas, monospace; }
@media (max-width: 880px) { .ledger { grid-template-columns: repeat(3, 1fr); } .ledger p { grid-column: 1 / -1; border-top: 1px solid #ddd1bf; } .source-grid { grid-template-columns: 1fr; } }
@media (max-width: 600px) { .corpus-library { padding: 22px 16px; } .library-hero { align-items: flex-start; flex-direction: column; } .ledger { grid-template-columns: 1fr; } .ledger > div { border-right: 0; border-bottom: 1px solid #ddd1bf; } .ledger p { grid-column: auto; } .filter-ribbon { grid-template-columns: 1fr; } .chapter-list { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .source-card { transition: none; } }
</style>
