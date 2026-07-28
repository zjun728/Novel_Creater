<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
} from 'vue'

import { createChapterOutlineController } from '../../application/planning/chapterOutlineController.js'
import { useOperationStore } from '../../stores/operationStore.js'
import { canonicalPlanningContentForUi } from '../../stores/planningStore.js'
import { createModalFocusManager } from '../common/modalFocusManager.js'
import ChapterOutlineWorkspace from './ChapterOutlineWorkspace.vue'
import PlanningHistoryDrawer from './PlanningHistoryDrawer.vue'
import PlotEditor from './PlotEditor.vue'
import StoryBlockEditor from './StoryBlockEditor.vue'
import VolumeEditor from './VolumeEditor.vue'

const props = defineProps({
  store: { type: Object, required: true },
  controller: { type: Object, required: true },
  activeTab: {
    type: String,
    required: true,
    validator: value => ['volumes', 'plots', 'story-blocks'].includes(value),
  },
})

const confirmOpen = ref(false)
const confirmDialog = ref(null)
const confirmInitial = ref(null)
const confirmFocus = createModalFocusManager({
  getDialog: () => confirmDialog.value,
  getInitialFocus: () => confirmInitial.value,
})
const planningContent = computed(() => {
  if (props.store.localContent) return props.store.localContent
  return canonicalPlanningContentForUi(
    props.store.state?.draft?.content
    || props.store.state?.futurePlan
    || null,
  )
})
const outlineController = createChapterOutlineController({
  store: props.store,
  projectId: () => String(
    props.store.projectId
    || props.store.outlineState?.projectId
    || props.store.state?.projectId
    || '',
  ),
  operationStore: props.store?._p ? useOperationStore(props.store._p) : null,
})
const originalRequestRouteLeave = props.controller.requestRouteLeave
const originalBeforeUnload = props.controller.beforeUnload

props.controller.requestRouteLeave = to => {
  if (!outlineController.hasCombinedLeaveRisk(props.controller)) {
    return originalRequestRouteLeave(to)
  }
  const instructions = props.controller.authorInstructions
  const snapshot = instructions?.value
  const needsSentinel = !String(snapshot || '').trim()
  if (needsSentinel && instructions) instructions.value = 'outline-leave-risk'
  try {
    return originalRequestRouteLeave(to)
  } finally {
    if (needsSentinel && instructions) instructions.value = snapshot
  }
}
props.controller.beforeUnload = event => {
  if (!outlineController.hasCombinedLeaveRisk(props.controller)) {
    return originalBeforeUnload(event)
  }
  event.preventDefault()
  event.returnValue = ''
  return ''
}
const revisionLabel = computed(() => (
  props.store.state ? `R${Number(props.store.state.head?.revision || 0)}` : '—'
))
const draftLabel = computed(() => (
  props.store.state?.draft?.draftRevision == null
    ? '—'
    : `D${props.store.state.draft.draftRevision}`
))
const counts = computed(() => {
  const content = planningContent.value
  const blocks = content?.storyBlocks || []
  return {
    volumes: content?.volumes?.length || 0,
    plots: content?.plots?.length || 0,
    storyBlocks: blocks.length,
    stages: blocks.reduce((total, block) => total + (block.stages?.length || 0), 0),
    sceneTasks: blocks.reduce((total, block) => (
      total + (block.stages || []).reduce(
        (stageTotal, stage) => stageTotal + (stage.sceneTasks?.length || 0),
        0,
      )
    ), 0),
  }
})
const activeStoryBlock = computed(() => (
  (planningContent.value?.storyBlocks || []).find(block => (
    String(block.id || block.clientNodeKey || '')
      === String(planningContent.value?.activeStoryBlockRef || '')
  )) || null
))

function run(action) {
  Promise.resolve(action()).catch(() => {})
}

function openConfirm() {
  if (!props.controller.canConfirm.value) return
  confirmOpen.value = true
}

function closeConfirm() {
  if (props.store.confirming) return
  confirmOpen.value = false
}

function handleConfirmKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeConfirm()
    return
  }
  confirmFocus.trapTab(event)
}

async function confirmPlanning() {
  try {
    if (await props.controller.confirm()) confirmOpen.value = false
  } catch {
    // The Store exposes only its public error envelope in the workspace.
  }
}

