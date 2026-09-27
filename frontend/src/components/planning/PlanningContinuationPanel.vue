<script setup>
defineProps({ result: Object, loading: Boolean, error: String, disabled: Boolean, dirty: Boolean })
defineEmits(['check', 'action', 'edit', 'continue'])
</script>

<template>
  <section id="continuation" class="continuation-panel" aria-labelledby="continuation-title" :aria-busy="loading">
    <header><h2 id="continuation-title">后续安排</h2><button type="button" :disabled="loading" @click="$emit('check')">{{ loading ? '正在检查…' : '检查后续安排' }}</button></header>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-else-if="result">
      <p class="location" v-if="result.currentBlock">当前：{{ result.currentVolume?.title }} / {{ result.currentBlock.title }}</p>
      <p role="status">{{ result.message }}</p>
      <p v-if="result.missing.length" class="missing">待补全：{{ result.missing.join('、') }}</p>
      <p v-if="dirty">已有未保存修改，请先保存并核对工作稿；检查不会覆盖修改。</p>
      <div class="actions">
        <button v-for="action in result.actions" :key="action.mode" class="primary" type="button" :disabled="disabled || dirty || loading" @click="$emit('action', action)">{{ action.label }}</button>
        <button v-if="result.status === 'draft_pending' || result.status === 'ready'" type="button" :disabled="disabled" @click="$emit('edit')">{{ result.status === 'draft_pending' ? '查看工作稿' : '手动调整规划' }}</button>
        <button v-if="['block_active', 'chapter_active'].includes(result.status)" type="button" @click="$emit('continue')">返回当前创作</button>
      </div>
    </template>
    <p v-else>检查当前进度与已有安排，再决定继续创作、补全或准备下一卷。</p>
  </section>
</template>

<style scoped>
.continuation-panel { padding:20px; border:1px solid var(--nc-border); border-radius:6px; background:var(--nc-paper); color:var(--nc-ink); scroll-margin-top:20px; }
header { display:flex; align-items:center; justify-content:space-between; gap:20px; }
h2 { margin:0; font-size:18px; font-weight:600; }
p { margin:12px 0 0; font-size:14px; line-height:1.7; }
.location,.missing { color:var(--nc-muted); font-size:13px; }
.actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:14px; }
button { min-height:40px; padding:0 18px; border:1px solid var(--nc-border); border-radius:6px; background:var(--nc-paper); color:var(--nc-ink); cursor:pointer; }
header button { min-width:170px; }
button.primary { background:var(--nc-vermilion); border-color:var(--nc-vermilion); color:var(--nc-paper); }
button:disabled { opacity:.5; cursor:default; }
button:focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:3px; }
@media(max-width:600px) { header { align-items:flex-start; flex-direction:column; gap:12px; } }
</style>
