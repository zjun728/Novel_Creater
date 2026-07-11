<script setup>
import { useRouter, useRoute } from 'vue-router'
import { NMenu, NButton, useDialog } from 'naive-ui'
import { computed } from 'vue'
import { useProjectStore } from '@/stores/projectStore'

const router = useRouter()
const route = useRoute()
const dialog = useDialog()
const projectStore = useProjectStore()

const menuOptions = computed(() => {
  const options = [
    {
      label: '项目库',
      key: '/',
      icon: () => '📚'
    }
  ]

  if (projectStore.currentProject) {
    options.push({
      label: projectStore.currentProject.title || '当前项目',
      key: `/project/${projectStore.currentProject.id}`,
      icon: () => '📖'
    })
  }

  options.push({
    label: '设置',
    key: '/settings',
    icon: () => '⚙️'
  })

  return options
})

function handleUpdate(key) {
  router.push(key)
}

function handleBackToProjects() {
  projectStore.currentProject = null
  router.push('/')
}
</script>

<template>
  <div class="sidebar flex flex-col h-full bg-gray-50 border-r border-gray-200">
    <div class="p-4 border-b border-gray-200">
      <h1 class="text-lg font-bold text-gray-800 truncate">Novel Creator</h1>
    </div>
    <div class="flex-1 overflow-y-auto">
      <n-menu
        :value="route.path"
        :options="menuOptions"
        @update:value="handleUpdate"
      />
    </div>
    <div class="p-3 border-t border-gray-200" v-if="projectStore.currentProject">
      <nButton quaternary size="small" @click="handleBackToProjects">
        ← 返回项目库
      </nButton>
    </div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 220px;
  min-width: 220px;
}
</style>
