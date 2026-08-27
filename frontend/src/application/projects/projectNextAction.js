const COPY = Object.freeze({
  select_seed: ['CREATIVE SEED', '选择创作种子', '从候选种子中明确本项目唯一的当前创作方向。'],
  continue_contract: ['CREATION CONTRACT', '继续创作契约', '完成故事发动机、风格、经验与篇幅边界，并由作者确认。'],
  continue_bible: ['CREATION BIBLE', '继续创作圣经', '补全未来设计；手工建立与确认不依赖可用模型。'],
  recover_planning_operation: ['STORY PLANNING', '核对规划生成结果', '沿用原操作标识读取权威结果，不会重复发起一次 AI 生成。'],
  establish_planning: ['STORY PLANNING', '开始故事规划', '从空白工作稿建立分卷与情节线，再逐步形成可执行的完整规划。'],
  continue_planning: ['STORY PLANNING', '继续故事规划', '建立分卷、情节线与滚动故事块，让后续章节有方向也有调整余地。'],
  recover_chapter_outline_operation: ['CHAPTER OUTLINE', '核对第 {n} 章小纲生成结果', '读取本章小纲生成操作的权威结果，不会重复发起生成。'],
  prepare_chapter_outline: ['CHAPTER OUTLINE', '准备第 {n} 章小纲', '基于当前规划、Canon 与 Projection 建立本章的写作边界。'],
  continue_chapter_outline: ['CHAPTER OUTLINE', '继续第 {n} 章小纲', '完善当前章节小纲并确认，随后即可进入正文工作台。'],
  start_chapter_session: ['WRITER', '进入第 {n} 章写作', '使用已确认的小纲与固定权威基线创建章节工作会话。'],
  continue_writing: ['WRITER', '继续创作第 {n} 章', '回到已有章节工作会话，继续编辑工作稿与候选稿。'],
})
const CHAPTER_ACTIONS = new Set([
  'recover_chapter_outline_operation', 'prepare_chapter_outline',
  'continue_chapter_outline', 'start_chapter_session', 'continue_writing',
])

function safeTargetPath(value) {
  return typeof value === 'string'
    && /^\/(?!\/)/u.test(value)
    && !/[\\\u0000-\u001f\u007f]/u.test(value)
}

export function mapProjectNextAction(preparation) {
  if (preparation?.lifecycle === 'archived') return Object.freeze({ state: 'archived' })
  const nextAction = preparation?.nextAction
  const copy = COPY[nextAction]
  if (preparation?.lifecycle !== 'active' || !copy || !safeTargetPath(preparation?.targetPath)) {
    return Object.freeze({ state: 'unavailable', label: '重新读取创作状态' })
  }
  const chapterNumber = preparation.authoritativeChapterNumber
  if (CHAPTER_ACTIONS.has(nextAction) && (!Number.isInteger(chapterNumber) || chapterNumber <= 0)) {
    return Object.freeze({ state: 'unavailable', label: '重新读取创作状态' })
  }
  const number = CHAPTER_ACTIONS.has(nextAction) ? chapterNumber : null
  return Object.freeze({
    state: 'available', eyebrow: copy[0], label: copy[1].replace('{n}', String(number ?? '')),
    description: copy[2], targetPath: preparation.targetPath, chapterNumber: number,
  })
}
