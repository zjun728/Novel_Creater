<script setup>
import { computed, reactive, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NPopconfirm,
  NSpin,
  NTag,
} from 'naive-ui'

import { useCreationContractStore } from '@/stores/creationContractStore'
import { useSeedStore } from '@/stores/seedStore'

const props = defineProps({
  projectId: { type: String, required: true },
  hasFinalChapters: { type: Boolean, default: false },
})

const emit = defineEmits(['saved', 'selected', 'dirty-change', 'busy-change'])
const seedStore = useSeedStore()
const contractStore = useCreationContractStore()

const fields = Object.freeze([
  { key: 'title', label: '种子标题', hint: '一句能辨认方向的工作标题', rows: 1 },
  { key: 'genre', label: '题材类型', hint: '例如：历史穿越、玄幻修仙、高武', rows: 1 },
  { key: 'logline', label: '一句话故事', hint: '谁在什么处境下，为何必须做成什么事', rows: 2 },
  { key: 'protagonist', label: '主角底色', hint: '身份、性格矛盾，以及他真正擅长的事', rows: 2 },
  { key: 'desire', label: '核心欲望', hint: '主角长期不会轻易放弃的目标', rows: 2 },
  { key: 'coreConflict', label: '核心冲突', hint: '欲望与阻力如何持续互相加码', rows: 2 },
  { key: 'worldPressure', label: '世界压力', hint: '环境、规则与势力怎样不断逼迫人物选择', rows: 2 },
  { key: 'openingHook', label: '开篇抓手', hint: '最早让读者产生问题并愿意追下去的事件', rows: 2 },
  { key: 'differentiation', label: '差异化支点', hint: '它和同类故事最不一样、最值得展开的地方', rows: 2 },
])

const emptyPayload = () => Object.fromEntries(fields.map(field => [field.key, '']))
const form = reactive(emptyPayload())
const editingSeedId = ref('')
const formOpen = ref(false)
const working = ref(false)
const errorMessage = ref('')
const localDirty = ref(false)

const selectionRevision = computed(() => Math.max(
  0,
  ...seedStore.seeds.map(seed => Number(seed.selectionRevision || 0)),
  Number(seedStore.selectedSeed?.selectionRevision || 0),
))

function safeMessage(error, fallback) {
  return String(error?.message || fallback)
}

function setDirty(value) {
  if (localDirty.value === value) return
  localDirty.value = value
  if (value) contractStore.markUnsavedChanges()
  else contractStore.discardUnsavedChanges()
  emit('dirty-change', value)
}

function setWorking(value) {
  working.value = value
  emit('busy-change', value)
}

function resetForm() {
  Object.assign(form, emptyPayload())
  editingSeedId.value = ''
  formOpen.value = false
  errorMessage.value = ''
  setDirty(false)
}

function openCreate() {
  if (localDirty.value) return
  Object.assign(form, emptyPayload())
  editingSeedId.value = ''
  formOpen.value = true
  errorMessage.value = ''
  setDirty(false)
}

function openEdit(seed) {
  if (localDirty.value) return
  Object.assign(form, emptyPayload(), seed.payload || {})
  editingSeedId.value = seed.id
  formOpen.value = true
  errorMessage.value = ''
  setDirty(false)
}

function markFormDirty() {
  setDirty(true)
}

function normalizedPayload() {
  const payload = Object.fromEntries(
    fields.map(field => [field.key, String(form[field.key] || '').trim()]),
  )
  const missing = fields.find(field => !payload[field.key])
  if (missing) throw new Error(`请填写“${missing.label}”`)
  return payload
}

async function saveSeed() {
  if (props.hasFinalChapters) return
  errorMessage.value = ''
  setWorking(true)
  try {
    const payload = normalizedPayload()
    if (editingSeedId.value) {
      const seed = seedStore.seeds.find(item => item.id === editingSeedId.value)
      if (!seed) throw new Error('当前种子已变化，请刷新后重试')
      await seedStore.updateSeed(props.projectId, seed.id, {
        payload,
        expectedSeedRevision: seed.revision,
        expectedSelectionRevision: selectionRevision.value,
      })
    } else {
      await seedStore.createSeed(props.projectId, payload)
    }
    resetForm()
  } catch (error) {
    errorMessage.value = safeMessage(error, '种子保存失败')
  } finally {
    setWorking(false)
  }
}

async function removeSeed(seed) {
  if (props.hasFinalChapters || localDirty.value) return
  errorMessage.value = ''
  setWorking(true)
  try {
    await seedStore.deleteSeed(props.projectId, seed.id, {
      expectedSeedRevision: seed.revision,
      expectedSelectionRevision: selectionRevision.value,
    })
    if (editingSeedId.value === seed.id) resetForm()
  } catch (error) {
    errorMessage.value = safeMessage(error, '种子删除失败')
  } finally {
    setWorking(false)
  }
}

