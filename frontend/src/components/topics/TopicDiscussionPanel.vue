<script setup>
import { computed, ref, nextTick } from 'vue'
import { NAlert, NButton, NEmpty, NSpin, NTag } from 'naive-ui'

import { clearTopicContext } from '@/application/topics/topicContext'
import { enterBlankTopicDiscussion } from '@/application/topics/topicSuggestionController'
import { providerSettingsPath } from '@/router/projectRoutes'
import { useTopicCenterStore } from '@/stores/topicCenterStore'
import { TOPIC_FIELD_LABELS } from '../../application/topics/topicRevision.js'
import { topicSuggestionKey } from '../../application/topics/topicSuggestionKey.js'
import {
  clearTopicDraft,
  readTopicDraft,
  writeTopicDraft,
} from './topicDiscussionDraftSession'

const props = defineProps({
  evidence: { type: Array, default: () => [] },
  subject: { type: Object, default: null },
  compact: { type: Boolean, default: false },
})
const emit = defineEmits(['remove-evidence', 'clear-subject'])
const topics = useTopicCenterStore()
const discussionTitle = ref('')
const localError = ref('')
const saveNotice = ref('')
const creating = ref(false)
const blankDraft = computed({ get: () => readTopicDraft('blank-topic'), set: value => writeTopicDraft('blank-topic', value) })
const savingKey = ref('')
const savedKeys = computed({ get: () => topics.savedSuggestionKeys || [], set: value => { topics.savedSuggestionKeys = value } })

const detail = computed(() => topics.activeDiscussion)
const discussionId = computed(() => detail.value?.discussion?.id || '')
const draft = computed({
  get: () => (discussionId.value ? readTopicDraft(discussionId.value) : ''),
  set: value => {
    if (discussionId.value) writeTopicDraft(discussionId.value, value)
  },
})
const recommendation = computed(() => topics.discussionRecommendation?.discussionId === discussionId.value ? topics.discussionRecommendation : null)
const messages = computed(() => detail.value?.messages || [])
const suggestionRequests = computed(() => (detail.value?.requests || []).filter(request => (
  request.status === 'succeeded' && request.assistantMessageId && request.result
)).slice().reverse())
const sendFailure = computed(() => (
  topics.lastSendFailure?.discussionId === discussionId.value ? topics.lastSendFailure : null
))
const providerNotReady = computed(() => sendFailure.value?.code === 'TOPIC_PROVIDER_NOT_READY')
const sendFailureMessage = computed(
  () => (providerNotReady.value
    ? '默认模型尚未配置。请先完成配置，返回后可继续发送；当前输入已保留。'
    : ({
      TOPIC_PROVIDER_FAILED: '模型请求失败，输入已保留。请稍后重试；持续失败时可到设置检查模型连接。',
      TOPIC_INVALID_RESPONSE: '模型返回的内容不完整，输入已保留。请重试或补充更明确的要求。',
      TOPIC_OUTCOME_UNKNOWN: '发送结果暂未确认，输入已保留。请先重新打开本讨论核对回复，避免重复发送。',
    }[sendFailure.value?.code] || 'AI 讨论暂时失败，输入已保留。请核对讨论记录后再试。')),
)

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
    clearTopicContext(topics)
    await topics.createDiscussion(title)
    discussionTitle.value = ''
  } catch (failure) {
    localError.value = failure?.message || '讨论创建失败'
  } finally {
    creating.value = false
  }
}

async function sendBlankDiscussion() {
  const content = blankDraft.value.trim()
  if (!content || creating.value || topics.sending) return
  creating.value = true
  localError.value = ''
  try {
    const created = await topics.createDiscussion(content.slice(0, 40))
    clearTopicContext(topics)
    await nextTick()
    writeTopicDraft(created.discussion.id, content)
    blankDraft.value = ''
    await send()
  } catch (failure) { localError.value = failure?.message || '讨论创建失败，输入已保留' }
  finally { creating.value = false }
}

