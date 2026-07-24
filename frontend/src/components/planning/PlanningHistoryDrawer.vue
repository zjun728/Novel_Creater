<script setup>
defineProps({
  open: { type: Boolean, default: false },
  history: { type: Array, default: () => [] },
})

defineEmits(['close'])
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="drawer-backdrop" @click.self="$emit('close')">
      <aside class="history-drawer" aria-label="规划修订历史">
        <header>
          <div>
            <p>IMMUTABLE ARCHIVE</p>
            <h2>规划修订历史</h2>
          </div>
          <button type="button" @click="$emit('close')">关闭</button>
        </header>
        <p class="read-only-note">只读档案：历史修订不能克隆、编辑或覆盖。</p>
        <ol v-if="history.length">
          <li v-for="item in history" :key="item.planningRevisionId || item.revision">
            <span>R{{ item.revision }}</span>
            <strong>{{ item.content?.volumes?.length || 0 }} 卷 · {{ item.content?.plots?.length || 0 }} 条情节线</strong>
            <small>{{ item.createdAt || item.confirmedAt || '已确认修订' }}</small>
          </li>
        </ol>
        <p v-else class="empty-copy">尚无已确认规划修订。</p>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.drawer-backdrop { position:fixed; z-index:36; inset:0; display:flex; justify-content:flex-end; background:color-mix(in srgb,var(--nc-ink) 32%,transparent); }
.history-drawer { width:min(460px,100%); height:100%; overflow:auto; padding:28px; color:var(--nc-ink); background:var(--nc-paper); box-shadow:-20px 0 50px color-mix(in srgb,var(--nc-ink) 18%,transparent); }
header { display:flex; align-items:start; justify-content:space-between; gap:20px; padding-bottom:16px; border-bottom:2px solid var(--nc-vermilion); }
header p { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.17em; }
h2 { margin:5px 0 0; font:600 26px Georgia,'Noto Serif SC',serif; }
button { border:1px solid var(--nc-border); border-radius:6px; padding:8px 12px; color:var(--nc-ink); background:var(--nc-paper); }
.read-only-note,.empty-copy { color:var(--nc-muted); line-height:1.7; }
ol { display:grid; gap:10px; margin:18px 0 0; padding:0; list-style:none; }
li { display:grid; grid-template-columns:auto 1fr; gap:4px 12px; padding:14px 0; border-bottom:1px solid var(--nc-border); }
li span { grid-row:span 2; color:var(--nc-vermilion); font:600 22px Georgia,serif; }
li strong { font-size:14px; }
li small { color:var(--nc-muted); }
</style>
