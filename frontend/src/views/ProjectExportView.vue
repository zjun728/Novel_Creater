<script setup>
import { onBeforeMount } from 'vue'
import { NButton, NResult, NSkeleton } from 'naive-ui'

import NotFoundView from './NotFoundView.vue'
import NovelDownloadPanel from '../components/projects/NovelDownloadPanel.vue'
import ProjectBackupPanel from '../components/projects/ProjectBackupPanel.vue'
import ProjectPageHeader from '../components/projects/ProjectPageHeader.vue'
import { useRouteProject } from '../composables/useRouteProject.js'

const routeProject = useRouteProject()

onBeforeMount(() => {
  void routeProject.reload({ force: true })
})

async function flushCurrentDraft() {
  return true
}
</script>

<template>
  <section v-if="routeProject.state.value === 'loading'" class="project-export-page" aria-busy="true">
    <div class="project-export-sheet" aria-live="polite">
      <p>正在读取项目交付信息</p>
      <n-skeleton text :repeat="4" />
    </div>
  </section>

  <not-found-view
    v-else-if="routeProject.state.value === 'missing'"
    title="项目不存在或已被删除"
    description="请返回项目库确认项目状态。"
  />

  <section v-else-if="routeProject.state.value === 'error'" class="project-export-page">
    <n-result
      role="alert"
      status="error"
      title="导出与备份暂时无法打开"
      description="项目身份读取失败，请稍后重试。"
    >
      <template #footer>
        <n-button type="primary" @click="routeProject.reload({ force: true })">重试</n-button>
      </template>
    </n-result>
  </section>

  <section v-else class="project-export-page">
    <div class="project-export-sheet">
      <project-page-header
        kicker=""
        title="导出与备份"
        :description="`交付《${routeProject.project.value.title}》的已定稿正文，或留存完整项目备份。`"
        :archived="routeProject.state.value === 'archived'"
      />

      <div class="project-export-tools">
        <novel-download-panel
          :key="`download:${routeProject.project.value.id}`"
          :project-id="routeProject.project.value.id"
          :title="routeProject.project.value.title"
        />
        <project-backup-panel
          :key="`backup:${routeProject.project.value.id}`"
          :project-id="routeProject.project.value.id"
          :title="routeProject.project.value.title"
          :lifecycle-revision="routeProject.project.value.lifecycleRevision"
          :archived="routeProject.state.value === 'archived'"
          :flush-current-draft="flushCurrentDraft"
        />
      </div>
      <footer class="export-return"><span>正文导出只包含已定稿章节；完整备份不受正文范围限制。</span><router-link :to="`/projects/${routeProject.project.value.id}/overview`">返回作品</router-link></footer>
    </div>
  </section>
</template>

<style scoped>
.project-export-page {
  min-height: 100%;
  padding: clamp(22px, 4vw, 56px);
  color: var(--nc-ink);
  background: var(--nc-canvas);
}

.project-export-sheet {
  width: min(1080px, 100%);
  margin-inline: auto;
  padding: clamp(26px, 4vw, 48px);
  border: 1px solid var(--nc-border);
  border-radius: 10px;
  background: var(--nc-paper);
  box-shadow: 0 22px 58px rgba(58, 43, 27, .065);
}

.project-export-tools {
  margin-top: 24px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: start;
  gap: 24px;
}
.export-return{display:flex;justify-content:space-between;gap:20px;margin-top:28px;padding-top:20px;border-top:1px solid var(--nc-border);font-size:13px;color:var(--nc-muted)}.export-return a{color:var(--nc-vermilion)}.project-export-page{padding:24px 36px}.project-export-sheet{padding:28px}.project-export-sheet :deep(h1){font-size:30px}@media(max-width:900px){.project-export-tools{grid-template-columns:1fr}}
.project-export-tools :deep(.project-backup-panel){flex-direction:column;align-items:stretch;margin-top:0;min-height:220px;padding:20px;border:1px solid var(--nc-border);border-radius:6px;background:var(--nc-canvas)}.project-export-tools :deep(.novel-download-panel){margin-top:0;padding:20px;border:1px solid var(--nc-border);border-radius:6px;background:var(--nc-canvas)}
</style>
