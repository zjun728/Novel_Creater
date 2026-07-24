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
const controlDisabled = node => (
  props.readOnly || props.disabled || node.lifecycle === 'retired'
)
const cannotMove = (node, direction) => {
  const position = activePosition(node)
  const target = position + direction
  return position < 0 || target < 0 || target >= activeItems().length
}

function update(node, field, value) {
  if (controlDisabled(node)) return
  emit('update', nodeKey(node), {
    [field]: field === 'relatedCharacters' ? parseList(value) : value,
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
  <section class="planning-editor" aria-labelledby="plot-editor-heading">
    <header>
      <div>
        <p>PLOT DESK</p>
        <h2 id="plot-editor-heading">情节线规划</h2>
      </div>
      <button v-if="!readOnly" type="button" :disabled="disabled" @click="add">新增情节线</button>
    </header>

    <p class="editor-intro">
      情节线记录问题、走向与回报，不反向保存故事块 ID。
    </p>

    <article
      v-for="(plot, index) in modelValue"
      :key="nodeKey(plot)"
      class="manuscript-card"
      :class="{ retired: plot.lifecycle === 'retired' }"
    >
      <div class="card-index">
        <span>线 {{ String(index + 1).padStart(2, '0') }}</span>
        <strong v-if="plot.lifecycle === 'retired'">已退役 · 只读保留</strong>
      </div>
      <fieldset :disabled="readOnly || disabled || plot.lifecycle === 'retired'">
        <label>
          情节线名称
          <input
            :value="plot.title"
            :disabled="controlDisabled(plot)"
            @input="update(plot, 'title', $event.target.value)"
          >
        </label>
        <label>
          类型
          <select
            :value="plot.plotType"
            :disabled="controlDisabled(plot)"
            @change="update(plot, 'plotType', $event.target.value)"
          >
            <option value="">请选择</option>
            <option value="main">主线</option>
            <option value="character">人物线</option>
            <option value="relationship">关系线</option>
            <option value="conflict">冲突线</option>
            <option value="mystery">悬念线</option>
            <option value="other">其他</option>
          </select>
        </label>
        <label>
          故事问题
          <textarea
            :value="plot.storyQuestion"
            :disabled="controlDisabled(plot)"
            rows="3"
            @input="update(plot, 'storyQuestion', $event.target.value)"
          />
        </label>
        <label>
          未来走向
          <textarea
            :value="plot.futureDirection"
            :disabled="controlDisabled(plot)"
            rows="3"
            @input="update(plot, 'futureDirection', $event.target.value)"
          />
        </label>
        <label>
          预期回报
          <textarea
            :value="plot.expectedPayoff"
            :disabled="controlDisabled(plot)"
            rows="3"
            @input="update(plot, 'expectedPayoff', $event.target.value)"
          />
        </label>
        <label>
          相关人物（每行一项）
          <textarea
            :value="listValue(plot.relatedCharacters)"
            :disabled="controlDisabled(plot)"
            rows="3"
            @input="update(plot, 'relatedCharacters', $event.target.value)"
          />
        </label>
      </fieldset>
      <footer v-if="!readOnly && plot.lifecycle !== 'retired'">
        <button type="button" :disabled="disabled || cannotMove(plot, -1)" @click="move(plot, -1)">上移</button>
        <button type="button" :disabled="disabled || cannotMove(plot, 1)" @click="move(plot, 1)">下移</button>
        <button type="button" class="danger" :disabled="disabled" @click="remove(plot)">
          {{ plot.id ? '退役情节线' : '撤销新增' }}
        </button>
      </footer>
    </article>

    <p v-if="!modelValue.length" class="empty-copy">
      尚无情节线。先写清读者会持续追问的问题，后续再与故事块衔接。
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
label:nth-child(n+3) { grid-column:span 2; }
input,select,textarea { width:100%; box-sizing:border-box; border:1px solid var(--nc-border); border-radius:6px; padding:10px 12px; color:var(--nc-ink); background:var(--nc-paper); font:inherit; line-height:1.6; resize:vertical; }
button { border:1px solid var(--nc-border); border-radius:6px; padding:8px 12px; color:var(--nc-ink); background:var(--nc-paper); cursor:pointer; }
button:disabled { cursor:not-allowed; opacity:.45; }
header button { border-color:var(--nc-vermilion); color:var(--nc-vermilion); }
footer { display:flex; gap:8px; margin-top:14px; }
.danger { margin-left:auto; color:var(--nc-vermilion); }
@media(max-width:700px){fieldset{grid-template-columns:1fr}label:nth-child(n+3){grid-column:auto}.danger{margin-left:0}footer{flex-wrap:wrap}}
</style>
