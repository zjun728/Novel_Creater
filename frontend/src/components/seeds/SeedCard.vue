<script setup>
import { computed } from 'vue'
import { NButton, NTag } from 'naive-ui'

const props = defineProps({
  seed: { type: Object, required: true },
  readOnly: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})

const emit = defineEmits([
  'edit',
  'select',
  'archive',
  'restore',
  'permanent-delete',
])

const payload = computed(() => props.seed.payload || {})
const capabilities = computed(() => props.seed.capabilities || {})
const disabled = computed(() => props.readOnly || props.busy)
</script>

<template>
  <article
    class="seed-record"
    :class="{
      'seed-record--selected': seed.isSelected,
      'seed-record--archived': seed.status === 'archived',
    }"
  >
    <div class="seed-record__folio" aria-hidden="true">SEED</div>
    <div class="seed-record__body">
      <header>
        <div>
          <p>{{ payload.genre || '题材未填写' }}</p>
          <h3>{{ payload.title || '未命名种子' }}</h3>
        </div>
        <n-tag v-if="seed.isSelected" type="success" round>当前选定</n-tag>
        <n-tag v-else-if="seed.status === 'archived'" round>已归档</n-tag>
        <n-tag v-else :bordered="false">候选</n-tag>
      </header>

      <p class="seed-record__logline">
        {{ payload.logline || '尚未写下一句话故事。' }}
      </p>
      <dl>
        <div><dt>主角</dt><dd>{{ payload.protagonist }}</dd></div>
        <div><dt>欲望</dt><dd>{{ payload.desire }}</dd></div>
        <div><dt>压力</dt><dd>{{ payload.worldPressure }}</dd></div>
        <div><dt>差异</dt><dd>{{ payload.differentiation }}</dd></div>
      </dl>

      <p v-if="seed.provenance" class="seed-record__provenance">
        来源留痕 ·
        {{
          seed.provenance.kind === 'ai_chat'
            ? '灵感讨论'
            : seed.provenance.kind === 'market_analysis'
              ? '市场分析'
              : seed.provenance.kind === 'market_snapshot'
                ? '市场快照'
                : '作者手动'
        }}
      </p>
    </div>

    <footer>
      <n-button
        size="small"
        :disabled="disabled || !capabilities.canEdit"
        @click="emit('edit', seed)"
      >
        编辑
      </n-button>
      <n-button
        v-if="seed.status === 'candidate'"
        size="small"
        :disabled="disabled || seed.isSelected || !capabilities.canSelect"
        @click="emit('select', seed)"
      >
        {{ seed.isSelected ? '当前选定' : '立即选定' }}
      </n-button>
      <n-button
        v-if="seed.status === 'candidate' && capabilities.canArchive"
        size="small"
        quaternary
        :disabled="disabled"
        @click="emit('archive', seed)"
      >
        归档
      </n-button>
      <n-button
        v-if="seed.status === 'archived' && capabilities.canRestore"
        size="small"
        :disabled="disabled"
        @click="emit('restore', seed)"
      >
        恢复
      </n-button>
      <n-button
        v-if="capabilities.canPermanentlyDelete && !readOnly"
        size="small"
        type="error"
        quaternary
        :disabled="busy"
        @click="emit('permanent-delete', seed)"
      >
        永久删除
      </n-button>
    </footer>
  </article>
</template>

<style scoped>
.seed-record {
  position: relative;
  display: grid;
  grid-template-columns: 54px minmax(0, 1fr);
  overflow: hidden;
  border: 1px solid #d7c9b3;
  border-radius: 5px 13px 13px 5px;
  color: #302a23;
  background:
    linear-gradient(110deg, rgba(255, 253, 247, .98), rgba(247, 240, 225, .9));
  box-shadow: 0 11px 30px rgba(70, 53, 34, .06);
}
.seed-record::before {
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  background: #b7a68c;
  content: '';
}
.seed-record--selected {
  border-color: #91aa98;
  box-shadow: inset 0 0 0 1px rgba(75, 111, 89, .12), 0 13px 32px rgba(54, 82, 65, .09);
}
.seed-record--selected::before { background: #4c715c; }
.seed-record--archived { filter: saturate(.72); opacity: .8; }
.seed-record__folio {
  padding: 24px 0 0 19px;
  color: #aa9475;
  font: 700 9px Georgia, serif;
  letter-spacing: .12em;
  writing-mode: vertical-rl;
}
.seed-record__body { min-width: 0; padding: 20px 22px 16px 0; }
header { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
header p { margin: 0 0 5px; color: #963f32; font-size: 12px; font-weight: 750; letter-spacing: .08em; }
h3 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 20px; }
.seed-record__logline { margin: 10px 0 14px; color: #5e554a; font-size: 13px; line-height: 1.75; }
dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px 18px; margin: 0; }
dl div { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 8px; }
dt { color: #963f32; font-size: 12px; font-weight: 750; }
dd { margin: 0; overflow: hidden; color: #796e60; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.seed-record__provenance { margin: 14px 0 0; color: #8b7e6d; font-size: 12px; }
footer { display: flex; grid-column: 1 / -1; justify-content: flex-end; gap: 6px; padding: 10px 18px; border-top: 1px solid rgba(215, 201, 179, .72); background: rgba(244, 237, 223, .48); }
@media (max-width: 560px) {
  .seed-record { grid-template-columns: 38px minmax(0, 1fr); }
  .seed-record__folio { padding-left: 13px; }
  dl { grid-template-columns: 1fr; }
  footer { flex-wrap: wrap; justify-content: flex-start; }
}
</style>
