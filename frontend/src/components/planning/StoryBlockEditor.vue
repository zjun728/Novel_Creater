<script setup>
import { computed } from 'vue'

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  volumes: { type: Array, default: () => [] },
  plots: { type: Array, default: () => [] },
  activeStoryBlockRef: { type: [String, Number], default: '' },
  undoAvailable: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits([
  'add',
  'update',
  'remove',
  'move',
  'select',
  'undo',
  'add-stage',
  'update-stage',
  'remove-stage',
  'move-stage',
  'add-scene-task',
  'update-scene-task',
  'remove-scene-task',
  'move-scene-task',
])

const nodeKey = node => String(node?.id || node?.clientNodeKey || '')
const activeNodes = items => (
  Array.isArray(items) ? items.filter(node => node.lifecycle === 'active') : []
)
const activeVolumes = computed(() => activeNodes(props.volumes))
const activePlots = computed(() => activeNodes(props.plots))
const blockHeadingId = blockIndex => `story-block-heading-${blockIndex}`
const stageHeadingId = (blockIndex, stageIndex) => (
  `story-stage-heading-${blockIndex}-${stageIndex}`
)
const taskHeadingId = (blockIndex, stageIndex, taskIndex) => (
  `story-task-heading-${blockIndex}-${stageIndex}-${taskIndex}`
)
const volumeOptions = block => {
  const referencedKey = String(block?.volumeRef || '')
  const retiredReference = props.volumes.find(volume => (
    nodeKey(volume) === referencedKey && volume.lifecycle !== 'active'
  ))
  return retiredReference
    ? [...activeVolumes.value, retiredReference]
    : activeVolumes.value
}
const plotOptions = block => {
  const referencedKeys = new Set(
    (Array.isArray(block?.plotRefs) ? block.plotRefs : []).map(String),
  )
  const retiredReferences = props.plots.filter(plot => (
    plot.lifecycle !== 'active' && referencedKeys.has(nodeKey(plot))
  ))
  return [...activePlots.value, ...retiredReferences]
}
const listValue = value => Array.isArray(value) ? value.join('\n') : ''
const parseList = value => String(value || '')
  .split(/\r?\n/u)
  .map(item => item.trim())
  .filter(Boolean)
const isActiveBlock = block => (
  nodeKey(block) === String(props.activeStoryBlockRef || '')
)
const controlDisabled = node => (
  props.readOnly || props.disabled || node?.lifecycle !== 'active'
)
const activePosition = (items, node) => (
  activeNodes(items).findIndex(item => nodeKey(item) === nodeKey(node))
)
const cannotMove = (items, node, direction) => {
  const position = activePosition(items, node)
  const target = position + direction
  return position < 0 || target < 0 || target >= activeNodes(items).length
}

function add() {
  if (!props.readOnly && !props.disabled) emit('add')
}

function update(block, field, value) {
  if (controlDisabled(block)) return
  emit('update', nodeKey(block), {
    [field]: ['openQuestions', 'involvedCharacters'].includes(field)
      ? parseList(value)
      : value,
  })
}

function togglePlot(block, plotRef, checked) {
  if (controlDisabled(block)) return
  const refs = Array.isArray(block.plotRefs)
    ? block.plotRefs.map(value => String(value))
    : []
  const next = checked
    ? [...new Set([...refs, String(plotRef)])]
    : refs.filter(value => value !== String(plotRef))
  emit('update', nodeKey(block), { plotRefs: next })
}

function move(block, direction) {
  if (
    !props.readOnly
    && !props.disabled
    && !cannotMove(props.modelValue, block, direction)
  ) {
    emit('move', nodeKey(block), direction)
  }
}

function select(block) {
  if (!controlDisabled(block) && !isActiveBlock(block)) {
    emit('select', nodeKey(block))
  }
}

function remove(block) {
  if (controlDisabled(block)) return
  emit('remove', nodeKey(block))
}

function addStage(block) {
  if (!controlDisabled(block)) emit('add-stage', nodeKey(block))
}

function updateStage(block, stage, field, value) {
  if (controlDisabled(block) || controlDisabled(stage)) return
  emit('update-stage', nodeKey(block), nodeKey(stage), { [field]: value })
}

