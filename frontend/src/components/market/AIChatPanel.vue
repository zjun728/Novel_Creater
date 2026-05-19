<script setup>
import { ref, watch, nextTick, onMounted } from 'vue'
import { NButton, NInput, NSpace, NTag, NSpin, NPopconfirm } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useMarketStore } from '@/stores/marketStore'

const props = defineProps({
  projectId: { type: String, required: true },
  items: { type: Array, default: () => [] }
})

const emit = defineEmits(['seed-created', 'seed-updated'])

const marketStore = useMarketStore()
const message = useAppMessage()

const inputText = ref('')
const chatContainer = ref(null)

watch(
  () => marketStore.chatMessages.length,
  async () => {
    await nextTick()
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight
    }
  }
)

watch(
  () => marketStore.chatDraft,
  (draft) => {
    if (draft) {
      inputText.value = draft
      marketStore.clearChatDraft()
    }
  }
)

onMounted(() => {
  marketStore.loadChatMessages(props.projectId)
})

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || marketStore.chatLoading) return
  inputText.value = ''

  try {
    const result = await marketStore.sendChatMessage(props.projectId, text)
    if (result?.seeds?.length) {
      if (result.seedAction === 'updated') {
        emit('seed-updated', { seeds: result.seeds })
      } else {
        emit('seed-created', { seeds: result.seeds })
      }
    }
    if (result?.seedError) {
      message.warning(result.seedError)
    }
  } catch (e) {
    message.error('发送失败：' + e.message)
  }
}

async function generateNewSeed() {
  if (marketStore.chatLoading) return
  inputText.value = '请基于当前选题雷达数据和我们刚才的讨论，生成 1 个新的完整创作种子，并保存为候选种子。要求回复末尾必须输出完整 JSON 数组。'
  await sendMessage()
}

function handleKeyDown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

async function clearChat() {
  try {
    await marketStore.clearChat(props.projectId)
    message.success('对话记录已清空')
  } catch (e) {
    message.error('清空失败：' + e.message)
  }
}

function getRoleLabel(role) {
  if (role === 'user') return '我'
  return 'AI 顾问'
}
</script>

<template>
  <div class="chat-panel flex flex-col h-full bg-white">
    <!-- 顶部 -->
    <div class="flex items-center justify-between px-3 py-2 border-b bg-gray-50">
      <div class="flex items-center gap-1.5">
        <span class="text-sm font-semibold text-gray-700">AI 选题顾问</span>
        <n-tag v-if="marketStore.chatLoading" size="tiny" type="info" :bordered="false">
          思考中...
        </n-tag>
      </div>
      <n-popconfirm @positive-click="clearChat">
        <template #trigger>
          <n-button size="tiny" quaternary>清空对话</n-button>
        </template>
        确定清空当前对话记录？种子不会丢失。
      </n-popconfirm>
    </div>

    <!-- 消息列表 -->
    <div ref="chatContainer" class="flex-1 overflow-y-auto p-3 space-y-3">
      <div v-if="marketStore.chatMessages.length === 0" class="text-center text-gray-400 text-xs py-8">
        <p>👋 你好！我是你的 AI 选题顾问。</p>
        <p class="mt-1">输入你的想法、偏好或问题，</p>
        <p>我会结合市场趋势给你建议。</p>
        <p class="mt-2 text-gray-300">例如：</p>
        <p class="text-gray-300">"分析一下当前玄幻市场的趋势"</p>
        <p class="text-gray-300">"结合这些热门题材，给我3个创作种子"</p>
        <p class="text-gray-300">"我想写都市异能，有什么建议？"</p>
      </div>

      <div
        v-for="(msg, idx) in marketStore.chatMessages"
        :key="idx"
        :class="[
          'flex',
          msg.role === 'user' ? 'justify-end' : 'justify-start'
        ]"
      >
        <div
          :class="[
            'max-w-[85%] rounded-lg px-3 py-2 text-xs leading-relaxed',
            msg.role === 'user'
              ? 'bg-blue-500 text-white'
              : 'bg-gray-100 text-gray-800'
          ]"
        >
          <div class="text-[10px] opacity-60 mb-0.5">
            {{ getRoleLabel(msg.role) }}
          </div>
          <div class="whitespace-pre-wrap">{{ msg.content }}</div>

          <!-- 种子结果 -->
          <div v-if="msg.seeds?.length" class="mt-3 border-t border-gray-300 pt-2">
            <p class="text-[10px] font-semibold text-green-600 mb-1">
              {{ msg.seedAction === 'updated' ? '已更新当前创作种子 →' : `已生成 ${msg.seeds.length} 个创作种子 →` }}
            </p>
          </div>
          <div v-if="msg.seedError" class="mt-3 border-t border-gray-300 pt-2">
            <p class="text-[10px] font-semibold text-red-500">
              {{ msg.seedError }}
            </p>
          </div>
        </div>
      </div>

      <div v-if="marketStore.chatLoading" class="flex justify-start">
        <div class="bg-gray-100 rounded-lg px-4 py-2">
          <n-spin size="small" />
        </div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="border-t p-2 bg-gray-50">
      <div class="flex gap-1">
        <n-input
          v-model:value="inputText"
          type="textarea"
          :rows="2"
          placeholder="输入你的想法..."
          :disabled="marketStore.chatLoading"
          @keydown="handleKeyDown"
          size="small"
        />
      </div>
      <div class="flex justify-between items-center mt-1">
        <span class="text-[10px] text-gray-300">Enter 发送 / Shift+Enter 换行</span>
        <div class="flex items-center gap-1">
          <n-button
            size="tiny"
            secondary
            :disabled="marketStore.chatLoading"
            @click="generateNewSeed"
          >
            生成新种子
          </n-button>
          <n-button
            size="tiny"
            type="primary"
            :disabled="!inputText.trim() || marketStore.chatLoading"
            :loading="marketStore.chatLoading"
            @click="sendMessage"
          >
            发送
          </n-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-panel {
  min-height: 400px;
  max-height: calc(100vh - 260px);
}
</style>

