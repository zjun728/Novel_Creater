<script setup>
import { computed } from 'vue'
import { comparePlanning } from '../../application/planning/planningPresentation.js'
const props = defineProps({ before: { type: Object, default: null }, after: { type: Object, default: null } })
const changes = computed(() => comparePlanning(props.before, props.after))
</script>
<template>
  <section aria-label="规划修改对比" class="planning-comparison">
    <p v-if="!before">首次规划：以下为拟采用的完整内容，尚无原安排。</p>
    <p v-if="!changes.length">与已确认规划相比没有内容变化。</p>
    <article v-for="change in changes" :key="change.key">
      <h3>{{ change.section }} · {{ change.title }} · {{ change.kind }}</h3>
      <div class="comparison-columns">
        <section v-for="side in ['before','after']" :key="side">
          <strong>{{ side === 'before' ? '原安排' : '修改后 · 拟采用' }}</strong>
          <template v-if="change[side]">
            <h4>{{ change[side].title }}</h4>
            <p v-if="change[side].order">顺序：{{ change[side].order }}{{ change[side].lifecycle === 'retired' ? ' · 已停用' : '' }}</p>
            <dl><div v-for="field in change[side].fields" :key="field.label"><dt>{{ field.label }}</dt><dd>{{ field.value }}</dd></div></dl>
          </template>
          <p v-else>{{ side === 'before' ? '无原安排（新增）' : '不再包含此项' }}</p>
        </section>
      </div>
    </article>
    <aside><strong>影响范围：未来规划</strong><p>本次 {{ changes.length }} 项变化；采用后作为后续创作的规划依据。已定稿正文及其采用的历史依据、已发生事实保留。具体可写章节仍由权威进度核定。</p></aside>
  </section>
</template>
<style scoped>
h3{font-size:17px;margin:20px 0 12px}.comparison-columns{display:grid;grid-template-columns:1fr 1fr;gap:16px}.comparison-columns>section{min-width:0;border:1px solid var(--nc-border);padding:18px;border-radius:5px}.comparison-columns strong{color:var(--nc-vermilion);font-size:12px}h4{font-size:18px;margin:14px 0}dl{margin:0}dl>div{margin:16px 0}dt{color:var(--nc-muted);font-size:12px}dd{margin:6px 0 0;white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.7;font-size:14px}aside{margin-top:18px;padding:16px;background:var(--nc-canvas);line-height:1.7}p{font-size:13px}
</style>
