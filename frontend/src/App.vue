<script setup>
import { NConfigProvider, NMessageProvider, NDialogProvider, NLayout, NLayoutSider, NLayoutContent, NAlert, zhCN, dateZhCN } from 'naive-ui'
import { darkTheme } from 'naive-ui'
import { ref, onMounted, onUnmounted, onErrorCaptured } from 'vue'
import Sidebar from '@/components/layout/Sidebar.vue'
import TopBar from '@/components/layout/TopBar.vue'
import AppOperationOverlay from '@/components/common/AppOperationOverlay.vue'
import { useHealthCheck } from '@/composables/useHealthCheck'

const darkMode = ref(false)
const theme = ref(null)

const { backendOnline, startPeriodic, stopPeriodic } = useHealthCheck()

onMounted(() => {
  startPeriodic(60000)
})

onUnmounted(() => {
  stopPeriodic()
})

function toggleTheme() {
  darkMode.value = !darkMode.value
  theme.value = darkMode.value ? darkTheme : null
}

onErrorCaptured((err, instance, info) => {
  console.error('[全局错误]', err.message, info)
  return false
})
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN" :theme="theme">
    <n-message-provider>
      <n-dialog-provider>
        <n-layout class="h-screen" has-sider>
          <n-layout-sider
            bordered
            :width="220"
            :collapsed-width="64"
            :collapsed="false"
            :native-scrollbar="false"
            class="sidebar-sider"
          >
            <Sidebar />
          </n-layout-sider>
          <n-layout>
            <TopBar />
            <n-alert v-if="!backendOnline" type="error" :bordered="false" class="rounded-none">
              后端服务连接失败，请确认 API 服务已启动（python -m backend.main）
            </n-alert>
            <n-layout-content class="main-content">
              <router-view />
            </n-layout-content>
          </n-layout>
        </n-layout>
        <AppOperationOverlay />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<style scoped>
.main-content {
  height: calc(100vh - 56px);
  overflow-y: auto;
  background: #fff;
}

.sidebar-sider {
  background: #f9fafb;
}
</style>
