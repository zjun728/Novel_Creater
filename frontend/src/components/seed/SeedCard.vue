<script setup>
import { NCard, NTag, NButton, NSpace } from 'naive-ui'

const props = defineProps({
  seed: { type: Object, required: true },
  selected: { type: Boolean, default: false }
})

const emit = defineEmits(['select', 'delete', 'view'])

const typeColors = {
  玄幻: 'error',
  都市: 'info',
  科幻: 'success',
  悬疑: 'warning',
  历史: 'default',
  言情: 'error',
  奇幻: 'warning',
  末世: 'default',
  无限流: 'info'
}

function getTagType(genre) {
  return typeColors[genre] || 'default'
}
</script>

<template>
  <n-card
    :title="seed.title || '未命名种子'"
    size="small"
    :class="{ 'border-2 border-blue-400': selected, 'border border-gray-200': !selected }"
    hoverable
  >
    <template #header-extra>
      <n-tag :type="getTagType(seed.genre)" size="small">{{ seed.genre || '未分类' }}</n-tag>
    </template>

    <p class="text-sm text-gray-600 mb-2 line-clamp-2">{{ seed.logline || '暂无简介' }}</p>

    <div class="text-xs text-gray-400 mb-3 space-y-1">
      <div v-if="seed.protagonist">
        <span class="font-medium">主角：</span>{{ seed.protagonist }}
      </div>
      <div v-if="seed.desire">
        <span class="font-medium">欲望：</span>{{ seed.desire }}
      </div>
      <div v-if="seed.openingHook" class="line-clamp-2">
        <span class="font-medium">开局：</span>{{ seed.openingHook }}
      </div>
    </div>

    <n-space justify="end" size="small">
      <n-tag v-if="seed.source === 'ai'" type="info" size="tiny" :bordered="false">AI 生成</n-tag>
      <n-tag v-else type="default" size="tiny" :bordered="false">手动</n-tag>
      <n-tag v-if="seed.status === 'selected'" type="success" size="tiny" :bordered="false">已选中</n-tag>
    </n-space>

    <template #footer>
      <n-space justify="end" size="small">
        <n-button size="tiny" quaternary @click="emit('delete', seed)">删除</n-button>
        <n-button size="tiny" @click="emit('view', seed)">详情</n-button>
        <n-button
          size="tiny"
          type="primary"
          :disabled="seed.status === 'selected'"
          @click="emit('select', seed)"
        >
          {{ seed.status === 'selected' ? '已选中' : '选择' }}
        </n-button>
      </n-space>
    </template>
  </n-card>
</template>
