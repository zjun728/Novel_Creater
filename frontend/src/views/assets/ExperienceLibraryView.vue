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

const store = useCreationAssetStore()
const search = ref('')
const category = ref(null)
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
const categoryOptions = computed(() => (inventory.value.categories || []).map(value => ({
  label: value,
  value,
})))
const genreOptions = computed(() => (inventory.value.genres || []).map(value => ({
  label: value === 'general' ? '通用题材' : value,
  value,
})))
const stageOptions = computed(() => (inventory.value.creationStages || []).map(value => ({
  label: value,
  value,
})))
const statusOptions = computed(() => (inventory.value.statuses || []).map(value => ({
  label: value === 'active' ? '当前版本' : '已归档',
  value,
})))

function query() {
  return {
    search: search.value.trim() || undefined,
    category: category.value || undefined,
    genre: genre.value || undefined,
    stage: stage.value || undefined,
    status: status.value || undefined,
  }
}

async function loadInventory() {
  await Promise.allSettled([
    store.loadInventory(),
    store.loadExperienceCards(query()),
  ])
}

async function retryList() {
  await Promise.allSettled([store.loadExperienceCards(query())])
}

function scheduleList() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => void retryList(), 220)
}

async function openDetail(item) {
  const epoch = ++detailEpoch
  selected.value = item
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  try {
    const result = await store.getExperienceCard(item.id, item.contentHash)
    if (epoch === detailEpoch) detail.value = result
  } catch (error) {
    if (epoch === detailEpoch) {
      detailError.value = error?.message || '经验卡详情加载失败'
    }
  } finally {
    if (epoch === detailEpoch) detailLoading.value = false
  }
}

function retryDetail() {
  if (selected.value) void openDetail(selected.value)
}

watch([search, category, genre, stage, status], scheduleList)
onMounted(loadInventory)
onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  detailEpoch += 1
})
</script>

