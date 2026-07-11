import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

export const useSeedStore = defineStore('seed', () => {
  const seeds = ref([])
  const loading = ref(false)
  const loadGuard = createLatestRequestGuard()

  async function loadSeeds(projectId) {
    const requestGeneration = loadGuard.begin()
    seeds.value = []
    loading.value = true
    try {
      const rows = await api.seeds.list(projectId) || []
      if (loadGuard.isCurrent(requestGeneration)) seeds.value = rows
      return rows
    } finally {
      if (loadGuard.isCurrent(requestGeneration)) loading.value = false
    }
  }

  function invalidateLoadSeeds() {
    loadGuard.invalidate()
    seeds.value = []
    loading.value = false
  }

  return { seeds, loading, loadSeeds, invalidateLoadSeeds }
})
