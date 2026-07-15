<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NEmpty,
  NModal,
  NPagination,
  NSelect,
  NSkeleton,
  NSpin,
  NTag,
} from 'naive-ui'

import { useCreationAssetStore } from '@/stores/creationAssetStore'

const PACKAGE_VERSION = 'writer-core-v1.1.0'
const EXPECTED_STYLE_COUNT = 10
const EXPECTED_CARD_COUNT = 64
const CARD_PAGE_SIZE = 12
const DETAIL_TEXT_LIMIT = 800

const assetStore = useCreationAssetStore()
const loadError = ref('')
const cardCategory = ref(null)
const cardPage = ref(1)
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const detailKind = ref('')
const detail = ref(null)
let detailEpoch = 0

const loading = computed(() => assetStore.loadingStyles || assetStore.loadingCards)
const inventoryComplete = computed(() => (
  assetStore.styleTemplates.length === EXPECTED_STYLE_COUNT
  && assetStore.experienceCards.length === EXPECTED_CARD_COUNT
))
const categoryOptions = computed(() => [...new Set(
  assetStore.experienceCards.map(card => card.category).filter(Boolean),
)].sort((left, right) => left.localeCompare(right, 'zh-CN')).map(value => ({
  label: value,
  value,
})))
const filteredCards = computed(() => cardCategory.value
  ? assetStore.experienceCards.filter(card => card.category === cardCategory.value)
  : assetStore.experienceCards)
const cardPageCount = computed(() => Math.max(1, Math.ceil(filteredCards.value.length / CARD_PAGE_SIZE)))
const visibleCards = computed(() => {
  const start = (cardPage.value - 1) * CARD_PAGE_SIZE
  return filteredCards.value.slice(start, start + CARD_PAGE_SIZE)
})

