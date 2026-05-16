<script setup>
import { ref, computed } from 'vue'
import { NButton, NCard, NTag, NSpace, NModal, NInput, NPopconfirm, NEmpty, NDivider } from 'naive-ui'
import { useNovelStore } from '@/stores/novelStore'

const novelStore = useNovelStore()

const editing = ref(false)
const editingFact = ref(null)
const editingContent = ref('')

const pendingFacts = computed(() =>
  novelStore.canonFacts.filter(f => f.status === 'pending_review')
)

const acceptedFacts = computed(() =>
  novelStore.canonFacts.filter(f => f.status === 'accepted')
)

const factTypeLabels = {
  world: '世界观',
  character: '角色',
  plot: '情节',
  relationship: '关系',
  timeline: '时间线',
  style: '风格'
}

const factTypeColors = {
  world: 'warning',
  character: 'info',
  plot: 'success',
  relationship: 'error',
  timeline: 'default',
  style: 'default'
}

function getConfidenceColor(conf) {
  if (conf >= 0.8) return 'success'
  if (conf >= 0.5) return 'warning'
  return 'error'
}

function getConfidenceLabel(conf) {
  if (conf >= 0.8) return '高'
  if (conf >= 0.5) return '中'
  return '低'
}

async function handleConfirm(fact) {
  await novelStore.confirmCanonFact(fact.id)
}

async function handleReject(fact) {
  await novelStore.rejectCanonFact(fact.id)
}

function startEdit(fact) {
  editingFact.value = fact
  editingContent.value = fact.content
  editing.value = true
}

async function handleSaveEdit() {
  if (editingFact.value && editingContent.value.trim()) {
    await novelStore.saveCanonFact({
      ...editingFact.value,
      content: editingContent.value.trim(),
      status: 'accepted'
    })
    editing.value = false
    editingFact.value = null
  }
}
</script>

<template>
  <div class="canon-review-panel">
    <div class="flex items-center justify-between mb-2">
      <h4 class="text-sm font-semibold text-gray-500">记忆变更待确认</h4>
      <n-tag v-if="pendingFacts.length > 0" type="warning" size="tiny" round>
        {{ pendingFacts.length }} 条
      </n-tag>
    </div>

    <n-empty
      v-if="pendingFacts.length === 0"
      description="暂无待确认的记忆变更"
      size="small"
      class="py-4"
    />

    <div class="space-y-2 max-h-96 overflow-y-auto">
      <div
        v-for="fact in pendingFacts"
        :key="fact.id"
        class="p-2 rounded border border-orange-200 bg-orange-50 text-xs"
      >
        <div class="flex items-center gap-1 mb-1">
          <n-tag
            :type="factTypeColors[fact.factType]"
            size="tiny"
            :bordered="false"
          >
            {{ factTypeLabels[fact.factType] || fact.factType }}
          </n-tag>
          <n-tag
            :type="getConfidenceColor(fact.confidence)"
            size="tiny"
            :bordered="false"
          >
            信心 {{ getConfidenceLabel(fact.confidence) }}
          </n-tag>
        </div>
        <p class="text-gray-700 mb-1">{{ fact.content }}</p>
        <div v-if="fact.evidence" class="text-gray-400 italic mb-1">
          "{{ fact.evidence }}"
        </div>
        <div v-if="fact.relatedCharacters?.length" class="text-gray-400 mb-1">
          角色：{{ fact.relatedCharacters.join('、') }}
        </div>
        <n-space justify="end" size="small">
          <n-button size="tiny" quaternary @click="startEdit(fact)">编辑</n-button>
          <n-popconfirm @positive-click="handleReject(fact)">
            <template #trigger>
              <n-button size="tiny" quaternary type="error">忽略</n-button>
            </template>
            确认忽略此条记忆？
          </n-popconfirm>
          <n-button size="tiny" type="primary" @click="handleConfirm(fact)">确认</n-button>
        </n-space>
      </div>
    </div>

    <!-- 已确认的记忆 -->
    <n-divider v-if="acceptedFacts.length > 0" style="margin: 12px 0" />
    <div v-if="acceptedFacts.length > 0">
      <h4 class="text-xs font-semibold text-gray-400 mb-2">
        已确认记忆（{{ acceptedFacts.length }} 条）
      </h4>
      <div class="space-y-1 max-h-48 overflow-y-auto">
        <div
          v-for="fact in acceptedFacts.slice(-20)"
          :key="fact.id"
          class="flex items-center gap-2 text-xs text-gray-500 py-0.5"
        >
          <n-tag :type="factTypeColors[fact.factType]" size="tiny" :bordered="false">
            {{ factTypeLabels[fact.factType] || fact.factType }}
          </n-tag>
          <span class="truncate flex-1">{{ fact.content }}</span>
        </div>
      </div>
    </div>

    <!-- 编辑弹窗 -->
    <n-modal v-model:show="editing" title="编辑记忆" preset="card" style="width: 480px">
      <n-input
        v-model:value="editingContent"
        type="textarea"
        rows="4"
        placeholder="修改事实描述..."
      />
      <template #footer>
        <n-space justify="end">
          <n-button @click="editing = false">取消</n-button>
          <n-button type="primary" @click="handleSaveEdit">保存并确认</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>
