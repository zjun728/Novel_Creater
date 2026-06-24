export const SETTING_CHANGE_CLASSIFICATIONS = {
  hardConflict: 'hard_conflict',
  revealOrRefinement: 'reveal_or_refinement',
  lowRiskUpdate: 'low_risk_update'
}

export const SETTING_FIELD_TIERS = {
  hardSetting: 'hardSetting',
  dynamicState: 'dynamicState',
  observedCapability: 'observedCapability',
  general: 'general'
}

export const RULE_INSTANCE_REHOME_FIELD = 'profile.observedCosts'
export const SUMMARY_CHAPTER_FACT_REHOME_FIELD = 'profile.observedFacts'
export const HARD_FIELD_BEHAVIOR_REHOME_FIELD = 'profile.hiddenStance'
export const OWNER_POSSESSION_REHOME_FIELD = 'profile.possessionStatus'

export const SETTING_CHANGE_CLASSIFICATION_LABELS = {
  hard_conflict: '硬冲突',
  reveal_or_refinement: '隐藏信息揭示/旧设定细化',
  low_risk_update: '低风险更新'
}

export const HARD_SETTING_FIELDS = new Set([
  'summary',
  'category',
  'status',
  'profile.identity',
  'profile.affiliation',
  'profile.family',
  'profile.sect',
  'profile.faction',
  'profile.nation',
  'profile.rankTitle',
  'profile.realm',
  'profile.realmLevel',
  'profile.powerLevel',
  'profile.abilityLevel',
  'profile.techniques',
  'profile.weapons',
  'profile.fixedRelationship',
  'profile.leader',
  'profile.territory',
  'profile.resources',
  'profile.controller',
  'profile.realms',
  'profile.breakthroughRules',
  'profile.grade',
  'profile.owner',
  'profile.coreLimitations',
  'profile.worldRules',
  'profile.powerRules',
  'profile.itemCoreLimitations',
  'profile.bloodline',
  'profile.lineage',
  'profile.camp',
  'profile.alignment',
  'profile.country'
])

export const DYNAMIC_STATE_FIELDS = new Set([
  'profile.location',
  'profile.currentGoal',
  'profile.temporaryGoal',
  'profile.physicalStatus',
  'profile.itemStatus',
  'profile.mentalState',
  'profile.behaviorState',
  'profile.currentState',
  'profile.situation',
  'profile.currentSituation',
  'profile.clueProgress',
  'profile.progress',
  'profile.lastKnownLocation',
  'profile.observedCosts',
  'profile.costHistory',
  'profile.ruleExamples',
  'profile.observedFacts',
  'profile.revealedClues',
  'profile.currentActions',
  'profile.internalMechanisms',
  'profile.chapterEvidence',
  'profile.hiddenStance',
  'profile.currentAction',
  'profile.currentHolder',
  'profile.possessionStatus',
  'profile.custodyState',
  'profile.contactStatus',
  'profile.accessState'
])

export const OBSERVED_CAPABILITY_FIELDS = new Set([
  'profile.ability',
  'profile.capability',
  'profile.observedAbility'
])

const HARD_FIELD_ALIASES = {
  identity: 'profile.identity',
  affiliation: 'profile.affiliation',
  family: 'profile.family',
  sect: 'profile.sect',
  faction: 'profile.faction',
  nation: 'profile.nation',
  rankTitle: 'profile.rankTitle',
  realm: 'profile.realm',
  realmLevel: 'profile.realmLevel',
  powerLevel: 'profile.powerLevel',
  abilityLevel: 'profile.abilityLevel',
  fixedRelationship: 'profile.fixedRelationship',
  owner: 'profile.owner',
  itemOwner: 'profile.owner',
  holder: 'profile.currentHolder',
  currentHolder: 'profile.currentHolder',
  possessor: 'profile.currentHolder',
  currentPossessor: 'profile.currentHolder',
  custody: 'profile.custodyState',
  possessionStatus: 'profile.possessionStatus',
  contactStatus: 'profile.contactStatus',
  accessState: 'profile.accessState',
  ability: 'profile.ability',
  capability: 'profile.capability',
  observedAbility: 'profile.observedAbility',
  observedFacts: 'profile.observedFacts',
  revealedClues: 'profile.revealedClues',
  currentActions: 'profile.currentActions',
  internalMechanisms: 'profile.internalMechanisms',
  chapterEvidence: 'profile.chapterEvidence',
  hiddenStance: 'profile.hiddenStance',
  currentAction: 'profile.currentAction',
  physicalStatus: 'profile.physicalStatus',
  itemStatus: 'profile.itemStatus',
  mentalState: 'profile.mentalState',
  behaviorState: 'profile.behaviorState',
  currentGoal: 'profile.currentGoal',
  currentState: 'profile.currentState',
  location: 'profile.location'
}

