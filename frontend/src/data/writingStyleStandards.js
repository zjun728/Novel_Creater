export const WRITING_STYLE_STANDARDS = [
  {
    id: 'realism-ensemble',
    name: '现实主义群像',
    category: '现实 / 群像',
    shortRule: '以人物处境、社会压力和日常细节推动剧情；避免单一主角爽点碾压，让每个关键角色都有自己的利益、难处和选择代价。',
    auditFocus: ['配角是否工具化', '冲突是否来自真实处境', '细节是否有生活质感', '结尾是否避免模板化总结']
  },
  {
    id: 'historical-court',
    name: '历史正剧 / 庙堂',
    category: '历史 / 权谋',
    shortRule: '以制度、信息差、立场和代价构成张力；人物说话要有身份边界，权谋推进应靠证据、误判和政治后果，而不是反派自曝。',
    auditFocus: ['制度逻辑是否自洽', '权谋是否靠信息倾倒', '人物口吻是否符合身份', '历史名词是否滥用']
  },
  {
    id: 'fanren-cultivation',
    name: '凡人流 / 慢热修仙',
    category: '修仙 / 成长',
    shortRule: '主角成长要靠谨慎选择、资源计算和风险承受；升级必须有代价、瓶颈和后果，不要用外挂连续跳级削弱沉浸感。',
    auditFocus: ['资源与等级是否前后一致', '胜负是否有铺垫', '风险是否真实存在', '章节是否过度解释体系']
  },
  {
    id: 'epic-upgrade-fantasy',
    name: '玄幻热血 / 史诗升级',
    category: '玄幻 / 爽文',
    shortRule: '以明确目标、强压迫、升级反馈和阶段爽点驱动阅读；爽点必须来自冲突积累后的释放，不能只靠数值膨胀。',
    auditFocus: ['爽点是否有压迫铺垫', '升级是否有代价', '敌我强弱是否清楚', '结尾钩子是否重复']
  },
  {
    id: 'xianxia-destiny',
    name: '仙侠宿命 / 情绪爆发',
    category: '仙侠 / 宿命',
    shortRule: '以情义、因果、命运选择和牺牲构成章节核心；情绪爆发前必须有克制、误解、残留和不可回避的选择。',
    auditFocus: ['情绪是否像开关', '宿命是否有因果铺垫', '牺牲是否服务人物', '意象是否套话化']
  },
  {
    id: 'light-comedy-contrast',
    name: '轻喜剧 / 反差网感',
    category: '都市 / 喜剧',
    shortRule: '喜剧来自人物误读、身份错位和节奏反差；每个笑点最好同时承担推进、埋梗或暴露关系，杜绝纯段子水文。',
    auditFocus: ['笑点是否推动剧情', '网感是否油腻', '反差是否重复', '严肃线是否被消解']
  },
  {
    id: 'suspense-hook',
    name: '悬疑解谜 / 强钩子',
    category: '悬疑 / 解谜',
    shortRule: '以问题、证据、误导、验证和新问题形成章节链条；关键答案应通过行动和细节揭示，不靠长篇解释。',
    auditFocus: ['线索是否公平', '误导是否合理', '信息是否倾倒', '章尾问题是否有效递进']
  },
  {
    id: 'rational-fantasy',
    name: '知识体系 / 理性奇幻',
    category: '知识 / 奇幻',
    shortRule: '把知识、考据、规则或技术变成行动能力；读者应看到主角如何判断、验证和付出代价，而不是只听解释。',
    auditFocus: ['知识是否参与行动', '术语是否过密', '推理链是否跳跃', '胜负是否靠临时设定']
  },
  {
    id: 'folk-eerie',
    name: '民俗志怪 / 中式诡异',
    category: '民俗 / 志怪',
    shortRule: '以民俗禁忌、地方细节、口耳相传和现实裂缝制造诡异；恐怖感要从生活物件变形中来，不靠堆血腥。',
    auditFocus: ['民俗是否具体', '诡异是否有日常根基', '解释是否过早', '氛围是否只有黑暗沉默']
  },
  {
    id: 'rule-survival',
    name: '规则怪谈 / 无限流 / 生存博弈',
    category: '规则 / 生存',
    shortRule: '规则必须清楚、可验证、可误判；章节推进要靠选择压力和代价，不要靠随机惩罚或作者临时加规则。',
    auditFocus: ['规则是否可执行', '违规后果是否一致', '博弈是否有选择空间', '新规则是否突兀']
  },
  {
    id: 'urban-supernatural',
    name: '都市异能 / 灵气复苏 / 幕后组织',
    category: '都市 / 异能',
    shortRule: '把异常放进现代生活秩序中，让机构、媒体、家庭和工作产生真实反应；异能升级不能脱离社会后果。',
    auditFocus: ['现代秩序是否缺席', '组织行动是否合理', '能力使用是否有代价', '日常与异常是否割裂']
  },
  {
    id: 'female-growth',
    name: '女频成长 / 古言现言 / 逆袭',
    category: '女频 / 成长',
    shortRule: '以关系压力、自我选择和长期成长构成爽点；逆袭不是单纯打脸，而是让角色在资源、认知和情感边界上变强。',
    auditFocus: ['成长是否靠选择', '情感关系是否工具化', '爽点是否只有打脸', '女性角色是否脸谱化']
  },
  {
    id: 'short-drama-reversal',
    name: '短剧爽文 / 强冲突反转',
    category: '短剧 / 强钩子',
    shortRule: '每章要有清晰冲突、快速误会、强反馈和小反转；反转必须服务主线，不要为了刺激牺牲人物逻辑。',
    auditFocus: ['冲突是否快速可见', '反转是否硬拧', '信息是否重复喊口号', '人物行为是否失真']
  },
  {
    id: 'business-healing',
    name: '经营种田 / 美食生活 / 治愈',
    category: '经营 / 治愈',
    shortRule: '用具体经营动作、物品细节和关系变化提供满足感；慢节奏也要有小目标、小反馈和可持续问题。',
    auditFocus: ['经营动作是否具体', '治愈是否空泛', '目标反馈是否明确', '日常细节是否重复']
  }
]

