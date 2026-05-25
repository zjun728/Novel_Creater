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
- 功法物品：功法、武器、法宝、丹药、信物等的持有者、能力、限制、状态变化。
- 关系变化：亲属、师承、盟友、敌对、债务、误解、隐藏关系、势力关系。

提取原则：
- 只提取会影响后续创作连续性的设定，不提取一闪而过的路人或纯氛围描写。
- 新实体必须判断是否有后续价值，不能把每个名字都当长期人物。
- 优先更新已有实体和已有关系，避免重复创建。
- 变更必须有原文证据。
- 不确定时降低 confidence，不要编造原文没有的信息。
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
      "fieldPath": "summary|category|profile.family|profile.sect|profile.faction|profile.nation|profile.rankTitle|profile.realm|profile.realmLevel|profile.techniques|profile.weapons|profile.location|profile.physicalStatus|profile.mentalState|profile.currentGoal|profile.leader|profile.territory|profile.resources|profile.controller|profile.realms|profile.breakthroughRules|profile.grade|profile.owner|profile.ability",
      "oldValue": "如果原文或已有设定能判断旧值，填写旧值；否则为空字符串",
      "newValue": "新的设定值；如果 changeType 是 relationship，则必须是一个对象",
      "profilePatch": {
        "只在 new_entity 时填写": "可包含 realm、sect、family、location、owner、grade、ability 等字段"
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
5. 如果本章没有值得入库的设定变化，输出 {"settingChanges":[]}。`
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
      const facts = ['family', 'sect', 'faction', 'nation', 'realm', 'location', 'owner', 'grade']
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