const FIELD_LABELS = {
  summary: '概要',
  category: '分类',
  status: '状态',
  'profile.identity': '身份',
  'profile.affiliation': '势力归属',
  'profile.family': '家族',
  'profile.sect': '宗门/门派',
  'profile.faction': '阵营',
  'profile.nation': '国家',
  'profile.rankTitle': '身份/职位',
  'profile.realm': '境界',
  'profile.realmLevel': '境界层级',
  'profile.powerLevel': '能力等级',
  'profile.abilityLevel': '能力等级',
  'profile.techniques': '功法',
  'profile.weapons': '武器/法宝',
  'profile.location': '当前位置',
  'profile.physicalStatus': '身体状态',
  'profile.currentGoal': '当前目标',
  'profile.mentalState': '心理状态',
  'profile.behaviorState': '行动状态',
  'profile.currentState': '当前状态',
  'profile.fixedRelationship': '固定关系',
  'profile.owner': '归属/持有人',
  'profile.currentHolder': '当前持有者',
  'profile.possessionStatus': '持有状态',
  'profile.custodyState': '保管状态',
  'profile.contactStatus': '接触状态',
  'profile.accessState': '访问/取用状态',
  'profile.ability': '能力',
  'profile.capability': '能力表现',
  'profile.observedAbility': '已观察能力表现',
  'profile.itemStatus': '物品状态',
  'profile.observedCosts': '已发生代价',
  'profile.costHistory': '代价历史',
  'profile.ruleExamples': '规则实例',
  'profile.observedFacts': '已观察事实',
  'profile.revealedClues': '已揭示线索',
  'profile.currentActions': '当前行动',
  'profile.internalMechanisms': '内部机制',
  'profile.chapterEvidence': '章节证据',
  'profile.hiddenStance': '隐藏立场',
  'profile.currentAction': '当前行为'
}

const RESERVATION_PATTERN = /(官方结论|表面(?:信息|说法|记录)?|传闻|传言|据说|可能|疑似|疑点|暗示|线索|未确认|不明|下落不明|名籍.*封存|封存.*名籍|封存于|旧档|档案异常|名字异常|星账.*名字|名字出现在|表面死亡|假死)/
const DEATH_ASSERTION_PATTERN = /(死于|死去|死亡|身亡|遇难|已死|已经死|死了|亡故|殒命|葬身)/
const DEATH_NEGATION_PATTERN = /(未死|可能未死|没有死|没有死亡|并未死|并未死亡|还活着|仍活着|活着|存活|假死|未必死亡|并非死亡|不曾死亡)/
const DIRECT_NEGATION_PATTERN = /(并非|不是|不再是|没有|从未|未曾|不曾|不存在|不属于|并未|否认|推翻)/
const AFFIRMATION_PATTERN = /(是|为|属于|位于|拥有|掌握|效忠|结盟|亲属|父亲|母亲|身份|状态|死亡|死于|死去)/
const OBSERVED_CAPABILITY_PATTERN = /(新增|已展现|展现|已观察|观察到|表现|使用效果|触发|现象|浮现|显示|感应|震动|发热|发光|主动|能(?:够)?|可以|会|使用后|发动后|触发后|表现为)/
const CORE_RULE_PATTERN = /(不能|只能|必须|不得|不可|限制|核心规则|规则|代价|随机|不可逆|只记录|不能伪造|不能销毁)/
const CORE_RULE_NEGATION_PATTERN = /(不再|无需|不必|无须|没有代价|免代价|可以伪造|可以销毁|可以复制|可被复制|不再需要|取消|删除|推翻|改写|改为|变成|不受限制|记录死人|记录死者|死人代价|死者代价|代价可逆|可以逆转|可逆转)/
const RULE_INSTANCE_PATTERN = /(第[一二三四五六七八九十百千万\d]+次|首次|初次|再(?:次|度)|本章|第\s*\d+\s*章|已发生|发生过|代价[:：]|欠债[一二三四五六七八九十\d]*次|左眼|右眼|视力|记忆|寿元|灵脉|失去|损失|扣除)/
const PLACEHOLDER_SUMMARY_PATTERN = /^(?:第\s*(?:\?|[一二三四五六七八九十百千万\d]+)\s*章自动识别的设定|自动识别的设定|待补全|待完善|未知|暂无|无|占位|占位设定|暂无明确设定|无有效摘要)$/
const SUMMARY_CHAPTER_FACT_PATTERN = /(第\s*[一二三四五六七八九十百千万\d]+\s*章|本章|章节|新增|揭示|发现|线索|证据|暗号|铜牌|追捕|帮助|调查|处决|内部|机制|当前|正在|已发生|行动|态势|动向|外围|暗中|派人|追踪|尾随|盯上|接触|拉拢|收购|交换|交易|威胁|封锁|设伏|搜查|试图|索要|逼迫|交换条件)/
const SUMMARY_CURRENT_ACTION_PATTERN = /(已派人|派人|尾随|盯上|拉拢|收购|交换|交易|威胁|封锁|设伏|搜查|试图|索要|逼迫|交换条件|暗中.{0,8}拉拢|已.{0,8}追踪|正在.{0,8}(追踪|尾随|盯上|拉拢|交换|交易|威胁|封锁|设伏|搜查|索要|逼迫)|试图.{0,8}(交换|交易|索要|逼迫|收购|拉拢))/
const UNCERTAIN_SUMMARY_FRAGMENT_PATTERN = /(可能|疑似|或许|也许|未确认|不明|下落不明|传闻|据说|暗示|线索|疑点)/
const DESCRIPTIVE_PLACEHOLDER_NAME_PATTERN = /(老人|老头|老者|男子|女人|女子|少年|少女|孩童|灰袍|黑袍|白衣|黑斗笠|斗笠|面具|蒙面|木门后|门后|卖.+的|守门|账房|追踪者|陌生人|来客|掌柜|伙计)$/
const UNCERTAIN_IDENTITY_PATTERN = /(可能|疑似|像是|看起来|身份不明|身份未明|未确认|不明|关键情报源|旧识|父亲旧识|线索人物|知情人|神秘|陌生)/
const FORMAL_IDENTITY_PATTERN = /(?:^|[，,。；;\s])(?:[一-龥]{2,4})(?:[，,。；;\s]|$)|(?:名叫|叫作|叫做|本名|真名|姓名|自称|承认自己叫).{0,8}[一-龥]{2,4}|(?:前|曾任|现任|原为|任).{0,16}(账房|星吏|官|吏|司主|掌柜|管事|弟子|长老|供奉|执事)/
const SUMMARY_IDENTITY_REWRITE_PATTERN = /(其实|并非|不是|不再是|变成|改为|本质上|根本上|真实身份|实际是).{0,24}(非官方|不是官方|商盟|分部|公开官署|官署|秘密组织|公开机构|官方机构|民间组织|商业联盟|商会|伪装|伪造)/
const OFFICIAL_ORG_PATTERN = /(官方机构|朝廷|官署|巡查|缉拿|执法|官府|公门)/
const SECRET_ORG_PATTERN = /(秘密组织|隐秘组织|暗中|地下|外围|暗号|秘密结社)/
const PUBLIC_ORG_PATTERN = /(公开官署|公开机构|官方机构|正式登记|朝廷设立)/
const HIDDEN_BEHAVIOR_PATTERN = /(暗中|秘密|私下|表面|伪装|但|却|当前|正在|帮助|追捕|调查|保护|掩护|背离|隐藏|短期|暂时|见习|卧底|内应)/
const OWNER_UNSTABLE_OR_DYNAMIC_PATTERN = /(未知|不明|疑似|可能|未确认|已接触|接触|未取出|取出|暂时|临时|当前|拿到|拿走|带走|携带|保管|藏在|收起|夺走|抢走|被夺|归还|交还|触碰|持有)/
const OWNER_POSSESSION_ACTION_PATTERN = /(已接触|接触|触碰|未取出|取出|暂时|临时|当前|拿到|拿走|带走|携带|保管|藏在|收起|夺走|抢走|被夺|归还|交还|持有|怀里|身上|掌中|手中)/
const OWNER_POSSESSION_NEGATION_PATTERN = /(无|没有|未|并未|并无|缺少|不具备|不能证明|未证明|没有证明).{0,18}(接触|取出|拿到|拿走|带走|携带|持有|保管|夺走|抢走|被夺|归还|交还|触碰)/
const OWNER_TRANSFER_PATTERN = /(正式|法理|长期|永久|真正|确认|明确|所有权|归属|拥有权|转让|移交|交割|继承|赠与|交给|交还|归还).{0,18}(归属|所有|拥有|主人|持有人|所有权|拥有权|移交|转让|继承|赠与|交割|交给|交还|归还)|(?:归属|所有权|拥有权).{0,18}(转移|移交|确认|改归|属于|归于)|(?:正式|法理|长期|永久|真正).{0,18}(属于|拥有|持有|归属)|(?:当众|明确).{0,12}(转让|移交|赠与|交割)/
const OWNER_TRANSFER_NEGATION_PATTERN = /(无|没有|未|并未|并无|缺少|不具备|不能证明|未证明|没有证明).{0,18}(转让|移交|交割|继承|赠与|归还|交还|所有权|归属|拥有权|法理|永久|长期)/
const HARD_PROFILE_STABLE_FIELDS = new Set([
  'profile.identity',
  'profile.affiliation',
  'profile.family',
  'profile.sect',
  'profile.faction',
  'profile.nation',
  'profile.rankTitle',
  'profile.realm',
  'profile.realmLevel',
  'profile.powerLevel',
  'profile.abilityLevel',
  'profile.fixedRelationship',
  'profile.leader',
  'profile.territory',
  'profile.controller',
  'profile.owner',
  'profile.camp',
  'profile.alignment',
  'profile.country'
])

