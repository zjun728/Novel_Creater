<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { NAlert, NButton, NCheckbox, NCollapse, NCollapseItem, NInput, NSpin, NTag } from 'naive-ui'

import { useCreationContractStore } from '@/stores/creationContractStore.js'

const props = defineProps({
  projectId: { type: String, required: true },
  project: { type: Object, default: null },
  selectedSeed: { type: Object, default: null },
})
const emit = defineEmits(['saved', 'dirty-change', 'busy-change'])
const store = useCreationContractStore()
const selectedOptionId = ref('')
const manualOpen = ref(false)
const allowNewBatchAfterUnknown = ref(false)
const errorMessage = ref('')
const errorRegion = ref(null)
const recoveryNotice = ref('')

function blankManualOption(index) {
  return {
    name: `手动方案${['甲', '乙', '丙'][index]}`,
    storyPromise: '', protagonistDesire: '', sustainedPressure: '',
    growthDirection: '', conflictLoop: '', ensembleRolesText: '',
    advantageAndCost: '', satisfactionSourcesText: '', longFormVariationText: '',
    endingAnchor: '', risksText: '', differentiation: '',
  }
}
const manualOptions = ref([0, 1, 2].map(blankManualOption))

const batch = computed(() => store.engineBatch)
const options = computed(() => Array.isArray(batch.value?.options) ? batch.value.options : [])
const selectedOption = computed(() => options.value.find(option => option.id === selectedOptionId.value) || null)
const currentDraft = computed(() => store.draft?.draft || null)
const channelProfileKey = ref(String(
  currentDraft.value?.channelProfileKey
  || props.project?.channelProfileKey
  || '',
))
const genreProfileKey = ref(String(
  currentDraft.value?.genreProfileKey
  || props.project?.genreProfileKey
  || props.selectedSeed?.genre
  || props.project?.genre
  || '',
))

function idempotencyKey(prefix) {
  const random = globalThis.crypto?.randomUUID?.().replaceAll('-', '')
    || `${Date.now()}${Math.random().toString(36).slice(2)}`
  return `${prefix}-${random}`.replace(/[^A-Za-z0-9_-]/gu, '').slice(0, 64)
}

async function showError(message) {
  errorMessage.value = String(message || '故事发动机操作失败')
  await nextTick()
  errorRegion.value?.focus({ preventScroll: false })
}

function markDirty() {
  if (store.saving) return
  store.markUnsavedChanges()
  emit('dirty-change', true)
}

function installBatch(result) {
  if (result?.status === 'failed') {
    throw new Error(`故事发动机生成失败${result.publicErrorCode ? `（${result.publicErrorCode}）` : ''}`)
  }
  if (result?.status === 'succeeded' && result.options?.length !== 3) {
    throw new Error('故事发动机返回结果不完整：必须恰好包含三套方案')
  }
  if (result?.status === 'succeeded') {
    selectedOptionId.value = ''
    allowNewBatchAfterUnknown.value = false
  }
  return result
}

async function generateProviderBatch() {
  if (store.saving) return
  if (store.providerOutcomeUnknown && !allowNewBatchAfterUnknown.value) {
    await showError('上一批次结果仍未知。请先核对；若仍需新建，请明确确认。')
    return
  }
  errorMessage.value = ''
  emit('busy-change', true)
  try {
    installBatch(await store.generateEngineBatch(props.projectId, {
      idempotencyKey: idempotencyKey('engine-provider'),
    }))
  } catch (error) {
    await showError(error?.message || '故事发动机生成失败')
  } finally {
    emit('busy-change', false)
  }
}

async function reconcileUnknownBatch() {
  if (!batch.value?.id || store.saving) return
  errorMessage.value = ''
  try {
    installBatch(await store.reconcileBatch(props.projectId, batch.value.id))
  } catch (error) {
    await showError(error?.message || '批次核对失败')
  }
}

function boundedBatchId(value) {
  return String(value || '').slice(-8)
}

async function reconcileRecoverable(item) {
  recoveryNotice.value = ''
  errorMessage.value = ''
  try {
    const result = await store.reconcileRecoverableBatch(props.projectId, item.id)
    if (!result) return
    recoveryNotice.value = result.status === 'outcome_unknown'
      ? '结果未知，系统不会自动重试'
      : '批次状态已安全核对'
  } catch (error) {
    await showError(error?.message || '批次核对失败')
  }
}

