<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert, NButton, NCard, NEmpty, NForm, NFormItem, NGrid, NGridItem,
  NInput, NInputNumber, NModal, NSpace, NTag, useDialog,
} from 'naive-ui'
import { api } from '@/api/db/client'
import { useAppMessage } from '@/composables/useAppMessage'
import { useProjectStore } from '@/stores/projectStore'

const router = useRouter()
const projectStore = useProjectStore()
const message = useAppMessage()
const dialog = useDialog()

const showCreateModal = ref(false)
const showEditModal = ref(false)
const creating = ref(false)
const editing = ref(false)
const loadError = ref('')
const loadingEditState = ref(false)
const editingProject = ref(null)
const editContentState = ref(null)
const formValue = ref({ title: '', genre: '', description: '', targetWords: 100000, targetChapters: 100 })
const editFormValue = ref({ title: '', genre: '', description: '', targetWords: 100000, targetChapters: 100 })

const projectPlanLocked = computed(() => loadingEditState.value || Boolean(editContentState.value?.hasFinalChapters))
const projectPlanLockReason = computed(() => {
  if (loadingEditState.value) return '正在读取 Writer Core 项目状态。'
  if (editContentState.value?.hasFinalChapters) return '项目已有不可变定稿章节，目标规模不再允许回写。'
  return ''
})

async function loadProjects() {
  loadError.value = ''
  try {
    await projectStore.loadProjects()
  } catch (error) {
    loadError.value = error.message || '项目列表加载失败'
  }
}

onMounted(loadProjects)

async function handleCreate() {
  if (!formValue.value.title.trim()) return message.warning('请输入项目名称')
  creating.value = true
  try {
    const project = await projectStore.createProject(formValue.value)
    showCreateModal.value = false
    formValue.value = { title: '', genre: '', description: '', targetWords: 100000, targetChapters: 100 }
    message.success('项目已创建')
    await router.push(`/project/${project.id}`)
  } catch (error) {
    message.error(`创建失败：${error.message}`)
  } finally {
    creating.value = false
  }
}

function handleOpen(project) {
  if (!project?.id || router.currentRoute.value.path === `/project/${project.id}`) return
  router.push(`/project/${project.id}`)
}

async function handleEdit(project) {
  editingProject.value = project
  editFormValue.value = {
    title: project.title || '',
    genre: project.genre || '',
    description: project.description || '',
    targetWords: project.targetWords || 100000,
    targetChapters: project.targetChapters || 100,
  }
  editContentState.value = null
  showEditModal.value = true
  loadingEditState.value = true
  try {
    editContentState.value = await api.projects.contentState(project.id)
  } catch (error) {
    editContentState.value = { hasFinalChapters: true }
    message.warning('无法确认定稿状态，目标规模已临时锁定。')
  } finally {
    loadingEditState.value = false
  }
}

async function handleUpdateProject() {
  if (!editingProject.value || !editFormValue.value.title.trim()) return
  const original = editingProject.value
  const payload = {
    ...original,
    title: editFormValue.value.title.trim(),
    genre: editFormValue.value.genre || '',
    description: editFormValue.value.description || '',
    targetWords: projectPlanLocked.value ? original.targetWords : editFormValue.value.targetWords,
    targetChapters: projectPlanLocked.value ? original.targetChapters : editFormValue.value.targetChapters,
  }
  editing.value = true
  try {
    await projectStore.updateProject(payload)
    showEditModal.value = false
    message.success('项目信息已更新')
  } catch (error) {
    message.error(`更新失败：${error.message}`)
  } finally {
    editing.value = false
  }
}

