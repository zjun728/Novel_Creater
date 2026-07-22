<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { NAlert, NButton, NResult, NSkeleton, NTag } from 'naive-ui'

import { projectSeedsPath } from '@/router/projectRoutes.js'
import { useCreationContractStore } from '@/stores/creationContractStore.js'
import { useSeedStore } from '@/stores/seedStore.js'
import { createLatestRequestGuard } from '@/utils/latestRequest.js'
import AssetScopeStep from './contract/AssetScopeStep.vue'
import CapacityStep from './contract/CapacityStep.vue'
import ContractHistoryDrawer from './contract/ContractHistoryDrawer.vue'
import ContractPreviewStep from './contract/ContractPreviewStep.vue'
import StoryEngineStep from './contract/StoryEngineStep.vue'
import StyleSelectionStep from './contract/StyleSelectionStep.vue'

const props = defineProps({
  projectId: { type: String, required: true },
  project: { type: Object, default: null },
  readOnly: { type: Boolean, default: false },
})

const seedStore = useSeedStore()
const contractStore = useCreationContractStore()
const loadGuard = createLatestRequestGuard()
const loading = ref(true)
const loadError = ref('')
const loadErrorRegion = ref(null)
const step = ref(1)
const childWriteBusy = ref(false)
const busyNotice = ref('')
const historyOpen = ref(false)

const steps = Object.freeze([
  { number: 1, label: '故事发动机', note: '生成、选择或手动录入' },
  { number: 2, label: '风格契约', note: '主风格、辅风格与临时试写' },
  { number: 3, label: '素材范围', note: '显式选择经验卡与语料片段' },
  { number: 4, label: '容量约定', note: '篇幅、卷章与禁止方向' },
  { number: 5, label: '预览并确认', note: '汇总变化，一次签印' },
])

const selectedSeed = computed(() => seedStore.selectedSeed)
const hasConfirmedContract = computed(() => (
  contractStore.head?.hasContract === true && (!contractStore.draft || props.readOnly)
))
const selectionDrift = computed(() => {
  const draft = contractStore.draft?.draft
  if (!draft || !selectedSeed.value) return false
  return draft.seedRevisionId !== selectedSeed.value.revisionId
    || draft.seedHash !== selectedSeed.value.contentHash
})
const restoredStep = computed(() => {
  if (selectionDrift.value) return 1
  const stage = contractStore.lastSavedStage
  if (stage === 'assets') return 4
  if (stage === 'style') return 3
  if (stage === 'engine') return 2
  return 1
})
const maxOpenStep = computed(() => (
  contractStore.lastSavedStage === 'assets' ? 5 : restoredStep.value
))
const writeBusy = computed(() => Boolean(
  childWriteBusy.value
  || contractStore.saving
  || contractStore.previewing
  || contractStore.confirming
  || contractStore.cloning
  || contractStore.engineLoading
  || contractStore.reconciling
  || contractStore.styleTrialLoading,
))
const operationLabel = computed(() => {
  if (contractStore.confirming) return '正在签印创作契约'
  if (contractStore.cloning) return '正在建立未来设计草稿'
  if (contractStore.styleTrialLoading) return '正在生成临时风格试写'
  if (contractStore.engineLoading || contractStore.reconciling) return '正在处理故事发动机'
  if (contractStore.previewing) return '正在核对冻结引用'
  return '正在保存创作契约草稿'
})

function canOpen(target) {
  return target >= 1 && target <= maxOpenStep.value
}

function confirmDiscard() {
  if (props.readOnly) return true
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
  if (props.readOnly || writeBusy.value || !canOpen(target) || !confirmDiscard()) return
  busyNotice.value = ''
  step.value = target
}

function markWriteBusy(value) {
  childWriteBusy.value = value === true
  if (!childWriteBusy.value) busyNotice.value = ''
}

function markDirty(value) {
  if (props.readOnly) return
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
  try {
    await Promise.all([
      seedStore.refresh(projectId),
      contractStore.load(projectId, { readOnly: props.readOnly }),
    ])
    if (!loadGuard.isCurrent(generation)) return
    step.value = restoredStep.value
  } catch (error) {
    if (!loadGuard.isCurrent(generation)) return
    loadError.value = error?.message || '创作契约加载失败'
    await nextTick()
    loadErrorRegion.value?.focus({ preventScroll: false })
  } finally {
    if (loadGuard.isCurrent(generation)) loading.value = false
  }
}