function nonemptyLines(value, label) {
  const rows = String(value || '').split(/\r?\n/u).map(item => item.trim()).filter(Boolean)
  if (!rows.length) throw new Error(`${label}至少填写一条。`)
  return rows
}

function ensembleRoles(value) {
  return nonemptyLines(value, '群像角色').map(line => {
    const [role, ...purposeParts] = line.split(/[：:]/u)
    const purpose = purposeParts.join('：').trim()
    if (!role?.trim() || !purpose) throw new Error('群像角色请使用“角色：作用”，每行一组。')
    return { role: role.trim(), purpose }
  })
}

function manualOption(value, index) {
  const textFields = [
    ['name', '方案名称'], ['storyPromise', '故事承诺'],
    ['protagonistDesire', '主角欲望'], ['sustainedPressure', '持续压力'],
    ['growthDirection', '成长方向'], ['conflictLoop', '冲突循环'],
    ['advantageAndCost', '优势与代价'], ['endingAnchor', '结局锚点'],
    ['differentiation', '差异化'],
  ]
  const normalized = {}
  for (const [field, label] of textFields) {
    normalized[field] = String(value[field] || '').trim()
    if (!normalized[field]) throw new Error(`方案${index + 1}的${label}不能为空。`)
  }
  return {
    ...normalized,
    ensembleRoles: ensembleRoles(value.ensembleRolesText),
    satisfactionSources: nonemptyLines(value.satisfactionSourcesText, '满足感来源'),
    longFormVariation: nonemptyLines(value.longFormVariationText, '长线变化'),
    risks: nonemptyLines(value.risksText, '风险'),
  }
}

async function createManualBatch() {
  if (store.saving || store.engineLoading) return
  errorMessage.value = ''
  emit('busy-change', true)
  try {
    const result = await store.createManualEngineBatch(props.projectId, {
      idempotencyKey: idempotencyKey('engine-manual'),
      options: manualOptions.value.map(manualOption),
    })
    installBatch(result)
    manualOpen.value = false
    manualOptions.value = [0, 1, 2].map(blankManualOption)
  } catch (error) {
    await showError(error?.message || '手动方案建立失败')
  } finally {
    emit('busy-change', false)
  }
}

function chooseOption(option) {
  if (store.saving || store.engineLoading) return
  selectedOptionId.value = option.id
  markDirty()
}

function provisionalCapacity() {
  const existing = currentDraft.value
  const projectWords = Number(props.project?.targetWords)
  const target = Number(existing?.targetTotalWords)
    || (Number.isInteger(projectWords) && projectWords > 0 ? projectWords : 100_000)
  const projectChapters = Number(props.project?.targetChapters)
  const chapters = Number(existing?.expectedChapterCount)
    || (Number.isInteger(projectChapters) && projectChapters > 0
      ? projectChapters
      : Math.max(1, Math.round(target / 3_000)))
  const perChapter = Math.max(1, Math.round(target / chapters))
  return {
    targetTotalWords: target,
    expectedVolumeCount: Number(existing?.expectedVolumeCount)
      || Math.max(1, Math.ceil(chapters / 50)),
    expectedChapterCount: chapters,
    chapterWordRangePreference: Array.isArray(existing?.chapterWordRangePreference)
      ? [...existing.chapterWordRangePreference]
      : [Math.max(1, Math.round(perChapter * .85)), Math.max(1, Math.round(perChapter * 1.15))],
    prohibitedDirections: Array.isArray(existing?.prohibitedDirections)
      ? [...existing.prohibitedDirections]
      : [],
    authorNotes: existing?.authorNotes ?? null,
  }
}

async function saveAndContinue() {
  if (store.saving || store.engineLoading || store.requiresReload || !selectedOption.value) return
  errorMessage.value = ''
  const channelProfile = channelProfileKey.value.trim()
  const genreProfile = genreProfileKey.value.trim()
  if (!channelProfile || !genreProfile) {
    await showError('渠道定位标识和题材定位标识均不能为空。')
    return
  }
  try {
    const option = selectedOption.value
    const saved = await store.saveDraft(props.projectId, {
      schemaVersion: 'contract-draft-v2',
      draftStage: 'engine',
      engineOptionId: option.id,
      engineHash: option.contentHash,
      channelProfileKey: channelProfile,
      genreProfileKey: genreProfile,
      qualityCharterVersion: String(currentDraft.value?.qualityCharterVersion || 'story-first-quality-v1'),
      ...provisionalCapacity(),
      primaryStyleRef: null,
      secondaryStyleRef: null,
      experienceCardRefs: null,
      corpusSourceRefs: null,
      likes: null,
      dislikes: null,
    })
    if (store.draft !== saved) {
      await showError('保存期间选择发生变化，请核对当前方案后再次保存。')
      return
    }
    emit('dirty-change', false)
    emit('saved', { draft: saved, option })
  } catch (error) {
    await showError(error?.message || '故事发动机草稿保存失败')
  }
}

