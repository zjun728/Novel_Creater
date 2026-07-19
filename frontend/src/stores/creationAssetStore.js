import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api/db/client.js'
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
const PURPOSES_BY_GENRE = Object.freeze({
  fantasy: ['progression_economy'],
  xianxia: ['progression_economy'],
  wuxia: ['progression_economy'],
  historical: ['long_arc_continuity'],
  science_fiction: ['long_arc_continuity'],
  urban: ['dialogue'],
  romance: ['emotion', 'dialogue'],
  mystery: ['suspense'],
  horror: ['suspense'],
  general: [],
})

function normalizedProfileText(...values) {
  return values.map(value => String(value || '').normalize('NFKC').toLowerCase()).join(' ')
}

function recommendationScope(draft) {
  if (!draft?.genreProfileKey || !draft?.channelProfileKey) {
    throw new Error('创作契约推荐上下文不完整')
  }
  const genreText = normalizedProfileText(draft.genreProfileKey)
  const genre = GENRE_PROFILE_SIGNALS.find(([, signals]) => (
    signals.some(signal => genreText.includes(signal))
  ))?.[0] || 'general'
  const channelText = normalizedProfileText(draft.channelProfileKey)
  const channel = ['female', '女频', '晋江', '潇湘'].some(
    signal => channelText.includes(signal),
  )
    ? 'female_frequency'
    : ['male', '男频', '起点', 'qidian', 'qq'].some(
      signal => channelText.includes(signal),
    )
      ? 'male_frequency'
      : 'all'
  const dislikes = new Set(Array.isArray(draft.dislikes) ? draft.dislikes : [])
  return {
    genres: [genre],
    channels: [channel],
    creationStages: ['drafting'],
    writingPurposes: [
      'style_direction',
      'plot_organization',
      'character_arcs',
      ...PURPOSES_BY_GENRE[genre],
    ],
    prohibitedDirections: PROHIBITED_DIRECTIONS.filter(value => dislikes.has(value)),
    status: 'active',
  }
}

export const useCreationAssetStore = defineStore('creation-assets', () => {
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

  const inventoryGuard = createLatestRequestGuard()
  const styleListGuard = createLatestRequestGuard()
  const cardListGuard = createLatestRequestGuard()
  const recommendationGuard = createLatestRequestGuard()

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

  async function loadRecommendations(projectId, engineOptionId, contractDraft) {
    const generation = recommendationGuard.begin()
    loadingRecommendations.value = true
    try {
      const result = await api.assets.recommendations(
        projectId,
        engineOptionId,
        recommendationScope(contractDraft),
      )
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
