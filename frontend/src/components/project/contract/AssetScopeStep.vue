<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NInputNumber, NSelect, NSkeleton, NSpin, NTag } from 'naive-ui'

import { useCorpusStore } from '@/stores/corpusStore.js'
import { useCreationAssetStore } from '@/stores/creationAssetStore.js'
import { useCreationContractStore } from '@/stores/creationContractStore.js'

const props = defineProps({ projectId: { type: String, required: true } })
const emit = defineEmits(['saved', 'dirty-change', 'back'])
const assetStore = useCreationAssetStore()
const contractStore = useCreationContractStore()
const corpusStore = useCorpusStore()
const loading = ref(false)
const loadError = ref('')
const saveError = ref('')
const errorRegion = ref(null)
const selectedExperienceIds = ref([])
const explicitExperienceRefs = ref({})
const selectedCorpusFragments = ref([])
const corpusBrowserSource = ref(null)
const corpusChapters = ref([])
const selectedChapterId = ref(null)
const fragmentPage = ref(null)
let loadEpoch = 0
let fragmentEpoch = 0

const draftValues = computed(() => contractStore.draft?.draft || null)
const recommendedCards = computed(() => assetStore.recommendations?.experienceCards || [])
const experienceOptions = computed(() => assetStore.experienceCards.map(card => ({
  label: `${card.title} · ${card.category}`,
  value: card.id,
})))
const visibleCorpusSources = computed(() => corpusStore.sources.filter(source => source.state !== 'archived'))
const chapterOptions = computed(() => corpusChapters.value.map(chapter => ({
  label: `${String(chapter.order).padStart(2, '0')} · ${chapter.title}`,
  value: chapter.id,
})))
const fragments = computed(() => fragmentPage.value?.items || [])
const selectedExperienceCards = computed(() => selectedExperienceIds.value.map(cardById).filter(Boolean))
const selectedCorpusSources = computed(() => {
  const rows = new Map()
  for (const selection of selectedCorpusFragments.value) rows.set(selection.source.id, selection.source)
  return [...rows.values()]
})
const previewBudgetUsed = computed(() => selectedCorpusFragments.value.reduce(
  (total, selection) => total + selection.chapterCharEnd - selection.chapterCharStart,
  0,
))
const previewBudgetRemaining = computed(() => Math.max(0, 4000 - previewBudgetUsed.value))

const REASON_LABELS = Object.freeze({
  'category-profile': '类别适配',
  'asset-text-overlap': '故事信号匹配',
  'default-rank': '基础优先级',
})

function reasonLabel(code) {
  return REASON_LABELS[code] || code
}

function cardById(id) {
  return assetStore.experienceCards.find(card => card.id === id)
    || recommendedCards.value.find(card => card.id === id)
    || draftValues.value?.experienceCardRefs?.find(card => card.id === id)
    || null
}

function assetRef(asset) {
  if (!asset?.id || !Number.isInteger(asset.revision) || !asset.contentHash) {
    throw new TypeError('经验卡版本信息不完整，请重新加载')
  }
  return { id: asset.id, revision: asset.revision, contentHash: asset.contentHash }
}

function exactExperienceRef(id) {
  return explicitExperienceRefs.value[id]
    || draftValues.value?.experienceCardRefs?.find(item => item.id === id)
    || assetRef(cardById(id))
}

function markDirty() {
  contractStore.markUnsavedChanges()
  emit('dirty-change', true)
}

async function showError(message) {
  saveError.value = String(message || '素材范围操作失败')
  await nextTick()
  errorRegion.value?.focus({ preventScroll: false })
}

function updateExperienceSelection(values) {
  if (contractStore.saving) return
  const next = [...new Set((values || []).filter(Boolean))]
  const overrides = {}
  for (const id of next) overrides[id] = exactExperienceRef(id)
  explicitExperienceRefs.value = overrides
  selectedExperienceIds.value = next
  saveError.value = ''
  markDirty()
}

function toggleExperience(id) {
  const selected = new Set(selectedExperienceIds.value)
  if (selected.has(id)) selected.delete(id)
  else selected.add(id)
  updateExperienceSelection([...selected])
}