async function selectSeed(seed) {
  if (props.hasFinalChapters || seed.isSelected || localDirty.value) return
  errorMessage.value = ''
  setWorking(true)
  try {
    const selected = await seedStore.selectSeed(props.projectId, {
      seedId: seed.id,
      expectedSeedRevision: seed.revision,
      expectedSelectionRevision: selectionRevision.value,
    })
    setDirty(false)
    emit('selected', selected)
    emit('saved', { stage: 'seed', seed: selected })
  } catch (error) {
    errorMessage.value = safeMessage(error, '种子选定失败')
  } finally {
    setWorking(false)
  }
}

async function loadSeeds() {
  errorMessage.value = ''
  try {
    await seedStore.refresh(props.projectId)
  } catch (error) {
    errorMessage.value = safeMessage(error, '种子列表加载失败')
  }
}

watch(() => props.projectId, loadSeeds, { immediate: true })
</script>

<template>
  <section class="seed-ledger" aria-labelledby="seed-step-heading">
    <header class="step-heading">
      <div>
        <p class="folio">第一纸 · 立意</p>
        <h3 id="seed-step-heading">选定这部长篇真正要写的故事</h3>
        <p>种子不是大纲。它只固定九项最初承诺，后续发动机、风格与素材都从这里生长。</p>
      </div>
      <n-button
        class="cinnabar-action"
        :disabled="props.hasFinalChapters || working || localDirty"
        @click="openCreate"
      >
        新增种子
      </n-button>
    </header>

    <n-alert v-if="props.hasFinalChapters" type="warning" :bordered="false" class="ledger-alert">
      项目已有定稿章节，种子池与选定结果已锁定。这里保留为只读档案，避免后续事实链漂移。
    </n-alert>
    <n-alert v-if="errorMessage" type="error" class="ledger-alert" closable @close="errorMessage = ''">
      {{ errorMessage }}
    </n-alert>

    <n-spin :show="seedStore.refreshing || working">
      <div v-if="seedStore.seeds.length" class="seed-stack">
        <article
          v-for="(seed, index) in seedStore.seeds"
          :key="seed.id"
          class="seed-slip"
          :class="{ 'seed-slip--selected': seed.isSelected }"
        >
          <div class="slip-number">{{ String(index + 1).padStart(2, '0') }}</div>
          <div class="slip-copy">
            <div class="slip-title">
              <h4>{{ seed.payload?.title || '未命名种子' }}</h4>
              <n-tag v-if="seed.isSelected" type="success" round size="small">已入册</n-tag>
              <n-tag v-else :bordered="false" size="small">候选</n-tag>
            </div>
            <p class="logline">{{ seed.payload?.logline }}</p>
            <dl class="seed-facts">
              <div><dt>主角</dt><dd>{{ seed.payload?.protagonist }}</dd></div>
              <div><dt>欲望</dt><dd>{{ seed.payload?.desire }}</dd></div>
              <div><dt>压力</dt><dd>{{ seed.payload?.worldPressure }}</dd></div>
              <div><dt>差异</dt><dd>{{ seed.payload?.differentiation }}</dd></div>
            </dl>
          </div>
          <div class="slip-actions">
            <n-button size="small" :disabled="props.hasFinalChapters || localDirty" @click="openEdit(seed)">校订</n-button>
            <n-popconfirm
              positive-text="确认删除"
              negative-text="保留"
              @positive-click="removeSeed(seed)"
            >
              <template #trigger>
                <n-button size="small" quaternary type="error" :disabled="props.hasFinalChapters || localDirty">删除</n-button>
              </template>
              删除后不能作为本书方向使用，确定继续吗？
            </n-popconfirm>
            <n-button
              size="small"
              :type="seed.isSelected ? 'default' : 'primary'"
              :disabled="props.hasFinalChapters || seed.isSelected || localDirty"
              @click="selectSeed(seed)"
            >
              {{ seed.isSelected ? '当前选定' : '选定并继续' }}
            </n-button>
          </div>
        </article>
      </div>
      <n-empty v-else description="种子池还是空的。先写下一个值得展开百万字的故事方向。" class="empty-ledger" />
    </n-spin>

    <aside v-if="formOpen" class="seed-form-sheet" aria-label="种子九字段编辑表">
      <div class="form-title">
        <div>
          <span>SEED RECORD / 9 FIELDS</span>
          <h4>{{ editingSeedId ? '校订种子' : '登记新种子' }}</h4>
        </div>
        <i aria-hidden="true">审</i>
      </div>
      <n-form label-placement="top" :show-feedback="false" class="field-grid">
        <n-form-item
          v-for="field in fields"
          :key="field.key"
          :label="field.label"
          :class="{ 'field-wide': field.rows > 1 }"
        >
          <n-input
            v-model:value="form[field.key]"
            :type="field.rows > 1 ? 'textarea' : 'text'"
            :autosize="field.rows > 1 ? { minRows: field.rows, maxRows: 5 } : undefined"
            :placeholder="field.hint"
            maxlength="2000"
            show-count
            :disabled="working || props.hasFinalChapters"
            @update:value="markFormDirty"
          />
        </n-form-item>
      </n-form>
      <div class="form-actions">
        <span>所有九项均为正式种子内容；字段变化只留在本页，点击保存才写入。</span>
        <div>
          <n-button :disabled="working" @click="resetForm">取消</n-button>
          <n-button type="primary" :loading="working" :disabled="props.hasFinalChapters || !localDirty" @click="saveSeed">
            保存种子
          </n-button>
        </div>
      </div>
    </aside>
  </section>
