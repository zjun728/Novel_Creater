<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NEmpty,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSpace,
  NGrid,
  NGridItem,
  useDialog
} from 'naive-ui'
import { api } from '@/api/db/client'
import { useAppMessage } from '@/composables/useAppMessage'
import { useProjectStore } from '@/stores/projectStore'

const router = useRouter()
const projectStore = useProjectStore()
const message = useAppMessage()
const dialog = useDialog()

const showCreateModal = ref(false)
const creating = ref(false)
const showImportModal = ref(false)
const importJson = ref('')
const showEditModal = ref(false)
const editing = ref(false)
const loadingEditState = ref(false)
const editingProject = ref(null)
const editContentState = ref(null)

const formValue = ref({
  title: '',
  genre: '',
  description: '',
  targetWords: 100000,
  targetChapters: 100
})

const editFormValue = ref({
  title: '',
  genre: '',
  description: '',
  targetWords: 100000,
  targetChapters: 100
})

const projectPlanLocked = computed(() => {
  if (loadingEditState.value) return true
  return Boolean(editContentState.value?.hasChapterContent)
})

const projectPlanLockReason = computed(() => {
  if (loadingEditState.value) return '正在检查项目章节状态，目标规划字段暂时锁定。'
  const writtenChapters = editContentState.value?.writtenChapters || 0
  const versions = editContentState.value?.chapterVersions || 0
  const drafts = editContentState.value?.tempDrafts || 0
  if (editContentState.value?.hasChapterContent) {
    return `当前项目已有 ${writtenChapters} 个含正文状态的章节、${versions} 个正文/候选版本、${drafts} 个临时草稿。目标字数和目标章节数会影响后续章节规划与进度判断，已锁定不可编辑。`
  }
  return ''
})

onMounted(async () => {
  await projectStore.loadProjects()
})

async function handleCreate() {
  if (!formValue.value.title.trim()) {
    message.warning('请输入项目名称')
    return
  }
  creating.value = true
  try {
    const project = await projectStore.createProject(formValue.value)
    message.success('项目创建成功')
    showCreateModal.value = false
    formValue.value = { title: '', genre: '', description: '', targetWords: 100000, targetChapters: 100 }
    await projectStore.openProject(project.id)
    router.push(`/project/${project.id}`)
  } catch (e) {
    message.error('创建失败：' + e.message)
  } finally {
    creating.value = false
  }
}

function handleOpen(project) {
  projectStore.openProject(project.id)
  router.push(`/project/${project.id}`)
}

async function handleEdit(project) {
  editingProject.value = project
  editFormValue.value = {
    title: project.title || '',
    genre: project.genre || '',
    description: project.description || '',
    targetWords: project.targetWords || 100000,
    targetChapters: project.targetChapters || 100
  }
  editContentState.value = null
  showEditModal.value = true
  loadingEditState.value = true
  try {
    editContentState.value = await api.projects.contentState(project.id)
  } catch (e) {
    editContentState.value = { hasChapterContent: true, writtenChapters: 1, chapterVersions: 1, tempDrafts: 0 }
    message.warning('无法检查章节状态，已临时锁定目标字数和目标章节数。')
  } finally {
    loadingEditState.value = false
  }
}

async function handleUpdateProject() {
  if (!editingProject.value) return
  if (!editFormValue.value.title.trim()) {
    message.warning('请输入项目名称')
    return
  }

  const original = editingProject.value
  const payload = {
    ...original,
    title: editFormValue.value.title.trim(),
    genre: editFormValue.value.genre || '',
    description: editFormValue.value.description || '',
    targetWords: projectPlanLocked.value
      ? original.targetWords
      : Number(editFormValue.value.targetWords || original.targetWords || 100000),
    targetChapters: projectPlanLocked.value
      ? original.targetChapters
      : Number(editFormValue.value.targetChapters || original.targetChapters || 100)
  }

  editing.value = true
  try {
    await projectStore.updateProject(payload)
    message.success('项目信息已更新')
    showEditModal.value = false
    editingProject.value = null
    editContentState.value = null
  } catch (e) {
    message.error('更新失败：' + e.message)
  } finally {
    editing.value = false
  }
}

