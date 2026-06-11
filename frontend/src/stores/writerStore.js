import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/db/client'
import { chatCompletion, chatCompletionStream } from '@/api/ai'
import { useProviderStore } from './providerStore'
import { useProjectStore } from './projectStore'
import {
  buildDraftSystemPrompt as buildChapterSystemPrompt,
  buildDraftPrompt as buildChapterPrompt
} from '@/prompts/chapterDraftPrompt'
import {
  buildScenePlanSystemPrompt as buildChapterBeatSystemPrompt,
  buildScenePlanPrompt as buildChapterBeatPrompt
} from '@/prompts/chapterPlanPrompt'
import {
  buildContinuePrompt,
  buildExpandPrompt,
  buildCompressPrompt,
  buildMultiVariantPrompt,
  buildChapterTitleSystemPrompt,
  buildChapterTitlePrompt,
  buildProseRhythmRepairSystemPrompt,
  buildProseRhythmRepairPrompt,
  parseMultiVariantText,
  cleanGeneratedChapterText,
  cleanChapterBeatPlanText,
  cleanGeneratedChapterTitle,
  deriveFallbackChapterTitle,
  isDefaultChapterTitle
} from '@/prompts/chapter'
import { buildRewriteSystemPrompt, buildRewritePrompt } from '@/prompts/rewrite'
import { buildCorrectionDraftPrompt } from '@/prompts/correctionDraft'
import {
  buildCorrectionPatchPrompt,
  buildCorrectionPatchRepairPrompt,
  buildCorrectionPatchRetryPrompt
} from '@/prompts/correctionPatch'
import { applyLocalRevisionPatches, extractLocalRevisionPatches } from '@/utils/localRevisionPatch'
import {
  analyzeProseRhythm,
  countCjkChars,
  shouldAcceptProseRhythmRepair,
  shouldRepairProseRhythm
} from '@/utils/proseRhythmGuard'

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
  const beatPlanRecord = ref(null)
  const generationStream = ref('')

  function extractAiContent(result) {
    if (typeof result === 'string') return result
    if (result?.content) return result.content
    if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
    return result ? JSON.stringify(result) : ''
  }

  async function compactChapterBeatPlanIfNeeded(provider, chapterNum, content, context = {}) {
    content = String(content || '').trim()
    if (content.length <= 1300) return content

    let best = content
    try {
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        const messages = [
          {
            role: 'system',
            content: '你是长篇小说分章小纲编辑。只负责压缩小纲，不写正文，不解释。'
          },
          {
            role: 'user',
            content: [
              `请把第 ${chapterNum} 章小纲压缩为 700-1100 字，绝不能超过 1300 字。`,
              '节拍控制在 4-6 条，保留本章核心目的、人物动机、关键选择、代价、结尾钩子、连续性自检和写作约束。',
              '必须保留时间线连续性、状态延续、道具来源、人物铺垫和伏笔铺垫的关键提醒，但用短句合并表达。',
              '不要新增剧情，不要改变因果顺序，不要把两章容量塞进一章。',
              context?.previousChapterEnding ? `上一章结尾：${context.previousChapterEnding}` : '',
              attempt > 1 ? `上一次压缩仍过长（${best.length} 字符），请继续压缩。` : '',
              `原小纲：\n${best}`
            ].filter(Boolean).join('\n\n')
          }
        ]
        const result = await chatCompletion(provider, messages, { maxTokens: 1400, temperature: 0.3 })
        const compacted = cleanChapterBeatPlanText(extractAiContent(result))
        if (compacted.length >= 500 && compacted.length < best.length) best = compacted
        if (best.length <= 1300) return best
      }

      if (best.length < content.length) {
        console.warn('压缩章节小纲后仍超过建议上限，已阻止继续生成正文:', {
          before: content.length,
          after: best.length
        })
        throw new Error(`第 ${chapterNum} 章小纲压缩后仍超过上限（${content.length} -> ${best.length} 字符），请重新生成或手动删减后再生成正文。`)
      }
    } catch (e) {
      console.warn('压缩章节小纲失败，已阻止继续生成正文:', e.message)
      throw e
    }
    throw new Error(`第 ${chapterNum} 章小纲超过上限（${content.length} 字符），请重新生成或手动删减后再生成正文。`)
  }

  async function expandChapterBeatPlanIfNeeded(provider, chapterNum, content, context = {}) {
    content = String(content || '').trim()
    if (content.length >= 500) return content

    let best = content
    try {
      for (let attempt = 1; attempt <= 2; attempt += 1) {
        const messages = [
          {
            role: 'system',
            content: '你是长篇小说分章小纲编辑。只负责把过短小纲扩展成可执行小纲，不写正文，不解释。'
          },
          {
            role: 'user',
            content: [
              `请把第 ${chapterNum} 章小纲扩展为 700-1100 字，控制在 4-6 个节拍，绝不能超过 1300 字。`,
              '必须补足：本章核心目的、场景摩擦、人物欲望/恐惧/遮掩、关键选择、选择代价、信息释放方式、状态延续、道具来源、伏笔铺垫和章末钩子。',
              '只扩展可执行节拍，不写正文句子，不新增完整大场景，不把下一章冲突提前塞进本章。',
              context?.previousChapterEnding ? `上一章结尾：${context.previousChapterEnding}` : '',
              context?.chapterGoal ? `本章目标：${JSON.stringify(context.chapterGoal).slice(0, 800)}` : '',
              attempt > 1 ? `上一次扩展仍过短或不合格（${best.length} 字符），请补足可执行节拍。` : '',
              `原小纲：\n${best || '只有空白或极短提示，请根据本章上下文补成可执行小纲。'}`
            ].filter(Boolean).join('\n\n')
          }
        ]
        const result = await chatCompletion(provider, messages, { maxTokens: 1800, temperature: 0.35 })
        const expanded = cleanChapterBeatPlanText(extractAiContent(result))
        if (expanded.length > best.length && expanded.length <= 1300) best = expanded
        if (best.length >= 500 && best.length <= 1300) return best
      }
    } catch (e) {
      console.warn('扩展章节小纲失败，已阻止继续生成正文:', e.message)
      throw e
    }

    throw new Error(`第 ${chapterNum} 章小纲过短（${content.length} 字符），请重新生成或手动补足人物动机、场景摩擦、选择代价和章末钩子后再生成正文。`)
  }

  async function ensureChapterBeatPlanQuality(provider, chapterNum, content, context = {}) {
    content = cleanChapterBeatPlanText(String(content || '').trim())
    if (!content) {
      throw new Error(`第 ${chapterNum} 章小纲为空，请先生成或填写本章小纲。`)
    }

    if (content.length > 1300) {
      content = await compactChapterBeatPlanIfNeeded(provider, chapterNum, content, context)
    }
    if (content.length < 500) {
      content = await expandChapterBeatPlanIfNeeded(provider, chapterNum, content, context)
    }
    if (content.length > 1300) {
      content = await compactChapterBeatPlanIfNeeded(provider, chapterNum, content, context)
    }

    if (content.length < 500) {
      throw new Error(`第 ${chapterNum} 章小纲过短（${content.length} 字符），请重新生成或手动补足后再生成正文。`)
    }
    if (content.length > 1300) {
      throw new Error(`第 ${chapterNum} 章小纲超过上限（${content.length} 字符），请重新生成或手动删减后再生成正文。`)
    }
    return content
  }

  async function repairProseRhythmIfNeeded(provider, chapterNum, content, context = {}) {
    const original = String(content || '').trim()
    const analysis = analyzeProseRhythm(original)
    if (!shouldRepairProseRhythm(analysis)) return original

    try {
      const result = await chatCompletion(provider, [
        { role: 'system', content: buildProseRhythmRepairSystemPrompt() },
        {
          role: 'user',
          content: buildProseRhythmRepairPrompt({
            chapterNum,
            content: original,
            analysis,
            beatPlan: context?.beatPlan,
            context
          })
        }
      ], { maxTokens: 8192, temperature: 0.28 })

      const repaired = cleanGeneratedChapterText(extractAiContent(result))
      const repairedAnalysis = analyzeProseRhythm(repaired)
      const originalCount = Math.max(countCjkChars(original), 1)
      const repairedCount = countCjkChars(repaired)
      const drift = repairedCount / originalCount
      const improved =
        repaired &&
        repaired !== original &&
        shouldAcceptProseRhythmRepair(analysis, repairedAnalysis, drift)

      if (improved) return repaired
      console.warn('正文节奏修订未带来稳定改善，保留原稿', {
        before: analysis,
        after: repairedAnalysis,
        drift
      })
    } catch (e) {
      console.warn('正文节奏修订失败，保留原稿:', e.message)
    }
    return original
  }

  async function resolveTaskProvider(projectId, bindingKeys = [], providerId = null) {
    const providerStore = useProviderStore()
    await providerStore.ensureProvidersLoaded()

    if (providerId) {
      const explicitProvider = providerStore.providers.find(p => p.id === providerId)
      if (!explicitProvider) throw new Error('指定的模型配置不存在或已被删除')
      return explicitProvider
    }

    const fallbackProjectId = projectId || useProjectStore().currentProject?.id || currentChapter.value?.projectId || currentChapter.value?.project_id
    let bindings = null
    if (fallbackProjectId) {
      try {
        bindings = await providerStore.getBindings(fallbackProjectId)
      } catch (e) {
        console.warn('读取任务模型映射失败，回退到默认模型:', e.message)
      }
    }

    for (const key of bindingKeys) {
      const modelId = bindings?.[key]
      if (!modelId) continue
      const mappedProvider = providerStore.providers.find(p => p.id === modelId)
      if (mappedProvider) return mappedProvider
    }

    const defaultProvider = providerStore.providers[0]
    if (!defaultProvider) throw new Error('请先在设置中配置模型')
    return defaultProvider
  }

  async function syncProjectCurrentChapter(projectId, chapterNum) {
    try {
      const projectStore = useProjectStore()
      await projectStore.updateCurrentChapterNum(projectId, chapterNum)
    } catch (e) {
      console.warn('同步项目当前章节失败:', e.message)
    }
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

  async function bulkCreateEmptyChapters(projectId, targetChapters) {
    const total = Number(targetChapters || 0)
    if (!projectId || total < 1) return []

    const existingNums = new Set(chapters.value.map(ch => Number(ch.chapterNum)))
    const created = []

    for (let chapterNum = 1; chapterNum <= total; chapterNum += 1) {
      if (existingNums.has(chapterNum)) continue
      const chapter = await api.chapters.create(projectId, {
        chapterNum,
        title: `第 ${chapterNum} 章`
      })
      created.push(chapter)
      chapters.value.push(chapter)
      existingNums.add(chapterNum)
    }

    chapters.value.sort((a, b) => a.chapterNum - b.chapterNum)
    return created
  }

  async function bulkCreateEmptyChapterRange(projectId, startChapter, endChapter) {
    const start = Number(startChapter || 0)
    const end = Number(endChapter || 0)
    if (!projectId || start < 1 || end < start) return []

    const existingNums = new Set(chapters.value.map(ch => Number(ch.chapterNum)))
    const created = []

    for (let chapterNum = start; chapterNum <= end; chapterNum += 1) {
      if (existingNums.has(chapterNum)) continue
      const chapter = await api.chapters.create(projectId, {
        chapterNum,
        title: `第 ${chapterNum} 章`
      })
      created.push(chapter)
      chapters.value.push(chapter)
      existingNums.add(chapterNum)
    }

    chapters.value.sort((a, b) => a.chapterNum - b.chapterNum)
    return created
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

  async function generateDefaultChapterTitle(projectId, chapter, chapterNum, content, context, provider, options = {}) {
    if (!projectId || !chapter?.id || !content) return ''
    if (!options.force && !isDefaultChapterTitle(chapter.title, chapterNum)) return chapter.title || ''
    const resolvedProvider = provider || await resolveTaskProvider(projectId, ['summaryModelId', 'writingModelId'])

    const messages = [
      { role: 'system', content: buildChapterTitleSystemPrompt() },
      {
        role: 'user',
        content: buildChapterTitlePrompt({
          chapterNum,
          chapterGoal: context?.chapterGoal,
          beatPlan: context?.beatPlan,
          content
        })
      }
    ]

    const result = await chatCompletion(resolvedProvider, messages, { maxTokens: 80, temperature: 0.35 })
    const rawTitle = extractAiContent(result)
    let title = cleanGeneratedChapterTitle(rawTitle)
    if (!title) {
      const retryResult = await chatCompletion(resolvedProvider, [
        { role: 'system', content: buildChapterTitleSystemPrompt() },
        {
          role: 'user',
          content: [
            '上一次输出不像章名，可能是正文片段或剧情摘要，请重新命名。',
            `上一次输出：${rawTitle}`,
            buildChapterTitlePrompt({
              chapterNum,
              chapterGoal: context?.chapterGoal,
              beatPlan: context?.beatPlan,
              content
            }),
            '请输出一个 2-10 个汉字的短章名，例如“旧宅无名”“后山无人棋”“雨夜归人”这种目录标题，不要输出句子。'
          ].join('\n\n')
        }
      ], { maxTokens: 80, temperature: 0.25 })
      title = cleanGeneratedChapterTitle(extractAiContent(retryResult))
    }
    if (!title) {
      title = deriveFallbackChapterTitle({
        chapterGoal: context?.chapterGoal,
        beatPlan: context?.beatPlan,
        content
      })
    }
    if (!title) return ''

    const updated = await api.chapters.updateTitle(projectId, chapter.id, { title })
    const idx = chapters.value.findIndex(c => c.id === chapter.id)
    if (idx !== -1) chapters.value[idx] = { ...chapters.value[idx], ...updated }
    if (currentChapter.value?.id === chapter.id) currentChapter.value = { ...currentChapter.value, ...updated }
    return title
  }

  async function deleteChapter(id) {
    try {
      const ch = chapters.value.find(c => c.id === id)
      if (!ch) return
      await api.chapters.delete(ch.projectId || ch.project_id, id)
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

  // === 章节小纲持久化 ===
  async function loadChapterBeatPlan(projectId, chapterNum) {
    try {
      beatPlanRecord.value = await api.beatPlans.get(projectId, chapterNum)
      chapterBeatPlan.value = beatPlanRecord.value?.content || ''
      return beatPlanRecord.value
    } catch (e) {
      console.error('加载章节小纲失败:', e.message)
      beatPlanRecord.value = null
      chapterBeatPlan.value = ''
      return null
    }
  }

  async function saveChapterBeatPlan(projectId, chapterNum, content) {
    try {
      beatPlanRecord.value = await api.beatPlans.save(projectId, chapterNum, content)
      chapterBeatPlan.value = beatPlanRecord.value?.content || content || ''
      return beatPlanRecord.value
    } catch (e) {
      console.error('保存章节小纲失败:', e.message)
      throw e
    }
  }

  async function clearChapterBeatPlan(projectId, chapterNum) {
    try {
      await api.beatPlans.delete(projectId, chapterNum)
      beatPlanRecord.value = null
      chapterBeatPlan.value = ''
    } catch (e) {
      console.error('清除章节小纲失败:', e.message)
      throw e
    }
  }

  // === AI 生成章前小纲 ===
  async function generateChapterBeatPlan(projectId, chapterNum, context, providerId) {
    beatPlanning.value = true
    try {
      const provider = await resolveTaskProvider(projectId, ['outlineModelId', 'writingModelId'], providerId)

      const messages = [
        { role: 'system', content: buildChapterBeatSystemPrompt() },
        { role: 'user', content: buildChapterBeatPrompt({ chapterNum, ...context }) }
      ]

      const result = await chatCompletion(provider, messages, { maxTokens: 1800, temperature: 0.6 })
      let content = cleanChapterBeatPlanText(extractAiContent(result))
      content = await ensureChapterBeatPlanQuality(provider, chapterNum, content, context)
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
      const provider = await resolveTaskProvider(projectId, ['writingModelId'], providerId)
      if (context?.beatPlan) {
        context = { ...context, beatPlan: await ensureChapterBeatPlanQuality(provider, chapterNum, context.beatPlan, context) }
      }

      const messages = [
        { role: 'system', content: buildChapterSystemPrompt() },
        { role: 'user', content: buildChapterPrompt({ chapterNum, ...context }) }
      ]

      let content = ''
      try {
        const stream = await chatCompletionStream(provider, messages, { maxTokens: 8192, temperature: 0.8 })
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
        const result = await chatCompletion(provider, messages, { maxTokens: 8192, temperature: 0.8 })
        if (typeof result === 'string') content = result
        else if (result?.content) content = result.content
        else if (result?.choices?.[0]?.message?.content) content = result.choices[0].message.content
      }

      content = cleanGeneratedChapterText(content)
      content = await repairProseRhythmIfNeeded(provider, chapterNum, content, context)
      if (!content.trim()) {
        throw new Error('AI 生成正文为空，请重新生成或切换模型后重试。')
      }
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
      await syncProjectCurrentChapter(projectId, chapterNum)
      currentVersion.value = version
      return version
    } finally {
      generating.value = false
    }
  }

  async function generateCorrectionDraft(projectId, chapterNum, taskOrTasks, originalContent, providerId) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(projectId, ['polishModelId', 'auditModelId', 'writingModelId'], providerId)

      const result = await chatCompletion(provider, [
        {
          role: 'user',
          content: buildCorrectionDraftPrompt({
            chapterNum,
            originalContent,
            tasks: normalizeCorrectionTasks(taskOrTasks)
          })
        }
      ], { maxTokens: 8192, temperature: 0.62 })

      const content = cleanGeneratedChapterText(extractAiContent(result))
      if (!content.trim()) {
        throw new Error('AI 生成纠偏草案为空，请重新生成或切换模型后重试。')
      }
      const chapter = await getOrCreateChapter(projectId, chapterNum)
      const taskCount = normalizeCorrectionTasks(taskOrTasks).length
      const version = await createVersion(projectId, chapter.id, chapterNum, {
        title: taskCount > 1 ? `第 ${chapterNum} 章 - 综合纠偏候选` : `第 ${chapterNum} 章 - 纠偏候选`,
        content,
        versionType: 'correction_candidate',
        sourceModelId: provider.id,
        promptBrief: buildCorrectionPromptBrief(taskOrTasks)
      })
      await syncProjectCurrentChapter(projectId, chapterNum)
      currentVersion.value = version
      return version
    } finally {
      generating.value = false
    }
  }

  async function generateLocalCorrectionPatchCandidate(projectId, chapterNum, issues, originalContent, providerId) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(projectId, ['polishModelId', 'auditModelId', 'writingModelId'], providerId)

      const result = await chatCompletion(provider, [
        {
          role: 'user',
          content: buildCorrectionPatchPrompt({
            chapterNum,
            originalContent,
            issues
          })
        }
      ], { maxTokens: 4096, temperature: 0.35 })

      const text = extractAiContent(result)
      let patches = extractLocalRevisionPatches(text)
      if (!patches.length && text.trim()) {
        const repairResult = await chatCompletion(provider, [
          { role: 'user', content: buildCorrectionPatchRepairPrompt(text) }
        ], { maxTokens: 4096, temperature: 0 })
        patches = extractLocalRevisionPatches(extractAiContent(repairResult))
      }

      if (!patches.length) {
        const retryResult = await chatCompletion(provider, [
          {
            role: 'user',
            content: buildCorrectionPatchRetryPrompt({
              chapterNum,
              originalContent,
              issues,
              previousOutput: text
            })
          }
        ], { maxTokens: 4096, temperature: 0.2 })
        patches = extractLocalRevisionPatches(extractAiContent(retryResult))
      }

      const patchResult = applyLocalRevisionPatches(originalContent, patches)
      if (patchResult.applied.length) {
        const chapter = await getOrCreateChapter(projectId, chapterNum)
        const version = await createVersion(projectId, chapter.id, chapterNum, {
          title: `第 ${chapterNum} 章 - 局部修订候选`,
          content: patchResult.content,
          versionType: 'correction_candidate',
          sourceModelId: provider.id,
          promptBrief: `本章审稿局部修订：应用 ${patchResult.applied.length} 处，跳过 ${patchResult.skipped.length} 处`
        })
        await syncProjectCurrentChapter(projectId, chapterNum)
        currentVersion.value = version
        return { version, ...patchResult, mode: 'local_patch' }
      }

      const skippedReasons = patchResult.skipped
        .map(item => item.reason)
        .filter(Boolean)
      const reasonText = skippedReasons.length ? `跳过原因：${[...new Set(skippedReasons)].join('、')}。` : ''
      throw new Error(`AI 没有返回可安全应用的局部修订补丁，${reasonText}请使用审稿面板的“定位原文/替换”，或手动选区改写。`)
    } finally {
      generating.value = false
    }
  }

  // === AI 续写 ===
  async function continueWriting(currentContent, instruction, providerId, context = {}) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(context?.projectId, ['writingModelId'], providerId)
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
      const provider = await resolveTaskProvider(projectId, ['writingModelId'])
      const messages = [
        { role: 'system', content: buildChapterSystemPrompt() },
        { role: 'user', content: buildMultiVariantPrompt({ chapterNum, ...context }) }
      ]
      const result = await chatCompletion(provider, messages, { maxTokens: 8192, temperature: 0.85 })
      let content = ''
      if (typeof result === 'string') content = result
      else if (result?.content) content = result.content
      else if (result?.choices?.[0]?.message?.content) content = result.choices[0].message.content

      const results = []
      const chapter = await getOrCreateChapter(projectId, chapterNum)
      const variants = parseMultiVariantText(content)
      for (const variant of variants) {
        const v = await createVersion(projectId, chapter.id, chapterNum, {
          title: `第 ${chapterNum} 章 - ${variant.label || '候选'}`,
          content: variant.content,
          versionType: 'ai_candidate',
          sourceModelId: provider.id,
          promptBrief: `多候选生成 - ${variant.label || '候选'}`
        })
        results.push(v)
      }
      if (results.length > 0) await syncProjectCurrentChapter(projectId, chapterNum)
      return results
    } finally {
      generating.value = false
    }
  }

  // === AI 选区重写 ===
  async function rewriteSelection(selectedText, mode, context, providerId) {
    generating.value = true
    try {
      const provider = await resolveTaskProvider(context?.projectId, ['polishModelId', 'writingModelId'], providerId)
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
      const provider = await resolveTaskProvider(context?.projectId, ['polishModelId', 'writingModelId'])
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
      const provider = await resolveTaskProvider(null, ['polishModelId', 'summaryModelId', 'writingModelId'])
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
      const chapter = chapters.value.find(c => c.id === cid)
      if (chapter && isDefaultChapterTitle(chapter.title, chapter.chapterNum || chapter.chapter_num || version.chapterNum || version.chapter_num)) {
        try {
          await generateDefaultChapterTitle(
            pid,
            chapter,
            chapter.chapterNum || chapter.chapter_num || version.chapterNum || version.chapter_num,
            version.content,
            {}
          )
        } catch (titleErr) {
          console.warn('定稿章名生成失败，保留默认章名:', titleErr.message)
        }
      }
      const result = await api.versions.finalize(pid, cid, version.id, {
        summary: chapter?.summary || '',
        wordCount: version.content?.length || 0
      })
      const finalizedVersion = result?.version || { ...version, versionType: 'final' }
      const finalizedChapter = result?.chapter

      Object.assign(version, finalizedVersion)

      if (finalizedChapter) {
        const idx = chapters.value.findIndex(c => c.id === cid)
        if (idx !== -1) chapters.value[idx] = { ...chapters.value[idx], ...finalizedChapter }
        if (currentChapter.value?.id === cid) currentChapter.value = { ...currentChapter.value, ...finalizedChapter }
        await syncProjectCurrentChapter(pid, finalizedChapter.chapterNum || finalizedChapter.chapter_num)
      } else if (chapter) {
        chapter.finalVersionId = version.id
        chapter.status = 'final'
        chapter.wordCount = version.content?.length || 0
        await syncProjectCurrentChapter(pid, chapter.chapterNum || chapter.chapter_num)
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

  function normalizeCorrectionTasks(taskOrTasks) {
    if (Array.isArray(taskOrTasks)) return taskOrTasks.filter(Boolean)
    return taskOrTasks ? [taskOrTasks] : []
  }

  function normalizeAuditIssuesAsCorrectionTasks(issues) {
    return (Array.isArray(issues) ? issues : [])
      .filter(Boolean)
      .map((issue, index) => {
        const descriptionParts = [
          issue?.description,
          issue?.location ? `位置：${issue.location}` : '',
          issue?.reason ? `原因：${issue.reason}` : ''
        ].filter(Boolean)

        return {
          title: `本章审稿问题 ${index + 1}`,
          issueType: issue?.type || 'chapter_audit',
          severity: issue?.severity || 'minor',
          description: descriptionParts.join('\n') || '本章审稿发现的问题',
          suggestedAction: issue?.suggestion || '在不改动无关正文的前提下进行保守修订。'
        }
      })
  }

  function buildCorrectionPromptBrief(taskOrTasks) {
    const tasks = normalizeCorrectionTasks(taskOrTasks)
    const title = tasks.length > 1
      ? `综合纠偏任务：${tasks.map(task => task?.title || '未命名').join('；')}`.slice(0, 160)
      : `纠偏任务：${tasks[0]?.title || ''}`.slice(0, 130)
    const ids = tasks
      .map(task => task?.id)
      .filter(Boolean)
      .map(id => `[correctionTaskId:${id}]`)
      .join('\n')
    return ids ? `${title}\n${ids}` : title
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
    beatPlanRecord,
    generationStream,
    loadChapters,
    getOrCreateChapter,
    bulkCreateEmptyChapters,
    bulkCreateEmptyChapterRange,
    updateChapter,
    generateDefaultChapterTitle,
    deleteChapter,
    loadVersions,
    createVersion,
    updateVersion,
    deleteVersion,
    saveTempDraft,
    loadTempDraft,
    clearTempDraft,
    loadChapterBeatPlan,
    saveChapterBeatPlan,
    clearChapterBeatPlan,
    generateChapterBeatPlan,
    generateChapter,
    generateCorrectionDraft,
    generateLocalCorrectionPatchCandidate,
    continueWriting,
    generateMultiVariants,
    rewriteSelection,
    expandText,
    compressText,
    finalizeVersion
  }
})