function moveStage(block, stage, direction) {
  if (
    !controlDisabled(block)
    && !controlDisabled(stage)
    && !cannotMove(block.stages, stage, direction)
  ) {
    emit('move-stage', nodeKey(block), nodeKey(stage), direction)
  }
}

function removeStage(block, stage) {
  if (controlDisabled(block) || controlDisabled(stage)) return
  emit('remove-stage', nodeKey(block), nodeKey(stage))
}

function addSceneTask(block, stage) {
  if (!controlDisabled(block) && !controlDisabled(stage)) {
    emit('add-scene-task', nodeKey(block), nodeKey(stage))
  }
}

function updateSceneTask(block, stage, sceneTask, field, value) {
  if (
    controlDisabled(block)
    || controlDisabled(stage)
    || controlDisabled(sceneTask)
  ) return
  emit(
    'update-scene-task',
    nodeKey(block),
    nodeKey(stage),
    nodeKey(sceneTask),
    { [field]: value },
  )
}

function moveSceneTask(block, stage, sceneTask, direction) {
  if (
    !controlDisabled(block)
    && !controlDisabled(stage)
    && !controlDisabled(sceneTask)
    && !cannotMove(stage.sceneTasks, sceneTask, direction)
  ) {
    emit(
      'move-scene-task',
      nodeKey(block),
      nodeKey(stage),
      nodeKey(sceneTask),
      direction,
    )
  }
}

function removeSceneTask(block, stage, sceneTask) {
  if (
    controlDisabled(block)
    || controlDisabled(stage)
    || controlDisabled(sceneTask)
  ) return
  emit(
    'remove-scene-task',
    nodeKey(block),
    nodeKey(stage),
    nodeKey(sceneTask),
  )
}

function undo() {
  if (props.readOnly || props.disabled || !props.undoAvailable) return
  emit('undo')
}
</script>

