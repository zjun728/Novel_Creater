import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const REPORT_DIR = 'tmp/realistic-flow-qa'
const REPORT_JSON = join(REPORT_DIR, 'latest-story-block-report.json')
const REPORT_MD = join(REPORT_DIR, 'latest-story-block-report.md')

const allowedDecisions = [
  'continue_current_block',
  'adjust_remaining_stages',
  'split_unfinalized_content',
  'complete_current_block',
  'open_new_block'
]

const liveMode = process.env.STORY_BLOCK_QA_LIVE === '1'

function buildDryRunReport() {
  return {
    reportType: 'story_block_realistic_flow_v1',
    mode: 'contract_dry_run',
    createdCleanProject: false,
    usesArchivedReports: false,
    generatedAt: new Date().toISOString(),
    scope: '干净项目 3-5 章验收脚本结构检查；未连接后端和真实模型时不冒充验收结果。',
    requiredLiveChecks: [
      '创建干净新项目',
      '创建 active 故事块',
      '从故事块生成小纲',
      '保存 block_stage_snapshot',
      '正文生成读取 snapshot 边界',
      '审稿输出故事任务一致性和阅读负担',
      '定稿后执行块级回看',
      '报告记录每章 storyBlockId 和 block_stage_snapshot',
      '不引用旧报告'
    ],
    allowedDecisions,
    chapters: [],
    checks: [
      {
        name: '新报告目录',
        pass: true,
        detail: REPORT_DIR
      },
      {
        name: '旧报告引用',
        pass: true,
        detail: 'usesArchivedReports=false'
      }
    ],
    acceptance: {
      passed: false,
      reason: 'dry-run 只验证脚本结构；live 模式才可作为 3-5 章验收。'
    }
  }
}

async function buildLiveReport() {
  const appURL = process.env.STORY_BLOCK_QA_APP_URL || 'http://127.0.0.1:8000/api'
  const startedAt = new Date().toISOString()
  const report = {
    reportType: 'story_block_realistic_flow_v1',
    mode: 'live',
    createdCleanProject: true,
    usesArchivedReports: false,
    appURL,
    generatedAt: startedAt,
    allowedDecisions,
    chapters: [],
    checks: [],
    acceptance: {
      passed: false,
      reason: 'live run not completed'
    }
  }

  report.checks.push({
    name: 'live mode entry',
    pass: true,
    detail: '脚本已进入 live 模式；后续步骤应创建新项目并跑 3-5 章。'
  })

  // v1 脚本先建立干净报告结构，避免复用旧真实流程报告。
  // 真正的模型调用和 3-5 章端到端跑法在主产品线程确认模型配置后填充。
  report.acceptance = {
    passed: false,
    reason: 'live 模式需要可用后端、模型配置和人工确认后继续执行。'
  }
  return report
}

function renderMarkdown(report) {
  const chapterRows = report.chapters.length
    ? report.chapters.map(chapter => `- 第 ${chapter.chapterNum} 章：storyBlockId=${chapter.storyBlockId || 'missing'}，block_stage_snapshot=${chapter.block_stage_snapshot ? 'yes' : 'no'}`).join('\n')
    : '- 尚未生成章节'
  const checkRows = report.checks
    .map(check => `- ${check.pass ? 'PASS' : 'FAIL'} ${check.name}：${check.detail || ''}`)
    .join('\n')
  return `# Story Block Realistic Flow QA

- mode: ${report.mode}
- createdCleanProject: ${report.createdCleanProject}
- usesArchivedReports: ${report.usesArchivedReports}
- generatedAt: ${report.generatedAt}

## Chapters
${chapterRows}

## Checks
${checkRows}

## Acceptance
- passed: ${report.acceptance.passed}
- reason: ${report.acceptance.reason}
`
}

const report = liveMode ? await buildLiveReport() : buildDryRunReport()
mkdirSync(REPORT_DIR, { recursive: true })
writeFileSync(REPORT_JSON, JSON.stringify(report, null, 2), 'utf8')
writeFileSync(REPORT_MD, renderMarkdown(report), 'utf8')

console.log(`story block realistic flow report written: ${REPORT_JSON}`)
