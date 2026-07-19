<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCheckbox,
  NEmpty,
  NSelect,
  NSkeleton,
  NTag,
} from 'naive-ui'

import { useCorpusStore } from '@/stores/corpusStore'
import { useCreationAssetStore } from '@/stores/creationAssetStore'
import { useCreationContractStore } from '@/stores/creationContractStore'

const props = defineProps({
  projectId: { type: String, required: true },
})

const emit = defineEmits(['saved', 'dirty-change', 'back'])
const assetStore = useCreationAssetStore()
const contractStore = useCreationContractStore()
const corpusStore = useCorpusStore()

const loading = ref(false)
const loadError = ref('')
const saveError = ref('')
const selectedExperienceIds = ref([])
const selectedCorpusIds = ref([])
const explicitExperienceRefs = ref({})
const explicitCorpusRefs = ref({})
let loadEpoch = 0

const draftValues = computed(() => contractStore.draft?.draft || null)
const recommendedCards = computed(() => assetStore.recommendations?.experienceCards || [])
const experienceOptions = computed(() => {
  const options = assetStore.experienceCards.map(card => ({
    label: `${card.title} · ${card.category}`,
    value: card.id,
  }))
  for (const frozen of draftValues.value?.experienceCardRefs || []) {
    if (!options.some(option => option.value === frozen.id)) {
      options.push({ label: `已冻结经验卡 · r${frozen.revision}`, value: frozen.id })
    }
  }
  return options
})
const selectedExperienceCards = computed(() => selectedExperienceIds.value
  .map(cardById)
  .filter(Boolean))
const selectedCorpusSources = computed(() => selectedCorpusIds.value
  .map(sourceById)
  .filter(Boolean))
const visibleCorpusSources = computed(() => {
  const rows = [...corpusStore.sources]
  for (const frozen of draftValues.value?.corpusSourceRefs || []) {
    if (!rows.some(source => source.id === frozen.id)) {
      rows.push({
        ...frozen,
        name: '已冻结语料',
        relativePath: '当前目录未列出',
        shortHash: String(frozen.contentHash || '').slice(0, 12),
        encoding: '—',
        chapterCount: '—',
        state: 'frozen',
      })
    }
  }
  return rows
})

const REASON_LABELS = Object.freeze({
  'category-profile': '类别适配',
  'asset-text-overlap': '故事信号匹配',
  'default-rank': '基础优先级',
})

function reasonLabel(code) {
  return REASON_LABELS[code] || code
}

function cardById(id) {
  if (!id) return null
  return assetStore.experienceCards.find(card => card.id === id)
    || recommendedCards.value.find(card => card.id === id)
    || draftValues.value?.experienceCardRefs?.find(card => card.id === id)
    || null
}

function sourceById(id) {
  if (!id) return null
  return corpusStore.sources.find(source => source.id === id)
    || draftValues.value?.corpusSourceRefs?.find(source => source.id === id)
    || null
}

function assetRef(asset) {
  if (!asset?.id || !Number.isInteger(asset.revision) || !asset.contentHash) {
    throw new TypeError('经验卡版本信息不完整，请重新加载')
  }
  return {
    id: asset.id,
    revision: asset.revision,
    contentHash: asset.contentHash,
  }
}

function exactExperienceRef(id) {
  return explicitExperienceRefs.value[id]
    || draftValues.value?.experienceCardRefs?.find(item => item.id === id)
    || assetRef(cardById(id))
}

function exactCorpusRef(id) {
  return explicitCorpusRefs.value[id]
    || draftValues.value?.corpusSourceRefs?.find(item => item.id === id)
    || corpusStore.toContractRef(sourceById(id), 'author')
}

function markDirty() {
  contractStore.markUnsavedChanges()
  emit('dirty-change', true)
}

function uniqueIds(values) {
  return [...new Set((values || []).filter(Boolean))]
}

function updateExperienceSelection(values) {
  if (contractStore.saving) return
  const next = uniqueIds(values)
  const previous = new Set(selectedExperienceIds.value)
  const overrides = { ...explicitExperienceRefs.value }
  for (const id of next) {
    if (!previous.has(id)) overrides[id] = assetRef(cardById(id))
  }
  for (const id of previous) {
    if (!next.includes(id)) delete overrides[id]
  }
  explicitExperienceRefs.value = overrides
  selectedExperienceIds.value = next
  saveError.value = ''
  markDirty()
}

