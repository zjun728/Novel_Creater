<script setup>
import {
  NAlert,
  NButton,
  NCard,
  NModal,
  NSpace,
} from 'naive-ui'
import { computed, ref } from 'vue'

const props = defineProps({
  source: { type: Object, required: true },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['archive', 'restore', 'delete'])
const confirmOpen = ref(false)

const deleteReasonText = computed(() => ({
  source_not_archived: '永久删除前必须先归档。',
  source_referenced: '当前或历史创作契约仍引用此来源。',
}[props.source.deleteReason] || '此来源当前不可永久删除。'))

function requestDelete() {
  if (props.source.deleteEligible) confirmOpen.value = true
}

function confirmDelete() {
  confirmOpen.value = false
  emit('delete')
}
</script>

<template>
  <section class="lifecycle" aria-label="语料生命周期">
    <n-space>
      <n-button
        v-if="source.state === 'active'"
        secondary
        :loading="busy"
        @click="emit('archive')"
      >
        归档来源
      </n-button>
      <n-button v-else secondary :loading="busy" @click="emit('restore')">
        恢复来源
      </n-button>
      <n-button
        v-if="source.state === 'archived'"
        :disabled="!source.deleteEligible || busy"
        @click="requestDelete"
      >
        永久删除
      </n-button>
    </n-space>
    <p v-if="source.state === 'archived' && !source.deleteEligible" class="delete-reason">
      {{ deleteReasonText }}
    </p>

    <n-modal v-model:show="confirmOpen">
      <n-card class="danger-card" :bordered="false" role="alertdialog" aria-modal="true">
        <h3>永久删除这份语料？</h3>
        <n-alert type="warning">
          该操作会删除来源、全部版本、章节与片段记录，且不能撤销。
        </n-alert>
        <p>受管内容仅在引用计数为零时允许删除；系统会在服务端再次校验。</p>
        <div>
          <n-button @click="confirmOpen = false">保留</n-button>
          <n-button type="error" @click="confirmDelete">确认永久删除</n-button>
        </div>
      </n-card>
    </n-modal>
  </section>
</template>

<style scoped>
.lifecycle { display: grid; gap: 8px; }
.delete-reason { margin: 0; color: #8b6b55; font-size: 11px; line-height: 1.6; }
.danger-card { width: min(500px, calc(100vw - 28px)); background: #fffaf5; }
.danger-card h3 { margin: 0 0 14px; font: 650 22px 'Noto Serif SC', 'Songti SC', serif; }
.danger-card p { color: #74685c; font-size: 12px; line-height: 1.7; }
.danger-card > div:last-child { display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px; }
</style>
