<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
} from 'vue'

import { createModalFocusManager } from '../common/modalFocusManager.js'
import ChapterOutlineHistoryDrawer from './ChapterOutlineHistoryDrawer.vue'

const props = defineProps({
  store: { type: Object, required: true },
  controller: { type: Object, required: true },
})

const confirmOpen = ref(false)
const confirmDialog = ref(null)
const confirmInitial = ref(null)
const confirmFocus = createModalFocusManager({
  getDialog: () => confirmDialog.value,
  getInitialFocus: () => confirmInitial.value,
})
const authorityContent = computed(() => (
  props.store.outlineState?.planningAuthority?.content || null
))
const displayContent = computed(() => (
  props.store.outlineLocalContent
  || props.store.outlineState?.draft?.content
  || props.store.outlineState?.confirmedOutline?.content
  || null
))
const activeNodes = items => (
  Array.isArray(items)
    ? items.filter(node => node?.lifecycle === 'active')
    : []
)
const activeStoryBlock = computed(() => (
  activeNodes(authorityContent.value?.storyBlocks).find(node => (
    node.id === authorityContent.value?.activeStoryBlockId
  )) || null
))
const storyBlocks = computed(() => (
  activeStoryBlock.value ? [activeStoryBlock.value] : []
))
const activeVolume = computed(() => (
  activeNodes(authorityContent.value?.volumes).find(node => (
    node.id === activeStoryBlock.value?.volumeId
  )) || null
))
const volumes = computed(() => activeVolume.value ? [activeVolume.value] : [])
const stages = computed(() => activeNodes(activeStoryBlock.value?.stages))
const selectedStageIds = computed(() => new Set(
  (displayContent.value?.stageRefs || []).map(node => node.id),
))
const sceneTasks = computed(() => stages.value.flatMap(stage => (
  selectedStageIds.value.has(stage.id)
    ? activeNodes(stage.sceneTasks)
    : []
)))
const chapterNumber = computed(() => (
  props.store.outlineState?.authoritativeChapterNumber || '—'
))
const authorityRefreshFailed = computed(() => (
  props.store.outlineState != null
  && props.store.outlineError?.code === 'ChapterOutlineRefreshFailed'
))
const outlineAdoptionLabel = computed(() => (
  props.store.outlineState?.confirmedOutline
    ? '更新当前小纲'
    : '采用小纲'
))

const clone = value => (
  value == null ? value : JSON.parse(JSON.stringify(value))
)
const exactRef = node => ({
  id: node.id,
  revision: node.revision,
  contentHash: node.contentHash,
})
const exactAllowedRefs = (refs, items) => {
  const selectedIds = new Set((refs || []).map(item => item.id))
  return items
    .filter(item => selectedIds.has(item.id))
    .map(exactRef)
}
const exactRefMatches = (refValue, node) => (
  refValue?.id === node?.id
  && refValue?.revision === node?.revision
  && refValue?.contentHash === node?.contentHash
)
const tasksForStages = (block, stageRefs) => {
  const stageIds = new Set((stageRefs || []).map(item => item.id))
  return activeNodes(block?.stages).flatMap(stage => (
    stageIds.has(stage.id) ? activeNodes(stage.sceneTasks) : []
  ))
}
const exactRefListIsSubset = (refs, items) => {
  const values = Array.isArray(refs) ? refs : []
  const ids = values.map(item => item?.id)
  return (
    new Set(ids).size === ids.length
    && values.every(item => (
      items.some(node => exactRefMatches(item, node))
    ))
  )
}
const hierarchyValid = computed(() => {
  const content = displayContent.value
  if (!content) return false
  const volumeRef = content.volumeRef
  const storyBlockRef = content.storyBlockRef
  const stageRefs = Array.isArray(content.stageRefs) ? content.stageRefs : []
  const sceneTaskRefs = Array.isArray(content.sceneTaskRefs)
    ? content.sceneTaskRefs
    : []
  if (!volumeRef) {
    return !storyBlockRef && !stageRefs.length && !sceneTaskRefs.length
  }
  if (!exactRefMatches(volumeRef, activeVolume.value)) return false
  if (!storyBlockRef) return !stageRefs.length && !sceneTaskRefs.length
  if (!exactRefMatches(storyBlockRef, activeStoryBlock.value)) return false
  if (!exactRefListIsSubset(stageRefs, stages.value)) return false
  return exactRefListIsSubset(
    sceneTaskRefs,
    tasksForStages(activeStoryBlock.value, stageRefs),
  )
})
const listValue = value => Array.isArray(value) ? value.join('\n') : ''
const parseList = value => String(value || '')
  .split(/\r?\n/u)
  .map(item => item.trim())
  .filter(Boolean)

