<script setup>
import { computed, watch } from 'vue'
import { NAlert, NButton, NCard, NEmpty, NSkeleton, NTag } from 'naive-ui'

import { usePlanningStore } from '@/stores/planningStore'

const props = defineProps({
  projectId: { type: String, required: true },
})

const planningStore = usePlanningStore()

const headRevision = computed(() => (
  planningStore.state
    ? Number(planningStore.state.head?.revision ?? 0)
    : null
))
const headRevisionLabel = computed(() => (
  planningStore.state ? `R${headRevision.value}` : '—'
))
const draftRevision = computed(() => (
  planningStore.state?.draft?.draftRevision ?? null
))
const futurePlan = computed(() => planningStore.state?.futurePlan || null)
const actualProgress = computed(() => (
  Array.isArray(planningStore.state?.actualProgress)
    ? planningStore.state.actualProgress
    : []
))
const capacityPolicy = computed(() => planningStore.state?.capacityPolicy || null)
const isReadOnly = computed(() => (
  planningStore.state?.capabilities?.edit === false
))
const planCounts = computed(() => ({
  volumes: futurePlan.value?.volumes?.length || 0,
  plots: futurePlan.value?.plots?.length || 0,
  blocks: futurePlan.value?.storyBlocks?.length || 0,
}))

watch(
  () => props.projectId,
  projectId => {
    if (projectId) void planningStore.load(projectId).catch(() => {})
  },
  { immediate: true },
)

function reloadPlanning() {
  void planningStore.load(props.projectId).catch(() => {})
}
</script>

<template>
  <section class="planning-workspace" aria-labelledby="planning-heading">
    <header class="workspace-header">
      <div>
        <p class="eyebrow">故事规划 · 单一事实链</p>
        <h2 id="planning-heading">滚动规划</h2>
        <p class="lede">
          未来安排与已经发生的正文事实分开呈现，定稿事实不会被规划静默改写。
        </p>
      </div>
      <div class="revision-strip" aria-label="规划版本">
        <div>
          <span>确认版本</span>
          <strong>{{ headRevisionLabel }}</strong>
        </div>
        <div>
          <span>工作草稿</span>
          <strong>{{ draftRevision === null ? '—' : `D${draftRevision}` }}</strong>
        </div>
      </div>
    </header>

    <n-alert
      v-if="planningStore.error"
      type="error"
      class="planning-alert"
      :show-icon="false"
    >
      {{ planningStore.error.message }}
    </n-alert>

    <n-alert
      v-else-if="isReadOnly"
      type="info"
      class="planning-alert"
      :show-icon="false"
    >
      当前规划为只读状态；请先完成项目准备条件，或恢复已归档项目。
    </n-alert>

    <div v-if="planningStore.loading && !planningStore.state" class="loading-grid">
      <n-card v-for="index in 2" :key="index" class="plan-card">
        <n-skeleton text :repeat="4" />
      </n-card>
    </div>

    <n-card
      v-else-if="!planningStore.state"
      class="plan-card planning-load-failure"
    >
      <n-empty description="规划数据加载失败，当前没有可展示的权威状态。">
        <template #extra>
          <n-button type="primary" ghost @click="reloadPlanning">
            重新加载
          </n-button>
        </template>
      </n-empty>
    </n-card>

    <div v-else class="planning-grid">
      <n-card class="plan-card future-card">
        <template #header>
          <div class="card-heading">
            <div>
              <p class="card-kicker">NEXT / 可调整</p>
              <h3>未来计划</h3>
            </div>
            <n-tag v-if="draftRevision !== null" round size="small" type="warning">
              草稿 D{{ draftRevision }}
            </n-tag>
            <n-tag v-else round size="small">暂无草稿</n-tag>
          </div>
        </template>

        <div v-if="headRevision === 0" class="head-zero">
          <span class="zero-mark">0</span>
          <div>
            <strong>尚无已确认规划</strong>
            <p>规划草稿确认后，首个不可变版本会从 R1 开始。</p>
          </div>
        </div>

        <div v-else-if="futurePlan" class="plan-summary">
          <div>
            <strong>{{ planCounts.volumes }}</strong>
            <span>分卷方向</span>
          </div>
          <div>
            <strong>{{ planCounts.plots }}</strong>
            <span>情节线</span>
          </div>
          <div>
            <strong>{{ planCounts.blocks }}</strong>
            <span>故事块</span>
          </div>
        </div>

        <n-empty
          v-else
          size="small"
          description="当前确认版本没有未来规划内容"
        />

        <div v-if="capacityPolicy" class="capacity-line">
          <span>章节容量参考</span>
          <strong>
            {{ capacityPolicy.targetMin }}–{{ capacityPolicy.targetMax }} 字
          </strong>
          <small>软上限 {{ capacityPolicy.softCeiling }} 字</small>
        </div>
      </n-card>

      <n-card class="plan-card progress-card">
        <template #header>
          <div class="card-heading">
            <div>
              <p class="card-kicker">CANON / 只读</p>
              <h3>已发生事实</h3>
            </div>
            <n-tag round size="small" type="success">
              {{ actualProgress.length }} 条
            </n-tag>
          </div>
        </template>

        <ol v-if="actualProgress.length" class="progress-list">
          <li
            v-for="(item, index) in actualProgress"
            :key="item.id || item.contentHash || index"
          >
            <span>{{ String(index + 1).padStart(2, '0') }}</span>
            <p>{{ item.summary || item.title || '已确认事实' }}</p>
          </li>
        </ol>
        <n-empty
          v-else
          size="small"
          description="尚无从定稿正文投影的已发生事实"
        />

        <p class="fact-note">
          此区域只读取 Canon 投影；规划不能反向覆盖已经确认的正文事实。
        </p>
      </n-card>
    </div>
  </section>