export function classifySettingChangeRisk(event = {}, context = {}) {
  const fieldPath = normalizeEventFieldPath(event.fieldPath, event.changeType)
  const fieldTier = getSettingFieldTier(fieldPath)
  const contextOldValue = context.existingValue ?? readEntityField(context.existingEntity, fieldPath)
  const oldText = cleanText(event.oldValue || contextOldValue)
  const newText = cleanText(event.newValue)
  const evidenceText = cleanText(event.evidence)
  const combinedNew = `${newText} ${evidenceText}`
  const hasOldValue = oldText.length > 0
  const hasNewValue = newText.length > 0
  const structuralWarnings = collectStructuralHardFieldWarnings(event, context)
  const advisoryWarnings = collectAdvisoryWarnings(event, context)
  let risk

  if (!hasOldValue || !hasNewValue || event.changeType === 'new_entity') {
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.lowRiskUpdate, advisoryWarnings, fieldTier)
    return applyStructuralRisk(event, context, risk, structuralWarnings)
  }

  if (fieldTier === SETTING_FIELD_TIERS.dynamicState) {
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.lowRiskUpdate, advisoryWarnings, fieldTier)
    return applyStructuralRisk(event, context, risk, structuralWarnings)
  }

  if (fieldTier === SETTING_FIELD_TIERS.observedCapability) {
    if (isAbilityCoreConflict(oldText, newText, evidenceText)) {
      risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.hardConflict, [
        `硬冲突：能力核心规则将从「${oldText}」变为「${newText}」。`
      ], fieldTier)
      return applyStructuralRisk(event, context, risk, structuralWarnings)
    }
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement, [
      '能力表现揭示/旧能力细化：新设定是在保留旧规则的基础上增加已观察到的表现、使用效果或触发现象。'
    ], fieldTier)
    return applyStructuralRisk(event, context, risk, structuralWarnings)
  }

  if (fieldPath === 'summary' && isRuleInstanceSummarySupplement(oldText, newText, evidenceText)) {
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement, [
      `规则实例/已发生代价补充：不改写 summary，新增信息应归位到 ${RULE_INSTANCE_REHOME_FIELD}。`
    ], fieldTier, {
      rehomeTargetField: RULE_INSTANCE_REHOME_FIELD,
      rehomeTargetTier: getSettingFieldTier(RULE_INSTANCE_REHOME_FIELD)
    })
    return risk
  }

  if (fieldPath === 'summary' && isPlaceholderSummary(oldText)) {
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement, [
      '占位 summary 补全：旧概要没有有效信息，新 summary 可作为完整设定补全。'
    ], fieldTier)
    return applyStructuralRisk(event, context, risk, structuralWarnings)
  }

  if (fieldPath === 'summary' && isDescriptivePlaceholderIdentityReveal(event.entityName, oldText, newText, evidenceText)) {
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement, [
      '身份揭示/描述性占位实体补全：旧描述名应进入 aliases，新正式姓名可作为 canonicalName，旧 summary 未被推翻的信息保留到身份揭示记录。'
    ], fieldTier)
    return applyStructuralRisk(event, context, risk, structuralWarnings)
  }

  if (fieldPath === 'summary' && isSummaryChapterFactSupplement(oldText, newText, evidenceText)) {
    const targetField = chooseSummaryChapterFactRehomeField(newText, evidenceText)
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement, [
      `章节事实补充：不覆盖 summary，新增行动、线索或内部机制应归位到 ${targetField}。`
    ], fieldTier, {
      rehomeTargetField: targetField,
      rehomeTargetTier: getSettingFieldTier(targetField)
    })
    return risk
  }

  if (isOwnerPossessionRehomeChange(fieldPath, oldText, newText, evidenceText)) {
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement, [
      `owner 动态持有/接触状态归位：保留 profile.owner 的稳定归属语义，新增接触、临时持有、取出或当前携带信息应归位到 ${OWNER_POSSESSION_REHOME_FIELD}，不覆盖 profile.owner。`
    ], fieldTier, {
      rehomeTargetField: OWNER_POSSESSION_REHOME_FIELD,
      rehomeTargetTier: getSettingFieldTier(OWNER_POSSESSION_REHOME_FIELD),
      rehomeTargetValue: buildOwnerPossessionRehomeValue(oldText, newText, evidenceText),
      stableOwnerValue: stableOwnerValueFromMixed(oldText)
    })
    return applyStructuralRisk(event, context, risk, structuralWarnings)
  }

  if (isHardFieldBehaviorSupplement(fieldPath, oldText, newText, evidenceText)) {
    const targetField = chooseHardFieldBehaviorRehomeField(newText, evidenceText)
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement, [
      `硬字段混入当前行为/隐藏立场：保留「${fieldLabel(fieldPath)}」旧值，新增信息应归位到 ${targetField}。`
    ], fieldTier, {
      rehomeTargetField: targetField,
      rehomeTargetTier: getSettingFieldTier(targetField)
    })
    return risk
  }

  const hasReservation = RESERVATION_PATTERN.test(`${oldText} ${combinedNew}`)
  const deathContradiction = DEATH_ASSERTION_PATTERN.test(oldText) && DEATH_NEGATION_PATTERN.test(combinedNew)
  if (deathContradiction) {
    if (hasReservation) {
      risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement, [
        '隐藏信息揭示/旧设定细化：新设定保留旧信息的表面说法，并增加证据或疑点。'
      ], fieldTier)
      return applyStructuralRisk(event, context, risk, structuralWarnings)
    }
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.hardConflict, [
      '硬冲突：旧设定明确断言死亡，新设定直接否定死亡，需要逐条确认。'
    ], fieldTier)
    return applyStructuralRisk(event, context, risk, structuralWarnings)
  }

  const directContradiction = AFFIRMATION_PATTERN.test(oldText) &&
    DIRECT_NEGATION_PATTERN.test(newText) &&
    !hasReservation
  if (directContradiction) {
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.hardConflict, [
      '硬冲突：新设定直接否定旧设定，且没有传闻、官方结论或疑似等保留空间。'
    ], fieldTier)
    return applyStructuralRisk(event, context, risk, structuralWarnings)
  }

  if (hasReservation) {
    risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement, [
      '隐藏信息揭示/旧设定细化：新设定是在旧信息上增加证据、疑点或表面/真相层次。'
    ], fieldTier)
    return applyStructuralRisk(event, context, risk, structuralWarnings)
  }

  risk = buildRisk(SETTING_CHANGE_CLASSIFICATIONS.lowRiskUpdate, advisoryWarnings, fieldTier)
  return applyStructuralRisk(event, context, risk, structuralWarnings)
}

