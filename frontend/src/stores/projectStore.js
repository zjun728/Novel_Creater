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
    const currentPreparation = ref(null)
    const preparationProjectId = ref('')
    const preparationStatus = ref('idle')
    const preparationError = ref(null)
    const currentOverview = ref(null)
    const overviewProjectId = ref('')
    const overviewStatus = ref('idle')
    const overviewError = ref(null)
    const projectGuard = createLatestRequestGuard()
    const preparationGuard = createLatestRequestGuard()
    const overviewGuard = createLatestRequestGuard()
    const activeListGuard = createLatestRequestGuard()
    const archivedListGuard = createLatestRequestGuard()
    const mutationTails = new Map()
    let routeProjectId = ''

    function enqueueProjectMutation(projectId, operation) {
      const key = String(projectId)
      const previous = mutationTails.get(key) ?? Promise.resolve()
      const result = previous.then(() => operation())
      const tail = result.then(
        () => undefined,
        () => undefined,
      )
      mutationTails.set(key, tail)
      void tail.then(() => {
        if (mutationTails.get(key) === tail) mutationTails.delete(key)
      })
      return result
    }

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
      const targetProjectId = String(projectId)
      if (routeProjectId !== targetProjectId) currentProject.value = null
      routeProjectId = targetProjectId
      const requestGeneration = projectGuard.begin()
      const project = await projectApi.get(projectId)
      if (projectGuard.isCurrent(requestGeneration)) currentProject.value = project
      return project
    }

    async function loadPreparation(projectId) {
      const targetProjectId = String(projectId)
      if (preparationProjectId.value !== targetProjectId) {
        currentPreparation.value = null
      }
      preparationProjectId.value = targetProjectId
      preparationStatus.value = 'loading'
      preparationError.value = null
      const generation = preparationGuard.begin()
      try {
        const preparation = await projectApi.preparation(projectId)
        if (preparationGuard.isCurrent(generation)) {
          currentPreparation.value = preparation
          preparationStatus.value = 'ready'
        }
        return preparation
      } catch (failure) {
        if (preparationGuard.isCurrent(generation)) {
          currentPreparation.value = null
          preparationStatus.value = 'error'
          preparationError.value = failure
        }
        throw failure
      }
    }

    function clearPreparation(projectId) {
      if (preparationProjectId.value !== String(projectId)) return
      preparationGuard.invalidate()
      currentPreparation.value = null
      preparationProjectId.value = ''
      preparationStatus.value = 'idle'
      preparationError.value = null
    }

    async function loadOverview(projectId) {
      const targetProjectId = String(projectId)
      if (overviewProjectId.value !== targetProjectId) currentOverview.value = null
      overviewProjectId.value = targetProjectId
      overviewStatus.value = 'loading'
      overviewError.value = null
      const generation = overviewGuard.begin()
      try {
        const overview = await projectApi.overview(projectId)
        if (overviewGuard.isCurrent(generation)) {
          currentOverview.value = overview
          overviewStatus.value = 'ready'
        }
        return overview
      } catch (failure) {
        if (overviewGuard.isCurrent(generation)) {
          currentOverview.value = null
          overviewStatus.value = 'error'
          overviewError.value = failure
        }
        throw failure
      }
    }

    function clearOverview(projectId) {
      if (overviewProjectId.value !== String(projectId)) return
      overviewGuard.invalidate()
      currentOverview.value = null
      overviewProjectId.value = ''
      overviewStatus.value = 'idle'
      overviewError.value = null
    }

    async function createProject(title) {
      const created = await projectApi.create({ title })
      activeListGuard.invalidate()
      activeProjects.value = upsertFirst(activeProjects.value, created)
      return created
    }

    function renameProject(projectId, title) {
      return enqueueProjectMutation(projectId, async () => {
        const renamed = await projectApi.rename(projectId, { title })
        activeListGuard.invalidate()
        archivedListGuard.invalidate()
        activeProjects.value = replaceExisting(activeProjects.value, renamed)
        archivedProjects.value = replaceExisting(archivedProjects.value, renamed)
        if (routeProjectId === String(renamed.id)) {
          projectGuard.invalidate()
          currentProject.value = renamed
        }
        return renamed
      })
    }

    function archiveProject(projectId, expectedLifecycleRevision) {
      return enqueueProjectMutation(projectId, async () => {
        const archived = await projectApi.archive(projectId, expectedLifecycleRevision)
        activeListGuard.invalidate()
        archivedListGuard.invalidate()
        activeProjects.value = activeProjects.value.filter(project => project.id !== projectId)
        archivedProjects.value = upsertFirst(archivedProjects.value, archived)
        if (routeProjectId === String(archived.id)) {
          projectGuard.invalidate()
          currentProject.value = archived
        }
        clearPreparation(projectId)
        clearOverview(projectId)
        return archived
      })
    }

    function restoreProject(projectId, expectedLifecycleRevision) {
      return enqueueProjectMutation(projectId, async () => {
        const restored = await projectApi.restore(projectId, expectedLifecycleRevision)
        activeListGuard.invalidate()
        archivedListGuard.invalidate()
        archivedProjects.value = archivedProjects.value.filter(project => project.id !== projectId)
        activeProjects.value = upsertFirst(activeProjects.value, restored)
        if (routeProjectId === String(restored.id)) {
          projectGuard.invalidate()
          currentProject.value = restored
        }
        clearPreparation(projectId)
        clearOverview(projectId)
        return restored
      })
    }

    function permanentlyDeleteProject(projectId, expectedLifecycleRevision) {
      return enqueueProjectMutation(projectId, async () => {
        await projectApi.permanentlyDelete(projectId, expectedLifecycleRevision)
        archivedListGuard.invalidate()
        archivedProjects.value = archivedProjects.value.filter(project => project.id !== projectId)
        if (routeProjectId === String(projectId)) {
          projectGuard.invalidate()
          currentProject.value = null
        }
        clearPreparation(projectId)
        clearOverview(projectId)
      })
    }

    return {
      activeProjects,
      archivedProjects,
      currentProject,
      currentPreparation,
      preparationProjectId,
      preparationStatus,
      preparationError,
      currentOverview,
      overviewProjectId,
      overviewStatus,
      overviewError,
      loadActiveProjects,
      loadArchivedProjects,
      loadProject,
      loadPreparation,
      loadOverview,
      clearOverview,
      createProject,
      renameProject,
      archiveProject,
      restoreProject,
      permanentlyDeleteProject,
    }
  })
}

export const useProjectStore = createProjectStore()
