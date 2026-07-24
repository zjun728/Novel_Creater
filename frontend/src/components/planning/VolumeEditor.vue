<script setup>
const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  readOnly: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
})

const emit = defineEmits(['add', 'update', 'remove', 'move'])
const nodeKey = node => String(node.id || node.clientNodeKey)
const listValue = value => Array.isArray(value) ? value.join('\n') : ''
const parseList = value => String(value || '')
  .split(/\r?\n/u)
  .map(item => item.trim())
  .filter(Boolean)
const activeItems = () => props.modelValue.filter(node => node.lifecycle !== 'retired')
const activePosition = node => activeItems().findIndex(item => nodeKey(item) === nodeKey(node))
const cannotMove = (node, direction) => {
  const position = activePosition(node)
  const target = position + direction
  return position < 0 || target < 0 || target >= activeItems().length
}

function update(node, field, value) {
  if (props.readOnly || props.disabled || node.lifecycle === 'retired') return
  emit('update', nodeKey(node), {
    [field]: ['ensembleFocus', 'forbiddenEvents'].includes(field)
      ? parseList(value)
      : value,
  })
}

function add() {
  if (!props.readOnly && !props.disabled) emit('add')
}

function move(node, direction) {
  if (!props.readOnly && !props.disabled && !cannotMove(node, direction)) {
    emit('move', nodeKey(node), direction)
  }
}

function remove(node) {
  if (!props.readOnly && !props.disabled && node.lifecycle !== 'retired') {
    emit('remove', nodeKey(node))
  }
}
</script>

<template>
  <section class="planning-editor" aria-labelledby="volume-editor-heading">
    <header>
      <div>
        <p>VOLUME DESK</p>
        <h2 id="volume-editor-heading">分卷规划</h2>
      </div>
      <button v-if="!readOnly" type="button" :disabled="disabled" @click="add">新增分卷</button>
    </header>

    <p class="editor-intro">
      分卷只描述一段长期变化，不反向保存情节线或故事块 ID。
    </p>

    <article
      v-for="(volume, index) in modelValue"
      :key="nodeKey(volume)"
      class="manuscript-card"
      :class="{ retired: volume.lifecycle === 'retired' }"
    >
      <div class="card-index">
        <span>卷 {{ String(index + 1).padStart(2, '0') }}</span>
        <strong v-if="volume.lifecycle === 'retired'">已退役 · 只读保留</strong>
      </div>
      <fieldset :disabled="readOnly || disabled || volume.lifecycle === 'retired'">
        <label>
          卷名
          <input
            :value="volume.title"
            @input="update(volume, 'title', $event.target.value)"
          >
        </label>
        <label>
          核心变化
          <textarea
            :value="volume.coreChange"
            rows="3"
            @input="update(volume, 'coreChange', $event.target.value)"
          />
        </label>
        <label>
          主要压力
          <textarea
            :value="volume.mainPressure"
            rows="3"
            @input="update(volume, 'mainPressure', $event.target.value)"
          />
        </label>
        <label>
          群像焦点（每行一项）
          <textarea
            :value="listValue(volume.ensembleFocus)"
            rows="3"
            @input="update(volume, 'ensembleFocus', $event.target.value)"
          />
        </label>
        <label>
          本卷禁区（每行一项）
          <textarea
            :value="listValue(volume.forbiddenEvents)"
            rows="3"
            @input="update(volume, 'forbiddenEvents', $event.target.value)"
          />
        </label>
      </fieldset>
      <footer v-if="!readOnly && volume.lifecycle !== 'retired'">
        <button type="button" :disabled="disabled || cannotMove(volume, -1)" @click="move(volume, -1)">
          上移
        </button>
        <button
          type="button"
          :disabled="disabled || cannotMove(volume, 1)"
          @click="move(volume, 1)"
        >
          下移
        </button>
        <button type="button" class="danger" :disabled="disabled" @click="remove(volume)">
          {{ volume.id ? '退役分卷' : '撤销新增' }}
        </button>
      </footer>
    </article>

    <p v-if="!modelValue.length" class="empty-copy">
      尚无分卷。可以先手工建立第一卷，再逐步补足完整规划。
    </p>
  </section>
</template>

<style scoped>
.planning-editor { display:grid; gap:16px; }
header { display:flex; align-items:end; justify-content:space-between; gap:18px; }
header p { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.18em; }
h2 { margin:4px 0 0; font:600 28px Georgia,'Noto Serif SC',serif; }
.editor-intro,.empty-copy { margin:0; color:var(--nc-muted); line-height:1.7; }
.manuscript-card { padding:18px; border:1px solid var(--nc-border); border-radius:10px; background:color-mix(in srgb,var(--nc-paper) 96%,var(--nc-canvas)); }
.manuscript-card.retired { opacity:.68; }
.card-index { display:flex; justify-content:space-between; margin-bottom:12px; color:var(--nc-muted); font-size:12px; letter-spacing:.08em; }
fieldset { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; margin:0; padding:0; border:0; }
label { display:grid; gap:6px; color:var(--nc-muted); font-size:12px; }
label:nth-child(2),label:nth-child(3) { grid-column:span 2; }
input,textarea { width:100%; box-sizing:border-box; border:1px solid var(--nc-border); border-radius:6px; padding:10px 12px; color:var(--nc-ink); background:var(--nc-paper); font:inherit; line-height:1.6; resize:vertical; }
button { border:1px solid var(--nc-border); border-radius:6px; padding:8px 12px; color:var(--nc-ink); background:var(--nc-paper); cursor:pointer; }
button:disabled { cursor:not-allowed; opacity:.45; }
header button { border-color:var(--nc-vermilion); color:var(--nc-vermilion); }
footer { display:flex; gap:8px; margin-top:14px; }
.danger { margin-left:auto; color:var(--nc-vermilion); }
@media(max-width:700px){fieldset{grid-template-columns:1fr}label:nth-child(2),label:nth-child(3){grid-column:auto}.danger{margin-left:0}footer{flex-wrap:wrap}}
</style>
