<script setup>
import { computed, ref } from 'vue'
import { NTag, NSelect, NPopover } from 'naive-ui'

const props = defineProps({
  characters: { type: Array, default: () => [] },
  chapters: { type: Array, default: () => [] },
  canonFacts: { type: Array, default: () => [] }
})

const filterCharId = ref(null)

const filteredCharacters = computed(() => {
  if (filterCharId.value) {
    return props.characters.filter(c => c.id === filterCharId.value)
  }
  return props.characters
})

const charOptions = computed(() =>
  props.characters.map(c => ({ label: c.name, value: c.id }))
)

function charChapterInfo(character, chapter) {
  const facts = props.canonFacts.filter(
    f => f.chapterNum === chapter.chapterNum && f.relatedCharacters?.includes(character.id)
  )
  const hardChanged = character.hardState?.lastUpdatedChapter === chapter.chapterNum
  const softChanged = character.softState?.lastUpdatedChapter === chapter.chapterNum
  return { facts, hardChanged, softChanged }
}

function getCellClass(character, chapter) {
  const info = charChapterInfo(character, chapter)
  if (info.hardChanged && info.softChanged) return 'bg-purple-400'
  if (info.hardChanged) return 'bg-blue-400'
  if (info.softChanged) return 'bg-orange-400'
  if (info.facts.length > 0) return 'bg-green-300'
  return 'bg-gray-100'
}

function getCellTitle(character, chapter) {
  const info = charChapterInfo(character, chapter)
  const parts = []
  if (info.hardChanged) parts.push('硬状态变更')
  if (info.softChanged) parts.push('软状态变更')
  if (info.facts.length) parts.push(`${info.facts.length} 条事实`)
  return parts.length ? `${character.name} · 第${chapter.chapterNum}章：${parts.join('、')}` : ''
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-lg font-semibold text-gray-700">人物弧光时间线</h3>
      <n-select
        v-model:value="filterCharId"
        placeholder="全部角色"
        size="tiny"
        style="width: 160px"
        :options="[{ label: '全部角色', value: null }, ...charOptions]"
        clearable
      />
    </div>

    <div v-if="!characters.length" class="text-center text-gray-400 text-sm py-8">
      暂无角色数据
    </div>

    <div v-else-if="!chapters.length" class="text-center text-gray-400 text-sm py-8">
      暂无章节数据
    </div>

    <div v-else class="overflow-x-auto">
      <div class="inline-block min-w-full">
        <!-- 图例 -->
        <div class="flex items-center gap-3 mb-2 text-xs text-gray-400">
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-blue-400 inline-block" /> 硬状态</span>
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-orange-400 inline-block" /> 软状态</span>
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-purple-400 inline-block" /> 双重变更</span>
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-green-300 inline-block" /> 有事实</span>
          <span class="flex items-center gap-1"><span class="w-3 h-3 rounded bg-gray-100 inline-block" /> 未出现</span>
        </div>

        <!-- 时间线表格 -->
        <div
          :style="{
            display: 'grid',
            gridTemplateColumns: `80px repeat(${chapters.length}, 24px)`,
            gap: '2px',
            alignItems: 'center'
          }"
        >
          <!-- 表头：章节号 -->
          <div class="text-xs text-gray-400 font-medium pr-2 truncate">角色</div>
          <div
            v-for="ch in chapters"
            :key="ch.id"
            class="text-center text-[10px] text-gray-400"
            :title="`第${ch.chapterNum}章 ${ch.title || ''}`"
          >
            {{ ch.chapterNum }}
          </div>

          <!-- 每个角色一行 -->
          <template v-for="char in filteredCharacters" :key="char.id">
            <div class="text-xs text-gray-700 pr-2 truncate font-medium">
              <n-tag size="tiny" :bordered="false">
                {{ char.name }}
              </n-tag>
            </div>
            <n-popover
              v-for="ch in chapters"
              :key="ch.id"
              :disabled="!getCellTitle(char, ch)"
            >
              <template #trigger>
                <div
                  :class="['w-6 h-6 rounded cursor-default', getCellClass(char, ch)]"
                  :title="getCellTitle(char, ch)"
                />
              </template>
              <div class="text-xs">{{ getCellTitle(char, ch) }}</div>
              <div v-if="charChapterInfo(char, ch).facts.length" class="mt-1">
                <div
                  v-for="(f, i) in charChapterInfo(char, ch).facts"
                  :key="i"
                  class="text-xs text-gray-500"
                >
                  {{ f.content?.slice(0, 80) }}{{ f.content?.length > 80 ? '...' : '' }}
                </div>
              </div>
            </n-popover>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>
