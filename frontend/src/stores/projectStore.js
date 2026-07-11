import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

export const useProjectStore = defineStore('project', () => {
  const projects = ref([])
  const currentProject = ref(null)
  const loading = ref(false)
  const openGuard = createLatestRequestGuard()

  async function loadProjects() {
    loading.value = true
    try {
      projects.value = await api.projects.list() || []
      return projects.value
    } finally {
      loading.value = false
    }
  }

  async function createProject({ title, genre, description, targetWords, targetChapters }) {
    const project = await api.projects.create({
      title,
      genre: genre || '',
      description: description || '',
      targetWords: targetWords || 100000,
      targetChapters: targetChapters || 100,
    })
    projects.value.unshift(project)
    return project
  }

  async function openProject(projectId) {
    const requestGeneration = openGuard.begin()
    currentProject.value = null
    loading.value = true
    try {
      const project = await api.projects.get(projectId)
      if (openGuard.isCurrent(requestGeneration)) currentProject.value = project
      return project
    } finally {
      if (openGuard.isCurrent(requestGeneration)) loading.value = false
    }
  }

  function invalidateOpenProject() {
    openGuard.invalidate()
    currentProject.value = null
    loading.value = false
  }

  async function updateProject(project) {
    const updated = await api.projects.update(project.id, {
      title: project.title,
      genre: project.genre,
      description: project.description,
      targetWords: project.targetWords,
      targetChapters: project.targetChapters,
      status: project.status,
    })
    const index = projects.value.findIndex(item => item.id === updated.id)
    if (index !== -1) projects.value[index] = updated
    if (currentProject.value?.id === updated.id) currentProject.value = updated
    return updated
  }

  async function deleteProject(projectId) {
    await api.projects.delete(projectId)
    projects.value = projects.value.filter(project => project.id !== projectId)
    if (currentProject.value?.id === projectId) currentProject.value = null
  }

  return {
    projects,
    currentProject,
    loading,
    loadProjects,
    createProject,
    openProject,
    invalidateOpenProject,
    updateProject,
    deleteProject,
  }
})
