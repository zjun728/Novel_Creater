/**
 * 设定库变更提取 Prompt
 */

export function buildSettingExtractionSystemPrompt() {
  return `你是一位长篇小说设定编辑，负责从已经定稿的章节中提取需要进入“设定库”的候选变更。

你的任务不是总结剧情，而是识别后续章节容易遗忘、容易错乱、需要长期追踪的信息。

重点关注：
- 关键人物：新出现且可能后续再出场的人物，或已有角色的身份、归属、境界、功法、武器、位置、身体/心理状态变化。
- 势力组织：家族、宗门、门派、国家、军队、商会、秘密组织的出现或变化。
- 地点世界观：国家、区域、城池、宗门驻地、秘境、战场、禁区、资源分布、地貌环境。
- 修炼/能力体系：境界顺序、突破规则、功法品阶、法宝/丹药等级、禁忌规则。
- 功法物品：功法、武器、法宝、丹药、信物等的稳定归属、当前持有/接触状态、能力、限制、状态变化。
- 关系变化：亲属、师承、盟友、敌对、债务、误解、隐藏关系、势力关系。
- 硬状态：交易次数、剩余寿命、冷却时间、隐性/显性消耗规则、物品价值/售价、时间流速、当前伤势、当前位置、持有物数量、能力等级。

提取原则：
- 只提取会影响后续创作连续性的设定，不提取一闪而过的路人或纯氛围描写。
- 新实体必须判断是否有后续价值，不能把每个名字都当长期人物。
- 优先更新已有实体和已有关系，避免重复创建。
- 变更必须有原文证据。
- 凡涉及数字、次数、寿命、价格、时间比例、冷却、消耗、等级、持有物数量，必须保留精确数字和单位。
- 不确定时降低 confidence，不要编造原文没有的信息。
- 势力/组织 summary 只写长期定义、根本身份、长期目标或稳定控制关系；本章派人、追踪、尾随、盯上、接触、拉拢、收购、交换、交易、威胁、封锁、设伏、搜查、试图、索要、逼迫等当前行动，写入 profile.currentActions，不写入 summary。
- 章节发现、线索、证据、历史补充、内部机制等不改写长期定义的信息，写入 profile.observedFacts、profile.revealedClues、profile.internalMechanisms 或 profile.chapterEvidence。
- 输出必须是 JSON，不要输出解释。`
}

