export const AI_TRACE_RULES = [
  {
    id: 'template_ending',
    label: '模板化章节结尾',
    issueType: 'template_ending',
    generationGuidance: '章节结尾要来自本章具体动作、关系变化、物件状态或未解决问题，避免每章都用转身、闭眼、走进黑暗、状态总结收束。',
    auditSignal: '连续出现动作+抽象状态+意象收束，或每章末尾都像固定结束模板。',
    falsePositive: '冷峻、短促或留白式结尾可以成立，前提是它来自本章独有处境。',
    repairStrategy: '改成具体余波、物件变化、关系落点或下一章可承接的真实动作。'
  },
  {
    id: 'surface_emotion',
    label: '表层情绪',
    issueType: 'surface_emotion',
    generationGuidance: '人物情绪变化不要写成开关，要有迟疑、残留习惯、反复、自我辩解或身体余波。',
    auditSignal: '角色突然失去/获得某种情感，只有结论，没有过程。',
    falsePositive: '强刺激下的瞬间反应可以很快，但后续必须留下余波。',
    repairStrategy: '补一处落空的习惯动作、迟到的疼、没说出口的话或错误反应。'
  },
  {
    id: 'tool_character',
    label: '工具人配角',
    issueType: 'tool_character',
    generationGuidance: '关键配角至少要有自己的小目标、顾虑、习惯或利益，不只负责送信息、送道具或制造障碍。',
    auditSignal: '配角只有功能，没有个人欲望、顾虑、误判或选择。',
    falsePositive: '极短过场角色可以功能化，但反复出现或承担转折的角色不能只有工具属性。',
    repairStrategy: '给配角补一个和主角目标不完全一致的小算盘、迟疑、遮掩或生活细节。'
  },
  {
    id: 'info_dump',
    label: '信息倾倒',
    issueType: 'info_dump',
    generationGuidance: '信息尽量被发现：证据、误判、行动失败、物件反应、关系变化，比长篇解释更优先。',
    auditSignal: '反派、老人、系统、导师、会议或旁白主动长篇交底。',
    falsePositive: '必要解释可以存在，但应被冲突、代价、遮掩或证据链打断。',
    repairStrategy: '把解释拆成可观察证据、错误推断、行动后果和人物遮掩。'
  },
  {
    id: 'cliche_imagery',
    label: '套话意象',
    issueType: 'cliche_imagery',
    generationGuidance: '意象来自角色职业、处境、身体状态和场景物，而不是通用的月光、影子、黑暗、风和孤独。',
    auditSignal: '通用意象反复出现，却没有角色视角里的独特观察。',
    falsePositive: '常见意象可以用，但必须被本书世界观或角色经验重新染色。',
    repairStrategy: '替换成角色此刻会注意到的具体物、声音、触感、旧习惯或误读。'
  },
  {
    id: 'sensory_checklist',
    label: '感官打勾',
    issueType: 'sensory_checklist',
    generationGuidance: '每场重点写一两种最敏感的感官，不要平均罗列视听嗅触味。',
    auditSignal: '五感均匀覆盖，每种只写一层，像完成清单。',
    falsePositive: '特殊场景可以多感官，但必须有主感官和行动后果。',
    repairStrategy: '保留最能推动误判、危险或情绪余波的一两种感官，其余删减。'
  },
  {
    id: 'decorative_number',
    label: '无效数字',
    issueType: 'decorative_number',
    generationGuidance: '数字、年份、距离、参数和术语必须影响风险、选择、代价、误判或后果，否则不要精确。',
    auditSignal: '数字很精确，但剧情不因它发生变化。',
    falsePositive: '考据、工程、推理类题材可以用数字，但数字要参与判断。',
    repairStrategy: '让数字变成倒计时、阈值、误差、代价或证据；不能承担作用就改成角色感知。'
  },
  {
    id: 'emotion_label',
    label: '情绪贴标签',
    issueType: 'emotion_label',
    generationGuidance: '动作后不要翻译情绪；让读者从动作、停顿、错话、回避和余波里感到情绪。',
    auditSignal: '直接写他感到愤怒/恐惧/绝望/不甘，却缺少动作、生理反应或残留。',
    falsePositive: '偶尔的情绪词不是问题，问题是用情绪词替代场景体验。',
    repairStrategy: '替换为身体反应、动作迟疑、错话、回避、自我辩解或物件互动。'
  },
  {
    id: 'overfunctional_density',
    label: '功能过满',
    issueType: 'overfunctional_density',
    generationGuidance: '每章允许少量真实但不直接推进剧情的呼吸细节，用来承载角色习惯、场景生活和节奏停顿。',
    auditSignal: '每段都推进剧情、解释设定或制造钩子，没有沉默、闲笔、生活痕迹或无用但真实的细节。',
    falsePositive: '高潮段可以高功能密度，但整章不能一直处于满负荷推进。',
    repairStrategy: '加入一处来自角色视角的真实停顿、跑题对白、生活痕迹或没有立刻解释的物件。'
  },
  {
    id: 'skipped_loss',
    label: '失去跳过',
    issueType: 'skipped_loss',
    generationGuidance: '失去记忆、亲人、能力、存在痕迹或重要物品时，不只写结果，要写落空、残留、迟来的疼或自我欺骗。',
    auditSignal: '重大失去一笔带过，没有过程和余波。',
    falsePositive: '角色可以当场麻木，但后续必须有迟发反应或行为改变。',
    repairStrategy: '补习惯动作落空、旧称呼说不出口、身体迟滞、错认或关系余震。'
  },
  {
    id: 'repetitive_subject_opening',
    label: '段首重复点名',
    issueType: 'ai_tone',
    generationGuidance: '连续单人视角中，段首可用动作、物件、环境、声音、对白、心理余波、代词或省略主语，不要总以主角名开头。',
    auditSignal: '多个连续段落都以同一角色姓名开头，读起来像机械分镜。',
    falsePositive: '多人混战或复杂调度时点名可以避免歧义。',
    repairStrategy: '合并碎段，改用动作承接、物件状态、环境变化或代词起段。'
  },
  {
    id: 'prose_rhythm_flat',
    label: '句式节奏失衡',
    issueType: 'pacing',
    generationGuidance: '短句是局部节奏工具，普通叙事段落需要动作因果、观察和余波自然连成 2-5 句。',
    auditSignal: '整章大量一句一段，长中短句没有变化。',
    falsePositive: '战斗、惊惧、濒死、情绪断裂可以短句密集，但应局部使用。',
    repairStrategy: '把连续碎段合并为动作流和因果流，保留爆点短句。'
  },
  {
    id: 'ineffective_dilemma',
    label: '假两难',
    issueType: 'logic',
    generationGuidance: '两难选择必须让不同选择带来不同损失；如果结果一样，就改成误判、压力或关系代价。',
    auditSignal: '看似两难，但两个选项结果相同，只是给主角制造选择姿态。',
    falsePositive: '角色信息不足时可以做错选择，但读者要能看出信息差或误判来源。',
    repairStrategy: '重写选择条件，让每个选项损失不同，或把重点改成角色误判后的代价。'
  }
]

export const AI_TRACE_ISSUE_TYPES = [...new Set(AI_TRACE_RULES.map(rule => rule.issueType))]

export function getAiTraceRuleById(id) {
  return AI_TRACE_RULES.find(rule => rule.id === id || rule.issueType === id) || null
}

export function formatAiTraceRulesForGeneration(rules = AI_TRACE_RULES) {
  return [
    '## 写作方法（AI 痕迹源头预防）',
    '这些是创作方法，不是审稿清单；自然叙事优先，不要为了规避检测而写得做作。',
    ...rules.map(rule => `- ${rule.label}：${rule.generationGuidance}`)
  ].join('\n')
}

export function formatAiTraceRulesForAudit(rules = AI_TRACE_RULES) {
  return [
    '## AI 痕迹反证与审稿规则',
    '审稿时先判断是否真的影响读者代入，再决定是否提出问题；不要把单一词句、单一短句或单一意象当作硬罪证。',
    ...rules.map(rule => [
      `- ${rule.label}（${rule.issueType}）`,
      `  - 风险信号：${rule.auditSignal}`,
      `  - 反证条件：${rule.falsePositive}`,
      `  - 修订方向：${rule.repairStrategy}`
    ].join('\n'))
  ].join('\n')
}
