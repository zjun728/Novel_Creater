<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NEmpty,
  NInput,
  NModal,
  NSelect,
  NSkeleton,
  NSpin,
  NTag,
} from 'naive-ui'

import { useCreationAssetStore } from '@/stores/creationAssetStore'
import { useCreationContractStore } from '@/stores/creationContractStore'

const props = defineProps({
  projectId: { type: String, required: true },
})

const emit = defineEmits(['saved', 'dirty-change', 'back'])
const assetStore = useCreationAssetStore()
const contractStore = useCreationContractStore()

const loading = ref(false)
const loadError = ref('')
const saveError = ref('')
const primaryStyleId = ref(null)
const secondaryStyleId = ref(null)
const primaryFrozenRef = ref(null)
const secondaryFrozenRef = ref(null)
const likesText = ref('')
const dislikesText = ref('')
const detailOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
const selectedDetail = ref(null)
let loadEpoch = 0

const draftValues = computed(() => contractStore.draft?.draft || null)
const recommendedStyles = computed(() => assetStore.recommendations?.styles || [])
const styleOptions = computed(() => {
  const options = assetStore.styleTemplates.map(style => ({
    label: `${style.name} · r${style.revision}`,
    value: style.id,
  }))
  for (const frozen of [primaryFrozenRef.value, secondaryFrozenRef.value]) {
    if (frozen?.id && !options.some(option => option.value === frozen.id)) {
      options.push({ label: `已冻结风格 · r${frozen.revision}`, value: frozen.id })
    }
  }
  return options
})
const selectedPrimary = computed(() => styleById(primaryStyleId.value))
const selectedSecondary = computed(() => styleById(secondaryStyleId.value))
const hasCatalog = computed(() => assetStore.styleTemplates.length > 0)

const REASON_LABELS = Object.freeze({
  'semantic-profile': '整体气质匹配',
  'seed-context': '贴合种子',
  'engine-context': '贴合故事发动机',
  'default-rank': '基础优先级',
})

function reasonLabel(code) {
  return REASON_LABELS[code] || code
}

function styleById(id) {
  if (!id) return null
  return assetStore.styleTemplates.find(style => style.id === id)
    || recommendedStyles.value.find(style => style.id === id)
    || null
}

function styleRef(style) {
  if (!style?.id || !Number.isInteger(style.revision) || !style.contentHash) {
    throw new TypeError('风格模板版本信息不完整，请重新加载')
  }
  return {
    id: style.id,
    revision: style.revision,
    contentHash: style.contentHash,
  }
}

function splitPreferenceLines(value) {
  return String(value || '')
    .split(/\r?\n/u)
    .map(item => item.trim())
    .filter(Boolean)
}

function markDirty() {
  contractStore.markUnsavedChanges()
  emit('dirty-change', true)
}

function setPrimary(id) {
  if (contractStore.saving) return
  if (primaryStyleId.value === id) return
  const style = styleById(id)
  if (!style) {
    saveError.value = '所选主风格已不在当前模板库，请重新加载。'
    return
  }
  primaryStyleId.value = id
  primaryFrozenRef.value = styleRef(style)
  if (secondaryStyleId.value === id) {
    secondaryStyleId.value = null
    secondaryFrozenRef.value = null
  }
  saveError.value = ''
  markDirty()
}

function setSecondary(id) {
  if (contractStore.saving) return
  const next = id || null
  if (next === primaryStyleId.value) {
    saveError.value = '主风格和次风格不能选择同一个模板。'
    return
  }
  if (secondaryStyleId.value === next) return
  const style = next ? styleById(next) : null
  if (next && !style) {
    saveError.value = '所选次风格已不在当前模板库，请重新加载。'
    return
  }
  secondaryStyleId.value = next
  secondaryFrozenRef.value = style ? styleRef(style) : null
  saveError.value = ''
  markDirty()
}

function updateLikes(value) {
  if (contractStore.saving) return
  likesText.value = value
  markDirty()
}

function updateDislikes(value) {
  if (contractStore.saving) return
  dislikesText.value = value
  markDirty()
}

