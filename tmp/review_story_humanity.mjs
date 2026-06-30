import fs from 'node:fs'
import path from 'node:path'
import { normalizeStoryHumanityReview } from './story_humanity_review_utils.mjs'

const QA_DIR = path.join(process.cwd(), 'tmp', 'realistic-flow-qa')
const LIVE_REPORT_PATH = path.join(QA_DIR, 'latest-longform-browser-live-report.json')
const STATE_AUDIT_PATH = path.join(QA_DIR, 'latest-state-source-stability-audit.json')
const OUT_JSON = path.join(QA_DIR, 'latest-story-humanity-review.json')
const OUT_MD = path.join(QA_DIR, 'latest-story-humanity-review.md')

const liveReport = JSON.parse(fs.readFileSync(LIVE_REPORT_PATH, 'utf8'))
const stateAudit = fs.existsSync(STATE_AUDIT_PATH)
  ? JSON.parse(fs.readFileSync(STATE_AUDIT_PATH, 'utf8'))
  : null

const termGroups = {
  chase: ['追', '跑', '逃', '躲', '封街', '搜', '埋伏', '翻墙', '潜入', '暗道'],
  clue: ['账', '信', '钥匙', '印', '纸条', '手札', '抄本', '线索', '密栈', '档案'],
  cost: ['星账', '代价', '寿元', '黑纹', '疼', '痛', '记忆', '忘', '左臂', '血'],
  relation: ['老陈', '小九', '老太太', '父亲', '陆长庚', '灰衣人', '徐主簿', '徐正清', '阿福', '老九'],
  explanation: ['这意味着', '说明', '也就是说', '规则', '应该是', '如果', '只要', '必须', '意味着', '原因'],
}

function versionContent(chapterReport) {
  return (
    chapterReport.flowEvents?.finalize_version_preflight_passed?.versions?.[0]?.content ||
    chapterReport.flowEvents?.finalize_click_started?.versions?.[0]?.content ||
    ''
  )
}

function countTerms(text, terms) {
  return terms.reduce((sum, term) => sum + text.split(term).length - 1, 0)
}

const chapters = (liveReport.chapterReports || []).map((chapter) => {
  const content = versionContent(chapter)
  const counts = Object.fromEntries(
    Object.entries(termGroups).map(([key, terms]) => [key, countTerms(content, terms)]),
  )
  const paragraphs = content.split(/\n+/).map((item) => item.trim()).filter(Boolean)
  return {
    chapterNum: chapter.chapterNum,
    title: chapter.title,
    storyBlockId: chapter.storyBlockId,
    storyBlockTitle: chapter.blockStageSnapshot?.blockTitle || '',
    stagePurpose: chapter.blockStageSnapshot?.stagePurpose || '',
    wordCount: chapter.wordCount,
    paragraphs: paragraphs.length,
    dialogueApprox: Math.round((content.match(/“/g) || []).length / 2),
    counts,
  }
})

const totals = chapters.reduce(
  (acc, chapter) => {
    acc.wordCount += chapter.wordCount || 0
    acc.dialogueApprox += chapter.dialogueApprox
    for (const key of Object.keys(termGroups)) {
      acc.counts[key] += chapter.counts[key]
    }
    return acc
  },
  {
    wordCount: 0,
    dialogueApprox: 0,
    counts: Object.fromEntries(Object.keys(termGroups).map((key) => [key, 0])),
  },
)