async function openDiscussion(id) {
  localError.value = ''
  try { await topics.openDiscussion(id); clearTopicContext(topics) } catch (failure) {
    localError.value = failure?.message || '讨论记录加载失败'
  }
}

async function send() {
  const draftSnapshot = draft.value
  const content = draftSnapshot.trim()
  const targetDiscussionId = discussionId.value
  if (!content || !targetDiscussionId || topics.sending) return
  localError.value = ''
  try {
    await topics.sendMessage(targetDiscussionId, {
      content: recommendation.value ? `${content}\n\n本次指定讨论的建议：${recommendation.value.title}` : content,
      idempotencyKey: commandKey(),
      evidence: evidencePayload(),
      subject: props.subject ? {
        kind: props.subject.kind,
        id: props.subject.id,
        version: props.subject.version,
        contentHash: props.subject.contentHash,
      } : null,
    })
    clearTopicDraft(targetDiscussionId, draftSnapshot)
    if (discussionId.value === targetDiscussionId) {
      try {
        await topics.openDiscussion(targetDiscussionId)
      } catch {
        if (discussionId.value === targetDiscussionId) {
          localError.value = '消息已经发送成功，但讨论记录刷新失败。请稍后重新打开本讨论查看回复。'
        }
      }
    }
  } catch {}
}

function clearSendFailure() {
  topics.clearSendFailure()
}

async function saveSuggestion(kind, request, payload, index) {
  const discussionId = detail.value?.discussion?.id
  const key = `${request.id}:${kind}:${index}`
  if (!discussionId || savingKey.value) return
  savingKey.value = key
  localError.value = ''
  saveNotice.value = ''
  const data = {
    messageId: request.assistantMessageId,
    payload,
    evidence: (request.basis?.evidence || []).map(
      ({ snapshotId, contentHash }) => ({ snapshotId, contentHash }),
    ),
  }
  const requestSubject = request.basis?.subject
  if (requestSubject?.kind === kind) {
    data[`${kind}Id`] = requestSubject.id
    data.expectedVersion = requestSubject.version
  }
  try {
    data.idempotencyKey = await topicSuggestionKey(discussionId, request.id, kind, index)
    if (kind === 'direction') await topics.saveDirection(discussionId, data)
    else await topics.saveCandidate(discussionId, data)
    savedKeys.value = [...savedKeys.value, key]
    saveNotice.value = kind === 'direction' ? '已保存，可在方向库查看。' : '已保存，可在候选种子库查看。'
  } catch (failure) {
    localError.value = failure?.message || '保存失败，请核对当前版本后重试'
  } finally {
    savingKey.value = ''
  }
}
</script>

