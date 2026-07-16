<script setup>
import { computed, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCheckbox,
  NCollapse,
  NCollapseItem,
  NInput,
  NSpin,
  NTag,
} from 'naive-ui'

import { useCreationContractStore } from '@/stores/creationContractStore'

const props = defineProps({
  projectId: { type: String, required: true },
  project: { type: Object, default: null },
})

const emit = defineEmits(['saved', 'back', 'dirty-change'])
const store = useCreationContractStore()
const selectedOptionId = ref('')
const manualJson = ref('')
const manualOpen = ref(false)
const allowNewBatchAfterUnknown = ref(false)
const errorMessage = ref('')
const recoveryNotice = ref('')
const localDirty = ref(false)

const batch = computed(() => store.engineBatch)
const options = computed(() => Array.isArray(batch.value?.options) ? batch.value.options : [])
const selectedOption = computed(() => options.value.find(option => option.id === selectedOptionId.value) || null)
const savedEngineId = computed(() => (
  store.draft?.draft?.engineOptionId
  || store.draft?.engineOptionId
  || ''
))
const selectedSeedGenre = computed(() => (
  batch.value?.options?.[0]?.payload?.genre
  || ''
))
const genreProfileKey = computed(() => String(
  props.project?.genre || selectedSeedGenre.value || '玄幻',
).trim())
const targetWords = computed(() => {
  const value = Number(props.project?.targetWords || 1_500_000)
  return Number.isFinite(value) && value > 0 ? Math.round(value) : 1_500_000
})
const totalWordRange = computed(() => {
  const center = targetWords.value
  const low = Math.max(100_000, Math.round(center * 0.9))
  return [low, Math.max(low, Math.round(center * 1.1))]
})

function idempotencyKey(prefix) {
  const random = globalThis.crypto?.randomUUID?.().slice(0, 12)
    || Math.random().toString(36).slice(2, 14)
  return `${prefix}-${Date.now()}-${random}`.slice(0, 64)
}

function safeMessage(error, fallback) {
  return String(error?.message || fallback)
}

function setDirty(value) {
  if (value) store.markUnsavedChanges()
  if (localDirty.value === value) return
  localDirty.value = value
  if (!value) store.discardUnsavedChanges()
  emit('dirty-change', value)
}

function syncDirty() {
  setDirty(Boolean(
    (selectedOptionId.value && selectedOptionId.value !== savedEngineId.value)
    || manualJson.value.trim(),
  ))
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
    setDirty(Boolean(manualJson.value.trim()))
  }
  return result
}

async function generateProviderBatch() {
  if (store.saving) return
  if (store.providerOutcomeUnknown && !allowNewBatchAfterUnknown.value) {
    errorMessage.value = '上一批次结果仍未知。请先核对；若仍需新建，请勾选明确确认。'
    return
  }
  if (store.providerOutcomeUnknown) allowNewBatchAfterUnknown.value = false
  errorMessage.value = ''
  try {
    const result = await store.generateEngineBatch(props.projectId, {
      idempotencyKey: idempotencyKey('engine-provider'),
    })
    installBatch(result)
  } catch (error) {
    errorMessage.value = safeMessage(error, '故事发动机生成失败')
  }
}

async function reconcileUnknownBatch() {
  if (store.saving) return
  if (!batch.value?.id) return
  errorMessage.value = ''
  try {
    installBatch(await store.reconcileBatch(props.projectId, batch.value.id))
  } catch (error) {
    errorMessage.value = safeMessage(error, '批次核对失败')
  }
}

function boundedBatchId(batchId) {
  return String(batchId || '').slice(-8)
}

function recoveryStatusText(item) {
  return {
    reserved: '已预留，等待手动核对',
    running: '正在处理，等待手动核对',
    outcome_unknown: '结果未知，需要手动核对',
  }[item?.status] || '公开状态待核对'
}