function hydrateFromDraft(draft) {
  primaryStyleId.value = draft?.primaryStyleRef?.id || null
  secondaryStyleId.value = draft?.secondaryStyleRef?.id || null
  primaryFrozenRef.value = draft?.primaryStyleRef ? { ...draft.primaryStyleRef } : null
  secondaryFrozenRef.value = draft?.secondaryStyleRef ? { ...draft.secondaryStyleRef } : null
  likesText.value = Array.isArray(draft?.likes) ? draft.likes.join('\n') : ''
  dislikesText.value = Array.isArray(draft?.dislikes) ? draft.dislikes.join('\n') : ''
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
    if (!draft?.engineOptionId || !draft?.engineHash) {
      throw new Error('请先选择并保存故事发动机。')
    }
    await Promise.all([
      assetStore.loadStyleTemplates(),
      assetStore.loadRecommendations(projectId, draft.engineOptionId, draft),
    ])
    if (epoch !== loadEpoch) return
    hydrateFromDraft(draft)
    contractStore.discardUnsavedChanges()
    emit('dirty-change', false)
  } catch (error) {
    if (epoch === loadEpoch) loadError.value = error?.message || '风格模板加载失败'
  } finally {
    if (epoch === loadEpoch) loading.value = false
  }
}

async function openStyleDetail(style) {
  detailOpen.value = true
  detailLoading.value = true
  detailError.value = ''
  selectedDetail.value = null
  try {
    selectedDetail.value = await assetStore.getStyleTemplate(style.id, style.contentHash)
  } catch (error) {
    detailError.value = error?.message || '完整风格详情加载失败'
  } finally {
    detailLoading.value = false
  }
}

async function saveAndContinue() {
  if (contractStore.saving || contractStore.requiresReload) return
  saveError.value = ''
  const current = draftValues.value
  const primary = primaryFrozenRef.value
  const secondary = secondaryFrozenRef.value
  const likes = splitPreferenceLines(likesText.value)
  const dislikes = splitPreferenceLines(dislikesText.value)

  if (!current?.engineOptionId || !current?.engineHash) {
    saveError.value = '故事发动机草稿已失效，请返回上一步重新加载。'
    return
  }
  if (!primary || !primaryStyleId.value) {
    saveError.value = '请选择一个主风格。'
    return
  }
  if (secondary?.id === primary.id) {
    saveError.value = '主风格和次风格不能选择同一个模板。'
    return
  }
  if (likes.length > 20 || dislikes.length > 20) {
    saveError.value = '喜欢和避开的表现各自最多填写 20 条。'
    return
  }

  try {
    const saved = await contractStore.saveDraft(props.projectId, {
      schemaVersion: 'contract-draft-v2',
      draftStage: 'style',
      engineOptionId: current.engineOptionId,
      engineHash: current.engineHash,
      channelProfileKey: current.channelProfileKey,
      genreProfileKey: current.genreProfileKey,
      qualityCharterVersion: current.qualityCharterVersion,
      totalWordRange: current.totalWordRange,
      chapterCapacityPolicy: current.chapterCapacityPolicy,
      primaryStyleRef: styleRef(primary),
      secondaryStyleRef: secondary ? styleRef(secondary) : null,
      likes,
      dislikes,
      experienceCardRefs: null,
      corpusSourceRefs: null,
    })
    if (contractStore.draft !== saved) {
      saveError.value = '保存期间风格内容发生了变化，请核对后再次保存。'
      return
    }
    emit('dirty-change', false)
    emit('saved')
  } catch (error) {
    saveError.value = error?.message || '风格契约保存失败'
  }
}

watch(() => props.projectId, projectId => initialize(String(projectId || '')), { immediate: true })

onBeforeUnmount(() => {
  loadEpoch += 1
})
</script>

