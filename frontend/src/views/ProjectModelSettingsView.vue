<script setup>
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { NButton, NResult, NSkeleton } from 'naive-ui'
import { ref } from 'vue'

import TaskModelBinding from '@/components/project/settings/TaskModelBinding.vue'
import { useAppMessage } from '@/composables/useAppMessage'
import { useRouteProject } from '@/composables/useRouteProject'
import NotFoundView from './NotFoundView.vue'


defineProps({
  projectId: {
    type: String,
    required: true,
  },
})
const routeProject = useRouteProject()
const router = useRouter()
function returnToProject() { void router.push(`/projects/${routeProject.project.value.id}/overview`) }
const message = useAppMessage()
const operationBusy = ref(false)
const dirty = ref(false)

onBeforeRouteLeave(() => {
  if (operationBusy.value) {
    message.warning('模型绑定正在保存或核验，请等待结果明确后再离开。')
    return false
  }
  if (!dirty.value) return true
  if (typeof window === 'undefined') return false
  return window.confirm('当前有尚未保存的模型绑定。放弃修改并离开吗？')
})
</script>

<template>
  <section
    v-if="routeProject.state.value === 'loading'"
    class="model-settings-page"
    aria-busy="true"
  >
    <section class="model-settings-sheet">
      <n-skeleton text width="32%" />
      <n-skeleton text :repeat="4" />
    </section>
  </section>

  <not-found-view
    v-else-if="routeProject.state.value === 'missing'"
    title="项目不存在或已被删除"
    description="请返回项目库确认项目状态。"
  />

  <section
    v-else-if="routeProject.state.value === 'error'"
    class="model-settings-page"
  >
    <n-result
      status="error"
      title="项目模型设置暂时无法加载"
      :description="routeProject.error.value?.message || '请稍后重试'"
    >
      <template #footer>
        <n-button type="primary" @click="routeProject.reload">重试</n-button>
      </template>
    </n-result>
  </section>

  <section v-else class="model-settings-page">
    <section class="model-settings-sheet">
      <h1>模型绑定</h1>
      <p class="intro">
        为本项目选择创作使用的模型；调整只影响之后的新任务。
      </p>
      <TaskModelBinding
        :project-id="projectId"
        :readonly="routeProject.state.value === 'archived'"
        @saved="returnToProject"
        @cancel="returnToProject"
        @busy-change="operationBusy = $event"
        @dirty-change="dirty = $event"
      />
    </section>
  </section>
</template>

<style scoped>
.model-settings-page { min-height: 100%; padding: 24px 36px; color: #302a23; background: var(--nc-canvas); }
.model-settings-sheet { width: min(1080px, 100%); margin-inline: auto; padding: 28px; border: 1px solid #d8cbb7; border-radius: 14px; background: #fffdf8; box-shadow: 0 22px 60px rgba(58, 43, 27, .065); }
.eyebrow { margin: 0; color: #9a3f32; font: 700 10px Georgia, serif; letter-spacing: .17em; }
h1 { margin: 8px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 30px; font-weight: 600; }
.intro { max-width: 72ch; margin: 10px 0 28px; color: #766c60; font-size: 13px; line-height: 1.75; }
.model-settings-sheet{padding:24px 28px}.intro{margin-bottom:18px}h1{margin:0}
</style>
