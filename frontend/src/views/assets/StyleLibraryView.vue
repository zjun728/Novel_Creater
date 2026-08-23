<script setup>
import {
  NAlert,
  NButton,
  NEmpty,
  NInput,
  NSelect,
  NSkeleton,
  NTag,
} from 'naive-ui'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import AssetDetailDrawer from '@/components/assets/AssetDetailDrawer.vue'
import { useCreationAssetStore } from '@/stores/creationAssetStore'
import {
  creationStageLabel,
  genreLabel,
} from '@/utils/assetTaxonomyLabels.js'

const store = useCreationAssetStore()
const search = ref('')
const genre = ref(null)
const stage = ref(null)
const status = ref('active')
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detail = ref(null)
const selected = ref(null)
let searchTimer = null
let detailEpoch = 0

const inventory = computed(() => store.inventory || {})
const genreOptions = computed(() => (inventory.value.genres || []).map(value => ({
  label: genreLabel(value),
  value,
})))
const stageOptions = computed(() => (inventory.value.creationStages || []).map(value => ({
  label: creationStageLabel(value),
  value,
})))
const statusOptions = computed(() => (inventory.value.statuses || []).map(value => ({
  label: value === 'active' ? '当前版本' : '已归档',
  value,
})))

function query() {
  return {
    search: search.value.trim() || undefined,
    genre: genre.value || undefined,
    stage: stage.value || undefined,
    status: status.value || undefined,
  }
}

async function loadInventory() {
  await Promise.allSettled([
    store.loadInventory(),
    store.loadStyleTemplates(query()),
  ])
}

async function retryList() {
  await Promise.allSettled([store.loadStyleTemplates(query())])
}

function scheduleList() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    void retryList()
  }, 220)
}

async function openDetail(item) {
  const epoch = ++detailEpoch
  selected.value = item
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  try {
    const result = await store.getStyleTemplate(item.id, item.contentHash)
    if (epoch === detailEpoch) detail.value = result
  } catch (error) {
    if (epoch === detailEpoch) {
      detailError.value = error?.message || '风格详情加载失败'
    }
  } finally {
    if (epoch === detailEpoch) detailLoading.value = false
  }
}

function retryDetail() {
  if (selected.value) void openDetail(selected.value)
}

watch([search, genre, stage, status], scheduleList)
onMounted(loadInventory)
onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  detailEpoch += 1
})
</script>

<template>
  <section class="asset-library" aria-labelledby="style-library-title">
    <header class="library-hero">
      <div>
        <p class="eyebrow">CREATIVE ASSETS · STYLE INDEX</p>
        <h1 id="style-library-title">风格模板库</h1>
        <span>查看批准示例与使用边界；项目会在创作契约中冻结具体版本。</span>
      </div>
      <nav class="library-tabs" aria-label="创作资产分类">
        <router-link to="/assets/styles" aria-current="page">风格模板</router-link>
        <router-link to="/assets/experience">经验卡</router-link>
        <router-link to="/assets/corpus">语料档案室</router-link>
      </nav>
    </header>

    <section class="inventory-ledger" aria-label="风格资产清单">
      <div>
        <span>ASSET PACKAGE</span>
        <strong>{{ inventory.assetPackageVersion || '—' }}</strong>
      </div>
      <div>
        <span>TAXONOMY</span>
        <strong>{{ inventory.taxonomyPackageVersion || '—' }}</strong>
      </div>
      <div class="inventory-count">
        <span>APPROVED STYLES</span>
        <strong>{{ inventory.styleCount ?? '—' }}</strong>
      </div>
    </section>

    <n-alert v-if="store.inventoryError" type="warning" class="state-alert">
      {{ store.inventoryError }}
      <template #action><n-button size="small" @click="loadInventory">重试清单</n-button></template>
    </n-alert>

    <section class="filter-ribbon" aria-label="风格筛选">
      <n-input
        v-model:value="search"
        clearable
        placeholder="搜索风格名称或 stable key"
        aria-label="搜索风格"
      />
      <n-select v-model:value="genre" :options="genreOptions" clearable placeholder="题材" aria-label="按题材筛选" />
      <n-select v-model:value="stage" :options="stageOptions" clearable placeholder="阶段" aria-label="按阶段筛选" />
      <n-select v-model:value="status" :options="statusOptions" clearable placeholder="状态" aria-label="按状态筛选" />
    </section>

    <n-alert v-if="store.styleError" type="error" class="state-alert">
      {{ store.styleError }}
      <template #action><n-button size="small" @click="retryList">重试</n-button></template>
    </n-alert>

    <div v-if="store.loadingStyles" class="loading-grid" aria-busy="true">
      <n-skeleton v-for="index in 6" :key="index" height="220px" />
    </div>

    <n-empty
      v-else-if="!store.styleError && !store.styleTemplates.length"
      description="没有匹配的风格模板"
      class="empty-state"
    />

    <div v-else-if="!store.styleError" class="style-grid">
      <article
        v-for="(item, index) in store.styleTemplates"
        :key="`${item.id}:${item.contentHash}`"
        class="style-card"
      >
        <div class="card-index" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</div>
        <div class="card-copy">
          <div class="card-meta">
            <span>{{ item.stableKey }}</span>
            <n-tag size="small" :bordered="false">r{{ item.revision }}</n-tag>
          </div>
          <h2>{{ item.name }}</h2>
          <p>{{ item.readingExperience }}</p>
          <dl>
            <dt>适合</dt>
            <dd>{{ item.applicability.join('；') }}</dd>
          </dl>
          <div class="typed-tags">
            <span v-for="tag in item.eligibility?.genres || []" :key="`genre:${tag}`">{{ genreLabel(tag) }}</span>
            <span v-for="tag in item.eligibility?.creationStages || []" :key="`stage:${tag}`">{{ creationStageLabel(tag) }}</span>
          </div>
          <n-button secondary @click="openDetail(item)">查看批准示例</n-button>
        </div>
      </article>
    </div>

    <AssetDetailDrawer
      v-model:show="detailOpen"
      kind="style"
      :detail="detail"
      :loading="detailLoading"
      :error="detailError"
      @retry="retryDetail"
    />
  </section>
