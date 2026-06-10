<script setup>
import { computed, ref } from 'vue'
import { useMessage } from 'naive-ui'
import localReport from '@/data/localWritingSampleReport.json'
import {
  approveWritingSampleStandard,
  normalizeWritingSampleReport,
  summarizeWritingSampleReport
} from '@/data/writingSampleReview'
import {
  loadCustomWritingStyleStandards,
  saveCustomWritingStyleStandard
} from '@/data/writingStyleStandards'

const STORAGE_KEY = 'novel_creator_reviewed_writing_standards'

const message = useMessage()
const report = computed(() => normalizeWritingSampleReport(localReport))
const summary = computed(() => summarizeWritingSampleReport(localReport))
const selectedIds = ref([])
const standardName = ref(localReport?.standardCandidate?.name || '本地真人样本写作标准')
const standardCategory = ref(localReport?.standardCandidate?.category || '本地样本 / 人工审核')
const approvedStandard = ref(null)
const officialStandards = ref(loadCustomWritingStyleStandards())

const selectedCount = computed(() => selectedIds.value.length)
const selectedAll = computed(() => selectedIds.value.length > 0 && selectedIds.value.length === report.value.cards.length)

function readSavedStandards() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function persistStandard(standard) {
  const saved = readSavedStandards()
  const next = [
    standard,
    ...saved.filter(item => item.id !== standard.id)
  ].slice(0, 20)
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next))
}

function toggleAll() {
  selectedIds.value = selectedAll.value ? [] : report.value.cards.map(card => card.id)
}

function handleApprove() {
  try {
    const standard = approveWritingSampleStandard(localReport, selectedIds.value, {
      id: `reviewed-local-sample-${Date.now()}`,
      name: standardName.value,
      category: standardCategory.value
    })
    approvedStandard.value = standard
    persistStandard(standard)
    message.success(`已合并 ${standard.sourceCardIds.length} 张样本卡为待审核标准候选`)
  } catch (error) {
    message.warning(error.message || '合并失败，请先选择样本卡')
  }
}

function handleConfirmOfficial() {
  if (!approvedStandard.value) {
    message.warning('请先合并生成待审核标准候选')
    return
  }
  try {
    const official = saveCustomWritingStyleStandard(approvedStandard.value)
    officialStandards.value = loadCustomWritingStyleStandards()
    message.success(`已加入正式标准库：${official.name}`)
  } catch (error) {
    message.error(error.message || '加入正式标准库失败')
  }
}

function copyApprovedJson() {
  if (!approvedStandard.value) return
  navigator.clipboard?.writeText(JSON.stringify(approvedStandard.value, null, 2))
  message.success('已复制标准候选 JSON')
}
</script>

<template>
  <n-card title="写作样本审核" size="small" class="mt-6">
    <template #header-extra>
      <n-tag type="success" size="small">本地离线报告</n-tag>
    </template>

    <div class="text-sm text-gray-500 mb-4 leading-6">
      从本地 <span class="font-mono">小说txt</span> 目录生成的写作指纹卡，只保留抽象写法方法，不包含小说原文长段。
      这些卡片必须经人工选择后，才能合并为待审核写作标准候选。
    </div>

    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
      <div class="border border-gray-100 rounded p-3">
        <div class="text-xs text-gray-400">来源文件</div>
        <div class="text-xl font-semibold text-gray-800">{{ summary.fileCount }}</div>
      </div>
      <div class="border border-gray-100 rounded p-3">
        <div class="text-xs text-gray-400">样本卡</div>
        <div class="text-xl font-semibold text-gray-800">{{ summary.cardCount }}</div>
      </div>
      <div class="border border-gray-100 rounded p-3">
        <div class="text-xs text-gray-400">可审核</div>
        <div class="text-xl font-semibold text-green-600">{{ summary.auditReadyCount }}</div>
      </div>
      <div class="border border-gray-100 rounded p-3">
        <div class="text-xs text-gray-400">已选择</div>
        <div class="text-xl font-semibold text-blue-600">{{ selectedCount }}</div>
      </div>
    </div>

    <div class="grid md:grid-cols-2 gap-3 mb-4">
      <n-input v-model:value="standardName" placeholder="标准候选名称" />
      <n-input v-model:value="standardCategory" placeholder="标准候选分类" />
    </div>

    <div class="flex items-center justify-between mb-3">
      <div class="text-sm text-gray-500">
        题材标签：
        <n-tag
          v-for="tag in summary.genreTags.slice(0, 8)"
          :key="tag"
          size="small"
          class="mr-1"
        >
          {{ tag }}
        </n-tag>
        <span v-if="!summary.genreTags.length">暂无</span>
      </div>
      <div class="flex gap-2">
        <n-button size="small" @click="toggleAll">
          {{ selectedAll ? '取消全选' : '全选样本卡' }}
        </n-button>
        <n-button type="primary" size="small" :disabled="!selectedCount" @click="handleApprove">
          合并为待审核标准
        </n-button>
      </div>
    </div>

    <div class="max-h-[420px] overflow-y-auto border border-gray-100 rounded">
      <n-checkbox-group v-model:value="selectedIds">
        <div
          v-for="card in report.cards"
          :key="card.id"
          class="p-3 border-b border-gray-100 last:border-b-0"
        >
          <div class="flex items-start gap-3">
            <n-checkbox :value="card.id" class="mt-1" />
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2 flex-wrap">
                <div class="font-semibold text-gray-800">{{ card.sourceTitle }}</div>
                <n-tag size="small" type="success">禁止复刻</n-tag>
                <n-tag v-if="card.metrics?.chapterCount" size="small">
                  约 {{ card.metrics.chapterCount }} 章
                </n-tag>
              </div>
              <div class="text-xs text-gray-500 mt-1 line-clamp-2">
                章节进入：{{ card.chapterEntry }}
              </div>
              <div class="text-xs text-gray-500 mt-1 line-clamp-2">
                对话方式：{{ card.dialogueMethod }}
              </div>
              <div class="text-xs text-gray-500 mt-1 line-clamp-2">
                语言节奏：{{ card.proseRhythm }}
              </div>
            </div>
          </div>
        </div>
      </n-checkbox-group>
    </div>

    <n-alert v-if="approvedStandard" type="success" class="mt-4" title="已生成待审核标准候选">
      <div class="text-sm leading-6">
        {{ approvedStandard.name }}，来源样本 {{ approvedStandard.sourceCardIds.length }} 张。
        当前只保存到浏览器本地审核池，点击确认后才会加入正式标准库。
      </div>
      <div class="flex gap-2 mt-2">
        <n-button size="small" @click="copyApprovedJson">复制候选 JSON</n-button>
        <n-button size="small" type="primary" @click="handleConfirmOfficial">确认加入正式标准库</n-button>
      </div>
    </n-alert>

    <div v-if="officialStandards.length" class="mt-4 border border-gray-100 rounded p-3">
      <div class="font-semibold text-gray-800 mb-2">已确认正式标准库</div>
      <div
        v-for="standard in officialStandards"
        :key="standard.id"
        class="text-sm text-gray-600 py-1 flex items-center gap-2"
      >
        <n-tag size="small" type="success">正式</n-tag>
        <span class="font-medium text-gray-800">{{ standard.name }}</span>
        <span class="text-xs text-gray-400">{{ standard.category }}</span>
      </div>
    </div>
  </n-card>
</template>