const STANDARD_BY_ID = Object.fromEntries(WRITING_STYLE_STANDARDS.map(item => [item.id, item]))

const WRITING_GUIDANCE_BY_ID = {
  'realism-ensemble': {
    chapterEngine: '用处境压力、关系变化和现实后果推动章节，不把事件写成单人闯关。',
    characterMethod: '关键角色都带着自己的利益、难处、习惯和小目标进入场景。',
    informationMethod: '信息从生活细节、制度反应、旁人误判和具体后果里露出。',
    proseRhythm: '语言平实克制，长短句自然交替，少用抽象总结收束情绪。',
    endingPreference: '结尾落在关系变化、现实代价或未说出口的选择上。',
    avoid: '避免所有配角只为主角递线索、递情绪或递爽点。'
  },
  'historical-court': {
    chapterEngine: '用制度约束、信息差、立场冲突和政治后果构成章节张力。',
    characterMethod: '人物说话和行动要带身份边界，权力越高越少直白自曝。',
    informationMethod: '证据、文书、礼法、传闻和误判逐层改变局势。',
    proseRhythm: '叙述稳重，少口号，多暗潮；对话留余地，不把权谋讲成说明书。',
    endingPreference: '结尾落在新证据、新立场、新后果或被迫站队上。',
    avoid: '避免反派长篇解释计划，避免用现代口吻替代身份逻辑。'
  },
  'fanren-cultivation': {
    chapterEngine: '用资源计算、风险选择、瓶颈试探和代价承受推动成长。',
    characterMethod: '主角谨慎、会权衡，不轻易相信天降好处；敌友都按利益行动。',
    informationMethod: '修炼规则通过失败、试错、消耗、旁人经验和器物反应展示。',
    proseRhythm: '叙述沉稳，动作和心理都要有因果；不要连续跳级式推进。',
    endingPreference: '结尾落在新风险、新资源缺口、旧债或修炼后遗症上。',
    avoid: '避免外挂连续解决问题，避免升级没有消耗、瓶颈和后果。'
  },
  'epic-upgrade-fantasy': {
    chapterEngine: '用明确目标、强压迫、阶段反馈和冲突释放形成阅读推进。',
    characterMethod: '主角可以强，但强来自积累和选择；对手要有压迫理由。',
    informationMethod: '力量体系通过战斗限制、资源代价、旁观反应和失败边界呈现。',
    proseRhythm: '节奏有推力，但爽点前要有压力蓄积，不能只堆数值。',
    endingPreference: '结尾落在更强阻力、新等级门槛或胜利后代价上。',
    avoid: '避免每章都用同一种震惊、碾压、抬头或握拳结尾。'
  },
  'xianxia-destiny': {
    chapterEngine: '用情义、因果、误解、牺牲和不可回避的选择推动章节。',
    characterMethod: '人物情绪先克制再破裂，选择背后要有旧债、旧诺或旧伤。',
    informationMethod: '宿命和因果通过旧物、誓言、残留、梦境和行动后果慢慢显影。',
    proseRhythm: '语言可有意象，但要落到人物身体和关系，不要空泛抒情。',
    endingPreference: '结尾落在誓言、代价、未完成的告别或命运反扑上。',
    avoid: '避免情绪像开关一样突然爆发，避免牺牲只为煽情。'
  },
  'light-comedy-contrast': {
    chapterEngine: '用身份错位、误读、吐槽节奏和真实压力并行推进。',
    characterMethod: '角色可以好笑，但不能只负责抛梗；每个笑点最好暴露关系或信息。',
    informationMethod: '严肃线藏在玩笑、误读、群聊细节和反差后果里。',
    proseRhythm: '对话快，叙述稳；网感要轻，不要让梗淹没场景。',
    endingPreference: '结尾可用轻微反差、误会升级或严肃信息突然露头。',
    avoid: '避免纯段子水文，避免严肃危机被玩笑完全消解。'
  },
  'suspense-hook': {
    chapterEngine: '用问题、证据、误导、验证和新问题形成章节链条。',
    characterMethod: '人物根据各自知道的信息误判，不要让角色为解释设定而说话。',
    informationMethod: '答案从行动、细节和可回看线索里出现，保持公平误导。',
    proseRhythm: '叙述克制，关键证据具体；不要把所有推理一次讲透。',
    endingPreference: '结尾留下更具体的新问题、反证或被误读的证据。',
    avoid: '避免靠长篇口述揭谜，避免章尾问题只换名字不升级。'
  },
  'rational-fantasy': {
    chapterEngine: '让知识、考据、规则或技术直接改变行动方案和胜负边界。',
    characterMethod: '主角要观察、验证、修正判断，并为判断失误付出代价。',
    informationMethod: '术语必须落在证据、物件反应、实验失败或推理动作里。',
    proseRhythm: '推理段和场景段交替，不要连续堆概念；保留读者自己拼合的空间。',
    endingPreference: '结尾落在一个新证据、新反例或刚被推翻的旧判断上。',
    avoid: '避免知识只作为说明书存在，避免胜负靠临时补设定。'
  },
  'folk-eerie': {
    chapterEngine: '用地方细节、禁忌、传闻和日常物件的轻微变形制造诡异。',
    characterMethod: '人物先按现实经验解释异常，直到解释逐渐失效。',
    informationMethod: '真相从口耳相传、旧物痕迹、地方规矩和反常习惯中渗出。',
    proseRhythm: '语气压低，细节要有湿度、气味和触感，少用空泛黑暗沉默。',
    endingPreference: '结尾落在一个日常物件变得不对、旧规矩被验证或被误解上。',
    avoid: '避免单纯堆血腥和惊吓，避免过早解释诡异来源。'
  },
  'rule-survival': {
    chapterEngine: '规则要可验证、可误判，章节推进靠选择压力和违规代价。',
    characterMethod: '人物在有限信息下试探边界，聪明人也会因为代价和恐惧犯错。',
    informationMethod: '新规则来自观察、失败案例、反证和环境变化，不临时加罚。',
    proseRhythm: '叙述清楚，压力递增；规则文本短而可执行。',
    endingPreference: '结尾落在规则边界被改写、代价到账或新选择出现上。',
    avoid: '避免随机惩罚，避免规则只服务作者想要的反转。'
  },
  'urban-supernatural': {
    chapterEngine: '把异常放进现代生活秩序，让机构、家庭、媒体和工作产生反应。',
    characterMethod: '人物既受超自然牵引，也被现实身份、职业和关系限制。',
    informationMethod: '异常通过监控、报告、谣言、新闻、病例或组织行动露出。',
    proseRhythm: '现实段要有烟火气，异常段要保留秩序崩开的裂缝。',
    endingPreference: '结尾落在异常影响现实秩序，或现实反过来逼迫主角选择。',
    avoid: '避免超能力脱离社会后果，避免组织像背景板一样只发任务。'
  },
  'female-growth': {
    chapterEngine: '用关系压力、自我选择、资源重组和长期成长推进爽点。',
    characterMethod: '主角变强来自认知、边界、资源和情感判断的升级。',
    informationMethod: '关系变化通过对话细节、旧账、新选择和利益交换呈现。',
    proseRhythm: '情绪细腻但不拖沓，爽点应有压抑后的释放和余波。',
    endingPreference: '结尾落在边界重划、关系反转或主角主动选择上。',
    avoid: '避免逆袭只靠打脸，避免女性角色脸谱化或互害工具化。'
  },
  'short-drama-reversal': {
    chapterEngine: '每章保持清晰冲突、快速误会、强反馈和小反转。',
    characterMethod: '人物可以外放，但动机要能被理解，不为反转牺牲逻辑。',
    informationMethod: '关键信息短促抛出，马上造成局势变化。',
    proseRhythm: '节奏快，场景短，反馈明确，但不要每段都喊口号。',
    endingPreference: '结尾落在身份揭示、误会升级或下一轮强冲突入口。',
    avoid: '避免为了刺激让人物行为失真，避免同一反转连续复用。'
  },
  'business-healing': {
    chapterEngine: '用具体经营动作、物品细节、关系变化和小反馈推进。',
    characterMethod: '人物的疲惫、善意、算计和成长都要落在日常动作里。',
    informationMethod: '经营成果通过成本、客人反应、物品变化和关系修复呈现。',
    proseRhythm: '节奏舒缓但有小目标，描写要具体，不空喊治愈。',
    endingPreference: '结尾落在一个小成果、一段关系松动或新的经营难题上。',
    avoid: '避免日常重复同一流程，避免治愈只靠温柔形容词。'
  }
}

