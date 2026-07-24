<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { createModalFocusManager } from '../common/modalFocusManager.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  history: { type: Array, default: () => [] },
})

const emit = defineEmits(['close'])
const dialog = ref(null)
const initialFocus = ref(null)
const focus = createModalFocusManager({
  getDialog: () => dialog.value,
  getInitialFocus: () => initialFocus.value,
})
let ariaHiddenSnapshot = null

const DISPLAY_STATUS_LABELS = Object.freeze({
  current: '当前版本',
  superseded: '已被后续规划取代',
  archived: '项目已归档',
})
const DISPLAY_REASON_LABELS = Object.freeze({
  currentPlanningHead: '当前规划主版本',
  newerPlanningOrBasis: '已有更新规划或创作依据',
  projectArchived: '项目已归档',
})
const LIFECYCLE_LABELS = Object.freeze({
  active: '有效',
  retired: '已退役',
})
const listText = value => (
  Array.isArray(value) && value.length ? value.join('、') : '无'
)
const nodeId = node => String(node?.id || node?.clientNodeKey || '')
const knownValue = (values, value) => Object.hasOwn(values, String(value || ''))
const displayStatusLabel = value => (
  knownValue(DISPLAY_STATUS_LABELS, value)
    ? DISPLAY_STATUS_LABELS[value]
    : '状态不可用'
)
const displayReasonLabel = value => (
  knownValue(DISPLAY_REASON_LABELS, value)
    ? DISPLAY_REASON_LABELS[value]
    : '原因不可用'
)
const lifecycleLabel = value => (
  knownValue(LIFECYCLE_LABELS, value)
    ? LIFECYCLE_LABELS[value]
    : '生命周期不可用'
)
const lifecycleClass = value => (
  knownValue(LIFECYCLE_LABELS, value)
    ? `lifecycle-${value}`
    : 'lifecycle-unknown'
)

function relationLabel(items, targetId, kind) {
  const normalized = String(targetId || '')
  if (!normalized) return `未关联${kind}`
  const target = (items || []).find(item => nodeId(item) === normalized)
  return target
    ? `${target.title || `未命名${kind}`}（${normalized}）`
    : `未找到${kind}（${normalized}）`
}

function volumeRelation(content, block) {
  return relationLabel(content?.volumes, block?.volumeId, '分卷')
}

function plotRelations(content, block) {
  const ids = Array.isArray(block?.plotIds) ? block.plotIds : []
  return ids.length
    ? ids.map(id => relationLabel(content?.plots, id, '情节线')).join('、')
    : '无'
}

function isActiveStoryBlock(content, block) {
  return (
    String(content?.activeStoryBlockId || '')
    && String(content.activeStoryBlockId) === nodeId(block)
  )
}

function setBackgroundHidden(hidden) {
  const appRoot = globalThis.document?.querySelector?.('#app')
  if (!appRoot) return
  if (hidden) {
    ariaHiddenSnapshot = {
      root: appRoot,
      hadAttribute: appRoot.hasAttribute?.('aria-hidden') === true,
      value: appRoot.getAttribute?.('aria-hidden'),
    }
    appRoot.setAttribute?.('aria-hidden', 'true')
    return
  }
  if (!ariaHiddenSnapshot) return
  if (ariaHiddenSnapshot.hadAttribute) {
    ariaHiddenSnapshot.root.setAttribute?.(
      'aria-hidden',
      ariaHiddenSnapshot.value ?? '',
    )
  } else {
    ariaHiddenSnapshot.root.removeAttribute?.('aria-hidden')
  }
  ariaHiddenSnapshot = null
}

function close() {
  emit('close')
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  focus.trapTab(event)
}