export function isBatchAcceptableSettingChange(event = {}) {
  const classification = event.classification || classifySettingChangeRisk(event).classification
  return classification === SETTING_CHANGE_CLASSIFICATIONS.lowRiskUpdate ||
    classification === SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement
}

export function sortSettingEventsForConfirmation(events = []) {
  return [...(Array.isArray(events) ? events : [])].sort((a, b) => {
    const rankA = settingEventConfirmationRank(a)
    const rankB = settingEventConfirmationRank(b)
    if (rankA !== rankB) return rankA - rankB
    return Number(a.createdAt || a.created_at || 0) - Number(b.createdAt || b.created_at || 0)
  })
}

export function settingChangeRiskLabel(classification) {
  return SETTING_CHANGE_CLASSIFICATION_LABELS[classification] || SETTING_CHANGE_CLASSIFICATION_LABELS.low_risk_update
}

export function isHardSettingField(fieldPath) {
  return hardFieldCandidates(fieldPath).some(candidate => HARD_SETTING_FIELDS.has(candidate))
}

export function isDynamicStateField(fieldPath) {
  return hardFieldCandidates(fieldPath).some(candidate => DYNAMIC_STATE_FIELDS.has(candidate))
}

export function isObservedCapabilityField(fieldPath) {
  return hardFieldCandidates(fieldPath).some(candidate => OBSERVED_CAPABILITY_FIELDS.has(candidate))
}

