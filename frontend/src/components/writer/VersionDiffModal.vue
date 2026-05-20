<script setup>
import { computed, ref, watch } from 'vue'
import { NModal, NButton, NCard, NEmpty, NSelect, NSpace, NTag } from 'naive-ui'

const props = defineProps({
  versions: { type: Array, default: () => [] }
})

const emit = defineEmits(['close', 'load-version'])

const baseVersionId = ref('')
const targetVersionId = ref('')

const versionOptions = computed(() =>
  props.versions.map(version => ({
    label: `${versionTypeLabel(version)} · ${version.title || version.promptBrief || version.id}`,
    value: version.id
  }))
)

const baseVersion = computed(() => props.versions.find(version => version.id === baseVersionId.value) || null)
const targetVersion = computed(() => props.versions.find(version => version.id === targetVersionId.value) || null)

const diff = computed(() => buildParagraphDiff(baseVersion.value?.content || '', targetVersion.value?.content || ''))

watch(
  () => props.versions,
  versions => {
    if (!versions.length) return
    if (!baseVersionId.value) {
      const finalVersion = versions.find(version => version.versionType === 'final')
      baseVersionId.value = finalVersion?.id || versions[0]?.id || ''
    }
    if (!targetVersionId.value) {
      const correctionVersion = versions.find(version => version.versionType === 'correction_candidate')
      targetVersionId.value = correctionVersion?.id || versions.find(version => version.id !== baseVersionId.value)?.id || ''
    }
  },
  { immediate: true }
)

function versionTypeLabel(version) {
  const labels = {
    ai_candidate: 'AI 候选',
    correction_candidate: '纠偏候选',
    user_draft: '用户草稿',
    polished: '润色版',
    final: '定稿',
    archived: '存档'
  }
  return labels[version?.versionType] || version?.versionType || '版本'
}

function splitParagraphs(text) {
  return String(text || '')
    .split(/\n\s*\n+/)
    .map(item => item.trim())
    .filter(Boolean)
}

function buildParagraphDiff(baseText, targetText) {
  const base = splitParagraphs(baseText)
  const target = splitParagraphs(targetText)
  const pairs = lcsPairs(base, target)
  const matchedBase = new Set(pairs.map(pair => pair[0]))
  const matchedTarget = new Set(pairs.map(pair => pair[1]))
  const removed = base.map((text, index) => ({ text, index })).filter(item => !matchedBase.has(item.index))
  const added = target.map((text, index) => ({ text, index })).filter(item => !matchedTarget.has(item.index))
  const unchanged = pairs.length
  const baseLength = baseText.length
  const targetLength = targetText.length

  return {
    baseParagraphs: base.length,
    targetParagraphs: target.length,
    unchanged,
    removed,
    added,
    removedCount: removed.length,
    addedCount: added.length,
    baseLength,
    targetLength,
    wordDelta: targetLength - baseLength,
    recommendation: buildRecommendation({ added, removed, baseLength, targetLength })
  }
}

function lcsPairs(a, b) {
  const rows = a.length + 1
  const cols = b.length + 1
  const dp = Array.from({ length: rows }, () => Array(cols).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = normalize(a[i]) === normalize(b[j])
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const pairs = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (normalize(a[i]) === normalize(b[j])) {
      pairs.push([i, j])
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      i++
    } else {
      j++
    }
  }
  return pairs
}

function normalize(text) {
  return String(text || '').replace(/\s+/g, '')
}

function buildRecommendation({ added, removed, baseLength, targetLength }) {
  const delta = targetLength - baseLength
  if (!baseLength && targetLength) return '这是一个新增版本，可直接阅读全文后决定是否采纳。'
  if (Math.abs(delta) < baseLength * 0.08 && added.length <= 3 && removed.length <= 3) {
    return '改动幅度较小，适合重点检查新增/删除段落是否解决了纠偏问题。'
  }
  if (delta > baseLength * 0.2) return '目标版本明显扩写，建议检查节奏是否变慢，以及新增信息是否都服务于本章目标。'
  if (delta < -baseLength * 0.2) return '目标版本明显压缩，建议检查关键情绪、伏笔和因果链是否被删弱。'
  return '改动幅度中等，建议先看段落变化，再决定是否加载为当前稿继续编辑。'
}

function preview(text, max = 180) {
  if (!text) return ''
  return text.length > max ? text.slice(0, max) + '...' : text
}
</script>

<template>
  <n-modal
    :show="true"
    preset="card"
    title="版本差异对比"
    style="width: 920px; max-width: 92vw; max-height: 86vh;"
    @close="emit('close')"
  >
    <n-empty v-if="versions.length < 2" description="至少需要两个版本才能对比" />

    <div v-else class="space-y-4">
      <div class="grid grid-cols-2 gap-3">
        <label class="text-sm text-gray-600">
          <span class="block mb-1">基准版本</span>
          <n-select v-model:value="baseVersionId" :options="versionOptions" size="small" />
        </label>
        <label class="text-sm text-gray-600">
          <span class="block mb-1">对比版本</span>
          <n-select v-model:value="targetVersionId" :options="versionOptions" size="small" />
        </label>
      </div>

      <n-card size="small" title="差异摘要">
        <div class="grid grid-cols-2 md:grid-cols-5 gap-2 text-sm">
          <div><span class="text-gray-400">字数变化：</span>{{ diff.wordDelta > 0 ? '+' : '' }}{{ diff.wordDelta }}</div>
          <div><span class="text-gray-400">新增段落：</span>{{ diff.addedCount }}</div>
          <div><span class="text-gray-400">删除段落：</span>{{ diff.removedCount }}</div>
          <div><span class="text-gray-400">保留段落：</span>{{ diff.unchanged }}</div>
          <div><span class="text-gray-400">目标段落：</span>{{ diff.targetParagraphs }}</div>
        </div>
        <p class="text-sm text-blue-700 bg-blue-50 border border-blue-100 rounded px-3 py-2 mt-3">
          {{ diff.recommendation }}
        </p>
      </n-card>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
        <n-card size="small" title="删除或改写较大的段落">
          <n-empty v-if="!diff.removed.length" description="没有明显删除段落" size="small" />
          <div v-else class="space-y-2 max-h-72 overflow-y-auto">
            <div v-for="item in diff.removed.slice(0, 12)" :key="`removed-${item.index}`" class="rounded border border-red-100 bg-red-50 p-2 text-xs text-gray-700 leading-5">
              <n-tag size="tiny" type="error" :bordered="false">原文段落 {{ item.index + 1 }}</n-tag>
              <p class="mt-1 whitespace-pre-wrap">{{ preview(item.text) }}</p>
            </div>
          </div>
        </n-card>

        <n-card size="small" title="新增或改写后的段落">
          <n-empty v-if="!diff.added.length" description="没有明显新增段落" size="small" />
          <div v-else class="space-y-2 max-h-72 overflow-y-auto">
            <div v-for="item in diff.added.slice(0, 12)" :key="`added-${item.index}`" class="rounded border border-green-100 bg-green-50 p-2 text-xs text-gray-700 leading-5">
              <n-tag size="tiny" type="success" :bordered="false">新版段落 {{ item.index + 1 }}</n-tag>
              <p class="mt-1 whitespace-pre-wrap">{{ preview(item.text) }}</p>
            </div>
          </div>
        </n-card>
      </div>

      <div class="flex justify-end">
        <n-space>
          <n-button @click="targetVersion && emit('load-version', targetVersion)">加载对比版本到编辑器</n-button>
          <n-button type="primary" @click="emit('close')">关闭</n-button>
        </n-space>
      </div>
    </div>
  </n-modal>
</template>