function handleBeforeUnload(event) {
  if (!contractStore.hasUnsavedChanges && !writeBusy.value) return
  event.preventDefault()
  event.returnValue = ''
}

watch(
  () => [props.projectId, props.readOnly],
  ([projectId]) => {
    if (projectId) void loadWizard(String(projectId))
  },
  { immediate: true },
)

if (typeof window !== 'undefined') window.addEventListener('beforeunload', handleBeforeUnload)
onBeforeRouteLeave(() => confirmDiscard())
onBeforeRouteUpdate(() => confirmDiscard())
onBeforeUnmount(() => {
  loadGuard.invalidate()
  contractStore.setReadOnly(false)
  if (typeof window !== 'undefined') window.removeEventListener('beforeunload', handleBeforeUnload)
})
</script>

<template>
  <section class="contract-ledger" aria-labelledby="creation-contract-heading">
    <header class="ledger-header">
      <div>
        <p class="section-index">CREATION CONTRACT / FORMAL WORKSPACE</p>
        <h1 id="creation-contract-heading">本书创作契约</h1>
        <p>先把未来写作的边界与承诺写成一份稿簿，再进入滚动规划。</p>
      </div>
      <div class="ledger-tools">
        <n-button v-if="contractStore.head?.hasContract" quaternary @click="historyOpen = true">历史修订</n-button>
        <n-tag v-if="props.readOnly" type="warning" round :bordered="false">只读档案</n-tag>
        <n-tag v-else-if="hasConfirmedContract" type="success" round :bordered="false">已签印</n-tag>
        <n-tag v-else round :bordered="false">草稿中</n-tag>
      </div>
    </header>

    <div v-if="loading" class="ledger-loading" aria-busy="true">
      <n-skeleton text width="42%" />
      <n-skeleton text :repeat="3" />
      <n-skeleton height="240px" />
    </div>

    <n-result
      v-else-if="loadError"
      ref="loadErrorRegion"
      tabindex="-1"
      status="error"
      title="创作契约未能加载"
      :description="loadError"
      class="ledger-error"
      aria-live="assertive"
    >
      <template #footer>
        <n-button type="primary" :disabled="writeBusy" @click="loadWizard(props.projectId)">重新加载并核对</n-button>
      </template>
    </n-result>

    <template v-else>
      <aside v-if="selectedSeed" class="seed-slip" aria-label="已选创作种子，只读">
        <div>
          <span>已选创作种子 · 只读</span>
          <strong>{{ selectedSeed.title }}</strong>
          <p>{{ selectedSeed.logline }}</p>
        </div>
        <dl>
          <div><dt>修订</dt><dd>{{ selectedSeed.revision ?? '—' }}</dd></div>
          <div><dt>题材</dt><dd>{{ selectedSeed.genre || '未标注' }}</dd></div>
          <div><dt>选择代次</dt><dd>R{{ seedStore.selectionRevision || '—' }}</dd></div>
        </dl>
      </aside>

      <n-result
        v-else
        status="warning"
        title="尚未选定创作种子"
        description="创作契约必须绑定一个当前有效的种子修订；这里不会重复提供种子选择。"
        class="seed-required"
      >
        <template #footer>
          <router-link class="seed-cta" :to="projectSeedsPath(props.projectId)">前往种子</router-link>
        </template>
      </n-result>

      <article v-if="selectedSeed && hasConfirmedContract" class="confirmed-ledger">
        <div class="confirmed-seal" aria-hidden="true">契</div>
        <div>
          <span>IMMUTABLE REVISION · R{{ contractStore.head.revision }}</span>
          <h2>当前生效的创作契约</h2>
          <p>这份修订已经签印，只读且不可覆盖。调整只会从历史修订建立一份面向未来的新草稿。</p>
          <div class="confirmed-facts">
            <span>种子 {{ contractStore.head.seedRef?.revisionId || '—' }}</span>
            <span>风格 {{ contractStore.head.styleRefs?.length || 0 }} 套</span>
            <span>经验卡 {{ contractStore.head.experienceCardRefs?.length || 0 }} 张</span>
            <span>语料 {{ contractStore.head.corpusSourceRefs?.length || 0 }} 份</span>
          </div>
          <n-button v-if="!props.readOnly" type="primary" @click="historyOpen = true">从历史调整未来设计</n-button>
        </div>
      </article>

      <n-result
        v-else-if="selectedSeed && props.readOnly"
        status="info"
        title="归档时尚未签印创作契约"
        description="归档项目保持全页只读，不能创建、保存、预览或确认草稿。"
      />

      <template v-else-if="selectedSeed">
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

        <n-alert v-if="contractStore.requiresReload" type="warning" class="checkpoint-alert" aria-live="assertive">
          草稿或冻结输入已经变化。系统不会静默覆盖；请重新加载并核对后再继续。
          <template #action><n-button text :disabled="writeBusy" @click="loadWizard(props.projectId)">重新加载并核对</n-button></template>
        </n-alert>
        <n-alert v-if="selectionDrift" type="warning" class="checkpoint-alert" aria-live="assertive">
          当前草稿绑定的是旧种子修订。请从故事发动机重新保存，系统不会沿用旧代次的冻结选择。
        </n-alert>
        <p class="workspace-live" aria-live="polite">{{ busyNotice }}</p>

        <div class="step-sheet">
          <StoryEngineStep
            v-if="step === 1"
            :project-id="props.projectId"
            :project="props.project"
            :selected-seed="selectedSeed"
            @saved="advance(2)"
            @dirty-change="markDirty"
            @busy-change="markWriteBusy"
          />
          <StyleSelectionStep
            v-else-if="step === 2"
            :project-id="props.projectId"
            :selection-revision="seedStore.selectionRevision"
            @saved="advance(3)"
            @back="openStep(1)"
            @dirty-change="markDirty"
          />
          <AssetScopeStep
            v-else-if="step === 3"
            :project-id="props.projectId"
            @saved="advance(4)"
            @back="openStep(2)"
            @dirty-change="markDirty"
          />
          <CapacityStep
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
            @reload="loadWizard(props.projectId)"
            @confirmed="contractStore.discardUnsavedChanges()"
          />
        </div>
      </template>
    </template>

    <aside v-if="writeBusy" class="contract-operation-overlay" role="status" aria-live="polite" aria-busy="true">
      <div><span aria-hidden="true">作</span><strong>{{ operationLabel }}</strong><small>请等待结果明确，期间不会切换步骤。</small></div>
    </aside>

    <ContractHistoryDrawer
      v-model:show="historyOpen"
      :project-id="props.projectId"
      :current-selection-revision="seedStore.selectionRevision"
      :read-only="props.readOnly"
      @cloned="advance(4)"
    />
  </section>