export function getSettingFieldTier(fieldPath) {
  if (isDynamicStateField(fieldPath)) return SETTING_FIELD_TIERS.dynamicState
  if (isObservedCapabilityField(fieldPath)) return SETTING_FIELD_TIERS.observedCapability
  if (isHardSettingField(fieldPath)) return SETTING_FIELD_TIERS.hardSetting
  return SETTING_FIELD_TIERS.general
}

export function isPlaceholderSettingEntity(entity = {}) {
  if (!entity) return false
  const summary = cleanText(entity.summary)
  if (summary && isPlaceholderSummary(summary)) return true
  if (hasChapterDependency(entity)) return false
  const category = cleanText(entity.category)
  const tags = normalizeList(entity.tags)
  const profile = parseMaybeJson(entity.profile) || {}
  const profileEmpty = !profile || (typeof profile === 'object' && !Array.isArray(profile) && !Object.keys(profile).length)
  const hasMeaningfulProfile = profile && typeof profile === 'object' && !Array.isArray(profile) &&
    Object.values(profile).some(value => cleanText(value))
  return tags.includes('AI识别') ||
    (profileEmpty && !summary && !category) ||
    (!hasMeaningfulProfile && !summary && !category)
}

function buildRisk(classification, conflictWarnings = [], fieldTier = SETTING_FIELD_TIERS.general, extra = {}) {
  return {
    classification,
    label: settingChangeRiskLabel(classification),
    fieldTier,
    conflictWarnings,
    batchAcceptable: classification !== SETTING_CHANGE_CLASSIFICATIONS.hardConflict,
    whyBlocked: classification === SETTING_CHANGE_CLASSIFICATIONS.hardConflict
      ? conflictWarnings.join('；')
      : '',
    ...extra
  }
}

function applyStructuralRisk(event, context, risk, structuralWarnings) {
  if (!structuralWarnings.length) return risk
  if (
    risk.classification === SETTING_CHANGE_CLASSIFICATIONS.revealOrRefinement &&
    allowsLayeredHardFieldReveal(event, context)
  ) {
    return {
      ...risk,
      conflictWarnings: [...risk.conflictWarnings, ...structuralWarnings.map(item => `硬设定字段已按揭示/细化处理：${item}`)]
    }
  }
  return {
    ...risk,
    classification: SETTING_CHANGE_CLASSIFICATIONS.hardConflict,
    label: settingChangeRiskLabel(SETTING_CHANGE_CLASSIFICATIONS.hardConflict),
    conflictWarnings: [...risk.conflictWarnings, ...structuralWarnings],
    batchAcceptable: false,
    fieldTier: structuralWarnings.some(item => item.includes('能力核心规则'))
      ? SETTING_FIELD_TIERS.observedCapability
      : SETTING_FIELD_TIERS.hardSetting,
    whyBlocked: [...risk.conflictWarnings, ...structuralWarnings].join('；')
  }
}

function collectStructuralHardFieldWarnings(event = {}, context = {}) {
  const entity = context.existingEntity || null
  if (!entity) return []
  if (event.changeType === 'relationship') return []
  if (event.changeType === 'new_entity' && isPlaceholderSettingEntity(entity)) return []

  if (event.changeType === 'new_entity') {
    return collectProfileHardFieldWarnings(event, entity)
  }

  const fieldPath = normalizeEventFieldPath(event.fieldPath, event.changeType)
  const existingValue = cleanText(context.existingValue ?? readEntityField(entity, fieldPath))
  const incomingValue = cleanText(resolveIncomingValue(event, fieldPath))
  if (!existingValue || !incomingValue || existingValue === incomingValue) return []
  if (isDynamicStateField(fieldPath)) return []
  if (isObservedCapabilityField(fieldPath)) {
    return isAbilityCoreConflict(existingValue, incomingValue, cleanText(event.evidence))
      ? [`能力核心规则「${fieldLabel(fieldPath)}」将从「${existingValue}」变为「${incomingValue}」。`]
      : []
  }
  if (!isHardSettingField(fieldPath)) return []
  if (fieldPath === 'summary' && isRuleInstanceSummarySupplement(existingValue, incomingValue, cleanText(event.evidence))) return []
  if (fieldPath === 'summary' && isPlaceholderSummary(existingValue)) return []
  if (fieldPath === 'summary' && isDescriptivePlaceholderIdentityReveal(entity.name || event.entityName, existingValue, incomingValue, cleanText(event.evidence))) return []
  if (fieldPath === 'summary' && isSummaryChapterFactSupplement(existingValue, incomingValue, cleanText(event.evidence))) return []
  if (fieldPath === 'profile.owner' && isOwnerPossessionRehomeChange(fieldPath, existingValue, incomingValue, cleanText(event.evidence))) return []
  if (fieldPath === 'profile.owner' && hasStableOwnerTransferEvidence(existingValue, incomingValue, cleanText(event.evidence))) return []
  if (isHardFieldBehaviorSupplement(fieldPath, existingValue, incomingValue, cleanText(event.evidence))) return []
  return [`硬设定字段「${fieldLabel(fieldPath)}」将从「${existingValue}」变为「${incomingValue}」。`]
}

