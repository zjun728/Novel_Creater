<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { NButton, NResult, NSkeleton } from 'naive-ui'

import ProjectPageHeader from '../components/projects/ProjectPageHeader.vue'
import { projectMetadataPayload } from '../application/projects/projectMetadata.js'
import { useAppMessage } from '../composables/useAppMessage.js'
import { useRouteProject } from '../composables/useRouteProject.js'
import { useProjectStore } from '../stores/projectStore.js'
import NotFoundView from './NotFoundView.vue'

defineProps({ projectId: { type: String, required: true } })
const routeProject = useRouteProject()
const projectStore = useProjectStore()
const message = useAppMessage()
const saving = ref(false)
const error = ref('')
const savedSignature = ref('')
const form = reactive({ title: '', genre: '', description: '', targetWords: 2_400_000, targetChapters: 720 })
const archived = computed(() => routeProject.state.value === 'archived')
const signature = computed(() => JSON.stringify(form))
const dirty = computed(() => savedSignature.value && signature.value !== savedSignature.value)

function hydrate(project) {
  if (!project) return
  Object.assign(form, {
    title: project.title || '',
    genre: project.genre || '',
    description: project.description || '',
    targetWords: project.targetWords ?? 2_400_000,
    targetChapters: project.targetChapters ?? 720,
  })
  savedSignature.value = JSON.stringify(form)
  error.value = ''
}

watch(() => routeProject.project.value, hydrate, { immediate: true })

async function save() {
  if (archived.value || saving.value) return
  error.value = ''
  let metadata
  try {
    metadata = projectMetadataPayload(form)
  } catch {
    error.value = '请填写项目名称，并确认目标字数和预计章节数为正整数。'
    return
  }
  saving.value = true
  try {
    const updated = await projectStore.updateProjectSettings(routeProject.project.value.id, {
      ...metadata,
      expectedLifecycleRevision: routeProject.project.value.lifecycleRevision,
    })
    routeProject.project.value = updated
    hydrate(updated)
    message.success('项目资料已保存')
  } catch (failure) {
    error.value = failure?.message || '项目资料保存失败，请重试'
  } finally {
    saving.value = false
  }
}

onBeforeRouteLeave(() => {
  if (saving.value) {
    message.warning('项目资料正在保存，请等待结果明确后再离开。')
    return false
  }
  if (!dirty.value) return true
  return typeof window !== 'undefined' && window.confirm('项目资料尚未保存。放弃修改并离开吗？')
})
</script>

<template>
  <section v-if="routeProject.state.value === 'loading'" class="settings-page" aria-busy="true">
    <div class="settings-sheet"><n-skeleton text :repeat="6" /></div>
  </section>
  <not-found-view v-else-if="routeProject.state.value === 'missing'" title="项目不存在或已被删除" description="请返回项目库确认项目状态。" />
  <section v-else-if="routeProject.state.value === 'error'" class="settings-page">
    <n-result status="error" title="项目资料暂时无法加载" :description="routeProject.error.value?.message || '请稍后重试'">
      <template #footer><n-button type="primary" @click="routeProject.reload">重试</n-button></template>
    </n-result>
  </section>
  <section v-else class="settings-page">
    <div class="settings-sheet">
      <ProjectPageHeader kicker="PROJECT IDENTITY · LONG-FORM SCALE" title="项目资料" description="集中维护作品定位与长篇规模；种子、契约和创作核心仍按原流程独立确认。" :archived="archived" />
      <p v-if="archived" class="archive-notice">已归档项目资料只能查看；恢复项目后才能修改。</p>
      <form class="settings-form" @submit.prevent="save">
        <label class="field field--wide"><span>项目名称</span><input v-model="form.title" maxlength="200" :disabled="archived || saving"></label>
        <label class="field"><span>题材</span><input v-model="form.genre" maxlength="120" placeholder="如：东方奇幻" :disabled="archived || saving"></label>
        <label class="field"><span>目标字数</span><input v-model.number="form.targetWords" type="number" min="1" step="1" :disabled="archived || saving"><small>平台面向 200 万字以上长篇，默认 240 万字</small></label>
        <label class="field"><span>预计章节数</span><input v-model.number="form.targetChapters" type="number" min="1" step="1" :disabled="archived || saving"></label>
        <label class="field field--wide"><span>项目简介</span><textarea v-model="form.description" maxlength="5000" rows="7" :disabled="archived || saving" placeholder="概括故事方向、主角目标和核心冲突"></textarea><small>{{ form.description.length }} / 5000</small></label>
        <p v-if="error" class="form-error" role="alert">{{ error }}</p>
        <footer v-if="!archived"><span>{{ dirty ? '有尚未保存的修改' : '所有修改已保存' }}</span><button type="submit" :disabled="saving || !dirty">{{ saving ? '正在保存…' : '保存项目资料' }}</button></footer>
      </form>
    </div>
  </section>
</template>

<style scoped>
.settings-page { min-height: 100%; padding: clamp(22px,4vw,52px); color: #302a23; background: #f4efe4; }
.settings-sheet { width: min(1000px,100%); box-sizing: border-box; margin: 0 auto; padding: clamp(24px,4vw,44px); border: 1px solid #d8cbb7; border-radius: 14px; background: #fffdf8; box-shadow: 0 22px 60px rgba(58,43,27,.065); }
.archive-notice { margin: 24px 0 0; padding: 12px 15px; border-left: 3px solid #a98558; background: #f5eee1; color: #6f6254; }
.settings-form { display: grid; grid-template-columns: 1fr 1fr; gap: 22px 24px; margin-top: 30px; }
.field { display: grid; align-content: start; gap: 8px; }
.field--wide, .form-error, footer { grid-column: 1 / -1; }
.field span { font-weight: 700; font-size: 14px; }
.field small, footer span { color: #817568; font-size: 12px; }
input, textarea { box-sizing: border-box; width: 100%; min-height: 46px; padding: 11px 13px; border: 1px solid #d8cbb7; border-radius: 8px; outline: none; background: #fffefb; color: #302a23; font: inherit; }
textarea { resize: vertical; line-height: 1.75; }
input:focus, textarea:focus { border-color: #9a3f32; box-shadow: 0 0 0 3px rgba(154,63,50,.1); }
input:disabled, textarea:disabled { color: #51483f; background: #f4efe7; }
.form-error { margin: 0; color: #a43f32; }
footer { display: flex; justify-content: space-between; align-items: center; gap: 18px; padding-top: 20px; border-top: 1px solid #e4dacb; }
button { min-height: 44px; padding: 0 22px; border: 0; border-radius: 9px; background: #9a3f32; color: #fff; font-weight: 700; cursor: pointer; }
button:disabled { cursor: default; opacity: .5; }
@media (max-width: 640px) { .settings-form { grid-template-columns: 1fr; } .field, .field--wide { grid-column: 1; } footer { align-items: stretch; flex-direction: column; } }
</style>