<template>
  <section class="contract-step" aria-labelledby="style-step-heading">
    <header class="step-heading">
      <div>
        <p class="step-kicker">STEP 03 · STYLE CONTRACT</p>
        <h3 id="style-step-heading">先定阅读感受，再谈写法</h3>
        <p>主风格决定整本书的语言底色；次风格只借少量局部技法，不与主风格平分控制权。</p>
      </div>
      <span class="step-number" aria-hidden="true">03</span>
    </header>

    <n-alert v-if="loadError" type="error" class="state-alert" title="风格模板未能加载">
      {{ loadError }}
      <template #action><n-button size="small" :disabled="contractStore.saving" @click="initialize(props.projectId, { reloadContract: true })">重新加载</n-button></template>
    </n-alert>

    <template v-if="loading">
      <div class="recommendation-grid" aria-busy="true" aria-label="正在加载风格推荐">
        <article v-for="index in 3" :key="index" class="style-card style-card--skeleton">
          <n-skeleton text width="34%" />
          <n-skeleton text :repeat="4" />
          <n-skeleton height="32px" width="70%" />
        </article>
      </div>
    </template>

    <template v-else-if="!loadError">
      <section class="recommendation-section" aria-labelledby="style-recommendations-heading">
        <div class="section-title-row">
          <div>
            <span>系统确定性推荐</span>
            <h4 id="style-recommendations-heading">三个可比较的写作气质</h4>
          </div>
          <n-tag :bordered="false" round>{{ recommendedStyles.length }} / 3</n-tag>
        </div>

        <n-empty v-if="!recommendedStyles.length" description="当前故事发动机没有可用的风格推荐" class="empty-state" />
        <div v-else class="recommendation-grid">
          <article
            v-for="(style, index) in recommendedStyles"
            :key="style.id"
            class="style-card"
            :class="{
              'style-card--primary': primaryStyleId === style.id,
              'style-card--secondary': secondaryStyleId === style.id,
            }"
          >
            <div class="card-topline">
              <span>推荐 {{ String(index + 1).padStart(2, '0') }}</span>
              <div class="selection-tags">
                <n-tag v-if="primaryStyleId === style.id" type="success" size="small" round>主风格</n-tag>
                <n-tag v-if="secondaryStyleId === style.id" type="warning" size="small" round>次风格</n-tag>
              </div>
            </div>
            <h5>{{ style.name }}</h5>
            <p class="reading-experience">{{ style.readingExperience }}</p>
            <div class="reason-list" aria-label="推荐原因">
              <n-tag v-for="code in style.reasonCodes" :key="code" size="small" :bordered="false">
                {{ reasonLabel(code) }}
              </n-tag>
            </div>
            <dl class="scope-list">
              <div>
                <dt>适合</dt>
                <dd>{{ style.applicability.join('；') }}</dd>
              </div>
              <div>
                <dt>慎用</dt>
                <dd>{{ style.nonApplicability.join('；') }}</dd>
              </div>
            </dl>
            <div class="card-actions">
              <n-button size="small" secondary :disabled="contractStore.saving" @click="openStyleDetail(style)">阅读全文示例</n-button>
              <n-button
                size="small"
                :type="primaryStyleId === style.id ? 'success' : 'default'"
                :aria-pressed="primaryStyleId === style.id"
                :disabled="contractStore.saving"
                @click="setPrimary(style.id)"
              >设为主风格</n-button>
              <n-button
                size="small"
                quaternary
                :disabled="contractStore.saving || primaryStyleId === style.id"
                :aria-pressed="secondaryStyleId === style.id"
                @click="setSecondary(secondaryStyleId === style.id ? null : style.id)"
              >{{ secondaryStyleId === style.id ? '取消次风格' : '设为次风格' }}</n-button>
            </div>
          </article>
        </div>
      </section>

      <section class="selection-panel" aria-labelledby="style-selection-heading">
        <div class="panel-intro">
          <span>最终选择</span>
          <h4 id="style-selection-heading">风格契约不是滤镜叠加</h4>
          <p>可以从完整模板库改选。保存前的所有变化只停留在本页，不会逐项写入。</p>
        </div>
        <n-empty v-if="!hasCatalog" description="风格模板库为空" class="empty-state" />
        <div v-else class="select-grid">
          <label>
            <span>主风格 <b>必选</b></span>
            <n-select
              :value="primaryStyleId"
              :options="styleOptions"
              filterable
              :disabled="contractStore.saving"
              placeholder="选择整本书的语言底色"
              @update:value="setPrimary"
            />
          </label>
          <label>
            <span>次风格 <em>可选</em></span>
            <n-select
              :value="secondaryStyleId"
              :options="styleOptions.filter(option => option.value !== primaryStyleId)"
              filterable
              clearable
              :disabled="contractStore.saving"
              placeholder="只借少量局部技法"
              @update:value="setSecondary"
            />
          </label>
        </div>
        <div class="selected-summary" aria-live="polite">
          <span>主风格：{{ selectedPrimary?.name || (primaryStyleId ? `已冻结 · r${primaryFrozenRef?.revision}` : '未选择') }}</span>
          <span>次风格：{{ selectedSecondary?.name || (secondaryStyleId ? `已冻结 · r${secondaryFrozenRef?.revision}` : '不使用') }}</span>
        </div>
        <div class="preference-grid">
          <label>
            <span>希望保留的表现</span>
            <small>每行一条，例如“对话里有没说透的关系变化”</small>
            <n-input
              :value="likesText"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 7 }"
              maxlength="4000"
              show-count
              :disabled="contractStore.saving"
              placeholder="写下你真正想读到的感觉"
              @update:value="updateLikes"
            />
          </label>
          <label>
            <span>明确避开的表现</span>
            <small>每行一条，例如“只靠脸色发白代替情绪”</small>
            <n-input
              :value="dislikesText"
              type="textarea"
              :autosize="{ minRows: 3, maxRows: 7 }"
              maxlength="4000"
              show-count
              :disabled="contractStore.saving"
              placeholder="写下会让故事显得干、机械或出戏的写法"
              @update:value="updateDislikes"
            />
          </label>
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
      <n-button secondary :disabled="contractStore.saving" @click="emit('back')">返回故事发动机</n-button>
      <div>
        <small>保存后建立一个刷新恢复点，并清除尚未重新确认的下游资产范围。</small>
        <n-button
          type="primary"
          size="large"
          :loading="contractStore.saving"
          :disabled="loading || contractStore.saving || contractStore.requiresReload || Boolean(loadError) || !primaryStyleId"
          @click="saveAndContinue"
        >保存并继续</n-button>
      </div>
    </footer>

    <n-modal v-model:show="detailOpen" preset="card" class="style-detail-modal" style="width: min(920px, 94vw)" title="完整风格样例">
      <n-spin :show="detailLoading">
        <n-alert v-if="detailError" type="error">{{ detailError }}</n-alert>
        <article v-else-if="selectedDetail" class="style-detail">
          <header>
            <p>{{ selectedDetail.stableKey }} · revision {{ selectedDetail.revision }}</p>
            <h3>{{ selectedDetail.name }}</h3>
            <strong>{{ selectedDetail.payload.readingExperience }}</strong>
          </header>
          <div class="craft-grid">
            <section><span>叙事距离</span><p>{{ selectedDetail.payload.narrativeDistance }}</p></section>
            <section><span>句段节奏</span><p>{{ selectedDetail.payload.rhythm }}</p></section>
            <section><span>词语密度</span><p>{{ selectedDetail.payload.dictionDensity }}</p></section>
            <section><span>对白</span><p>{{ selectedDetail.payload.dialogue }}</p></section>
            <section><span>潜台词</span><p>{{ selectedDetail.payload.subtext }}</p></section>
            <section><span>人物声音</span><p>{{ selectedDetail.payload.characterVoices }}</p></section>
            <section><span>情绪表达</span><p>{{ selectedDetail.payload.emotion }}</p></section>
            <section><span>内心活动</span><p>{{ selectedDetail.payload.interiority }}</p></section>
          </div>
          <section class="example-block">
            <span>同一标准场景示例</span>
            <p>{{ selectedDetail.payload.standardSceneExample }}</p>
          </section>
          <section class="example-block example-block--complete">
            <span>完整应用示例</span>
            <p>{{ selectedDetail.payload.completeApplicationExample }}</p>
          </section>
          <section class="risk-block">
            <span>使用风险</span>
            <ul><li v-for="risk in selectedDetail.payload.risks" :key="risk">{{ risk }}</li></ul>
          </section>
        </article>
      </n-spin>
    </n-modal>
  </section>
