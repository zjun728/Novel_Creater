<script setup>
import {
  NAlert,
  NConfigProvider,
  NDialogProvider,
  NMessageProvider,
  dateZhCN,
  zhCN,
} from 'naive-ui'
import { computed, nextTick, onErrorCaptured, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'

import AppInteractionBoundary from '@/components/common/AppInteractionBoundary.vue'
import AppOperationOverlay from '@/components/common/AppOperationOverlay.vue'
import MobileNavigationDrawer, { navigationModeForWidth } from '@/components/layout/MobileNavigationDrawer.vue'
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
import { createBeforeUnloadManager } from '@/router/operationNavigationGuard.js'
import {
  createManuscriptHistory,
  MANUSCRIPT_HISTORY_CONTEXT,
} from '@/application/manuscript/manuscriptHistory.js'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const routeProject = useShellProjectHydration({ route, store: projectStore })
provide(SHELL_PROJECT_CONTEXT, routeProject)
const viewportWidth = useViewportWidth()
const operationStore = useOperationStore()
const { blocking } = storeToRefs(operationStore)
const beforeUnload = createBeforeUnloadManager()
const { backendOnline, startPeriodic, stopPeriodic } = useHealthCheck()
const shellRegion = ref(null)
const mainContent = ref(null)
const menuButton = ref(null)
const mobileNavigationOpen = ref(false)
const navigationMode = computed(() => navigationModeForWidth(viewportWidth.value))
const isMobileNavigation = computed(() => navigationMode.value === 'mobile')
const manuscriptHistory = createManuscriptHistory({
  router,
  getScroller: () => mainContent.value,
  schedule: nextTick,
})
provide(MANUSCRIPT_HISTORY_CONTEXT, manuscriptHistory)

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

onMounted(async () => {
  startPeriodic(60000)
  beforeUnload.setBlocking(blocking.value)
  await nextTick()
  await manuscriptHistory.mount()
})

watch(blocking, value => beforeUnload.setBlocking(value))
watch(isMobileNavigation, mobile => {
  if (!mobile) mobileNavigationOpen.value = false
})

onUnmounted(() => {
  stopPeriodic()
  beforeUnload.dispose()
  manuscriptHistory.dispose()
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
          <div ref="shellRegion" class="product-application-region">
            <a class="skip-link" href="#main-content">跳到主内容</a>
            <div
              class="product-app-shell"
              :class="{
                'product-app-shell--collapsed': shell.sidebarCollapsed && !isMobileNavigation,
                'product-app-shell--mobile': isMobileNavigation,
              }"
              :data-sidebar-collapsed="String(shell.sidebarCollapsed)"
              :data-navigation-mode="navigationMode"
            >
              <Sidebar v-if="!isMobileNavigation" :shell="shell" />
              <section class="product-app-shell__workspace">
              <div v-if="isMobileNavigation" class="product-mobile-topbar">
                <button
                  ref="menuButton"
                  type="button"
                  aria-controls="mobile-navigation-drawer"
                  :aria-expanded="String(mobileNavigationOpen)"
                  @click="mobileNavigationOpen = true"
                >
                  <span aria-hidden="true">☰</span>
                  <span>菜单</span>
                </button>
                <strong>{{ shell.routeTitle }}</strong>
              </div>
              <TopBar :shell="shell" />
              <n-alert
                v-if="!backendOnline"
                type="error"
                :bordered="false"
                class="product-app-shell__offline"
              >
                后端服务连接失败。请确认本机 API 服务已启动后重试。
              </n-alert>
              <main
                id="main-content"
                ref="mainContent"
                class="product-app-shell__content"
                data-manuscript-history="true"
                tabindex="-1"
              >
                <router-view />
              </main>
              </section>
            </div>
          </div>
          <MobileNavigationDrawer
            :open="mobileNavigationOpen"
            :shell="shell"
            :application-region="shellRegion"
            :trigger="menuButton"
            @close="mobileNavigationOpen = false"
            @navigate="mobileNavigationOpen = false"
          />
          <template #overlay>
            <AppOperationOverlay />
          </template>
        </AppInteractionBoundary>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
