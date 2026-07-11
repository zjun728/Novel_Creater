<script setup>
import { useRouter, useRoute } from 'vue-router'
import { NBreadcrumb, NBreadcrumbItem, NSpace } from 'naive-ui'
import { computed } from 'vue'
import { useProjectStore } from '@/stores/projectStore'

const router = useRouter()
const route = useRoute()
const projectStore = useProjectStore()

const breadcrumbItems = computed(() => {
  const items = [{ label: '项目库', key: '/' }]

  if (projectStore.currentProject) {
    items.push({
      label: projectStore.currentProject.title,
      key: `/project/${projectStore.currentProject.id}`
    })
  }

  return items
})

function handleBreadcrumbClick(item) {
  if (item.key) {
    router.push(item.key)
  }
}
</script>

<template>
  <div class="topbar flex items-center justify-between px-6 h-14 border-b border-gray-200 bg-white">
    <n-breadcrumb>
      <n-breadcrumb-item
        v-for="item in breadcrumbItems"
        :key="item.key"
        @click="handleBreadcrumbClick(item)"
        :class="{ 'cursor-pointer hover:text-blue-600': item.key }"
      >
        {{ item.label }}
      </n-breadcrumb-item>
    </n-breadcrumb>

    <n-space>
      <span class="text-sm text-gray-400">
        v0.1 本地地基版
      </span>
    </n-space>
  </div>
</template>