function boundedText(value, limit = DETAIL_TEXT_LIMIT) {
  const text = String(value || '')
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

function shortHash(asset) {
  return String(asset?.contentHash || '').slice(0, 12)
}

function setCategory(value) {
  cardCategory.value = value || null
  cardPage.value = 1
}

async function loadInventory() {
  loadError.value = ''
  try {
    await Promise.all([
      assetStore.loadStyleTemplates(),
      assetStore.loadExperienceCards(),
    ])
  } catch (error) {
    loadError.value = error?.message || '创作资产目录加载失败'
  }
}

async function openStyle(style) {
  const epoch = ++detailEpoch
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = ''
  detailKind.value = 'style'
  detail.value = null
  try {
    const result = await assetStore.getStyleTemplate(style.id, style.contentHash)
    if (epoch === detailEpoch) detail.value = result
  } catch (error) {
    if (epoch === detailEpoch) detailError.value = error?.message || '风格详情加载失败'
  } finally {
    if (epoch === detailEpoch) detailLoading.value = false
  }
}

async function openCard(card) {
  const epoch = ++detailEpoch
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = ''
  detailKind.value = 'card'
  detail.value = null
  try {
    const result = await assetStore.getExperienceCard(card.id, card.contentHash)
    if (epoch === detailEpoch) detail.value = result
  } catch (error) {
    if (epoch === detailEpoch) detailError.value = error?.message || '经验卡详情加载失败'
  } finally {
    if (epoch === detailEpoch) detailLoading.value = false
  }
}

onMounted(loadInventory)
</script>

<template>
  <section class="asset-ledger" aria-labelledby="creation-assets-heading">
    <header class="ledger-heading">
      <div>
        <p>WRITING ASSET LEDGER</p>
        <h3 id="creation-assets-heading">创作资产册</h3>
        <span>统一分析后的全局写作资产，只读供每本书选择和冻结。</span>
      </div>
      <n-tag :type="inventoryComplete ? 'success' : 'warning'" round :bordered="false">
        {{ inventoryComplete ? '目录完整' : '目录待核对' }}
      </n-tag>
    </header>

    <div class="inventory-strip" aria-label="资产包清单">
      <div>
        <span>资产包版本</span>
        <strong>{{ PACKAGE_VERSION }}</strong>
      </div>
      <div>
        <span>风格模板</span>
        <strong>{{ assetStore.styleTemplates.length }} / {{ EXPECTED_STYLE_COUNT }}</strong>
        <small>10 套风格</small>
      </div>
      <div>
        <span>经验卡</span>
        <strong>{{ assetStore.experienceCards.length }} / {{ EXPECTED_CARD_COUNT }}</strong>
        <small>64 张经验卡</small>
      </div>
      <div>
        <span>目录性质</span>
        <strong>只读 inventory</strong>
        <small>项目仅保存冻结引用</small>
      </div>
    </div>

    <n-alert v-if="loadError" type="error" class="state-alert">
      {{ loadError }}
      <template #action><n-button size="small" @click="loadInventory">重新加载</n-button></template>
    </n-alert>

    <template v-if="loading">
      <div class="loading-grid" aria-busy="true" aria-label="正在加载创作资产">
        <n-skeleton v-for="index in 6" :key="index" height="140px" />
      </div>
    </template>

    <template v-else-if="!loadError">
      <section class="catalog-section" aria-labelledby="style-catalog-heading">
        <div class="section-heading">
          <div>
            <p>STYLE / 10</p>
            <h4 id="style-catalog-heading">风格模板</h4>
          </div>
          <span>阅读体验与适用边界的公开摘要</span>
        </div>

        <n-empty v-if="!assetStore.styleTemplates.length" description="风格模板目录为空" class="empty-state" />
        <div v-else class="style-grid">
          <article v-for="style in assetStore.styleTemplates" :key="style.id" class="style-slip">
            <div class="slip-meta">
              <span>r{{ style.revision }}</span>
              <code>{{ shortHash(style) }}</code>
            </div>
            <h5>{{ style.name }}</h5>
            <p>{{ boundedText(style.readingExperience, 180) }}</p>
            <dl>
              <dt>适合</dt>
              <dd>{{ boundedText(style.applicability.join('；'), 220) }}</dd>
            </dl>
            <n-button size="small" secondary @click="openStyle(style)">查看安全详情</n-button>
          </article>
        </div>
      </section>

      <section class="catalog-section" aria-labelledby="card-catalog-heading">
        <div class="section-heading section-heading--filter">
          <div>
            <p>EXPERIENCE / 64</p>
            <h4 id="card-catalog-heading">经验卡</h4>
          </div>
          <n-select
            :value="cardCategory"
            :options="categoryOptions"
            clearable
            placeholder="全部类别"
            style="width: min(220px, 100%)"
            @update:value="setCategory"
          />
        </div>

        <n-empty v-if="!filteredCards.length" description="此类别没有经验卡" class="empty-state" />
        <div v-else class="card-grid">
          <article v-for="card in visibleCards" :key="card.id" class="card-slip">
            <div class="slip-meta">
              <n-tag size="small" :bordered="false">{{ card.category }}</n-tag>
              <code>{{ shortHash(card) }}</code>
            </div>
            <h5>{{ card.title }}</h5>
            <p>{{ boundedText(card.method, 220) }}</p>
            <div class="card-foot">
              <span>revision {{ card.revision }}</span>
              <n-button size="tiny" quaternary @click="openCard(card)">查看安全详情</n-button>
            </div>
          </article>
        </div>
        <n-pagination
          v-if="cardPageCount > 1"
          v-model:page="cardPage"
          :page-count="cardPageCount"
          :page-slot="7"
          class="catalog-pagination"
        />
      </section>
    </template>

    <n-modal
      v-model:show="detailOpen"
      preset="card"
      :title="detailKind === 'style' ? '风格模板详情' : '经验卡详情'"
      style="width: min(880px, 94vw)"
    >
      <n-spin :show="detailLoading">
        <n-alert v-if="detailError" type="error">{{ detailError }}</n-alert>
        <article v-else-if="detail" class="detail-sheet">
          <header>
            <div>
              <span>{{ detail.stableKey }} · revision {{ detail.revision }}</span>
              <h3>{{ detail.name || detail.title }}</h3>
            </div>
            <code>{{ shortHash(detail) }}</code>
          </header>

          <template v-if="detailKind === 'style'">
            <div class="detail-grid">
              <section><span>阅读体验</span><p>{{ boundedText(detail.payload.readingExperience) }}</p></section>
              <section><span>叙事距离</span><p>{{ boundedText(detail.payload.narrativeDistance) }}</p></section>
              <section><span>节奏</span><p>{{ boundedText(detail.payload.rhythm) }}</p></section>
              <section><span>对白与潜台词</span><p>{{ boundedText(`${detail.payload.dialogue}；${detail.payload.subtext}`) }}</p></section>
              <section><span>人物声音</span><p>{{ boundedText(detail.payload.characterVoices) }}</p></section>
              <section><span>情绪与内心</span><p>{{ boundedText(`${detail.payload.emotion}；${detail.payload.interiority}`) }}</p></section>
            </div>
            <section class="preview-block">
              <span>标准场景节选</span>
              <p>{{ boundedText(detail.payload.standardSceneExample, 800) }}</p>
            </section>
            <section class="preview-block preview-block--warm">
              <span>完整应用节选</span>
              <p>{{ boundedText(detail.payload.completeApplicationExample, 800) }}</p>
            </section>
            <section class="risk-list">
              <span>风险</span>
              <ul><li v-for="risk in detail.payload.risks" :key="risk">{{ boundedText(risk, 240) }}</li></ul>
            </section>
          </template>

          <template v-else>
            <div class="detail-grid">
              <section><span>方法</span><p>{{ boundedText(detail.payload.method) }}</p></section>
              <section><span>适用</span><p>{{ boundedText(detail.payload.applicability.join('；')) }}</p></section>
              <section><span>不适用</span><p>{{ boundedText(detail.payload.nonApplicability.join('；')) }}</p></section>
              <section><span>风险</span><p>{{ boundedText(detail.payload.risks.join('；')) }}</p></section>
            </div>
            <section class="preview-block">
              <span>原创微型示例节选</span>
              <p>{{ boundedText(detail.payload.originalMicroDemo, 600) }}</p>
            </section>
          </template>
        </article>
      </n-spin>
    </n-modal>
  </section>
</template>

<style scoped>
.asset-ledger { --paper: #fbf7ed; --ink: #302b24; --muted: #776d60; --rule: #d9cdb8; color: var(--ink); }
.ledger-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; padding-bottom: 18px; border-bottom: 1px solid var(--rule); }
.ledger-heading p, .section-heading p { margin: 0; color: #8f7048; font-size: 10px; font-weight: 800; letter-spacing: .17em; }
.ledger-heading h3 { margin: 4px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 25px; }
.ledger-heading span { display: block; margin-top: 7px; color: var(--muted); font-size: 12px; }
.inventory-strip { display: grid; grid-template-columns: 1.2fr repeat(3, 1fr); margin-top: 18px; overflow: hidden; border: 1px solid var(--rule); border-radius: 10px; background: #fffdf8; }
.inventory-strip > div { display: grid; gap: 3px; min-width: 0; padding: 16px; border-right: 1px solid #e6ddce; }
.inventory-strip > div:last-child { border-right: 0; }
.inventory-strip span { color: #8e8272; font-size: 10px; }
.inventory-strip strong { overflow: hidden; font-family: Georgia, 'Noto Serif SC', serif; font-size: 16px; text-overflow: ellipsis; white-space: nowrap; }
.inventory-strip small { color: #9a8d7a; font-size: 9px; }
.state-alert { margin-top: 16px; }
.loading-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-top: 24px; }
.catalog-section { margin-top: 28px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 13px; }
.section-heading h4 { margin: 3px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 20px; }
.section-heading > span { color: #8b7f70; font-size: 11px; }
.style-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 11px; }
.style-slip, .card-slip { display: flex; min-width: 0; flex-direction: column; border: 1px solid #ddd2be; background: rgba(255, 253, 248, .86); }
.style-slip { min-height: 248px; padding: 17px; border-radius: 4px 12px 12px 4px; }
.slip-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #947b59; font-size: 10px; }
.slip-meta code, .detail-sheet code { color: #847967; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10px; }
.style-slip h5, .card-slip h5 { margin: 15px 0 7px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 17px; }
.style-slip > p, .card-slip > p { margin: 0; color: #655d52; font-size: 11px; line-height: 1.7; }
.style-slip dl { margin: 13px 0 16px; }
.style-slip dt { color: #97754b; font-size: 10px; font-weight: 700; }
.style-slip dd { margin: 4px 0 0; color: #7a7062; font-size: 10px; line-height: 1.6; }
.style-slip > .n-button { align-self: flex-start; margin-top: auto; }
.card-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.card-slip { min-height: 190px; padding: 15px; border-radius: 9px; }
.card-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-top: auto; padding-top: 12px; color: #8c806f; font-size: 9px; }
.catalog-pagination { display: flex; justify-content: center; margin-top: 18px; }
.empty-state { padding: 36px 0; }
.detail-sheet header { display: flex; align-items: end; justify-content: space-between; gap: 16px; padding-bottom: 17px; border-bottom: 1px solid #ded4c3; }
.detail-sheet header span { color: #8f754f; font-size: 10px; letter-spacing: .1em; }
.detail-sheet header h3 { margin: 5px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 26px; }
.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin-top: 18px; overflow: hidden; border: 1px solid #e2d9c9; border-radius: 9px; background: #e2d9c9; }
.detail-grid section { padding: 14px; background: #fffdf8; }
.detail-grid span, .preview-block > span, .risk-list > span { color: #8e6f46; font-size: 10px; font-weight: 750; letter-spacing: .08em; }
.detail-grid p { margin: 6px 0 0; color: #5f574d; font-size: 12px; line-height: 1.7; white-space: pre-wrap; }
.preview-block { margin-top: 16px; padding: 17px; border-left: 3px solid #58745e; background: #f3f0e7; }
.preview-block--warm { border-left-color: #9a7043; background: #faf5e9; }
.preview-block p { margin: 8px 0 0; color: #4f483f; font-family: Georgia, 'Noto Serif SC', serif; font-size: 13px; line-height: 1.9; white-space: pre-wrap; }
.risk-list { margin-top: 16px; }
.risk-list ul { margin: 7px 0 0; padding-left: 18px; color: #6d6356; font-size: 11px; line-height: 1.75; }
@media (max-width: 860px) { .inventory-strip { grid-template-columns: repeat(2, 1fr); } .inventory-strip > div:nth-child(2) { border-right: 0; } .inventory-strip > div:nth-child(-n+2) { border-bottom: 1px solid #e6ddce; } .card-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 600px) { .ledger-heading, .section-heading { align-items: flex-start; flex-direction: column; } .inventory-strip, .card-grid, .detail-grid { grid-template-columns: 1fr; } .inventory-strip > div { border-right: 0; border-bottom: 1px solid #e6ddce; } .inventory-strip > div:last-child { border-bottom: 0; } .loading-grid { grid-template-columns: 1fr; } }
</style>