function optionPayload(option) {
  return option?.payload || {}
}

watch(options, rows => {
  const savedId = currentDraft.value?.engineOptionId
  if (rows.some(option => option.id === savedId)) selectedOptionId.value = savedId
}, { immediate: true })
</script>

<template>
  <section class="engine-step" aria-labelledby="engine-step-heading">
    <header class="step-heading">
      <div>
        <p class="folio">STEP 01 · STORY ENGINE</p>
        <h2 id="engine-step-heading">选择能持续制造故事的发动机</h2>
        <p>比较长期承诺、持续压力、冲突循环、群像位置与必须付出的代价；不会在这里假定渠道或题材。</p>
      </div>
      <div class="generation-actions">
        <n-button secondary :disabled="store.saving" @click="manualOpen = !manualOpen">普通字段手动录入</n-button>
        <n-button type="primary" :loading="store.engineLoading && !store.reconciling" :disabled="store.saving" @click="generateProviderBatch">{{ batch ? '生成新三案' : '生成三套方案' }}</n-button>
      </div>
    </header>

    <n-alert v-if="errorMessage" ref="errorRegion" tabindex="-1" type="error" class="state-alert" aria-live="assertive">{{ errorMessage }}</n-alert>

    <section class="profile-fields" aria-labelledby="story-profile-heading">
      <header>
        <span>AUTHOR POSITIONING</span>
        <h3 id="story-profile-heading">明确渠道与题材定位</h3>
        <p>系统只用项目与当前种子提供初值；最终标识由作者核对并可直接修改，不会自动补造。</p>
      </header>
      <label>
        <span>渠道定位标识</span>
        <small>例如你在项目中维护的真实渠道键；不能为空。</small>
        <n-input v-model:value="channelProfileKey" maxlength="120" @update:value="markDirty" />
      </label>
      <label>
        <span>题材定位标识</span>
        <small>可沿用当前种子题材，也可以在签约前改成更准确的标识。</small>
        <n-input v-model:value="genreProfileKey" maxlength="120" @update:value="markDirty" />
      </label>
    </section>

    <section v-if="store.recoverableBatches.length" class="recovery-ledger">
      <h3>待核对的故事发动机批次</h3>
      <n-alert v-if="recoveryNotice" type="info">{{ recoveryNotice }}</n-alert>
      <article v-for="item in store.recoverableBatches" :key="item.id">
        <span>{{ item.status }} · {{ boundedBatchId(item.id) }}</span>
        <n-button size="small" :loading="store.reconcilingBatchIds.includes(item.id)" @click="reconcileRecoverable(item)">核对本批次结果</n-button>
      </article>
    </section>

    <n-alert v-if="store.providerOutcomeUnknown" type="warning" class="state-alert" title="上一批生成结果尚不确定">
      <p>系统不会暗中重试。请先核对原批次；仍要放弃时，再明确确认新建。</p>
      <div class="unknown-actions">
        <n-button size="small" :loading="store.reconciling" @click="reconcileUnknownBatch">核对本批次结果</n-button>
        <n-checkbox v-model:checked="allowNewBatchAfterUnknown">我确认核对后仍要新建批次</n-checkbox>
      </div>
    </n-alert>

    <section v-if="manualOpen" class="manual-sheet" aria-labelledby="manual-engine-heading">
      <header><span>MANUAL / THREE DISTINCT OPTIONS</span><h3 id="manual-engine-heading">用普通命名字段建立三套方案</h3><p>每套方案都必须完整；多项内容每行一条，群像角色使用“角色：作用”。</p></header>
      <article v-for="(option, index) in manualOptions" :key="index" class="manual-option">
        <h4>方案 {{ ['甲', '乙', '丙'][index] }}</h4>
        <label><span>方案名称</span><n-input v-model:value="option.name" @update:value="markDirty" /></label>
        <label><span>故事承诺</span><n-input v-model:value="option.storyPromise" type="textarea" @update:value="markDirty" /></label>
        <label><span>主角欲望</span><n-input v-model:value="option.protagonistDesire" type="textarea" @update:value="markDirty" /></label>
        <label><span>持续压力</span><n-input v-model:value="option.sustainedPressure" type="textarea" @update:value="markDirty" /></label>
        <label><span>成长方向</span><n-input v-model:value="option.growthDirection" type="textarea" @update:value="markDirty" /></label>
        <label><span>冲突循环</span><n-input v-model:value="option.conflictLoop" type="textarea" @update:value="markDirty" /></label>
        <label><span>群像角色</span><n-input v-model:value="option.ensembleRolesText" type="textarea" placeholder="同行者：迫使主角为选择负责" @update:value="markDirty" /></label>
        <label><span>优势与代价</span><n-input v-model:value="option.advantageAndCost" type="textarea" @update:value="markDirty" /></label>
        <label><span>满足感来源</span><n-input v-model:value="option.satisfactionSourcesText" type="textarea" @update:value="markDirty" /></label>
        <label><span>长线变化</span><n-input v-model:value="option.longFormVariationText" type="textarea" @update:value="markDirty" /></label>
        <label><span>结局锚点</span><n-input v-model:value="option.endingAnchor" type="textarea" @update:value="markDirty" /></label>
        <label><span>风险</span><n-input v-model:value="option.risksText" type="textarea" @update:value="markDirty" /></label>
        <label><span>差异化</span><n-input v-model:value="option.differentiation" type="textarea" @update:value="markDirty" /></label>
      </article>
      <footer><n-button @click="manualOpen = false">收起</n-button><n-button type="primary" :loading="store.engineLoading" @click="createManualBatch">建立手动三案</n-button></footer>
    </section>

    <n-spin :show="store.engineLoading">
      <div v-if="options.length" class="engine-grid" role="radiogroup" aria-label="故事发动机方案">
        <article v-for="(option, index) in options" :key="option.id" class="engine-card" :class="{ 'engine-card--selected': selectedOptionId === option.id }" role="radio" :aria-checked="selectedOptionId === option.id" tabindex="0" @click="chooseOption(option)" @keydown.enter.prevent="chooseOption(option)" @keydown.space.prevent="chooseOption(option)">
          <div class="card-head"><span>案 {{ ['甲', '乙', '丙'][index] }}</span><i aria-hidden="true"></i></div>
          <h3>{{ optionPayload(option).name }}</h3>
          <p>{{ optionPayload(option).storyPromise }}</p>
          <dl><div><dt>持续压力</dt><dd>{{ optionPayload(option).sustainedPressure }}</dd></div><div><dt>冲突循环</dt><dd>{{ optionPayload(option).conflictLoop }}</dd></div><div><dt>优势与代价</dt><dd>{{ optionPayload(option).advantageAndCost }}</dd></div></dl>
          <n-collapse><n-collapse-item title="风险与差异化" name="detail"><ul><li v-for="risk in optionPayload(option).risks || []" :key="risk">{{ risk }}</li></ul><p>{{ optionPayload(option).differentiation }}</p></n-collapse-item></n-collapse>
        </article>
      </div>
      <div v-else class="empty-engine"><i aria-hidden="true">三</i><h3>尚未形成可比较的三案</h3><p>显式调用已绑定的 Provider，或用命名字段一次建立三套手动方案。</p></div>
    </n-spin>

    <footer class="step-actions"><span><n-tag :bordered="false">所选种子只读</n-tag> {{ props.selectedSeed?.title }}</span><n-button type="primary" size="large" :loading="store.saving" :disabled="store.saving || store.engineLoading || store.requiresReload || !selectedOption" @click="saveAndContinue">保存草稿并继续</n-button></footer>
  </section>