function collectProfileHardFieldWarnings(event, entity) {
  const warnings = []
  const payload = parseMaybeJson(event.newValue)
  if (!payload || typeof payload !== 'object') return warnings
  for (const fieldPath of ['summary', 'category', 'status']) {
    if (!(fieldPath in payload)) continue
    if (!isHardSettingField(fieldPath)) continue
    const existingValue = cleanText(readEntityField(entity, fieldPath))
    const incomingValue = cleanText(payload[fieldPath])
    if (!existingValue || !incomingValue || existingValue === incomingValue) continue
    if (fieldPath === 'summary' && isRuleInstanceSummarySupplement(existingValue, incomingValue, cleanText(event.evidence))) continue
    if (fieldPath === 'summary' && isPlaceholderSummary(existingValue)) continue
    if (fieldPath === 'summary' && isDescriptivePlaceholderIdentityReveal(entity.name || event.entityName, existingValue, incomingValue, cleanText(event.evidence))) continue
    if (fieldPath === 'summary' && isSummaryChapterFactSupplement(existingValue, incomingValue, cleanText(event.evidence))) continue
    warnings.push(`硬设定字段「${fieldLabel(fieldPath)}」将从「${existingValue}」变为「${incomingValue}」。`)
  }
  const profile = {
    ...(payload.profile && typeof payload.profile === 'object' ? payload.profile : {}),
    ...(payload.profilePatch && typeof payload.profilePatch === 'object' ? payload.profilePatch : {})
  }
  for (const [key, value] of Object.entries(profile)) {
    const fieldPath = normalizeProfileFieldPath(key)
    const existingValue = cleanText(readEntityField(entity, fieldPath))
    const incomingValue = cleanText(value)
    if (!existingValue || !incomingValue || existingValue === incomingValue) continue
    if (isDynamicStateField(fieldPath)) continue
    if (isObservedCapabilityField(fieldPath)) {
      if (isAbilityCoreConflict(existingValue, incomingValue, cleanText(event.evidence))) {
        warnings.push(`能力核心规则「${fieldLabel(fieldPath)}」将从「${existingValue}」变为「${incomingValue}」。`)
      }
      continue
    }
    if (!isHardSettingField(fieldPath)) continue
    if (fieldPath === 'profile.owner' && isOwnerPossessionRehomeChange(fieldPath, existingValue, incomingValue, cleanText(event.evidence))) continue
    if (fieldPath === 'profile.owner' && hasStableOwnerTransferEvidence(existingValue, incomingValue, cleanText(event.evidence))) continue
    if (isHardFieldBehaviorSupplement(fieldPath, existingValue, incomingValue, cleanText(event.evidence))) continue
    warnings.push(`硬设定字段「${fieldLabel(fieldPath)}」将从「${existingValue}」变为「${incomingValue}」。`)
  }
  return warnings
}

function collectAdvisoryWarnings(event = {}, context = {}) {
  if (event.changeType !== 'new_entity' || !context.existingEntity) return []
  const entity = context.existingEntity
  if (isPlaceholderSettingEntity(entity)) {
    return [`占位实体补全：已存在同名占位实体「${entity.name || event.entityName || '未命名'}」，确认后会用完整设定补全该档案。`]
  }
  return [`已存在同名${entity.entityType || '设定'}「${entity.name || event.entityName || '未命名'}」，确认后会更新已有档案，而不是创建全新实体。`]
}

function allowsLayeredHardFieldReveal(event = {}, context = {}) {
  const fieldPath = normalizeEventFieldPath(event.fieldPath, event.changeType)
  const existingValue = cleanText(context.existingValue ?? readEntityField(context.existingEntity, fieldPath) ?? event.oldValue)
  const incomingValue = cleanText(resolveIncomingValue(event, fieldPath))
  const evidenceText = cleanText(event.evidence)
  return Boolean(existingValue) &&
    Boolean(incomingValue) &&
    RESERVATION_PATTERN.test(`${incomingValue} ${evidenceText}`) &&
    incomingValue.includes(existingValue)
}

function isAbilityCoreConflict(existingValue = '', incomingValue = '', evidence = '') {
  const oldText = cleanText(existingValue)
  const newText = cleanText(incomingValue)
  const combined = `${newText} ${cleanText(evidence)}`
  if (!oldText || !newText || oldText === newText) return false
  if (RESERVATION_PATTERN.test(combined)) return false
  if (oldText && newText.includes(oldText) && OBSERVED_CAPABILITY_PATTERN.test(combined)) return false
  if (CORE_RULE_PATTERN.test(oldText) && CORE_RULE_NEGATION_PATTERN.test(newText)) return true
  if (/只记录活人/.test(oldText) && /(记录死人|记录死者)/.test(newText)) return true
  if (/不能伪造|不能销毁/.test(oldText) && /(可以伪造|可以销毁)/.test(newText)) return true
  if (/必须.*代价|付出.*代价|代价.*不可逆/.test(oldText) && /(无需.*代价|没有代价|免代价|不再需要.*代价)/.test(newText)) return true
  return DIRECT_NEGATION_PATTERN.test(newText) && !OBSERVED_CAPABILITY_PATTERN.test(combined)
}

export function isRuleInstanceSummarySupplement(existingValue = '', incomingValue = '', evidence = '') {
  const oldText = cleanText(existingValue)
  const newText = cleanText(incomingValue)
  const combined = `${newText} ${cleanText(evidence)}`
  if (!oldText || !newText || oldText === newText) return false
  if (!CORE_RULE_PATTERN.test(oldText)) return false
  if (!RULE_INSTANCE_PATTERN.test(combined)) return false
  if (isCoreRuleRewrite(oldText, newText)) return false
  return newText.includes(oldText) || stripParentheticalSegments(newText) === oldText
}