function fragmentKey(sourceId, chapterId, fragmentId) {
  return `${sourceId}:${chapterId}:${fragmentId}`
}

function selectedFragment(sourceId, chapterId, fragmentId) {
  const key = fragmentKey(sourceId, chapterId, fragmentId)
  return selectedCorpusFragments.value.find(item => item.key === key) || null
}

async function chooseCorpusSource(source) {
  const epoch = ++fragmentEpoch
  corpusBrowserSource.value = source
  selectedChapterId.value = null
  fragmentPage.value = null
  saveError.value = ''
  try {
    const rows = await corpusStore.loadChapters(source.id, source.revision, source.contentHash)
    if (epoch !== fragmentEpoch || corpusBrowserSource.value?.id !== source.id) return
    corpusChapters.value = rows
    if (rows.length) await chooseChapter(rows[0].id)
  } catch (error) {
    if (epoch !== fragmentEpoch) return
    await showError(error?.message || '语料章节加载失败')
  }
}

async function chooseChapter(chapterId) {
  const epoch = ++fragmentEpoch
  selectedChapterId.value = chapterId
  fragmentPage.value = null
  try {
    const page = await corpusStore.loadFragments(chapterId, { cursor: 0, limit: 20 })
    if (epoch !== fragmentEpoch || selectedChapterId.value !== chapterId) return
    fragmentPage.value = page
  } catch (error) {
    if (epoch !== fragmentEpoch) return
    await showError(error?.message || '语料片段加载失败')
  }
}

async function loadMoreFragments() {
  const cursor = fragmentPage.value?.nextCursor
  const chapterId = selectedChapterId.value
  if (cursor == null || !chapterId || corpusStore.loadingFragments) return
  const epoch = ++fragmentEpoch
  const previous = fragmentPage.value?.items || []
  try {
    const page = await corpusStore.loadFragments(chapterId, { cursor, limit: 20 })
    if (epoch !== fragmentEpoch || selectedChapterId.value !== chapterId) return
    const seen = new Set(previous.map(fragment => fragment.id))
    fragmentPage.value = {
      items: [...previous, ...(page?.items || []).filter(fragment => !seen.has(fragment.id))],
      nextCursor: page?.nextCursor ?? null,
    }
  } catch (error) {
    if (epoch !== fragmentEpoch) return
    await showError(error?.message || '更多语料片段加载失败')
  }
}

function toggleFragment(fragment) {
  const source = corpusBrowserSource.value
  const chapterId = selectedChapterId.value
  if (!source || !chapterId || contractStore.saving) return
  const key = fragmentKey(source.id, chapterId, fragment.id)
  const existing = selectedCorpusFragments.value.find(item => item.key === key)
  if (existing) {
    selectedCorpusFragments.value = selectedCorpusFragments.value.filter(item => item.key !== key)
    markDirty()
    return
  }
  const fragmentHash = fragment.contentHash || fragment.fragmentHash
  if (!fragmentHash) {
    void showError('该片段缺少完整内容摘要，请重新加载语料。')
    return
  }
  const chapterCharStart = Number(fragment.charStart)
  const chapterCharEnd = Math.min(Number(fragment.charEnd), chapterCharStart + 300)
  const nextLength = chapterCharEnd - chapterCharStart
  if (nextLength < 1 || previewBudgetUsed.value + nextLength > 4000) {
    void showError('加入该片段会超过 4000 字预览预算。')
    return
  }
  selectedCorpusFragments.value = [...selectedCorpusFragments.value, {
    key,
    source: { ...source },
    chapterId,
    fragmentId: fragment.id,
    fragmentHash,
    chapterCharStart,
    chapterCharEnd,
    fragmentMin: Number(fragment.charStart),
    fragmentMax: Number(fragment.charEnd),
    referenceUse: 'style',
    preview: fragment.preview,
  }]
  markDirty()
}