</template>

<style scoped>
.engine-step { color: #302b24; }
.step-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; padding-bottom: 22px; border-bottom: 1px solid #cfc1a8; }
.step-heading > div:first-child { max-width: 740px; }
.folio, .manual-sheet header > span { margin: 0; color: #9c3f32; font: 800 10px Georgia, serif; letter-spacing: .18em; }
.step-heading h2 { margin: 7px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(24px, 4vw, 34px); }
.step-heading p:not(.folio), .manual-sheet header p { margin: 9px 0 0; color: #756b5d; font-size: 12px; line-height: 1.8; }
.generation-actions, .unknown-actions { display: flex; gap: 8px; }
.state-alert, .recovery-ledger { margin-top: 16px; }
.profile-fields { display: grid; grid-template-columns: minmax(210px, 1.15fr) repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 18px; padding: 17px; border: 1px solid #d4c5aa; background: #faf6ec; }
.profile-fields header span { color: #9c3f32; font: 800 9px Georgia, serif; letter-spacing: .15em; }
.profile-fields header h3 { margin: 5px 0 0; font-family: 'Noto Serif SC', serif; font-size: 15px; }
.profile-fields header p { margin: 6px 0 0; color: #756b5d; font-size: 10px; line-height: 1.65; }
.profile-fields label { display: grid; align-content: start; gap: 6px; }
.profile-fields label > span { color: #5f5548; font-size: 11px; font-weight: 750; }
.profile-fields label > small { color: #8c7f6d; font-size: 9px; line-height: 1.5; }
.recovery-ledger { padding: 17px; border: 1px solid #d4c5aa; background: #faf6ec; }
.recovery-ledger h3 { margin: 0 0 10px; font-family: 'Noto Serif SC', serif; }
.recovery-ledger article { display: flex; align-items: center; justify-content: space-between; padding: 9px 0; border-top: 1px dashed #d9ccb7; color: #756b5d; font-size: 11px; }
.manual-sheet { margin-top: 18px; padding: 20px; border: 1px solid #cbb99c; background: #f9f4e9; }
.manual-sheet header h3 { margin: 5px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 21px; }
.manual-option { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 16px; padding: 16px; border: 1px solid #ded2bd; background: #fffdf8; }
.manual-option h4 { grid-column: 1 / -1; margin: 0; color: #4f725b; font-family: 'Noto Serif SC', serif; }
.manual-option label { display: grid; gap: 5px; }
.manual-option label > span { color: #736858; font-size: 10px; font-weight: 700; }
.manual-sheet footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 14px; }
.engine-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 20px; }
.engine-card { padding: 20px; border: 1px solid #d4c5aa; border-radius: 3px 12px 12px 3px; background: linear-gradient(155deg, #fffdf8, #f2ead8); cursor: pointer; }
.engine-card:focus-visible { outline: 2px solid #4f725b; outline-offset: 3px; }
.engine-card--selected { border-color: #6c8a78; box-shadow: inset 0 4px 0 #4f725b; }
.card-head { display: flex; justify-content: space-between; color: #9c3f32; font: 700 11px Georgia, serif; }
.card-head i { width: 12px; height: 12px; border: 1px solid #a99b84; border-radius: 50%; }
.engine-card--selected .card-head i { background: #4f725b; box-shadow: inset 0 0 0 3px #fff; }
.engine-card h3 { margin: 18px 0 8px; font-family: Georgia, 'Noto Serif SC', serif; }
.engine-card > p, .engine-card dd { color: #675e52; font-size: 12px; line-height: 1.7; }
.engine-card dl { display: grid; gap: 9px; padding-top: 12px; border-top: 1px solid #dfd3be; }
.engine-card dt { color: #9c3f32; font-size: 9px; font-weight: 800; }
.engine-card dd { margin: 3px 0 0; }
.empty-engine { display: grid; justify-items: center; margin-top: 20px; padding: 46px 20px; border: 1px dashed #c9b99f; text-align: center; }
.empty-engine i { display: grid; width: 46px; height: 46px; place-items: center; border: 2px solid #9c3f32; color: #9c3f32; font: 22px Georgia, serif; font-style: normal; }
.empty-engine h3 { margin: 14px 0 5px; font-family: 'Noto Serif SC', serif; }
.empty-engine p { margin: 0; color: #756b5d; font-size: 11px; }
.step-actions { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 24px; padding-top: 20px; border-top: 1px solid #d9ccb7; color: #766c5e; font-size: 11px; }
@media (max-width: 980px) { .engine-grid { grid-template-columns: 1fr; } }
@media (max-width: 720px) { .step-heading, .step-actions { align-items: stretch; flex-direction: column; } .generation-actions, .unknown-actions { align-items: stretch; flex-direction: column; } .profile-fields, .manual-option { grid-template-columns: 1fr; } .manual-option h4 { grid-column: 1; } }
</style>
