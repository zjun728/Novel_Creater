<script setup>
import { computed } from 'vue'
import { NAlert, NButton, NCard, NEmpty, NList, NListItem, NSpace, NTag } from 'naive-ui'

import { useCreationContractStore } from '@/stores/creationContractStore'
import { usePlanningStore } from '@/stores/planningStore'

const props = defineProps({
  projectId: { type: String, required: true },
})

const planningStore = usePlanningStore()
const contractStore = useCreationContractStore()

const contractRevision = computed(() => Number(contractStore.head?.revision || 0))
const canCreate = computed(() => (
  contractStore.head?.hasContract === true
  && contractStore.head?.contractReady === true
  && contractRevision.value > 0
  && !planningStore.hasPlanning
  && !planningStore.creating
))
const activeBlock = computed(() => planningStore.activeBlock)
const activeVolume = computed(() => planningStore.activeVolume)
const stages = computed(() => planningStore.stages)
const tasks = computed(() => planningStore.sceneTasks)

function taskCount(stageId) {
  return tasks.value.filter(task => task.storyStageId === stageId).length
}

async function createInitialPlanning() {
  if (!canCreate.value) return
  await planningStore.createInitial(props.projectId, {
    expectedContractRevision: contractRevision.value,
    idempotencyKey: `planning-initial-${contractRevision.value}`,
  })
}
</script>

<template>
  <section class="planning-panel" aria-labelledby="planning-heading">
    <div class="section-heading">
      <div>
        <p class="section-index">02 / 滚动规划</p>
        <h2 id="planning-heading">StoryBlock / Stage / SceneTask</h2>
      </div>
      <n-tag v-if="planningStore.planningReady" type="success" round>规划已就绪</n-tag>
      <n-tag v-else round>等待滚动规划</n-tag>
    </div>

    <n-alert v-if="planningStore.error" type="error" class="planning-alert">
      {{ planningStore.error.message }}
    </n-alert>

    <n-card v-if="planningStore.hasPlanning && activeBlock" class="planning-card">
      <template #header>
        <div class="card-title">
          <span>当前故事块</span>
          <strong>{{ activeBlock.title }}</strong>
        </div>
      </template>
      <div class="planning-grid">
        <div>
          <p class="label">当前卷</p>
          <p>{{ activeVolume?.title || '未命名分卷' }}</p>
        </div>
        <div>
          <p class="label">章节容量</p>
          <p>
            {{ activeBlock.goal?.chapterCapacity?.targetMin || 3500 }}
            —
            {{ activeBlock.goal?.chapterCapacity?.targetMax || 4500 }}
            字，安全上限约
            {{ activeBlock.goal?.chapterCapacity?.softCeiling || 5200 }}
          </p>
        </div>
      </div>
      <p class="block-goal">{{ activeBlock.goal?.goal }}</p>
      <n-list bordered>
        <n-list-item v-for="stage in stages" :key="stage.id">
          <n-space justify="space-between" align="center">
            <div>
              <strong>{{ stage.stageOrder }}. {{ stage.title }}</strong>
              <p class="stage-line">{{ stage.plan?.dramaticQuestion || stage.plan?.purpose }}</p>
            </div>
            <n-tag :type="stage.status === 'in_progress' ? 'warning' : 'default'">
              {{ stage.status }} · SceneTask {{ taskCount(stage.id) }}
            </n-tag>
          </n-space>
        </n-list-item>
      </n-list>
    </n-card>

    <n-card v-else class="planning-card empty-card">
      <n-empty description="创作契约签印后，可以建立首个滚动规划。">
        <template #extra>
          <n-button
            type="primary"
            :loading="planningStore.creating"
            :disabled="!canCreate"
            @click="createInitialPlanning"
          >
            创建滚动规划
          </n-button>
        </template>
      </n-empty>
      <p class="hint">
        滚动规划只建立分卷方向、当前 StoryBlock、StoryStage 和 SceneTask；
        不设置目标章节数，不调用模型，也不生成正文。
      </p>
    </n-card>
  </section>
</template>

<style scoped>
.planning-panel { width: min(1120px, 100%); margin: 42px auto 0; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.section-index { margin: 0; color: #967548; font-size: 10px; font-weight: 800; letter-spacing: .18em; text-transform: uppercase; }
h2 { margin: 5px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 24px; font-weight: 650; }
.planning-alert { margin-bottom: 12px; }
.planning-card { background: #fffdf8; border: 1px solid #ded2bf; border-radius: 14px; }
.card-title { display: grid; gap: 4px; }
.card-title span, .label, .hint, .stage-line { color: #82766a; font-size: 12px; }
.card-title strong { font-family: Georgia, 'Noto Serif SC', serif; font-size: 21px; }
.planning-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-bottom: 14px; }
.planning-grid p { margin: 0; }
.block-goal { color: #3d362f; line-height: 1.8; }
.stage-line { margin: 5px 0 0; }
.empty-card { text-align: center; }
.hint { max-width: 620px; margin: 14px auto 0; line-height: 1.8; }
@media (max-width: 720px) {
  .section-heading, .planning-grid { grid-template-columns: 1fr; align-items: flex-start; }
  .section-heading { flex-direction: column; }
}
</style>