</template>

<style scoped>
.asset-library {
  min-height: 100%;
  padding: clamp(24px, 4vw, 46px);
  color: #302a23;
  background:
    radial-gradient(circle at 84% 3%, rgba(143, 61, 50, .08), transparent 24rem),
    linear-gradient(180deg, #fbf8f1 0%, #f6f0e5 100%);
}
.library-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; }
.eyebrow { margin: 0; color: #946e4c; font: 750 10px Georgia, serif; letter-spacing: .17em; }
.library-hero h1 { margin: 7px 0 0; font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif; font-size: clamp(32px, 5vw, 52px); font-weight: 650; letter-spacing: -.04em; }
.library-hero > div > span { display: block; max-width: 620px; margin-top: 10px; color: #776c5f; font-size: 13px; line-height: 1.7; }
.library-tabs { display: flex; gap: 6px; padding: 5px; border: 1px solid #d8cbb7; border-radius: 999px; background: rgba(255, 253, 248, .78); }
.library-tabs a { padding: 8px 15px; border-radius: 999px; color: #74685b; font-size: 12px; text-decoration: none; }
.library-tabs a[aria-current="page"] { color: #fffaf1; background: #7e4036; }
.inventory-ledger { display: grid; grid-template-columns: 1.2fr 1.2fr .6fr; margin-top: 30px; overflow: hidden; border-block: 1px solid #d6c9b6; }
.inventory-ledger > div { display: grid; min-width: 0; gap: 6px; padding: 16px 18px; border-right: 1px solid #ddd1bf; }
.inventory-ledger > div:last-child { border-right: 0; }
.inventory-ledger span { color: #92795d; font: 750 9px Georgia, serif; letter-spacing: .12em; }
.inventory-ledger strong { overflow: hidden; font-family: Georgia, 'Noto Serif SC', serif; font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.inventory-count { text-align: right; }
.inventory-count strong { color: #7e4036; font-size: 28px; }
.filter-ribbon { display: grid; grid-template-columns: minmax(240px, 1.6fr) repeat(3, minmax(130px, .6fr)); gap: 10px; margin-top: 24px; }
.state-alert { margin-top: 16px; }
.loading-grid, .style-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-top: 24px; }
.style-card { display: grid; grid-template-columns: 62px minmax(0, 1fr); min-height: 260px; overflow: hidden; border: 1px solid #d9cdb9; background: rgba(255, 253, 248, .86); transition: transform .16s ease, box-shadow .16s ease; }
.style-card:hover { transform: translateY(-2px); box-shadow: 0 16px 32px rgba(68, 55, 40, .08); }
.card-index { display: grid; place-items: start center; padding-top: 22px; border-right: 1px solid #dfd4c2; color: #b2a18c; font: 20px Georgia, serif; }
.card-copy { display: flex; min-width: 0; flex-direction: column; padding: 20px; }
.card-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #8e765e; font: 10px ui-monospace, Consolas, monospace; }
.card-copy h2 { margin: 16px 0 8px; font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif; font-size: 22px; }
.card-copy > p { margin: 0; color: #5f574d; font-size: 12px; line-height: 1.75; }
.card-copy dl { margin: 14px 0; }
.card-copy dt { color: #956d45; font-size: 10px; font-weight: 750; }
.card-copy dd { margin: 5px 0 0; color: #7a7063; font-size: 11px; line-height: 1.65; }
.typed-tags { display: flex; flex-wrap: wrap; gap: 5px; margin: auto 0 14px; }
.typed-tags span { padding: 3px 7px; border: 1px solid #ded2bf; border-radius: 999px; color: #776b5d; font-size: 9px; }
.card-copy :deep(.n-button) { align-self: flex-start; }
.empty-state { padding: 68px 0; }
@media (max-width: 900px) { .filter-ribbon { grid-template-columns: repeat(2, minmax(0, 1fr)); } .style-grid { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .asset-library { padding: 22px 16px; } .library-hero { align-items: flex-start; flex-direction: column; } .inventory-ledger { grid-template-columns: 1fr; } .inventory-ledger > div { border-right: 0; border-bottom: 1px solid #ddd1bf; } .inventory-count { text-align: left; } .filter-ribbon { grid-template-columns: 1fr; } .style-card { grid-template-columns: 44px minmax(0, 1fr); } }
@media (prefers-reduced-motion: reduce) { .style-card { transition: none; } }
</style>