export function isPlaceholderSummary(value = '') {
  const text = cleanText(value)
  if (!text) return true
  return PLACEHOLDER_SUMMARY_PATTERN.test(text)
}

export function isSummaryChapterFactSupplement(existingValue = '', incomingValue = '', evidence = '') {
  const oldText = cleanText(existingValue)
  const newText = cleanText(incomingValue)
  const combined = `${newText} ${cleanText(evidence)}`
  if (!oldText || !newText || oldText === newText) return false
  if (isPlaceholderSummary(oldText)) return false
  if (isHardSummaryRewrite(oldText, newText)) return false
  if (!SUMMARY_CHAPTER_FACT_PATTERN.test(combined)) return false
  return newText.includes(oldText) || oldSummaryAnchorPreserved(oldText, newText)
}

export function isDescriptivePlaceholderIdentityReveal(entityName = '', existingValue = '', incomingValue = '', evidence = '') {
  const name = cleanText(entityName)
  const oldText = cleanText(existingValue)
  const newText = cleanText(incomingValue)
  const combined = `${newText} ${cleanText(evidence)}`
  if (!name || !oldText || !newText || oldText === newText) return false
  if (!DESCRIPTIVE_PLACEHOLDER_NAME_PATTERN.test(name)) return false
  if (!UNCERTAIN_IDENTITY_PATTERN.test(oldText)) return false
  if (!FORMAL_IDENTITY_PATTERN.test(combined)) return false
  if (isHardSummaryRewrite(oldText, newText)) return false
  return true
}

export function isHardSummaryRewrite(existingValue = '', incomingValue = '') {
  const oldText = cleanText(existingValue)
  const newText = cleanText(incomingValue)
  if (!oldText || !newText) return false
  if (SUMMARY_IDENTITY_REWRITE_PATTERN.test(newText)) return true
  if (/(其实|并非|不是|不再是).{0,12}(商业联盟|商会|组织|机构|势力)/.test(newText)) return true
  if (/(星债会).{0,12}(伪装|分部)|(?:伪装|分部).{0,12}(星债会)/.test(newText)) return true
  if (OFFICIAL_ORG_PATTERN.test(oldText) && /(不是|并非|不再是).{0,12}(官方|朝廷|官署)|商盟.{0,8}分部|伪造.{0,8}(机构|官署)/.test(newText)) return true
  if (SECRET_ORG_PATTERN.test(oldText) && /(不再是|不是|并非).{0,8}秘密|公开官署|公开机构|正式登记/.test(newText)) return true
  if (PUBLIC_ORG_PATTERN.test(oldText) && /(秘密组织|隐秘组织|地下组织)/.test(newText) && DIRECT_NEGATION_PATTERN.test(newText)) return true
  return false
}

export function chooseSummaryChapterFactRehomeField(incomingValue = '', evidence = '') {
  const combined = `${cleanText(incomingValue)} ${cleanText(evidence)}`
  return SUMMARY_CURRENT_ACTION_PATTERN.test(combined)
    ? 'profile.currentActions'
    : SUMMARY_CHAPTER_FACT_REHOME_FIELD
}

export function isHardFieldBehaviorSupplement(fieldPath = '', existingValue = '', incomingValue = '', evidence = '') {
  const normalized = normalizeProfileFieldPath(fieldPath)
  const oldText = cleanText(existingValue)
  const newText = cleanText(incomingValue)
  const combined = `${newText} ${cleanText(evidence)}`
  if (!HARD_PROFILE_STABLE_FIELDS.has(normalized)) return false
  if (!oldText || !newText || oldText === newText) return false
  if (!HIDDEN_BEHAVIOR_PATTERN.test(combined)) return false
  return newText.includes(oldText) || stripParentheticalSegments(newText) === oldText
}

export function isOwnerPossessionRehomeChange(fieldPath = '', existingValue = '', incomingValue = '', evidence = '') {
  const normalized = normalizeProfileFieldPath(fieldPath)
  if (normalized !== 'profile.owner') return false
  const oldText = cleanText(existingValue)
  const newText = cleanText(incomingValue)
  const evidenceText = cleanText(evidence)
  if (!oldText || !newText || oldText === newText) return false
  if (hasStableOwnerTransferEvidence(oldText, newText, evidenceText)) return false
  const combinedNew = `${newText} ${evidenceText}`
  const oldIsUnstable = OWNER_UNSTABLE_OR_DYNAMIC_PATTERN.test(oldText)
  const newIsDynamic = OWNER_POSSESSION_ACTION_PATTERN.test(newText)
  const evidenceIsDynamic = OWNER_POSSESSION_ACTION_PATTERN.test(evidenceText) &&
    !OWNER_POSSESSION_NEGATION_PATTERN.test(evidenceText)
  return oldIsUnstable || newIsDynamic || evidenceIsDynamic
}

export function hasStableOwnerTransferEvidence(existingValue = '', incomingValue = '', evidence = '') {
  const combined = `${cleanText(existingValue)} ${cleanText(incomingValue)} ${cleanText(evidence)}`
  if (OWNER_TRANSFER_NEGATION_PATTERN.test(combined)) return false
  return OWNER_TRANSFER_PATTERN.test(combined)
}

function buildOwnerPossessionRehomeValue(existingValue = '', incomingValue = '', evidence = '') {
  const newText = cleanText(incomingValue)
  const oldText = cleanText(existingValue)
  const evidenceText = cleanText(evidence)
  const parts = []
  if (newText) parts.push(`当前持有/接触线索：${newText}`)
  if (oldText && OWNER_UNSTABLE_OR_DYNAMIC_PATTERN.test(oldText)) parts.push(`旧 owner 动态状态：${oldText}`)
  if (evidenceText) parts.push(`证据：${evidenceText}`)
  return parts.join('；')
}

