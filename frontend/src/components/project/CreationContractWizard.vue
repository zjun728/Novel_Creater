<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { NAlert, NButton, NResult, NSkeleton, NTag } from 'naive-ui'
import { api } from '@/api/db/client'
import { useCreationContractStore } from '@/stores/creationContractStore'
import { useSeedStore } from '@/stores/seedStore'
import { createLatestRequestGuard } from '@/utils/latestRequest'
import ContractHeadSummary from './ContractHeadSummary.vue'
import AssetScopeStep from './contract/AssetScopeStep.vue'
import ContractPreviewStep from './contract/ContractPreviewStep.vue'
import SeedSelectionStep from './contract/SeedSelectionStep.vue'
import StoryEngineStep from './contract/StoryEngineStep.vue'
import StyleSelectionStep from './contract/StyleSelectionStep.vue'

const props = defineProps({
  projectId: { type: String, required: true },
  project: { type: Object, default: null },
})

const seedStore = useSeedStore()
const contractStore = useCreationContractStore()
const loadGuard = createLatestRequestGuard()
const loading = ref(true)
const loadError = ref('')
const contentState = ref(null)
const step = ref(1)
const childWriteBusy = ref(false)
const busyNotice = ref('')

const steps = [
  { number: 1, label: '选择种子', note: '确定本书唯一出发点' },
  { number: 2, label: '故事发动机', note: '选择持续推动长篇的动力' },
  { number: 3, label: '风格契约', note: '约定读感而非堆砌规则' },
  { number: 4, label: '素材范围', note: '冻结经验卡与参考语料' },
  { number: 5, label: '冻结并确认', note: '一次确认完整契约' },
]

const hasConfirmedContract = computed(() => (
  contractStore.head?.hasContract === true && !contractStore.draft
))

const restoredStep = computed(() => {
  if (!seedStore.selectedSeed) return 1
  const draftValues = contractStore.draft?.draft
  if (draftValues && (
    draftValues.seedRevisionId !== seedStore.selectedSeed.revisionId
    || draftValues.seedHash !== seedStore.selectedSeed.contentHash
  )) return 2
  const stage = contractStore.lastSavedStage
  if (stage === 'assets') return 5
  if (stage === 'style') return 4
  if (stage === 'engine') return 3
  return 2
})

const seedLocked = computed(() => contentState.value?.hasFinalChapters === true)
const writeBusy = computed(() => Boolean(
  childWriteBusy.value
  || contractStore.saving
  || contractStore.confirming
  || contractStore.cloning
  || contractStore.engineLoading
  || contractStore.reconciling,
))

function setRestoredStep() {
  step.value = restoredStep.value
}

function canOpen(target) {
  return target <= restoredStep.value
}

function confirmDiscard() {
  if (writeBusy.value) {
    busyNotice.value = '正式操作正在提交，请等待结果明确后再切换步骤或离开项目。'
    return false
  }
  if (!contractStore.hasUnsavedChanges) return true
  if (typeof window === 'undefined') return false
  const accepted = window.confirm('当前步骤有尚未保存的修改。放弃这些修改并离开吗？')
  if (accepted) contractStore.discardUnsavedChanges()
  return accepted
}

function openStep(target) {
  if (writeBusy.value || !canOpen(target) || !confirmDiscard()) return
  busyNotice.value = ''
  step.value = target
}

function markWriteBusy(value) {
  childWriteBusy.value = value === true
  if (!childWriteBusy.value) busyNotice.value = ''
}

function markDirty(value) {
  if (value) contractStore.markUnsavedChanges()
  else contractStore.discardUnsavedChanges()
}

function advance(target) {
  childWriteBusy.value = false
  busyNotice.value = ''
  contractStore.discardUnsavedChanges()
  step.value = target
}

async function loadWizard(projectId) {
  if (writeBusy.value) {
    busyNotice.value = '正式操作正在提交，当前不能并发重新加载项目状态。'
    return
  }
  const generation = loadGuard.begin()
  loading.value = true
  loadError.value = ''
  childWriteBusy.value = false
  busyNotice.value = ''
  contentState.value = null
  try {
    const [, , state] = await Promise.all([
      seedStore.refresh(projectId),
      contractStore.load(projectId),
      api.projects.contentState(projectId),
    ])
    if (!loadGuard.isCurrent(generation)) return
    contentState.value = state
    setRestoredStep()
  } catch (error) {
    if (!loadGuard.isCurrent(generation)) return
    loadError.value = error?.message || '创作契约加载失败'
  } finally {
    if (loadGuard.isCurrent(generation)) loading.value = false
  }
}

function handleBeforeUnload(event) {
  if (!contractStore.hasUnsavedChanges && !writeBusy.value) return
  event.preventDefault()
  event.returnValue = ''
}

watch(() => props.projectId, projectId => {
  if (projectId) loadWizard(String(projectId))
}, { immediate: true })

if (typeof window !== 'undefined') window.addEventListener('beforeunload', handleBeforeUnload)

onBeforeRouteLeave(() => confirmDiscard())
onBeforeRouteUpdate(() => confirmDiscard())

onBeforeUnmount(() => {
  loadGuard.invalidate()
  if (typeof window !== 'undefined') window.removeEventListener('beforeunload', handleBeforeUnload)
})
</script>

