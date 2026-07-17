<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NResult, NSkeleton, NTag } from 'naive-ui'
import { api } from '@/api/db/client'
import CreationContractWizard from '@/components/project/CreationContractWizard.vue'
import WriterCoreStateCard from '@/components/project/WriterCoreStateCard.vue'
import PlanningWorkspace from '@/components/planning/PlanningWorkspace.vue'
import { usePlanningStore } from '@/stores/planningStore'
import { useProjectStore } from '@/stores/projectStore'
import { createLatestRequestGuard } from '@/utils/latestRequest'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const planningStore = usePlanningStore()
const writerCoreState = ref(null)
const loadedProject = ref(null)
const loading = ref(true)
const loadError = ref('')
const foundationGuard = createLatestRequestGuard()

async function loadFoundation(projectId) {
  const requestGeneration = foundationGuard.begin()
  loading.value = true
  loadError.value = ''
  loadedProject.value = null
  writerCoreState.value = null
  try {
    const [project, state] = await Promise.all([
      projectStore.openProject(projectId),
      api.writerCore.state(projectId),
      planningStore.load(projectId),
    ])
    if (!foundationGuard.isCurrent(requestGeneration)) return
    loadedProject.value = project
    writerCoreState.value = state
  } catch (error) {
    if (!foundationGuard.isCurrent(requestGeneration)) return
    loadError.value = error.message || 'Writer Core 地基状态加载失败'
  } finally {
    if (foundationGuard.isCurrent(requestGeneration)) loading.value = false
  }
}

function retryFoundation() {
  return loadFoundation(String(route.params.id || ''))
}

function openWriterWorkspace() {
  if (!planningStore.planningReady) return
  router.push(`/writer/${encodeURIComponent(String(route.params.id || ''))}`)
}

watch(() => route.params.id, projectId => {
  loadFoundation(String(projectId || ''))
}, { immediate: true })

onBeforeUnmount(() => {
  foundationGuard.invalidate()
  projectStore.invalidateOpenProject()
  planningStore.invalidate()
})
</script>

<template>
  <main class="project-shell">
    <section v-if="loading" class="loading-sheet" aria-busy="true" aria-label="正在加载项目地基状态">
      <div class="loading-line"><n-skeleton text width="32%" /><n-skeleton text width="18%" /></div>
      <n-skeleton text :repeat="2" />
      <div class="loading-grid"><n-skeleton height="160px" /><n-skeleton height="160px" /><n-skeleton height="160px" /></div>
      <n-skeleton height="210px" />
    </section>

    <n-result v-else-if="loadError" status="error" title="项目地基未能加载" :description="loadError" class="error-sheet">
      <template #footer><n-button type="primary" @click="retryFoundation">重试</n-button></template>
    </n-result>

    <template v-else-if="loadedProject && writerCoreState">
      <header class="project-hero">
        <div class="hero-copy">
          <p class="eyebrow">CREATION CONTRACT / WRITER CORE V2</p>
          <div class="title-line">
            <h1>{{ loadedProject.title }}</h1>
            <n-tag round :bordered="false">{{ loadedProject.genre || '未分类' }}</n-tag>
          </div>
          <p class="description">{{ loadedProject.description || '暂无项目简介。' }}</p>
        </div>
        <div class="project-targets" aria-label="项目目标">
          <div><strong>{{ loadedProject.targetChapters }}</strong><span>目标章节</span></div>
          <div><strong>{{ Math.round((loadedProject.targetWords || 0) / 10000) }} 万</strong><span>目标字数</span></div>
        </div>
      </header>

      <n-alert type="info" :bordered="false" class="reset-note">
        派生写作数据已按设计重置。项目基础信息、种子池和 Provider 配置被保留；旧章节、临时草稿、设定、故事块与 QA 状态不会进入新内核。
      </n-alert>

      <creation-contract-wizard
        :project-id="String(route.params.id || '')"
        :project="loadedProject"
      />

      <planning-workspace :project-id="String(route.params.id || '')" />

      <section class="foundation-section" aria-labelledby="foundation-heading">
        <div class="section-heading">
          <div>
            <p class="section-index">03 / 状态地基</p>
            <h2 id="foundation-heading">唯一事实源与投影</h2>
          </div>
          <span>只读诊断，不产生正式状态</span>
        </div>
        <WriterCoreStateCard :state="writerCoreState" />
        <n-alert v-if="!writerCoreState.projectionInSync" type="error" class="mismatch-alert" title="Writer Core 状态不一致">
          写作入口保持关闭。请先从 Canon 重建投影，禁止继续生成或写入。
        </n-alert>
      </section>

      <footer class="workspace-gate">
        <div>
          <strong>下一站：ChapterSession</strong>
          <p v-if="planningStore.planningReady">滚动规划已就绪；下一里程碑将开放章节会话、WorkingDraft 与显式候选保存。</p>
          <p v-else>请先完成本书创作契约和首个滚动规划，再进入章节会话里程碑。</p>
        </div>
        <n-button
          type="primary"
          size="large"
          :disabled="!planningStore.planningReady"
          @click="openWriterWorkspace"
        >
          进入写作台
        </n-button>
      </footer>
    </template>
  </main>
