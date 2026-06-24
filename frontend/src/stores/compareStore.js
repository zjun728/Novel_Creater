import { defineStore } from 'pinia'
import { ref, reactive } from 'vue'
import { chatCompletion } from '@/api/ai'
import { useProviderStore } from './providerStore'
import { useWriterStore } from './writerStore'
import { buildFusionPrompt } from '@/prompts/chapter'

export const useCompareStore = defineStore('compare', () => {
  const runningJobs = reactive({})
  const comparisonVersions = ref([])
  const comparing = ref(false)

  function updateJob(providerId, update) {
    runningJobs[providerId] = { ...runningJobs[providerId], ...update }
  }

  async function startComparison(projectId, chapterNum, context, modelIds) {
    const writerStore = useWriterStore()

    comparing.value = true
    comparisonVersions.value = []

    for (const modelId of modelIds) {
      updateJob(modelId, { streaming: true, content: '', done: false, error: null, version: null })
    }

    const jobs = modelIds.map(async (modelId) => {
      try {
        const version = await writerStore.generateChapter(
          projectId,
          chapterNum,
          context,
          modelId,
          fullContent => {
            updateJob(modelId, { content: fullContent })
          }
        )
        updateJob(modelId, { version, done: true, streaming: false })
        comparisonVersions.value.push(version)
        return version
      } catch (e) {
        updateJob(modelId, { error: e.message, done: true, streaming: false })
        return null
      }
    })

    await Promise.allSettled(jobs)
    comparing.value = false
    return comparisonVersions.value
  }

  function toggleVersion(version) {
    if (!version?.id) return
    const idx = comparisonVersions.value.findIndex(item => item.id === version.id)
    if (idx >= 0) comparisonVersions.value.splice(idx, 1)
    else comparisonVersions.value.push(version)
  }

  function cancelAll() {
    comparing.value = false
    for (const key of Object.keys(runningJobs)) {
      delete runningJobs[key]
    }
  }

  function clearComparison() {
    comparisonVersions.value = []
    for (const key of Object.keys(runningJobs)) {
      delete runningJobs[key]
    }
  }

  async function fuseFragments(projectId, chapterNum, fragments, providerId) {
    try {
      const providerStore = useProviderStore()
      const provider = await providerStore.resolveTaskProvider({
        projectId,
        bindingKeys: ['polishModelId', 'writingModelId'],
        providerId,
        taskName: 'fragment_fusion'
      })

      const result = await chatCompletion(provider, [
        { role: 'user', content: buildFusionPrompt(fragments, { chapterNum }) }
      ], { maxTokens: 4096, temperature: 0.7 })
      if (typeof result === 'string') return result
      if (result?.content) return result.content
      if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
      return JSON.stringify(result)
    } catch (e) {
      console.error('融合失败:', e.message)
      throw e
    }
  }

  return {
    runningJobs,
    comparisonVersions,
    comparing,
    startComparison,
    toggleVersion,
    cancelAll,
    clearComparison,
    fuseFragments
  }
})