export function buildSettingExtractionPrompt(chapterContent, chapterNum, existingSettings = [], existingRelations = []) {
  const existingText = formatExistingSettings(existingSettings)
  const relationText = formatExistingRelations(existingRelations, existingSettings)
  return `请从以下定稿章节中提取“待确认设定变更”。

## 第 ${chapterNum} 章正文
---
${chapterContent}
---

${existingText ? `## 已有设定库（避免重复创建）\n${existingText}` : ''}

${relationText ? `## 已有关系（避免重复创建关系）\n${relationText}` : ''}

请输出一个 JSON 对象，顶层字段固定为 "settingChanges"。不要输出 Markdown，不要输出解释。每个对象只能使用以下字段：

\`\`\`json
{
  "settingChanges": [
    {
      "entityType": "character|faction|location|power_system|technique|item",
      "entityName": "实体名称",
      "changeType": "new_entity|update_entity|relationship",
      "fieldPath": "summary|category|profile.family|profile.sect|profile.faction|profile.nation|profile.rankTitle|profile.realm|profile.realmLevel|profile.techniques|profile.weapons|profile.location|profile.physicalStatus|profile.mentalState|profile.currentGoal|profile.leader|profile.territory|profile.resources|profile.controller|profile.realms|profile.breakthroughRules|profile.grade|profile.owner|profile.currentHolder|profile.possessionStatus|profile.custodyState|profile.contactStatus|profile.accessState|profile.observedFacts|profile.revealedClues|profile.currentActions|profile.internalMechanisms|profile.chapterEvidence|profile.ability|profile.transactionCount|profile.remainingLifespan|profile.cooldownUntil|profile.costRule|profile.valueLevel|profile.price|profile.timeFlowRule|profile.behaviorState",
      "oldValue": "如果原文或已有设定能判断旧值，填写旧值；否则为空字符串",
      "newValue": "新的设定值；如果 changeType 是 relationship，则必须是一个对象",
      "profilePatch": {
        "只在 new_entity 时填写": "可包含 realm、sect、family、location、owner、currentHolder、possessionStatus、contactStatus、accessState、observedFacts、revealedClues、currentActions、internalMechanisms、chapterEvidence、grade、ability、transactionCount、remainingLifespan、cooldownUntil、costRule、valueLevel、price、timeFlowRule 等字段"
      },
      "category": "可选分类，如 主角/宗门/秘境/境界体系",
      "summary": "一句话说明该实体或变化对后续创作的意义",
      "importance": 1,
      "evidence": "原文依据，短句引用或准确转述",
      "confidence": 0.8
    }
  ]
}
\`\`\`

relationship 类型的 newValue 必须使用对象：
\`\`\`json
{
  "targetEntityName": "关系另一端名称",
  "targetEntityType": "character|faction|location|power_system|technique|item",
  "relationType": "师承|亲属|盟友|敌对|持有|控制|隶属|误解|债务|隐藏关系",
  "stance": "亲近|中立|敌对|利用|未知",
  "summary": "关系说明"
}
\`\`\`

要求：
1. 如果是新人物，必须判断他/她是否可能后续再出现；纯路人不提取。
2. 如果是已有实体变化，用 update_entity，不要重复 new_entity。
3. 如果一个新人物同时有多个重要属性，可以输出一个 new_entity，并把属性放入 profilePatch。
4. 如果只是人物短暂情绪，不影响后续，不要提取。
5. 如果本章发生交易、寿命/次数扣减、冷却变化、物品价值确认、时间流速确认、伤势/位置/持有物变化，必须作为 update_entity 或 new_entity 提取。
6. profile.owner 只写稳定/法理/长期归属；接触、临时持有、已取出、当前携带、被夺走、已归还等写入 profile.currentHolder、profile.possessionStatus、profile.contactStatus 或 profile.accessState。
7. 势力/组织 summary 不写当前章行动；“已派人追踪”“试图交换”“暗中拉拢”“封锁搜查”等写入 profile.currentActions，线索/证据/历史补充写入 profile.observedFacts。
8. 如果本章没有值得入库的设定变化，输出 {"settingChanges":[]}。`
}

export function buildSettingExtractionRepairPrompt(rawText) {
  return `请把下面模型输出修复为合法 JSON 对象。

只允许输出：
{
  "settingChanges": []
}

要求：
- 保留原文中已经出现的设定候选，不新增、不要脑补。
- 兼容原文中的 settings、changes、settingChanges、data、items 等字段，把它们统一放入 settingChanges。
- 如果候选字段缺失，尽量按原文补齐字段名；不能判断的字段填空字符串。
- relationship 的 newValue 必须保持对象。
- 硬状态候选优先保留：交易次数、剩余寿命、冷却时间、物品价值、时间流速。
- 如果原文没有任何可保存候选，输出 {"settingChanges":[]}。
- 不要输出 Markdown，不要解释。

原始输出：
---
${String(rawText || '').slice(0, 12000)}
---`
}

function formatExistingSettings(settings) {
  if (!Array.isArray(settings) || !settings.length) return ''
  return settings
    .slice(0, 80)
    .map(entity => {
      const profile = entity.profile || {}
      const facts = ['family', 'sect', 'faction', 'nation', 'realm', 'location', 'owner', 'currentHolder', 'possessionStatus', 'grade']
        .filter(key => profile[key])
        .map(key => `${key}=${profile[key]}`)
        .join('；')
      return `- [${entity.entityType}] ${entity.name}${entity.category ? `（${entity.category}）` : ''}：${entity.summary || ''}${facts ? `；${facts}` : ''}`
    })
    .join('\n')
}

function formatExistingRelations(relations, settings = []) {
  if (!Array.isArray(relations) || !relations.length) return ''
  const entityMap = new Map((settings || []).map(entity => [entity.id, entity.name]))
  return relations
    .slice(0, 80)
    .map(relation => {
      const source = entityMap.get(relation.sourceEntityId) || relation.sourceEntityName || '未知主体'
      const target = entityMap.get(relation.targetEntityId) || relation.targetEntityName || '未知客体'
      return `- ${source} -> ${relation.relationType || '关系'} -> ${target}${relation.stance ? `；立场=${relation.stance}` : ''}${relation.summary ? `；${relation.summary}` : ''}`
    })
    .join('\n')
}
