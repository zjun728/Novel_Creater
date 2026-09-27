<script setup>
import { computed, onBeforeUnmount, onMounted, onServerPrefetch, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute } from 'vue-router'
import { api } from '../api/db/client.js'
import { createContinuityIssuesController, ISSUE_CATEGORIES, ISSUE_SEVERITIES, ISSUE_STATUSES } from '../application/continuity/continuityIssuesController.js'
import { chapterWorkbenchPath, projectOverviewPath, planningPlotsPath } from '../router/projectRoutes.js'

const route = useRoute()
const projectId = computed(() => String(route.params.projectId || ''))
const controller = createContinuityIssuesController({ api })
const { state, form, mode, selected, operation, message, lifecycle, readOnly, busy, formLocked, dirty, canCloseArchivedUncertain } = controller
const filter = ref('')
const offset = ref(0)
const sourceChapter = computed(() => {
  const value = route.query.sourceChapterNumber
  return typeof value === 'string' && /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) ? Number(value) : null
})
const sourcePath = computed(() => selected.value?.sourceChapterNumber ? chapterWorkbenchPath(projectId.value, selected.value.sourceChapterNumber) : '')
const confirmDiscard = uncertain => globalThis.window?.confirm(uncertain
  ? '创建结果尚未确认，记录可能已保存。离开后请先检查问题列表，避免重复创建。仍要离开吗？'
  : '问题记录有未保存的修改。放弃修改并离开吗？') ?? false
const canLeave = () => controller.confirmLeave(confirmDiscard)
async function load(nextOffset = offset.value) {
  offset.value = nextOffset
  return controller.load(projectId.value, { status: filter.value, offset: nextOffset })
}
async function changeFilter(event) {
  const value = event.target.value
  filter.value = value
  await load(0)
}
async function createIssue() { if (await canLeave()) controller.beginCreate(sourceChapter.value) }
async function openIssue(id) { if (await canLeave()) await controller.open(id) }
async function closeEditor() { if (await canLeave()) controller.cancel() }
function closeUncertainEditor() {
  return controller.closeArchivedUncertain(() => globalThis.window?.confirm('项目已归档，创建结果仍未确认，问题可能已经保存。关闭未确认表单后请先核对已有记录。确认关闭吗？') ?? false)
}
function dateLabel(value) { return new Date(value).toLocaleString('zh-CN', { hour12: false }) }
let initialLoad = Promise.resolve()
watch(projectId, () => {
  filter.value = ''; offset.value = 0
  const id = projectId.value
  initialLoad = load(0).then(loaded => {
    if (loaded && id === projectId.value && sourceChapter.value && !readOnly.value) controller.beginCreate(sourceChapter.value)
  })
}, { immediate: true })
onServerPrefetch(() => initialLoad)
onBeforeRouteLeave(canLeave)
onBeforeRouteUpdate((to, from) => to.params.projectId !== from.params.projectId ? canLeave() : true)
onMounted(() => globalThis.window?.addEventListener('beforeunload', controller.beforeUnload))
onBeforeUnmount(() => { globalThis.window?.removeEventListener('beforeunload', controller.beforeUnload); controller.dispose() })
</script>