const review = {
  createdAt: new Date().toISOString(),
  project: liveReport.project,
  sourceReports: {
    liveReport: path.relative(process.cwd(), LIVE_REPORT_PATH).replaceAll('\\', '/'),
    stateAudit: stateAudit ? path.relative(process.cwd(), STATE_AUDIT_PATH).replaceAll('\\', '/') : null,
  },
  scope: {
    chaptersReviewed: [1, 20],
    chapterCount: chapters.length,
    mode: 'readonly_story_humanity_review',
    didRun50Chapters: false,
    changedModelConfig: false,
    changedMainFlow: false,
    changedDraftPrompt: false,
  },
  overallVerdict: {
    shortAnswer: '第 1-20 章能看下去，但主要靠悬疑线索和追逃压力驱动；离“长篇黏住读者的人物故事”还有明显距离。',
    readabilityScore10: 6.2,
    followReadScore10: 6.0,
    humanityScore10: 4.8,
    reason:
      '开篇钩子有效，账本、父亲、巡天司和粮价黑账有类型小说吸引力；但 6-20 章反复进入“拿线索、被追、躲藏、解读、去下一地点”的循环，父亲和配角常被用作线索发放器，星账代价多表现为黑纹与疼痛，较少改变关系和选择。',
  },
  evidenceMetrics: {
    totals,
    chapters,
    notes: [
      '线索词和追逃词持续高密度，说明推进强，但玩法集中。',
      '关系词出现频率不低，但大量围绕父亲遗留物、旧部说明和线索解释，关系变化不足。',
      '解释性连接词在 10、18 章较集中，和读者阅读理解负担上升相吻合。',
    ],
  },
  dimensionReview: [
    {
      dimension: '人物血肉',
      score10: 5.2,
      finding:
        '陆沉舟有清晰外部目标：查父亲、查黑账、躲巡天司。但个人化动机还不够稳定，常从“儿子想知道真相”滑成“解谜执行者”。父亲线有右手旧疤、母亲授账、六岁猫头等亮点，却在中后段被钥匙、坐标、旧印、账本替代。老陈和老太太有动作记忆点，小九开始有嘴硬和照应，灰衣人、乙十七、徐主簿偏功能化。',
      representativeChapters: [1, 3, 5, 8, 13, 18, 20],
    },
    {
      dimension: '情绪层次',
      score10: 4.6,
      finding:
        '第 3、9、18、19 章有短暂喘息，但大多仍用于读信、拆线索、安排下一次潜入。追逃、疼痛、紧张很密，人和人的温度不够。星账代价有“母亲授账记忆被支取”的潜力，但后续没有持续改变陆沉舟的心理和关系。',
      representativeChapters: [3, 7, 9, 11, 18, 19],
    },
    {
      dimension: '对话自然度',
      score10: 5.0,
      finding:
        '有些对话短促好用，例如老陈的冷处理、小九的“饿/别嚼”、老太太的灶台动作。但大量对话仍是问答式设定交代：问地点、问钥匙、问规则、问父亲，回答直接给背景。角色间遮掩、误会、打岔、说半句的比例不足。',
      representativeChapters: [2, 5, 9, 14, 18],
    },
    {
      dimension: '场景循环',
      score10: 4.1,
      finding:
        '6-20 章循环明显：潜入/取得物证/暴露/逃跑/临时安全处解析/下一个地点。故事块“夜枭绕城”覆盖 10 章，虽然阶段推进多，但玩法相似。生活、市井、关系和静态压迫场景太少。',
      representativeChapters: [6, 7, 10, 11, 12, 16, 17, 20],
    },
    {
      dimension: '设定呈现',
      score10: 5.0,
      finding:
        '好处是设定多由物件和后果带出，如星灰、旧钥匙、档案、密栈。但中后段名词密度高，庚字、丙寅、甲肆、第三密栈、天池等连续叠加，常靠主角内心推导解释。读者需要记很多编码，不够低负担。',
      representativeChapters: [8, 12, 16, 18, 20],
    },
    {
      dimension: '长篇黏性',
      score10: 5.8,
      finding:
        '阶段目标清楚：查父亲名籍和粮价黑账，进入第三密栈。每 5 章有阶段答案，但答案经常马上引出更多名词和地点，读者能复述“陆沉舟一路查到徐主簿和第三密栈”，却较难复述人物关系发生了什么变化。',
      representativeChapters: [1, 5, 10, 15, 20],
    },
  ],
  chapterAssessments: [
    { chapter: 1, title: '不存在', assessment: '强开篇。父亲死而复现、主角名字被抹、粮铺黑账都清楚；右手旧疤让父亲有温度。风险是同章塞入追逃和粮账，信息量偏大。' },
    { chapter: 2, title: '分掉的是什么', assessment: '老陈与徐主簿交锋带推进，但对话承担了过多说明职责。星账代价第一次像规则说明，心理后果还浅。' },
    { chapter: 3, title: '表侄', assessment: '较好的人味章：烙饼、表侄、老陈旧话、母亲授账记忆被支取都有生活感。后半仍快速转回线索。' },
    { chapter: 4, title: '咔', assessment: '潜入账房有动作细节，目标明确；人物关系弱，主要服务粮价舞弊证据。' },
    { chapter: 5, title: '谢了', assessment: '父亲钥匙和猫头记忆有个人化亮点；但“别去/还是去”的选择没有形成足够人物冲突。' },
    { chapter: 6, title: '还有一件事——', assessment: '老宅探秘有效，但单章完成到达、取信、遇埋伏、撤退，关系和情绪沉淀不足。' },
    { chapter: 7, title: '留个记号就行', assessment: '徐主簿恶意明确，市井压迫可读；反派台词略直白，黑纹和追踪继续加强但情绪变化有限。' },
    { chapter: 8, title: '遁隐', assessment: '主角推理过长，读者需要跟“水缸/水闸/水涨”做阅读理解。老太太登场有味道，但主要功能仍是递规则和新地点。' },
    { chapter: 9, title: '进来吧', assessment: '老太太的灶台、醋、星灰处理很具体，是较好的行动后果式设定；但她对主角的情感立场仍不够清晰。' },
    { chapter: 10, title: '陈', assessment: '茶馆观察和西阁抄本推进强，代价升级明显；场景仍是观察、潜入、取物、被追。' },
    { chapter: 11, title: '翻墙出去了', assessment: '追逐和误导密集，父亲动作记忆有细节；但顺序混乱、碎布、钥匙、纸条叠加，阅读负担上升。' },
    { chapter: 12, title: '丙壹', assessment: '档案室查证给出硬答案：父亲甲肆、密牢、会客记录。好处是阶段答案清楚，问题是仍主要靠档案阅读。' },
    { chapter: 13, title: '主簿例行问话', assessment: '父亲假解法、灰衣人旧部是有效转折；灰衣人缺少自己的欲望和风险，只像递信人。' },
    { chapter: 14, title: '染坊巷七号', assessment: '老九有阻拦和旧事，适合发展关系；但实际仍围绕西阁信息说明，人物冲突很快让位于行动安排。' },
    { chapter: 15, title: '先进西阁', assessment: '小九的观察、老周的不可信带来人物判断；这是中段较好的“关系+线索”章，但结尾又回到下一地点。' },
    { chapter: 16, title: '走了', assessment: '旧印和第三密栈定位清楚，阶段功能完成；对话少、内心多，人物关系没有获得新层次。' },
    { chapter: 17, title: '别嚼', assessment: '小九的“饿/别嚼”自然，终于出现非功能性口气；可继续放大成搭档关系。' },
    { chapter: 18, title: '等等', assessment: '安全处读信本可做情绪喘息，但大量解释“信是给谁看的/哪块砖是饵”，对话又变成推理解说。' },
    { chapter: 19, title: '能走', assessment: '冷饼、腊肠、一顿酒是很好的关系温度；应把这类小动作常态化，并让小九有自己的代价。' },
    { chapter: 20, title: '哎呦', assessment: '第三密栈给出徐正清超额抽取和天池裂隙，阶段答案够大；但追逃开场、密室取物、再指向底层密室，循环疲劳仍在。' },
  ],
  prioritizedIssues: [
    {
      id: 'P0-1',
      severity: 'P0',
      title: '6-20 章形成高强度“拿线索 -> 被追 -> 躲藏 -> 解读 -> 下一地点”循环',
      chapters: [6, 7, 8, 10, 11, 12, 16, 17, 18, 20],
      typicalFragmentSummary:
        '老宅取信后撤离，城隍庙被迫转移；广源/西阁/档案室/密牢/第三密栈连续潜入；每次得到纸条、钥匙、抄本或旧印后，很快被追击或转向下一处。',
      whyItMatters:
        '短期紧张感足，但 20 章内玩法趋同，读者会记住“又去拿东西又被追”，而不是记住这一段关系或选择发生了什么变化。',
      recommendation:
        '故事块不只设“线索目标”，还设“关系任务”和“场景玩法”。例如第 21-25 章至少安排一次静态压迫、一次伤口/吃饭/分赃/吵架场，一次因隐瞒造成的信任变化，而不是连续潜入。'
    },
    {
      id: 'P0-2',
      severity: 'P0',
      title: '父亲线被谜题物件吞没，陆沉舟像解码器多过像儿子',
      chapters: [1, 3, 5, 8, 12, 13, 18, 20],
      typicalFragmentSummary:
        '前 5 章有右手疤、母亲遗物、六岁猫头等个人记忆；中后段父亲主要以手札、坐标、旧印、油纸、密栈账本和暗号出现。',
      whyItMatters:
        '父亲是主线情感发动机。如果父亲长期只产出线索，读者关心的是谜底而不是父子关系，主角的痛感会变成任务提示。',
      recommendation:
        '每个父亲线索都绑定一个情绪问题：他保护过我还是利用我？他为什么瞒我？我还想不想救他？让陆沉舟至少出现愤怒、嘴硬、误判或拒绝相信一次，而不只是把线索整理正确。'
    },
    {
      id: 'P0-3',
      severity: 'P0',
      title: '星账代价多停留在黑纹、疼痛和失忆提示，没有持续改变选择与关系',
      chapters: [3, 7, 8, 10, 11, 12, 16, 18, 20],
      typicalFragmentSummary:
        '母亲授账记忆被支取是强代价，但后续更多是黑纹扩散、左臂疼痛、身体麻木；主角仍持续高效推理和行动。',
      whyItMatters:
        '代价如果不改变行为，就会变成 UI 血条。读者会逐渐不信“很严重”，也不容易为主角的选择揪心。',
      recommendation:
        '把代价落到可见后果：忘记一句父亲旧话导致误判；疼痛让他必须向小九求助；他隐瞒失忆伤害信任；某次不用星账导致错过机会。代价要逼出选择，不只提示危险。'
    },
    {
      id: 'P0-4',
      severity: 'P0',
      title: '阶段答案给得有，但常被新名词和新谜题立刻覆盖',
      chapters: [5, 10, 12, 15, 18, 20],
      typicalFragmentSummary:
        '第 12 章确认父亲甲肆和密牢线，第 20 章确认徐正清超额抽取与天池裂隙；但同一串里又叠加丙寅、庚字号门、底层密室、庚虎、路线图。',
      whyItMatters:
        '读者需要阶段性“我懂了”。如果答案之后马上增加更多编码，爽感会被阅读负担抵消。',
      recommendation:
        '每 5 章安排一个“读者可复述答案场”：用人物行动证明一个答案，只留一个新问题。避免在答案章同时新增三个以上专名/机关。'
    },
    {
      id: 'P1-1',
      severity: 'P1',
      title: '配角有动作记忆点，但小目标和不可说之事不足',
      chapters: [2, 9, 13, 14, 17, 19],
      typicalFragmentSummary:
        '老陈递凉茶、藏账、说话短；老太太用醋化星灰；小九嘴硬但照顾人；灰衣人递信，乙十七让路，徐主簿压迫。',
      whyItMatters:
        '配角如果只有“帮主角拿下一把钥匙”的功能，就不容易被读者记住，也难形成长篇陪伴感。',
      recommendation:
        '给重要配角声音卡：说话习惯、不愿说出口的事、对主角态度、本阶段小目标。每次出场至少有一个动作来自他自己的利益或恐惧。'
    },
    {
      id: 'P1-2',
      severity: 'P1',
      title: '对话经常是问答式信息交代，遮掩、误会和废话偏少',
      chapters: [2, 5, 8, 14, 18],
      typicalFragmentSummary:
        '陆沉舟问星灰、钥匙、西阁、父亲旧事，对方直接解释；小九在第 17、19 章的插科和食物细节反而更自然。',
      whyItMatters:
        '人物越像答案接口，声音越趋同。真实对话常有不答、转移、半句、嘴硬和误会。',
      recommendation:
        '正文提示不列检查清单，只轻量强调：对话不要每问必答；角色可以避开关键点，用动作、打岔或误会泄露信息。'
    },
    {
      id: 'P1-3',
      severity: 'P1',
      title: '反派压迫有，但徐主簿台词偏直给，缺少官僚式危险',
      chapters: [2, 7, 20],
      typicalFragmentSummary:
        '徐主簿会直接暴露贪婪和轻贱底层，账本上也直接留下签名与核定。',
      whyItMatters:
        '反派主动讲坏事会削弱真实感。越是掌权者，越应通过程序、印章、沉默和替罪羊体现危险。',
      recommendation:
        '徐主簿少说“我坏”，多说“按例处置、账目无误、此人不在名籍”。让别人因他的程序受害，读者自然恨他。'
    },
    {
      id: 'P1-4',
      severity: 'P1',
      title: '喘息场存在，但经常被用成读信和推理会议',
      chapters: [3, 9, 14, 18, 19],
      typicalFragmentSummary:
        '伤口处理、躲屋、密室、仓库都可以喘息；实际常迅速转成解释星灰、旧印、信件和密栈。',
      whyItMatters:
        '读者需要紧张后的情绪回落，人物也需要在低压时暴露人性。否则节奏一直绷着，长篇会疲劳。',
      recommendation:
        '每 3-5 章设置一次关系场：处理伤口、吃东西、分赃、吵架、躲雨、临时合作。场景仍推进剧情，但核心变化是人物态度。'
    },
    {
      id: 'P2-1',
      severity: 'P2',
      title: '部分推理段解释词过密，读者阅读负担上升',
      chapters: [8, 10, 16, 18, 20],
      typicalFragmentSummary:
        '“这意味着 / 也就是说 / 应该是 / 必须”等连接在推理解码段集中出现，尤其是水缸水闸、第三密栈、信件真假和庚字号门。',
      whyItMatters:
        '类型小说需要清楚，但连续解释会让读者像做题，爽点被拆成说明书。',
      recommendation:
        '把设定说明改成行动后果：试一下、出事、别人反应、主角总结一句。内心推理保留关键一步，不把所有中间过程写满。'
    },
    {
      id: 'P2-2',
      severity: 'P2',
      title: '章尾钩子可用但偏密，停顿点不够多样',
      chapters: [4, 5, 8, 14, 15, 17, 20],
      typicalFragmentSummary:
        '“别去”“猫头”“进来”“只有一刻钟”“下一站”“地下第十三阶”“底层密室”等结尾连续推下一钩。',
      whyItMatters:
        '强钩子能促读，但长期只靠外部钩子，人物状态和阶段满足感不足。',
      recommendation:
        '部分章节以关系变化或代价落地收束，例如“他没有告诉小九自己忘了什么”“老陈第一次承认欠陆家一条命”。'
    },
    {
      id: 'P2-3',
      severity: 'P2',
      title: '编码类名词过多，容易让读者混淆',
      chapters: [12, 16, 18, 20],
      typicalFragmentSummary:
        '甲肆、乙十七、丙壹、丙寅、庚字、庚字号门、第三密栈、庚虎等连续出现。',
      whyItMatters:
        '编码有悬疑味，但过密会让读者记忆成本超过剧情收益。',
      recommendation:
        '每章只让一个编码承担关键功能，其余用普通话复述，例如“那扇要三件东西才能开的门”。'
    },
  ],
  storyHumanityV1Plan: {
    principle: '创作机制优先，不新增大量 hard gate，不把正文 prompt 改成 QA 清单。',
    mechanisms: [
      {
        name: '故事块增加人物关系任务',
        description:
          '每个故事块除了线索目标，还记录一个必须发生变化的人物关系：误会、信任、亏欠、交易、背叛、救助或隐瞒。',
        suggestedFields: ['relationshipFocus', 'relationshipStart', 'relationshipTask', 'relationshipEnd', 'relationshipCost'],
      },
      {
        name: '小纲增加情绪锚点',
        description:
          '小纲阶段规划时轻量记录本章主角最在意什么、失去/确认/误解了什么、哪段关系发生轻微变化。字段只帮助规划，不作为正文硬检查。',
        suggestedFields: ['protagonistImmediateWant', 'emotionalAnchor', 'misbeliefOrFear', 'relationshipDelta', 'stageAnswerForReader'],
      },
      {
        name: '正文 prompt 降低文学化，强调真实反应',
        description:
          '正文提示保留短小正向引导：大白话、可视动作、真实反应、对话有遮掩和停顿。避免复杂比喻解释情绪，避免把审稿 rubric 塞进正文。',
      },
      {
        name: '设定呈现改为行动后果优先',
        description:
          '把规则说明改成“人物尝试 -> 出事 -> 付代价 -> 别人反应 -> 主角只总结一点点”。星账、星灰、密栈机关都按这个顺序呈现。',
      },
      {
        name: '每 3-5 章安排一次喘息/关系场',
        description:
          '不是水文，而是处理伤口、分赃/交易、吵架、吃饭、躲雨、临时合作、小人物闲话透露世界。场景目标是让人物态度改变。',
      },
      {
        name: '配角声音卡',
        description:
          '给老陈、小九、老太太、灰衣人、徐主簿、乙十七等记录说话习惯、不愿说出口的事、对主角态度和本阶段小目标，进入上下文时短量注入。',
      },
    ],
    chapter21To25ValidationShape: [
      '第 21-25 章只跑 5 章，不跑 50 章。',
      '至少一个章节以关系变化收束，而不是新地点钩子。',
      '至少一个线索通过小人物闲话、交易或误会呈现，而不是文书/密信直给。',
      '至少一次星账代价影响选择或关系，而不只是疼痛/黑纹提示。',
      '第 25 章给出一个读者能复述的阶段答案，只保留一个主要新问题。',
    ],
  },
  candidateFileImpact: [
    {
      file: 'frontend/src/prompts/storyBlockPrompt.js',
      possibleChange: '故事块规划中加入可选人物关系任务和场景玩法字段。',
      risk: '低到中。影响故事块输出结构，需要保持向后兼容，不能阻断已有块。',
    },
    {
      file: 'frontend/src/prompts/chapter.js',
      possibleChange: '如该文件承接章节规划上下文，可加入情绪锚点的轻量说明。',
      risk: '低。仅建议字段进入规划，不作为 hard gate。',
    },
    {
      file: 'frontend/src/prompts/chapterDraftPrompt.js',
      possibleChange: '正文提示增加简短创作取向：大白话、动作反应、对话遮掩、少解释。',
      risk: '中。必须避免变成检查清单，避免挤压正文创作空间。',
    },
    {
      file: 'frontend/src/utils/contextBuilder.js',
      possibleChange: '短量注入配角声音卡和最近情绪锚点；避免把完整人物档案塞入正文上下文。',
      risk: '中。要控制上下文长度和事实来源优先级。',
    },
    {
      file: 'tmp/review_story_humanity.mjs',
      possibleChange: '本轮新增，只读生成故事性与人物血肉诊断报告。',
      risk: '低。只读输入报告并写 QA 产物，不进入主链路。',
    },
  ],
  nextRoundVerification: {
    beforeChange: [
      '保留本报告作为第 1-20 章基线。',
      '不改模型配置，不跑 50 章。',
    ],
    afterSmallChange: [
      '只跑第 21-25 章五章。',
      '对比是否仍是连续追逃循环。',
      '检查每章是否有清晰人物情绪锚点。',
      '检查配角是否有非功能性对话或动作。',
      '检查设定说明句是否下降，尤其是“这意味着/也就是说/应该是”。',
      '检查第 25 章是否给出阶段性答案。',
      '人工复述测试：读者是否能用三句话复述 21-25 章发生了什么和谁的关系变了。',
    ],
    commandsThisRound: [
      'node --check tmp/review_story_humanity.mjs',
      'node tmp/review_story_humanity.mjs',
    ],
    frontendBuildRequired: false,
  },
}

