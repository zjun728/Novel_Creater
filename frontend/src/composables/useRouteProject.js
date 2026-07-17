import { ref, shallowRef, watch } from 'vue'
import { useRoute } from 'vue-router'

import { useProjectStore } from '../stores/projectStore.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

function isMissingProject(error) {
  return Number(error?.status) === 404
    || error?.code === 'project_not_found'
    || error?.code === 'not_found'
}

export function useRouteProject({
  route = useRoute(),
  store = useProjectStore(),
} = {}) {
  const state = ref('loading')
  const project = shallowRef(null)
  const error = shallowRef(null)
  const loadGuard = createLatestRequestGuard()

  async function reload() {
    const projectId = String(route.params.projectId || '')
    const generation = loadGuard.begin()
    state.value = 'loading'
    project.value = null
    error.value = null

    if (!projectId) {
      state.value = 'missing'
      return null
    }

    try {
      const loaded = await store.loadProject(projectId)
      if (!loadGuard.isCurrent(generation)) return loaded
      project.value = loaded
      state.value = loaded?.archivedAt == null ? 'active' : 'archived'
      return loaded
    } catch (failure) {
      if (!loadGuard.isCurrent(generation)) return null
      if (isMissingProject(failure)) {
        state.value = 'missing'
      } else {
        error.value = failure
        state.value = 'error'
      }
      return null
    }
  }

  watch(
    () => route.params.projectId,
    () => {
      void reload()
    },
    { immediate: true },
  )

  return {
    state,
    project,
    error,
    reload,
  }
}
