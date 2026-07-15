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

export const useCreationAssetStore = defineStore('creation-assets', () => {
  const styleTemplates = ref([])
  const experienceCards = ref([])
  const recommendations = ref(null)
  const loadingStyles = ref(false)
  const loadingCards = ref(false)
  const loadingRecommendations = ref(false)
  const styleDetails = ref({})
  const experienceCardDetails = ref({})

  const styleListGuard = createLatestRequestGuard()
  const cardListGuard = createLatestRequestGuard()
  const recommendationGuard = createLatestRequestGuard()

  async function loadStyleTemplates() {
    const generation = styleListGuard.begin()
    loadingStyles.value = true
    try {
      const rows = await api.assets.styleTemplates.list() || []
      if (styleListGuard.isCurrent(generation)) styleTemplates.value = rows
      return rows
    } finally {
      if (styleListGuard.isCurrent(generation)) loadingStyles.value = false
    }
  }

  async function loadExperienceCards(category = undefined) {
    const generation = cardListGuard.begin()
    loadingCards.value = true
    try {
      const rows = await api.assets.experienceCards.list({ category }) || []
      if (cardListGuard.isCurrent(generation)) experienceCards.value = rows
      return rows
    } finally {
      if (cardListGuard.isCurrent(generation)) loadingCards.value = false
    }
  }

  async function loadRecommendations(projectId, engineOptionId) {
    const generation = recommendationGuard.begin()
    loadingRecommendations.value = true
    try {
      const result = await api.assets.recommendations(projectId, engineOptionId)
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
    styleListGuard.invalidate()
    cardListGuard.invalidate()
    recommendationGuard.invalidate()
    styleTemplates.value = []
    experienceCards.value = []
    recommendations.value = null
    loadingStyles.value = false
    loadingCards.value = false
    loadingRecommendations.value = false
  }

  return {
    styleTemplates,
    experienceCards,
    recommendations,
    loadingStyles,
    loadingCards,
    loadingRecommendations,
    styleDetails,
    experienceCardDetails,
    loadStyleTemplates,
    loadExperienceCards,
    loadRecommendations,
    getStyleTemplate,
    getExperienceCard,
    invalidateCatalogQueries,
  }
})
