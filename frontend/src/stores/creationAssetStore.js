import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api/db/client.js'
import { useCorpusStore } from './corpusStore.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

function immutableKey(id, contentHash) {
  if (!id || !contentHash) throw new TypeError('Immutable asset identity requires id and content hash')
  return `${id}\u0000${contentHash}`
}

function assertImmutableDetail(kind, detail, id, contentHash) {
  if (detail?.id !== id || detail?.contentHash !== contentHash) {
    throw new Error(`Immutable ${kind} revision changed; reload the catalog`)
  }
  return detail
}

const GENRE_PROFILE_SIGNALS = Object.freeze([
  ['science_fiction', ['science_fiction', 'science fiction', 'sci-fi', '科幻']],
  ['xianxia', ['xianxia', 'cultivation', '仙侠', '修仙', '仙道']],
  ['wuxia', ['wuxia', '武侠']],
  ['fantasy', ['xuanhuan', 'fantasy', '玄幻', '奇幻', '魔法']],
  ['historical', ['historical', 'history', '历史', '古代', '穿越']],
  ['urban', ['urban', '都市', '现代']],
  ['romance', ['romance', '言情', '爱情', '恋爱']],
  ['mystery', ['mystery', '悬疑', '推理']],
  ['horror', ['horror', '恐怖', '惊悚']],
])
const PROHIBITED_DIRECTIONS = Object.freeze([
  'comedic',
  'romance_centric',
  'graphic_violence',
  'rapid_power_fantasy',
  'grim_tragedy',
  'slow_burn',
  'dense_exposition',
])
function normalizedProfileText(...values) {
  return values.map(value => String(value || '').normalize('NFKC').toLowerCase()).join(' ')
}

function recommendationScope(draft) {
  if (!draft?.genreProfileKey) {
    throw new Error('创作契约推荐上下文不完整')
  }
  const genreText = normalizedProfileText(draft.genreProfileKey)
  const genre = GENRE_PROFILE_SIGNALS.find(([, signals]) => (
    signals.some(signal => genreText.includes(signal))
  ))?.[0] || 'general'
  const dislikes = new Set(Array.isArray(draft.dislikes) ? draft.dislikes : [])
  return {
    genre,
    creationStage: 'drafting',
    prohibitedDirections: PROHIBITED_DIRECTIONS.filter(value => dislikes.has(value)),
    status: 'active',
  }
}

function frozenRefFingerprint(ref) {
  if (!ref) return null
  return [ref.id || null, ref.revision || null, ref.contentHash || null]
}

function recommendationFingerprint(projectId, engineOptionId, taxonomy, scope, draft, context) {
  return JSON.stringify({
    projectId: String(projectId || ''),
    engineOptionId: String(engineOptionId || ''),
    taxonomyVersion: taxonomy.taxonomyPackageVersion,
    taxonomyHash: taxonomy.taxonomyPackageHash,
    genre: scope.genre,
    creationStage: scope.creationStage,
    status: scope.status,
    prohibitedDirections: scope.prohibitedDirections,
    selectionRevision: context?.selectionRevision ?? draft?.selectionRevision ?? null,
    seedHash: draft?.seedHash ?? null,
    engineHash: draft?.engineHash ?? null,
    primaryStyleRef: frozenRefFingerprint(draft?.primaryStyleRef),
    secondaryStyleRef: frozenRefFingerprint(draft?.secondaryStyleRef),
  })
}

function newRecommendationIdempotencyKey() {
  if (typeof globalThis.crypto?.randomUUID !== 'function') {
    throw new Error('当前环境无法生成创作资产推荐指令')
  }
  return `${globalThis.crypto.randomUUID()}${globalThis.crypto.randomUUID()}`
    .replaceAll('-', '')
}