function handleDelete(project) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除项目「${project.title}」吗？此操作不可恢复。`,
    positiveText: '确认删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await projectStore.deleteProject(project.id)
      message.success('已删除')
    }
  })
}

async function handleExport(project) {
  try {
    const json = await projectStore.exportProjectJson(project.id)
    const blob = new Blob([json], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${project.title}_备份.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('导出成功')
  } catch (e) {
    message.error('导出失败：' + e.message)
  }
}

async function handleImport() {
  if (!importJson.value.trim()) {
    message.warning('请粘贴项目 JSON')
    return
  }
  try {
    await projectStore.importProjectJson(importJson.value)
    message.success('导入成功')
    showImportModal.value = false
    importJson.value = ''
  } catch (e) {
    message.error('导入失败：' + e.message)
  }
}
</script>

<template>
  <div class="p-6">
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-2xl font-bold text-gray-800">项目库</h2>
      <n-space>
        <n-button @click="showImportModal = true">导入项目</n-button>
        <n-button type="primary" @click="showCreateModal = true">新建项目</n-button>
      </n-space>
    </div>

    <n-empty
      v-if="projectStore.projects.length === 0 && !projectStore.loading"
      description="还没有项目，点击上方按钮创建"
    />

    <n-grid v-if="projectStore.projects.length > 0" :cols="3" :x-gap="16" :y-gap="16">
      <n-grid-item v-for="project in projectStore.projects" :key="project.id">
        <n-card
          :title="project.title"
          size="small"
          hoverable
          class="project-card"
        >
          <template #header-extra>
            <span class="text-xs text-gray-400">{{ project.genre || '未分类' }}</span>
          </template>
          <p class="text-sm text-gray-600 mb-3 truncate">{{ project.description || '暂无简介' }}</p>
          <div class="text-xs text-gray-400 mb-3">
            目标 {{ project.targetChapters }} 章 · {{ (project.targetWords / 10000).toFixed(0) }} 万字
          </div>
          <template #footer>
            <n-space justify="end">
              <n-button size="tiny" @click="handleExport(project)">导出</n-button>
              <n-button size="tiny" @click="handleEdit(project)">编辑</n-button>
              <n-button size="tiny" type="error" quaternary @click="handleDelete(project)">删除</n-button>
              <n-button size="tiny" type="primary" @click="handleOpen(project)">打开</n-button>
            </n-space>
          </template>
        </n-card>
      </n-grid-item>
    </n-grid>

    <n-modal v-model:show="showCreateModal" title="新建项目" preset="card" style="width: 520px">
      <n-form :model="formValue">
        <n-form-item label="项目名称" required>
          <n-input v-model:value="formValue.title" placeholder="输入项目名称" />
        </n-form-item>
        <n-form-item label="题材">
          <n-input v-model:value="formValue.genre" placeholder="如：玄幻、都市、科幻" />
        </n-form-item>
        <n-form-item label="简介">
          <n-input v-model:value="formValue.description" type="textarea" rows="3" placeholder="项目简介" />
        </n-form-item>
        <n-form-item label="目标字数（万字）">
          <n-input-number
            v-model:value="formValue.targetWords"
            :min="1"
            :step="1"
            :format="v => `${v / 10000}`"
            :parse="v => Number.parseFloat(v || 0) * 10000"
          />
        </n-form-item>
        <n-form-item label="目标章节数">
          <n-input-number v-model:value="formValue.targetChapters" :min="1" :step="1" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showCreateModal = false">取消</n-button>
          <n-button type="primary" :loading="creating" @click="handleCreate">创建</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showEditModal" title="编辑项目信息" preset="card" style="width: 560px">
      <n-form :model="editFormValue">
        <n-form-item label="项目名称" required>
          <n-input v-model:value="editFormValue.title" placeholder="输入项目名称" />
        </n-form-item>
        <n-form-item label="题材">
          <n-input v-model:value="editFormValue.genre" placeholder="如：玄幻、都市、科幻" />
        </n-form-item>
        <n-form-item label="简介">
          <n-input v-model:value="editFormValue.description" type="textarea" rows="3" placeholder="项目简介" />
        </n-form-item>
        <n-alert v-if="projectPlanLocked" type="warning" class="mb-4" :bordered="false">
          {{ projectPlanLockReason }}
        </n-alert>
        <n-form-item label="目标字数（万字）">
          <n-input-number
            v-model:value="editFormValue.targetWords"
            :min="1"
            :step="1"
            :disabled="projectPlanLocked"
            :format="v => `${v / 10000}`"
            :parse="v => Number.parseFloat(v || 0) * 10000"
          />
        </n-form-item>
        <n-form-item label="目标章节数">
          <n-input-number
            v-model:value="editFormValue.targetChapters"
            :min="1"
            :step="1"
            :disabled="projectPlanLocked"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showEditModal = false">取消</n-button>
          <n-button type="primary" :loading="editing" @click="handleUpdateProject">保存修改</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showImportModal" title="导入项目" preset="card" style="width: 560px">
      <p class="text-sm text-yellow-600 mb-3">请粘贴从本系统导出的项目 JSON 备份文件内容。</p>
      <n-input v-model:value="importJson" type="textarea" rows="10" placeholder="粘贴项目 JSON 内容" />
      <template #footer>
        <n-space justify="end">
          <n-button @click="showImportModal = false">取消</n-button>
          <n-button type="primary" @click="handleImport">导入</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.project-card {
  cursor: pointer;
}
</style>
