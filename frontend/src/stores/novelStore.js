import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'

export const useNovelStore = defineStore('novel', () => {
  const bible = ref(null)
  const outline = ref(null)
  const characters = ref([])
  const plotThreads = ref([])
  const canonFacts = ref([])
  const possibilityCards = ref([])
  const loading = ref(false)

  // === 创作圣经 ===
  async function loadBible(projectId) {
    loading.value = true
    try {
      bible.value = await api.bible.get(projectId)
      return bible.value
    } catch (e) {
      console.error('加载创作圣经失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveBible(projectId, data) {
    loading.value = true
    try {
      const result = await api.bible.save(projectId, data)
      bible.value = result
      return result
    } catch (e) {
      console.error('保存创作圣经失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  // === 滚动大纲 ===
  async function loadOutline(projectId) {
    loading.value = true
    try {
      outline.value = await api.outline.get(projectId)
      return outline.value
    } catch (e) {
      console.error('加载大纲失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveOutline(projectId, data) {
    loading.value = true
    try {
      const result = await api.outline.save(projectId, data)
      outline.value = result
      return result
    } catch (e) {
      console.error('保存大纲失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  // === 角色 ===
  async function loadCharacters(projectId) {
    loading.value = true
    try {
      characters.value = await api.characters.list(projectId)
      return characters.value
    } catch (e) {
      console.error('加载角色失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveCharacter(data) {
    try {
      const pid = data.projectId || data.project_id
      if (data.id) {
        const updated = await api.characters.update(pid, data.id, data)
        const idx = characters.value.findIndex(c => c.id === data.id)
        if (idx !== -1) characters.value[idx] = updated
      } else {
        const created = await api.characters.create(pid, data)
        characters.value.push(created)
      }
    } catch (e) {
      console.error('保存角色失败:', e.message)
      throw e
    }
  }

  async function deleteCharacter(id) {
    try {
      const ch = characters.value.find(c => c.id === id)
      if (!ch) return
      const pid = ch.projectId || ch.project_id
      await api.characters.delete(pid, id)
      characters.value = characters.value.filter(c => c.id !== id)
    } catch (e) {
      console.error('删除角色失败:', e.message)
      throw e
    }
  }

  // === 伏笔 ===
  async function loadPlotThreads(projectId) {
    loading.value = true
    try {
      plotThreads.value = await api.plotThreads.list(projectId)
      return plotThreads.value
    } catch (e) {
      console.error('加载伏笔失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function savePlotThread(data) {
    try {
      const pid = data.projectId || data.project_id
      if (data.id) {
        const updated = await api.plotThreads.update(pid, data.id, data)
        const idx = plotThreads.value.findIndex(t => t.id === data.id)
        if (idx !== -1) plotThreads.value[idx] = updated
      } else {
        const created = await api.plotThreads.create(pid, data)
        plotThreads.value.push(created)
      }
    } catch (e) {
      console.error('保存伏笔失败:', e.message)
      throw e
    }
  }

  async function deletePlotThread(id) {
    try {
      const t = plotThreads.value.find(t => t.id === id)
      if (!t) return
      const pid = t.projectId || t.project_id
      await api.plotThreads.delete(pid, id)
      plotThreads.value = plotThreads.value.filter(t => t.id !== id)
    } catch (e) {
      console.error('删除伏笔失败:', e.message)
      throw e
    }
  }

  // === Canon 事实 ===
  async function loadCanonFacts(projectId) {
    loading.value = true
    try {
      canonFacts.value = await api.canonFacts.list(projectId)
      return canonFacts.value
    } catch (e) {
      console.error('加载Canon事实失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveCanonFact(data) {
    try {
      const pid = data.projectId || data.project_id
      if (data.id) {
        const updated = await api.canonFacts.update(pid, data.id, data)
        const idx = canonFacts.value.findIndex(f => f.id === data.id)
        if (idx !== -1) canonFacts.value[idx] = updated
      } else {
        const created = await api.canonFacts.create(pid, data)
        canonFacts.value.push(created)
      }
    } catch (e) {
      console.error('保存Canon事实失败:', e.message)
      throw e
    }
  }

  async function confirmCanonFact(id) {
    try {
      const fact = canonFacts.value.find(f => f.id === id)
      if (fact) {
        const pid = fact.projectId || fact.project_id
        fact.status = 'accepted'
        await api.canonFacts.update(pid, id, { status: 'accepted' })
      }
    } catch (e) {
      console.error('确认Canon事实失败:', e.message)
      throw e
    }
  }

  async function rejectCanonFact(id) {
    try {
      const fact = canonFacts.value.find(f => f.id === id)
      if (fact) {
        const pid = fact.projectId || fact.project_id
        fact.status = 'rejected'
        await api.canonFacts.update(pid, id, { status: 'rejected' })
      }
    } catch (e) {
      console.error('拒绝Canon事实失败:', e.message)
      throw e
    }
  }

  // === 可能性池 ===
  async function loadPossibilityCards(projectId) {
    loading.value = true
    try {
      possibilityCards.value = await api.possibilityCards.list(projectId)
      return possibilityCards.value
    } catch (e) {
      console.error('加载可能性池失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function savePossibilityCard(data) {
    try {
      const pid = data.projectId || data.project_id
      const created = await api.possibilityCards.create(pid, data)
      possibilityCards.value.push(created)
    } catch (e) {
      console.error('保存可能性卡片失败:', e.message)
      throw e
    }
  }

  async function deletePossibilityCard(id) {
    try {
      const card = possibilityCards.value.find(c => c.id === id)
      if (!card) return
      const pid = card.projectId || card.project_id
      await api.possibilityCards.delete(pid, id)
      possibilityCards.value = possibilityCards.value.filter(c => c.id !== id)
    } catch (e) {
      console.error('删除可能性卡片失败:', e.message)
      throw e
    }
  }

  return {
    bible,
    outline,
    characters,
    plotThreads,
    canonFacts,
    possibilityCards,
    loading,
    loadBible,
    saveBible,
    loadOutline,
    saveOutline,
    loadCharacters,
    saveCharacter,
    deleteCharacter,
    loadPlotThreads,
    savePlotThread,
    deletePlotThread,
    loadCanonFacts,
    saveCanonFact,
    confirmCanonFact,
    rejectCanonFact,
    loadPossibilityCards,
    savePossibilityCard,
    deletePossibilityCard
  }
})