watch(
  () => props.open,
  async open => {
    if (open) {
      setBackgroundHidden(true)
      await nextTick()
      focus.mount()
    } else {
      focus.unmount()
      setBackgroundHidden(false)
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  focus.unmount()
  setBackgroundHidden(false)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="drawer-backdrop" @click.self="close">
      <aside
        ref="dialog"
        class="history-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="规划修订历史"
        @keydown="handleKeydown"
      >
        <header>
          <div>
            <p>IMMUTABLE ARCHIVE</p>
            <h2>规划修订历史</h2>
          </div>
          <button ref="initialFocus" type="button" @click="close">关闭</button>
        </header>
        <p class="read-only-note">只读档案：历史修订仅供完整查阅，不产生任何写操作。</p>
        <ol v-if="history.length" class="revision-list">
          <li
            v-for="item in history"
            :key="item.planningRevisionId || item.revision"
            class="revision-card"
          >
            <div class="revision-heading">
              <span>R{{ item.revision }}</span>
              <strong>
                {{ item.content?.volumes?.length || 0 }} 卷 ·
                {{ item.content?.plots?.length || 0 }} 条情节线 ·
                {{ item.content?.storyBlocks?.length || 0 }} 个故事块
              </strong>
              <small>{{ item.createdAt || item.confirmedAt || '已确认修订' }}</small>
              <div class="revision-state">
                <b>{{ displayStatusLabel(item.displayStatus) }}</b>
                <small>{{ displayReasonLabel(item.displayReason) }}</small>
              </div>
            </div>

            <section>
              <h3>分卷</h3>
              <article
                v-for="volume in item.content?.volumes || []"
                :key="volume.id || volume.clientNodeKey"
                class="node-record"
                :class="lifecycleClass(volume.lifecycle)"
              >
                <div class="node-heading">
                  <h4>{{ volume.title || '未命名分卷' }}</h4>
                  <span class="lifecycle-marker">
                    分卷 · {{ lifecycleLabel(volume.lifecycle) }}
                  </span>
                </div>
                <dl>
                  <div><dt>核心变化</dt><dd>{{ volume.coreChange || '未填写' }}</dd></div>
                  <div><dt>主要压力</dt><dd>{{ volume.mainPressure || '未填写' }}</dd></div>
                  <div><dt>群像焦点</dt><dd>{{ listText(volume.ensembleFocus) }}</dd></div>
                  <div><dt>本卷禁区</dt><dd>{{ listText(volume.forbiddenEvents) }}</dd></div>
                </dl>
              </article>
            </section>

            <section>
              <h3>情节线</h3>
              <article
                v-for="plot in item.content?.plots || []"
                :key="plot.id || plot.clientNodeKey"
                class="node-record"
                :class="lifecycleClass(plot.lifecycle)"
              >
                <div class="node-heading">
                  <h4>{{ plot.title || '未命名情节线' }}</h4>
                  <span class="lifecycle-marker">
                    情节线 · {{ lifecycleLabel(plot.lifecycle) }}
                  </span>
                </div>
                <dl>
                  <div><dt>类型</dt><dd>{{ plot.plotType || '未填写' }}</dd></div>
                  <div><dt>故事问题</dt><dd>{{ plot.storyQuestion || '未填写' }}</dd></div>
                  <div><dt>未来走向</dt><dd>{{ plot.futureDirection || '未填写' }}</dd></div>
                  <div><dt>预期回报</dt><dd>{{ plot.expectedPayoff || '未填写' }}</dd></div>
                  <div><dt>相关人物</dt><dd>{{ listText(plot.relatedCharacters) }}</dd></div>
                </dl>
              </article>
            </section>

            <section>
              <h3>故事块、阶段与场景任务</h3>
              <article
                v-for="block in item.content?.storyBlocks || []"
                :key="block.id || block.clientNodeKey"
                class="node-record"
                :class="lifecycleClass(block.lifecycle)"
              >
                <div class="block-heading">
                  <h4>{{ block.title || '未命名故事块' }}</h4>
                  <div class="node-markers">
                    <span class="lifecycle-marker">
                      故事块 · {{ lifecycleLabel(block.lifecycle) }}
                    </span>
                    <strong v-if="isActiveStoryBlock(item.content, block)">
                      当前活动故事块
                    </strong>
                  </div>
                </div>
                <p class="block-relations">
                  所属分卷：{{ volumeRelation(item.content, block) }}
                </p>
                <p class="block-relations">
                  关联情节线：{{ plotRelations(item.content, block) }}
                </p>
                <dl>
                  <div><dt>进入情境</dt><dd>{{ block.entrySituation || '未填写' }}</dd></div>
                  <div><dt>故事块目标</dt><dd>{{ block.blockGoal || '未填写' }}</dd></div>
                  <div><dt>主要压力</dt><dd>{{ block.mainPressure || '未填写' }}</dd></div>
                  <div><dt>预期变化</dt><dd>{{ block.expectedChange || '未填写' }}</dd></div>
                  <div><dt>开放问题</dt><dd>{{ listText(block.openQuestions) }}</dd></div>
                  <div><dt>涉及人物</dt><dd>{{ listText(block.involvedCharacters) }}</dd></div>
                </dl>
                <ol class="stage-list">
                  <li
                    v-for="stage in block.stages || []"
                    :key="stage.id || stage.clientNodeKey"
                    :class="lifecycleClass(stage.lifecycle)"
                  >
                    <div class="node-heading">
                      <h5>{{ stage.title || '未命名阶段' }}</h5>
                      <span class="lifecycle-marker">
                        阶段 · {{ lifecycleLabel(stage.lifecycle) }}
                      </span>
                    </div>
                    <p><b>阶段目的：</b>{{ stage.purpose || '未填写' }}</p>
                    <p><b>戏剧问题：</b>{{ stage.dramaticQuestion || '未填写' }}</p>
                    <ul>
                      <li
                        v-for="task in stage.sceneTasks || []"
                        :key="task.id || task.clientNodeKey"
                        :class="lifecycleClass(task.lifecycle)"
                      >
                        <b>{{ task.task || '未命名任务' }}</b>
                        <small class="lifecycle-marker">
                          场景任务 · {{ lifecycleLabel(task.lifecycle) }}
                        </small>
                        <span>完成证据：{{ task.completionEvidence || '未填写' }}</span>
                      </li>
                    </ul>
                  </li>
                </ol>
              </article>
            </section>
          </li>
        </ol>
        <p v-else class="empty-copy">尚无已确认规划修订。</p>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.drawer-backdrop { position:fixed; z-index:36; inset:0; display:flex; justify-content:flex-end; background:color-mix(in srgb,var(--nc-ink) 32%,transparent); }
.history-drawer { width:min(680px,100%); height:100%; overflow:auto; padding:28px; color:var(--nc-ink); background:var(--nc-paper); box-shadow:-20px 0 50px color-mix(in srgb,var(--nc-ink) 18%,transparent); }
header { display:flex; align-items:start; justify-content:space-between; gap:20px; padding-bottom:16px; border-bottom:2px solid var(--nc-vermilion); }
header p { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.17em; }
h2 { margin:5px 0 0; font:600 26px Georgia,'Noto Serif SC',serif; }
button { border:1px solid var(--nc-border); border-radius:6px; padding:8px 12px; color:var(--nc-ink); background:var(--nc-paper); }
.read-only-note,.empty-copy { color:var(--nc-muted); line-height:1.7; }
.revision-list,.stage-list { display:grid; gap:16px; margin:18px 0 0; padding:0; list-style:none; }
.revision-card { display:grid; gap:20px; padding:18px 0 26px; border-bottom:1px solid var(--nc-border); }
.revision-heading { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; }
.revision-heading span { grid-row:span 2; color:var(--nc-vermilion); font:600 22px Georgia,serif; }
.revision-heading strong { font-size:14px; }
.revision-heading small { color:var(--nc-muted); }
.revision-state { grid-column:1 / -1; display:flex; align-items:center; gap:10px; margin-top:6px; }
.revision-state b { color:var(--nc-vermilion); font-size:13px; }
.revision-card section { display:grid; gap:10px; }
.revision-card h3 { margin:0; padding-bottom:7px; border-bottom:1px solid var(--nc-border); font-size:15px; }
.revision-card article { padding:13px; border:1px solid var(--nc-border); border-radius:8px; }
.revision-card h4,.revision-card h5 { margin:0 0 9px; }
.node-heading,.block-heading { display:flex; align-items:start; justify-content:space-between; gap:12px; }
.node-markers { display:flex; align-items:end; flex-direction:column; gap:5px; }
.block-heading strong { flex:none; color:var(--nc-vermilion); font-size:12px; }
.lifecycle-marker { color:var(--nc-muted); font-size:11px; }
.lifecycle-retired { border-left:3px solid var(--nc-muted) !important; background:color-mix(in srgb,var(--nc-muted) 8%,var(--nc-paper)) !important; }
.lifecycle-retired .lifecycle-marker { font-weight:700; }
.lifecycle-unknown { border:2px dashed var(--nc-vermilion) !important; }
.lifecycle-unknown .lifecycle-marker { color:var(--nc-vermilion); font-weight:700; }
.block-relations { margin:5px 0; color:var(--nc-muted); line-height:1.6; }
.revision-card dl { display:grid; gap:7px; margin:0; }
.revision-card dl div { display:grid; grid-template-columns:90px 1fr; gap:10px; }
.revision-card dt { color:var(--nc-muted); font-size:12px; }
.revision-card dd { margin:0; line-height:1.6; }
.stage-list { gap:10px; margin-top:12px; }
.stage-list>li { padding:11px; background:var(--nc-canvas); }
.stage-list p { margin:5px 0; line-height:1.6; }
.stage-list ul { display:grid; gap:6px; margin:9px 0 0; padding-left:20px; }
.stage-list ul li { display:grid; gap:2px; }
.stage-list ul span { color:var(--nc-muted); font-size:12px; }
</style>