<template>
  <section class="contract-ledger" aria-labelledby="creation-contract-heading">
    <header class="ledger-header">
      <div>
        <p class="section-index">01 / 创作契约</p>
        <h2 id="creation-contract-heading">本书创作契约</h2>
        <p>把“这本书如何持续讲得好看”先约定清楚，再进入逐章写作。</p>
      </div>
      <n-tag v-if="hasConfirmedContract" type="success" round :bordered="false">已签印</n-tag>
      <n-tag v-else round :bordered="false">修订中</n-tag>
    </header>

    <div v-if="loading" class="ledger-loading" aria-busy="true">
      <n-skeleton text width="42%" />
      <n-skeleton text :repeat="3" />
      <n-skeleton height="240px" />
    </div>

    <n-result
      v-else-if="loadError"
      status="error"
      title="创作契约未能加载"
      :description="loadError"
      class="ledger-error"
    >
      <template #footer>
        <n-button type="primary" :disabled="writeBusy" @click="loadWizard(props.projectId)">重新加载</n-button>
      </template>
    </n-result>

    <ContractHeadSummary
      v-else-if="hasConfirmedContract"
      :project-id="props.projectId"
      :head="contractStore.head"
      @cloned="advance(5)"
    />

    <template v-else>
      <nav class="step-ribbon" aria-label="创作契约五个步骤">
        <button
          v-for="item in steps"
          :key="item.number"
          type="button"
          class="step-tab"
          :class="{ 'step-tab--active': step === item.number, 'step-tab--done': item.number < restoredStep }"
          :disabled="writeBusy || !canOpen(item.number)"
          :aria-current="step === item.number ? 'step' : undefined"
          @click="openStep(item.number)"
        >
          <span>{{ String(item.number).padStart(2, '0') }}</span>
          <strong>{{ item.label }}</strong>
          <small>{{ item.note }}</small>
        </button>
      </nav>

      <n-alert v-if="contractStore.requiresReload" type="warning" class="checkpoint-alert">
        草稿版本已经变化。请重新加载后再编辑，系统不会覆盖另一份修订。
        <template #action><n-button text :disabled="writeBusy" @click="loadWizard(props.projectId)">重新加载</n-button></template>
      </n-alert>
      <n-alert v-if="writeBusy || busyNotice" type="info" class="checkpoint-alert">
        {{ busyNotice || '正式操作正在提交，完成前暂不能切换步骤或离开项目。' }}
      </n-alert>

      <SeedSelectionStep
        v-if="step === 1"
        :project-id="props.projectId"
        :has-final-chapters="seedLocked"
        @selected="advance(2)"
        @saved="advance(2)"
        @dirty-change="markDirty"
        @busy-change="markWriteBusy"
      />
      <StoryEngineStep
        v-else-if="step === 2"
        :project-id="props.projectId"
        :project="props.project"
        @saved="advance(3)"
        @back="openStep(1)"
        @dirty-change="markDirty"
      />
      <StyleSelectionStep
        v-else-if="step === 3"
        :project-id="props.projectId"
        @saved="advance(4)"
        @back="openStep(2)"
        @dirty-change="markDirty"
      />
      <AssetScopeStep
        v-else-if="step === 4"
        :project-id="props.projectId"
        @saved="advance(5)"
        @back="openStep(3)"
        @dirty-change="markDirty"
      />
      <ContractPreviewStep
        v-else
        :project-id="props.projectId"
        @back="openStep(4)"
        @confirmed="contractStore.discardUnsavedChanges()"
      />
    </template>
  </section>
</template>

<style scoped>
.contract-ledger { --paper: #fffdf7; --ink: #302b24; --muted: #786e60; --rule: #d9ccb7; --cinnabar: #9c3d2f; --jade: #4f725b; width: min(1120px, 100%); margin: 42px auto 0; border: 1px solid var(--rule); border-radius: 14px; color: var(--ink); background: var(--paper); box-shadow: 0 18px 50px rgba(67, 52, 34, .07); overflow: hidden; }
.ledger-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 28px 30px 22px; border-bottom: 1px solid var(--rule); background: linear-gradient(90deg, rgba(156, 61, 47, .035), transparent 44%); }
.section-index { margin: 0; color: #967548; font-size: 10px; font-weight: 800; letter-spacing: .18em; text-transform: uppercase; }
.ledger-header h2 { margin: 6px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 28px; }
.ledger-header p:last-child { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
.ledger-loading, .ledger-error { padding: 34px 30px; }
.ledger-loading { display: grid; gap: 16px; }
.step-ribbon { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border-bottom: 1px solid var(--rule); }
.step-tab { display: grid; min-width: 0; padding: 17px 16px 15px; border: 0; border-right: 1px solid #e8decd; color: #827667; text-align: left; background: #f8f3e9; cursor: pointer; }
.step-tab:last-child { border-right: 0; }
.step-tab:disabled { cursor: not-allowed; opacity: .55; }
.step-tab > span { color: #ae9b7d; font-family: Georgia, serif; font-size: 10px; }
.step-tab strong { margin-top: 4px; color: inherit; font-family: 'Noto Serif SC', serif; font-size: 14px; }
.step-tab small { margin-top: 5px; overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.step-tab--done { color: var(--jade); background: #f2f5ed; }
.step-tab--active { color: var(--cinnabar); background: var(--paper); box-shadow: inset 0 3px 0 var(--cinnabar); }
.checkpoint-alert { margin: 20px 28px 0; }
@media (max-width: 850px) { .step-ribbon { grid-template-columns: 1fr; } .step-tab { border-right: 0; border-bottom: 1px solid #e8decd; } .step-tab small { white-space: normal; } }
@media (max-width: 560px) { .ledger-header { align-items: flex-start; flex-direction: column; padding: 22px 18px; } }
</style>
