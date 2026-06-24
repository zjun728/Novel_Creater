<script setup>
import { computed } from 'vue'
import { NCard, NEmpty } from 'naive-ui'
import StoryBlockCard from './StoryBlockCard.vue'

const props = defineProps({
  blocks: { type: Array, default: () => [] },
  activeVolume: { type: Object, default: null },
  chapters: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits([
  'confirmBlock',
  'updateRemainingStages',
  'closeBlock',
  'openNewBlock',
  'saveStageEdit'
])

const visibleBlocks = computed(() => {
  const volume = props.activeVolume
  const blocks = props.blocks || []
  if (!volume) return sortedBlocks(blocks)
  return sortedBlocks(blocks.filter(block => blockBelongsToVolume(block, volume)))
})

function blockBelongsToVolume(block, volume) {
  if (!block || !volume) return false
  if (block.volumeId && String(block.volumeId) === String(volume.id)) return true
  if (block.volumeId) return false

  const start = Number(volume.startChapter || 0)
  const end = Number(volume.endChapter || start)
  return (block.chapterRefs || []).some(ref => {
    const chapterNum = Number(ref?.chapterNum || ref)
    return chapterNum >= start && chapterNum <= end
  })
}

function sortedBlocks(blocks = []) {
  return [...blocks].sort((a, b) =>
    Number(a.blockNum || 0) - Number(b.blockNum || 0) ||
    String(a.createdAt || '').localeCompare(String(b.createdAt || ''))
  )
}
</script>

<template>
  <n-card class="story-block-list" size="small" :bordered="false">
    <div class="story-block-list-header">
      <div>
        <h3>当前卷故事块</h3>
        <p>
          {{ activeVolume ? `${activeVolume.title || `第 ${activeVolume.volumeNum} 卷`} · ` : '' }}
          分卷 -> 故事块 -> 章节
        </p>
      </div>
    </div>

    <n-empty
      v-if="!visibleBlocks.length"
      size="small"
      description="当前卷还没有故事块；生成小纲前会创建故事块。"
    />

    <div v-else class="story-block-list-grid">
      <StoryBlockCard
        v-for="block in visibleBlocks"
        :key="block.id"
        :block="block"
        :active="block.status === 'active'"
        :disabled="disabled || loading"
        @confirm-block="emit('confirmBlock', $event)"
        @update-remaining-stages="emit('updateRemainingStages', $event)"
        @close-block="emit('closeBlock', $event)"
        @open-new-block="emit('openNewBlock', $event)"
        @save-stage-edit="emit('saveStageEdit', $event)"
      />
    </div>
  </n-card>
</template>

<style scoped>
.story-block-list {
  margin: 14px 0;
  background: #f8fafc;
}

.story-block-list-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.story-block-list-header h3 {
  margin: 0;
  color: #374151;
  font-size: 16px;
  font-weight: 700;
}

.story-block-list-header p {
  margin: 3px 0 0;
  color: #6b7280;
  font-size: 12px;
}

.story-block-list-grid {
  display: grid;
  gap: 10px;
}
</style>