<template>
  <section class="issues-page" aria-labelledby="issues-title">
    <header class="issues-heading">
      <div><p class="issues-eyebrow">世界与连续性</p><h1 id="issues-title">连续性问题</h1><p>记录跨章冲突、处理建议与未来纠偏目标，追踪每项问题的处理结论。</p></div>
      <button v-if="!readOnly" class="issues-primary" :disabled="busy || operation === 'uncertain'" @click="createIssue">记录问题</button>
    </header>
    <p class="issues-boundary">“已解决”表示作者记录了处理结论，不代表历史正文或已发生事实被改写。未来处理目标仅保存说明。</p>
    <p v-if="lifecycle === 'archived'" class="issues-archive" role="status">项目已归档，连续性问题仅可查看。</p>
    <div class="issues-layout">
      <section class="issues-register" aria-labelledby="issues-register-title">
        <div class="issues-toolbar"><h2 id="issues-register-title">问题记录</h2><label>处理状态<select aria-label="处理状态" :value="filter" :disabled="state.status === 'loading' || busy" @change="changeFilter"><option value="">全部状态</option><option v-for="(label, value) in ISSUE_STATUSES" :key="value" :value="value">{{ label }}</option></select></label></div>
        <p v-if="state.status === 'loading'" class="issues-empty" role="status">正在读取问题记录…</p>
        <div v-else-if="state.status === 'error'" class="issues-empty"><p role="alert">{{ state.message }}</p><button @click="load()">重新读取</button></div>
        <template v-else-if="state.status === 'ready'">
          <div v-if="!state.data.items.length" class="issues-empty"><h3>{{ filter ? '该状态下暂无问题' : '尚无连续性问题记录' }}</h3><p>{{ filter ? '可以切换状态查看其他记录。' : '发现时间、位置、人物状态、规则或事实冲突时，可在这里记录。' }}</p></div>
          <ul v-else class="issues-list"><li v-for="item in state.data.items" :key="item.id"><button class="issue-choice" :aria-pressed="selected?.id === item.id" :disabled="busy || operation === 'uncertain'" @click="openIssue(item.id)"><span class="issue-tags"><span class="issue-status" :data-status="item.status">{{ ISSUE_STATUSES[item.status] }}</span><span>{{ ISSUE_CATEGORIES[item.category] }}</span><span :class="{ 'issue-high': item.severity === 'high' }">{{ ISSUE_SEVERITIES[item.severity] }}严重度</span></span><span class="issue-description">{{ item.description }}</span><span class="issue-meta">{{ item.sourceChapterNumber ? `来源：第 ${item.sourceChapterNumber} 章定稿` : '手工记录 · 未关联来源章' }}<span>{{ dateLabel(item.updatedAt) }}</span></span></button></li></ul>
          <nav class="issues-pagination" aria-label="问题记录分页"><button :disabled="offset === 0 || busy" @click="load(Math.max(0, offset - 50))">上一页</button><span>第 {{ Math.floor(offset / 50) + 1 }} 页</span><button :disabled="state.data.nextOffset === null || busy" @click="load(state.data.nextOffset)">下一页</button><button :disabled="busy" @click="load()">刷新列表</button></nav>
        </template>
      </section>

      <section class="issue-detail" aria-labelledby="issue-detail-title" :aria-busy="busy">
        <div class="issue-detail-heading"><div><p class="issues-eyebrow">{{ mode === 'create' ? '新增记录' : '处理与来源' }}</p><h2 id="issue-detail-title">{{ mode === 'create' ? '记录连续性问题' : selected ? '问题详情' : '查看与处理问题' }}</h2></div><button v-if="canCloseArchivedUncertain" @click="closeUncertainEditor">关闭未确认表单</button><button v-else-if="mode" :disabled="busy || operation === 'uncertain'" @click="closeEditor">关闭</button></div>
        <p v-if="message" class="issue-message" role="status">{{ message }}</p>
        <p v-if="operation === 'opening'" role="status">正在读取问题详情…</p>
        <form v-else-if="mode === 'create'" class="issue-form" @submit.prevent="controller.save()">
          <fieldset :disabled="formLocked"><div class="issue-form-row"><label>问题类别<select aria-label="问题类别" v-model="form.category"><option v-for="(label, value) in ISSUE_CATEGORIES" :key="value" :value="value">{{ label }}</option></select></label><label>严重程度<select aria-label="严重程度" v-model="form.severity"><option v-for="(label, value) in ISSUE_SEVERITIES" :key="value" :value="value">{{ label }}</option></select></label></div>
            <label>问题说明 <span class="issue-required">必填</span><textarea v-model="form.description" rows="4" maxlength="4000" required placeholder="描述冲突及其对故事连续性的影响" /></label>
            <label>处理建议<textarea v-model="form.suggestion" rows="2" maxlength="4000" placeholder="可选，记录你建议的处理方式" /></label>
            <label>未来处理目标<textarea v-model="form.futureTarget" rows="2" maxlength="4000" placeholder="可选，例如在后续章节补充解释" /></label>
            <label>来源章节<input v-model="form.sourceChapterNumber" inputmode="numeric" pattern="[1-9][0-9]*" placeholder="可选，填写已定稿章节编号" /><small>保存时关联该章定稿依据；未填写则作为无来源的手工记录。</small></label>
          </fieldset>
          <button class="issues-primary" :disabled="busy || readOnly || operation === 'create-conflict'">{{ operation === 'uncertain' ? '重试确认创建结果' : busy ? '正在保存…' : '保存问题记录' }}</button>
        </form>
        <template v-else-if="selected">
          <div class="issue-tags"><span class="issue-status" :data-status="selected.status">{{ ISSUE_STATUSES[selected.status] }}</span><span>{{ ISSUE_CATEGORIES[selected.category] }}</span><span>{{ ISSUE_SEVERITIES[selected.severity] }}严重度</span></div>
          <dl class="issue-facts"><div><dt>问题说明</dt><dd>{{ selected.description }}</dd></div><div><dt>处理建议</dt><dd>{{ selected.suggestion || '未填写' }}</dd></div><div><dt>未来处理目标</dt><dd>{{ selected.futureTarget || '未填写' }}</dd></div><div><dt>来源</dt><dd><router-link v-if="sourcePath" :to="{ path: sourcePath, query: { view: 'text' } }">查看第 {{ selected.sourceChapterNumber }} 章定稿</router-link><span v-else>手工记录，未关联来源章节。</span></dd></div><div><dt>当前处理结论</dt><dd>{{ ISSUE_STATUSES[selected.status] }} · {{ selected.resolutionNote || '尚未填写处理说明' }}</dd></div><div><dt>最近更新</dt><dd>{{ dateLabel(selected.updatedAt) }}</dd></div></dl>
          <div v-if="readOnly"><p class="issues-archive">当前仅可查看问题及处理结论。</p><section v-if="dirty" class="issue-unsaved-draft" aria-label="未保存的处理说明"><h3>未保存的处理说明</h3><p>处理状态：{{ ISSUE_STATUSES[form.status] }}</p><p>{{ form.resolutionNote || '未填写说明' }}</p><small>这些内容仅保留在当前页面，尚未保存。</small></section></div>
          <form v-else class="issue-form issue-resolution" @submit.prevent="controller.save()"><h3>记录处理结论</h3><fieldset :disabled="busy"><label>处理状态<select aria-label="处理状态" v-model="form.status"><option v-for="(label, value) in ISSUE_STATUSES" :key="value" :value="value">{{ label }}</option></select></label><label>处理说明 <span v-if="form.status !== 'pending'" class="issue-required">必填</span><textarea v-model="form.resolutionNote" rows="4" maxlength="4000" :required="form.status !== 'pending'" placeholder="说明如何处理，或为何忽略这项问题" /></label></fieldset>
            <div class="issue-actions"><button v-if="operation === 'conflict'" type="button" @click="controller.reloadSelected()">读取最新记录</button><button class="issues-primary" :disabled="busy || operation === 'conflict'">{{ busy ? '正在确认…' : '保存处理结论' }}</button><span v-if="dirty" class="issue-unsaved">有未保存的修改</span></div>
          </form>
        </template>
        <p v-else-if="operation !== 'opening'" class="issues-empty">选择一项问题查看详情、来源章节与处理结论。</p>
      </section>
    </div>
    <footer class="issues-return"><span>问题处理保留历史记录，不直接改写已定稿事实。</span><router-link :to="planningPlotsPath(projectId)">查看故事规划</router-link><router-link :to="projectOverviewPath(projectId)">返回继续创作</router-link></footer>
  </section>
