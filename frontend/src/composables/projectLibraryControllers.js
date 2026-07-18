import { reactive, ref } from 'vue'

import { chapterWriterPath, projectOverviewPath } from '../router/projectRoutes.js'

function publicError(error, fallback) {
  return String(error?.message || fallback)
}

export function createProjectLibraryController({ store, router, message }) {
  const loading = ref(true)
  const loadError = ref('')
  const actionError = ref('')
  const createDialogOpen = ref(false)
  const createPending = ref(false)
  const createError = ref('')
  const renameTarget = ref(null)
  const renamePending = ref(false)
  const renameError = ref('')
  const pendingProjectIds = reactive(new Set())

  async function load() {
    loading.value = true
    loadError.value = ''
    try {
      await store.loadActiveProjects?.()
    } catch (error) {
      loadError.value = publicError(error, '项目库加载失败')
    } finally {
      loading.value = false
    }
  }

  function beginCreate() {
    createError.value = ''
    createDialogOpen.value = true
  }

  function closeCreate() {
    if (createPending.value) return
    createDialogOpen.value = false
    createError.value = ''
  }

  async function create({ title }) {
    if (createPending.value) return
    createPending.value = true
    createError.value = ''
    let created
    try {
      created = await store.createProject(title)
    } catch (error) {
      createError.value = publicError(error, '项目创建失败，请重试')
      return
    } finally {
      createPending.value = false
    }

    createDialogOpen.value = false
    message.success('项目已创建')
    try {
      await router.push(projectOverviewPath(created.id))
    } catch (error) {
      actionError.value = publicError(error, '项目已创建，请点击“打开项目”继续')
    }
  }

  function beginRename(project) {
    renameError.value = ''
    renameTarget.value = project
  }

  function closeRename() {
    if (renamePending.value) return
    renameTarget.value = null
    renameError.value = ''
  }

  async function rename({ title }) {
    if (!renameTarget.value || renamePending.value) return
    const projectId = renameTarget.value.id
    renamePending.value = true
    renameError.value = ''
    try {
      await store.renameProject(projectId, title)
      renameTarget.value = null
      message.success('项目名称已更新')
    } catch (error) {
      renameError.value = publicError(error, '项目重命名失败，请重试')
    } finally {
      renamePending.value = false
    }
  }

  function open(project) {
    return router.push(projectOverviewPath(project.id))
  }

  function resume(project, chapterNumber) {
    return router.push(chapterWriterPath(project.id, chapterNumber))
  }

  function isProjectPending(projectId) {
    return pendingProjectIds.has(String(projectId))
  }

  async function archive(project) {
    const projectId = String(project.id)
    if (pendingProjectIds.has(projectId)) return
    pendingProjectIds.add(projectId)
    actionError.value = ''
    try {
      const archived = await store.archiveProject(
        project.id,
        project.lifecycleRevision,
      )
      message.success('项目已归档', {
        actionLabel: '撤销',
        duration: 6000,
        onAction: async () => {
          const archivedId = String(archived.id)
          if (pendingProjectIds.has(archivedId)) return
          pendingProjectIds.add(archivedId)
          actionError.value = ''
          try {
            await store.restoreProject(
              archived.id,
              archived.lifecycleRevision,
            )
            message.success('项目已恢复')
          } catch (error) {
            actionError.value = publicError(error, '撤销归档失败，请重试')
            message.error('撤销归档失败', { duration: 8000 })
          } finally {
            pendingProjectIds.delete(archivedId)
          }
        },
      })
    } catch (error) {
      actionError.value = publicError(error, '项目归档失败，请重试')
    } finally {
      pendingProjectIds.delete(projectId)
    }
  }

  function dismissActionError() {
    actionError.value = ''
  }

  function resumableChapterNumber(project) {
    const chapterNumber = Number(project?.resumableChapterNumber)
    return Number.isInteger(chapterNumber) && chapterNumber > 0
      ? chapterNumber
      : null
  }

  return {
    loading,
    loadError,
    actionError,
    createDialogOpen,
    createPending,
    createError,
    renameTarget,
    renamePending,
    renameError,
    load,
    beginCreate,
    closeCreate,
    create,
    beginRename,
    closeRename,
    rename,
    open,
    resume,
    archive,
    isProjectPending,
    dismissActionError,
    resumableChapterNumber,
  }
}

export function createArchivedProjectsController({
  store,
  message,
  confirmation,
}) {
  const loading = ref(true)
  const loadError = ref('')
  const actionError = ref('')
  const pendingProjectIds = reactive(new Set())
  const confirmingProjectIds = reactive(new Set())

  async function load() {
    loading.value = true
    loadError.value = ''
    try {
      await store.loadArchivedProjects?.()
    } catch (error) {
      loadError.value = publicError(error, '已归档项目加载失败')
    } finally {
      loading.value = false
    }
  }

  function isProjectPending(projectId) {
    const key = String(projectId)
    return pendingProjectIds.has(key) || confirmingProjectIds.has(key)
  }

  async function restore(project) {
    const projectId = String(project.id)
    if (pendingProjectIds.has(projectId)) return
    pendingProjectIds.add(projectId)
    actionError.value = ''
    try {
      await store.restoreProject(project.id, project.lifecycleRevision)
      message.success('项目已恢复')
    } catch (error) {
      actionError.value = publicError(error, '项目恢复失败，请重试')
    } finally {
      pendingProjectIds.delete(projectId)
    }
  }

  async function permanentlyDelete(project) {
    const projectId = String(project.id)
    if (isProjectPending(projectId)) return
    confirmingProjectIds.add(projectId)
    actionError.value = ''
    try {
      await confirmation.confirm({
        title: `永久删除《${project.title}》？`,
        content: '项目正文、工作稿、候选和规划将全部删除，且无法恢复。',
        positiveText: '永久删除',
        negativeText: '取消',
        onConfirm: async () => {
          pendingProjectIds.add(projectId)
          actionError.value = ''
          try {
            await store.permanentlyDeleteProject(
              project.id,
              project.lifecycleRevision,
            )
            message.success('项目已永久删除')
          } catch (error) {
            actionError.value = publicError(error, '永久删除失败，请重试')
            throw error
          } finally {
            pendingProjectIds.delete(projectId)
          }
        },
      })
    } finally {
      confirmingProjectIds.delete(projectId)
    }
  }

  function dismissActionError() {
    actionError.value = ''
  }

  return {
    loading,
    loadError,
    actionError,
    load,
    restore,
    permanentlyDelete,
    isProjectPending,
    dismissActionError,
  }
}