function markdownTable(headers, rows) {
  return [
    `|${headers.join('|')}|`,
    `|${headers.map(() => '---').join('|')}|`,
    ...rows.map((row) => `|${row.join('|')}|`),
  ].join('\n')
}

function mdEscape(value) {
  return String(value ?? '').replaceAll('|', '｜').replace(/\n+/g, ' ')
}

function renderMarkdown(data) {
  const issueRows = data.prioritizedIssues.map((issue) => [
    issue.severity,
    issue.title,
    issue.chapters.join('、'),
    mdEscape(issue.typicalFragmentSummary),
    mdEscape(issue.whyItMatters),
    mdEscape(issue.recommendation),
  ])

  const dimensionRows = data.dimensionReview.map((item) => [
    item.dimension,
    item.score10,
    mdEscape(item.finding),
    item.representativeChapters.join('、'),
  ])

  const chapterRows = data.chapterAssessments.map((item) => [
    item.chapter,
    item.title,
    mdEscape(item.assessment),
  ])

  const metricsRows = data.evidenceMetrics.chapters.map((chapter) => [
    chapter.chapterNum,
    chapter.title,
    chapter.stagePurpose,
    chapter.wordCount,
    chapter.dialogueApprox,
    chapter.counts.chase,
    chapter.counts.clue,
    chapter.counts.cost,
    chapter.counts.relation,
    chapter.counts.explanation,
  ])

  return `# 故事性与人物血肉质量诊断 v1

- 项目：${data.project?.name || ''} (${data.project?.id || ''})
- 范围：第 ${data.scope.chaptersReviewed[0]}-${data.scope.chaptersReviewed[1]} 章
- 模式：只读诊断 + 小范围方案设计
- 未跑 50 章：${data.scope.didRun50Chapters ? '否' : '是'}
- 未改模型配置 / 主流程 / 正文 prompt：是

## 结论

${data.overallVerdict.shortAnswer}

- 可读性：${data.overallVerdict.readabilityScore10}/10
- 追读动力：${data.overallVerdict.followReadScore10}/10
- 人物血肉：${data.overallVerdict.humanityScore10}/10

${data.overallVerdict.reason}

## 证据概览

${data.evidenceMetrics.notes.map((note) => `- ${note}`).join('\n')}

总词数约 ${data.evidenceMetrics.totals.wordCount}；对话组约 ${data.evidenceMetrics.totals.dialogueApprox}；追逃词 ${data.evidenceMetrics.totals.counts.chase}；线索词 ${data.evidenceMetrics.totals.counts.clue}；代价词 ${data.evidenceMetrics.totals.counts.cost}；关系词 ${data.evidenceMetrics.totals.counts.relation}；解释连接词 ${data.evidenceMetrics.totals.counts.explanation}。

${markdownTable(['章', '标题', '阶段功能', '字数', '对话', '追逃', '线索', '代价', '关系', '解释'], metricsRows)}

## 分维度诊断

${markdownTable(['维度', '评分', '判断', '代表章节'], dimensionRows)}

## 章节简评

${markdownTable(['章', '标题', '简评'], chapterRows)}

## 问题排序

${markdownTable(['级别', '问题', '章节', '典型片段摘要', '为什么影响阅读', '建议怎么改'], issueRows)}

## 故事性与人物血肉 v1 改造方案

原则：${data.storyHumanityV1Plan.principle}

${data.storyHumanityV1Plan.mechanisms.map((item, index) => {
  const fields = item.suggestedFields ? `\n  - 建议字段：${item.suggestedFields.join(' / ')}` : ''
  return `${index + 1}. ${item.name}\n  - ${item.description}${fields}`
}).join('\n\n')}

## 候选影响面

${data.candidateFileImpact.map((item) => `- ${item.file}：${item.possibleChange} 风险：${item.risk}`).join('\n')}

本轮不直接修改上述主链路文件；只新增只读报告脚本和报告产物。

## 下一轮验证

修改前：
${data.nextRoundVerification.beforeChange.map((item) => `- ${item}`).join('\n')}

小改后：
${data.nextRoundVerification.afterSmallChange.map((item) => `- ${item}`).join('\n')}

本轮验证命令：
${data.nextRoundVerification.commandsThisRound.map((item) => `- \`${item}\``).join('\n')}

前端构建：${data.nextRoundVerification.frontendBuildRequired ? '需要' : '不需要，本轮未改前端代码'}。
`
}

const normalizedReview = normalizeStoryHumanityReview(review)

fs.writeFileSync(OUT_JSON, `${JSON.stringify(normalizedReview, null, 2)}\n`, 'utf8')
fs.writeFileSync(OUT_MD, renderMarkdown(normalizedReview), 'utf8')

console.log(`Wrote ${path.relative(process.cwd(), OUT_JSON)}`)
console.log(`Wrote ${path.relative(process.cwd(), OUT_MD)}`)
