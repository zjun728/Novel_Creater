<script setup>
import { computed, ref } from 'vue'
import { latestDispute } from '../../utils/reviewReference.js'

const props = defineProps({ finding: Object, decisions: Object, disabled: Boolean, loadEvidence: Function, saveDispute: Function })
const sources = { candidate: '本章正文', canon: '此前已确认事实与进度', planning: '规划要求（不代表已发生）', outline: '本章小纲（不代表已发生）', contract: '创作契约', bible: '创作基础' }
const categories = { attribution: '事实归因', state_change: '前后状态变化', custody: '已交代交接', style: '表达偏好', other: '其他' }
const records = ref([]), selected = ref(''), quote = ref(''), reason = ref(''), category = ref('other'), source = ref('candidate'), search = ref(''), busy = ref(false), error = ref(''), saved = ref(false)
const history = computed(() => (props.decisions?.disputeEvents || []).filter(e => e.findingId === props.finding.id))
const latest = computed(() => latestDispute(props.decisions, props.finding.id))
const candidates = computed(() => records.value.filter(r => r.sourceType === source.value && (!search.value || r.text.includes(search.value))))
const record = computed(() => records.value.find(r => r.id === selected.value))
const locked = computed(() => props.disabled || busy.value)
async function load() {
  busy.value = true; error.value = ''
  try { records.value = await props.loadEvidence() || []; selected.value = ''; quote.value = '' }
  catch { error.value = '无法读取本次审稿依据，请重新读取审稿。' }
  finally { busy.value = false }
}
async function save(action) {
  if (locked.value) return
  busy.value = true; error.value = ''; saved.value = false
  try {
    const prior = latest.value
    const data = action === 'note'
      ? { category: category.value, reason: reason.value, evidence: record.value && quote.value.trim() ? [{ id: record.value.id, quote: quote.value }] : [] }
      : { category: prior.category, reason: prior.reason, evidence: prior.evidence.map(r => ({ id: r.id, quote: r.quote })) }
    await props.saveDispute({ findingId: props.finding.id, action, ...data })
    saved.value = true
  } catch { error.value = '处理尚未确认保存，请重新读取审稿核对，勿将本地输入视为已生效。' }
  finally { busy.value = false }
}
</script>

<template>
  <details class="dispute-panel">
    <summary>查看依据／记录异议<span v-if="latest?.action === 'retain'"> · 作者已选择保留原稿</span></summary>
    <p>模型意见保留。引文真实不代表模型推论正确；作者说明也不代表系统已证实误报。</p>
    <ol v-if="history.length" aria-label="作者处理记录">
      <li v-for="event in history" :key="event.id">
        <strong>{{ { note: '已记录异议', retain: '作者确认保留原稿', revoke: '已撤回处理' }[event.action] }}</strong>
        · {{ new Date(event.createdAt).toLocaleString() }} · {{ categories[event.category] }}
        <p>{{ event.reason }}</p>
        <blockquote v-for="ref in event.evidence" :key="ref.id"><strong>{{ sources[ref.sourceType] }} · 保存时的原文</strong><br>{{ ref.quote }}</blockquote>
      </li>
    </ol>
    <p v-else>尚无作者处理记录。旧报告未保存的历史依据不会自动补造。</p>
    <template v-if="!disabled">
      <button type="button" :disabled="locked" @click="load">读取本次审稿依据</button>
      <label>依据来源<select v-model="source" :disabled="locked" @change="selected = ''; quote = ''"><option v-for="(label, key) in sources" :key="key" :value="key">{{ label }}</option></select></label>
      <label>查找依据<input v-model="search" :disabled="locked" placeholder="输入人物或原文关键词"></label>
      <label>选择原文<select v-model="selected" :disabled="locked" @change="quote = ''"><option value="">请选择依据</option><option v-for="r in candidates" :key="r.id" :value="r.id">{{ r.text.slice(0, 80) }}</option></select></label>
      <details v-if="record"><summary>查看完整依据</summary><pre>{{ record.text }}</pre></details>
      <label>引用原句<textarea v-model="quote" :disabled="locked || !record" maxlength="10000" placeholder="从选中的依据复制原句；系统将核对原文。" /></label>
      <label>争议类型<select v-model="category" :disabled="locked"><option v-for="(label, key) in categories" :key="key" :value="key">{{ label }}</option></select></label>
      <label>作者理由<textarea v-model="reason" :disabled="locked" maxlength="2000" placeholder="说明你对这条意见的判断。" /></label>
      <button type="button" :disabled="locked || !reason.trim() || (!!quote.trim() && (!record || !record.text.includes(quote)))" @click="save('note')">保存异议（不解除阻断）</button>
      <div v-if="finding.severity === 'required' && latest?.action === 'note' && latest.evidence.length" class="retain-confirmation">
        <p>确认后仅对上方已保存的异议选择保留原稿，解除这一条模型意见的阻断；其他校验及事实、进度确认仍须完成。</p>
        <button type="button" :disabled="locked" @click="save('retain')">确认保留原稿</button>
      </div>
      <button v-if="latest && latest.action !== 'revoke'" type="button" :disabled="locked" @click="save('revoke')">撤回本条处理</button>
    </template>
    <p v-else>当前记录只读。正文或审稿依据变化后，原处理不能用于新审稿。</p>
    <p v-if="saved" role="status">处理已保存。</p><p v-if="error" role="alert">{{ error }}</p>
  </details>
</template>

<style scoped>
.dispute-panel { margin-top:12px; border-top:1px solid #d8d1c7; padding-top:10px; }
summary { cursor:pointer; min-height:32px; }
label { display:block; margin:10px 0; font-size:14px; }
input, select, textarea { display:block; box-sizing:border-box; width:100%; padding:8px; margin-top:4px; color:inherit; background:#fffefa; border:1px solid #c7bdb0; border-radius:4px; }
textarea { min-height:72px; } pre, blockquote { white-space:pre-wrap; overflow-wrap:anywhere; margin:8px 0; padding:10px; background:#fffefa; max-height:280px; overflow:auto; }
button { margin:6px 8px 6px 0; padding:8px 12px; min-height:36px; cursor:pointer; } button:disabled { cursor:default; opacity:.55; }
.retain-confirmation { padding:10px; border:1px solid #934735; } :is(button, input, select, textarea, summary):focus-visible { outline:2px solid #934735; outline-offset:2px; }
</style>