function updateFragment(selection, field, value) {
  const number = Number(value)
  const next = selectedCorpusFragments.value.map(item => (
    item.key === selection.key ? { ...item, [field]: number } : item
  ))
  const changed = next.find(item => item.key === selection.key)
  const length = changed.chapterCharEnd - changed.chapterCharStart
  const total = next.reduce((sum, item) => sum + item.chapterCharEnd - item.chapterCharStart, 0)
  if (
    changed.chapterCharStart < changed.fragmentMin
    || changed.chapterCharEnd > changed.fragmentMax
    || length < 1
    || length > 300
    || total > 4000
  ) {
    void showError('单个片段范围须为 1–300 字，全部片段合计不超过 4000 字。')
    return
  }
  selectedCorpusFragments.value = next
  saveError.value = ''
  markDirty()
}

function updateReferenceUse(selection, value) {
  selectedCorpusFragments.value = selectedCorpusFragments.value.map(item => (
    item.key === selection.key ? { ...item, referenceUse: value } : item
  ))
  markDirty()
}

function removeFragment(selection) {
  selectedCorpusFragments.value = selectedCorpusFragments.value.filter(
    item => item.key !== selection.key,
  )
  markDirty()
}

function hydrateFromDraft(draft) {
  explicitExperienceRefs.value = {}
  if (draft?.draftStage === 'assets') {
    selectedExperienceIds.value = (draft.experienceCardRefs || []).map(item => item.id)
    selectedCorpusFragments.value = (draft.corpusSourceRefs || []).flatMap(source => (
      (source.fragments || []).map(fragment => ({
        key: fragmentKey(source.id, fragment.chapterId, fragment.fragmentId),
        source: { ...source, fragments: undefined },
        ...fragment,
        fragmentMin: fragment.chapterCharStart,
        fragmentMax: fragment.chapterCharEnd,
        preview: '已冻结片段范围',
      }))
    ))
    return
  }
  selectedExperienceIds.value = []
  selectedCorpusFragments.value = []
}

async function initialize(projectId, { reloadContract = false } = {}) {
  if (contractStore.saving) return
  const epoch = ++loadEpoch
  fragmentEpoch += 1
  loading.value = true
  loadError.value = ''
  saveError.value = ''
  try {
    if (reloadContract || contractStore.projectId !== projectId || !contractStore.draft) {
      await contractStore.load(projectId)
    }
    const draft = contractStore.draft?.draft
    if (!draft?.engineOptionId || !draft?.primaryStyleRef) throw new Error('请先完成并保存风格契约。')
    await Promise.all([
      assetStore.loadExperienceCards(),
      assetStore.loadRecommendations(projectId, draft.engineOptionId, draft),
      corpusStore.loadSources(),
    ])
    if (epoch !== loadEpoch) return
    hydrateFromDraft(draft)
    contractStore.discardUnsavedChanges()
    emit('dirty-change', false)
  } catch (error) {
    if (epoch === loadEpoch) loadError.value = error?.message || '创作资产范围加载失败'
  } finally {
    if (epoch === loadEpoch) loading.value = false
  }
}

function corpusRefs() {
  if (previewBudgetUsed.value > 4000) throw new Error('语料片段预览预算不能超过 4000 字。')
  const groups = new Map()
  for (const selection of selectedCorpusFragments.value) {
    const source = selection.source
    if (!source.revisionId) throw new Error('语料版本身份不完整，请重新加载完整语料库。')
    if (!groups.has(source.id)) {
      groups.set(source.id, {
        id: source.id,
        revisionId: source.revisionId,
        revision: source.revision,
        contentHash: source.contentHash,
        selectionMode: 'author',
        pinnedHistoricalRevision: false,
        fragments: [],
      })
    }
    groups.get(source.id).fragments.push({
      chapterId: selection.chapterId,
      fragmentId: selection.fragmentId,
      fragmentHash: selection.fragmentHash,
      chapterCharStart: selection.chapterCharStart,
      chapterCharEnd: selection.chapterCharEnd,
      referenceUse: selection.referenceUse,
    })
  }
  return [...groups.values()]
}

async function saveAndContinue() {
  if (contractStore.saving || contractStore.requiresReload) return
  const current = draftValues.value
  if (!current?.engineOptionId || !current?.primaryStyleRef) {
    await showError('风格草稿已失效，请返回上一步重新加载。')
    return
  }
  try {
    const saved = await contractStore.saveDraft(props.projectId, {
      ...current,
      draftStage: 'assets',
      experienceCardRefs: selectedExperienceIds.value.map(exactExperienceRef),
      corpusSourceRefs: corpusRefs(),
    })
    if (contractStore.draft !== saved) {
      await showError('保存期间素材范围发生变化，请重新加载并核对。')
      return
    }
    emit('dirty-change', false)
    emit('saved', saved)
  } catch (error) {
    await showError(error?.message || '创作资产范围保存失败')
  }
}

