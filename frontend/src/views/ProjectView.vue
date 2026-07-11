<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { NAlert, NButton, NResult, NSkeleton, NTag } from 'naive-ui'
import { api } from '@/api/db/client'
import WriterCoreStateCard from '@/components/project/WriterCoreStateCard.vue'
import { useProjectStore } from '@/stores/projectStore'
import { useSeedStore } from '@/stores/seedStore'

const route = useRoute()
const projectStore = useProjectStore()
const seedStore = useSeedStore()
const writerCoreState = ref(null)
const loadedProject = ref(null)
const loading = ref(true)
const loadError = ref('')

const selectedSeedId = computed(() => seedStore.seeds.find(seed => seed.status === 'selected')?.id || '')

function seedPremise(seed) {
  return seed.premiseJSON && typeof seed.premiseJSON === 'object' ? seed.premiseJSON : {}
}

function seedSummary(seed) {
  const premise = seedPremise(seed)
  return premise.logline || premise.openingHook || '种子内容已保留，等待创作契约里程碑展开。'
}

async function loadFoundation() {
  const projectId = String(route.params.id || '')
  loading.value = true
  loadError.value = ''
  loadedProject.value = null
  writerCoreState.value = null
  try {
    const [project, , state] = await Promise.all([
      projectStore.openProject(projectId),
      seedStore.loadSeeds(projectId),
      api.writerCore.state(projectId),
    ])
    loadedProject.value = project
    writerCoreState.value = state
  } catch (error) {
    loadError.value = error.message || 'Writer Core 地基状态加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadFoundation)
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
      <template #footer><n-button type="primary" @click="loadFoundation">重试</n-button></template>
    </n-result>

    <template v-else-if="loadedProject && writerCoreState">
      <header class="project-hero">
        <div class="hero-copy">
          <p class="eyebrow">PRESERVED PROJECT / WRITER CORE V1</p>
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
        派生写作数据已按设计重置。项目基础信息、三个种子和 Provider 配置被保留；旧章节、临时草稿、设定、故事块与 QA 状态不会进入新内核。
      </n-alert>

      <section class="seed-section" aria-labelledby="seed-pool-heading">
        <div class="section-heading">
          <div>
            <p class="section-index">01 / 种子池</p>
            <h2 id="seed-pool-heading">保留的创作方向</h2>
          </div>
          <span>{{ seedStore.seeds.length }} 个种子 · 仅一个进入创作契约</span>
        </div>

        <div class="seed-grid">
          <article v-for="seed in seedStore.seeds" :key="seed.id" class="seed-card" :class="{ 'seed-card--selected': seed.id === selectedSeedId }">
            <div class="seed-card-top">
              <span class="seed-number">{{ String(seedStore.seeds.indexOf(seed) + 1).padStart(2, '0') }}</span>
              <n-tag v-if="seed.id === selectedSeedId" type="success" size="small" round>已选定</n-tag>
              <n-tag v-else size="small" :bordered="false">候选</n-tag>
            </div>
            <h3>{{ seed.title }}</h3>
            <p>{{ seedSummary(seed) }}</p>
            <div class="seed-meta">
              <span>{{ seedPremise(seed).genre || loadedProject.genre || '未分类' }}</span>
              <span>{{ seedPremise(seed).source === 'ai' ? 'AI 生成' : '作者种子' }}</span>
            </div>
          </article>
        </div>
      </section>

      <section class="foundation-section" aria-labelledby="foundation-heading">
        <div class="section-heading">
          <div>
            <p class="section-index">02 / 状态地基</p>
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
          <p>章节会话、WorkingDraft 与显式候选保存尚未进入本里程碑。</p>
        </div>
        <n-button type="primary" size="large" disabled>进入写作台</n-button>
      </footer>
    </template>
  </main>
</template>

<style scoped>
.project-shell { --paper: #f4efe4; --ink: #2e2923; --muted: #796f62; min-height: 100%; padding: clamp(22px, 4vw, 50px); color: var(--ink); background: var(--paper); }
.loading-sheet, .error-sheet, .project-hero, .seed-section, .foundation-section, .workspace-gate { width: min(1120px, 100%); margin-inline: auto; }
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
.seed-section, .foundation-section { margin-top: 42px; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.section-heading h2 { margin: 5px 0 0; font-size: 24px; font-weight: 650; }
.section-heading > span { color: #8a8072; font-size: 12px; }
.seed-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }
.seed-card { min-height: 190px; padding: 20px; border: 1px solid #dcd1bd; border-radius: 11px; background: rgba(255, 253, 248, .72); }
.seed-card--selected { border-color: #6f8c70; background: #fffdf8; box-shadow: inset 0 3px 0 #52745b, 0 10px 28px rgba(61, 72, 54, .07); }
.seed-card-top { display: flex; align-items: center; justify-content: space-between; }
.seed-number { color: #b09a78; font-family: Georgia, serif; font-size: 12px; }
.seed-card h3 { margin: 20px 0 9px; font-size: 20px; }
.seed-card p { min-height: 50px; margin: 0; color: #746a5d; font-size: 13px; line-height: 1.7; }
.seed-meta { display: flex; gap: 8px; margin-top: 18px; color: #958876; font-size: 11px; }
.seed-meta span + span::before { margin-right: 8px; content: '·'; }
.mismatch-alert { margin-top: 12px; }
.workspace-gate { display: flex; align-items: center; justify-content: space-between; gap: 24px; margin-top: 42px; padding: 24px 28px; border-top: 1px solid #d6cbb7; }
.workspace-gate strong { font-family: Georgia, 'Noto Serif SC', serif; font-size: 17px; }
.workspace-gate p { margin: 5px 0 0; color: #817668; font-size: 12px; }
@media (max-width: 820px) { .project-hero { align-items: flex-start; flex-direction: column; } .project-targets div { text-align: left; } .seed-grid { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .project-shell { padding: 20px 14px; } .section-heading, .workspace-gate { align-items: flex-start; flex-direction: column; } .loading-grid { grid-template-columns: 1fr; } }
</style>