<template>
  <section class="story-block-editor" aria-labelledby="story-block-editor-heading">
    <header class="editor-header">
      <div>
        <p>STORY BLOCK DESK</p>
        <h2 id="story-block-editor-heading">故事块编排</h2>
      </div>
      <button v-if="!readOnly" type="button" :disabled="disabled" @click="add">
        新增故事块
      </button>
    </header>

    <p class="editor-intro">
      把分卷与情节线落实为可执行的阶段和场景任务；当前活动故事块会成为后续写作焦点。
    </p>

    <aside
      v-if="undoAvailable && !readOnly"
      class="undo-note"
      role="status"
      aria-live="polite"
    >
      <span>已移除新增节点，可撤销一次。</span>
      <button type="button" :disabled="disabled" @click="undo">
        撤销上次物理删除
      </button>
    </aside>

    <article
      v-for="(block, blockIndex) in modelValue"
      :key="nodeKey(block)"
      class="story-block-card"
      :class="{
        active: isActiveBlock(block),
        retired: block.lifecycle !== 'active',
      }"
      :aria-labelledby="blockHeadingId(blockIndex)"
    >
      <div class="block-heading">
        <div>
          <h3 :id="blockHeadingId(blockIndex)">故事块 {{ String(blockIndex + 1).padStart(2, '0') }} · {{ block.title || '未命名故事块' }}</h3>
          <strong v-if="block.lifecycle !== 'active'">已退役 · 只读保留</strong>
          <strong v-else-if="isActiveBlock(block)" class="active-mark">
            当前活动故事块
          </strong>
        </div>
        <button
          v-if="!readOnly && block.lifecycle === 'active' && !isActiveBlock(block)"
          type="button"
          :disabled="disabled"
          @click="select(block)"
        >
          设为当前活动块
        </button>
      </div>

      <fieldset :disabled="disabled" class="block-fields">
        <label>
          故事块标题
          <input
            :value="block.title"
            :readonly="controlDisabled(block)"
            :disabled="disabled"
            @input="update(block, 'title', $event.target.value)"
          >
        </label>
        <label>
          所属分卷
          <select
            :value="block.volumeRef"
            :disabled="controlDisabled(block)"
            @change="update(block, 'volumeRef', $event.target.value)"
          >
            <option value="">请选择活动分卷</option>
            <option
              v-for="volume in volumeOptions(block)"
              :key="nodeKey(volume)"
              :value="nodeKey(volume)"
              :disabled="volume.lifecycle !== 'active'"
            >
              {{ volume.title || '未命名分卷' }}
              <template v-if="volume.lifecycle !== 'active'"> · 已退役</template>
            </option>
          </select>
        </label>
        <fieldset class="plot-refs" :disabled="controlDisabled(block)">
          <legend>关联情节线</legend>
          <p v-if="!plotOptions(block).length">暂无可引用的活动情节线</p>
          <label v-for="plot in plotOptions(block)" :key="nodeKey(plot)">
            <input
              type="checkbox"
              :value="nodeKey(plot)"
              :checked="(block.plotRefs || []).map(String).includes(nodeKey(plot))"
              :disabled="controlDisabled(block)"
              @change="togglePlot(block, nodeKey(plot), $event.target.checked)"
            >
            <span>
              {{ plot.title || '未命名情节线' }}
              <template v-if="plot.lifecycle !== 'active'"> · 已退役</template>
            </span>
          </label>
        </fieldset>
        <label>
          进入情境
          <textarea
            :value="block.entrySituation"
            :readonly="controlDisabled(block)"
            :disabled="disabled"
            rows="3"
            @input="update(block, 'entrySituation', $event.target.value)"
          />
        </label>
        <label>
          故事块目标
          <textarea
            :value="block.blockGoal"
            :readonly="controlDisabled(block)"
            :disabled="disabled"
            rows="3"
            @input="update(block, 'blockGoal', $event.target.value)"
          />
        </label>
        <label>
          主要压力
          <textarea
            :value="block.mainPressure"
            :readonly="controlDisabled(block)"
            :disabled="disabled"
            rows="3"
            @input="update(block, 'mainPressure', $event.target.value)"
          />
        </label>
        <label>
          预期变化
          <textarea
            :value="block.expectedChange"
            :readonly="controlDisabled(block)"
            :disabled="disabled"
            rows="3"
            @input="update(block, 'expectedChange', $event.target.value)"
          />
        </label>
        <label>
          开放问题（每行一项）
          <textarea
            :value="listValue(block.openQuestions)"
            :readonly="controlDisabled(block)"
            :disabled="disabled"
            rows="3"
            @input="update(block, 'openQuestions', $event.target.value)"
          />
        </label>
        <label>
          涉及人物（每行一项）
          <textarea
            :value="listValue(block.involvedCharacters)"
            :readonly="controlDisabled(block)"
            :disabled="disabled"
            rows="3"
            @input="update(block, 'involvedCharacters', $event.target.value)"
          />
        </label>
      </fieldset>

      <section
        v-for="(stage, stageIndex) in block.stages || []"
        :key="nodeKey(stage)"
        class="stage-card"
        :class="{ retired: stage.lifecycle !== 'active' }"
        :aria-labelledby="stageHeadingId(blockIndex, stageIndex)"
      >
        <div class="nested-heading">
          <h4 :id="stageHeadingId(blockIndex, stageIndex)">阶段 {{ String(stageIndex + 1).padStart(2, '0') }} · {{ stage.title || '未命名阶段' }}</h4>
          <strong v-if="stage.lifecycle !== 'active'">已退役 · 只读保留</strong>
        </div>
        <fieldset
          :disabled="disabled"
          class="stage-fields"
        >
          <label>
            阶段标题
            <input
              :value="stage.title"
              :readonly="controlDisabled(block) || controlDisabled(stage)"
              :disabled="disabled"
              @input="updateStage(block, stage, 'title', $event.target.value)"
            >
          </label>
          <label>
            阶段目的
            <textarea
              :value="stage.purpose"
              :readonly="controlDisabled(block) || controlDisabled(stage)"
              :disabled="disabled"
              rows="2"
              @input="updateStage(block, stage, 'purpose', $event.target.value)"
            />
          </label>
          <label>
            戏剧问题
            <textarea
              :value="stage.dramaticQuestion"
              :readonly="controlDisabled(block) || controlDisabled(stage)"
              :disabled="disabled"
              rows="2"
              @input="updateStage(block, stage, 'dramaticQuestion', $event.target.value)"
            />
          </label>
        </fieldset>

        <section class="scene-task-list" aria-label="场景任务">
          <article
            v-for="(sceneTask, taskIndex) in stage.sceneTasks || []"
            :key="nodeKey(sceneTask)"
            class="scene-task"
            :class="{ retired: sceneTask.lifecycle !== 'active' }"
            :aria-labelledby="taskHeadingId(blockIndex, stageIndex, taskIndex)"
          >
            <div class="nested-heading">
              <h5 :id="taskHeadingId(blockIndex, stageIndex, taskIndex)">场景任务 {{ String(taskIndex + 1).padStart(2, '0') }} · {{ sceneTask.task || '未命名场景任务' }}</h5>
              <strong v-if="sceneTask.lifecycle !== 'active'">已退役 · 只读保留</strong>
            </div>
            <fieldset
              :disabled="disabled"
              class="task-fields"
            >
              <label>
                场景任务
                <textarea
                  :value="sceneTask.task"
                  :readonly="
                    controlDisabled(block)
                      || controlDisabled(stage)
                      || controlDisabled(sceneTask)
                  "
                  :disabled="disabled"
                  rows="2"
                  @input="
                    updateSceneTask(
                      block,
                      stage,
                      sceneTask,
                      'task',
                      $event.target.value,
                    )
                  "
                />
              </label>
              <label>
                完成证据
                <textarea
                  :value="sceneTask.completionEvidence"
                  :readonly="
                    controlDisabled(block)
                      || controlDisabled(stage)
                      || controlDisabled(sceneTask)
                  "
                  :disabled="disabled"
                  rows="2"
                  @input="
                    updateSceneTask(
                      block,
                      stage,
                      sceneTask,
                      'completionEvidence',
                      $event.target.value,
                    )
                  "
                />
              </label>
            </fieldset>
            <footer
              v-if="
                !readOnly
                  && block.lifecycle === 'active'
                  && stage.lifecycle === 'active'
                  && sceneTask.lifecycle === 'active'
              "
              class="nested-actions"
            >
              <button
                type="button"
                :disabled="disabled || cannotMove(stage.sceneTasks, sceneTask, -1)"
                @click="moveSceneTask(block, stage, sceneTask, -1)"
              >
                上移场景任务
              </button>
              <button
                type="button"
                :disabled="disabled || cannotMove(stage.sceneTasks, sceneTask, 1)"
                @click="moveSceneTask(block, stage, sceneTask, 1)"
              >
                下移场景任务
              </button>
              <button
                type="button"
                class="danger"
                :disabled="disabled"
                @click="removeSceneTask(block, stage, sceneTask)"
              >
                {{ sceneTask.id ? '退役场景任务' : '撤销新增场景任务' }}
              </button>
            </footer>
          </article>
          <button
            v-if="
              !readOnly
                && block.lifecycle === 'active'
                && stage.lifecycle === 'active'
            "
            type="button"
            class="nested-add"
            :disabled="disabled"
            @click="addSceneTask(block, stage)"
          >
            新增场景任务
          </button>
        </section>

        <footer
          v-if="
            !readOnly
              && block.lifecycle === 'active'
              && stage.lifecycle === 'active'
          "
          class="nested-actions"
        >
          <button
            type="button"
            :disabled="disabled || cannotMove(block.stages, stage, -1)"
            @click="moveStage(block, stage, -1)"
          >
            上移阶段
          </button>
          <button
            type="button"
            :disabled="disabled || cannotMove(block.stages, stage, 1)"
            @click="moveStage(block, stage, 1)"
          >
            下移阶段
          </button>
          <button
            type="button"
            class="danger"
            :disabled="disabled"
            @click="removeStage(block, stage)"
          >
            {{ stage.id ? '退役阶段' : '撤销新增阶段' }}
          </button>
        </footer>
      </section>

      <button
        v-if="!readOnly && block.lifecycle === 'active'"
        type="button"
        class="nested-add"
        :disabled="disabled"
        @click="addStage(block)"
      >
        新增阶段
      </button>

      <footer
        v-if="!readOnly && block.lifecycle === 'active'"
        class="block-actions"
      >
        <button
          type="button"
          :disabled="disabled || cannotMove(modelValue, block, -1)"
          @click="move(block, -1)"
        >
          上移故事块
        </button>
        <button
          type="button"
          :disabled="disabled || cannotMove(modelValue, block, 1)"
          @click="move(block, 1)"
        >
          下移故事块
        </button>
        <button
          type="button"
          class="danger"
          :disabled="disabled"
          @click="remove(block)"
        >
          {{ block.id ? '退役故事块' : '撤销新增故事块' }}
        </button>
      </footer>
    </article>

    <p v-if="!modelValue.length" class="empty-copy">
      尚无故事块。先建立一个故事块，再选择分卷、情节线并拆出阶段与场景任务。
    </p>
  </section>
