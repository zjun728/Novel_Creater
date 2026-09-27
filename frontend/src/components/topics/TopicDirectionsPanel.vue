<script setup>
import { computed, ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { NAlert, NButton, NEmpty, NSpin, NTag } from 'naive-ui'

import { useTopicCenterStore } from '@/stores/topicCenterStore'
import TopicRevisionEditor from './TopicRevisionEditor.vue'
import { createTopicRevision } from '../../application/topics/topicRevision.js'
import { topicCandidatesPath } from '@/router/projectRoutes'
import { createDirectionCandidateController } from '@/application/topics/directionCandidate'
import { api } from '../../api/db/client.js'

const emit = defineEmits(['continue-discussion'])
const topics = useTopicCenterStore()
const router = useRouter()
const candidateGeneration = createDirectionCandidateController(topics)
const localError = ref('')
const selectedVersion = ref(null)
const revision = createTopicRevision({ api: api.topics })
function allowLeave() {
  if (revision.busy.value || candidateGeneration.state.busy) return false
  if (revision.dirty.value && !window.confirm('修订尚未保存，确定离开并放弃这次修改吗？')) return false
  revision.cancel()
  return true
}
function beforeUnload(event) { if (revision.dirty.value || revision.busy.value || candidateGeneration.state.busy) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(allowLeave)
onBeforeRouteUpdate(allowLeave)
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
function edit() { revision.begin('direction', detail.value, version.value) }
function chooseVersion(value) { if (allowLeave()) selectedVersion.value = value }
async function saveEdit() {
  const saved = await revision.save()
  if (!saved) return
  try { await topics.loadDirections(); await topics.openDirection(saved.directionId) }
  catch { localError.value = '内容已保存，但列表刷新失败。请重新打开方向库核对。' }
}

const detail = computed(() => topics.activeDirection)
const version = computed(() => detail.value?.versions?.find(item => item.version === selectedVersion.value)
  || detail.value?.versions?.[0] || null)
const fields = Object.freeze([
  ['genreOpportunity', '题材机会'], ['targetAudience', '目标读者'],
  ['readerPromise', '读者承诺'], ['differentiation', '差异化'],
  ['longFormPotential', '长篇发展空间'], ['risks', '风险'],
  ['evidenceSummary', '证据摘要'],
])

watch(detail, value => { selectedVersion.value = value?.currentVersion || null })

async function open(item) {
  if (!allowLeave()) return
  localError.value = ''
  try { await topics.openDirection(item.id) } catch (failure) {
    localError.value = failure?.message || '选题方向加载失败'
  }
}

function selectedSubject() {
  return { kind: 'direction', id: detail.value.id, version: version.value.version, contentHash: version.value.contentHash, title: version.value.payload.title, discussionId: version.value.discussionId, evidence: version.value.basis?.evidence || [] }
}
async function generateCandidate() {
  if (!detail.value || !version.value || !allowLeave()) return
  const receipt = await candidateGeneration.generate(selectedSubject())
  if (!receipt) return
  try { await topics.openCandidate(receipt.candidateId); await router.push(topicCandidatesPath()) }
  catch { localError.value = '候选已保存，请到候选种子页查看。' }
}
function continueDiscussion() {
  if (!allowLeave()) return
  if (!detail.value || !version.value) return
  emit('continue-discussion', {
    kind: 'direction', id: detail.value.id, version: version.value.version,
    contentHash: version.value.contentHash, title: version.value.payload.title,
    discussionId: version.value.discussionId, evidence: version.value.basis?.evidence || [],
  })
}
</script>

<template>
  <section class="library-panel" aria-labelledby="direction-library-title">
    <header class="panel-heading" hidden>
      <div><p>DIRECTION LIBRARY</p><h2>选题方向库</h2></div>
      <n-tag :bordered="false">{{ topics.directions.length }} 个方向</n-tag>
    </header>
    <p class="panel-intro" hidden>方向是可选的中间成果。它帮助你看清机会、读者和风险，但不会替你创建种子或项目。</p>
    <n-alert v-if="localError" type="error" aria-live="assertive">{{ localError }}</n-alert>
    <n-alert v-if="candidateGeneration.state.error" type="error" aria-live="assertive">{{ candidateGeneration.state.error }}</n-alert>
    <n-spin :show="topics.loading || candidateGeneration.state.busy">
      <div class="library-layout">
        <div class="record-list" tabindex="0" aria-label="选题方向列表"><h2 id="direction-library-title">我的方向 {{ topics.directions.length }}</h2>
          <button v-for="item in topics.directions" :key="item.id" type="button" :class="{ active: detail?.id === item.id }" @click="open(item)">
            <span>版本 {{ item.currentVersion }}</span><strong>{{ item.current.payload.title }}</strong><small>{{ item.current.payload.genreOpportunity }}</small>
          </button>
          <n-empty v-if="!topics.directions.length && !topics.loading" description="尚未保存选题方向。可在 AI 讨论中显式保存。" />
        </div>
        <article v-if="version" class="record-detail">
          <header><div><span>当前阅读版本 {{ version.version }}</span><h3>{{ version.payload.title }}</h3></div><div><n-button v-if="!revision.draft.value" size="small" @click="edit">手工修订</n-button></div></header>
          <TopicRevisionEditor :controller="revision" @save="saveEdit" @cancel="allowLeave" />
          <p v-if="revision.message.value && !revision.draft.value" role="status">{{ revision.message.value }}</p>
          <section v-if="!revision.draft.value" class="reading-summary"><h4>一句话方向</h4><p>{{ version.payload.readerPromise }}</p><h4>故事张力与差异化</h4><p>{{ version.payload.differentiation }}</p><h4>长篇空间</h4><p>{{ version.payload.longFormPotential }}</p><h4>仍需展开</h4><p>{{ version.payload.risks }}</p></section>
          <details v-if="!revision.draft.value"><summary>完整方向与市场依据</summary><dl class="detail-fields">
            <div v-for="field in fields" :key="field[0]"><dt>{{ field[1] }}</dt><dd>{{ version.payload[field[0]] }}</dd></div>
          </dl></details>
          <section class="version-history" aria-label="方向版本历史">
            <h4>版本历史</h4>
            <button v-for="item in detail.versions" :key="item.id" type="button" :aria-pressed="item.version === version.version" @click="chooseVersion(item.version)">版本 {{ item.version }}<span>{{ item.payload.title }}</span></button>
          </section>
        </article>
        <n-empty v-else class="detail-empty" description="从左侧选择一个方向，查看完整判断。" />
      </div>
    </n-spin>
    <footer class="topic-footer"><span>方向已保存，可继续讨论或展开为候选种子。</span><n-button :disabled="!version || candidateGeneration.state.busy" @click="continueDiscussion">继续讨论</n-button><n-button type="primary" :disabled="!version || candidateGeneration.state.uncertain" :loading="candidateGeneration.state.busy" @click="generateCandidate">{{ candidateGeneration.state.pending ? '重试保存候选种子' : '生成候选种子' }}</n-button></footer>
  </section>
</template>

<style scoped>
.library-layout .record-detail{max-height:none;overflow-y:visible}.detail-fields dd{overflow-wrap:anywhere}
.library-panel { min-width:0; padding:24px; border:1px solid #d8c9b5; background:rgba(255,253,248,.94); }
.panel-heading,.record-detail>header { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.panel-heading p,.record-detail>header span { margin:0; color:#9a4938; font:750 9px Georgia,serif; letter-spacing:.14em; }
.panel-heading h2 { margin:5px 0 0; font:650 27px 'Noto Serif SC','Songti SC',serif; }.panel-intro{margin:10px 0 20px;color:#786c5e;font-size:12px;line-height:1.7}
.library-layout { display:grid; grid-template-columns:minmax(230px,.38fr) minmax(0,1fr); min-height:590px; border:1px solid #e1d6c5; }
.record-list { min-width:0; max-height:660px; overflow-y:auto; border-right:1px solid #e1d6c5; background:#f6efe3; }
.record-list>button { display:grid; width:100%; gap:6px; padding:17px; border:0; border-bottom:1px solid #e1d6c5; text-align:left; color:#514940; background:transparent; cursor:pointer; }
.record-list>button.active { color:#8f3f31; background:#fffdf8; box-shadow:inset 3px 0 #9a4938; }.record-list span,.record-list small{color:#887763;font-size:10px}.record-list strong{font:650 17px 'Noto Serif SC','Songti SC',serif}.record-list small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.record-detail { min-width:0; max-height:660px; overflow-y:auto; padding:24px; }.record-detail h3{margin:6px 0 0;font:650 28px 'Noto Serif SC','Songti SC',serif}
.detail-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0; margin:24px 0; border:1px solid #e1d6c5; }.detail-fields div{padding:15px;border-right:1px solid #e1d6c5;border-bottom:1px solid #e1d6c5}.detail-fields div:nth-child(2n){border-right:0}.detail-fields dt{color:#92775c;font-size:10px;font-weight:700}.detail-fields dd{margin:7px 0 0;white-space:pre-wrap;color:#403a34;font-size:12px;line-height:1.75}
.version-history { padding-top:18px; border-top:1px solid #e1d6c5; }.version-history h4{font:650 16px 'Noto Serif SC','Songti SC',serif}.version-history button{display:flex;width:100%;justify-content:space-between;gap:12px;padding:9px;border:0;border-bottom:1px solid #eee4d6;color:#62594e;background:transparent;cursor:pointer}.version-history button[aria-pressed=true]{color:#8f3f31;background:#fbf3e8}.detail-empty{align-self:center}
@media(max-width:720px){.library-panel{padding:16px}.library-layout{grid-template-columns:1fr}.record-list{max-height:260px;border-right:0;border-bottom:1px solid #e1d6c5}.record-detail{max-height:none;overflow-y:visible;padding:16px}.record-detail>header{align-items:flex-start;flex-direction:column}.detail-fields{grid-template-columns:1fr}.detail-fields div{border-right:0}}

.panel-heading[hidden],.panel-intro[hidden]{display:none}.library-panel,.candidate-panel{padding:0;border:0;background:none}.library-layout,.candidate-layout{gap:20px;border:0;grid-template-columns:300px minmax(0,1fr);height:calc(100dvh - 348px);min-height:380px}.library-layout{grid-template-columns:326px minmax(0,1fr)}.record-list{background:#fffefa;border:1px solid #ddd5c8;border-radius:6px;padding:18px 10px;max-height:none}.record-list h2{font-size:17px;font-weight:500;margin:0 8px 24px}.record-list>button{border:0;border-radius:10px;padding:16px;margin-bottom:10px}.record-list>button.active{background:#efe2d7;box-shadow:none}.record-list>button strong{font-size:19px}.library-layout .record-detail,.candidate-layout .record-detail{overflow-y:auto;max-height:100%;min-height:0;border:1px solid #ddd5c8;border-radius:6px;background:#fffefa;padding:26px 28px}.record-detail>header{align-items:flex-start}.record-detail h3{font-size:28px}.reading-summary h4{font:500 20px 'Noto Serif SC','Songti SC',serif;margin:28px 0 14px}.reading-summary p{font-size:15px;line-height:1.9;white-space:pre-wrap;overflow-wrap:anywhere}.record-detail details{margin:24px 0;color:#6f685e}.record-detail summary{cursor:pointer}.detail-fields{border:0;grid-template-columns:1fr}.detail-fields div{border:0;padding:10px 0}.version-history{margin-top:20px}.topic-footer{position:fixed;bottom:0;left:224px;right:0;min-height:76px;padding:15px 36px;display:flex;align-items:center;gap:20px;border-top:1px solid #ddd5c8;background:#fffefa;z-index:10}.topic-footer>span{margin-right:auto;color:#6f685e;font-size:13px}.topic-footer :deep(.n-button){min-height:46px;min-width:160px;border-radius:10px}.topic-footer :deep(.n-button--primary-type){min-width:264px;background:#934735}.status-tabs{margin-bottom:12px}
@media(min-width:1120px) and (max-height:820px){.library-layout,.candidate-layout{height:calc(100dvh - 306px);min-height:350px;grid-template-columns:280px minmax(0,1fr)}.record-detail h3{font-size:26px}.reading-summary h4{margin:20px 0 10px}}
@media(max-width:1119px){.topic-footer{left:72px}}
@media(max-width:760px){.topic-footer{left:0;padding:12px}.topic-footer>span{display:none}.topic-footer :deep(.n-button){min-width:0;flex:1}.library-layout,.candidate-layout{height:auto;grid-template-columns:1fr}.record-detail{overflow-y:visible}}

.topic-footer :deep(.n-button--primary-type),.discussion-panel :deep(.n-button--primary-type),.direction-summary :deep(.n-button){--n-color:#934735!important;--n-color-hover:#803b2c!important;--n-color-pressed:#803b2c!important;--n-text-color:#fffefa!important;--n-text-color-hover:#fffefa!important;--n-text-color-pressed:#fffefa!important;--n-border:1px solid #934735!important;--n-border-hover:1px solid #934735!important;background:#934735;color:#fffefa}.record-list>button strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.record-list>button span{font-family:inherit;font-size:12px}.status-tabs{margin:0 8px 18px}.discussion-list strong{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.conversation-title strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.conversation-title span{flex-shrink:0}
</style>