<template>
  <section class="discussion-panel" :class="{ compact }" aria-labelledby="discussion-panel-title">
    <header class="panel-heading" hidden>
      <div><p>IDEA CONVERSATION</p><h2>AI 选题讨论</h2></div>
      <n-tag :bordered="false">显式保存</n-tag>
    </header>
    <p class="panel-intro" hidden>从空白想法开始，不依赖市场证据或既有方向。AI 的回复只是建议，不会自动进入正式库。</p>

    <n-alert v-if="localError" type="error" aria-live="assertive" class="panel-alert">{{ localError }}</n-alert>
    <n-alert v-if="saveNotice" type="success" aria-live="polite" class="panel-alert">{{ saveNotice }}</n-alert>
    <n-alert
      v-if="sendFailure"
      type="error"
      aria-live="assertive"
      class="panel-alert"
      closable
      @close="clearSendFailure"
    >
      {{ sendFailureMessage }}
      <router-link v-if="providerNotReady" :to="providerSettingsPath()">配置默认模型</router-link>
    </n-alert>
    <div class="discussion-layout">
      <aside class="discussion-index" aria-label="讨论列表">
        <h2 id="discussion-panel-title">讨论记录</h2>
        <n-button class="new-discussion-button" :disabled="topics.sending" @click="enterBlankTopicDiscussion(topics)">＋ 新讨论</n-button>
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
          <div v-if="recommendation" class="subject-chip"><span>围绕建议：{{ recommendation.title }}</span><button type="button" @click="topics.discussionRecommendation = null">移除建议上下文</button></div>
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

          </div>
          <div class="composer">
            <label for="topic-message">继续讨论</label>
            <textarea id="topic-message" v-model="draft" maxlength="20000" rows="4" placeholder="输入你的判断、限制或新想法……" @keydown.enter.exact.prevent="send" />
            <div><small>Enter 发送 · Shift + Enter 换行</small><n-button type="primary" :disabled="!draft.trim() || topics.sending" :loading="topics.sending" @click="send">发送给 AI</n-button></div>
            <p aria-live="polite">{{ topics.sending ? 'AI 正在分析你的想法，请稍候……' : '' }}</p>
          </div>
        </template>
        <div v-else class="blank-conversation">
          <h3>从你的想法开始</h3><p>这是一场空白讨论，不包含创作推荐或市场资料。</p>
          <label for="blank-topic-message">你的想法</label>
          <textarea id="blank-topic-message" v-model="blankDraft" rows="6" maxlength="20000" placeholder="写下你的灵感、人物或故事设想……" @keydown.enter.exact.prevent="sendBlankDiscussion" />
          <n-button type="primary" :disabled="!blankDraft.trim() || creating || topics.sending" :loading="creating" @click="sendBlankDiscussion">发送给 AI</n-button>
        </div>
      </div>
      <aside class="direction-summary" aria-label="方向摘要">
        <h2>方向摘要</h2><p v-if="!suggestionRequests.length" class="summary-empty">讨论后，这里会呈现可保存的方向与候选种子。</p>
            <template v-for="request in suggestionRequests" :key="request.id">
              <article v-for="(suggestion, index) in request.result.directionSuggestions" :key="`d:${index}`" class="suggestion">
                <small>待保存 · 方向建议</small><h3>{{ suggestion.title }}</h3><h4>故事张力</h4><p>{{ suggestion.readerPromise }}</p><h4>长篇空间</h4><p>{{ suggestion.longFormPotential }}</p>
                <details class="suggestion-details"><summary>查看完整方向</summary><dl><div v-for="(value, field) in suggestion" :key="field"><dt>{{ TOPIC_FIELD_LABELS[field] || '内容' }}</dt><dd>{{ value }}</dd></div></dl></details>
                <n-button size="small" :disabled="savedKeys.includes(`${request.id}:direction:${index}`)" :loading="savingKey === `${request.id}:direction:${index}`" @click="saveSuggestion('direction', request, suggestion, index)">
                  {{ savedKeys.includes(`${request.id}:direction:${index}`) ? '已保存为方向' : '保存为方向' }}
                </n-button>
              </article>
              <article v-for="(suggestion, index) in request.result.candidateSuggestions" :key="`c:${index}`" class="suggestion candidate">
                <small>候选种子建议</small><h3>{{ suggestion.title }}</h3><p>{{ suggestion.logline }}</p>
                <details class="suggestion-details"><summary>查看完整候选种子</summary><dl><div v-for="(value, field) in suggestion" :key="field"><dt>{{ TOPIC_FIELD_LABELS[field] || '内容' }}</dt><dd>{{ value }}</dd></div></dl></details>
                <n-button size="small" :disabled="savedKeys.includes(`${request.id}:candidate:${index}`)" :loading="savingKey === `${request.id}:candidate:${index}`" @click="saveSuggestion('candidate', request, suggestion, index)">
                  {{ savedKeys.includes(`${request.id}:candidate:${index}`) ? '已保存为候选种子' : '保存为候选种子' }}
                </n-button>
              </article>
            </template>
      </aside>
    </div>
    <footer class="topic-footer">先讨论，再保存方向；候选种子创建后才进入项目。</footer>
  </section>
</template>

