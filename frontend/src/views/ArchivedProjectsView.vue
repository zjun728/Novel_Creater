<script>
import { defineComponent, onMounted } from 'vue'

import ProjectCard from '../components/projects/ProjectCard.vue'
import ProjectEmptyState from '../components/projects/ProjectEmptyState.vue'
import { useAppMessage } from '../composables/useAppMessage.js'
import { useDangerousConfirmation } from '../composables/useDangerousConfirmation.js'
import { createArchivedProjectsController } from '../composables/projectLibraryControllers.js'
import { useProjectStore } from '../stores/projectStore.js'

export { createArchivedProjectsController }

export default defineComponent({
  name: 'ArchivedProjectsView',
  components: { ProjectCard, ProjectEmptyState },
  setup() {
    const store = useProjectStore()
    const controller = createArchivedProjectsController({
      store,
      message: useAppMessage(),
      confirmation: useDangerousConfirmation(),
    })
    onMounted(controller.load)
    return { projectStore: store, ...controller }
  },
})
</script>

<template>
  <main class="archived-projects-page">
    <header class="archived-projects-heading">
      <div>
        <p>ARCHIVED WORKS</p>
        <h1>已归档项目</h1>
        <span>归档只隐藏项目；恢复后可继续原来的工作稿。</span>
      </div>
      <router-link to="/projects">返回项目库</router-link>
    </header>

    <section
      class="archived-projects-sheet"
      :aria-busy="String(loading)"
      aria-live="polite"
    >
      <div v-if="loading" class="archived-projects-skeleton" aria-label="正在加载已归档项目">
        <span v-for="index in 2" :key="index"></span>
      </div>

      <div v-else-if="loadError" class="archived-projects-error" role="alert">
        <div>
          <strong>暂时无法读取归档</strong>
          <p>{{ loadError }}</p>
        </div>
        <button type="button" @click="load">重试</button>
      </div>

      <ProjectEmptyState
        v-else-if="!projectStore.archivedProjects.length"
        archived
      />

      <template v-else>
        <div class="archived-projects-summary">
          <p>归档项目</p>
          <span>{{ projectStore.archivedProjects.length }} 部</span>
        </div>
        <div v-if="actionError" class="archived-projects-inline-error" role="alert">
          <span>{{ actionError }}</span>
          <button type="button" @click="dismissActionError">关闭</button>
        </div>
        <div class="archived-projects-grid">
          <ProjectCard
            v-for="project in projectStore.archivedProjects"
            :key="project.id"
            :project="project"
            :pending="isProjectPending(project.id)"
            archived
            @restore="restore"
            @delete="permanentlyDelete"
          />
        </div>
      </template>
    </section>
  </main>
</template>

<style src="../components/projects/projectLibrary.css"></style>