</template>

<style scoped>
.project-shell { --paper: #f4efe4; --ink: #2e2923; --muted: #796f62; min-height: 100%; padding: clamp(22px, 4vw, 50px); color: var(--ink); background: var(--paper); }
.loading-sheet, .error-sheet, .project-hero, .foundation-section, .workspace-gate { width: min(1120px, 100%); margin-inline: auto; }
.loading-sheet { display: grid; gap: 22px; padding: 36px; border: 1px solid #ddd3c0; border-radius: 14px; background: #fffdf8; }
.loading-line { display: flex; justify-content: space-between; }
.loading-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.error-sheet { padding: 54px 20px; border: 1px solid #dfc9c3; border-radius: 14px; background: #fffaf7; }
.project-hero { display: flex; align-items: end; justify-content: space-between; gap: 36px; padding-bottom: 30px; border-bottom: 1px solid #d6cbb7; }
.hero-copy { max-width: 760px; }
.eyebrow, .section-index { margin: 0; color: #967548; font-size: 10px; font-weight: 800; letter-spacing: .18em; text-transform: uppercase; }
.title-line { display: flex; align-items: center; gap: 14px; margin-top: 9px; }
h1, h2, h3 { font-family: Georgia, 'Noto Serif SC', serif; }
h1 { margin: 0; font-size: clamp(34px, 6vw, 58px); font-weight: 600; letter-spacing: -.03em; }
.description { max-width: 66ch; margin: 14px 0 0; color: var(--muted); font-size: 15px; line-height: 1.85; }
.project-targets { display: flex; flex: 0 0 auto; gap: 28px; }
.project-targets div { display: grid; gap: 3px; text-align: right; }
.project-targets strong { font-family: Georgia, serif; font-size: 25px; font-weight: 600; }
.project-targets span { color: #8b8173; font-size: 11px; }
.reset-note { width: min(1120px, 100%); margin: 22px auto 0; background: rgba(255, 253, 248, .76); }
.foundation-section { margin-top: 42px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.section-heading h2 { margin: 5px 0 0; font-size: 24px; font-weight: 650; }
.section-heading > span { color: #8a8072; font-size: 12px; }
.mismatch-alert { margin-top: 12px; }
.workspace-gate { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-top: 42px; padding: 24px 28px; border-top: 1px solid #d6cbb7; }
.workspace-gate strong { font-family: Georgia, 'Noto Serif SC', serif; font-size: 17px; }
.workspace-gate p { margin: 5px 0 0; color: #817668; font-size: 12px; }
@media (max-width: 820px) { .project-hero { align-items: flex-start; flex-direction: column; } .project-targets div { text-align: left; } }
@media (max-width: 560px) { .project-shell { padding: 20px 14px; } .section-heading, .workspace-gate { align-items: flex-start; flex-direction: column; } .loading-grid { grid-template-columns: 1fr; } }
</style>