function toggleExperience(id) {
  if (contractStore.saving) return
  const selected = new Set(selectedExperienceIds.value)
  if (selected.has(id)) selected.delete(id)
  else selected.add(id)
  updateExperienceSelection([...selected])
}

function toggleCorpus(id, checked) {
  if (contractStore.saving) return
  const selected = new Set(selectedCorpusIds.value)
  const overrides = { ...explicitCorpusRefs.value }
  if (checked) {
    selected.add(id)
    overrides[id] = corpusStore.toContractRef(sourceById(id), 'author')
  } else {
    selected.delete(id)
    delete overrides[id]
  }
  explicitCorpusRefs.value = overrides
  selectedCorpusIds.value = [...selected]
  saveError.value = ''
  markDirty()
}

function hydrateFromDraft(draft) {
  explicitExperienceRefs.value = {}
  explicitCorpusRefs.value = {}
  if (draft?.draftStage === 'assets') {
    selectedExperienceIds.value = uniqueIds(
      (draft.experienceCardRefs || []).map(item => item.id),
    )
    selectedCorpusIds.value = uniqueIds(
      (draft.corpusSourceRefs || []).map(item => item.id),
    )
    return
  }
  selectedExperienceIds.value = uniqueIds(recommendedCards.value.map(item => item.id))
  selectedCorpusIds.value = []
}

async function initialize(projectId, { reloadContract = false } = {}) {
  if (contractStore.saving) return
  const epoch = ++loadEpoch
  loading.value = true
  loadError.value = ''
  saveError.value = ''
  try {
    if (reloadContract || contractStore.projectId !== projectId || !contractStore.draft) {
      await contractStore.load(projectId)
    }
    const draft = contractStore.draft?.draft
    if (!draft?.engineOptionId || !draft?.primaryStyleRef) {
      throw new Error('请先完成并保存风格契约。')
    }
    await Promise.all([
      assetStore.loadExperienceCards(),
      assetStore.loadRecommendations(projectId, draft.engineOptionId, draft),
      corpusStore.loadSources(),
    ])
    if (epoch !== loadEpoch) return
    hydrateFromDraft(draft)
    contractStore.discardUnsavedChanges()
    emit('dirty-change', false)
  } catch (error) {
    if (epoch === loadEpoch) loadError.value = error?.message || '创作资产范围加载失败'
  } finally {
    if (epoch === loadEpoch) loading.value = false
  }
}

async function saveAndContinue() {
  if (contractStore.saving || contractStore.requiresReload) return
  saveError.value = ''
  const current = draftValues.value
  if (!current?.engineOptionId || !current?.engineHash || !current?.primaryStyleRef) {
    saveError.value = '风格草稿已失效，请返回上一步重新加载。'
    return
  }

  try {
    const experienceCardRefs = selectedExperienceIds.value.map(exactExperienceRef)
    const corpusSourceRefs = selectedCorpusIds.value.map(exactCorpusRef)
    const saved = await contractStore.saveDraft(props.projectId, {
      schemaVersion: 'contract-draft-v2',
      draftStage: 'assets',
      engineOptionId: current.engineOptionId,
      engineHash: current.engineHash,
      channelProfileKey: current.channelProfileKey,
      genreProfileKey: current.genreProfileKey,
      qualityCharterVersion: current.qualityCharterVersion,
      totalWordRange: current.totalWordRange,
      chapterCapacityPolicy: current.chapterCapacityPolicy,
      primaryStyleRef: current.primaryStyleRef,
      secondaryStyleRef: current.secondaryStyleRef || null,
      likes: Array.isArray(current.likes) ? [...current.likes] : [],
      dislikes: Array.isArray(current.dislikes) ? [...current.dislikes] : [],
      experienceCardRefs,
      corpusSourceRefs,
    })
    if (contractStore.draft !== saved) {
      saveError.value = '保存期间素材范围发生了变化，请核对后再次保存。'
      return
    }
    emit('dirty-change', false)
    emit('saved')
  } catch (error) {
    saveError.value = error?.message || '创作资产范围保存失败'
  }
}

