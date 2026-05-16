<script setup>
import { ref, onMounted } from 'vue'
import { NAlert, NButton, NSpace } from 'naive-ui'
import { needsReminder, timeSinceBackup, downloadBackup } from '@/utils/backup'

const show = ref(false)

onMounted(() => {
  show.value = needsReminder()
})

async function handleBackup() {
  try {
    await downloadBackup()
    show.value = false
  } catch (e) {
    // silently fail, keep showing reminder
  }
}
</script>

<template>
  <n-alert
    v-if="show"
    type="info"
    closable
    @close="show = false"
  >
    <template #header>
      距离上次备份已过去 {{ timeSinceBackup() }}，建议立即备份项目数据
    </template>
    <n-space>
      <n-button size="tiny" type="primary" @click="handleBackup">立即备份</n-button>
    </n-space>
  </n-alert>
</template>
