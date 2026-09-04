<script setup>
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NAlert, NButton, NEmpty, NSpin, NTag } from 'naive-ui'

import { projectSeedsPath, topicCandidatesPath } from '@/router/projectRoutes'
import { useTopicCenterStore } from '@/stores/topicCenterStore'
import CreateProjectFromCandidateDialog from './CreateProjectFromCandidateDialog.vue'

const props = defineProps({ compact: { type: Boolean, default: false } })
const emit = defineEmits(['continue-discussion'])
const topics = useTopicCenterStore()
const router = useRouter()
const status = ref('active')
const selectedVersion = ref(null)
const localError = ref('')
const archiveBusy = ref(false)
const dialogOpen = ref(false)

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
  status.value = value
  topics.activeCandidate = null
  localError.value = ''
  try { await topics.loadCandidates(value) } catch (failure) {
    localError.value = failure?.message || '候选种子列表加载失败'
  }
}

async function open(item) {
  localError.value = ''
  try { await topics.openCandidate(item.id) } catch (failure) {
    localError.value = failure?.message || '候选种子详情加载失败'
  }
}

function continueDiscussion() {
  if (!detail.value || !version.value) return
  emit('continue-discussion', {
    kind: 'candidate', id: detail.value.id, version: version.value.version,
    contentHash: version.value.contentHash, title: version.value.payload.title,
  })
}