async function reconcileRecoverable(item) {
  recoveryNotice.value = ''
  errorMessage.value = ''
  try {
    const result = await store.reconcileRecoverableBatch(props.projectId, item.id)
    if (!result) return
    if (result.status === 'failed' && result.publicErrorCode === 'not_started') {
      recoveryNotice.value = '未开始，已安全结束'
    } else if (result.status === 'outcome_unknown') {
      recoveryNotice.value = '结果未知，系统不会自动重试'
    }
  } catch (error) {
    errorMessage.value = safeMessage(error, '批次核对失败')
  }
}

function parseManualOptions() {
  let parsed
  try {
    parsed = JSON.parse(manualJson.value)
  } catch {
    throw new Error('手动方案不是有效 JSON')
  }
  const optionsValue = Array.isArray(parsed) ? parsed : parsed?.options
  if (!Array.isArray(optionsValue) || optionsValue.length !== 3) {
    throw new Error('手动 JSON 必须恰好包含三套方案')
  }
  return optionsValue
}

async function createManualBatch() {
  if (store.saving) return
  errorMessage.value = ''
  try {
    const result = await store.createManualEngineBatch(props.projectId, {
      idempotencyKey: idempotencyKey('engine-manual'),
      options: parseManualOptions(),
    })
    installBatch(result)
    manualJson.value = ''
    manualOpen.value = false
    setDirty(false)
  } catch (error) {
    errorMessage.value = safeMessage(error, '手动方案保存失败')
  }
}

function chooseOption(option) {
  if (store.saving) return
  selectedOptionId.value = option.id
  syncDirty()
}

async function saveAndContinue() {
  if (store.saving || store.engineLoading || store.requiresReload || !selectedOption.value) return
  errorMessage.value = ''
  try {
    const option = selectedOption.value
    const saved = await store.saveDraft(props.projectId, {
      schemaVersion: 'contract-draft-v2',
      draftStage: 'engine',
      engineOptionId: option.id,
      engineHash: option.contentHash,
      channelProfileKey: 'qidian-qq',
      genreProfileKey: genreProfileKey.value,
      qualityCharterVersion: 'story-first-quality-v1',
      totalWordRange: totalWordRange.value,
      chapterCapacityPolicy: '手动逐章定稿；故事块允许跨章滚动，未完成情节自然延续到下一章。',
      primaryStyleRef: null,
      secondaryStyleRef: null,
      experienceCardRefs: null,
      corpusSourceRefs: null,
      likes: null,
      dislikes: null,
    })
    if (store.draft !== saved) {
      errorMessage.value = '保存期间选择发生了变化，请核对当前方案后再次保存。'
      return
    }
    setDirty(false)
    emit('saved', { stage: 'engine', draft: saved, option })
  } catch (error) {
    errorMessage.value = safeMessage(error, '故事发动机方案保存失败')
  }
}

function optionPayload(option) {
  return option?.payload || {}
}

watch(options, rows => {
  if (rows.some(option => option.id === savedEngineId.value)) {
    selectedOptionId.value = savedEngineId.value
  }
}, { immediate: true })

watch(manualJson, syncDirty)
</script>

