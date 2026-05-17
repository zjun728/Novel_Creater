import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatCompletion } from '@/api/ai'
import { useProviderStore } from './providerStore'
import {
  buildStyleTrialSystemPrompt,
  buildStyleTrialUserPrompt,
  styleTrialPresets
} from '@/prompts/styleTrial'

function extractJson(text) {
  if (typeof text !== 'string') {
    if (text?.content) text = text.content
    else if (text?.choices?.[0]?.message?.content) text = text.choices[0].message.content
    else text = JSON.stringify(text)
  }

  const cleaned = text
    .replace(/```json\s*/gi, '')
    .replace(/```\s*/g, '')
    .trim()

  const match = cleaned.match(/\{[\s\S]*\}/)
  if (!match) throw new Error('AI 返回格式不正确，未找到 JSON 对象')
  return JSON.parse(match[0])
}

function normalizeTrial(trial, index) {
  return {
    id: trial.id || `style-${index + 1}`,
    name: trial.name || `风格 ${index + 1}`,
    positioning: trial.positioning || '',
    styleFingerprint: Array.isArray(trial.styleFingerprint) ? trial.styleFingerprint : [],
    excerpt: trial.excerpt || '',
    suitabilityScore: Number(trial.suitabilityScore || 0),
    continuationStability: Number(trial.continuationStability || 0),
    imaginationSpace: Number(trial.imaginationSpace || 0),
    risks: Array.isArray(trial.risks) ? trial.risks : [],
    recommendation: trial.recommendation || ''
  }
}

export const useStyleTrialStore = defineStore('styleTrial', () => {
  const presets = ref(styleTrialPresets)
  const trials = ref([])
  const sampleAnalysis = ref(null)
  const selectedTrial = ref(null)
  const generating = ref(false)

  async function getProvider(projectId) {
    const providerStore = useProviderStore()
    await providerStore.ensureProvidersLoaded()
    let bindings = null
    try {
      bindings = await providerStore.getBindings(projectId)
    } catch {
      bindings = null
    }
    const modelId = bindings?.brainstormModelId || bindings?.writingModelId
    const provider = providerStore.providers.find(p => p.id === modelId) || providerStore.providers[0]
    if (!provider) throw new Error('请先在设置中配置模型')
    return provider
  }

  async function generateTrials(projectId, seed, options) {
    generating.value = true
    try {
      const provider = await getProvider(projectId)
      const messages = [
        { role: 'system', content: buildStyleTrialSystemPrompt() },
        { role: 'user', content: buildStyleTrialUserPrompt(seed, options) }
      ]
      const result = await chatCompletion(provider, messages, {
        maxTokens: 8192,
        temperature: 0.75,
        responseFormat: 'json'
      })
      const data = extractJson(result)
      sampleAnalysis.value = data.sampleAnalysis || null
      trials.value = (data.trials || []).map(normalizeTrial)
      selectedTrial.value = trials.value[0] || null
      return trials.value
    } finally {
      generating.value = false
    }
  }

  function selectTrial(trial) {
    selectedTrial.value = trial
  }

  function buildStyleBible(trial = selectedTrial.value) {
    if (!trial) return ''
    const fingerprint = trial.styleFingerprint?.length
      ? trial.styleFingerprint.map(item => `- ${item}`).join('\n')
      : '- 保持该版本试写片段体现出的叙事节奏、语言密度和人物距离。'
    const risks = trial.risks?.length
      ? trial.risks.map(item => `- ${item}`).join('\n')
      : '- 定期检查风格是否漂移。'

    return `## 主风格：${trial.name}

${trial.positioning}

### 风格指纹
${fingerprint}

### 长篇保持原则
- 后续章节优先保持这一版的叙事距离、句式节奏、信息密度和情绪温度。
- 系统提示、任务面板、设定信息必须自然融入正文，不直接暴露为写作说明。
- 每章允许根据情节强弱微调节奏，但不要偏离主风格。

### 风险提醒
${risks}

### 试写基准
${trial.excerpt}`
  }

  function clearTrials() {
    trials.value = []
    sampleAnalysis.value = null
    selectedTrial.value = null
  }

  return {
    presets,
    trials,
    sampleAnalysis,
    selectedTrial,
    generating,
    generateTrials,
    selectTrial,
    buildStyleBible,
    clearTrials
  }
})
