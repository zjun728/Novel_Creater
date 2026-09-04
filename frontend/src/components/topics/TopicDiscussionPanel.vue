<script setup>
import { computed, ref } from 'vue'
import { NAlert, NButton, NEmpty, NSpin, NTag } from 'naive-ui'

import { useTopicCenterStore } from '@/stores/topicCenterStore'

const props = defineProps({
  evidence: { type: Array, default: () => [] },
  subject: { type: Object, default: null },
  compact: { type: Boolean, default: false },
})
const emit = defineEmits(['remove-evidence', 'clear-subject'])
const topics = useTopicCenterStore()
const discussionTitle = ref('')
const draft = ref('')
const localError = ref('')
const creating = ref(false)
const savingKey = ref('')
const savedKeys = ref([])

const detail = computed(() => topics.activeDiscussion)
const messages = computed(() => detail.value?.messages || [])
const suggestionRequests = computed(() => (detail.value?.requests || []).filter(request => (
  request.status === 'succeeded' && request.assistantMessageId && request.result
)))

function commandKey() {
  const bytes = new Uint8Array(32)
  globalThis.crypto.getRandomValues(bytes)
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
}

function evidencePayload() {
  return props.evidence.map(({ snapshotId, contentHash }) => ({ snapshotId, contentHash }))
}

async function createDiscussion() {
  const title = discussionTitle.value.trim()
  if (!title) return
  creating.value = true
  localError.value = ''
  try {
    await topics.createDiscussion(title)
    discussionTitle.value = ''
  } catch (failure) {
    localError.value = failure?.message || '讨论创建失败'
  } finally {
    creating.value = false
  }
}

async function openDiscussion(id) {
  localError.value = ''
  try { await topics.openDiscussion(id) } catch (failure) {
    localError.value = failure?.message || '讨论记录加载失败'
  }
}

async function send() {
  const content = draft.value.trim()
  const discussionId = detail.value?.discussion?.id
  if (!content || !discussionId || topics.sending) return
  localError.value = ''
  try {
    await topics.sendMessage(discussionId, {
      content,
      idempotencyKey: commandKey(),
      evidence: evidencePayload(),
      subject: props.subject ? {
        kind: props.subject.kind,
        id: props.subject.id,
        version: props.subject.version,
        contentHash: props.subject.contentHash,
      } : null,
    })
    draft.value = ''
  } catch (failure) {
    localError.value = failure?.message || 'AI 讨论暂时失败，输入内容已保留'
  }
}

async function saveSuggestion(kind, request, payload, index) {
  const discussionId = detail.value?.discussion?.id
  const key = `${request.id}:${kind}:${index}`
  if (!discussionId || savingKey.value) return
  savingKey.value = key
  localError.value = ''
  const data = {
    messageId: request.assistantMessageId,
    payload,
    evidence: (request.basis?.evidence || []).map(
      ({ snapshotId, contentHash }) => ({ snapshotId, contentHash }),
    ),
    idempotencyKey: commandKey(),
  }
  const requestSubject = request.basis?.subject
  if (requestSubject?.kind === kind) {
    data[`${kind}Id`] = requestSubject.id
    data.expectedVersion = requestSubject.version
  }
  try {
    if (kind === 'direction') await topics.saveDirection(discussionId, data)
    else await topics.saveCandidate(discussionId, data)
    savedKeys.value = [...savedKeys.value, key]
  } catch (failure) {
    localError.value = failure?.message || '保存失败，请核对当前版本后重试'
  } finally {
    savingKey.value = ''
  }
}
</script>

