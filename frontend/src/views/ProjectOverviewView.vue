<script setup>
import { NButton, NResult, NSkeleton } from 'naive-ui'

import ArchivedProjectStatusView from './ArchivedProjectStatusView.vue'
import NotFoundView from './NotFoundView.vue'
import { useRouteProject } from '../composables/useRouteProject.js'

const routeProject = useRouteProject()
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
        <n-button type="primary" @click="routeProject.reload">重试</n-button>
      </template>
    </n-result>
  </main>

  <main v-else-if="routeProject.state.value === 'active'" class="overview-page">
    <section class="overview-sheet" aria-labelledby="project-overview-title">
      <p class="eyebrow">PROJECT OVERVIEW</p>
      <h1 id="project-overview-title">{{ routeProject.project.value.title }}</h1>
      <p>项目上下文已从当前网址恢复。创作准备和写作模块将在后续纵向闭环中逐步接入。</p>
    </section>
  </main>
</template>

<style scoped>
.overview-page {
  min-height: 100%;
  padding: clamp(24px, 5vw, 64px);
  color: #302a23;
  background: #f4efe4;
}
.overview-sheet {
  width: min(980px, 100%);
  min-height: 260px;
  margin-inline: auto;
  padding: clamp(28px, 5vw, 54px);
  border: 1px solid #d8cbb7;
  border-radius: 14px;
  background: #fffdf8;
  box-shadow: 0 24px 64px rgba(58, 43, 27, .07);
}
.eyebrow {
  margin: 0 0 12px;
  color: #9a3f32;
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
  color: #766c60;
  line-height: 1.8;
}
</style>