function run(action) {
  Promise.resolve(action()).catch(() => {})
}

function edit(patch) {
  if (!props.controller.editable.value || props.controller.editorLocked.value) {
    return
  }
  props.controller.editLocal({
    ...clone(displayContent.value),
    ...patch,
  })
}

function selectVolume(id) {
  const volume = volumes.value.find(item => item.id === id)
  if (!volume) {
    edit({
      volumeRef: null,
      storyBlockRef: null,
      stageRefs: [],
      sceneTaskRefs: [],
    })
    return
  }
  const block = activeStoryBlock.value
  const keepBlock = (
    block?.volumeId === volume.id
    && displayContent.value?.storyBlockRef?.id === block.id
  )
  const nextStages = keepBlock
    ? exactAllowedRefs(displayContent.value?.stageRefs, stages.value)
    : []
  edit({
    volumeRef: exactRef(volume),
    storyBlockRef: keepBlock ? exactRef(block) : null,
    stageRefs: nextStages,
    sceneTaskRefs: keepBlock
      ? exactAllowedRefs(
          displayContent.value?.sceneTaskRefs,
          tasksForStages(block, nextStages),
        )
      : [],
  })
}

function selectStoryBlock(id) {
  const block = storyBlocks.value.find(item => item.id === id)
  if (!block) {
    edit({
      storyBlockRef: null,
      stageRefs: [],
      sceneTaskRefs: [],
    })
    return
  }
  const volume = volumes.value.find(item => item.id === block.volumeId)
  const nextStages = exactAllowedRefs(
    displayContent.value?.stageRefs,
    activeNodes(block.stages),
  )
  edit({
    volumeRef: volume ? exactRef(volume) : null,
    storyBlockRef: exactRef(block),
    stageRefs: nextStages,
    sceneTaskRefs: exactAllowedRefs(
      displayContent.value?.sceneTaskRefs,
      tasksForStages(block, nextStages),
    ),
  })
}

function toggleNode(field, items, id, checked) {
  const current = Array.isArray(displayContent.value?.[field])
    ? displayContent.value[field]
    : []
  const selected = items.find(item => item.id === id)
  const next = checked && selected
    ? [...current.filter(item => item.id !== id), exactRef(selected)]
    : current.filter(item => item.id !== id)
  if (field === 'stageRefs') {
    edit({
      stageRefs: next,
      sceneTaskRefs: exactAllowedRefs(
        displayContent.value?.sceneTaskRefs,
        tasksForStages(activeStoryBlock.value, next),
      ),
    })
    return
  }
  edit({ [field]: next })
}

function updateText(field, value) {
  edit({ [field]: value })
}

function updateList(field, value) {
  edit({ [field]: parseList(value) })
}

function openConfirm() {
  if (
    props.controller.canConfirm.value
    && hierarchyValid.value
  ) confirmOpen.value = true
}

function closeConfirm() {
  if (!props.store.outlineConfirming) confirmOpen.value = false
}

function handleConfirmKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    closeConfirm()
    return
  }
  confirmFocus.trapTab(event)
}

