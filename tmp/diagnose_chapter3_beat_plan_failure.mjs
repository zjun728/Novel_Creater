import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8000/api'
const OUT_DIR = 'tmp/realistic-flow-qa'
const PROJECT_ID = process.env.PROJECT_ID || '5eb10995-7aa7-4027-9ac9-b350c9e673d7'
const REPORT_JSON = path.join(OUT_DIR, 'latest-longform-browser-live-report.json')
const OUT_JSON = path.join(OUT_DIR, 'chapter3-beat-plan-failure-diagnostics.json')
const OUT_MD = path.join(OUT_DIR, 'chapter3-beat-plan-failure-diagnostics.md')

mkdirSync(OUT_DIR, { recursive: true })

async function api(pathname) {
  const res = await fetch(`${API_BASE}${pathname}`)
  if (!res.ok) throw new Error(`API ${res.status} ${pathname}: ${await res.text()}`)
  const text = await res.text()
  return text ? JSON.parse(text) : null
}

function readLatestReport() {
  try {
    return JSON.parse(readFileSync(REPORT_JSON, 'utf8'))
  } catch {
    return null
  }
}

function stageId(stage = {}) {
  return stage.id || stage.stageId || stage.stage_id || ''
}

function stageStatus(stage = {}) {
  return stage.status || stage.stageStatus || stage.stage_status || 'planned'
}

function findNextStage(block = {}) {
  const stages = Array.isArray(block.stagePlan || block.stage_plan) ? (block.stagePlan || block.stage_plan) : []
  return stages.find(stage => !['completed', 'closed', 'skipped'].includes(String(stageStatus(stage)).toLowerCase()))
    || stages[0]
    || null
}

async function main() {
  const [project, chapters, blocks] = await Promise.all([
    api(`/projects/${PROJECT_ID}`).catch(error => ({ error: error.message })),
    api(`/projects/${PROJECT_ID}/chapters`).catch(() => []),
    api(`/projects/${PROJECT_ID}/story-blocks`).catch(() => [])
  ])
  const beatPlans = {}
  for (const chapterNum of [1, 2, 3]) {
    beatPlans[chapterNum] = await api(`/projects/${PROJECT_ID}/chapter-beat-plan/${chapterNum}`).catch(() => null)
  }
  const activeBlocks = (Array.isArray(blocks) ? blocks : []).filter(block => block.status === 'active')
  const activeBlock = activeBlocks[0] || null
  const nextStage = findNextStage(activeBlock || {})
  const latestReport = readLatestReport()
  const diagnostics = {
    checkedAt: new Date().toISOString(),
    mode: 'read_only_original_failure_project_diagnostic',
    projectId: PROJECT_ID,
    projectName: project?.title || project?.name || '',
    projectError: project?.error || '',
    chapters: (Array.isArray(chapters) ? chapters : []).map(chapter => ({
      chapterNum: chapter.chapterNum || chapter.chapter_num,
      title: chapter.title || '',
      status: chapter.status || '',
      wordCount: chapter.wordCount || chapter.word_count || 0,
      finalVersionId: chapter.finalVersionId || chapter.final_version_id || null
    })),
    activeStoryBlock: activeBlock ? {
      id: activeBlock.id || '',
      title: activeBlock.title || '',
      status: activeBlock.status || '',
      stageCount: Array.isArray(activeBlock.stagePlan || activeBlock.stage_plan) ? (activeBlock.stagePlan || activeBlock.stage_plan).length : 0,
      nextStage: nextStage ? {
        id: stageId(nextStage),
        status: stageStatus(nextStage),
        purpose: nextStage.purpose || nextStage.stagePurpose || nextStage.goal || '',
        sceneOrAction: nextStage.sceneOrAction || nextStage.action || nextStage.description || ''
      } : null,
      nextStageSuggestion: activeBlock.nextStageSuggestion || activeBlock.next_stage_suggestion || '',
      completedStages: activeBlock.completedStages || activeBlock.completed_stages || [],
      chapterRefs: activeBlock.chapterRefs || activeBlock.chapter_refs || []
    } : null,
    activeStoryBlockCount: activeBlocks.length,
    chapterBeatPlans: Object.fromEntries(Object.entries(beatPlans).map(([chapterNum, beat]) => [chapterNum, {
      exists: Boolean(beat?.content),
      storyBlockId: beat?.storyBlockId || beat?.story_block_id || '',
      blockStageId: beat?.blockStageId || beat?.block_stage_id || '',
      hasSnapshot: Boolean(beat?.blockStageSnapshot || beat?.block_stage_snapshot),
      contentLength: String(beat?.content || '').length
    }])),
    confirmsFailureShape: Boolean(activeBlock?.title === '夜行灵脉城' && !beatPlans[3]?.content),
    latestReportBlocker: latestReport?.blocker || null
  }

  writeFileSync(OUT_JSON, JSON.stringify(diagnostics, null, 2), 'utf8')
  writeFileSync(OUT_MD, [
    '# 第 3 章小纲失败原项目诊断',
    '',
    `- mode: ${diagnostics.mode}`,
    `- projectId: ${diagnostics.projectId}`,
    `- projectName: ${diagnostics.projectName || 'unknown'}`,
    `- activeStoryBlock: ${diagnostics.activeStoryBlock?.title || 'none'} (${diagnostics.activeStoryBlock?.id || 'none'})`,
    `- activeStoryBlockCount: ${diagnostics.activeStoryBlockCount}`,
    `- activeStageCount: ${diagnostics.activeStoryBlock?.stageCount ?? 0}`,
    `- activeNextStage: ${diagnostics.activeStoryBlock?.nextStage?.id || 'none'}`,
    `- chapter3BeatPlanExists: ${diagnostics.chapterBeatPlans['3']?.exists}`,
    `- confirmsFailureShape: ${diagnostics.confirmsFailureShape}`,
    '',
    '```json',
    JSON.stringify(diagnostics, null, 2),
    '```'
  ].join('\n'), 'utf8')
  console.log(JSON.stringify({
    projectId: diagnostics.projectId,
    activeStoryBlock: diagnostics.activeStoryBlock?.title || '',
    chapter3BeatPlanExists: diagnostics.chapterBeatPlans['3']?.exists,
    confirmsFailureShape: diagnostics.confirmsFailureShape,
    outJson: OUT_JSON
  }, null, 2))
}

main().catch(error => {
  console.error(error)
  process.exit(1)
})
