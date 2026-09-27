<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { NAlert, NButton, NEmpty, NSpin, NTag } from 'naive-ui'

import { projectSeedsPath, topicCandidatesPath, topicDirectionsPath } from '@/router/projectRoutes'
import { useTopicCenterStore } from '@/stores/topicCenterStore'
import CreateProjectFromCandidateDialog from './CreateProjectFromCandidateDialog.vue'
import TopicRevisionEditor from './TopicRevisionEditor.vue'
import { createTopicRevision } from '../../application/topics/topicRevision.js'
import { api } from '../../api/db/client.js'

const props = defineProps({ compact: { type: Boolean, default: false } })
const emit = defineEmits(['continue-discussion'])
const topics = useTopicCenterStore()
const router = useRouter()
const status = ref('active')
const selectedVersion = ref(null)
const localError = ref('')
const archiveBusy = ref(false)
const dialogOpen = ref(false)
const revision = createTopicRevision({ api: api.topics })

function allowLeave() {
  if (revision.busy.value) return false
  if (revision.dirty.value && !window.confirm('修订尚未保存，确定离开并放弃这次修改吗？')) return false
  revision.cancel()
  return true
}
function beforeUnload(event) { if (revision.dirty.value || revision.busy.value) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(allowLeave)
onBeforeRouteUpdate(allowLeave)
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
function edit() { revision.begin('candidate', detail.value, version.value) }
function cancelEdit() { allowLeave() }
function chooseVersion(value) { if (allowLeave()) selectedVersion.value = value }
async function saveEdit(copy) {
  const saved = await revision.save({ copy })
  if (!saved) return
  localError.value = ''
  try { await topics.loadCandidates('active'); await topics.openCandidate(saved.candidateId) }
  catch { localError.value = '内容已保存，但列表刷新失败。请重新打开候选库核对。' }
}

const detail = computed(() => topics.activeCandidate)
const version = computed(() => detail.value?.versions?.find(item => item.version === selectedVersion.value)
  || detail.value?.versions?.[0] || null)
const fields = Object.freeze([
  ['title', '暂定书名'], ['genre', '题材'], ['logline', '一句话创意'],
  ['targetAudience', '目标读者'], ['protagonist', '主角'], ['desire', '核心欲望'],
  ['coreConflict', '核心冲突'], ['worldPressure', '世界压力'], ['openingHook', '开篇钩子'],
  ['differentiation', '差异化'], ['storyPromise', '故事承诺'],
  ['longFormPotential', '长篇发展空间'], ['marketBasis', '市场依据'],
])

watch(detail, value => { selectedVersion.value = value?.currentVersion || null })

async function setStatus(value) {
  if (!allowLeave()) return
  status.value = value
  topics.activeCandidate = null
  localError.value = ''
  try { await topics.loadCandidates(value) } catch (failure) {
    localError.value = failure?.message || '候选种子列表加载失败'
  }
}

async function open(item) {
  if (!allowLeave()) return
  localError.value = ''
  try { await topics.openCandidate(item.id) } catch (failure) {
    localError.value = failure?.message || '候选种子详情加载失败'
  }
}

function continueDiscussion() {
  if (!allowLeave()) return
  if (!detail.value || !version.value) return
  emit('continue-discussion', {
    kind: 'candidate', id: detail.value.id, version: version.value.version,
    contentHash: version.value.contentHash, title: version.value.payload.title,
    discussionId: version.value.discussionId, evidence: version.value.basis?.evidence || [],
  })
}

async function archive() {
  if (!allowLeave()) return
  if (!detail.value || archiveBusy.value) return
  archiveBusy.value = true
  localError.value = ''
  try { await topics.archiveCandidate(detail.value.id, detail.value.currentVersion) } catch (failure) {
    localError.value = failure?.message || '归档失败，请刷新候选版本后重试'
  } finally { archiveBusy.value = false }
}

async function projectCreated(result) {
  dialogOpen.value = false
  await router.push(projectSeedsPath(result.project.id))
}
</script>

<template>
  <section class="candidate-panel" :class="{ compact }" aria-labelledby="candidate-library-title">
    <header class="panel-heading" hidden>
      <div><p>CANDIDATE LIBRARY</p><h2>候选种子库</h2></div>
      <router-link v-if="compact" :to="topicCandidatesPath()">查看全部候选 →</router-link>
      <n-tag v-else :bordered="false">{{ topics.candidates.length }} 个候选</n-tag>
    </header>
    <p class="panel-intro" hidden>候选种子是项目创建前的正式版本库；它仍不等于项目种子，更不会在创建项目后自动确认。</p>
    <n-alert v-if="localError" type="error" aria-live="assertive">{{ localError }}</n-alert>

    <div v-if="compact" class="recent-grid">
      <article v-for="item in topics.candidates.slice(0, 3)" :key="item.id">
        <span>版本 {{ item.currentVersion }} · {{ item.current.payload.genre }}</span>
        <h3>{{ item.current.payload.title }}</h3><p>{{ item.current.payload.logline }}</p>
      </article>
      <n-empty v-if="!topics.candidates.length" description="讨论产生的候选种子会显示在这里。" />
    </div>

    <template v-else>
      <n-spin :show="topics.loading">
        <div class="candidate-layout">
          <div class="record-list" tabindex="0" aria-label="候选种子列表"><h2 id="candidate-library-title">候选种子 {{ topics.candidates.length }}</h2>      <div class="status-tabs" role="group" aria-label="候选种子状态">
        <button type="button" :aria-pressed="status === 'active'" @click="setStatus('active')">当前候选</button>
        <button type="button" :aria-pressed="status === 'archived'" @click="setStatus('archived')">归档记录</button>
      </div>

            <button v-for="item in topics.candidates" :key="item.id" type="button" :class="{ active: detail?.id === item.id }" @click="open(item)">
              <span>{{ item.current.payload.genre }} · 版本 {{ item.currentVersion }}</span><strong>{{ item.current.payload.title }}</strong><small>{{ item.current.payload.logline }}</small>
            </button>
            <n-empty v-if="!topics.candidates.length && !topics.loading" :description="status === 'active' ? '尚无候选种子。可从 AI 建议显式保存。' : '尚无归档候选。'" />
          </div>
          <article v-if="version" class="record-detail">
            <header>
              <div><span>{{ detail.status === 'archived' ? '已归档' : '当前候选' }} · 版本 {{ version.version }}</span><h3>{{ version.payload.title }}</h3></div>
              <div class="detail-actions">
                <n-button size="small" @click="continueDiscussion">继续讨论</n-button>
                <n-button v-if="detail.status === 'active'" size="small" type="warning" :loading="archiveBusy" @click="archive">归档</n-button>
                <n-button v-if="detail.status === 'active' && !revision.draft.value" size="small" @click="edit">手工修订</n-button>

              </div>
            </header>
            <TopicRevisionEditor :controller="revision" allow-copy @save="saveEdit" @cancel="cancelEdit" />
            <p v-if="revision.message.value && !revision.draft.value" role="status">{{ revision.message.value }}</p>
            <section v-if="!revision.draft.value" class="reading-summary"><h4>核心创意</h4><p>{{ version.payload.logline }}</p><h4>核心欲望与冲突</h4><p>{{ version.payload.desire }}</p><p>{{ version.payload.coreConflict }}</p><h4>故事承诺</h4><p>{{ version.payload.storyPromise }}</p></section>
            <details v-if="!revision.draft.value"><summary>完整种子与市场依据</summary><dl class="detail-fields">
              <div v-for="field in fields" :key="field[0]"><dt>{{ field[1] }}</dt><dd>{{ version.payload[field[0]] }}</dd></div>
            </dl></details>
            <section class="version-history" aria-label="候选种子版本历史">
              <h4>版本历史</h4>
              <button v-for="item in detail.versions" :key="item.id" type="button" :aria-pressed="item.version === version.version" @click="chooseVersion(item.version)">版本 {{ item.version }}<span>{{ item.payload.title }}</span></button>
            </section>
          </article>
          <n-empty v-else class="detail-empty" description="从左侧选择一个候选，查看完整种子内容。" />
        </div>
      </n-spin>
    </template>
    <footer v-if="!compact" class="topic-footer"><span>创建作品时复制这份候选，项目内仍需确认种子。</span><n-button @click="router.push(topicDirectionsPath())">返回方向</n-button><n-button type="primary" :disabled="!version || detail?.status !== 'active' || Boolean(revision.draft.value)" @click="dialogOpen = true">用此种子创建作品</n-button></footer>
    <CreateProjectFromCandidateDialog :show="dialogOpen" :candidate="detail" :version="version" @close="dialogOpen = false" @created="projectCreated" />
  </section>
</template>

<style scoped>
.candidate-layout .record-detail{max-height:none;overflow-y:visible}.record-list>button small,.detail-fields dd{overflow-wrap:anywhere}
.candidate-panel { min-width:0; padding:24px; border:1px solid #d8c9b5; background:rgba(255,253,248,.94); }
.panel-heading,.record-detail>header,.detail-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; }.panel-heading a{color:#8f3f31;font-size:12px;text-decoration:none}
.panel-heading p,.record-detail>header span,.recent-grid span { margin:0; color:#9a4938; font:750 9px Georgia,serif; letter-spacing:.13em; }.panel-heading h2{margin:5px 0 0;font:650 27px 'Noto Serif SC','Songti SC',serif}.panel-intro{margin:10px 0 18px;color:#786c5e;font-size:12px;line-height:1.7}
.status-tabs { display:flex; gap:7px; margin-bottom:12px; }.status-tabs button{padding:7px 13px;border:1px solid #cdbba2;color:#65594d;background:transparent;cursor:pointer}.status-tabs button[aria-pressed=true]{color:#fff;background:#8f3f31}
.candidate-layout { display:grid; grid-template-columns:minmax(250px,.38fr) minmax(0,1fr); min-height:620px; border:1px solid #e1d6c5; }.record-list{min-width:0;max-height:690px;overflow-y:auto;border-right:1px solid #e1d6c5;background:#f6efe3}.record-list:focus-visible{outline:2px solid #9a4938;outline-offset:2px}.record-list>button{display:grid;width:100%;gap:6px;padding:17px;border:0;border-bottom:1px solid #e1d6c5;text-align:left;color:#514940;background:transparent;cursor:pointer}.record-list>button.active{color:#8f3f31;background:#fffdf8;box-shadow:inset 3px 0 #9a4938}.record-list span,.record-list small{color:#887763;font-size:10px}.record-list strong{font:650 18px 'Noto Serif SC','Songti SC',serif}.record-list small{display:-webkit-box;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-height:1.5}
.record-detail{min-width:0;max-height:690px;overflow-y:auto;padding:24px}.record-detail h3{margin:6px 0 0;font:650 29px 'Noto Serif SC','Songti SC',serif}.detail-actions{justify-content:flex-end;flex-wrap:wrap}.detail-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin:24px 0;border:1px solid #e1d6c5}.detail-fields div{padding:14px;border-right:1px solid #e1d6c5;border-bottom:1px solid #e1d6c5}.detail-fields div:nth-child(2n){border-right:0}.detail-fields dt{color:#92775c;font-size:10px;font-weight:700}.detail-fields dd{margin:7px 0 0;white-space:pre-wrap;color:#403a34;font-size:12px;line-height:1.72}.version-history{padding-top:18px;border-top:1px solid #e1d6c5}.version-history h4{font:650 16px 'Noto Serif SC','Songti SC',serif}.version-history button{display:flex;width:100%;justify-content:space-between;gap:12px;padding:9px;border:0;border-bottom:1px solid #eee4d6;color:#62594e;background:transparent;cursor:pointer}.version-history button[aria-pressed=true]{color:#8f3f31;background:#fbf3e8}
.recent-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.recent-grid article{min-width:0;padding:15px;border:1px solid #e1d6c5;background:#fbf7ef}.recent-grid h3{margin:8px 0 5px;font:650 18px 'Noto Serif SC','Songti SC',serif}.recent-grid p{margin:0;color:#6f6458;font-size:11px;line-height:1.65}.detail-empty{align-self:center}
@media(max-width:720px){.candidate-panel{padding:16px}.candidate-layout{grid-template-columns:1fr}.record-list{max-height:none;overflow-y:visible;border-right:0;border-bottom:1px solid #e1d6c5}.record-detail{max-height:none;overflow-y:visible;padding:16px}.record-detail>header{align-items:flex-start;flex-direction:column}.detail-actions{justify-content:flex-start}.detail-fields,.recent-grid{grid-template-columns:1fr}.detail-fields div{border-right:0}}

.panel-heading[hidden],.panel-intro[hidden]{display:none}.library-panel,.candidate-panel{padding:0;border:0;background:none}.library-layout,.candidate-layout{gap:20px;border:0;grid-template-columns:300px minmax(0,1fr);height:calc(100dvh - 348px);min-height:380px}.library-layout{grid-template-columns:326px minmax(0,1fr)}.record-list{background:#fffefa;border:1px solid #ddd5c8;border-radius:6px;padding:18px 10px;max-height:none}.record-list h2{font-size:17px;font-weight:500;margin:0 8px 24px}.record-list>button{border:0;border-radius:10px;padding:16px;margin-bottom:10px}.record-list>button.active{background:#efe2d7;box-shadow:none}.record-list>button strong{font-size:19px}.library-layout .record-detail,.candidate-layout .record-detail{overflow-y:auto;max-height:100%;min-height:0;border:1px solid #ddd5c8;border-radius:6px;background:#fffefa;padding:26px 28px}.record-detail>header{align-items:flex-start}.record-detail h3{font-size:28px}.reading-summary h4{font:500 20px 'Noto Serif SC','Songti SC',serif;margin:28px 0 14px}.reading-summary p{font-size:15px;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere}.record-detail details{margin:24px 0;color:#6f685e}.record-detail summary{cursor:pointer}.detail-fields{border:0;grid-template-columns:1fr}.detail-fields div{border:0;padding:10px 0}.version-history{margin-top:20px}.topic-footer{position:fixed;bottom:0;left:224px;right:0;min-height:76px;padding:15px 36px;display:flex;align-items:center;gap:20px;border-top:1px solid #ddd5c8;background:#fffefa;z-index:10}.topic-footer>span{margin-right:auto;color:#6f685e;font-size:13px}.topic-footer :deep(.n-button){min-height:46px;min-width:160px;border-radius:10px}.topic-footer :deep(.n-button--primary-type){min-width:264px;background:#934735}.status-tabs{margin-bottom:12px}
@media(min-width:1120px) and (max-height:820px){.library-layout,.candidate-layout{height:calc(100dvh - 306px);min-height:350px;grid-template-columns:280px minmax(0,1fr)}.record-detail h3{font-size:26px}.reading-summary h4{margin:20px 0 10px}}
@media(max-width:1119px){.topic-footer{left:72px}}
@media(max-width:760px){.topic-footer{left:0;padding:12px}.topic-footer>span{display:none}.topic-footer :deep(.n-button){min-width:0;flex:1}.library-layout,.candidate-layout{height:auto;grid-template-columns:1fr}.record-detail{overflow-y:visible}}

.topic-footer :deep(.n-button--primary-type),.discussion-panel :deep(.n-button--primary-type),.direction-summary :deep(.n-button){--n-color:#934735!important;--n-color-hover:#803b2c!important;--n-color-pressed:#803b2c!important;--n-text-color:#fffefa!important;--n-text-color-hover:#fffefa!important;--n-text-color-pressed:#fffefa!important;--n-border:1px solid #934735!important;--n-border-hover:1px solid #934735!important;background:#934735;color:#fffefa}.record-list>button strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.record-list>button span{font-family:inherit;font-size:12px}.status-tabs{margin:0 8px 18px}.discussion-list strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.conversation-title strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.conversation-title span{flex-shrink:0}
</style>