watch(confirmOpen, async open => {
  if (open) {
    await nextTick()
    confirmFocus.mount()
  } else {
    confirmFocus.unmount()
  }
})
watch(
  () => props.controller.projectScope.value,
  () => { confirmOpen.value = false },
)
watch(
  () => String(
    props.store.projectId
    || props.store.outlineState?.projectId
    || props.store.state?.projectId
    || '',
  ),
  projectId => {
    outlineController.enterProject(projectId)
    if (
      projectId
      && typeof props.store.ensureOutlineLoaded === 'function'
    ) {
      void outlineController.hydrate().catch(() => {})
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  confirmFocus.unmount()
  props.controller.requestRouteLeave = originalRequestRouteLeave
  props.controller.beforeUnload = originalBeforeUnload
})
</script>

<template>
  <section class="planning-workspace" aria-labelledby="planning-heading">
    <header class="workspace-header">
      <div>
        <p class="eyebrow">STORY PLANNING · ONE AGGREGATE</p>
        <h1 id="planning-heading">故事规划工作台</h1>
        <p class="lede">
          像编辑部整理手稿一样，先写清长期变化与持续追问，再把完整规划交给故事块执行。
        </p>
      </div>
      <div class="revision-strip" aria-label="规划版本">
        <div><span>确认版本</span><strong>{{ revisionLabel }}</strong></div>
        <div><span>工作草稿</span><strong>{{ draftLabel }}</strong></div>
      </div>
    </header>

    <p v-if="controller.notice.value" class="notice" role="status" aria-live="polite">
      {{ controller.notice.value }}
    </p>
    <section v-if="store.error" class="error-summary" role="alert">
      <strong>{{ store.error.message }}</strong>
      <small v-if="store.error.correlationId">参考编号：{{ store.error.correlationId }}</small>
    </section>
    <section
      v-if="controller.hasCriticalRecovery.value"
      class="recovery-summary"
      role="status"
      aria-live="polite"
    >
      <strong v-if="store.generationOperation?.status === 'pending'">
        原操作仍在进行，稍后核对
      </strong>
      <strong v-else>生成结果尚未完成权威核对</strong>
      <button
        type="button"
        :disabled="store.reconciling"
        @click="run(controller.reconcile)"
      >
        核对原操作
      </button>
    </section>

    <section v-if="store.loading && !store.state" class="paper-panel" aria-busy="true">
      正在展开规划手稿…
    </section>
    <section v-else-if="!store.state" class="paper-panel planning-load-failure">
      <h2>规划数据暂时无法加载</h2>
      <p>当前没有可展示的权威状态，系统不会推断或拼接旧数据。</p>
      <button type="button" @click="run(controller.hydrate)">重新加载</button>
    </section>

    <template v-else>
      <aside v-if="controller.readOnly.value" class="read-only-banner">
        当前项目或规划修订为只读状态；可以查阅正文规划与历史，不能克隆、编辑或写入。
      </aside>

      <section v-if="!store.state.draft && !controller.readOnly.value" class="paper-panel empty-draft">
        <span>BLANK DRAFT</span>
        <h2>从空白工作稿开始</h2>
        <p>可以先只建立分卷和情节线并保存；补齐故事块、阶段与场景任务后才能确认。</p>
        <button
          type="button"
          :disabled="!controller.canCreateDraft.value"
          @click="run(controller.createManualDraft)"
        >
          建立空白规划工作稿
        </button>
      </section>

      <section v-else-if="planningContent" class="workspace-sheet">
        <div
          class="workspace-scroll"
          :class="{ 'streaming-read-only': controller.localOverlay.value }"
          :inert="controller.localOverlay.value || undefined"
        >
          <volume-editor
            v-if="activeTab === 'volumes'"
            :model-value="planningContent.volumes || []"
            :read-only="!controller.editable.value"
            :disabled="controller.editorLocked.value"
            @add="controller.addVolume"
            @update="controller.updateVolume"
            @remove="controller.removeVolume"
            @move="controller.moveVolume"
          />
          <plot-editor
            v-else-if="activeTab === 'plots'"
            :model-value="planningContent.plots || []"
            :read-only="!controller.editable.value"
            :disabled="controller.editorLocked.value"
            @add="controller.addPlot"
            @update="controller.updatePlot"
            @remove="controller.removePlot"
            @move="controller.movePlot"
          />
          <story-block-editor
            v-else-if="activeTab === 'story-blocks'"
            :model-value="planningContent.storyBlocks || []"
            :volumes="planningContent.volumes || []"
            :plots="planningContent.plots || []"
            :active-story-block-ref="planningContent.activeStoryBlockRef"
            :undo-available="controller.canUndoStoryBlockEdit.value"
            :read-only="!controller.editable.value"
            :disabled="controller.editorLocked.value"
            @add="controller.addStoryBlock"
            @update="controller.updateStoryBlock"
            @remove="controller.removeStoryBlock"
            @move="controller.moveStoryBlock"
            @select="controller.selectActiveStoryBlock"
            @undo="controller.undoStoryBlockEdit"
            @add-stage="controller.addStage"
            @update-stage="controller.updateStage"
            @remove-stage="controller.removeStage"
            @move-stage="controller.moveStage"
            @add-scene-task="controller.addSceneTask"
            @update-scene-task="controller.updateSceneTask"
            @remove-scene-task="controller.removeSceneTask"
            @move-scene-task="controller.moveSceneTask"
          />

          <section class="aggregate-summary" aria-label="完整规划摘要">
            <div>
              <p>AGGREGATE STATUS</p>
              <h2>完整规划摘要</h2>
            </div>
            <dl>
              <div><dt>分卷</dt><dd>{{ counts.volumes }}</dd></div>
              <div><dt>情节线</dt><dd>{{ counts.plots }}</dd></div>
              <div><dt>故事块</dt><dd>{{ counts.storyBlocks }}</dd></div>
              <div><dt>阶段</dt><dd>{{ counts.stages }}</dd></div>
              <div><dt>场景任务</dt><dd>{{ counts.sceneTasks }}</dd></div>
            </dl>
            <ol v-if="planningContent.storyBlocks?.length" class="hierarchy-summary">
              <li
                v-for="block in planningContent.storyBlocks"
                :key="block.id || block.clientNodeKey"
              >
                <strong>{{ block.title || '未命名故事块' }}</strong>
                <span>
                  分卷 {{ block.volumeRef || '未关联' }} ·
                  情节线 {{ block.plotRefs?.join('、') || '未关联' }}
                </span>
                <ol>
                  <li
                    v-for="stage in block.stages || []"
                    :key="stage.id || stage.clientNodeKey"
                  >
                    <b>{{ stage.title || '未命名阶段' }}</b>
                    <span>
                      {{ (stage.sceneTasks || []).map(task => task.task).filter(Boolean).join('；') || '尚无场景任务' }}
                    </span>
                  </li>
                </ol>
              </li>
            </ol>
            <p v-if="controller.complete.value" class="complete-note">
              聚合已完整。请先保存所有本地编辑，再确认不可变修订。
            </p>
            <p v-else class="incomplete-note">
              当前可保存为工作稿，但尚缺完整故事块 / 阶段 / 场景任务，不能确认。
            </p>
          </section>
        </div>

        <div v-if="controller.localOverlay.value" class="streaming-overlay" role="status" aria-live="polite">
          <strong>只读流式模式</strong>
          <span>AI 正在生成并核对当前工作稿；文字保持清晰，可上下滚动查看。</span>
        </div>
      </section>

      <chapter-outline-workspace
        v-if="activeTab === 'story-blocks' && store.outlineState !== undefined"
        :store="store"
        :controller="outlineController"
      />

      <section v-if="store.state.draft && controller.editable.value" class="ai-panel">
        <label for="planning-author-instructions">作者补充要求（可选）</label>
        <textarea
          id="planning-author-instructions"
          v-model="controller.authorInstructions.value"
          rows="3"
          maxlength="4000"
          :disabled="controller.editorLocked.value"
          placeholder="例如：强化第二卷群像冲突，但不要提前揭露残卷来源。"
        />
        <button
          type="button"
          :disabled="!controller.canGenerate.value"
          @click="run(controller.generate)"
        >
          AI 生成当前规划工作稿
        </button>
        <p v-if="controller.generationDisabledReason.value">
          {{ controller.generationDisabledReason.value }}
        </p>
      </section>

      <footer class="workspace-actions">
        <button type="button" @click="controller.historyOpen.value = true">修订历史</button>
        <template v-if="controller.editable.value">
          <button
            type="button"
            :disabled="!controller.canSave.value"
            @click="run(controller.save)"
          >
            保存工作稿
          </button>
          <button
            type="button"
            class="primary"
            :disabled="!controller.canConfirm.value"
            @click="openConfirm"
          >
            预览并确认
          </button>
        </template>
      </footer>
    </template>

    <Teleport to="body">
      <div v-if="confirmOpen" class="confirm-backdrop">
        <section
          ref="confirmDialog"
          class="confirm-panel"
          role="dialog"
          aria-modal="true"
          aria-label="确认故事规划"
          @keydown="handleConfirmKeydown"
        >
          <p>IMMUTABLE REVISION</p>
          <h2>确认完整规划修订</h2>
          <p>确认后会形成不可变历史版本。本次只提交已经保存的完整聚合，不会静默改写旧修订。</p>
          <dl>
            <div><dt>分卷</dt><dd>{{ counts.volumes }}</dd></div>
            <div><dt>情节线</dt><dd>{{ counts.plots }}</dd></div>
            <div><dt>故事块</dt><dd>{{ counts.storyBlocks }}</dd></div>
            <div><dt>阶段</dt><dd>{{ counts.stages }}</dd></div>
            <div><dt>场景任务</dt><dd>{{ counts.sceneTasks }}</dd></div>
          </dl>
          <p class="confirm-active">
            活动故事块：{{ activeStoryBlock?.title || '尚未选择' }}
          </p>
          <footer>
            <button ref="confirmInitial" type="button" :disabled="store.confirming" @click="closeConfirm">返回核对</button>
            <button type="button" class="primary" :disabled="store.confirming" @click="confirmPlanning">确认并签印</button>
          </footer>
        </section>
      </div>
    </Teleport>

    <planning-history-drawer
      :open="controller.historyOpen.value"
      :history="store.history"
      @close="controller.historyOpen.value = false"
    />
  </section>
</template>

<style scoped>
.planning-workspace { width:min(1120px,100%); margin:auto; color:var(--nc-ink); }
.workspace-header { display:flex; align-items:end; justify-content:space-between; gap:28px; margin-bottom:20px; }
.eyebrow,.aggregate-summary p:first-child,.empty-draft>span { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.18em; }
h1 { margin:6px 0 0; font:600 clamp(32px,5vw,52px) Georgia,'Noto Serif SC',serif; }
.lede { max-width:650px; margin:10px 0 0; color:var(--nc-muted); line-height:1.75; }
.revision-strip { display:flex; flex:none; overflow:hidden; border:1px solid var(--nc-border); border-radius:10px; background:var(--nc-paper); }
.revision-strip div { display:grid; min-width:100px; padding:10px 14px; }
.revision-strip div+div { border-left:1px solid var(--nc-border); }
.revision-strip span { color:var(--nc-muted); font-size:11px; }
.revision-strip strong { font:600 18px Georgia,serif; }
.notice,.read-only-banner,.error-summary,.recovery-summary { margin:0 0 14px; padding:12px 14px; border-left:3px solid var(--nc-vermilion); background:var(--nc-paper); }
.error-summary,.recovery-summary { display:flex; align-items:center; gap:12px; border:1px solid var(--nc-vermilion); }
.error-summary small { color:var(--nc-muted); }
.recovery-summary button { margin-left:auto; }
.read-only-banner { color:var(--nc-muted); border-color:var(--nc-muted); }
.paper-panel,.workspace-sheet,.ai-panel { border:1px solid var(--nc-border); background:var(--nc-paper); box-shadow:0 22px 58px color-mix(in srgb,var(--nc-ink) 8%,transparent); }
.paper-panel { padding:clamp(24px,4vw,44px); }
.paper-panel h2 { margin:6px 0; font:600 28px Georgia,'Noto Serif SC',serif; }
.paper-panel p { color:var(--nc-muted); line-height:1.7; }
.workspace-sheet { position:relative; min-height:420px; }
.workspace-scroll { max-height:calc(100vh - 320px); min-height:420px; overflow:auto; padding:clamp(20px,4vw,38px); transition:opacity .15s ease; }
.workspace-scroll.streaming-read-only { opacity:.72; }
.streaming-overlay { position:absolute; z-index:2; inset:0; display:flex; align-items:center; justify-content:center; flex-direction:column; gap:6px; pointer-events:none; color:var(--nc-ink); background:color-mix(in srgb,var(--nc-paper) 38%,transparent); text-align:center; }
.streaming-overlay span { max-width:42ch; color:var(--nc-muted); }
.aggregate-summary { margin-top:28px; padding-top:20px; border-top:2px solid var(--nc-vermilion); }
.aggregate-summary h2 { margin:5px 0 14px; font:600 24px Georgia,'Noto Serif SC',serif; }
.aggregate-summary dl,.confirm-panel dl { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:8px; margin:0; }
.aggregate-summary dl div,.confirm-panel dl div { padding:10px; border:1px solid var(--nc-border); }
dt { color:var(--nc-muted); font-size:11px; }
dd { margin:4px 0 0; font:600 20px Georgia,serif; }
.hierarchy-summary { display:grid; gap:10px; margin:16px 0 0; padding:0; list-style:none; }
.hierarchy-summary>li { display:grid; gap:4px; padding:12px 14px; border-left:2px solid var(--nc-border); background:var(--nc-paper); }
.hierarchy-summary span { color:var(--nc-muted); font-size:12px; line-height:1.6; }
.hierarchy-summary ol { display:grid; gap:5px; margin:7px 0 0; padding-left:18px; }
.hierarchy-summary ol li { display:grid; grid-template-columns:minmax(100px,.32fr) 1fr; gap:10px; }
.complete-note,.incomplete-note { margin:14px 0 0; padding:10px; line-height:1.6; }
.complete-note { color:#426c58; background:color-mix(in srgb,#426c58 8%,transparent); }
.incomplete-note { color:var(--nc-muted); background:var(--nc-canvas); }
.ai-panel { display:grid; gap:8px; margin-top:14px; padding:16px; }
.ai-panel textarea { border:1px solid var(--nc-border); border-radius:6px; padding:10px; color:var(--nc-ink); background:var(--nc-paper); font:inherit; resize:vertical; }
.ai-panel p { margin:0; color:var(--nc-muted); font-size:12px; }
button { border:1px solid var(--nc-border); border-radius:6px; padding:9px 13px; color:var(--nc-ink); background:var(--nc-paper); cursor:pointer; }
button:disabled { cursor:not-allowed; opacity:.45; }
.primary { border-color:var(--nc-vermilion); color:var(--nc-vermilion); }
.workspace-actions { display:flex; justify-content:flex-end; gap:10px; margin-top:14px; }
.confirm-backdrop { position:fixed; z-index:34; inset:0; display:grid; place-items:center; padding:24px; background:color-mix(in srgb,var(--nc-ink) 38%,transparent); }
.confirm-panel { width:min(620px,100%); padding:26px; color:var(--nc-ink); background:var(--nc-paper); box-shadow:0 24px 64px color-mix(in srgb,var(--nc-ink) 22%,transparent); }
.confirm-panel>p:first-child { color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.17em; }
.confirm-panel h2 { font:600 28px Georgia,'Noto Serif SC',serif; }
.confirm-panel dl { grid-template-columns:repeat(5,1fr); }
.confirm-active { margin:14px 0 0; padding:10px 12px; border-left:2px solid var(--nc-vermilion); background:var(--nc-canvas); color:var(--nc-muted); }
.confirm-panel footer { display:flex; justify-content:flex-end; gap:10px; margin-top:20px; }
@media(max-width:760px){.workspace-header{align-items:start;flex-direction:column}.revision-strip{width:100%}.revision-strip div{flex:1}.aggregate-summary dl,.confirm-panel dl{grid-template-columns:repeat(2,1fr)}.workspace-scroll{max-height:none}.error-summary{align-items:start;flex-direction:column}.error-summary button{margin-left:0}}
</style>