function recommendationViewModels(response, catalog, assetType) {
  const recommendations = Array.isArray(response?.assetRecommendations)
    ? response.assetRecommendations
    : []
  const assets = Array.isArray(catalog) ? catalog : []
  const seen = new Set()
  const result = []
  for (const recommendation of recommendations) {
    if (
      recommendation?.assetType !== assetType
      || typeof recommendation.assetRevisionId !== 'string'
      || typeof recommendation.stableKey !== 'string'
      || !Number.isInteger(recommendation.revision)
      || typeof recommendation.contentHash !== 'string'
      || typeof recommendation.reason !== 'string'
      || !Number.isFinite(recommendation.confidence)
      || seen.has(recommendation.assetRevisionId)
    ) continue
    const asset = assets.find(item => (
      item?.id === recommendation.assetRevisionId
      && item.stableKey === recommendation.stableKey
      && item.revision === recommendation.revision
      && item.contentHash === recommendation.contentHash
    ))
    if (!asset) continue
    seen.add(recommendation.assetRevisionId)
    result.push({
      ...asset,
      reasonCodes: [recommendation.reason],
      confidence: recommendation.confidence,
    })
  }
  return result
}

function corpusRecommendationViewModels(response, sources) {
  const recommendations = Array.isArray(response?.corpusRecommendations)
    ? response.corpusRecommendations
    : []
  const catalog = Array.isArray(sources) ? sources : []
  const seen = new Set()
  const result = []
  for (const recommendation of recommendations) {
    if (
      typeof recommendation?.sourceId !== 'string'
      || !Number.isInteger(recommendation.sourceRevision)
      || typeof recommendation.sourceHash !== 'string'
      || typeof recommendation.chapterId !== 'string'
      || typeof recommendation.fragmentId !== 'string'
      || typeof recommendation.fragmentHash !== 'string'
      || !Number.isInteger(recommendation.rangeStart)
      || !Number.isInteger(recommendation.rangeEnd)
      || recommendation.rangeStart < 0
      || recommendation.rangeEnd <= recommendation.rangeStart
      || typeof recommendation.use !== 'string'
      || typeof recommendation.reason !== 'string'
      || !Number.isFinite(recommendation.confidence)
      || seen.has(recommendation.fragmentId)
    ) continue
    const source = catalog.find(item => (
      item?.id === recommendation.sourceId
      && item.revision === recommendation.sourceRevision
      && item.contentHash === recommendation.sourceHash
      && typeof item.revisionId === 'string'
      && item.revisionId.length > 0
      && item.state !== 'archived'
    ))
    if (!source) continue
    seen.add(recommendation.fragmentId)
    result.push({
      ...recommendation,
      source: { ...source },
      reasonCodes: [recommendation.reason],
    })
  }
  return result
}

