<script setup>
import { onBeforeRouteLeave } from 'vue-router'
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
  <main
    v-if="routeProject.state.value === 'loading'"
    class="model-settings-page"
    aria-busy="true"
  >
    <section class="model-settings-sheet">
      <n-skeleton text width="32%" />
      <n-skeleton text :repeat="4" />
    </section>
  </main>

  <not-found-view
    v-else-if="routeProject.state.value === 'missing'"
    title="项目不存在或已被删除"
    description="请返回项目库确认项目状态。"
  />

  <main
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
  </main>

  <main v-else class="model-settings-page">
    <section class="model-settings-sheet">
      <p class="eyebrow">PROJECT SETTINGS · MODEL SNAPSHOT</p>
      <h1>{{ routeProject.project.value?.title || '项目模型绑定' }}</h1>
      <p class="intro">
        模型调整只影响之后的新任务；历史结果继续记录当时的 Provider、模型与绑定 revision。
      </p>
      <TaskModelBinding
        :project-id="projectId"
        :readonly="routeProject.state.value === 'archived'"
        @busy-change="operationBusy = $event"
        @dirty-change="dirty = $event"
      />
    </section>
  </main>
</template>

<style scoped>
.model-settings-page { min-height: 100%; padding: clamp(22px, 4vw, 52px); color: #302a23; background: #f4efe4; }
.model-settings-sheet { width: min(1080px, 100%); margin-inline: auto; padding: clamp(22px, 4vw, 42px); border: 1px solid #d8cbb7; border-radius: 14px; background: #fffdf8; box-shadow: 0 22px 60px rgba(58, 43, 27, .065); }
.eyebrow { margin: 0; color: #9a3f32; font: 700 10px Georgia, serif; letter-spacing: .17em; }
h1 { margin: 8px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(30px, 5vw, 46px); font-weight: 600; }
.intro { max-width: 72ch; margin: 10px 0 28px; color: #766c60; font-size: 13px; line-height: 1.75; }
</style>