async function confirmOutline() {
  try {
    if (await props.controller.confirm()) confirmOpen.value = false
  } catch {
    // The Store exposes only a fixed public error envelope.
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
  () => props.store.outlineState?.projectId,
  () => { confirmOpen.value = false },
)
onBeforeUnmount(() => confirmFocus.unmount())
</script>

<template>
  <section class="outline-workspace" aria-labelledby="outline-heading">
    <header class="outline-header">
      <div>
        <p>CHAPTER OUTLINE · AUTHORITATIVE ENTRY</p>
        <h2 id="outline-heading">第 {{ chapterNumber }} 章小纲</h2>
        <span>从当前故事块收束本章任务；手工输入只保留在本地，保存时才推进工作稿。</span>
      </div>
      <p class="authority-strip" aria-label="章节小纲状态">章节小纲依据已同步</p>
    </header>

    <p
      v-if="controller.notice.value"
      class="notice"
      role="status"
      aria-live="polite"
    >
      {{ controller.notice.value }}
    </p>
    <section v-if="store.outlineError" class="error-summary" role="alert">
      <strong>{{ store.outlineError.message }}</strong>
      <small v-if="store.outlineError.correlationId">
        参考编号：{{ store.outlineError.correlationId }}
      </small>
      <button
        v-if="authorityRefreshFailed"
        type="button"
        :disabled="store.outlineLoading || controller.busy.value"
        @click="run(() => controller.hydrate({ force: true }))"
      >
        重新读取权威状态
      </button>
    </section>
    <section
      v-if="controller.hasCriticalRecovery.value"
      class="recovery-summary"
      role="status"
      aria-live="polite"
    >
      <strong>小纲生成结果尚未完成权威核对，本地文字保持不变。</strong>
      <button
        type="button"
        :disabled="store.outlineReconciling"
        @click="run(controller.reconcile)"
      >
        核对原操作
      </button>
    </section>
    <aside v-if="controller.recoveryActions.value.length" class="recovery-link">
      <span>当前权威状态暂不允许继续这一步。</span>
      <a
        v-for="action in controller.recoveryActions.value"
        :key="action.path"
        :href="action.path"
      >
        {{ action.label }}
      </a>
    </aside>

    <section
      v-if="store.outlineLoading && !store.outlineState"
      class="outline-paper"
      aria-busy="true"
    >
      正在读取权威章节入口…
    </section>
    <section v-else-if="!store.outlineState" class="outline-paper">
      <h3>章节小纲暂时无法加载</h3>
      <p>系统不会从当前页面或本地规划推导章节号。</p>
      <button type="button" @click="run(controller.hydrate)">重新加载</button>
    </section>

    <template v-else>
      <aside v-if="controller.readOnly.value" class="read-only-note">
        当前小纲为只读权威记录；本地字段与正式引用均不会被改写。
      </aside>
      <section
        v-if="controller.canAdjustOutline.value"
        class="outline-paper outline-adjustment"
      >
        <p>调整本章小纲</p>
        <span>采用后作为当前写作依据；正文定稿前仍可调整。</span>
      </section>

      <section
        v-if="store.outlineState.capabilities?.createDraft === true"
        class="outline-paper empty-outline"
      >
        <p>MANUAL DRAFT</p>
        <h3>建立新工作稿</h3>
        <span>旧内容保持只读；新工作稿不会自动确认或创建写作会话。</span>
        <button
          type="button"
          :disabled="!controller.canCreateDraft.value"
          @click="run(controller.createManualDraft)"
        >
          建立新工作稿
        </button>
      </section>

      <section
        v-if="displayContent"
        class="outline-sheet"
        :class="{ 'outline-sheet--locked': controller.localOverlay.value }"
      >
        <div
          class="outline-scroll"
          :inert="controller.localOverlay.value || undefined"
        >
          <fieldset :disabled="controller.editorLocked.value">
            <div class="reference-grid">
              <label>
                所属分卷
                <select
                  :value="displayContent.volumeRef?.id || ''"
                  :disabled="!controller.editable.value || controller.editorLocked.value"
                  @change="selectVolume($event.target.value)"
                >
                  <option value="">请选择活动分卷</option>
                  <option
                    v-for="node in volumes"
                    :key="node.id"
                    :value="node.id"
                  >
                    {{ node.title || node.id }}
                  </option>
                </select>
              </label>
              <label>
                当前故事块
                <select
                  :value="displayContent.storyBlockRef?.id || ''"
                  :disabled="!controller.editable.value || controller.editorLocked.value"
                  @change="selectStoryBlock($event.target.value)"
                >
                  <option value="">请选择活动故事块</option>
                  <option
                    v-for="node in storyBlocks"
                    :key="node.id"
                    :value="node.id"
                  >
                    {{ node.title || node.id }}
                  </option>
                </select>
              </label>
            </div>

            <fieldset class="reference-list">
              <legend>关联阶段</legend>
              <p v-if="!stages.length">当前故事块没有可引用的活动阶段。</p>
              <label v-for="node in stages" :key="node.id">
                <input
                  type="checkbox"
                  :checked="(displayContent.stageRefs || []).some(item => item.id === node.id)"
                  :disabled="!controller.editable.value || controller.editorLocked.value"
                  @change="
                    toggleNode(
                      'stageRefs',
                      stages,
                      node.id,
                      $event.target.checked,
                    )
                  "
                >
                <span>{{ node.title || node.id }}</span>
              </label>
            </fieldset>

            <fieldset class="reference-list">
              <legend>关联场景任务</legend>
              <p v-if="!sceneTasks.length">先选择阶段，再勾选其中的活动场景任务。</p>
              <label v-for="node in sceneTasks" :key="node.id">
                <input
                  type="checkbox"
                  :checked="(displayContent.sceneTaskRefs || []).some(item => item.id === node.id)"
                  :disabled="!controller.editable.value || controller.editorLocked.value"
                  @change="
                    toggleNode(
                      'sceneTaskRefs',
                      sceneTasks,
                      node.id,
                      $event.target.checked,
                    )
                  "
                >
                <span>{{ node.task || node.id }}</span>
              </label>
            </fieldset>

            <label class="wide-field">
              本章目标
              <textarea
                :value="displayContent.chapterGoal"
                :readonly="!controller.editable.value"
                rows="4"
                maxlength="4000"
                @input="updateText('chapterGoal', $event.target.value)"
              />
            </label>
            <div class="text-grid">
              <label>
                预计出场人物（每行一项）
                <textarea
                  :value="listValue(displayContent.expectedCharacters)"
                  :readonly="!controller.editable.value"
                  rows="4"
                  @input="updateList('expectedCharacters', $event.target.value)"
                />
              </label>
              <label>
                承接的未完成情节（每行一项）
                <textarea
                  :value="listValue(displayContent.continuation)"
                  :readonly="!controller.editable.value"
                  rows="4"
                  @input="updateList('continuation', $event.target.value)"
                />
              </label>
              <label>
                计划推进的任务（每行一项）
                <textarea
                  :value="listValue(displayContent.plannedTasks)"
                  :readonly="!controller.editable.value"
                  rows="4"
                  @input="updateList('plannedTasks', $event.target.value)"
                />
              </label>
              <label>
                主要场景（每行一项）
                <textarea
                  :value="listValue(displayContent.scenes)"
                  :readonly="!controller.editable.value"
                  rows="4"
                  @input="updateList('scenes', $event.target.value)"
                />
              </label>
            </div>
            <label class="wide-field">
              不应提前发生的内容（每行一项）
              <textarea
                :value="listValue(displayContent.forbiddenEarlyEvents)"
                :readonly="!controller.editable.value"
                rows="4"
                @input="updateList('forbiddenEarlyEvents', $event.target.value)"
              />
            </label>
          </fieldset>
        </div>
        <div
          v-if="controller.localOverlay.value"
          class="outline-local-overlay"
          role="status"
          aria-live="polite"
        >
          <strong>小纲生成只读模式</strong>
          <span>仅锁定本区；故事规划仍可独立查看和操作。</span>
        </div>
      </section>

      <section
        v-if="store.outlineState.draft && controller.editable.value"
        class="outline-ai"
      >
        <label for="outline-author-instructions">作者补充要求（可选）</label>
        <textarea
          id="outline-author-instructions"
          v-model="controller.authorInstructions.value"
          rows="3"
          maxlength="4000"
          :disabled="controller.editorLocked.value"
          placeholder="例如：本章保持潜入压力，不要提前揭露残卷来源。"
        />
        <div>
          <button
            type="button"
            :disabled="!controller.canGenerate.value"
            @click="run(controller.generate)"
          >
            AI 生成当前小纲工作稿
          </button>
          <p v-if="controller.generationDisabledReason.value">
            {{ controller.generationDisabledReason.value }}
          </p>
        </div>
      </section>

      <footer class="outline-actions">
        <button type="button" @click="controller.openHistory">小纲历史</button>
        <template v-if="controller.editable.value">
          <button
            type="button"
            :disabled="!controller.canSave.value || !hierarchyValid"
            @click="run(controller.save)"
          >
            保存小纲工作稿
          </button>
          <button
            type="button"
            class="primary"
            :disabled="!controller.canConfirm.value || !hierarchyValid"
            @click="openConfirm"
          >
            {{ outlineAdoptionLabel }}
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
          aria-label="确认章节小纲"
          @keydown="handleConfirmKeydown"
        >
          <p>IMMUTABLE CHAPTER OUTLINE</p>
          <h3>确认第 {{ chapterNumber }} 章小纲</h3>
          <p>确认后形成不可变修订；只提交已保存工作稿，不会创建写作会话。</p>
          <blockquote>{{ displayContent?.chapterGoal || '本章目标尚未填写' }}</blockquote>
          <footer>
            <button
              ref="confirmInitial"
              type="button"
              :disabled="store.outlineConfirming"
              @click="closeConfirm"
            >
              返回核对
            </button>
            <button
              type="button"
              class="primary"
              :disabled="store.outlineConfirming"
              @click="confirmOutline"
            >
              确认并签印
            </button>
          </footer>
        </section>
      </div>
    </Teleport>

    <chapter-outline-history-drawer
      :open="controller.historyOpen.value"
      :history="store.outlineHistory"
      @close="controller.closeHistory"
    />
  </section>
</template>

<style scoped>
.outline-workspace { display:grid; gap:14px; margin-top:28px; padding-top:28px; border-top:3px double var(--nc-border); color:var(--nc-ink); }
.outline-header { display:flex; align-items:end; justify-content:space-between; gap:24px; }
.outline-header p,.empty-outline>p,.confirm-panel>p:first-child { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.17em; }
.outline-header h2 { margin:5px 0 6px; font:600 30px Georgia,'Noto Serif SC',serif; }
.outline-header span,.empty-outline span { color:var(--nc-muted); line-height:1.7; }
.authority-strip { flex:none; margin:0; padding:9px 12px; border:1px solid var(--nc-border); border-radius:8px; color:var(--nc-muted); background:var(--nc-paper); font:600 13px Georgia,'Noto Serif SC',serif; }
.notice,.read-only-note,.recovery-link,.error-summary,.recovery-summary { margin:0; padding:11px 13px; border-left:3px solid var(--nc-vermilion); background:var(--nc-paper); }
.error-summary,.recovery-summary,.recovery-link { display:flex; align-items:center; gap:12px; border:1px solid var(--nc-border); }
.error-summary small { color:var(--nc-muted); }
.recovery-summary button,.recovery-link a { margin-left:auto; }
.recovery-link a { color:var(--nc-vermilion); font-weight:700; }
.outline-paper,.outline-sheet,.outline-ai { border:1px solid var(--nc-border); background:var(--nc-paper); box-shadow:0 18px 42px color-mix(in srgb,var(--nc-ink) 7%,transparent); }
.outline-paper { display:grid; gap:10px; padding:26px; }
.outline-paper h3 { margin:0; font:600 24px Georgia,'Noto Serif SC',serif; }
.outline-adjustment { gap:4px; padding:16px 20px; }
.outline-adjustment p { margin:0; color:var(--nc-vermilion); font-weight:700; }
.empty-outline button { justify-self:start; margin-top:6px; }
.outline-sheet { position:relative; }
.outline-scroll { max-height:min(720px,calc(100vh - 180px)); overflow:auto; padding:24px; transition:opacity .15s ease; }
.outline-sheet--locked .outline-scroll { opacity:.72; }
.outline-local-overlay { position:absolute; z-index:2; inset:0; display:flex; align-items:center; justify-content:center; flex-direction:column; gap:5px; pointer-events:none; background:color-mix(in srgb,var(--nc-paper) 35%,transparent); text-align:center; }
.outline-local-overlay span { color:var(--nc-muted); }
fieldset { margin:0; padding:0; border:0; }
.reference-grid,.text-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
label { display:grid; gap:6px; color:var(--nc-muted); font-size:12px; }
select,textarea { width:100%; box-sizing:border-box; border:1px solid var(--nc-border); border-radius:6px; padding:10px 12px; color:var(--nc-ink); background:var(--nc-paper); font:inherit; line-height:1.6; resize:vertical; }
.reference-list { display:flex; flex-wrap:wrap; gap:8px 16px; margin:16px 0; padding:12px; border:1px solid var(--nc-border); border-radius:6px; }
.reference-list legend { padding:0 5px; color:var(--nc-muted); font-size:12px; }
.reference-list label { display:flex; align-items:center; grid-auto-flow:column; }
.reference-list p { width:100%; margin:0; color:var(--nc-muted); font-size:12px; }
.wide-field { margin-top:14px; }
.outline-ai { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:12px; align-items:end; padding:16px; }
.outline-ai>div { display:grid; gap:5px; }
.outline-ai p { max-width:32ch; margin:0; color:var(--nc-muted); font-size:11px; }
button { border:1px solid var(--nc-border); border-radius:6px; padding:9px 13px; color:var(--nc-ink); background:var(--nc-paper); cursor:pointer; }
button:disabled { cursor:not-allowed; opacity:.45; }
.primary { border-color:var(--nc-vermilion); color:var(--nc-vermilion); }
.outline-actions { display:flex; justify-content:flex-end; gap:10px; }
.confirm-backdrop { position:fixed; z-index:34; inset:0; display:grid; place-items:center; padding:24px; background:color-mix(in srgb,var(--nc-ink) 38%,transparent); }
.confirm-panel { width:min(560px,100%); padding:26px; color:var(--nc-ink); background:var(--nc-paper); box-shadow:0 24px 64px color-mix(in srgb,var(--nc-ink) 22%,transparent); }
.confirm-panel h3 { margin:7px 0; font:600 27px Georgia,'Noto Serif SC',serif; }
.confirm-panel blockquote { margin:16px 0; padding:12px 14px; border-left:2px solid var(--nc-vermilion); background:var(--nc-canvas); }
.confirm-panel footer { display:flex; justify-content:flex-end; gap:10px; margin-top:18px; }
@media(max-width:760px){
  .outline-header{align-items:start;flex-direction:column}
  .authority-strip{width:100%}
  .reference-grid,.text-grid,.outline-ai{grid-template-columns:1fr}
  .outline-scroll{max-height:none}
  .outline-actions{flex-wrap:wrap}
  .outline-actions button{width:100%}
}
</style>