</template>

<style scoped>
.story-block-editor { display:grid; gap:16px; }
.editor-header { display:flex; align-items:end; justify-content:space-between; gap:18px; }
.editor-header p { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.18em; }
h2 { margin:4px 0 0; font:600 28px Georgia,'Noto Serif SC',serif; }
.editor-intro,.empty-copy { margin:0; color:var(--nc-muted); line-height:1.7; }
.undo-note { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 12px; border-left:3px solid var(--nc-vermilion); background:var(--nc-canvas); color:var(--nc-muted); }
.story-block-card { padding:18px; border:1px solid var(--nc-border); border-radius:10px; background:color-mix(in srgb,var(--nc-paper) 96%,var(--nc-canvas)); }
.story-block-card.active { border-color:var(--nc-vermilion); box-shadow:inset 3px 0 0 var(--nc-vermilion); }
.retired { border-style:dashed; }
.block-heading,.nested-heading { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.block-heading>div { display:flex; align-items:center; gap:12px; color:var(--nc-muted); font-size:12px; letter-spacing:.06em; }
.block-heading h3 { margin:0; color:var(--nc-ink); font:600 19px Georgia,'Noto Serif SC',serif; letter-spacing:0; }
.active-mark { color:var(--nc-vermilion); }
fieldset { margin:0; padding:0; border:0; }
.block-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin-top:14px; }
label { display:grid; gap:6px; color:var(--nc-muted); font-size:12px; }
.block-fields>label:nth-of-type(n+3) { grid-column:span 2; }
.plot-refs { grid-column:span 2; display:flex; flex-wrap:wrap; gap:8px 14px; padding:12px; border:1px solid var(--nc-border); border-radius:6px; }
.plot-refs legend { padding:0 5px; color:var(--nc-muted); font-size:12px; }
.plot-refs label { display:flex; align-items:center; grid-auto-flow:column; }
.plot-refs p { width:100%; margin:0; color:var(--nc-muted); font-size:12px; }
input:not([type='checkbox']),select,textarea { width:100%; box-sizing:border-box; border:1px solid var(--nc-border); border-radius:6px; padding:10px 12px; color:var(--nc-ink); background:var(--nc-paper); font:inherit; line-height:1.6; resize:vertical; }
button { border:1px solid var(--nc-border); border-radius:6px; padding:8px 12px; color:var(--nc-ink); background:var(--nc-paper); cursor:pointer; }
button:disabled { cursor:not-allowed; opacity:.45; }
.editor-header button,.nested-add { border-color:var(--nc-vermilion); color:var(--nc-vermilion); }
.stage-card { margin-top:18px; padding:15px; border-left:2px solid var(--nc-border); background:var(--nc-paper); }
.nested-heading h4,.nested-heading h5 { margin:0; font:600 17px Georgia,'Noto Serif SC',serif; }
.nested-heading strong { color:var(--nc-muted); font-size:11px; }
.stage-fields,.task-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; margin-top:12px; }
.stage-fields label:nth-child(n+2) { grid-column:span 2; }
.scene-task-list { display:grid; gap:10px; margin-top:14px; padding:12px; border-top:1px solid var(--nc-border); background:var(--nc-canvas); }
.scene-task { padding:12px; border:1px solid var(--nc-border); background:var(--nc-paper); }
.nested-actions,.block-actions { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
.danger { margin-left:auto; color:var(--nc-vermilion); }
.story-block-card>.nested-add { margin-top:14px; }
@media(max-width:700px){
  .editor-header,.undo-note,.block-heading{align-items:stretch;flex-direction:column}
  .block-fields,.stage-fields,.task-fields{grid-template-columns:1fr}
  .block-fields>label:nth-of-type(n+3),.plot-refs,.stage-fields label:nth-child(n+2){grid-column:auto}
  .danger{margin-left:0}
}
</style>