<template>
  <section class="asset-library" aria-labelledby="experience-library-title">
    <header class="library-hero">
      <div>
        <p class="eyebrow">CREATIVE ASSETS · METHOD CARDS</p>
        <h1 id="experience-library-title">经验卡库</h1>
        <span>每张卡只描述一种可复用写法：方法、正向示例、反向边界与使用范围。</span>
      </div>
      <nav class="library-tabs" aria-label="创作资产分类">
        <router-link to="/assets/styles">风格模板</router-link>
        <router-link to="/assets/experience" aria-current="page">经验卡</router-link>
      </nav>
    </header>

    <section class="inventory-ledger" aria-label="经验卡资产清单">
      <div>
        <span>ASSET PACKAGE</span>
        <strong>{{ inventory.assetPackageVersion || '—' }}</strong>
      </div>
      <div>
        <span>TAXONOMY</span>
        <strong>{{ inventory.taxonomyPackageVersion || '—' }}</strong>
      </div>
      <div class="inventory-count">
        <span>APPROVED CARDS</span>
        <strong>{{ inventory.experienceCardCount ?? '—' }}</strong>
      </div>
    </section>

    <n-alert v-if="store.inventoryError" type="warning" class="state-alert">
      {{ store.inventoryError }}
      <template #action><n-button size="small" @click="loadInventory">重试清单</n-button></template>
    </n-alert>

    <section class="filter-ribbon" aria-label="经验卡筛选">
      <n-input v-model:value="search" clearable placeholder="搜索标题、stable key 或类别" aria-label="搜索经验卡" />
      <n-select v-model:value="category" :options="categoryOptions" clearable placeholder="类别" aria-label="按类别筛选" />
      <n-select v-model:value="genre" :options="genreOptions" clearable placeholder="题材" aria-label="按题材筛选" />
      <n-select v-model:value="stage" :options="stageOptions" clearable placeholder="阶段" aria-label="按阶段筛选" />
      <n-select v-model:value="status" :options="statusOptions" clearable placeholder="状态" aria-label="按状态筛选" />
    </section>

    <n-alert v-if="store.cardError" type="error" class="state-alert">
      {{ store.cardError }}
      <template #action><n-button size="small" @click="retryList">重试</n-button></template>
    </n-alert>

    <div v-if="store.loadingCards" class="loading-grid" aria-busy="true">
      <n-skeleton v-for="index in 9" :key="index" height="210px" />
    </div>

    <n-empty
      v-else-if="!store.cardError && !store.experienceCards.length"
      description="没有匹配的经验卡"
      class="empty-state"
    />

    <div v-else-if="!store.cardError" class="card-grid">
      <article
        v-for="item in store.experienceCards"
        :key="`${item.id}:${item.contentHash}`"
        class="method-card"
      >
        <div class="card-topline">
          <n-tag size="small" :bordered="false">{{ item.category }}</n-tag>
          <span>r{{ item.revision }}</span>
        </div>
        <h2>{{ item.title }}</h2>
        <p>{{ item.method }}</p>
        <dl>
          <dt>使用范围</dt>
          <dd>{{ item.applicability.join('；') }}</dd>
        </dl>
        <div class="typed-tags">
          <span v-for="tag in item.eligibility?.genres || []" :key="tag">{{ tag }}</span>
          <span v-for="tag in item.eligibility?.creationStages || []" :key="tag">{{ tag }}</span>
        </div>
        <n-button quaternary @click="openDetail(item)">展开方法与示例 →</n-button>
      </article>
    </div>

    <AssetDetailDrawer
      v-model:show="detailOpen"
      kind="experience"
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
    linear-gradient(90deg, rgba(99, 119, 91, .035) 1px, transparent 1px) 0 0 / 46px 46px,
    linear-gradient(180deg, #faf8f1 0%, #f4f0e6 100%);
}
.library-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; }
.eyebrow { margin: 0; color: #63775b; font: 750 10px Georgia, serif; letter-spacing: .17em; }
.library-hero h1 { margin: 7px 0 0; font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif; font-size: clamp(32px, 5vw, 52px); font-weight: 650; letter-spacing: -.04em; }
.library-hero > div > span { display: block; max-width: 640px; margin-top: 10px; color: #776c5f; font-size: 13px; line-height: 1.7; }
.library-tabs { display: flex; gap: 6px; padding: 5px; border: 1px solid #d8cbb7; border-radius: 999px; background: rgba(255, 253, 248, .78); }
.library-tabs a { padding: 8px 15px; border-radius: 999px; color: #74685b; font-size: 12px; text-decoration: none; }
.library-tabs a[aria-current="page"] { color: #fffaf1; background: #61745a; }
.inventory-ledger { display: grid; grid-template-columns: 1.2fr 1.2fr .6fr; margin-top: 30px; overflow: hidden; border-block: 1px solid #d6c9b6; }
.inventory-ledger > div { display: grid; min-width: 0; gap: 6px; padding: 16px 18px; border-right: 1px solid #ddd1bf; }
.inventory-ledger > div:last-child { border-right: 0; }
.inventory-ledger span { color: #7b8068; font: 750 9px Georgia, serif; letter-spacing: .12em; }
.inventory-ledger strong { overflow: hidden; font-family: Georgia, 'Noto Serif SC', serif; font-size: 15px; text-overflow: ellipsis; white-space: nowrap; }
.inventory-count { text-align: right; }
.inventory-count strong { color: #61745a; font-size: 28px; }
.filter-ribbon { display: grid; grid-template-columns: minmax(230px, 1.5fr) repeat(4, minmax(120px, .55fr)); gap: 9px; margin-top: 24px; }
.state-alert { margin-top: 16px; }
.loading-grid, .card-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-top: 24px; }
.method-card { display: flex; min-width: 0; min-height: 260px; flex-direction: column; padding: 18px; border: 1px solid #d9cdb9; background: rgba(255, 253, 248, .87); box-shadow: inset 0 3px 0 rgba(97, 116, 90, .35); transition: transform .16s ease, box-shadow .16s ease; }
.method-card:hover { transform: translateY(-2px); box-shadow: inset 0 3px 0 #61745a, 0 16px 30px rgba(68, 55, 40, .08); }
.card-topline { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: #8b7f70; font-size: 10px; }
.method-card h2 { margin: 17px 0 8px; font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif; font-size: 18px; line-height: 1.45; }
.method-card > p { margin: 0; color: #5e574d; font-size: 12px; line-height: 1.75; }
.method-card dl { margin: 14px 0; }
.method-card dt { color: #6c7e64; font-size: 10px; font-weight: 750; }
.method-card dd { margin: 5px 0 0; color: #7a7063; font-size: 11px; line-height: 1.65; }
.typed-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: auto; }
.typed-tags span { padding: 3px 7px; border: 1px solid #d8d4c3; border-radius: 999px; color: #716e5f; font-size: 9px; }
.method-card :deep(.n-button) { align-self: flex-start; margin-top: 12px; padding-inline: 0; }
.empty-state { padding: 68px 0; }
@media (max-width: 1050px) { .filter-ribbon { grid-template-columns: repeat(3, minmax(0, 1fr)); } .card-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 680px) { .asset-library { padding: 22px 16px; } .library-hero { align-items: flex-start; flex-direction: column; } .inventory-ledger, .filter-ribbon, .card-grid { grid-template-columns: 1fr; } .inventory-ledger > div { border-right: 0; border-bottom: 1px solid #ddd1bf; } .inventory-count { text-align: left; } }
@media (prefers-reduced-motion: reduce) { .method-card { transition: none; } }
</style>