export const useCreationAssetStore = defineStore('creation-assets', () => {
  const corpusStore = useCorpusStore()
  const styleTemplates = ref([])
  const experienceCards = ref([])
  const inventory = ref(null)
  const recommendations = ref(null)
  const loadingInventory = ref(false)
  const loadingStyles = ref(false)
  const loadingCards = ref(false)
  const loadingRecommendations = ref(false)
  const inventoryError = ref('')
  const styleError = ref('')
  const cardError = ref('')
  const styleDetails = ref({})
  const experienceCardDetails = ref({})
  const recommendedStyles = computed(() => recommendationViewModels(
    recommendations.value,
    styleTemplates.value,
    'style',
  ))
  const recommendedExperienceCards = computed(() => recommendationViewModels(
    recommendations.value,
    experienceCards.value,
    'experience_card',
  ))
  const recommendedCorpusFragments = computed(() => corpusRecommendationViewModels(
    recommendations.value,
    corpusStore.sources,
  ))

  const inventoryGuard = createLatestRequestGuard()
  const styleListGuard = createLatestRequestGuard()
  const cardListGuard = createLatestRequestGuard()
  const recommendationGuard = createLatestRequestGuard()
  const recommendationIdempotencyKeys = new Map()

  async function loadInventory() {
    const generation = inventoryGuard.begin()
    loadingInventory.value = true
    inventoryError.value = ''
    try {
      const result = await api.assets.inventory()
      if (inventoryGuard.isCurrent(generation)) inventory.value = result
      return result
    } catch (error) {
      if (inventoryGuard.isCurrent(generation)) {
        inventoryError.value = error?.message || '创作资产清单加载失败'
      }
      throw error
    } finally {
      if (inventoryGuard.isCurrent(generation)) loadingInventory.value = false
    }
  }

  async function loadStyleTemplates(params = {}) {
    const generation = styleListGuard.begin()
    loadingStyles.value = true
    styleError.value = ''
    try {
      const rows = await api.assets.styleTemplates.list(params) || []
      if (styleListGuard.isCurrent(generation)) styleTemplates.value = rows
      return rows
    } catch (error) {
      if (styleListGuard.isCurrent(generation)) {
        styleError.value = error?.message || '风格模板加载失败'
      }
      throw error
    } finally {
      if (styleListGuard.isCurrent(generation)) loadingStyles.value = false
    }
  }

  async function loadExperienceCards(params = {}) {
    if (typeof params === 'string') params = { category: params }
    const generation = cardListGuard.begin()
    loadingCards.value = true
    cardError.value = ''
    try {
      const rows = await api.assets.experienceCards.list(params) || []
      if (cardListGuard.isCurrent(generation)) experienceCards.value = rows
      return rows
    } catch (error) {
      if (cardListGuard.isCurrent(generation)) {
        cardError.value = error?.message || '经验卡加载失败'
      }
      throw error
    } finally {
      if (cardListGuard.isCurrent(generation)) loadingCards.value = false
    }
  }

  async function loadRecommendations(projectId, engineOptionId, contractDraft, context = {}) {
    const generation = recommendationGuard.begin()
    loadingRecommendations.value = true
    try {
      const taxonomy = inventory.value || await loadInventory()
      if (
        typeof taxonomy?.taxonomyPackageVersion !== 'string'
        || !/^[0-9a-f]{64}$/u.test(taxonomy?.taxonomyPackageHash || '')
      ) {
        throw new Error('创作资产分类版本信息不完整')
      }
      const scope = recommendationScope(contractDraft)
      const fingerprint = recommendationFingerprint(
        projectId,
        engineOptionId,
        taxonomy,
        scope,
        contractDraft,
        context,
      )
      let idempotencyKey = recommendationIdempotencyKeys.get(fingerprint)
      if (!idempotencyKey) {
        idempotencyKey = newRecommendationIdempotencyKey()
        recommendationIdempotencyKeys.set(fingerprint, idempotencyKey)
      }
      const result = await api.assets.recommendations(projectId, {
        idempotencyKey,
        engineOptionId,
        taxonomyVersion: taxonomy.taxonomyPackageVersion,
        taxonomyHash: taxonomy.taxonomyPackageHash,
        ...scope,
      })
      if (recommendationGuard.isCurrent(generation)) recommendations.value = result
      return result
    } finally {
      if (recommendationGuard.isCurrent(generation)) loadingRecommendations.value = false
    }
  }

  async function getStyleTemplate(revisionId, contentHash) {
    const key = immutableKey(revisionId, contentHash)
    if (styleDetails.value[key]) return styleDetails.value[key]
    const detail = assertImmutableDetail(
      'style template',
      await api.assets.styleTemplates.get(revisionId),
      revisionId,
      contentHash,
    )
    styleDetails.value[key] = detail
    return detail
  }

  async function getExperienceCard(revisionId, contentHash) {
    const key = immutableKey(revisionId, contentHash)
    if (experienceCardDetails.value[key]) return experienceCardDetails.value[key]
    const detail = assertImmutableDetail(
      'experience card',
      await api.assets.experienceCards.get(revisionId),
      revisionId,
      contentHash,
    )
    experienceCardDetails.value[key] = detail
    return detail
  }

  function invalidateCatalogQueries() {
    inventoryGuard.invalidate()
    styleListGuard.invalidate()
    cardListGuard.invalidate()
    recommendationGuard.invalidate()
    recommendationIdempotencyKeys.clear()
    inventory.value = null
    styleTemplates.value = []
    experienceCards.value = []
    recommendations.value = null
    loadingInventory.value = false
    loadingStyles.value = false
    loadingCards.value = false
    loadingRecommendations.value = false
    inventoryError.value = ''
    styleError.value = ''
    cardError.value = ''
  }

  return {
    styleTemplates,
    experienceCards,
    inventory,
    recommendations,
    recommendedStyles,
    recommendedExperienceCards,
    recommendedCorpusFragments,
    loadingInventory,
    loadingStyles,
    loadingCards,
    loadingRecommendations,
    inventoryError,
    styleError,
    cardError,
    styleDetails,
    experienceCardDetails,
    loadInventory,
    loadStyleTemplates,
    loadExperienceCards,
    loadRecommendations,
    getStyleTemplate,
    getExperienceCard,
    invalidateCatalogQueries,
  }
})
