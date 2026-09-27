<script setup>
import { computed, ref, watch } from 'vue'
import { planningEntries } from '../../application/planning/planningPresentation.js'
const props = defineProps({ content: { type: Object, required: true }, section: { type: String, required: true }, draft: Boolean })
const selectedKey = ref('')
const entries = computed(() => planningEntries(props.content, props.section))
const selected = computed(() => entries.value.find(row => row.key === selectedKey.value) || entries.value.find(row => row.current) || entries.value[0])
watch(() => props.section, () => { selectedKey.value = '' })
</script>

<template>
  <section class="planning-reader" aria-label="规划阅读">
    <nav class="reader-index" aria-label="规划目录">
      <strong>{{ section === 'volumes' ? '全书分卷' : section === 'plots' ? '情节线目录' : '故事块目录' }}</strong>
      <button v-for="entry in entries" :key="entry.key" type="button" :aria-current="selected?.key === entry.key ? 'true' : undefined" @click="selectedKey = entry.key">
        <span>{{ entry.title }}</span><small>{{ entry.current ? '当前故事块' : draft ? '待确认安排' : '已确认安排' }}</small>
      </button>
      <p v-if="!entries.length">尚无内容</p>
      <p class="reader-hint">选择条目仅查看详情；结构调整请使用“调整规划”。</p>
    </nav>
    <article class="reader-detail">
      <template v-if="selected">
        <span class="reader-badge">{{ draft ? '工作稿 · 尚未采用' : '已确认 · 默认阅读' }}</span>
        <h2>{{ selected.title }}</h2>
        <dl><div v-for="field in selected.fields" :key="field.label"><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></div></dl>
      </template>
      <p v-else>当前分区尚无规划内容。请主动进入调整规划后补充。</p>
    </article>
  </section>
</template>

<style scoped>
.planning-reader{display:grid;grid-template-columns:240px minmax(0,1fr);gap:18px;min-height:380px}
.reader-index,.reader-detail{border:1px solid var(--nc-border);border-radius:5px;background:var(--nc-paper);padding:20px;min-width:0;max-height:calc(100vh - 330px);overflow:auto}
.reader-index{display:flex;flex-direction:column;gap:12px}.reader-index strong{font-size:14px}.reader-index button{display:grid;gap:7px;width:100%;border:0;border-radius:5px;padding:14px 10px;text-align:left;background:transparent;color:var(--nc-ink);font:inherit;cursor:pointer;overflow-wrap:anywhere}
.reader-index button[aria-current]{background:var(--nc-wash);color:var(--nc-vermilion)}.reader-index small,.reader-hint{font-size:12px;color:var(--nc-muted)}.reader-hint{margin-top:auto;padding-top:24px;line-height:1.7}
.reader-detail h2{font:500 24px Georgia,'Noto Serif SC',serif;margin:20px 0}.reader-badge{padding:5px 10px;background:var(--nc-wash);color:var(--nc-muted);font-size:12px;border-radius:5px}
dl{margin:0}dl>div{margin:0 0 24px}dt{font-size:16px;margin-bottom:9px}dd{margin:0;white-space:pre-wrap;overflow-wrap:anywhere;font-size:14px;line-height:1.8}button:focus-visible{outline:2px solid var(--nc-vermilion);outline-offset:2px}
</style>
