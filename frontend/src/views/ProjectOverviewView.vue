<script setup>
import { computed, onMounted, watch } from 'vue'
import { NButton, NResult, NSkeleton } from 'naive-ui'

import ArchivedProjectStatusView from './ArchivedProjectStatusView.vue'
import NotFoundView from './NotFoundView.vue'
import { useRouteProject } from '../composables/useRouteProject.js'
import { useProjectStore } from '../stores/projectStore.js'

const routeProject = useRouteProject()
const projectStore = useProjectStore()
let mounted = false
let reconciledArchivedProjectId = ''

const preparation = computed(() => (
  projectStore.preparationProjectId
    === String(routeProject.project.value?.id || '')
    ? projectStore.currentPreparation
    : null
))

const actionCopy = computed(() => ({
  select_seed: {
    eyebrow: 'CREATIVE SEED',
    title: '选择创作种子',
    description: '从候选种子中明确本项目唯一的当前创作方向。',
  },
  continue_contract: {
    eyebrow: 'CREATION CONTRACT',
    title: '继续创作契约',
    description: '完成故事发动机、风格、经验与篇幅边界，并由作者确认。',
  },
  continue_bible: {
    eyebrow: 'CREATION BIBLE',
    title: '继续创作圣经',
    description: '补全未来设计；手工建立与确认不依赖可用模型。',
  },
  continue_planning: {
    eyebrow: 'STORY PLANNING',
    title: '继续故事规划',
    description: '建立分卷、情节线与滚动故事块，让后续章节有方向也有调整余地。',
  },
  establish_planning: {
    eyebrow: 'STORY PLANNING',
    title: '开始故事规划',
    description: '从空白工作稿建立分卷与情节线，再逐步形成可执行的完整规划。',
  },
  recover_planning_operation: {
    eyebrow: 'STORY PLANNING',
    title: '核对规划生成结果',
    description: '沿用原操作标识读取权威结果，不会重复发起一次 AI 生成。',
  },
}[preparation.value?.nextAction] || null))

const statusItems = computed(() => {
  const value = preparation.value
  if (!value) return []
  const labels = {
    activeSelection: { missing: '未选择', current: '已选择' },
    contract: {
      missing: '未建立',
      draft: '草稿',
      current: '已确认',
      superseded: '需重新确认',
    },
    bible: {
      missing: '未建立',
      draft: '草稿',
      current: '已确认',
      superseded: '需重新确认',
    },
  }
  const planning = value.modelTasks?.find(item => item.taskKey === 'planning')
  return [
    ['种子', labels.activeSelection[value.activeSelection] || '未知'],
    ['创作契约', labels.contract[value.contract] || '未知'],
    ['创作圣经', labels.bible[value.bible] || '未知'],
    ['规划模型', planning?.readiness === 'ready' ? '可用' : '不可用'],
  ]
})

async function refreshPreparation() {
  const projectId = routeProject.project.value?.id
  if (routeProject.state.value !== 'active' || !projectId) return
  try {
    const authority = await projectStore.loadPreparation(projectId)
    if (
      routeProject.state.value !== 'active'
      || String(routeProject.project.value?.id || '') !== String(projectId)
    ) {
      return
    }
    if (authority.lifecycle === 'archived') {
      if (reconciledArchivedProjectId !== String(projectId)) {
        reconciledArchivedProjectId = String(projectId)
        await routeProject.reload({ force: true })
      }
    } else if (authority.lifecycle === 'active') {
      reconciledArchivedProjectId = ''
    }
  } catch {
    // The Store retains a safe retryable state; raw transport details are not rendered.
  }
}

async function retryRouteProject() {
  const projectId = String(
    projectStore.preparationProjectId
    || routeProject.project.value?.id
    || '',
  )
  reconciledArchivedProjectId = projectId
  await routeProject.reload({ force: true })
}

onMounted(() => {
  mounted = true
  void refreshPreparation()
})

watch(
  () => [routeProject.state.value, routeProject.project.value?.id],
  () => {
    if (mounted) void refreshPreparation()
  },
)
</script>