</template>

<style scoped>
.issue-unsaved-draft{padding:16px;background:var(--nc-wash);border:1px solid var(--nc-border);border-radius:6px}.issue-unsaved-draft h3{font-size:15px;margin:0 0 12px}.issue-unsaved-draft p{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;font-size:14px}.issue-unsaved-draft small{color:var(--nc-muted)}
.issues-page{max-width:1660px;margin:0 auto;padding:26px 30px 38px;color:var(--nc-ink,#302a23)}
.issues-heading,.issue-detail-heading,.issues-toolbar{display:flex;align-items:center;justify-content:space-between;gap:20px}.issues-heading h1{font-family:var(--nc-font-serif,serif);font-size:28px;margin:4px 0 10px;font-weight:650;letter-spacing:.02em}.issues-heading p{margin:0;color:var(--nc-muted,#766c60);line-height:1.7}.issues-eyebrow{font-size:12px;font-weight:650;letter-spacing:.14em;color:var(--nc-vermilion,#8f3d32);margin:0 0 7px}.issues-boundary{padding:13px 17px;margin:22px 0 16px;border-left:3px solid var(--nc-vermilion);background:#efe6d7;color:var(--nc-muted);font-size:13px;line-height:1.7}.issues-archive{background:#f6f0e4;color:#735e34;padding:12px 15px;border-radius:7px;line-height:1.6}
.issues-layout{display:grid;grid-template-columns:minmax(350px,.94fr) minmax(420px,1.06fr);align-items:start;gap:22px}.issues-register,.issue-detail{min-width:0;background:var(--nc-paper,#fffdf8);border:1px solid var(--nc-border,#d8cbb7);border-radius:12px;overflow:hidden}.issue-detail{padding:22px 24px;position:sticky;top:18px;max-height:calc(100vh - 128px);overflow-y:auto}.issues-toolbar{padding:17px 20px;border-bottom:1px solid #e3d7c5}.issues-toolbar h2,.issue-detail h2{font-size:18px;margin:0}.issues-toolbar label{display:flex;align-items:center;gap:9px;font-size:13px}.issues-page button,.issues-page select,.issues-page input,.issues-page textarea{font:inherit}.issues-page button,.issues-page select{min-height:40px}.issues-page button{cursor:pointer;padding:9px 14px;border:1px solid var(--nc-border);border-radius:7px;background:var(--nc-paper);color:var(--nc-ink)}.issues-page button:disabled{cursor:default;opacity:.5}.issues-page button:hover:not(:disabled){background:#f2eadd}.issues-page .issues-primary{background:var(--nc-vermilion);color:#fff;border-color:var(--nc-vermilion);font-weight:600}.issues-page .issues-primary:hover:not(:disabled){background:#713025}.issues-page :is(button,select,input,textarea,a):focus-visible{outline:3px solid #c99370;outline-offset:3px}.issues-page select,.issues-page input,.issues-page textarea{box-sizing:border-box;border:1px solid var(--nc-border);border-radius:6px;padding:9px 10px;background:var(--nc-paper);color:var(--nc-ink)}.issues-page textarea{resize:vertical;line-height:1.65;min-height:66px}.issues-page a{color:var(--nc-vermilion);text-underline-offset:3px}
.issues-list{list-style:none;padding:0;margin:0;max-height:calc(100vh - 405px);min-height:240px;overflow-y:auto}.issues-list li+li{border-top:1px solid #e7dccb}.issues-page .issue-choice{display:block;width:100%;padding:18px 20px;text-align:left;border:0;border-radius:0;background:transparent}.issues-page .issue-choice[aria-pressed=true]{background:#f4ecdf;box-shadow:inset 3px 0 var(--nc-vermilion)}.issue-tags{display:flex;align-items:center;flex-wrap:wrap;gap:10px;font-size:12px;color:var(--nc-muted)}.issue-status{padding:3px 8px;border-radius:4px;background:#f4edda;color:#846529}.issue-status[data-status=resolved]{background:#e2f0e6;color:#34654a}.issue-status[data-status=ignored]{background:#edf0f1;color:#61706d}.issue-high{color:#a25040}.issue-description{display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;line-height:1.75;font-size:14px;margin:11px 0;white-space:pre-wrap;overflow-wrap:anywhere}.issue-meta{display:flex;flex-wrap:wrap;gap:7px 18px;justify-content:space-between;font-size:11px;color:var(--nc-muted)}.issues-pagination{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding:14px 18px;border-top:1px solid #e3d7c5;font-size:12px}.issues-pagination button{padding:6px 10px}.issues-pagination span{margin:0 auto}.issues-empty{padding:32px 20px;color:var(--nc-muted);line-height:1.8;font-size:14px}.issues-empty h3{font-size:17px;font-weight:550;color:var(--nc-ink)}
.issue-detail-heading{margin-bottom:22px}.issue-detail-heading button{font-size:12px}.issue-message{padding:12px 14px;background:#f1eadb;color:var(--nc-ink);font-size:13px;line-height:1.7;border-radius:6px}.issue-form{display:flex;flex-direction:column;gap:16px}.issue-form fieldset{border:0;padding:0;margin:0;display:flex;flex-direction:column;gap:15px;min-width:0}.issue-form label{display:block;font-size:13px;font-weight:550}.issue-form label :is(select,input,textarea){display:block;width:100%;margin-top:7px;font-size:14px;font-weight:400}.issue-form small{display:block;margin-top:7px;font-size:12px;line-height:1.6;color:var(--nc-muted);font-weight:400}.issue-required{font-size:11px;color:#8e6744;font-weight:400;margin-left:5px}.issue-form-row{display:grid;grid-template-columns:1fr 1fr;gap:16px}.issue-form>button{align-self:flex-start}.issue-facts{margin:20px 0;font-size:14px}.issue-facts>div{margin-bottom:17px}.issue-facts dt{font-size:12px;color:var(--nc-muted);margin-bottom:6px}.issue-facts dd{margin:0;line-height:1.75;white-space:pre-wrap;overflow-wrap:anywhere}.issue-resolution{padding-top:20px;border-top:1px solid var(--nc-border)}.issue-resolution h3{font-size:16px;margin:0}.issue-actions{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.issue-unsaved{font-size:12px;color:#8f7246}
.issues-return{display:flex;align-items:center;gap:24px;margin:24px auto;max-width:1320px;padding:20px;background:var(--nc-paper);font-size:13px}.issues-return span{margin-right:auto;color:var(--nc-muted)}.issues-return a{color:var(--nc-vermilion)}
</style>