watch(() => props.projectId, projectId => void initialize(String(projectId || '')), { immediate: true })
onBeforeUnmount(() => { loadEpoch += 1; fragmentEpoch += 1 })
</script>

<template>
  <section class="asset-step" aria-labelledby="asset-step-heading">
    <header class="step-heading"><div><p>STEP 03 · REFERENCE SCOPE</p><h2 id="asset-step-heading">逐项授权，片段级冻结</h2><span>推荐只是候选，任何经验卡或语料片段都不会默认勾选；推荐为空时仍可浏览完整库。</span></div><b aria-hidden="true">03</b></header>

    <n-alert v-if="loadError" type="error" class="state-alert" title="创作资产未能加载">{{ loadError }}<template #action><n-button size="small" @click="initialize(props.projectId, { reloadContract: true })">重新加载并核对</n-button></template></n-alert>
    <div v-if="loading" class="loading-grid" aria-busy="true"><section><n-skeleton text :repeat="6" /></section><section><n-skeleton text :repeat="6" /></section></div>

    <template v-else-if="!loadError">
      <section class="asset-section" aria-labelledby="experience-heading">
        <div class="section-title"><div><span>推荐经验卡</span><h3 id="experience-heading">方法候选</h3></div><strong>{{ selectedExperienceIds.length }} 张已选</strong></div>
        <n-empty v-if="!recommendedCards.length" description="当前没有经验卡推荐；完整经验库仍可浏览" />
        <div v-else class="card-grid">
          <article v-for="card in recommendedCards" :key="card.id" :class="{ selected: selectedExperienceIds.includes(card.id) }"><n-tag size="small" :bordered="false">{{ card.category }}</n-tag><h4>{{ card.title }}</h4><p>{{ card.method }}</p><div><n-tag v-for="reason in card.reasonCodes" :key="reason" size="small" :bordered="false">{{ reasonLabel(reason) }}</n-tag></div><n-button block size="small" :aria-pressed="selectedExperienceIds.includes(card.id)" @click="toggleExperience(card.id)">{{ selectedExperienceIds.includes(card.id) ? '移出范围' : '明确纳入' }}</n-button></article>
        </div>
        <label class="library-selector"><span>完整经验库</span><small>搜索并显式选择；清空表示不使用经验卡。</small><n-select :value="selectedExperienceIds" :options="experienceOptions" multiple filterable clearable max-tag-count="responsive" @update:value="updateExperienceSelection" /></label>
        <div class="selection-ledger" aria-live="polite"><span v-for="card in selectedExperienceCards" :key="card.id">{{ card.title || card.id }} · r{{ card.revision }}</span></div>
      </section>

      <section class="asset-section corpus-section" aria-labelledby="corpus-heading">
        <div class="section-title"><div><span>完整语料库</span><h3 id="corpus-heading">选择来源，再圈定片段与字数范围</h3></div><strong>{{ selectedCorpusFragments.length }} 个片段</strong></div>
        <div class="budget-meter" role="status" aria-live="polite"><span>有界预览预算</span><strong>{{ previewBudgetUsed }} / 4000 字</strong><small>剩余 {{ previewBudgetRemaining }} 字；单个范围最多 300 字。</small></div>
        <n-empty v-if="!visibleCorpusSources.length" description="完整语料库暂无可用来源；可以零选继续" />
        <div v-else class="source-list"><button v-for="source in visibleCorpusSources" :key="source.id" type="button" :class="{ active: corpusBrowserSource?.id === source.id }" @click="chooseCorpusSource(source)"><strong>{{ source.name }}</strong><span>r{{ source.revision }} · {{ source.fragmentCount || 0 }} 片段 · {{ source.shortHash }}</span></button></div>

        <section v-if="corpusBrowserSource" class="fragment-browser">
          <header><div><span>当前来源</span><h4>{{ corpusBrowserSource.name }}</h4></div><n-select :value="selectedChapterId" :options="chapterOptions" placeholder="选择章节" @update:value="chooseChapter" /></header>
          <n-spin :show="corpusStore.loadingFragments">
            <n-empty v-if="!corpusStore.loadingFragments && !fragments.length" description="当前章节没有可选片段" />
            <article v-for="fragment in fragments" :key="fragment.id" :class="{ selected: selectedFragment(corpusBrowserSource.id, selectedChapterId, fragment.id) }">
              <div><span>片段 {{ fragment.order }}</span><small>{{ fragment.charStart }}–{{ fragment.charEnd }}</small></div><p>{{ fragment.preview }}</p><n-button size="small" @click="toggleFragment(fragment)">{{ selectedFragment(corpusBrowserSource.id, selectedChapterId, fragment.id) ? '移出范围' : '选择片段' }}</n-button>
            </article>
            <n-button v-if="fragmentPage?.nextCursor != null" block secondary class="load-more" :loading="corpusStore.loadingFragments" @click="loadMoreFragments">加载更多片段</n-button>
          </n-spin>
        </section>

        <section v-if="selectedCorpusFragments.length" class="range-ledger" aria-labelledby="selected-fragments-heading"><h4 id="selected-fragments-heading">已选片段与范围</h4><article v-for="selection in selectedCorpusFragments" :key="selection.key"><div><strong>{{ selection.source.name }}</strong><small>{{ selection.preview }}</small></div><label><span>起</span><n-input-number :value="selection.chapterCharStart" :min="selection.fragmentMin" :max="selection.fragmentMax - 1" @update:value="value => updateFragment(selection, 'chapterCharStart', value)" /></label><label><span>止</span><n-input-number :value="selection.chapterCharEnd" :min="selection.fragmentMin + 1" :max="selection.fragmentMax" @update:value="value => updateFragment(selection, 'chapterCharEnd', value)" /></label><n-select :value="selection.referenceUse" :options="[{ label: '文风', value: 'style' }, { label: '结构', value: 'structure' }, { label: '灵感', value: 'inspiration' }, { label: '事实核对', value: 'fact_check' }]" @update:value="value => updateReferenceUse(selection, value)" /><n-button quaternary size="small" @click="removeFragment(selection)">移出</n-button></article></section>
        <p v-if="selectedCorpusSources.length" class="source-count">已授权 {{ selectedCorpusSources.length }} 个来源，只冻结上列片段，不把整书送入生成。</p>
      </section>
    </template>

    <n-alert v-if="saveError" ref="errorRegion" tabindex="-1" type="error" class="state-alert" aria-live="assertive">{{ saveError }}</n-alert>
    <footer class="step-actions"><n-button secondary @click="emit('back')">返回风格契约</n-button><div><small>零选择会明确保存为空；推荐不会自动纳入。</small><n-button type="primary" size="large" :loading="contractStore.saving" :disabled="loading || contractStore.saving || contractStore.requiresReload || Boolean(loadError)" @click="saveAndContinue">保存草稿并继续</n-button></div></footer>
  </section>