<template>
  <main v-if="routeProject.state.value === 'loading'" class="overview-page" aria-busy="true">
    <section class="overview-sheet">
      <n-skeleton text width="28%" />
      <n-skeleton text :repeat="3" />
    </section>
  </main>

  <archived-project-status-view
    v-else-if="routeProject.state.value === 'archived'"
    :project="routeProject.project.value"
    @restored="routeProject.reload"
  />

  <not-found-view
    v-else-if="routeProject.state.value === 'missing'"
    title="项目不存在或已被删除"
    description="请返回项目库确认项目状态。系统不会打开其他项目作为替代。"
  />

  <main v-else-if="routeProject.state.value === 'error'" class="overview-page">
    <n-result
      status="error"
      title="项目暂时无法加载"
      :description="routeProject.error.value?.message || '请稍后重试'"
    >
      <template #footer>
        <n-button type="primary" @click="retryRouteProject">重试</n-button>
      </template>
    </n-result>
  </main>

  <main
    v-else-if="preparation?.lifecycle === 'archived'"
    class="overview-page"
    aria-live="polite"
  >
    <n-result
      status="info"
      title="项目已归档"
      description="正在同步项目权威状态，完成后可查看只读内容或恢复项目。"
    >
      <template #footer>
        <n-button type="primary" @click="retryRouteProject">重新同步</n-button>
      </template>
    </n-result>
  </main>

  <main v-else-if="routeProject.state.value === 'active'" class="overview-page">
    <section class="overview-sheet" aria-labelledby="project-overview-title">
      <p class="eyebrow">PROJECT OVERVIEW</p>
      <h1 id="project-overview-title">{{ routeProject.project.value.title }}</h1>
      <p>这里汇总服务端已经持久化的创作准备事实，并只给出一个当前下一步。</p>

      <n-result
        v-if="projectStore.preparationStatus === 'error'"
        status="error"
        title="创作准备状态暂时无法加载"
        description="已保留当前项目，请重新读取服务端状态。"
      >
        <template #footer>
          <n-button type="primary" @click="refreshPreparation">重新读取</n-button>
        </template>
      </n-result>

      <div
        v-else-if="projectStore.preparationStatus === 'loading' || !preparation"
        class="preparation-loading"
        aria-live="polite"
      >
        <n-skeleton text :repeat="3" />
      </div>

      <template v-else>
        <dl class="preparation-summary" aria-label="创作准备状态">
          <div v-for="[label, value] in statusItems" :key="label">
            <dt>{{ label }}</dt>
            <dd>{{ value }}</dd>
          </div>
        </dl>

        <router-link
          v-if="preparation.targetPath && actionCopy"
          class="overview-next-action"
          :to="preparation.targetPath"
        >
          <span>{{ actionCopy.eyebrow }}</span>
          <strong>{{ actionCopy.title }}</strong>
          <small>{{ actionCopy.description }}</small>
        </router-link>

        <n-result
          v-else
          status="warning"
          title="创作准备状态需要重新读取"
          description="当前下一步不完整，系统不会推断或跳转到其他模块。"
        >
          <template #footer>
            <n-button type="primary" @click="refreshPreparation">重新读取</n-button>
          </template>
        </n-result>

        <p
          v-if="preparation.reasons.includes('planning_model_not_ready')"
          class="model-note"
        >
          规划模型不可用；手工契约与圣经仍可继续，只有 AI 生成被停用。
        </p>
      </template>
    </section>
  </main>
</template>

<style scoped>
.overview-page {
  min-height: 100%;
  padding: clamp(24px, 5vw, 64px);
  color: var(--nc-ink);
  background: var(--nc-canvas);
}
.overview-sheet {
  width: min(980px, 100%);
  min-height: 260px;
  margin-inline: auto;
  padding: clamp(28px, 5vw, 54px);
  border: 1px solid var(--nc-border);
  border-radius: 14px;
  background: var(--nc-paper);
  box-shadow: 0 24px 64px rgba(58, 43, 27, .07);
}
.eyebrow {
  margin: 0 0 12px;
  color: var(--nc-vermilion);
  font: 700 11px Georgia, serif;
  letter-spacing: .16em;
}
h1 {
  margin: 0;
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: clamp(34px, 6vw, 58px);
  font-weight: 600;
}
.overview-sheet > p:not(.eyebrow) {
  max-width: 60ch;
  margin: 18px 0 0;
  color: var(--nc-muted);
  line-height: 1.8;
}
.preparation-loading {
  margin-top: 28px;
}
.preparation-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 28px 0 0;
}
.preparation-summary div {
  padding: 14px 16px;
  border: 1px solid var(--nc-border);
  border-radius: 8px;
}
.preparation-summary dt {
  color: var(--nc-muted);
  font-size: 12px;
}
.preparation-summary dd {
  margin: 6px 0 0;
  font-weight: 700;
}
.overview-next-action {
  display: grid;
  width: min(560px, 100%);
  gap: 6px;
  margin-top: 30px;
  padding: 20px 22px;
  border: 1px solid var(--nc-border);
  border-radius: 9px;
  color: var(--nc-ink);
  background: var(--nc-paper);
  text-decoration: none;
  transition: border-color .15s ease, transform .15s ease;
}
.overview-next-action:hover {
  border-color: var(--nc-vermilion);
  transform: translateY(-2px);
}
.overview-next-action span {
  color: var(--nc-vermilion);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .15em;
}
.overview-next-action strong {
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: 20px;
}
.overview-next-action small {
  color: var(--nc-muted);
  line-height: 1.7;
}
.model-note {
  color: var(--nc-muted);
  line-height: 1.7;
}
.model-note {
  margin-top: 14px;
}
@media (max-width: 760px) {
  .preparation-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (prefers-reduced-motion: reduce) {
  .overview-next-action { transition: none; }
}
</style>
