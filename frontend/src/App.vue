<script setup>
import {
  NAlert,
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  dateZhCN,
  zhCN,
} from 'naive-ui'
import { computed, onErrorCaptured, onMounted, onUnmounted, provide } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'

import AppInteractionBoundary from '@/components/common/AppInteractionBoundary.vue'
import AppOperationOverlay from '@/components/common/AppOperationOverlay.vue'
import Sidebar from '@/components/layout/Sidebar.vue'
import TopBar from '@/components/layout/TopBar.vue'
import {
  createProductShellModel,
  SHELL_PROJECT_CONTEXT,
  useShellProjectHydration,
  useViewportWidth,
} from '@/components/layout/productShell.js'
import { useHealthCheck } from '@/composables/useHealthCheck'
import { useOperationStore } from '@/stores/operationStore.js'
import { useProjectStore } from '@/stores/projectStore.js'

const route = useRoute()
const projectStore = useProjectStore()
const routeProject = useShellProjectHydration({ route, store: projectStore })
provide(SHELL_PROJECT_CONTEXT, routeProject)
const viewportWidth = useViewportWidth()
const { blocking } = storeToRefs(useOperationStore())
const { backendOnline, startPeriodic, stopPeriodic } = useHealthCheck()

const shellProject = computed(() => {
  const projectId = String(route.params.projectId || '')
  if (
    projectStore.currentProject?.id != null
    && String(projectStore.currentProject.id) === projectId
  ) return projectStore.currentProject
  return routeProject.project.value
})

const shell = computed(() => createProductShellModel({
  route,
  project: shellProject.value,
  viewportWidth: viewportWidth.value,
}))

onMounted(() => {
  startPeriodic(60000)
})

onUnmounted(() => {
  stopPeriodic()
})

onErrorCaptured((_error, _instance, info) => {
  console.error('[界面错误]', info)
  return false
})
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-dialog-provider>
        <AppInteractionBoundary :blocking="blocking">
          <div
            class="product-app-shell"
            :class="{ 'product-app-shell--collapsed': shell.sidebarCollapsed }"
            :data-sidebar-collapsed="String(shell.sidebarCollapsed)"
          >
            <Sidebar :shell="shell" />
            <section class="product-app-shell__workspace">
              <TopBar :shell="shell" />
              <n-alert
                v-if="!backendOnline"
                type="error"
                :bordered="false"
                class="product-app-shell__offline"
              >
                后端服务连接失败。请确认本机 API 服务已启动后重试。
              </n-alert>
              <main class="product-app-shell__content">
                <router-view />
              </main>
            </section>
          </div>
          <template #overlay>
            <AppOperationOverlay />
          </template>
        </AppInteractionBoundary>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