</template>

<style scoped>
.seed-ledger {
  --paper: #f5efdf;
  --paper-deep: #e8ddc5;
  --ink: #29251f;
  --muted: #756b5d;
  --cinnabar: #9f3e31;
  --jade: #476b5d;
  color: var(--ink);
}
.step-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 28px; padding: 4px 2px 22px; border-bottom: 1px solid #cfc1a8; }
.step-heading > div { max-width: 760px; }
.folio { margin: 0 0 7px; color: var(--cinnabar); font-size: 11px; font-weight: 800; letter-spacing: .18em; }
.step-heading h3 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(22px, 3.5vw, 32px); font-weight: 650; letter-spacing: -.02em; }
.step-heading p:last-child { margin: 10px 0 0; color: var(--muted); font-size: 13px; line-height: 1.8; }
.ledger-alert { margin-top: 16px; background: rgba(255, 252, 244, .72); }
.seed-stack { display: grid; gap: 12px; margin-top: 18px; }
.seed-slip { position: relative; display: grid; grid-template-columns: 48px minmax(0, 1fr) auto; gap: 18px; padding: 21px 22px; overflow: hidden; border: 1px solid #d4c7af; border-radius: 4px 12px 12px 4px; background: linear-gradient(105deg, rgba(255, 253, 246, .96), rgba(246, 239, 223, .8)); box-shadow: 0 9px 24px rgba(74, 61, 42, .06); }
.seed-slip::before { position: absolute; inset: 0 auto 0 0; width: 4px; background: #baa98d; content: ''; }
.seed-slip--selected { border-color: #9aaf9e; box-shadow: inset 0 0 0 1px rgba(71, 107, 93, .16), 0 12px 28px rgba(52, 79, 67, .09); }
.seed-slip--selected::before { background: var(--jade); }
.slip-number { color: #a89475; font-family: Georgia, serif; font-size: 14px; letter-spacing: .08em; }
.slip-title { display: flex; align-items: center; gap: 10px; }
.slip-title h4 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 19px; font-weight: 650; }
.logline { margin: 8px 0 14px; color: #554d42; font-size: 14px; line-height: 1.75; }
.seed-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px 18px; margin: 0; }
.seed-facts div { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 7px; }
.seed-facts dt { color: var(--cinnabar); font-size: 11px; font-weight: 700; }
.seed-facts dd { margin: 0; overflow: hidden; color: var(--muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.slip-actions { display: flex; align-items: center; align-self: center; gap: 6px; }
.empty-ledger { margin-top: 18px; padding: 54px 20px; border: 1px dashed #cbbda4; background: rgba(255, 252, 244, .45); }
.seed-form-sheet { position: relative; margin-top: 20px; padding: clamp(20px, 4vw, 34px); border: 1px solid #cbbba0; background: radial-gradient(circle at 90% 4%, rgba(159, 62, 49, .05), transparent 22%), rgba(255, 252, 244, .92); box-shadow: 0 18px 45px rgba(67, 55, 36, .09); }
.form-title { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 22px; }
.form-title span { color: #917a59; font-size: 10px; font-weight: 800; letter-spacing: .16em; }
.form-title h4 { margin: 5px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 23px; }
.form-title i { display: grid; width: 45px; height: 45px; place-items: center; border: 2px solid var(--cinnabar); color: var(--cinnabar); font-family: 'Noto Serif SC', serif; font-size: 22px; font-style: normal; transform: rotate(5deg); }
.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 20px; }
.field-wide { grid-column: span 2; }
.form-actions { display: flex; align-items: center; justify-content: space-between; gap: 22px; margin-top: 22px; padding-top: 17px; border-top: 1px solid #ddd0ba; }
.form-actions > span { color: var(--muted); font-size: 11px; line-height: 1.6; }
.form-actions > div { display: flex; flex: 0 0 auto; gap: 8px; }
@media (max-width: 860px) {
  .seed-slip { grid-template-columns: 34px 1fr; }
  .slip-actions { grid-column: 2; justify-content: flex-start; }
}
@media (max-width: 640px) {
  .step-heading, .form-actions { align-items: flex-start; flex-direction: column; }
  .seed-slip { grid-template-columns: 1fr; }
  .slip-number, .slip-actions { grid-column: 1; }
  .seed-facts, .field-grid { grid-template-columns: 1fr; }
  .field-wide { grid-column: span 1; }
  .slip-actions { flex-wrap: wrap; }
}
</style>
