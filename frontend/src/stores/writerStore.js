import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion, chatCompletionStream } from '@/api/ai'
import { useProviderStore } from './providerStore'
import {
  buildChapterSystemPrompt,
  buildChapterPrompt,
  buildChapterBeatSystemPrompt,
  buildChapterBeatPrompt,
  buildContinuePrompt,
  buildExpandPrompt,
  buildCompressPrompt,
  buildMultiVariantPrompt,
  cleanGeneratedChapterText,
  cleanChapterBeatPlanText
} from '@/prompts/chapter'
import { buildRewriteSystemPrompt, buildRewritePrompt } from '@/prompts/rewrite'
import { buildCorrectionDraftPrompt } from '@/prompts/correctionDraft'

export const useWriterStore = defineStore('writer', () => {
  const chapters = ref([])
  const versions = ref([])
  const currentChapter = ref(null)
  const currentVersion = ref(null)
  const tempDraft = ref(null)
  const loading = ref(false)
  const generating = ref(false)
  const beatPlanning = ref(false)
  const chapterBeatPlan = ref('')
  const generationStream = ref('')

  function extractAiContent(result) {
    if (typeof result === 'string') return result
    if (result?.content) return result.content
    if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
    return result ? JSON.stringify(result) : ''
  }

  // === 章节管理 ===
  async function loadChapters(projectId) {
    loading.value = true
    try {
      chapters.value = await api.chapters.list(projectId)
      return chapters.value
    } catch (e) {
      console.error('加载章节列表失败:', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function getOrCreateChapter(projectId, chapterNum) {
    try {
      const existing = chapters.value.find(c => c.chapterNum === chapterNum)
      if (existing) {
        currentChapter.value = existing
        return existing
      }
      const chapter = await api.chapters.create(projectId, { chapterNum, title: `第 ${chapterNum} 章` })
      chapters.value.push(chapter)
      chapters.value.sort((a, b) => a.chapterNum - b.chapterNum)
      currentChapter.value = chapter
      return chapter
    } catch (e) {
      console.error('获取/创建章节失败:', e.message)
      throw e
    }
  }

  async function updateChapter(chapter) {
    try {
      const pid = chapter.projectId || chapter.project_id
      const data = {
        title: chapter.title,
        status: chapter.status,
        summary: chapter.summary,
        wordCount: chapter.wordCount || (chapter.content?.length || 0),
        finalVersionId: chapter.finalVersionId
      }
      const updated = await api.chapters.update(pid, chapter.id, data)
      const idx = chapters.value.findIndex(c => c.id === chapter.id)
      if (idx !== -1) chapters.value[idx] = { ...chapter, ...updated }
      if (currentChapter.value?.id === chapter.id) currentChapter.value = { ...chapter, ...updated }
    } catch (e) {
      console.error('更新章节失败:', e.message)
      throw e
    }
  }

  async function deleteChapter(id) {
    try {
      const ch = chapters.value.find(c => c.id === id)
      if (!ch) return
      chapters.value = chapters.value.filter(c => c.id !== id)
      if (currentChapter.value?.id === id) currentChapter.value = null
    } catch (e) {
      console.error('删除章节失败:', e.message)
      throw e
    }
  }

  // === 版本管理 ===
  async function loadVersions(projectId, chapterId) {
    try {
      versions.value = await api.versions.list(projectId, chapterId)
      return versions.value
    } catch (e) {
      console.error('加载版本列表失败:', e.message)
      throw e
    }
  }

  async function createVersion(projectId, chapterId, chapterNum, data) {
    try {
      const version = await api.versions.create(projectId, chapterId, {
        title: data.title || '',
        content: data.content || '',
        versionType: data.versionType || 'ai_candidate',
        sourceModelId: data.sourceModelId || null,
        promptBrief: data.promptBrief || ''
      })
      versions.value.unshift(version)
      return version
    } catch (e) {
      console.error('创建版本失败:', e.message)
      throw e
    }
  }

  async function updateVersion(version) {
    try {
      const pid = version.projectId || version.project_id
      const cid = version.chapterId || version.chapter_id
      const updated = await api.versions.update(pid, cid, version.id, {
        title: version.title,
        content: version.content,
        versionType: version.versionType
      })
      const idx = versions.value.findIndex(v => v.id === version.id)
      if (idx !== -1) versions.value[idx] = updated
      if (currentVersion.value?.id === version.id) currentVersion.value = updated
    } catch (e) {
      console.error('更新版本失败:', e.message)
      throw e
    }
  }

  async function deleteVersion(id) {
    try {
      const v = versions.value.find(v => v.id === id)
      if (!v) return
      const pid = v.projectId || v.project_id
      const cid = v.chapterId || v.chapter_id
      await api.versions.delete(pid, cid, id)
      versions.value = versions.value.filter(v => v.id !== id)
      if (currentVersion.value?.id === id) currentVersion.value = null
    } catch (e) {
      console.error('删除版本失败:', e.message)
      throw e
    }
  }

  // === 自动保存草稿 ===
  async function saveTempDraft(projectId, chapterNum, content) {
    try {
      await api.tempDrafts.save(projectId, chapterNum, content)
      tempDraft.value = { projectId, chapterNum, content, savedAt: Date.now() }
    } catch (e) {
      console.error('保存草稿失败:', e.message)
      // 静默失败，不中断用户输入
    }
  }

  async function loadTempDraft(projectId, chapterNum) {
    try {
      tempDraft.value = await api.tempDrafts.get(projectId, chapterNum)
      return tempDraft.value
    } catch (e) {
      console.error('加载草稿失败:', e.message)
      tempDraft.value = null
      return null
    }
  }

  async function clearTempDraft(projectId, chapterNum) {
    try {
      await api.tempDrafts.delete(projectId, chapterNum)
      tempDraft.value = null
    } catch (e) {
      console.error('清除草稿失败:', e.message)
    }
  }

  // === AI 生成章前小纲 ===
  async function generateChapterBeatPlan(projectId, chapterNum, context, providerId) {
    beatPlanning.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const provider = providerId
        ? providerStore.providers.find(p => p.id === providerId)
        : providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')

      const messages = [
        { role: 'system', content: buildChapterBeatSystemPrompt() },
        { role: 'user', content: buildChapterBeatPrompt({ chapterNum, ...context }) }
      ]

      const result = await chatCompletion(provider, messages, { maxTokens: 2048, temperature: 0.72 })
      const content = cleanChapterBeatPlanText(extractAiContent(result))
      chapterBeatPlan.value = content
      return content
    } catch (e) {
      console.error('生成章前小纲失败:', e.message)
      throw e
    } finally {
      beatPlanning.value = false
    }
  }

  // === AI 生成章节（流式） ===
  async function generateChapter(projectId, chapterNum, context, providerId, onStream) {
    generating.value = true
    generationStream.value = ''
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const provider = providerId
        ? providerStore.providers.find(p => p.id === providerId)
        : providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')

      const messages = [
        { role: 'system', content: buildChapterSystemPrompt() },
        { role: 'user', content: buildChapterPrompt({ chapterNum, ...context }) }
      ]

      let content = ''
      try {
        const stream = await chatCompletionStream(provider, messages, { maxTokens: 4096, temperature: 0.8 })
        while (true) {
          const { done, delta } = await stream.readNext()
          if (delta) {
            content += delta
            generationStream.value = content
            if (onStream) onStream(content, delta)
          }
          if (done) break
        }
      } catch (streamErr) {
        console.warn('流式请求失败，回退到非流式:', streamErr.message)
        const result = await chatCompletion(provider, messages, { maxTokens: 4096, temperature: 0.8 })
        if (typeof result === 'string') content = result
        else if (result?.content) content = result.content
        else if (result?.choices?.[0]?.message?.content) content = result.choices[0].message.content
      }

      content = cleanGeneratedChapterText(content)
      generationStream.value = content
      if (onStream) onStream(content, '')

      const chapter = await getOrCreateChapter(projectId, chapterNum)
      const version = await createVersion(projectId, chapter.id, chapterNum, {
        title: `第 ${chapterNum} 章 - AI 候选`,
        content,
        versionType: 'ai_candidate',
        sourceModelId: provider.id,
        promptBrief: context?.beatPlan ? '按确认小纲生成章节' : '章节生成'
      })
      currentVersion.value = version
      return version
    } finally {
      generating.value = false
    }
  }

  async function generateCorrectionDraft(projectId, chapterNum, task, originalContent, providerId) {
    generating.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const provider = providerId
        ? providerStore.providers.find(p => p.id === providerId)
        : providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')

      const result = await chatCompletion(provider, [
        {
          role: 'user',
          content: buildCorrectionDraftPrompt({ chapterNum, originalContent, task })
        }
      ], { maxTokens: 8192, temperature: 0.62 })

      const content = cleanGeneratedChapterText(extractAiContent(result))
      const chapter = await getOrCreateChapter(projectId, chapterNum)
      const version = await createVersion(projectId, chapter.id, chapterNum, {
        title: `第 ${chapterNum} 章 - 纠偏候选`,
        content,
        versionType: 'correction_candidate',
        sourceModelId: provider.id,
        promptBrief: `纠偏任务：${task?.title || ''}`.slice(0, 180)
      })
      currentVersion.value = version
      return version
    } finally {
      generating.value = false
    }
  }

  // === AI 续写 ===
  async function continueWriting(currentContent, instruction, providerId, context = {}) {
    generating.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const provider = providerId
        ? providerStore.providers.find(p => p.id === providerId)
        : providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')
      const messages = [{ role: 'user', content: buildContinuePrompt(currentContent, instruction, context) }]
      return await chatCompletion(provider, messages, { maxTokens: 2048, temperature: 0.8 })
    } finally {
      generating.value = false
    }
  }

  // === AI 多候选生成 ===
  async function generateMultiVariants(projectId, chapterNum, context) {
    generating.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const provider = providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')
      const messages = [
        { role: 'system', content: buildChapterSystemPrompt() },
        { role: 'user', content: buildMultiVariantPrompt({ chapterNum, ...context }) }
      ]
      const result = await chatCompletion(provider, messages, { maxTokens: 8192, temperature: 0.85 })
      let content = ''
      if (typeof result === 'string') content = result
      else if (result?.content) content = result.content
      else if (result?.choices?.[0]?.message?.content) content = result.choices[0].message.content
      content = cleanGeneratedChapterText(content)

      const results = []
      const chapter = await getOrCreateChapter(projectId, chapterNum)
      const splits = content.split(/(?=#+\s*(?:稳妥推进|强冲突|意外转向|文学气质))/)
      const labels = ['稳妥推进版', '强冲突版', '意外转向版']
      for (let i = 0; i < splits.length; i++) {
        if (splits[i].trim()) {
          const v = await createVersion(projectId, chapter.id, chapterNum, {
            title: `第 ${chapterNum} 章 - ${labels[i] || '候选'}`,
            content: splits[i].trim(),
            versionType: 'ai_candidate',
            sourceModelId: provider.id,
            promptBrief: `多候选生成 - ${labels[i] || '候选'}`
          })
          results.push(v)
        }
      }
      return results
    } finally {
      generating.value = false
    }
  }

  // === AI 选区重写 ===
  async function rewriteSelection(selectedText, mode, context, providerId) {
    generating.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const provider = providerId
        ? providerStore.providers.find(p => p.id === providerId)
        : providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')
      const messages = [
        { role: 'system', content: buildRewriteSystemPrompt() },
        { role: 'user', content: buildRewritePrompt(selectedText, mode, context) }
      ]
      const result = await chatCompletion(provider, messages, { maxTokens: 2048, temperature: 0.7 })
      if (typeof result === 'string') return result
      if (result?.content) return result.content
      if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
      return result
    } finally {
      generating.value = false
    }
  }

  // === AI 扩写 ===
  async function expandText(selectedText, context = {}) {
    generating.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const provider = providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')
      const messages = [{ role: 'user', content: buildExpandPrompt(selectedText, context) }]
      const result = await chatCompletion(provider, messages, { maxTokens: 2048, temperature: 0.7 })
      if (typeof result === 'string') return result
      if (result?.content) return result.content
      if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
      return result
    } finally {
      generating.value = false
    }
  }

  // === AI 压缩 ===
  async function compressText(selectedText) {
    generating.value = true
    try {
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const provider = providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')
      const messages = [{ role: 'user', content: buildCompressPrompt(selectedText) }]
      const result = await chatCompletion(provider, messages, { maxTokens: 1024, temperature: 0.5 })
      if (typeof result === 'string') return result
      if (result?.content) return result.content
      if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
      return result
    } finally {
      generating.value = false
    }
  }

  // === 确认定稿 ===
  async function finalizeVersion(version) {
    try {
      const pid = version.projectId || version.project_id
      const cid = version.chapterId || version.chapter_id
      await api.versions.update(pid, cid, version.id, { versionType: 'final' })
      version.versionType = 'final'

      const chapter = chapters.value.find(c => c.id === cid)
      if (chapter) {
        chapter.finalVersionId = version.id
        chapter.status = 'final'
        chapter.summary = chapter.summary || ''
        chapter.wordCount = version.content?.length || 0
        await updateChapter(chapter)
      }

      const vIdx = versions.value.findIndex(v => v.id === version.id)
      if (vIdx !== -1) versions.value[vIdx] = version
      if (currentVersion.value?.id === version.id) currentVersion.value = version

      return version
    } catch (e) {
      console.error('定稿失败:', e.message)
      throw e
    }
  }

  return {
    chapters,
    versions,
    currentChapter,
    currentVersion,
    tempDraft,
    loading,
    generating,
    beatPlanning,
    chapterBeatPlan,
    generationStream,
    loadChapters,
    getOrCreateChapter,
    updateChapter,
    deleteChapter,
    loadVersions,
    createVersion,
    updateVersion,
    deleteVersion,
    saveTempDraft,
    loadTempDraft,
    clearTempDraft,
    generateChapterBeatPlan,
    generateChapter,
    generateCorrectionDraft,
    continueWriting,
    generateMultiVariants,
    rewriteSelection,
    expandText,
    compressText,
    finalizeVersion
  }
})
