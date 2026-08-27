<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton } from 'naive-ui'

import ProjectBackupPanel from '../components/projects/ProjectBackupPanel.vue'
import ManuscriptSummaryLink from '../components/manuscript/ManuscriptSummaryLink.vue'
import { useProjectStore } from '../stores/projectStore.js'
import { projectBiblePath, projectContractPath } from '../router/projectRoutes.js'

const props = defineProps({
  project: {
    type: Object,
    required: true,
  },
})
const emit = defineEmits(['restored'])
const router = useRouter()
const projectStore = useProjectStore()
const restoring = ref(false)
const restoreError = ref('')

async function restoreProject() {
  if (restoring.value) return
  restoring.value = true
  restoreError.value = ''
  try {
    const restored = await projectStore.restoreProject(
      props.project.id,
      props.project.lifecycleRevision,
    )
    emit('restored', restored)
  } catch (error) {
    restoreError.value = error.message || '项目恢复失败'
  } finally {
    restoring.value = false
  }
}

function returnToLibrary() {
  router.push('/projects')
}
</script>

<template>
  <section class="archived-page" aria-labelledby="archived-title">
    <section class="archived-sheet" aria-labelledby="archived-title">
      <p class="eyebrow">ARCHIVED PROJECT</p>
      <span class="status-mark">已归档</span>
      <h1 id="archived-title">{{ project.title }}</h1>
      <p>项目内容仍完整保留，但当前为只读状态。恢复后可继续原来的工作稿。</p>
      <n-alert v-if="restoreError" type="error" :bordered="false">{{ restoreError }}</n-alert>
      <div class="actions">
        <router-link class="readonly-contract-link" :to="projectContractPath(project.id)">
          查看只读创作契约
        </router-link>
        <router-link class="readonly-contract-link" :to="projectBiblePath(project.id)">
          查看只读创作圣经
        </router-link>
        <n-button :loading="restoring" type="primary" @click="restoreProject">恢复项目</n-button>
        <n-button quaternary @click="returnToLibrary">返回项目库</n-button>
      </div>
      <manuscript-summary-link :project-id="project.id" />
      <project-backup-panel
        :key="`backup:${project.id}`"
        :project-id="project.id"
        :title="project.title"
        :lifecycle-revision="project.lifecycleRevision"
        :archived="true"
      />
    </section>
  </section>
</template>

<style scoped>
.archived-page {
  display: grid;
  min-height: 100%;
  padding: clamp(24px, 6vw, 72px);
  place-items: center;
  color: #302a23;
  background: #f4efe4;
}
.archived-sheet {
  width: min(760px, 100%);
  padding: clamp(28px, 6vw, 60px);
  border: 1px solid #d8cbb7;
  border-radius: 14px;
  background: #fffdf8;
  box-shadow: 0 24px 64px rgba(58, 43, 27, .08);
}
.eyebrow {
  margin: 0 0 10px;
  color: #9a3f32;
  font: 700 11px Georgia, serif;
  letter-spacing: .16em;
}
.status-mark {
  display: inline-flex;
  padding: 4px 10px;
  border: 1px solid #c9b9a2;
  border-radius: 999px;
  color: #6f6253;
  font-size: 12px;
}
h1 {
  margin: 18px 0 0;
  font-family: Georgia, 'Noto Serif SC', serif;
  font-size: clamp(32px, 5vw, 50px);
  font-weight: 600;
}
.archived-sheet > p:not(.eyebrow) {
  margin: 18px 0 24px;
  color: #766c60;
  line-height: 1.8;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 24px;
}
.readonly-contract-link {
  display: inline-flex;
  align-items: center;
  padding: 0 14px;
  border: 1px solid #9a3f32;
  border-radius: 4px;
  color: #8f382c;
  font-weight: 650;
  text-decoration: none;
}
</style>
