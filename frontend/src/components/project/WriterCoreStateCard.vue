<script setup>
import { computed } from 'vue'
import { NTag } from 'naive-ui'

const props = defineProps({
  state: { type: Object, required: true },
})

const inSync = computed(() => props.state.projectionInSync === true)
</script>

<template>
  <section class="state-card" :class="{ 'state-card--mismatch': !inSync }" aria-labelledby="writer-core-state-heading">
    <header class="state-header">
      <div>
        <p class="state-kicker">Writer Core / Foundation</p>
        <h2 id="writer-core-state-heading">写作内核状态</h2>
      </div>
      <n-tag :type="inSync ? 'success' : 'error'" round>
        {{ inSync ? '状态同步' : '状态不同步' }}
      </n-tag>
    </header>

    <dl class="state-grid">
      <div>
        <dt>Schema</dt>
        <dd>{{ state.schemaVersion }}</dd>
      </div>
      <div>
        <dt>Canon</dt>
        <dd>Canon {{ state.canonHeadRevision }}</dd>
      </div>
      <div>
        <dt>Projection</dt>
        <dd>Projection {{ state.projectionHeadRevision }}</dd>
      </div>
    </dl>

    <p class="state-note" aria-live="polite">
      {{ inSync
        ? '唯一事实源与确定性投影位于同一 revision，可以安全进入下一阶段建设。'
        : 'Canon 与投影 revision 不一致。系统已停止写作入口，请先诊断并重建投影。' }}
    </p>
  </section>
</template>

<style scoped>
.state-card {
  --state-accent: #3f765c;
  padding: 22px;
  border: 1px solid #d8cfbd;
  border-left: 4px solid var(--state-accent);
  border-radius: 12px;
  background: #fffdf8;
  box-shadow: 0 12px 34px rgba(67, 57, 42, .07);
}
.state-card--mismatch { --state-accent: #a4473d; background: #fff9f7; }
.state-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.state-kicker { margin: 0; color: #8b7453; font-size: 10px; font-weight: 750; letter-spacing: .18em; text-transform: uppercase; }
h2 { margin: 4px 0 0; color: #302b24; font-family: Georgia, 'Noto Serif SC', serif; font-size: 21px; font-weight: 650; }
.state-grid { display: grid; grid-template-columns: 1.4fr repeat(2, 1fr); margin: 20px 0 0; border-top: 1px solid #e8e1d4; border-bottom: 1px solid #e8e1d4; }
.state-grid div { min-width: 0; padding: 16px 14px; border-right: 1px solid #e8e1d4; }
.state-grid div:first-child { padding-left: 0; }
.state-grid div:last-child { border-right: 0; }
dt { color: #887d6e; font-size: 11px; letter-spacing: .08em; text-transform: uppercase; }
dd { overflow: hidden; margin: 5px 0 0; color: #2f2b25; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 14px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.state-note { margin: 15px 0 0; color: #6d6356; font-size: 13px; line-height: 1.7; }
@media (max-width: 680px) {
  .state-grid { grid-template-columns: 1fr; }
  .state-grid div, .state-grid div:first-child { padding: 12px 0; border-right: 0; border-bottom: 1px solid #e8e1d4; }
  .state-grid div:last-child { border-bottom: 0; }
}
</style>