<template>
  <section class="engine-dossier" aria-labelledby="engine-step-heading">
    <header class="step-heading">
      <div>
        <p class="folio">第二纸 · 发动</p>
        <h3 id="engine-step-heading">选择能持续制造故事的发动机</h3>
        <p>这里不写整本大纲。三案只比较长期承诺、持续压力、冲突循环、群像位置和必须付出的代价。</p>
      </div>
      <div class="generation-actions">
        <n-button secondary :disabled="store.saving" @click="manualOpen = !manualOpen">高级手动 JSON</n-button>
        <n-button type="primary" :loading="store.engineLoading && !store.reconciling" :disabled="store.saving" @click="generateProviderBatch">
          {{ batch ? '生成新三案' : '生成三套方案' }}
        </n-button>
      </div>
    </header>

    <n-alert v-if="errorMessage" type="error" class="dossier-alert" closable @close="errorMessage = ''">
      {{ errorMessage }}
    </n-alert>

    <section
      v-if="store.recoverableBatches.length"
      class="recovery-ledger"
      aria-labelledby="recoverable-batches-heading"
    >
      <h4 id="recoverable-batches-heading">待恢复的故事发动机批次</h4>
      <n-alert v-if="recoveryNotice" type="info">{{ recoveryNotice }}</n-alert>
      <div class="recovery-rows">
        <article v-for="item in store.recoverableBatches" :key="item.id" class="recovery-row">
          <div>
            <p>{{ recoveryStatusText(item) }}</p>
            <code>{{ boundedBatchId(item.id) }}</code>
          </div>
          <n-button
            size="small"
            :aria-label="`核对批次 ${boundedBatchId(item.id)}`"
            :loading="store.reconcilingBatchIds.includes(item.id)"
            :disabled="store.reconcilingBatchIds.includes(item.id)"
            @click="reconcileRecoverable(item)"
          >
            核对本批次结果
          </n-button>
        </article>
      </div>
    </section>

    <n-alert v-if="store.providerOutcomeUnknown" type="warning" class="unknown-slip" title="上一批生成结果尚不确定">
      <p>系统不会暗中重试，也不会把未知结果当作失败。先用原批次号核对；确认仍要放弃它时，才新建另一批。</p>
      <div class="unknown-actions">
        <n-button size="small" :loading="store.reconciling" :disabled="store.saving" @click="reconcileUnknownBatch">核对本批次结果</n-button>
        <n-checkbox v-model:checked="allowNewBatchAfterUnknown" :disabled="store.saving">我确认核对后仍要新建批次</n-checkbox>
      </div>
    </n-alert>

    <aside v-if="manualOpen" class="manual-sheet">
      <div class="manual-copy">
        <span>ADVANCED / EXACTLY THREE</span>
        <h4>录入三套完整发动机方案</h4>
        <p>可粘贴数组，或含 <code>options</code> 的对象。每案须包含故事承诺、主角欲望、持续压力、成长方向、冲突循环、群像角色、优势与代价、爽点来源、长线变化、结局锚点、风险与差异化。</p>
      </div>
      <n-input
        v-model:value="manualJson"
        type="textarea"
        :autosize="{ minRows: 9, maxRows: 18 }"
        placeholder='[{ "name": "方案一", "storyPromise": "...", "protagonistDesire": "..." }, ...共三案]'
        :disabled="store.engineLoading || store.saving"
      />
      <div class="manual-actions">
        <n-button :disabled="store.saving" @click="manualOpen = false; manualJson = ''">取消</n-button>
        <n-button type="primary" :loading="store.engineLoading" :disabled="store.saving || !manualJson.trim()" @click="createManualBatch">
          建立手动三案
        </n-button>
      </div>
    </aside>

    <n-spin :show="store.engineLoading">
      <div v-if="options.length" class="engine-grid" role="radiogroup" aria-label="故事发动机方案">
        <article
          v-for="(option, index) in options"
          :key="option.id"
          class="engine-card"
          :class="{ 'engine-card--selected': selectedOptionId === option.id }"
          role="radio"
          :aria-checked="selectedOptionId === option.id"
          tabindex="0"
          @click="chooseOption(option)"
          @keydown.enter.prevent="chooseOption(option)"
          @keydown.space.prevent="chooseOption(option)"
        >
          <div class="card-head">
            <span class="option-mark">案 {{ ['甲', '乙', '丙'][index] || index + 1 }}</span>
            <span class="selection-dot" aria-hidden="true"></span>
          </div>
          <h4>{{ optionPayload(option).name }}</h4>
          <p class="promise">{{ optionPayload(option).storyPromise }}</p>

          <dl class="engine-facts">
            <div>
              <dt>持续压力</dt>
              <dd>{{ optionPayload(option).sustainedPressure }}</dd>
            </div>
            <div>
              <dt>冲突循环</dt>
              <dd>{{ optionPayload(option).conflictLoop }}</dd>
            </div>
            <div>
              <dt>优势与代价</dt>
              <dd>{{ optionPayload(option).advantageAndCost }}</dd>
            </div>
          </dl>

          <div class="ensemble-block">
            <span>群像位置</span>
            <ul>
              <li v-for="role in optionPayload(option).ensembleRoles || []" :key="`${role.role}-${role.purpose}`">
                <strong>{{ role.role }}</strong>{{ role.purpose }}
              </li>
            </ul>
          </div>

          <n-collapse arrow-placement="right" class="risk-notes">
            <n-collapse-item title="展开风险批注" name="risks">
              <ul><li v-for="risk in optionPayload(option).risks || []" :key="risk">{{ risk }}</li></ul>
              <p><b>差异化：</b>{{ optionPayload(option).differentiation }}</p>
            </n-collapse-item>
          </n-collapse>
        </article>
      </div>

      <div v-else class="empty-engine">
        <i aria-hidden="true">三</i>
        <h4>尚未形成可比较的三案</h4>
        <p>点击“生成三套方案”会显式调用已绑定的 Provider；也可以在高级入口一次录入恰好三套手动方案。</p>
      </div>
    </n-spin>

    <footer class="contract-strip">
      <div class="frozen-facts">
        <n-tag :bordered="false">起点 / QQ 阅读型</n-tag>
        <span>{{ genreProfileKey }}</span>
        <span>{{ (totalWordRange[0] / 10000).toFixed(0) }}–{{ (totalWordRange[1] / 10000).toFixed(0) }} 万字</span>
        <span>手动逐章定稿 · 故事块跨章滚动</span>
      </div>
      <div class="contract-actions">
        <n-button :disabled="store.saving" @click="emit('back')">返回种子</n-button>
        <n-button type="primary" size="large" :loading="store.saving" :disabled="store.saving || store.engineLoading || store.requiresReload || !selectedOption" @click="saveAndContinue">
          保存并继续
        </n-button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.engine-dossier {
  --paper: #f5efdf;
  --ink: #28241f;
  --muted: #756b5d;
  --cinnabar: #9c3f32;
  --jade: #496d5e;
  color: var(--ink);
}
.step-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; padding: 4px 2px 22px; border-bottom: 1px solid #cfc1a8; }
.step-heading > div:first-child { max-width: 760px; }
.folio { margin: 0 0 7px; color: var(--cinnabar); font-size: 11px; font-weight: 800; letter-spacing: .18em; }
.step-heading h3 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(22px, 3.5vw, 32px); font-weight: 650; letter-spacing: -.02em; }
.step-heading p:last-child { margin: 10px 0 0; color: var(--muted); font-size: 13px; line-height: 1.8; }
.generation-actions { display: flex; flex: 0 0 auto; gap: 8px; }
.dossier-alert, .unknown-slip { margin-top: 16px; background: rgba(255, 252, 244, .76); }
.recovery-ledger { margin-top: 16px; padding: 18px; border: 1px solid #cbb99c; background: rgba(255, 252, 244, .72); }
.recovery-ledger > h4 { margin: 0 0 12px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 17px; }
.recovery-rows { display: grid; gap: 9px; margin-top: 12px; }
.recovery-row { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 11px 13px; border-top: 1px solid #dfd3be; }
.recovery-row p { margin: 0 0 4px; color: var(--muted); font-size: 12px; }
.recovery-row code { color: var(--cinnabar); font-size: 11px; letter-spacing: .08em; }
.unknown-slip p { margin: 0 0 10px; line-height: 1.7; }
.unknown-actions { display: flex; align-items: center; gap: 16px; }
.manual-sheet { display: grid; grid-template-columns: minmax(210px, .65fr) minmax(360px, 1.35fr); gap: 22px; margin-top: 18px; padding: 22px; border: 1px solid #cbb99c; background: rgba(255, 252, 244, .9); box-shadow: 0 14px 34px rgba(69, 57, 39, .08); }
.manual-copy span { color: #927754; font-size: 10px; font-weight: 800; letter-spacing: .15em; }
.manual-copy h4 { margin: 6px 0 9px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 20px; }
.manual-copy p { margin: 0; color: var(--muted); font-size: 12px; line-height: 1.8; }
.manual-copy code { color: var(--cinnabar); }
.manual-actions { display: flex; grid-column: 2; justify-content: flex-end; gap: 8px; }
.engine-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 20px; }
.engine-card { position: relative; min-width: 0; padding: 21px; border: 1px solid #d4c5aa; border-radius: 3px 13px 13px 3px; background: linear-gradient(155deg, rgba(255, 253, 247, .98), rgba(242, 234, 216, .73)); box-shadow: 0 10px 26px rgba(70, 57, 39, .06); cursor: pointer; transition: border-color .2s ease, box-shadow .2s ease, transform .2s ease; }
.engine-card:hover { border-color: #ad9b7b; transform: translateY(-2px); }
.engine-card:focus-visible { outline: 2px solid var(--jade); outline-offset: 3px; }
.engine-card--selected { border-color: #789386; box-shadow: inset 0 4px 0 var(--jade), 0 15px 34px rgba(51, 79, 67, .12); }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.option-mark { color: var(--cinnabar); font-family: 'Noto Serif SC', serif; font-size: 12px; font-weight: 800; letter-spacing: .12em; }
.selection-dot { width: 13px; height: 13px; border: 1px solid #a99b84; border-radius: 50%; background: #fffdf8; box-shadow: inset 0 0 0 3px #fffdf8; }
.engine-card--selected .selection-dot { border-color: var(--jade); background: var(--jade); }
.engine-card h4 { margin: 20px 0 9px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 20px; font-weight: 650; }
.promise { min-height: 76px; margin: 0; color: #4e473d; font-size: 13px; line-height: 1.75; }
.engine-facts { display: grid; gap: 10px; margin: 18px 0 0; padding-top: 15px; border-top: 1px solid #dfd3be; }
.engine-facts dt, .ensemble-block > span { color: var(--cinnabar); font-size: 10px; font-weight: 800; letter-spacing: .1em; }
.engine-facts dd { margin: 4px 0 0; color: var(--muted); font-size: 12px; line-height: 1.65; }
.ensemble-block { margin-top: 16px; }
.ensemble-block ul, .risk-notes ul { display: grid; gap: 6px; margin: 8px 0 0; padding: 0; list-style: none; }
.ensemble-block li { color: var(--muted); font-size: 11px; line-height: 1.55; }
.ensemble-block strong { margin-right: 7px; color: var(--jade); }
.risk-notes { margin-top: 14px; font-size: 12px; }
.risk-notes li::before { margin-right: 7px; color: var(--cinnabar); content: '—'; }
.risk-notes p { color: var(--muted); line-height: 1.65; }
.empty-engine { display: grid; justify-items: center; margin-top: 20px; padding: 48px 20px; border: 1px dashed #c9b99f; background: rgba(255, 252, 244, .48); text-align: center; }
.empty-engine i { display: grid; width: 48px; height: 48px; place-items: center; border: 2px solid var(--cinnabar); color: var(--cinnabar); font-family: Georgia, 'Noto Serif SC', serif; font-size: 23px; font-style: normal; transform: rotate(-4deg); }
.empty-engine h4 { margin: 16px 0 6px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 19px; }
.empty-engine p { max-width: 620px; margin: 0; color: var(--muted); font-size: 12px; line-height: 1.75; }
.contract-strip { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-top: 22px; padding: 18px 20px; border-top: 1px solid #cdbda2; border-bottom: 1px solid #cdbda2; background: rgba(238, 229, 209, .42); }
.frozen-facts { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 15px; color: var(--muted); font-size: 11px; }
.frozen-facts span + span::before { margin-right: 15px; color: #b6a689; content: '·'; }
.contract-actions { display: flex; align-items: center; flex: 0 0 auto; gap: 8px; }
@media (max-width: 980px) { .engine-grid { grid-template-columns: 1fr; } .promise { min-height: 0; } }
@media (max-width: 720px) {
  .step-heading, .contract-strip { align-items: flex-start; flex-direction: column; }
  .manual-sheet { grid-template-columns: 1fr; }
  .manual-actions { grid-column: 1; }
  .generation-actions, .unknown-actions { align-items: flex-start; flex-direction: column; }
}
</style>
