<script setup>
import { NButton, NResult, NSkeleton, NTag } from 'naive-ui'

import CreationContractWizard from '@/components/project/CreationContractWizard.vue'
import { useRouteProject } from '@/composables/useRouteProject.js'
import NotFoundView from './NotFoundView.vue'

defineProps({ projectId: { type: String, required: true } })
const routeProject = useRouteProject()
</script>

<template>
  <main v-if="routeProject.state.value === 'loading'" class="contract-page" aria-busy="true">
    <section class="contract-page__loading">
      <n-skeleton text width="24%" />
      <n-skeleton text :repeat="4" />
      <n-skeleton height="320px" />
    </section>
  </main>

  <not-found-view
    v-else-if="routeProject.state.value === 'missing'"
    title="项目不存在或已被删除"
    description="请返回项目库确认项目状态。系统不会打开其他项目作为替代。"
  />

  <main v-else-if="routeProject.state.value === 'error'" class="contract-page">
    <n-result
      status="error"
      title="创作契约暂时无法加载"
      :description="routeProject.error.value?.message || '请稍后重试'"
    >
      <template #footer>
        <n-button type="primary" @click="routeProject.reload">重新加载</n-button>
      </template>
    </n-result>
  </main>

  <main
    v-else-if="routeProject.state.value === 'archived'"
    class="contract-page contract-page--archived"
  >
    <header class="archive-banner">
      <div>
        <p>ARCHIVED MANUSCRIPT</p>
        <h1>{{ routeProject.project.value.title }}</h1>
      </div>
      <n-tag type="warning" round>全页只读</n-tag>
    </header>
    <creation-contract-wizard
      :project-id="String(routeProject.project.value.id)"
      :project="routeProject.project.value"
      :read-only="true"
    />
  </main>

  <main v-else-if="routeProject.state.value === 'active'" class="contract-page">
    <creation-contract-wizard
      :project-id="String(routeProject.project.value.id)"
      :project="routeProject.project.value"
    />
  </main>
</template>

<style scoped>
.contract-page {
  min-height: 100%;
  padding: clamp(20px, 4vw, 54px);
  color: #302a23;
  background:
    linear-gradient(rgba(118, 95, 60, .035) 1px, transparent 1px) 0 0 / 100% 30px,
    #f4efe4;
}
.contract-page__loading {
  display: grid;
  width: min(1180px, 100%);
  gap: 18px;
  margin-inline: auto;
  padding: clamp(26px, 4vw, 48px);
  border: 1px solid #d8cbb7;
  border-radius: 14px;
  background: #fffdf8;
}
.archive-banner {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  width: min(1180px, 100%);
  gap: 20px;
  margin: 0 auto 18px;
  padding: 20px 24px;
  border: 1px solid #cfbea3;
  border-left: 5px solid #9c3d2f;
  background: rgba(255, 253, 248, .9);
}
.archive-banner p { margin: 0; color: #9c3d2f; font: 700 10px Georgia, serif; letter-spacing: .16em; }
.archive-banner h1 { margin: 5px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(24px, 4vw, 36px); }
@media (max-width: 620px) {
  .contract-page { padding: 14px; }
  .archive-banner { align-items: flex-start; flex-direction: column; }
}
</style>