</template>

<style scoped>
.contract-step { color: #302b24; }
.step-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 32px; padding-bottom: 22px; border-bottom: 1px solid #d9cfbb; }
.step-heading > div { max-width: 720px; }
.step-kicker, .section-title-row span, .panel-intro > span { margin: 0; color: #8b6b3f; font-size: 10px; font-weight: 800; letter-spacing: .17em; text-transform: uppercase; }
.step-heading h3 { margin: 7px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(25px, 4vw, 36px); font-weight: 650; letter-spacing: -.02em; }
.step-heading p:not(.step-kicker) { margin: 10px 0 0; color: #766c5e; font-size: 13px; line-height: 1.8; }
.step-number { color: #c9baa1; font-family: Georgia, serif; font-size: 50px; line-height: .9; }
.state-alert { margin-top: 18px; }
.recommendation-section { margin-top: 30px; }
.section-title-row { display: flex; align-items: end; justify-content: space-between; gap: 18px; margin-bottom: 14px; }
.section-title-row h4, .panel-intro h4 { margin: 4px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 21px; }
.recommendation-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }
.style-card { display: flex; min-width: 0; min-height: 390px; flex-direction: column; padding: 18px; border: 1px solid #ddd2be; border-radius: 12px; background: rgba(255, 253, 248, .86); transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease; }
.style-card:hover { transform: translateY(-2px); box-shadow: 0 13px 30px rgba(62, 51, 36, .08); }
.style-card--primary { border-color: #53745b; box-shadow: inset 0 3px 0 #53745b; }
.style-card--secondary { border-color: #a47745; box-shadow: inset 0 3px 0 #a47745; }
.style-card--primary.style-card--secondary { border-color: #53745b; }
.style-card--skeleton { gap: 16px; min-height: 330px; }
.card-topline { display: flex; align-items: center; justify-content: space-between; min-height: 24px; color: #9c8664; font-size: 10px; font-weight: 750; letter-spacing: .12em; text-transform: uppercase; }
.selection-tags { display: flex; gap: 5px; }
.style-card h5 { margin: 20px 0 7px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 21px; }
.reading-experience { min-height: 44px; margin: 0; color: #655d52; font-size: 13px; line-height: 1.7; }
.reason-list { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 12px; }
.scope-list { display: grid; gap: 9px; margin: 16px 0 0; }
.scope-list div { display: grid; grid-template-columns: 36px 1fr; gap: 8px; }
.scope-list dt { color: #957750; font-size: 11px; font-weight: 700; }
.scope-list dd { margin: 0; color: #786f62; font-size: 11px; line-height: 1.65; }
.card-actions { display: flex; flex-wrap: wrap; gap: 6px; margin-top: auto; padding-top: 18px; }
.selection-panel { margin-top: 26px; padding: clamp(18px, 3vw, 28px); border: 1px solid #d8cdb9; border-radius: 14px; background: #f9f5eb; }
.panel-intro p { margin: 7px 0 0; color: #786e60; font-size: 12px; }
.select-grid, .preference-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 20px; }
.select-grid label, .preference-grid label { display: grid; gap: 8px; }
.select-grid label > span, .preference-grid label > span { font-size: 13px; font-weight: 700; }
.select-grid b { color: #56725b; font-size: 10px; }
.select-grid em { color: #8f8373; font-size: 10px; font-style: normal; }
.preference-grid small { color: #8a7f70; font-size: 11px; }
.selected-summary { display: flex; flex-wrap: wrap; gap: 10px 20px; margin-top: 12px; color: #6e6558; font-size: 11px; }
.empty-state { padding: 32px 0; }
.step-actions { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-top: 24px; padding-top: 20px; border-top: 1px solid #ded5c4; }
.step-actions > div { display: flex; align-items: center; justify-content: flex-end; gap: 14px; }
.step-actions small { max-width: 360px; color: #8a8071; font-size: 10px; line-height: 1.5; text-align: right; }
.style-detail { color: #332e27; }
.style-detail header { padding-bottom: 18px; border-bottom: 1px solid #e1d8c8; }
.style-detail header p { margin: 0; color: #92764e; font-size: 10px; letter-spacing: .12em; text-transform: uppercase; }
.style-detail header h3 { margin: 7px 0 4px; font-family: Georgia, 'Noto Serif SC', serif; font-size: 28px; }
.style-detail header strong { color: #645a4e; font-size: 13px; }
.craft-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin-top: 20px; overflow: hidden; border: 1px solid #e3dbcc; border-radius: 10px; background: #e3dbcc; }
.craft-grid section { padding: 14px; background: #fffdf8; }
.craft-grid span, .example-block > span, .risk-block > span { color: #8a6d46; font-size: 10px; font-weight: 750; letter-spacing: .1em; }
.craft-grid p { margin: 5px 0 0; color: #5f584e; font-size: 12px; line-height: 1.65; }
.example-block { margin-top: 18px; padding: 18px; border-left: 3px solid #6a816b; background: #f4f0e6; }
.example-block--complete { border-left-color: #9a7044; background: #fbf7ee; }
.example-block p { margin: 9px 0 0; color: #4c463d; font-family: Georgia, 'Noto Serif SC', serif; font-size: 14px; line-height: 1.95; white-space: pre-wrap; }
.risk-block { margin-top: 18px; }
.risk-block ul { margin: 8px 0 0; padding-left: 18px; color: #6d6255; font-size: 12px; line-height: 1.8; }
@media (max-width: 900px) { .recommendation-grid { grid-template-columns: 1fr; } .style-card { min-height: 0; } }
@media (max-width: 680px) { .step-heading { gap: 12px; } .step-number { font-size: 38px; } .select-grid, .preference-grid, .craft-grid { grid-template-columns: 1fr; } .step-actions, .step-actions > div { align-items: stretch; flex-direction: column; } .step-actions small { text-align: left; } }
</style>
