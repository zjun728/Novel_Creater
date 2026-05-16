<script setup>
import { computed } from 'vue'
import { NTag, NEmpty, NDivider } from 'naive-ui'
import { useNovelStore } from '@/stores/novelStore'

const novelStore = useNovelStore()

const activePlotThreads = computed(() =>
  (novelStore.plotThreads || []).filter(t => t.status === 'planted' || t.status === 'developing')
)

const recentSummaries = computed(() =>
  (novelStore.canonFacts || [])
    .filter(f => f.status === 'accepted')
    .slice(-15)
)

const mainCharacters = computed(() =>
  (novelStore.characters || []).filter(c =>
    c.role === 'protagonist' || c.role === 'antagonist'
  )
)

// Group facts by type
const factsByType = computed(() => {
  const map = {}
  for (const f of recentSummaries.value) {
    if (!map[f.factType]) map[f.factType] = []
    map[f.factType].push(f)
  }
  return map
})
</script>

<template>
  <div class="context-memory-panel">
    <h4 class="text-sm font-semibold text-gray-500 mb-2">上下文记忆</h4>

    <!-- 角色硬状态速览 -->
    <div v-if="mainCharacters.length > 0" class="mb-3">
      <h5 class="text-xs font-medium text-gray-400 mb-1">主要角色</h5>
      <div v-for="c in mainCharacters" :key="c.id" class="text-xs py-1">
        <div class="flex items-center gap-1 mb-0.5">
          <n-tag size="tiny" :bordered="false" :type="c.role === 'protagonist' ? 'info' : 'error'">
            {{ c.role === 'protagonist' ? '主角' : '反派' }}
          </n-tag>
          <span class="font-medium text-gray-700">{{ c.name }}</span>
        </div>
        <div class="text-gray-500 space-y-0.5 ml-1">
          <div v-if="c.hardState?.location">
            位置：{{ c.hardState.location }}
          </div>
          <div v-if="c.hardState?.physicalStatus">
            状态：{{ c.hardState.physicalStatus }}
          </div>
          <div v-if="c.softState?.emotion">
            情绪：{{ c.softState.emotion }}
          </div>
          <div v-if="c.softState?.currentDesire">
            当前欲望：{{ c.softState.currentDesire }}
          </div>
        </div>
      </div>
    </div>

    <n-divider v-if="mainCharacters.length > 0" style="margin: 8px 0" />

    <!-- 进行中的伏笔 -->
    <div v-if="activePlotThreads.length > 0" class="mb-3">
      <h5 class="text-xs font-medium text-gray-400 mb-1">
        进行中的伏笔（{{ activePlotThreads.length }}）
      </h5>
      <div v-for="t in activePlotThreads" :key="t.id" class="text-xs py-0.5">
        <span class="text-gray-700">{{ t.title }}</span>
        <n-tag size="tiny" :bordered="false" class="ml-1">
          {{ t.status === 'planted' ? '已埋设' : '推进中' }}
        </n-tag>
      </div>
    </div>

    <n-divider v-if="activePlotThreads.length > 0" style="margin: 8px 0" />

    <!-- 世界规则 -->
    <div v-if="novelStore.bible?.worldRules" class="mb-3">
      <h5 class="text-xs font-medium text-gray-400 mb-1">世界规则</h5>
      <p class="text-xs text-gray-600 line-clamp-3 whitespace-pre-wrap">
        {{ novelStore.bible.worldRules }}
      </p>
    </div>

    <n-divider v-if="novelStore.bible?.worldRules" style="margin: 8px 0" />

    <!-- 禁止方向 -->
    <div v-if="novelStore.bible?.forbiddenDirections?.length" class="mb-3">
      <h5 class="text-xs font-medium text-gray-400 mb-1">禁止方向</h5>
      <div class="flex flex-wrap gap-1">
        <n-tag v-for="d in novelStore.bible.forbiddenDirections" :key="d" size="tiny" type="error">
          {{ d }}
        </n-tag>
      </div>
    </div>

    <n-empty
      v-if="!mainCharacters.length && !activePlotThreads.length && !novelStore.bible?.worldRules"
      description="暂无上下文记忆，定稿章节后将自动提取"
      size="small"
      class="py-6"
    />
  </div>
</template>
