<script setup>
import { computed } from 'vue'
import { NButton, NCard, NEmpty, NTag } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'

const props = defineProps({
  context: { type: Object, default: () => ({}) },
  mode: { type: String, default: 'chapter' },
  usedTokens: { type: Number, default: 0 },
  maxTokens: { type: Number, default: 0 }
})

const emit = defineEmits(['close', 'navigate'])
const message = useAppMessage()

const modeLabel = computed(() => {
  const labels = {
    chapter: '生成小纲/正文',
    planning: '续写/扩写',
    rewrite: '选区改写'
  }
  return labels[props.mode] || '写作任务'
})

const sections = computed(() => [
  {
    key: 'seed',
    title: '创作种子',
    value: props.context.seed || props.context.openingAnchor,
    type: 'object'
  },
  {
    key: 'premise',
    title: '作品定位',
    value: props.context.premise,
    type: 'text'
  },
  {
    key: 'chapterGoal',
    title: '本章目标',
    value: props.context.chapterGoal,
    type: 'object'
  },
  {
    key: 'volumeStage',
    title: '当前分卷上下文',
    value: props.context.volumeStage,
    type: 'object'
  },
  {
    key: 'settingLibrary',
    title: '设定库摘要',
    value: props.context.settingLibrary,
    type: 'text'
  },
  {
    key: 'recentSettingChanges',
    title: '最近设定变更',
    value: props.context.recentSettingChanges,
    type: 'text'
  },
  {
    key: 'activeCorrectionTasks',
    title: '未完成纠偏任务',
    value: props.context.activeCorrectionTasks,
    type: 'text'
  },
  {
    key: 'recentFacts',
    title: '最近 Canon 事实',
    value: props.context.recentFacts,
    type: 'text'
  },
  {
    key: 'plotThreads',
    title: '进行中的伏笔',
    value: props.context.plotThreads,
    type: 'text'
  },
  {
    key: 'styleBible',
    title: '风格要求',
    value: props.context.styleBible,
    type: 'text'
  },
  {
    key: 'forbiddenDirections',
    title: '禁止方向',
    value: props.context.forbiddenDirections,
    type: 'object'
  },
  {
    key: 'sequenceRules',
    title: '正文顺序规则',
    value: props.context.sequenceRules,
    type: 'object'
  },
  {
    key: 'currentDraft',
    title: '当前草稿片段',
    value: props.context.currentDraft,
    type: 'text'
  }
].filter(section => hasValue(section.value)))

const missingSections = computed(() => [
  { key: 'seed', label: '创作种子', targetTab: 'seed' },
  { key: 'premise', label: '作品定位', targetTab: 'bible' },
  { key: 'chapterGoal', label: '本章目标', targetTab: 'chapters' },
  { key: 'volumeStage', label: '分卷上下文', targetTab: 'chapters' },
  { key: 'settingLibrary', label: '设定库摘要', targetTab: 'settingsLibrary' },
  { key: 'activeCorrectionTasks', label: '纠偏任务', targetTab: 'corrections' }
].filter(item => !hasValue(props.context[item.key])))

function hasValue(value) {
  if (value == null) return false
  if (Array.isArray(value)) return value.length > 0
  if (typeof value === 'object') return Object.keys(value).length > 0
  return String(value).trim().length > 0
}

function renderValue(value) {
  if (value == null) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value, null, 2)
}

function tokenText() {
  if (!props.maxTokens) return ''
  return `${props.usedTokens || 0} / ${props.maxTokens}`
}

function buildCopyText(section = null) {
  if (section) {
    return `## ${section.title}\n\n${renderValue(section.value)}`
  }
  return sections.value
    .map(item => `## ${item.title}\n\n${renderValue(item.value)}`)
    .join('\n\n---\n\n')
}

async function copyText(text, successText) {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
    } else {
      const textarea = document.createElement('textarea')
      textarea.value = text
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      document.execCommand('copy')
      document.body.removeChild(textarea)
    }
    message.success(successText)
  } catch (e) {
    message.error('复制失败：' + e.message)
  }
}
</script>

<template>
  <div class="context-preview-mask">
    <section class="context-preview-modal">
      <header class="modal-head">
        <div>
          <h3>AI 上下文预览</h3>
          <p>{{ modeLabel }}会读取的核心资料。这里是本地预览，实际请求仍会由具体 Prompt 组织。</p>
        </div>
        <n-button size="small" @click="emit('close')">关闭</n-button>
      </header>

      <div class="meta-row">
        <n-tag size="small" type="info" :bordered="false">{{ modeLabel }}</n-tag>
        <n-tag v-if="tokenText()" size="small" :bordered="false">Token 估算：{{ tokenText() }}</n-tag>
        <n-tag size="small" :bordered="false">已注入 {{ sections.length }} 类上下文</n-tag>
        <n-button size="tiny" :disabled="!sections.length" @click="copyText(buildCopyText(), '上下文已复制')">
          复制全部上下文
        </n-button>
      </div>

      <div v-if="missingSections.length" class="missing-box">
        <strong>缺失或未启用：</strong>
        <button
          v-for="item in missingSections"
          :key="item.key"
          type="button"
          @click="emit('navigate', item)"
        >
          {{ item.label }}
        </button>
      </div>

      <div v-if="sections.length" class="section-list">
        <n-card v-for="section in sections" :key="section.key" size="small" class="section-card">
          <template #header>
            <div class="section-title">
              <span>{{ section.title }}</span>
              <div class="section-actions">
                <n-button size="tiny" quaternary @click="copyText(buildCopyText(section), `${section.title}已复制`)">
                  复制
                </n-button>
                <n-tag size="tiny" :bordered="false">{{ section.key }}</n-tag>
              </div>
            </div>
          </template>
          <pre>{{ renderValue(section.value) }}</pre>
        </n-card>
      </div>

      <n-empty v-else description="暂无可预览上下文" class="py-8" />
    </section>
  </div>
</template>

<style scoped>
.context-preview-mask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: grid;
  place-items: center;
  background: rgba(15, 23, 42, 0.48);
  padding: 24px;
}

.context-preview-modal {
  width: min(920px, calc(100vw - 48px));
  max-height: min(860px, calc(100vh - 48px));
  overflow: hidden;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 24px 80px rgba(15, 23, 42, 0.24);
  display: flex;
  flex-direction: column;
}

.modal-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 12px;
  border-bottom: 1px solid #edf0f2;
}

.modal-head h3 {
  margin: 0;
  color: #1f2937;
  font-size: 20px;
  font-weight: 750;
}

.modal-head p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 12px 20px;
}

.missing-box {
  margin: 0 20px 12px;
  border: 1px solid #fde68a;
  border-radius: 6px;
  background: #fffbeb;
  padding: 10px 12px;
  color: #92400e;
  font-size: 13px;
}

.missing-box button {
  display: inline-block;
  margin-left: 8px;
  color: #2563eb;
  cursor: pointer;
  text-decoration: underline;
  background: transparent;
  border: 0;
  padding: 0;
}

.section-list {
  display: grid;
  gap: 12px;
  overflow-y: auto;
  padding: 0 20px 20px;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: #1f2937;
  font-size: 14px;
  font-weight: 700;
}

.section-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.section-card pre {
  max-height: 260px;
  overflow: auto;
  margin: 0;
  color: #334155;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