watch(() => props.projectId, projectId => initialize(String(projectId || '')), { immediate: true })

onBeforeUnmount(() => {
  loadEpoch += 1
})
</script>

<template>
  <section class="contract-step" aria-labelledby="asset-step-heading">
    <header class="step-heading">
      <div>
        <p class="step-kicker">STEP 04 · REFERENCE SCOPE</p>
        <h3 id="asset-step-heading">只圈定可用范围，不把资料塞满提示词</h3>
        <p>经验卡指导写作方法，语料提供作者允许参考的来源。这里可以零选或多选；实际检索会在后续按场景只取最相关内容。</p>
      </div>
      <span class="step-number" aria-hidden="true">04</span>
    </header>

    <n-alert v-if="loadError" type="error" class="state-alert" title="创作资产未能加载">
      {{ loadError }}
      <template #action><n-button size="small" :disabled="contractStore.saving" @click="initialize(props.projectId, { reloadContract: true })">重新加载</n-button></template>
    </n-alert>

    <template v-if="loading">
      <div class="loading-grid" aria-busy="true" aria-label="正在加载经验卡和本机语料">
        <section><n-skeleton text width="30%" /><n-skeleton text :repeat="5" /></section>
        <section><n-skeleton text width="38%" /><n-skeleton text :repeat="5" /></section>
      </div>
    </template>

    <template v-else-if="!loadError">
      <section class="asset-section" aria-labelledby="experience-scope-heading">
        <div class="section-title-row">
          <div>
            <span>经验卡范围</span>
            <h4 id="experience-scope-heading">让方法服务故事，而不是变成规则清单</h4>
          </div>
          <strong>{{ selectedExperienceIds.length }} 张已选</strong>
        </div>

        <n-alert type="info" :bordered="false" class="scope-note">
          下方是系统按种子和故事发动机给出的少量推荐。点击卡片可加入或移出范围；后续单次生成仍只会检索最相关的 2–4 张。
        </n-alert>

        <n-empty v-if="!recommendedCards.length" description="当前没有经验卡推荐；仍可从完整卡库手动选择" class="empty-state" />
        <div v-else class="card-grid">
          <article
            v-for="card in recommendedCards"
            :key="card.id"
            class="experience-card"
            :class="{ 'experience-card--selected': selectedExperienceIds.includes(card.id) }"
          >
            <div class="card-topline">
              <n-tag size="small" :bordered="false">{{ card.category }}</n-tag>
              <span>{{ selectedExperienceIds.includes(card.id) ? '已纳入' : '未纳入' }}</span>
            </div>
            <h5>{{ card.title }}</h5>
            <p class="method">{{ card.method }}</p>
            <div class="reason-list" aria-label="推荐原因">
              <n-tag v-for="code in card.reasonCodes" :key="code" size="small" :bordered="false">
                {{ reasonLabel(code) }}
              </n-tag>
            </div>
            <dl>
              <dt>适用场景</dt>
              <dd>{{ card.applicability.join('；') }}</dd>
            </dl>
            <n-button
              block
              size="small"
              :type="selectedExperienceIds.includes(card.id) ? 'success' : 'default'"
              :aria-pressed="selectedExperienceIds.includes(card.id)"
              :disabled="contractStore.saving"
              @click="toggleExperience(card.id)"
            >{{ selectedExperienceIds.includes(card.id) ? '移出项目范围' : '纳入项目范围' }}</n-button>
          </article>
        </div>

        <label class="library-selector">
          <span>从完整经验库调整</span>
          <small>可搜索标题或类别，清空即代表本项目暂不使用经验卡。</small>
          <n-select
            :value="selectedExperienceIds"
            :options="experienceOptions"
            multiple
            filterable
            clearable
            :disabled="contractStore.saving"
            max-tag-count="responsive"
            placeholder="选择 0 到多张经验卡"
            @update:value="updateExperienceSelection"
          />
        </label>

        <div v-if="selectedExperienceCards.length" class="selection-ledger" aria-live="polite">
          <span v-for="card in selectedExperienceCards" :key="card.id">{{ card.title || card.id }} · r{{ card.revision }}</span>
        </div>
      </section>

      <section class="asset-section corpus-section" aria-labelledby="corpus-scope-heading">
        <div class="section-title-row">
          <div>
            <span>本机语料范围</span>
            <h4 id="corpus-scope-heading">作者明确允许参考的来源</h4>
          </div>
          <strong>{{ selectedCorpusIds.length }} 个来源已选</strong>
        </div>

        <n-alert type="warning" :bordered="false" class="scope-note">
          标题和版本只用于展示与追溯，不会直接进入故事发动机。这里不选语料也可以继续。
        </n-alert>

        <n-empty v-if="!visibleCorpusSources.length" description="尚无可用本机语料；可先跳过，之后在设置中导入" class="empty-state" />
        <div v-else class="corpus-list">
          <label
            v-for="source in visibleCorpusSources"
            :key="source.id"
            class="corpus-row"
            :class="{ 'corpus-row--selected': selectedCorpusIds.includes(source.id) }"
          >
            <n-checkbox
              :checked="selectedCorpusIds.includes(source.id)"
              :aria-label="`允许参考 ${source.name}`"
              :disabled="contractStore.saving"
              @update:checked="checked => toggleCorpus(source.id, checked)"
            />
            <div class="corpus-main">
              <strong>{{ source.name }}</strong>
              <span class="relative-path">{{ source.relativePath }}</span>
            </div>
            <dl class="corpus-meta">
              <div><dt>版本</dt><dd>r{{ source.revision }}</dd></div>
              <div><dt>摘要</dt><dd>{{ source.shortHash }}</dd></div>
              <div><dt>编码</dt><dd>{{ source.encoding || '未知' }}</dd></div>
              <div><dt>章节</dt><dd>{{ source.chapterCount ?? 0 }}</dd></div>
            </dl>
            <n-tag size="small" :type="source.state === 'analyzed' ? 'success' : 'default'">
              {{ source.state === 'analyzed' ? '可使用' : (source.state === 'frozen' ? '旧修订' : source.state) }}
            </n-tag>
          </label>
        </div>

        <div v-if="selectedCorpusSources.length" class="selection-ledger" aria-live="polite">
          <span v-for="source in selectedCorpusSources" :key="source.id">{{ source.name || source.id }} · r{{ source.revision }}</span>
        </div>
      </section>
    </template>

    <n-alert v-if="saveError" type="error" class="state-alert" aria-live="assertive">
      {{ saveError }}
      <template v-if="contractStore.requiresReload" #action>
        <n-button size="small" :disabled="contractStore.saving" @click="initialize(props.projectId, { reloadContract: true })">重新加载项目状态</n-button>
      </template>
    </n-alert>

    <footer class="step-actions">
      <n-button secondary :disabled="contractStore.saving" @click="emit('back')">返回风格契约</n-button>
      <div>
        <small>零选择会明确保存为空范围；勾选时冻结资产 ID、版本和内容校验值。</small>
        <n-button
          type="primary"
          size="large"
          :loading="contractStore.saving"
          :disabled="loading || contractStore.saving || contractStore.requiresReload || Boolean(loadError)"
          @click="saveAndContinue"
        >保存并继续</n-button>
      </div>
    </footer>
  </section>