function stableOwnerValueFromMixed(value = '') {
  const text = cleanText(value)
  if (!text) return ''
  const stripped = stripParentheticalSegments(text)
    .replace(/（[^）]*）|\([^)]*\)/g, '')
    .replace(/已接触|接触|未取出|取出|暂时|临时|当前|拿到|拿走|带走|携带|保管|藏在|收起|触碰|持有/g, '')
    .replace(/[，,；;、/]+$/g, '')
    .trim()
  if (!stripped || /^(未知|不明|疑似|可能|未确认)$/.test(stripped)) return '未知'
  if (/^(未知|不明)/.test(stripped)) return '未知'
  return stripped
}

function chooseHardFieldBehaviorRehomeField(incomingValue = '', evidence = '') {
  const combined = `${cleanText(incomingValue)} ${cleanText(evidence)}`
  return /(暗中|秘密|私下|表面|伪装|隐藏|卧底|内应)/.test(combined)
    ? HARD_FIELD_BEHAVIOR_REHOME_FIELD
    : 'profile.currentAction'
}

function oldSummaryAnchorPreserved(oldText = '', newText = '') {
  const incoming = cleanText(newText)
  return cleanText(oldText)
    .split(/[。；;，,]/)
    .map(part => cleanText(part))
    .filter(part => part.length >= 8 && !UNCERTAIN_SUMMARY_FRAGMENT_PATTERN.test(part))
    .some(anchor => incoming.includes(anchor))
}

function isCoreRuleRewrite(existingValue = '', incomingValue = '') {
  const oldText = cleanText(existingValue)
  const newText = cleanText(incomingValue)
  if (!oldText || !newText) return false
  if (CORE_RULE_PATTERN.test(oldText) && CORE_RULE_NEGATION_PATTERN.test(newText)) return true
  if (/只记录活人/.test(oldText) && /(记录死人|记录死者|死人代价|死者代价)/.test(newText)) return true
  if (/(不可复制|不能复制|不可被复制)/.test(oldText) && /(可以复制|可被复制|能够复制)/.test(newText)) return true
  if (/(必须.*代价|付出.*代价|每次使用.*代价)/.test(oldText) && /(无需.*代价|无须.*代价|不必.*代价|没有代价|免代价|不再需要.*代价)/.test(newText)) return true
  if (/不可逆/.test(oldText) && /(代价可逆|可以逆转|可逆转|可以恢复|可恢复)/.test(newText)) return true
  return false
}

function stripParentheticalSegments(text = '') {
  return cleanText(text).replace(/[（(][^（）()]*[）)]/g, '').replace(/\s+/g, ' ').trim()
}

function resolveIncomingValue(event = {}, fieldPath = '') {
  if (event.changeType !== 'new_entity') return event.newValue
  const payload = parseMaybeJson(event.newValue)
  if (!payload || typeof payload !== 'object') return event.newValue
  if (fieldPath.startsWith('profile.')) {
    const key = fieldPath.split('.', 2)[1]
    return payload.profile?.[key] ?? payload.profilePatch?.[key] ?? event.newValue
  }
  return payload[fieldPath] ?? payload.summary ?? event.newValue
}

function readEntityField(entity, fieldPath) {
  if (!entity || !fieldPath) return ''
  if (fieldPath.startsWith('profile.')) {
    const key = fieldPath.split('.', 2)[1]
    return entity.profile?.[key] ?? ''
  }
  return entity[fieldPath] ?? ''
}

function normalizeEventFieldPath(fieldPath, changeType) {
  const value = String(fieldPath || '').trim()
  if (value) return normalizeProfileFieldPath(value)
  return changeType === 'new_entity' ? 'summary' : 'notes'
}

function normalizeProfileFieldPath(fieldPath) {
  const value = String(fieldPath || '').trim()
  return HARD_FIELD_ALIASES[value] || value
}

function hardFieldCandidates(fieldPath) {
  const normalized = normalizeProfileFieldPath(fieldPath)
  const candidates = [normalized]
  if (normalized && !normalized.startsWith('profile.') && normalized !== 'summary' && normalized !== 'category' && normalized !== 'status') {
    candidates.push(`profile.${normalized}`)
  }
  return candidates
}

function fieldLabel(fieldPath) {
  const normalized = normalizeProfileFieldPath(fieldPath)
  return FIELD_LABELS[normalized] || FIELD_LABELS[fieldPath] || fieldPath
}

function parseMaybeJson(value) {
  if (!value) return null
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function cleanText(value) {
  if (value == null) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value).replace(/\s+/g, ' ').trim()
}

function settingEventConfirmationRank(event = {}) {
  const type = event.changeType || event.change_type || ''
  if (type === 'new_entity') return 0
  if (type === 'update_entity') return 1
  if (type === 'relationship') return 2
  return 1
}

function hasChapterDependency(entity = {}) {
  return Boolean(
    entity.firstChapter ||
    entity.first_chapter ||
    entity.lastChapter ||
    entity.last_chapter ||
    (Array.isArray(entity.chapterRefs) && entity.chapterRefs.length) ||
    (Array.isArray(entity.chapter_refs) && entity.chapter_refs.length)
  )
}

function normalizeList(value) {
  if (Array.isArray(value)) return value.map(item => String(item).trim()).filter(Boolean)
  const parsed = parseMaybeJson(value)
  if (Array.isArray(parsed)) return parsed.map(item => String(item).trim()).filter(Boolean)
  if (!value) return []
  return String(value)
    .split(/[\n,，、]/)
    .map(item => item.trim())
    .filter(Boolean)
}