async function archive() {
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
    <header class="panel-heading">
      <div><p>CANDIDATE LIBRARY</p><h2 id="candidate-library-title">候选种子库</h2></div>
      <router-link v-if="compact" :to="topicCandidatesPath()">查看全部候选 →</router-link>
      <n-tag v-else :bordered="false">{{ topics.candidates.length }} 个候选</n-tag>
    </header>
    <p class="panel-intro">候选种子是项目创建前的正式版本库；它仍不等于项目种子，更不会在创建项目后自动确认。</p>
    <n-alert v-if="localError" type="error" aria-live="assertive">{{ localError }}</n-alert>

    <div v-if="compact" class="recent-grid">
      <article v-for="item in topics.candidates.slice(0, 3)" :key="item.id">
        <span>版本 {{ item.currentVersion }} · {{ item.current.payload.genre }}</span>
        <h3>{{ item.current.payload.title }}</h3><p>{{ item.current.payload.logline }}</p>
      </article>
      <n-empty v-if="!topics.candidates.length" description="讨论产生的候选种子会显示在这里。" />
    </div>

    <template v-else>
      <div class="status-tabs" role="group" aria-label="候选种子状态">
        <button type="button" :aria-pressed="status === 'active'" @click="setStatus('active')">当前候选</button>
        <button type="button" :aria-pressed="status === 'archived'" @click="setStatus('archived')">归档记录</button>
      </div>
      <n-spin :show="topics.loading">
        <div class="candidate-layout">
          <div class="record-list" tabindex="0" aria-label="候选种子列表">
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
                <n-button v-if="detail.status === 'active'" size="small" type="primary" @click="dialogOpen = true">创建项目</n-button>
              </div>
            </header>
            <dl class="detail-fields">
              <div v-for="field in fields" :key="field[0]"><dt>{{ field[1] }}</dt><dd>{{ version.payload[field[0]] }}</dd></div>
            </dl>
            <section class="version-history" aria-label="候选种子版本历史">
              <h4>版本历史</h4>
              <button v-for="item in detail.versions" :key="item.id" type="button" :aria-pressed="item.version === version.version" @click="selectedVersion = item.version">版本 {{ item.version }}<span>{{ item.payload.title }}</span></button>
            </section>
          </article>
          <n-empty v-else class="detail-empty" description="从左侧选择一个候选，查看完整种子内容。" />
        </div>
      </n-spin>
    </template>
    <CreateProjectFromCandidateDialog :show="dialogOpen" :candidate="detail" :version="version" @close="dialogOpen = false" @created="projectCreated" />
  </section>
</template>

<style scoped>
.candidate-panel { min-width:0; padding:24px; border:1px solid #d8c9b5; background:rgba(255,253,248,.94); }
.panel-heading,.record-detail>header,.detail-actions { display:flex; align-items:center; justify-content:space-between; gap:12px; }.panel-heading a{color:#8f3f31;font-size:12px;text-decoration:none}
.panel-heading p,.record-detail>header span,.recent-grid span { margin:0; color:#9a4938; font:750 9px Georgia,serif; letter-spacing:.13em; }.panel-heading h2{margin:5px 0 0;font:650 27px 'Noto Serif SC','Songti SC',serif}.panel-intro{margin:10px 0 18px;color:#786c5e;font-size:12px;line-height:1.7}
.status-tabs { display:flex; gap:7px; margin-bottom:12px; }.status-tabs button{padding:7px 13px;border:1px solid #cdbba2;color:#65594d;background:transparent;cursor:pointer}.status-tabs button[aria-pressed=true]{color:#fff;background:#8f3f31}
.candidate-layout { display:grid; grid-template-columns:minmax(250px,.38fr) minmax(0,1fr); min-height:620px; border:1px solid #e1d6c5; }.record-list{min-width:0;max-height:690px;overflow-y:auto;border-right:1px solid #e1d6c5;background:#f6efe3}.record-list:focus-visible{outline:2px solid #9a4938;outline-offset:2px}.record-list>button{display:grid;width:100%;gap:6px;padding:17px;border:0;border-bottom:1px solid #e1d6c5;text-align:left;color:#514940;background:transparent;cursor:pointer}.record-list>button.active{color:#8f3f31;background:#fffdf8;box-shadow:inset 3px 0 #9a4938}.record-list span,.record-list small{color:#887763;font-size:10px}.record-list strong{font:650 18px 'Noto Serif SC','Songti SC',serif}.record-list small{display:-webkit-box;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-height:1.5}
.record-detail{min-width:0;max-height:690px;overflow-y:auto;padding:24px}.record-detail h3{margin:6px 0 0;font:650 29px 'Noto Serif SC','Songti SC',serif}.detail-actions{justify-content:flex-end;flex-wrap:wrap}.detail-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));margin:24px 0;border:1px solid #e1d6c5}.detail-fields div{padding:14px;border-right:1px solid #e1d6c5;border-bottom:1px solid #e1d6c5}.detail-fields div:nth-child(2n){border-right:0}.detail-fields dt{color:#92775c;font-size:10px;font-weight:700}.detail-fields dd{margin:7px 0 0;white-space:pre-wrap;color:#403a34;font-size:12px;line-height:1.72}.version-history{padding-top:18px;border-top:1px solid #e1d6c5}.version-history h4{font:650 16px 'Noto Serif SC','Songti SC',serif}.version-history button{display:flex;width:100%;justify-content:space-between;gap:12px;padding:9px;border:0;border-bottom:1px solid #eee4d6;color:#62594e;background:transparent;cursor:pointer}.version-history button[aria-pressed=true]{color:#8f3f31;background:#fbf3e8}
.recent-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.recent-grid article{min-width:0;padding:15px;border:1px solid #e1d6c5;background:#fbf7ef}.recent-grid h3{margin:8px 0 5px;font:650 18px 'Noto Serif SC','Songti SC',serif}.recent-grid p{margin:0;color:#6f6458;font-size:11px;line-height:1.65}.detail-empty{align-self:center}
@media(max-width:720px){.candidate-panel{padding:16px}.candidate-layout{grid-template-columns:1fr}.record-list{max-height:none;overflow-y:visible;border-right:0;border-bottom:1px solid #e1d6c5}.record-detail{max-height:none;overflow-y:visible;padding:16px}.record-detail>header{align-items:flex-start;flex-direction:column}.detail-actions{justify-content:flex-start}.detail-fields,.recent-grid{grid-template-columns:1fr}.detail-fields div{border-right:0}}
</style>