</template>

<style scoped>
.asset-step { color: #302b24; }
.step-heading { display: flex; justify-content: space-between; gap: 24px; padding-bottom: 22px; border-bottom: 1px solid #d9cfbb; }
.step-heading p, .section-title span { margin: 0; color: #9c3d2f; font: 800 10px Georgia, serif; letter-spacing: .16em; }
.step-heading h2 { margin: 7px 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(25px, 4vw, 36px); }
.step-heading div > span { color: #766c5e; font-size: 12px; line-height: 1.8; }
.step-heading b { color: #c9baa1; font: 50px Georgia, serif; }
.state-alert { margin-top: 17px; }
.loading-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 24px; }
.loading-grid section { padding: 22px; border: 1px solid #ddd2be; background: #fffdf8; }
.asset-section { margin-top: 28px; }
.section-title { display: flex; align-items: end; justify-content: space-between; gap: 16px; margin-bottom: 13px; }
.section-title h3 { margin: 4px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 21px; }
.section-title > strong { color: #4f725b; font-size: 11px; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 11px; }
.card-grid article { display: flex; min-height: 250px; flex-direction: column; padding: 16px; border: 1px solid #ddd2be; border-radius: 10px; background: #fffdf8; }
.card-grid article.selected { border-color: #5d7b63; box-shadow: inset 0 3px 0 #5d7b63; }
.card-grid h4 { margin: 14px 0 6px; font-family: 'Noto Serif SC', serif; }
.card-grid p { color: #675f54; font-size: 11px; line-height: 1.7; }
.card-grid article > div { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 12px; }
.card-grid :deep(.n-button) { margin-top: auto; }
.library-selector { display: grid; gap: 6px; margin-top: 14px; padding: 16px; border: 1px solid #d8cdb9; background: #f8f4e9; }
.library-selector > span { font-weight: 700; }
.library-selector small { color: #877b6a; }
.selection-ledger { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.selection-ledger span { padding: 4px 8px; border-radius: 999px; background: #eee7da; font-size: 10px; }
.corpus-section { padding-top: 26px; border-top: 1px solid #dcd2c1; }
.budget-meter { display: grid; grid-template-columns: 1fr auto; gap: 3px 14px; margin-bottom: 13px; padding: 13px 15px; border-left: 4px solid #9c3d2f; background: #f5eee1; }
.budget-meter span { color: #9c3d2f; font-size: 10px; font-weight: 800; }
.budget-meter small { grid-column: 1 / -1; color: #776d60; font-size: 10px; }
.source-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 8px; }
.source-list button { display: grid; gap: 5px; padding: 13px; border: 1px solid #ddd2be; border-radius: 8px; color: #302b24; text-align: left; background: #fffdf8; cursor: pointer; }
.source-list button.active { border-color: #4f725b; box-shadow: inset 3px 0 0 #4f725b; }
.source-list span { color: #867969; font-size: 9px; }
.fragment-browser { margin-top: 14px; padding: 16px; border: 1px solid #d3c5af; background: #f8f3e8; }
.fragment-browser > header { display: grid; grid-template-columns: 1fr minmax(220px, .7fr); align-items: end; gap: 14px; }
.fragment-browser header span { color: #9c3d2f; font-size: 9px; font-weight: 800; }
.fragment-browser h4 { margin: 4px 0 0; font-family: 'Noto Serif SC', serif; }
.fragment-browser article { display: grid; grid-template-columns: 100px 1fr auto; align-items: center; gap: 12px; margin-top: 8px; padding: 12px; border: 1px solid #e0d5c3; background: #fffdf8; }
.fragment-browser article.selected { border-color: #4f725b; }
.fragment-browser article > div { display: grid; gap: 3px; color: #9c3d2f; font-size: 10px; }
.fragment-browser article small { color: #897c6a; }
.fragment-browser article p { margin: 0; color: #635b50; font-size: 11px; line-height: 1.65; }
.range-ledger { margin-top: 15px; }
.range-ledger > h4 { font-family: 'Noto Serif SC', serif; }
.range-ledger article { display: grid; grid-template-columns: minmax(180px, 1fr) 110px 110px 130px auto; align-items: end; gap: 8px; padding: 11px 0; border-top: 1px dashed #d9ccb7; }
.range-ledger article > div { display: grid; min-width: 0; gap: 4px; }
.range-ledger article small { overflow: hidden; color: #827667; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.range-ledger label { display: grid; gap: 3px; }
.range-ledger label span { color: #8c7e6b; font-size: 9px; }
.source-count { color: #776d60; font-size: 10px; }
.step-actions { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-top: 26px; padding-top: 20px; border-top: 1px solid #ded5c4; }
.step-actions > div { display: flex; align-items: center; gap: 13px; }
.step-actions small { color: #8a8071; font-size: 10px; }
@media (max-width: 900px) { .range-ledger article { grid-template-columns: 1fr 1fr; } .range-ledger article > div { grid-column: 1 / -1; } }
@media (max-width: 680px) { .loading-grid { grid-template-columns: 1fr; } .step-heading, .section-title, .step-actions, .step-actions > div { align-items: stretch; flex-direction: column; } .fragment-browser > header, .fragment-browser article { grid-template-columns: 1fr; } .range-ledger article { grid-template-columns: 1fr; } }
</style>
