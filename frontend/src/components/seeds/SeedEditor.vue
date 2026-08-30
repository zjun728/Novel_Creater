<script setup>
import { reactive, watch } from 'vue'
import { NButton, NInput } from 'naive-ui'

const props = defineProps({
  seed: { type: Object, default: null },
  initialPayload: { type: Object, default: null },
  busy: { type: Boolean, default: false },
  readOnly: { type: Boolean, default: false },
})

const emit = defineEmits(['save', 'cancel'])

const fields = Object.freeze([
  { key: 'title', label: '种子标题', hint: '能辨认本书方向的工作标题', rows: 1 },
  { key: 'genre', label: '题材类型', hint: '例如：历史穿越、玄幻修仙、高武', rows: 1 },
  { key: 'logline', label: '一句话故事', hint: '谁在何种处境下，为什么必须做成什么事', rows: 2 },
  { key: 'targetAudience', label: '目标读者', hint: '最希望持续追读这部长篇小说的读者', rows: 2, optional: true },
  { key: 'protagonist', label: '主角底色', hint: '身份、性格矛盾与真正擅长的事', rows: 2 },
  { key: 'desire', label: '核心欲望', hint: '主角长期不会轻易放弃的目标', rows: 2 },
  { key: 'coreConflict', label: '核心冲突', hint: '欲望与阻力如何持续互相加码', rows: 2 },
  { key: 'worldPressure', label: '世界压力', hint: '环境、规则与势力怎样逼迫人物选择', rows: 2 },
  { key: 'openingHook', label: '开篇抓手', hint: '最早使读者产生问题的具体事件', rows: 2 },
  { key: 'differentiation', label: '差异化支点', hint: '和同类故事最不一样、最值得展开之处', rows: 2 },
  { key: 'storyPromise', label: '故事承诺', hint: '读者长期跟读能稳定获得什么体验', rows: 2, optional: true },
  { key: 'longFormPotential', label: '长篇发展空间', hint: '人物、地图、势力和冲突如何支撑二百万字以上', rows: 2, optional: true },
  { key: 'marketBasis', label: '市场依据', hint: '来自公开证据或作者判断的选题依据', rows: 2, optional: true },
])

const form = reactive(Object.fromEntries(fields.map(field => [field.key, ''])))

watch(
  () => [props.seed, props.initialPayload],
  () => {
    const payload = props.seed?.payload || props.initialPayload || {}
    for (const field of fields) form[field.key] = String(payload[field.key] || '')
  },
  { immediate: true, deep: true },
)

function save() {
  const payload = Object.fromEntries(fields.map(field => [
    field.key,
    String(form[field.key] || '').trim(),
  ]))
  const missing = fields.find(field => !field.optional && !payload[field.key])
  if (missing) {
    emit('save', { error: `请填写“${missing.label}”` })
    return
  }
  emit('save', { payload })
}
</script>

<template>
  <section class="seed-editor" aria-label="种子完整字段编辑器">
    <header>
      <div>
        <p>SEED RECORD / 13 FIELDS</p>
        <h2>{{ seed ? '校订创作种子' : '登记候选种子' }}</h2>
      </div>
      <span aria-hidden="true">审</span>
    </header>
    <div class="seed-editor__grid">
      <label
        v-for="field in fields"
        :key="field.key"
        :class="{ 'seed-editor__wide': field.rows > 1 }"
      >
        <strong>{{ field.label }}<small v-if="field.optional">（可选）</small></strong>
        <n-input
          v-model:value="form[field.key]"
          :type="field.rows > 1 ? 'textarea' : 'text'"
          :autosize="field.rows > 1 ? { minRows: field.rows, maxRows: 5 } : undefined"
          :placeholder="field.hint"
          maxlength="2000"
          show-count
          :disabled="busy || readOnly"
        />
      </label>
    </div>
    <footer>
      <p>内容只保留在当前表单中；点击保存后才写入一个正式种子版本。</p>
      <div>
        <n-button :disabled="busy" @click="emit('cancel')">取消</n-button>
        <n-button
          type="primary"
          :loading="busy"
          :disabled="readOnly"
          @click="save"
        >
          保存种子
        </n-button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.seed-editor {
  margin-top: 20px;
  padding: clamp(20px, 4vw, 34px);
  border: 1px solid #cbbba0;
  color: #302a23;
  background:
    radial-gradient(circle at 92% 5%, rgba(148, 57, 45, .055), transparent 25%),
    rgba(255, 252, 244, .95);
  box-shadow: 0 18px 44px rgba(67, 52, 34, .08);
}
header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 24px; }
header p { margin: 0; color: #987a54; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
h2 { margin: 6px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 24px; }
header > span { display: grid; width: 45px; height: 45px; place-items: center; border: 2px solid #963f32; color: #963f32; font-family: 'Noto Serif SC', serif; font-size: 22px; transform: rotate(5deg); }
.seed-editor__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 17px 20px; }
label { display: grid; gap: 7px; }
label strong { color: #554b40; font-size: 12px; }
.seed-editor__wide { grid-column: span 2; }
footer { display: flex; align-items: center; justify-content: space-between; gap: 20px; margin-top: 24px; padding-top: 17px; border-top: 1px solid #ded1bb; }
footer p { max-width: 58ch; margin: 0; color: #807465; font-size: 12px; line-height: 1.65; }
footer div { display: flex; flex: 0 0 auto; gap: 8px; }
@media (max-width: 680px) {
  .seed-editor__grid { grid-template-columns: 1fr; }
  .seed-editor__wide { grid-column: span 1; }
  footer { align-items: flex-start; flex-direction: column; }
}
</style>
