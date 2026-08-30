<script setup>
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NSpin, NTag } from 'naive-ui'

import { useTopicCenterStore } from '@/stores/topicCenterStore'

const emit = defineEmits(['continue-discussion'])
const topics = useTopicCenterStore()
const localError = ref('')
const selectedVersion = ref(null)

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
  localError.value = ''
  try { await topics.openDirection(item.id) } catch (failure) {
    localError.value = failure?.message || '选题方向加载失败'
  }
}

function continueDiscussion() {
  if (!detail.value || !version.value) return
  emit('continue-discussion', {
    kind: 'direction', id: detail.value.id, version: version.value.version,
    contentHash: version.value.contentHash, title: version.value.payload.title,
  })
}
</script>

<template>
  <section class="library-panel" aria-labelledby="direction-library-title">
    <header class="panel-heading">
      <div><p>DIRECTION LIBRARY</p><h2 id="direction-library-title">选题方向库</h2></div>
      <n-tag :bordered="false">{{ topics.directions.length }} 个方向</n-tag>
    </header>
    <p class="panel-intro">方向是可选的中间成果。它帮助你看清机会、读者和风险，但不会替你创建种子或项目。</p>
    <n-alert v-if="localError" type="error" aria-live="assertive">{{ localError }}</n-alert>
    <n-spin :show="topics.loading">
      <div class="library-layout">
        <div class="record-list" tabindex="0" aria-label="选题方向列表">
          <button v-for="item in topics.directions" :key="item.id" type="button" :class="{ active: detail?.id === item.id }" @click="open(item)">
            <span>版本 {{ item.currentVersion }}</span><strong>{{ item.current.payload.title }}</strong><small>{{ item.current.payload.genreOpportunity }}</small>
          </button>
          <n-empty v-if="!topics.directions.length && !topics.loading" description="尚未保存选题方向。可在 AI 讨论中显式保存。" />
        </div>
        <article v-if="version" class="record-detail">
          <header><div><span>当前阅读版本 {{ version.version }}</span><h3>{{ version.payload.title }}</h3></div><n-button size="small" @click="continueDiscussion">继续讨论</n-button></header>
          <dl class="detail-fields">
            <div v-for="field in fields" :key="field[0]"><dt>{{ field[1] }}</dt><dd>{{ version.payload[field[0]] }}</dd></div>
          </dl>
          <section class="version-history" aria-label="方向版本历史">
            <h4>版本历史</h4>
            <button v-for="item in detail.versions" :key="item.id" type="button" :aria-pressed="item.version === version.version" @click="selectedVersion = item.version">版本 {{ item.version }}<span>{{ item.payload.title }}</span></button>
          </section>
        </article>
        <n-empty v-else class="detail-empty" description="从左侧选择一个方向，查看完整判断。" />
      </div>
    </n-spin>
  </section>
</template>

<style scoped>
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
</style>