</template>

<style scoped>
.contract-ledger { --paper: #fffdf7; --ink: #302b24; --muted: #786e60; --rule: #d9ccb7; --cinnabar: #9c3d2f; --jade: #4f725b; position: relative; width: min(1180px, 100%); margin: 0 auto; border: 1px solid var(--rule); border-radius: 14px; color: var(--ink); background: var(--paper); box-shadow: 0 18px 50px rgba(67, 52, 34, .07); overflow: hidden; }
.ledger-header { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding: 28px 30px 22px; border-bottom: 1px solid var(--rule); background: linear-gradient(90deg, rgba(156, 61, 47, .04), transparent 50%); }
.section-index { margin: 0; color: #967548; font: 800 10px Georgia, serif; letter-spacing: .18em; }
.ledger-header h1 { margin: 6px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(27px, 4vw, 38px); font-weight: 600; }
.ledger-header p:last-child { margin: 8px 0 0; color: var(--muted); font-size: 13px; }
.ledger-tools { display: flex; align-items: center; gap: 8px; }
.ledger-loading, .ledger-error { padding: 34px 30px; }
.ledger-loading { display: grid; gap: 16px; }
.seed-slip { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 28px; margin: 22px 28px; padding: 18px 20px; border: 1px solid #d8c9b2; border-left: 4px solid var(--jade); background: #faf6ec; }
.seed-slip span { color: var(--jade); font-size: 10px; font-weight: 800; letter-spacing: .12em; }
.seed-slip strong { display: block; margin-top: 5px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 19px; }
.seed-slip p { margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.65; }
.seed-slip dl { display: grid; grid-template-columns: repeat(3, auto); gap: 20px; margin: 0; }
.seed-slip dt { color: #9a8b75; font-size: 9px; }
.seed-slip dd { margin: 4px 0 0; font-size: 12px; font-weight: 700; }
.seed-required { padding: 44px 24px; }
.seed-cta { display: inline-flex; padding: 9px 18px; border-radius: 7px; color: #fff; background: var(--cinnabar); text-decoration: none; }
.confirmed-ledger { display: grid; grid-template-columns: 82px 1fr; min-height: 280px; border-top: 1px solid var(--rule); }
.confirmed-seal { display: grid; place-items: center; color: #fff8eb; background: var(--cinnabar); font-family: 'Noto Serif SC', serif; font-size: 34px; }
.confirmed-ledger > div:last-child { padding: 32px; }
.confirmed-ledger span { color: var(--cinnabar); font: 700 10px Georgia, serif; letter-spacing: .1em; }
.confirmed-ledger h2 { margin: 7px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 27px; }
.confirmed-ledger p { max-width: 68ch; color: var(--muted); line-height: 1.8; }
.confirmed-facts { display: flex; flex-wrap: wrap; gap: 8px 18px; margin: 20px 0; }
.confirmed-facts span { color: #655c50; font-family: inherit; letter-spacing: 0; }
.step-ribbon { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.step-tab { display: grid; min-width: 0; padding: 17px 16px 15px; border: 0; border-right: 1px solid #e8decd; color: #827667; text-align: left; background: #f8f3e9; cursor: pointer; }
.step-tab:last-child { border-right: 0; }
.step-tab:disabled { cursor: not-allowed; opacity: .52; }
.step-tab > span { color: #ae9b7d; font-family: Georgia, serif; font-size: 10px; }
.step-tab strong { margin-top: 4px; color: inherit; font-family: 'Noto Serif SC', serif; font-size: 14px; }
.step-tab small { margin-top: 5px; overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.step-tab--done { color: var(--jade); background: #f2f5ed; }
.step-tab--active { color: var(--cinnabar); background: var(--paper); box-shadow: inset 0 3px 0 var(--cinnabar); }
.step-sheet { padding: clamp(22px, 4vw, 34px); }
.checkpoint-alert { margin: 20px 28px 0; }
.workspace-live { min-height: 18px; margin: 10px 28px 0; color: var(--muted); font-size: 11px; }
.contract-operation-overlay { position: absolute; z-index: 20; inset: 0; display: grid; place-items: center; padding: 24px; background: rgba(47, 39, 30, .25); backdrop-filter: blur(1px); }
.contract-operation-overlay > div { display: grid; grid-template-columns: auto 1fr; min-width: min(420px, 92%); gap: 4px 13px; padding: 18px 20px; border: 1px solid #cab99c; border-radius: 10px; background: #fffdf7; box-shadow: 0 20px 54px rgba(42, 34, 25, .2); }
.contract-operation-overlay span { grid-row: 1 / 3; display: grid; width: 36px; height: 36px; place-items: center; color: #fff; background: var(--cinnabar); font-family: 'Noto Serif SC', serif; }
.contract-operation-overlay small { color: var(--muted); }
@media (max-width: 850px) { .step-ribbon { grid-template-columns: 1fr; } .step-tab { border-right: 0; border-bottom: 1px solid #e8decd; } .step-tab small { white-space: normal; } .seed-slip { grid-template-columns: 1fr; } .seed-slip dl { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 560px) { .ledger-header { align-items: flex-start; flex-direction: column; padding: 22px 18px; } .ledger-tools { width: 100%; justify-content: space-between; } .seed-slip { margin-inline: 16px; } .seed-slip dl { grid-template-columns: 1fr; } .confirmed-ledger { grid-template-columns: 1fr; } .confirmed-seal { min-height: 54px; } }
</style>
