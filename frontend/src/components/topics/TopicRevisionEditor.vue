<script setup>
import { TOPIC_FIELD_LABELS } from '../../application/topics/topicRevision.js'
defineProps({ controller: { type: Object, required: true }, allowCopy: Boolean })
defineEmits(['save', 'cancel'])
</script>
<template>
  <section v-if="controller.draft.value" class="revision-editor" aria-label="手工修订内容">
    <header><h3>手工修订</h3><p>保存将形成新版本，已保存的历史内容及项目种子不受影响。</p></header>
    <form @submit.prevent="$emit('save', false)">
      <label v-for="(_value, key) in controller.draft.value" :key="key"><span>{{ TOPIC_FIELD_LABELS[key] || '内容' }}</span><textarea v-model="controller.draft.value[key]" rows="3" maxlength="2000" :disabled="controller.busy.value" required /></label>
      <p v-if="controller.message.value" role="status">{{ controller.message.value }}</p>
      <footer><button type="submit" :disabled="controller.busy.value">{{ controller.busy.value ? '正在保存…' : '保存为新版本' }}</button><button v-if="allowCopy" type="button" :disabled="controller.busy.value" @click="$emit('save', true)">另存为独立候选</button><button type="button" :disabled="controller.busy.value" @click="$emit('cancel')">取消修订</button></footer>
    </form>
  </section>
</template>
<style scoped>
.revision-editor{margin:20px 0;padding:22px;border:1px solid var(--nc-border,#d8c9b5);background:var(--nc-paper,#fffdf8)}h3{margin:0;font:600 22px 'Noto Serif SC',serif}header p{color:var(--nc-muted,#786c5e);font-size:13px;line-height:1.7}form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}label{display:grid;gap:8px;font-size:13px}textarea{resize:vertical;min-height:86px;width:100%;box-sizing:border-box;padding:10px;border:1px solid var(--nc-border,#d8c9b5);background:transparent;color:inherit;font:inherit;line-height:1.7}footer,form>p{grid-column:1/-1}footer{display:flex;flex-wrap:wrap;gap:10px}button{padding:9px 14px;border:1px solid var(--nc-border,#d8c9b5);background:transparent;color:inherit;cursor:pointer}button[type=submit]{background:var(--nc-vermilion,#9a4938);color:white}button:disabled{opacity:.5;cursor:wait}textarea:focus-visible,button:focus-visible{outline:2px solid var(--nc-vermilion,#9a4938);outline-offset:2px}@media(max-width:720px){form{grid-template-columns:1fr}}
</style>
