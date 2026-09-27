<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'
import { api } from '../../api/db/client.js'
import { activeDesignNodes, bibleDesignSections, createFutureDesignController, PLOT_TYPES } from '../../application/continuity/futureDesign.js'
import { projectBiblePath, planningStoryBlocksPath, planningPlotsPath } from '../../router/projectRoutes.js'
import CharacterPlanDetails from './CharacterPlanDetails.vue'

const props = defineProps({ projectId: { type: String, required: true }, revision: { type: Number, default: null }, snapshot: { type: Object, default: null }, entityName: { type: String, default: '' }, entityId: { type: String, default: '' } })
const controller = createFutureDesignController({ api })
const state = controller.state
const sections = computed(() => bibleDesignSections(state.value.data?.bible?.content))
const plots = computed(() => props.entityId ? (state.value.data?.linkedPlots || []) : activeDesignNodes(state.value.data?.planning?.content?.plots))
const blocks = computed(() => activeDesignNodes(state.value.data?.planning?.content?.storyBlocks))
function load() { if (props.revision !== null) void controller.load(props.projectId, props.revision, props.entityId || null); else controller.clear() }
watch(() => [props.projectId, props.revision, props.snapshot, props.entityId], load, { immediate: true })
onBeforeUnmount(controller.dispose)
</script>

<template>
  <section class="future-panel" aria-label="已确认未来设计">
    <header><div><h2>未来设计</h2><p>以下是已确认的创作意图，尚不代表正文中已经发生。</p></div><span class="design-tag">全书设计</span></header>
    <p v-if="entityName" class="association-note">「{{ entityName }}」的关联计划与全书初始设定分别展示。</p>
    <p v-if="state.status === 'loading'" role="status">正在读取已确认设计…</p>
    <p v-else-if="state.status === 'error'" role="alert">{{ state.message }} <button @click="load">重试</button></p>
    <template v-else-if="state.status === 'ready'">
      <details v-if="sections.length" class="design-group"><summary>初始设定 <span>{{ sections.length }} 类 · 来自创作圣经</span></summary><section v-for="section in sections" :key="section.key"><h3>{{ section.title }}</h3><p v-for="(item, index) in section.items" :key="index">{{ item }}</p></section></details>
      <p v-else>{{ state.data.bible ? '当前圣经暂无可展示的设定条目。' : '暂无基于当前创作基础的已确认圣经。' }}</p>
      <p v-if="entityId && !plots.length">尚无与当前人物明确关联的已确认计划。</p>
      <details v-if="plots.length" class="design-group" :open="Boolean(entityId)"><summary>{{ entityId ? '与当前人物关联的计划' : '计划中的情节与人物发展' }} <span>{{ plots.length }} 条</span></summary><article v-for="plot in plots" :key="plot.id"><h3>{{ plot.title }} <small>{{ PLOT_TYPES[plot.plotType] || '情节线' }}</small></h3><dl><dt>故事问题</dt><dd>{{ plot.storyQuestion || '未填写' }}</dd><dt>未来方向</dt><dd>{{ plot.futureDirection || '未填写' }}</dd><dt>预期回收</dt><dd>{{ plot.expectedPayoff || '未填写' }}</dd></dl><CharacterPlanDetails v-if="plot.characterDesign" :design="plot.characterDesign" /></article></details>
      <details v-if="blocks.length" class="design-group"><summary>计划中的故事节点 <span>{{ blocks.length }} 个故事块</span></summary><article v-for="block in blocks" :key="block.id"><h3>{{ block.title }}</h3><dl><dt>目标</dt><dd>{{ block.blockGoal }}</dd><dt>预期变化</dt><dd>{{ block.expectedChange || '未填写' }}</dd></dl><details v-for="stage in activeDesignNodes(block.stages)" :key="stage.id" class="stage"><summary>{{ stage.title }}</summary><p>{{ stage.purpose }}</p><ol><li v-for="task in activeDesignNodes(stage.sceneTasks)" :key="task.id">{{ task.task }}<p class="task-evidence">计划完成依据：{{ task.completionEvidence }}</p></li></ol></details></article></details>
      <p v-if="!state.data.planning">暂无基于当前创作基础的已确认规划。</p>
    </template>
    <nav><router-link :to="projectBiblePath(projectId)">查看创作圣经</router-link><router-link :to="planningPlotsPath(projectId)">编辑人物与情节计划</router-link><router-link :to="planningStoryBlocksPath(projectId)">前往故事规划</router-link><button :disabled="revision === null || state.status === 'loading'" @click="load">刷新未来设计</button></nav>
  </section>
</template>

<style scoped>
.future-panel{padding-bottom:22px;border-bottom:1px solid var(--nc-border);font-size:13px}.future-panel header{display:flex;justify-content:space-between;align-items:start;gap:16px}.future-panel h2{font-size:17px;margin:0 0 8px}.future-panel p{line-height:1.8;white-space:pre-wrap;overflow-wrap:anywhere}.future-panel header p,.association-note,.task-evidence{color:var(--nc-muted)}.design-tag{white-space:nowrap;color:var(--nc-vermilion);border:1px solid var(--nc-border);padding:4px 8px}.design-group{margin:12px 0;border:1px solid var(--nc-border);padding:12px 16px}.design-group summary{cursor:pointer;line-height:1.8}.design-group summary span{color:var(--nc-muted);margin-left:12px}.design-group section,.design-group article{padding:10px 0;border-top:1px solid var(--nc-border);margin-top:12px}.design-group h3{font-size:14px}.design-group small{font-weight:400;color:var(--nc-muted);margin-left:10px}dl{display:grid;grid-template-columns:90px minmax(0,1fr);gap:8px;line-height:1.8}dt{color:var(--nc-muted)}dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere}.stage{margin:10px 0;padding:10px;background:var(--nc-canvas)}nav{display:flex;gap:20px;margin-top:16px}a{color:var(--nc-vermilion);text-underline-offset:4px}button{font:inherit;color:inherit;background:transparent;border:1px solid var(--nc-border);cursor:pointer}summary:focus-visible,a:focus-visible,button:focus-visible{outline:2px solid var(--nc-vermilion);outline-offset:3px}
</style>