<style scoped>
.blank-conversation{display:flex;flex-direction:column;gap:14px;align-self:start}.blank-conversation textarea{padding:14px;background:#fffefa;border:1px solid #ddd5c8;border-radius:6px;font:inherit}.blank-conversation p{color:#6f685e}.blank-conversation :deep(.n-button){align-self:flex-end}
.suggestion-details{margin:12px 0;font-size:13px}.suggestion-details summary{cursor:pointer;color:#8f3f31}.suggestion-details dl{display:grid;gap:12px}.suggestion-details dt{font-weight:600}.suggestion-details dd{margin:5px 0 0;white-space:pre-wrap;line-height:1.8;overflow-wrap:anywhere}
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

.discussion-panel{padding:0;border:0;background:none}.discussion-layout{grid-template-columns:216px minmax(0,1fr) 322px;gap:16px;border:0;height:calc(100dvh - 348px);min-height:400px}.discussion-index,.conversation,.direction-summary{border:1px solid #ddd5c8;border-radius:6px;background:#fffefa;min-height:0;padding:18px}.discussion-index{display:flex;flex-direction:column}.discussion-index h2,.direction-summary>h2{font-size:15px;font-weight:500;margin:0 0 16px}.new-discussion-button{width:100%;min-height:46px}.discussion-list{flex:1;max-height:none}.discussion-list button.active{background:#efe2d7;border:0;border-radius:10px}.conversation{display:flex;flex-direction:column;gap:10px;padding:20px}.message-scroll{flex:1;max-height:none;min-height:80px}.composer{flex-shrink:0}.composer textarea{max-height:120px}.message.assistant{max-width:100%;border:0;background:none;padding:10px 0}.message.user{border:0;border-radius:10px}.direction-summary{overflow-y:auto}.direction-summary .suggestion{border:0;border-bottom:1px solid #ddd5c8;border-radius:0;background:none;margin:0 0 18px;padding:0 0 18px}.direction-summary h3{font-size:23px}.direction-summary h4{font-size:16px;margin:16px 0 6px}.direction-summary p{font-size:14px}.direction-summary :deep(.n-button){width:100%;min-height:40px}.summary-empty{color:#6f685e;line-height:1.8}.blank-conversation{flex:1}.blank-conversation textarea{min-height:100px;max-height:220px}.topic-footer{position:fixed;bottom:0;left:224px;right:0;min-height:76px;padding:26px 36px;background:#fffefa;border-top:1px solid #ddd5c8;color:#6f685e;font-size:13px;z-index:10}
@media(min-width:1120px) and (max-height:820px){.discussion-layout{height:calc(100dvh - 296px);min-height:360px;grid-template-columns:190px minmax(0,1fr) 290px}.conversation{padding:14px}.composer textarea{max-height:85px}.composer p{min-height:0}.discussion-index,.direction-summary{padding:14px}}
@media(max-width:1119px){.discussion-layout{grid-template-columns:180px minmax(0,1fr);height:auto}.direction-summary{grid-column:1/-1}.topic-footer{left:72px}}
@media(max-width:760px){.discussion-layout{grid-template-columns:1fr}.topic-footer{left:0}.direction-summary{grid-column:auto}}
.panel-heading[hidden],.panel-intro[hidden]{display:none}
.topic-footer :deep(.n-button--primary-type),.discussion-panel :deep(.n-button--primary-type),.direction-summary :deep(.n-button){--n-color:#934735!important;--n-color-hover:#803b2c!important;--n-color-pressed:#803b2c!important;--n-text-color:#fffefa!important;--n-text-color-hover:#fffefa!important;--n-text-color-pressed:#fffefa!important;--n-border:1px solid #934735!important;--n-border-hover:1px solid #934735!important;background:#934735;color:#fffefa}.record-list>button strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.record-list>button span{font-family:inherit;font-size:12px}.status-tabs{margin:0 8px 18px}.discussion-list strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.conversation-title strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.conversation-title span{flex-shrink:0}
</style>
