function text(value) {
  if (value == null) return ''
  if (Array.isArray(value)) return value.filter(Boolean).join('；')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function compact(value, max = 900) {
  return text(value).replace(/\s+/g, ' ').trim().slice(0, max)
}

function formatSeed(seed) {
  if (!seed) return '暂无'
  return [
    seed.title ? `标题：${seed.title}` : '',
    seed.genre ? `题材：${seed.genre}` : '',
    seed.logline ? `一句话：${seed.logline}` : '',
    seed.protagonist ? `主角：${compact(seed.protagonist, 500)}` : '',
    seed.coreConflict ? `核心矛盾：${compact(seed.coreConflict, 700)}` : '',
    seed.endingAnchor ? `结局锚点：${compact(seed.endingAnchor, 500)}` : ''
  ].filter(Boolean).join('\n') || '暂无'
}

function formatBible(bible) {
  if (!bible) return '暂无'
  return [
    bible.premise ? `故事前提：${compact(bible.premise, 600)}` : '',
    bible.themeBible ? `主题与母题：${compact(bible.themeBible, 600)}` : '',
    bible.worldRules ? `世界规则：${compact(bible.worldRules, 800)}` : '',
    bible.styleBible ? `风格基准：${compact(bible.styleBible, 500)}` : '',
    bible.forbiddenDirections ? `禁止方向：${compact(bible.forbiddenDirections, 500)}` : ''
  ].filter(Boolean).join('\n') || '暂无'
}

function formatSettings(entities = []) {
  const rows = (entities || []).slice(0, 30).map(entity => [
    entity.entityType || entity.type || '设定',
    entity.name || entity.entityName || '',
    compact(entity.summary || entity.profile || '', 160)
  ].filter(Boolean).join('｜'))
  return rows.length ? rows.map(row => `- ${row}`).join('\n') : '暂无'
}

export function buildVolumePlanSystemPrompt() {
  return `你是长篇小说分卷规划编辑。你只负责生成中层结构，不写正文。
分卷规划用于约束未来 30-60 章的大方向，必须粗粒度、可执行、可滚动调整。
只输出合法 JSON，不要 Markdown，不要解释。`
}

export function buildVolumePlanPrompt({ project, seed, bible, settings, volumeCount, chapterSize } = {}) {
  const targetChapters = Number(project?.targetChapters || 100)
  const targetWords = Number(project?.targetWords || 100000)
  const count = Number(volumeCount || Math.max(1, Math.ceil(targetChapters / Number(chapterSize || 60))))
  const size = Number(chapterSize || Math.ceil(targetChapters / count))

  return `请为这个长篇小说生成 ${count} 卷分卷规划。

## 项目信息
- 项目名：${project?.title || '未命名项目'}
- 题材：${project?.genre || '未填写'}
- 简介：${project?.description || '未填写'}
- 目标字数：${targetWords}
- 目标章节数：${targetChapters}
- 建议每卷章节：约 ${size} 章

## 当前创作种子
${formatSeed(seed)}

## 创作圣经
${formatBible(bible)}

## 已确认设定摘要
${formatSettings(settings)}

## 输出 JSON 格式
{
  "volumes": [
    {
      "volumeNum": 1,
      "title": "第一卷 卷名",
      "startChapter": 1,
      "endChapter": 50,
      "targetWords": 250000,
      "coreGoal": "本卷阶段目标，说明主角和主线必须发生的变化",
      "mainConflict": "本卷核心冲突，不要写成空泛主题",
      "keyCharacters": ["主角", "关键配角或对手"],
      "summary": "本卷大方向和阶段概要，不要细化到单章剧情。",
      "foreshadowingPlan": ["本卷需要埋下的伏笔", "本卷需要回收的伏笔"],
      "unresolvedItems": ["本卷暂不解决、必须留到后续卷的问题"],
      "handoffPoint": "卷尾交接点：本卷结束时交给下一卷的状态、压力或未完成选择"
    }
  ]
}

## 规划要求
1. 必须覆盖第 1 章到第 ${targetChapters} 章，章节范围连续且不重叠。
2. 每卷目标字数按章节比例分配，总体接近 ${targetWords}。
3. 每卷都要有明确阶段目标、核心冲突和卷尾交接点，不能只写“成长”“升级”“探索真相”这种空话。
4. foreshadowingPlan 只写本卷要埋或要回收的伏笔；unresolvedItems 只写本卷暂不解决的内容；handoffPoint 只写卷尾交接点。
5. 前几卷可以稍细，后几卷保持粗粒度，不要细化到单章剧情。
6. 不要提前解决终局矛盾；后续卷只给方向，不剧透完整解法。
7. 不要生成正文、小纲或章节列表。`
}

export function buildVolumePlanRepairPrompt(rawText, project) {
  return `下面是不稳定格式的分卷规划输出。请修复为合法 JSON，不要新增剧情，不要解释。
必须输出 {"volumes":[...]}，每项包含 volumeNum、title、startChapter、endChapter、targetWords、coreGoal、mainConflict、keyCharacters、summary、foreshadowingPlan、unresolvedItems、handoffPoint。
目标章节数：${Number(project?.targetChapters || 100)}

原始内容：
${String(rawText || '').slice(0, 12000)}`
}
