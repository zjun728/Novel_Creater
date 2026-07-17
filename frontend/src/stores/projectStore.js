import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

function replaceExisting(rows, replacement) {
  return rows.map(row => (row.id === replacement.id ? replacement : row))
}

function upsertFirst(rows, project) {
  return [project, ...rows.filter(row => row.id !== project.id)]
}

export function createProjectStore(projectApi = api.projects, storeId = 'project') {
  return defineStore(storeId, () => {
    const activeProjects = ref([])
    const archivedProjects = ref([])
    const currentProject = ref(null)
    const projectGuard = createLatestRequestGuard()
    const activeListGuard = createLatestRequestGuard()
    const archivedListGuard = createLatestRequestGuard()
    let routeProjectId = ''

    async function loadActiveProjects() {
      const generation = activeListGuard.begin()
      const projects = await projectApi.listActive()
      const rows = Array.isArray(projects) ? [...projects] : []
      if (activeListGuard.isCurrent(generation)) activeProjects.value = rows
      return rows
    }

    async function loadArchivedProjects() {
      const generation = archivedListGuard.begin()
      const projects = await projectApi.listArchived()
      const rows = Array.isArray(projects) ? [...projects] : []
      if (archivedListGuard.isCurrent(generation)) archivedProjects.value = rows
      return rows
    }

    async function loadProject(projectId) {
      routeProjectId = String(projectId)
      const requestGeneration = projectGuard.begin()
      const project = await projectApi.get(projectId)
      if (projectGuard.isCurrent(requestGeneration)) currentProject.value = project
      return project
    }

    async function createProject(title) {
      const created = await projectApi.create({ title })
      activeListGuard.invalidate()
      activeProjects.value = upsertFirst(activeProjects.value, created)
      return created
    }

    async function renameProject(projectId, title) {
      const renamed = await projectApi.rename(projectId, { title })
      activeListGuard.invalidate()
      archivedListGuard.invalidate()
      activeProjects.value = replaceExisting(activeProjects.value, renamed)
      archivedProjects.value = replaceExisting(archivedProjects.value, renamed)
      if (routeProjectId === renamed.id) {
        projectGuard.invalidate()
        currentProject.value = renamed
      } else if (currentProject.value?.id === renamed.id) {
        currentProject.value = renamed
      }
      return renamed
    }

    async function archiveProject(projectId, expectedLifecycleRevision) {
      const archived = await projectApi.archive(projectId, expectedLifecycleRevision)
      activeListGuard.invalidate()
      archivedListGuard.invalidate()
      activeProjects.value = activeProjects.value.filter(project => project.id !== projectId)
      archivedProjects.value = upsertFirst(archivedProjects.value, archived)
      if (routeProjectId === archived.id) {
        projectGuard.invalidate()
        currentProject.value = archived
      } else if (currentProject.value?.id === archived.id) {
        currentProject.value = archived
      }
      return archived
    }

    async function restoreProject(projectId, expectedLifecycleRevision) {
      const restored = await projectApi.restore(projectId, expectedLifecycleRevision)
      activeListGuard.invalidate()
      archivedListGuard.invalidate()
      archivedProjects.value = archivedProjects.value.filter(project => project.id !== projectId)
      activeProjects.value = upsertFirst(activeProjects.value, restored)
      if (routeProjectId === restored.id) {
        projectGuard.invalidate()
        currentProject.value = restored
      } else if (currentProject.value?.id === restored.id) {
        currentProject.value = restored
      }
      return restored
    }

    async function permanentlyDeleteProject(projectId, expectedLifecycleRevision) {
      await projectApi.permanentlyDelete(projectId, expectedLifecycleRevision)
      archivedListGuard.invalidate()
      archivedProjects.value = archivedProjects.value.filter(project => project.id !== projectId)
      if (routeProjectId === projectId) {
        projectGuard.invalidate()
        currentProject.value = null
      } else if (currentProject.value?.id === projectId) {
        currentProject.value = null
      }
    }

    return {
      activeProjects,
      archivedProjects,
      currentProject,
      loadActiveProjects,
      loadArchivedProjects,
      loadProject,
      createProject,
      renameProject,
      archiveProject,
      restoreProject,
      permanentlyDeleteProject,
    }
  })
}

export const useProjectStore = createProjectStore()
