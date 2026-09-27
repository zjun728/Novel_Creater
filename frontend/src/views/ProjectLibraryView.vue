<script>
import { computed, ref, defineComponent, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import ProjectCard from '../components/projects/ProjectCard.vue'
import ProjectEmptyState from '../components/projects/ProjectEmptyState.vue'
import ProjectImportPanel from '../components/projects/ProjectImportPanel.vue'
import ProjectCreateDialog from '../components/projects/ProjectCreateDialog.vue'
import ProjectNameDialog from '../components/projects/ProjectNameDialog.vue'
import { useAppMessage } from '../composables/useAppMessage.js'
import { createProjectLibraryController } from '../composables/projectLibraryControllers.js'
import { useProjectStore } from '../stores/projectStore.js'
import { topicCandidatesPath } from '../router/projectRoutes.js'

export { createProjectLibraryController }

export default defineComponent({
  name: 'ProjectLibraryView',
  components: {
    ProjectCard,
    ProjectCreateDialog,
    ProjectEmptyState,
    ProjectImportPanel,
    ProjectNameDialog,
  },
  setup() {
    const store = useProjectStore()
    const router = useRouter()
    const search = ref('')
    const filteredProjects = computed(() => store.activeProjects.filter(project => project.title.toLocaleLowerCase().includes(search.value.trim().toLocaleLowerCase())))
    const controller = createProjectLibraryController({
      store,
      router,
      message: useAppMessage(),
    })
    onMounted(controller.load)
    return { search, filteredProjects, projectStore: store, ...controller, startFromCandidate: () => router.push(topicCandidatesPath()) }
  },
})
</script>

<template>
  <section class="project-library-page">
    <header class="project-library-heading">
      <div>

        <h1>项目库</h1>
        <span>选择一部长篇继续创作，或从已保存的候选种子建立新项目。</span>
      </div>
      <div class="project-library-heading__actions">
        <ProjectImportPanel />
        <router-link class="library-link" to="/projects/archived">已归档</router-link>
        <button type="button" class="library-link" @click="beginCreate">空白项目</button>
        <button type="button" class="library-primary-button" @click="startFromCandidate">
          新建项目
        </button>
      </div>
    </header>

    <label class="project-search">搜索作品<input v-model="search" type="search" placeholder="搜索作品名称" /></label>
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
        @create="startFromCandidate"
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
        <p v-if="!filteredProjects.length">没有找到匹配的作品。</p>
        <div class="project-library-grid">
          <ProjectCard
            v-for="project in filteredProjects"
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

    <ProjectCreateDialog
      v-if="createDialogOpen"
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
  </section>
</template>

<style src="../components/projects/projectLibrary.css"></style>

<style scoped>
.project-library-page{padding:24px 36px}.project-library-heading h1{font-size:30px}.project-library-heading{align-items:center}.project-library-heading__actions{flex-wrap:wrap}.project-search{display:grid;gap:10px;max-width:1120px;margin:24px auto 0;color:var(--nc-muted);font-size:13px}.project-search input{padding:12px;border:1px solid var(--nc-border);border-radius:6px;background:var(--nc-paper);color:var(--nc-ink);font:inherit}.project-search input:focus-visible{outline:2px solid var(--nc-vermilion);outline-offset:2px}
</style>
