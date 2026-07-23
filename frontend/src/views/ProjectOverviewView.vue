<script setup>
import { NButton, NResult, NSkeleton } from 'naive-ui'

import ArchivedProjectStatusView from './ArchivedProjectStatusView.vue'
import NotFoundView from './NotFoundView.vue'
import { useRouteProject } from '../composables/useRouteProject.js'
import { projectBiblePath, projectContractPath } from '../router/projectRoutes.js'

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
      <p>创作契约把已选种子、故事发动机、风格、参考范围与篇幅容量收拢为一份可追溯的正式设计。</p>
      <router-link
        class="overview-next-action"
        :to="projectContractPath(routeProject.project.value.id)"
      >
        <span>FORMAL CREATION CONTRACT</span>
        <strong>进入创作契约工作区</strong>
        <small>核对唯一种子，完成五步设计，预览全部变化后一次签印。</small>
      </router-link>
      <router-link class="overview-next-action" :to="projectBiblePath(routeProject.project.value.id)">
        <span>CREATION BIBLE</span>
        <strong>进入创作圣经工作区</strong>
        <small>维护未来设计，并只在确认后写入新的不可变修订。</small>
      </router-link>
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
.overview-next-action {
  display: grid;
  width: min(560px, 100%);
  gap: 6px;
  margin-top: 30px;
  padding: 20px 22px;
  border: 1px solid #cdbda5;
  border-radius: 9px;
  color: #302a23;
  background: linear-gradient(110deg, #fffaf0, #f4ead9);
  text-decoration: none;
  transition: border-color .15s ease, transform .15s ease;
}
.overview-next-action:hover {
  border-color: #9a3f32;
  transform: translateY(-2px);
}
.overview-next-action span {
  color: #9a3f32;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .15em;
}
.overview-next-action strong {
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: 20px;
}
.overview-next-action small {
  color: #766c60;
  line-height: 1.7;
}
@media (prefers-reduced-motion: reduce) {
  .overview-next-action { transition: none; }
}
</style>
