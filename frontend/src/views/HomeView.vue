<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NCard, NEmpty, NModal, NForm, NFormItem, NInput, NInputNumber, NSpace, NGrid, NGridItem, useMessage, useDialog } from 'naive-ui'
import { useProjectStore } from '@/stores/projectStore'

const router = useRouter()
const projectStore = useProjectStore()
const message = useMessage()
const dialog = useDialog()

const showCreateModal = ref(false)
const creating = ref(false)
const showImportModal = ref(false)
const importJson = ref('')

const formValue = ref({
  title: '',
  genre: '',
  description: '',
  targetWords: 100000,
  targetChapters: 100
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
    const project = await projectStore.importProjectJson(importJson.value)
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
        <nButton @click="showImportModal = true">导入项目</nButton>
        <nButton type="primary" @click="showCreateModal = true">新建项目</nButton>
      </n-space>
    </div>

    <n-empty v-if="projectStore.projects.length === 0 && !projectStore.loading" description="还没有项目，点击上方按钮创建">
    </n-empty>

    <n-grid :cols="3" :x-gap="16" :y-gap="16" v-if="projectStore.projects.length > 0">
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
              <nButton size="tiny" @click="handleExport(project)">导出</nButton>
              <nButton size="tiny" type="error" quaternary @click="handleDelete(project)">删除</nButton>
              <nButton size="tiny" type="primary" @click="handleOpen(project)">打开</nButton>
            </n-space>
          </template>
        </n-card>
      </n-grid-item>
    </n-grid>

    <!-- 新建项目弹窗 -->
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
          <n-input-number v-model:value="formValue.targetWords" :min="1" :step="1" :format="v => `${v / 10000}`" :parse="v => parseFloat(v) * 10000" />
        </n-form-item>
        <n-form-item label="目标章节数">
          <n-input-number v-model:value="formValue.targetChapters" :min="1" :step="1" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <nButton @click="showCreateModal = false">取消</nButton>
          <nButton type="primary" :loading="creating" @click="handleCreate">创建</nButton>
        </n-space>
      </template>
    </n-modal>

    <!-- 导入项目弹窗 -->
    <n-modal v-model:show="showImportModal" title="导入项目" preset="card" style="width: 560px">
      <p class="text-sm text-yellow-600 mb-3">⚠️ 请粘贴从本系统导出的项目 JSON 备份文件内容。</p>
      <n-input v-model:value="importJson" type="textarea" rows="10" placeholder="粘贴项目 JSON 内容" />
      <template #footer>
        <n-space justify="end">
          <nButton @click="showImportModal = false">取消</nButton>
          <nButton type="primary" @click="handleImport">导入</nButton>
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