</template>

<style scoped>
.contract-step { color: #302b24; }
.step-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 32px; padding-bottom: 22px; border-bottom: 1px solid #d9cfbb; }
.step-heading > div { max-width: 760px; }
.step-kicker, .section-title-row span { margin: 0; color: #8b6b3f; font-size: 10px; font-weight: 800; letter-spacing: .17em; text-transform: uppercase; }
.step-heading h3 { margin: 7px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(25px, 4vw, 36px); font-weight: 650; letter-spacing: -.02em; }
.step-heading p:not(.step-kicker) { margin: 10px 0 0; color: #766c5e; font-size: 13px; line-height: 1.8; }
.step-number { color: #c9baa1; font-family: Georgia, serif; font-size: 50px; line-height: .9; }
.state-alert { margin-top: 18px; }
.loading-grid { display: grid; grid-template-columns: 1.3fr 1fr; gap: 16px; margin-top: 26px; }
.loading-grid section { display: grid; gap: 14px; padding: 24px; border: 1px solid #ddd2be; border-radius: 12px; background: #fffdf8; }
.asset-section { margin-top: 30px; }
.section-title-row { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 14px; }
.section-title-row h4 { margin: 4px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 21px; }
.section-title-row > strong { color: #6d7e69; font-size: 12px; }
.scope-note { margin-bottom: 14px; background: rgba(255, 253, 248, .68); }
.card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.experience-card { display: flex; min-height: 340px; flex-direction: column; padding: 17px; border: 1px solid #ddd2be; border-radius: 11px; background: rgba(255, 253, 248, .86); transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.experience-card:hover { transform: translateY(-2px); box-shadow: 0 12px 28px rgba(63, 53, 39, .08); }
.experience-card--selected { border-color: #5d7b63; box-shadow: inset 0 3px 0 #5d7b63; }
.card-topline { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #8c7d69; font-size: 10px; }
.experience-card h5 { margin: 16px 0 7px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 18px; }
.method { margin: 0; color: #5e574d; font-size: 12px; line-height: 1.75; }
.reason-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 11px; }
.experience-card dl { margin: 14px 0 17px; }
.experience-card dt { color: #96754b; font-size: 10px; font-weight: 750; }
.experience-card dd { margin: 5px 0 0; color: #7a7062; font-size: 11px; line-height: 1.65; }
.experience-card :deep(.n-button) { margin-top: auto; }
.library-selector { display: grid; gap: 7px; margin-top: 16px; padding: 18px; border: 1px solid #d8cdb9; border-radius: 11px; background: #f8f4e9; }
.library-selector > span { font-size: 13px; font-weight: 700; }
.library-selector > small { color: #847969; font-size: 11px; }
.selection-ledger { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 11px; }
.selection-ledger span { padding: 4px 8px; border-radius: 999px; color: #6c6256; background: #eee7da; font-size: 10px; }
.corpus-section { padding-top: 28px; border-top: 1px solid #dcd2c1; }
.corpus-list { display: grid; gap: 8px; }
.corpus-row { display: grid; grid-template-columns: auto minmax(180px, 1.4fr) minmax(300px, 1fr) auto; align-items: center; gap: 14px; padding: 14px 16px; border: 1px solid #ddd4c4; border-radius: 10px; background: rgba(255, 253, 248, .78); cursor: pointer; }
.corpus-row--selected { border-color: #637d67; background: #fbfdf8; box-shadow: inset 3px 0 0 #637d67; }
.corpus-main { display: grid; min-width: 0; gap: 3px; }
.corpus-main strong { overflow: hidden; font-family: Georgia, 'Noto Serif SC', serif; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.relative-path { overflow: hidden; color: #877c6d; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.corpus-meta { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin: 0; }
.corpus-meta div { min-width: 0; }
.corpus-meta dt { color: #9a8c78; font-size: 9px; }
.corpus-meta dd { overflow: hidden; margin: 2px 0 0; color: #5e574d; font-size: 10px; font-weight: 650; text-overflow: ellipsis; white-space: nowrap; }
.empty-state { padding: 32px 0; }
.step-actions { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-top: 26px; padding-top: 20px; border-top: 1px solid #ded5c4; }
.step-actions > div { display: flex; align-items: center; justify-content: flex-end; gap: 14px; }
.step-actions small { max-width: 380px; color: #8a8071; font-size: 10px; line-height: 1.5; text-align: right; }
@media (max-width: 920px) { .corpus-row { grid-template-columns: auto 1fr auto; } .corpus-meta { grid-column: 2 / -1; grid-row: 2; } }
@media (max-width: 680px) { .step-heading { gap: 12px; } .step-number { font-size: 38px; } .loading-grid { grid-template-columns: 1fr; } .section-title-row { align-items: flex-start; flex-direction: column; } .corpus-row { grid-template-columns: auto 1fr; } .corpus-row > .n-tag { grid-column: 2; } .corpus-meta { grid-column: 1 / -1; grid-template-columns: repeat(2, 1fr); } .step-actions, .step-actions > div { align-items: stretch; flex-direction: column; } .step-actions small { text-align: left; } }
</style>
