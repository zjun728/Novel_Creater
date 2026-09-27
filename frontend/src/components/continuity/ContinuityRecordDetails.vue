<script setup>
import { computed } from 'vue'
import { continuityRecordDetails } from '../../application/continuity/recordDetails.js'

const props = defineProps({ record: { type: Object, required: true }, kind: { type: String, default: 'facts' } })
const details = computed(() => continuityRecordDetails(props.record, props.kind))
</script>

<template>
  <div class="record-details">
    <p v-if="details.title" class="record-caption">{{ details.title }}</p>
    <dl v-if="details.rows.length" class="record-dimensions">
      <div v-for="row in details.rows" :key="row.label"><dt>{{ row.label }}</dt><dd><p v-for="(line, index) in row.lines" :key="index">{{ line }}</p></dd></div>
    </dl>
    <p v-for="(line, index) in details.lines" :key="index" class="record-content">{{ line }}</p>
    <p v-if="!details.lines.length && !details.rows.some(row => row.lines.length)" class="record-note">这项记录尚无法生成摘要，请查看来源正文。</p>
    <p v-if="details.provenance" class="record-note">{{ details.provenance }}</p>
    <p v-if="details.note" class="record-note">{{ details.note }}</p>
  </div>
</template>

<style scoped>
.record-details{margin:16px 0;color:var(--nc-ink);overflow-wrap:anywhere}.record-caption{font-size:12px;color:var(--nc-vermilion);letter-spacing:.04em}.record-dimensions{margin:12px 0;border-left:2px solid var(--nc-border);padding-left:16px}.record-dimensions>div{display:grid;grid-template-columns:180px minmax(0,1fr);gap:16px;padding:7px 0}.record-dimensions dt{font-size:13px;color:var(--nc-muted);line-height:1.9}.record-dimensions dd{margin:0}.record-dimensions dd p{margin:0;white-space:pre-wrap;line-height:1.9}.record-content{line-height:1.9;white-space:pre-wrap}.record-note{font-size:12px;color:var(--nc-muted);line-height:1.8;margin:8px 0}
</style>