export function getWritingStyleStandard(id) {
  return STANDARD_BY_ID[String(id || '').trim()] || null
}

function getWritingGuidance(standard) {
  return WRITING_GUIDANCE_BY_ID[standard.id] || {
    chapterEngine: standard.shortRule,
    characterMethod: '让人物带着自身欲望、压力和误判进入场景。',
    informationMethod: '把信息放进行动、证据、关系变化和具体后果里。',
    proseRhythm: '保持自然叙述节奏，避免把标准写成逐条打卡。',
    endingPreference: '结尾落在具体变化或下一章可承接的问题上。',
    avoid: '避免机械套用题材标签。'
  }
}

function parseMaybeJson(value) {
  if (typeof value !== 'string') return value
  const text = value.trim()
  if (!text) return {}
  if (!/^[{[]/.test(text)) return value
  try {
    return JSON.parse(text)
  } catch {
    return value
  }
}

export function normalizeWritingProfile(value = {}) {
  const parsed = parseMaybeJson(value)
  let config = parsed

  if (Array.isArray(config)) {
    const ids = config
      .map(item => typeof item === 'string' ? item : item?.id || item?.value)
      .map(id => String(id || '').trim())
      .filter(id => getWritingStyleStandard(id))
    config = { primaryStandard: ids[0] || '', secondaryFlavor: ids[1] || '' }
  }

  if (typeof config === 'string') {
    const id = String(config).trim()
    config = getWritingStyleStandard(id) ? { primaryStandard: id, secondaryFlavor: '' } : {}
  }

  const primaryStandard = getWritingStyleStandard(config?.primaryStandard) ? String(config.primaryStandard).trim() : ''
  const secondaryFlavor = getWritingStyleStandard(config?.secondaryFlavor) ? String(config.secondaryFlavor).trim() : ''

  return {
    primaryStandard,
    secondaryFlavor: secondaryFlavor && secondaryFlavor !== primaryStandard ? secondaryFlavor : '',
    customStyleNotes: typeof config?.customStyleNotes === 'string' ? config.customStyleNotes.trim() : ''
  }
}

export function getSelectedWritingStyleStandards(config = {}) {
  const normalized = normalizeWritingProfile(config)
  return [
    normalized.primaryStandard ? { role: '主写作标准', standard: getWritingStyleStandard(normalized.primaryStandard) } : null,
    normalized.secondaryFlavor ? { role: '辅助风味', standard: getWritingStyleStandard(normalized.secondaryFlavor) } : null
  ].filter(item => item?.standard)
}

export function formatWritingStyleStandardsForPrompt(config = {}) {
  const selected = getSelectedWritingStyleStandards(config)
  const profile = normalizeWritingProfile(config)
  const blocks = selected.map(({ role, standard }) => {
    const guidance = getWritingGuidance(standard)
    const isPrimary = role === '主写作标准'
    return [
      `### ${role}：${standard.name}`,
      `适用：${standard.category}`,
      isPrimary
        ? '定位：作为本项目章节组织、人物方法和叙事气质的主轴。'
        : '定位：只提供局部风味和场景纹理，不改变主写作标准、人物逻辑和剧情方向。',
      `章节组织：${guidance.chapterEngine}`,
      `人物方法：${guidance.characterMethod}`,
      `信息释放：${guidance.informationMethod}`,
      `语言节奏：${guidance.proseRhythm}`,
      `结尾倾向：${guidance.endingPreference}`,
      `避免：${guidance.avoid}`
    ].join('\n')
  })

  if (profile.customStyleNotes) {
    blocks.push(`### 项目风格备注\n${profile.customStyleNotes}`)
  }

  if (!blocks.length) return ''

  return blocks.join('\n\n')
}