function handleDelete(project) {
  dialog.warning({
    title: '确认删除项目',
    content: `确定删除「${project.title}」吗？此操作不可恢复。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await projectStore.deleteProject(project.id)
      message.success('项目已删除')
    },
  })
}
</script>

<template>
  <main class="library-shell">
    <header class="library-header">
      <div>
        <p class="eyebrow">LOCAL EDITORIAL DESK</p>
        <h1>项目书架</h1>
        <p>每个项目是一份长期写作档案。M1 只开放可信的基础状态。</p>
      </div>
      <n-button type="primary" size="large" @click="showCreateModal = true">新建项目</n-button>
    </header>

    <n-alert v-if="loadError" type="error" class="load-alert">
      {{ loadError }}
      <template #action><n-button size="small" @click="loadProjects">重试</n-button></template>
    </n-alert>

    <section class="shelf" aria-label="项目列表">
      <n-empty v-if="!projectStore.loading && !projectStore.projects.length && !loadError" description="书架还是空的，新建一本书开始整理创作地基。" />
      <n-grid v-else :cols="'1 s:1 m:2 l:3'" responsive="screen" :x-gap="18" :y-gap="18">
        <n-grid-item v-for="project in projectStore.projects" :key="project.id">
          <n-card
            class="project-card"
            hoverable
            role="link"
            tabindex="0"
            :aria-label="`打开项目 ${project.title}`"
            @click="handleOpen(project)"
            @dblclick="handleOpen(project)"
            @keydown.enter="handleOpen(project)"
          >
            <div class="card-folio">PROJECT / {{ project.status || 'drafting' }}</div>
            <div class="card-title-line">
              <h2>{{ project.title }}</h2>
              <n-tag size="small" :bordered="false">{{ project.genre || '未分类' }}</n-tag>
            </div>
            <p class="card-description">{{ project.description || '暂无简介，等待作者补充。' }}</p>
            <dl class="card-targets">
              <div><dt>篇幅</dt><dd>{{ Math.round((project.targetWords || 0) / 10000) }} 万字</dd></div>
              <div><dt>规划</dt><dd>{{ project.targetChapters }} 章</dd></div>
            </dl>
            <template #footer>
              <n-space justify="end">
                <n-button size="tiny" @click.stop="handleEdit(project)">编辑信息</n-button>
                <n-button size="tiny" type="error" quaternary @click.stop="handleDelete(project)">删除</n-button>
                <n-button size="tiny" type="primary" @click.stop="handleOpen(project)">打开项目</n-button>
              </n-space>
            </template>
          </n-card>
        </n-grid-item>
      </n-grid>
    </section>

    <n-modal v-model:show="showCreateModal" preset="card" title="建立新项目档案" style="width: min(540px, 94vw)">
      <n-form :model="formValue" label-placement="top">
        <n-form-item label="项目名称" required><n-input v-model:value="formValue.title" placeholder="小说项目名称" /></n-form-item>
        <n-form-item label="题材"><n-input v-model:value="formValue.genre" placeholder="如：架空历史穿越" /></n-form-item>
        <n-form-item label="简介"><n-input v-model:value="formValue.description" type="textarea" rows="3" /></n-form-item>
        <div class="form-grid">
          <n-form-item label="目标字数"><n-input-number v-model:value="formValue.targetWords" :min="1" :step="10000" /></n-form-item>
          <n-form-item label="目标章节"><n-input-number v-model:value="formValue.targetChapters" :min="1" /></n-form-item>
        </div>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showCreateModal = false">取消</n-button><n-button type="primary" :loading="creating" @click="handleCreate">创建</n-button></n-space></template>
    </n-modal>

    <n-modal v-model:show="showEditModal" preset="card" title="编辑项目档案" style="width: min(560px, 94vw)">
      <n-form :model="editFormValue" label-placement="top">
        <n-form-item label="项目名称" required><n-input v-model:value="editFormValue.title" /></n-form-item>
        <n-form-item label="题材"><n-input v-model:value="editFormValue.genre" /></n-form-item>
        <n-form-item label="简介"><n-input v-model:value="editFormValue.description" type="textarea" rows="3" /></n-form-item>
        <n-alert v-if="projectPlanLocked" type="warning" :bordered="false" class="mb-3">{{ projectPlanLockReason }}</n-alert>
        <div class="form-grid">
          <n-form-item label="目标字数"><n-input-number v-model:value="editFormValue.targetWords" :disabled="projectPlanLocked" :min="1" :step="10000" /></n-form-item>
          <n-form-item label="目标章节"><n-input-number v-model:value="editFormValue.targetChapters" :disabled="projectPlanLocked" :min="1" /></n-form-item>
        </div>
      </n-form>
      <template #footer><n-space justify="end"><n-button @click="showEditModal = false">取消</n-button><n-button type="primary" :loading="editing" @click="handleUpdateProject">保存</n-button></n-space></template>
    </n-modal>
  </main>
</template>

<style scoped>
.library-shell { min-height: 100%; padding: clamp(24px, 4vw, 52px); color: #302b25; background: #f3eee3; }
.library-header { display: flex; width: min(1160px, 100%); align-items: end; justify-content: space-between; gap: 24px; margin: 0 auto; padding-bottom: 27px; border-bottom: 1px solid #d5cab6; }
.eyebrow { margin: 0; color: #98784b; font-size: 10px; font-weight: 800; letter-spacing: .2em; }
h1, h2 { font-family: Georgia, 'Noto Serif SC', serif; }
h1 { margin: 7px 0 5px; font-size: clamp(34px, 5vw, 52px); font-weight: 600; }
.library-header p:last-child { margin: 0; color: #7c7163; }
.load-alert, .shelf { width: min(1160px, 100%); margin-inline: auto; }
.load-alert { margin-top: 20px; }
.shelf { margin-top: 28px; }
.project-card { cursor: pointer; border-color: #dcd1bd; background: #fffdf8; transition: border-color .16s ease, transform .16s ease; }
.project-card:hover { border-color: #a89575; transform: translateY(-2px); }
.project-card:focus-visible { outline: 3px solid rgba(117, 139, 105, .35); outline-offset: 3px; }
.card-folio { color: #a08864; font-size: 9px; font-weight: 750; letter-spacing: .15em; }
.card-title-line { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 16px; }
.card-title-line h2 { margin: 0; font-size: 23px; font-weight: 650; }
.card-description { min-height: 48px; margin: 14px 0 18px; color: #746a5d; font-size: 13px; line-height: 1.75; }
.card-targets { display: grid; grid-template-columns: repeat(2, 1fr); margin: 0; padding-top: 14px; border-top: 1px solid #ebe4d7; }
.card-targets div { display: grid; gap: 2px; }
.card-targets dt { color: #978a78; font-size: 10px; }
.card-targets dd { margin: 0; font-family: Georgia, serif; font-size: 16px; font-weight: 600; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
@media (max-width: 600px) { .library-header { align-items: flex-start; flex-direction: column; } .form-grid { grid-template-columns: 1fr; } }
</style>