</template>

<style scoped>
.planning-workspace {
  --ink: #302b25;
  --muted: #807568;
  --paper: #fffdf8;
  --line: #ddd1bf;
  --accent: #9a6c32;
  width: min(1120px, 100%);
  margin: 42px auto 0;
  color: var(--ink);
}

.workspace-header {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 32px;
  margin-bottom: 18px;
}

.eyebrow,
.card-kicker {
  margin: 0;
  color: var(--accent);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .18em;
}

h2,
h3 {
  font-family: Georgia, 'Noto Serif SC', serif;
  font-weight: 650;
}

h2 {
  margin: 6px 0 0;
  font-size: 28px;
}

h3 {
  margin: 5px 0 0;
  font-size: 20px;
}

.lede {
  max-width: 630px;
  margin: 8px 0 0;
  color: var(--muted);
  line-height: 1.7;
}

.revision-strip {
  display: flex;
  flex: 0 0 auto;
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: rgba(255, 253, 248, .78);
}

.revision-strip > div {
  display: grid;
  min-width: 104px;
  padding: 10px 16px;
}

.revision-strip > div + div {
  border-left: 1px solid var(--line);
}

.revision-strip span {
  color: var(--muted);
  font-size: 10px;
}

.revision-strip strong {
  margin-top: 2px;
  font-family: Georgia, serif;
  font-size: 18px;
}

.planning-alert {
  margin-bottom: 14px;
}

.planning-grid,
.loading-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.18fr) minmax(300px, .82fr);
  gap: 16px;
}

.plan-card {
  min-height: 300px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: var(--paper);
}

.future-card {
  background:
    linear-gradient(145deg, rgba(154, 108, 50, .055), transparent 44%),
    var(--paper);
}

.progress-card {
  background:
    linear-gradient(160deg, rgba(65, 105, 90, .055), transparent 48%),
    var(--paper);
}

.card-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.head-zero {
  display: flex;
  align-items: center;
  gap: 18px;
  min-height: 118px;
  padding: 14px 0 20px;
}

.zero-mark {
  color: rgba(154, 108, 50, .18);
  font-family: Georgia, serif;
  font-size: 82px;
  line-height: .9;
}

.head-zero strong {
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: 18px;
}

.head-zero p,
.fact-note {
  margin: 6px 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.7;
}

.plan-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  overflow: hidden;
  margin: 8px 0 24px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background: var(--line);
}

.plan-summary div {
  display: grid;
  gap: 3px;
  padding: 18px;
  background: rgba(255, 253, 248, .94);
}

.plan-summary strong {
  font-family: Georgia, serif;
  font-size: 26px;
}

.plan-summary span,
.capacity-line span,
.capacity-line small {
  color: var(--muted);
  font-size: 11px;
}

.capacity-line {
  display: grid;
  grid-template-columns: 1fr auto;
  align-items: baseline;
  gap: 4px 16px;
  margin-top: 22px;
  padding-top: 15px;
  border-top: 1px dashed var(--line);
}

.capacity-line small {
  grid-column: 1 / -1;
}

.progress-list {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.progress-list li {
  display: grid;
  grid-template-columns: 30px 1fr;
  gap: 10px;
  padding: 12px 0;
  border-bottom: 1px solid rgba(221, 209, 191, .68);
}

.progress-list span {
  color: var(--accent);
  font-family: Georgia, serif;
  font-size: 11px;
}

.progress-list p {
  margin: 0;
  line-height: 1.65;
}

.fact-note {
  margin-top: 20px;
  padding: 12px 14px;
  border-left: 2px solid rgba(65, 105, 90, .5);
  background: rgba(65, 105, 90, .045);
}

@media (max-width: 760px) {
  .workspace-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .planning-grid,
  .loading-grid {
    grid-template-columns: 1fr;
  }

  .revision-strip {
    width: 100%;
  }

  .revision-strip > div {
    flex: 1;
  }

  .plan-summary {
    grid-template-columns: 1fr;
  }
}
</style>
