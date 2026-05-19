import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'

export const useProjectStore = defineStore('project', () => {
  const projects = ref([])
  const currentProject = ref(null)
  const loading = ref(false)

  async function loadProjects() {
    loading.value = true
    try {
      projects.value = await api.projects.list()
    } catch (e) {
      console.error('加载项目列表失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function createProject({ title, genre, description, targetWords, targetChapters }) {
    try {
      const project = await api.projects.create({
        title,
        genre: genre || '',
        description: description || '',
        targetWords: targetWords || 100000,
        targetChapters: targetChapters || 100
      })
      projects.value.unshift(project)
      return project
    } catch (e) {
      console.error('创建项目失败:', e.message)
      throw e
    }
  }

  async function openProject(id) {
    loading.value = true
    try {
      currentProject.value = await api.projects.get(id)
      return currentProject.value
    } catch (e) {
      console.error('打开项目失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function updateProject(project) {
    try {
      const updated = await api.projects.update(project.id, {
        title: project.title,
        genre: project.genre,
        description: project.description,
        targetWords: project.targetWords,
        targetChapters: project.targetChapters,
        currentChapterNum: project.currentChapterNum,
        status: project.status
      })
      const idx = projects.value.findIndex(p => p.id === updated.id)
      if (idx !== -1) projects.value[idx] = updated
      if (currentProject.value?.id === updated.id) currentProject.value = updated
      return updated
    } catch (e) {
      console.error('更新项目失败:', e.message)
      throw e
    }
  }

  async function deleteProject(id) {
    try {
      await api.projects.delete(id)
      projects.value = projects.value.filter(p => p.id !== id)
      if (currentProject.value?.id === id) currentProject.value = null
    } catch (e) {
      console.error('删除项目失败:', e.message)
      throw e
    }
  }

  async function exportProjectJson(id) {
    try {
      const data = await api.exportFull(id)
      return JSON.stringify(data, null, 2)
    } catch (e) {
      console.error('导出项目失败:', e.message)
      throw e
    }
  }

  async function importProjectJson(jsonStr) {
    try {
      const data = JSON.parse(jsonStr)
      if (!data.projects?.length && !data.project) throw new Error('无效的项目数据')

      if (data.project && !data.projects) {
        data.projects = [{ ...data, project: data.project }]
        data.providers = data.providers || []
      }

      await api.importFull(data)
      await loadProjects()
      return projects.value[0]
    } catch (e) {
      console.error('导入项目失败:', e.message)
      throw e
    }
  }

  return {
    projects,
    currentProject,
    loading,
    loadProjects,
    createProject,
    openProject,
    updateProject,
    deleteProject,
    exportProjectJson,
    importProjectJson
  }
})
