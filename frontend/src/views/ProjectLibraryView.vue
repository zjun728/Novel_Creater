<script>
import { defineComponent, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import ProjectCard from '../components/projects/ProjectCard.vue'
import ProjectEmptyState from '../components/projects/ProjectEmptyState.vue'
import ProjectNameDialog from '../components/projects/ProjectNameDialog.vue'
import { useAppMessage } from '../composables/useAppMessage.js'
import { createProjectLibraryController } from '../composables/projectLibraryControllers.js'
import { useProjectStore } from '../stores/projectStore.js'

export { createProjectLibraryController }

export default defineComponent({
  name: 'ProjectLibraryView',
  components: { ProjectCard, ProjectEmptyState, ProjectNameDialog },
  setup() {
    const store = useProjectStore()
    const controller = createProjectLibraryController({
      store,
      router: useRouter(),
      message: useAppMessage(),
    })
    onMounted(controller.load)
    return { projectStore: store, ...controller }
  },
})
</script>

<template>
  <main class="project-library-page">
    <header class="project-library-heading">
      <div>
        <p class="project-library-kicker">LONG-FORM FICTION DESK</p>
        <h1>项目库</h1>
        <span>选择一部长篇继续创作，或从一个名字建立新项目。</span>
      </div>
      <div class="project-library-heading__actions">
        <router-link class="library-link" to="/projects/archived">已归档</router-link>
        <button type="button" class="library-primary-button" @click="beginCreate">
          新建项目
        </button>
      </div>
    </header>

    <section
      class="project-library-sheet"
      :aria-busy="String(loading)"
      aria-live="polite"
    >
      <div v-if="loading" class="project-library-skeleton" aria-label="正在加载项目">
        <span v-for="index in 3" :key="index"></span>
      </div>

      <div v-else-if="loadError" class="project-library-error" role="alert">
        <div>
          <strong>暂时无法打开项目库</strong>
          <p>{{ loadError }}</p>
        </div>
        <button type="button" @click="load">重试</button>
      </div>

      <ProjectEmptyState
        v-else-if="!projectStore.activeProjects.length"
        @create="beginCreate"
      />

      <template v-else>
        <div class="project-library-summary">
          <p>活动项目</p>
          <span>{{ projectStore.activeProjects.length }} 部长篇</span>
        </div>
        <div v-if="actionError" class="project-library-inline-error" role="alert">
          <span>{{ actionError }}</span>
          <button type="button" @click="dismissActionError">关闭</button>
        </div>
        <div class="project-library-grid">
          <ProjectCard
            v-for="project in projectStore.activeProjects"
            :key="project.id"
            :project="project"
            :pending="isProjectPending(project.id)"
            :resumable-chapter-number="resumableChapterNumber(project)"
            @open="open"
            @resume="resume(project, resumableChapterNumber(project))"
            @rename="beginRename"
            @archive="archive"
          />
        </div>
      </template>
    </section>

    <ProjectNameDialog
      v-if="createDialogOpen"
      id="create-project"
      title="新建项目"
      submit-label="创建并打开"
      :pending="createPending"
      :server-error="createError"
      :on-cancel="closeCreate"
      @submit="create"
    />

    <ProjectNameDialog
      v-if="renameTarget"
      id="rename-project"
      title="编辑项目名称"
      submit-label="保存名称"
      :initial-title="renameTarget.title"
      :pending="renamePending"
      :server-error="renameError"
      :on-cancel="closeRename"
      @submit="rename"
    />
  </main>
</template>

<style src="../components/projects/projectLibrary.css"></style>