<template>
  <section class="discussion-panel" :class="{ compact }" aria-labelledby="discussion-panel-title">
    <header class="panel-heading">
      <div><p>IDEA CONVERSATION</p><h2 id="discussion-panel-title">AI 选题讨论</h2></div>
      <n-tag :bordered="false">显式保存</n-tag>
    </header>
    <p class="panel-intro">从空白想法开始，不依赖市场证据或既有方向。AI 的回复只是建议，不会自动进入正式库。</p>

    <n-alert v-if="localError" type="error" aria-live="assertive" class="panel-alert">{{ localError }}</n-alert>
    <div class="discussion-layout">
      <aside class="discussion-index" aria-label="讨论列表">
        <form class="new-discussion" @submit.prevent="createDiscussion">
          <label for="topic-discussion-title">新讨论标题</label>
          <input id="topic-discussion-title" v-model="discussionTitle" maxlength="300" placeholder="例如：东方玄幻里的县城秩序重建">
          <n-button attr-type="submit" size="small" :disabled="!discussionTitle.trim()" :loading="creating">开始讨论</n-button>
        </form>
        <div class="discussion-list" tabindex="0">
          <button
            v-for="item in topics.discussions"
            :key="item.id"
            type="button"
            :class="{ active: detail?.discussion?.id === item.id }"
            @click="openDiscussion(item.id)"
          >
            <strong>{{ item.title }}</strong><span>{{ item.status === 'active' ? '讨论中' : item.status }}</span>
          </button>
        </div>
      </aside>

      <div class="conversation">
        <template v-if="detail">
          <header class="conversation-title"><strong>{{ detail.discussion.title }}</strong><span>{{ messages.length }} 条消息</span></header>
          <div v-if="subject" class="subject-chip">
            <span>正在继续讨论：{{ subject.title }} · 版本 {{ subject.version }}</span>
            <button type="button" @click="emit('clear-subject')">移除上下文</button>
          </div>
          <div v-if="evidence.length" class="evidence-chips" aria-label="已附加市场证据">
            <span v-for="item in evidence" :key="item.snapshotId">
              {{ item.label || '市场快照' }}
              <button type="button" :aria-label="`移除证据 ${item.label || ''}`" @click="emit('remove-evidence', item.snapshotId)">移除证据</button>
            </span>
          </div>
          <div class="message-scroll" tabindex="0" aria-label="选题讨论消息">
            <article v-for="message in messages" :key="message.id" :class="`message ${message.role}`">
              <small>{{ message.role === 'user' ? '我' : 'AI 建议' }}</small><p>{{ message.content }}</p>
            </article>
            <n-empty v-if="!messages.length" description="写下你的想法，开始第一轮讨论。" />
            <template v-for="request in suggestionRequests" :key="request.id">
              <article v-for="(suggestion, index) in request.result.directionSuggestions" :key="`d:${index}`" class="suggestion">
                <small>方向建议</small><h3>{{ suggestion.title }}</h3><p>{{ suggestion.readerPromise }}</p>
                <n-button size="small" :disabled="savedKeys.includes(`${request.id}:direction:${index}`)" :loading="savingKey === `${request.id}:direction:${index}`" @click="saveSuggestion('direction', request, suggestion, index)">
                  {{ savedKeys.includes(`${request.id}:direction:${index}`) ? '已保存为方向' : '保存为方向' }}
                </n-button>
              </article>
              <article v-for="(suggestion, index) in request.result.candidateSuggestions" :key="`c:${index}`" class="suggestion candidate">
                <small>候选种子建议</small><h3>{{ suggestion.title }}</h3><p>{{ suggestion.logline }}</p>
                <n-button size="small" :disabled="savedKeys.includes(`${request.id}:candidate:${index}`)" :loading="savingKey === `${request.id}:candidate:${index}`" @click="saveSuggestion('candidate', request, suggestion, index)">
                  {{ savedKeys.includes(`${request.id}:candidate:${index}`) ? '已保存为候选种子' : '保存为候选种子' }}
                </n-button>
              </article>
            </template>
          </div>
          <div class="composer">
            <label for="topic-message">继续讨论</label>
            <textarea id="topic-message" v-model="draft" maxlength="20000" rows="4" placeholder="输入你的判断、限制或新想法……" @keydown.enter.exact.prevent="send" />
            <div><small>Enter 发送 · Shift + Enter 换行</small><n-button type="primary" :disabled="!draft.trim() || topics.sending" :loading="topics.sending" @click="send">发送给 AI</n-button></div>
            <p aria-live="polite">{{ topics.sending ? 'AI 正在分析你的想法，请稍候……' : '' }}</p>
          </div>
        </template>
        <n-empty v-else description="选择一个讨论，或从左侧创建新讨论。" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.discussion-panel { min-width:0; padding:22px; border:1px solid #d8c9b5; background:rgba(255,253,248,.94); }
.panel-heading,.conversation-title,.composer>div { display:flex; align-items:center; justify-content:space-between; gap:12px; }
.panel-heading p { margin:0; color:#9a4938; font:750 9px Georgia,serif; letter-spacing:.14em; }
.panel-heading h2 { margin:5px 0 0; font:650 25px 'Noto Serif SC','Songti SC',serif; }
.panel-intro { margin:11px 0 18px; color:#786c5e; font-size:12px; line-height:1.7; }.panel-alert{margin-bottom:12px}
.discussion-layout { display:grid; grid-template-columns:minmax(170px,.38fr) minmax(0,1fr); min-height:520px; border:1px solid #e1d6c5; }
.discussion-index { min-width:0; padding:13px; border-right:1px solid #e1d6c5; background:#f6efe3; }
.new-discussion { display:grid; gap:7px; }.new-discussion label,.composer label { color:#765f48; font-size:11px; font-weight:700; }
.new-discussion input,.composer textarea { min-width:0; border:1px solid #cfc0aa; padding:9px; color:#302923; background:#fffdf8; font:inherit; }
.discussion-list { display:grid; gap:6px; max-height:410px; margin-top:14px; overflow-y:auto; }
.discussion-list:focus-visible,.message-scroll:focus-visible { outline:2px solid #9a4938; outline-offset:2px; }
.discussion-list button { min-width:0; padding:10px; border:1px solid transparent; text-align:left; color:#5e5449; background:transparent; cursor:pointer; }
.discussion-list button.active { border-color:#c8b79f; background:#fffdf8; }.discussion-list strong,.discussion-list span{display:block;overflow:hidden;text-overflow:ellipsis}.discussion-list span{margin-top:3px;font-size:9px}
.conversation { display:grid; min-width:0; grid-template-rows:auto auto auto minmax(230px,1fr) auto; padding:16px; }
.conversation-title { padding-bottom:11px; border-bottom:1px solid #e1d6c5; }.conversation-title strong{font-family:'Noto Serif SC','Songti SC',serif}.conversation-title span{color:#8c7b68;font-size:10px}
.subject-chip,.evidence-chips>span { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.subject-chip { margin-top:10px; padding:8px 10px; color:#31553f; background:#edf2e9; font-size:11px; }
.subject-chip button,.evidence-chips button { border:0; color:#8f3f31; background:transparent; cursor:pointer; font-size:10px; }
.evidence-chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:10px; }.evidence-chips>span{padding:5px 8px;border:1px solid #d8c9b5;font-size:10px}
.message-scroll { min-height:0; max-height:520px; overflow-y:auto; padding:14px 5px 10px 0; scrollbar-gutter:stable; }
.message { max-width:86%; margin:0 0 10px; padding:11px 13px; border-left:2px solid #91765c; background:#f6efe3; }.message.user{margin-left:auto;border-color:#9a4938;background:#fbf3eb}.message small,.suggestion small{color:#9a4938;font:700 9px Georgia,serif;letter-spacing:.12em}.message p{margin:5px 0 0;white-space:pre-wrap;line-height:1.7}
.suggestion { margin:12px 0; padding:14px; border:1px solid #c9d3c6; background:#f3f6f0; }.suggestion.candidate{border-color:#d8c4ac;background:#fff8ed}.suggestion h3{margin:5px 0;font:650 17px 'Noto Serif SC','Songti SC',serif}.suggestion p{color:#695f54;font-size:11px;line-height:1.65}
.composer { display:grid; gap:7px; padding-top:13px; border-top:1px solid #e1d6c5; }.composer textarea{resize:vertical}.composer small{color:#8c7b68}.composer p{min-height:18px;margin:0;color:#48654f;font-size:10px}
.compact .discussion-layout { grid-template-columns:1fr; }.compact .discussion-index{border-right:0;border-bottom:1px solid #e1d6c5}.compact .discussion-list{max-height:150px}.compact .message-scroll{max-height:360px}
@media(max-width:720px){.discussion-panel{padding:16px}.discussion-layout{grid-template-columns:1fr}.discussion-index{border-right:0;border-bottom:1px solid #e1d6c5}.discussion-list{max-height:none;overflow-y:visible}.conversation{padding:12px}.message-scroll{max-height:none;overflow-y:visible}.composer>div{align-items:flex-start;flex-direction:column}.composer :deep(.n-button){width:100%}}
</style>
