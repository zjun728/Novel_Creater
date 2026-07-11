import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/db/client.js'

export const useSeedStore = defineStore('seed', () => {
  const seeds = ref([])
  const loading = ref(false)
  let loadSequence = 0

  async function loadSeeds(projectId) {
    const sequence = ++loadSequence
    seeds.value = []
    loading.value = true
    try {
      const rows = await api.seeds.list(projectId) || []
      if (sequence === loadSequence) seeds.value = rows
      return rows
    } finally {
      if (sequence === loadSequence) loading.value = false
    }
  }

  return { seeds, loading, loadSeeds }
})
