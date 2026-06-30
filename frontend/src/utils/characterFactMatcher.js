function parseList(value) {
  if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean)
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text) return []
    try {
      const parsed = JSON.parse(text)
      if (Array.isArray(parsed)) return parsed.map(item => String(item || '').trim()).filter(Boolean)
    } catch {}
    return text.split(/[，,；;]/).map(item => item.trim()).filter(Boolean)
  }
  return []
}

function parseObject(value) {
  if (!value) return {}
  if (typeof value === 'object' && !Array.isArray(value)) return value
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value)
      return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
    } catch {}
  }
  return {}
}

export function normalizeCharacterName(value = '') {
  return String(value || '')
    .trim()
    .replace(/^[#＃]+/, '')
    .replace(/[「」《》【】\[\]\s]/g, '')
    .replace(/[（(].*?[）)]/g, '')
    .replace(/[：:、，,。；;]+$/g, '')
}

function sameCharacterName(a = '', b = '') {
  const left = normalizeCharacterName(a)
  const right = normalizeCharacterName(b)
  if (!left || !right) return false
  if (left === right) return true
  if (left.length >= 2 && right.includes(left)) return true
  if (right.length >= 2 && left.includes(right)) return true
  return false
}

function relatedCharacterValues(fact = {}) {
  return parseList(fact.relatedCharacters || fact.related_characters || fact.characters || fact.roles)
}

function canonicalCharacterValues(fact = {}) {
  return parseList(fact.canonicalCharacters || fact.canonical_characters || fact.canonicalCharacterNames)
}

function profileOf(entity = {}) {
  return parseObject(entity.profile)
}

function personasOf(entity = {}) {
  const raw = profileOf(entity).personas || entity.personas || []
  const list = Array.isArray(raw) ? raw : parseList(raw)
  return list
    .map(item => typeof item === 'string' ? { name: item, type: 'alias' } : item)
    .filter(item => item?.name)
}

function canonicalNameOf(entity = {}) {
  const profile = profileOf(entity)
  return normalizeCharacterName(profile.canonicalName || entity.canonicalName || entity.name)
}

export function buildCharacterAliasIndex(characters = [], settingEntities = []) {
  const byCharacterId = new Map()
  const byNormalizedName = new Map()

  function addAlias(character, alias) {
    const normalized = normalizeCharacterName(alias)
    if (!character || !normalized) return
    byNormalizedName.set(normalized, character.id || character.name)
  }

  for (const character of characters || []) {
    byCharacterId.set(character.id, character)
    addAlias(character, character.name)
    addAlias(character, character.canonicalName)
    for (const alias of parseList(character.aliases || character.alias || [])) {
      addAlias(character, alias)
    }
    for (const persona of personasOf(character)) {
      addAlias(character, persona.name)
    }
  }

  for (const entity of settingEntities || []) {
    const type = entity.entityType || entity.entity_type
    if (type && type !== 'character') continue
    const profile = profileOf(entity)
    const canonicalName = normalizeCharacterName(profile.canonicalName || entity.canonicalName || entity.name)
    const matched = (characters || []).find(character =>
      sameCharacterName(character.canonicalName || character.name, canonicalName) ||
      sameCharacterName(character.name, entity.name) ||
      parseList(character.aliases || character.alias || []).some(alias => sameCharacterName(alias, entity.name))
    )
    if (!matched) continue
    addAlias(matched, canonicalName)
    addAlias(matched, entity.name)
    for (const alias of parseList(entity.aliases || entity.alias || [])) {
      addAlias(matched, alias)
    }
    for (const persona of personasOf(entity)) {
      addAlias(matched, persona.name)
    }
  }

  return { byCharacterId, byNormalizedName }
}

export function buildCanonicalCharacterRows(characters = [], settingEntities = []) {
  const rowsByName = new Map()

  function ensureRow(canonicalName, source = {}) {
    const clean = normalizeCharacterName(canonicalName || source.name)
    if (!clean) return null
    if (!rowsByName.has(clean)) {
      rowsByName.set(clean, {
        id: `canonical:${clean}`,
        canonicalName: clean,
        name: clean,
        role: source.role || 'supporting',
        aliases: [],
        personas: [],
        sourceCharacters: [],
        sourceCharacterIds: [],
        sourceEntityIds: [],
        hardState: source.hardState || source.hard_state || {},
        softState: source.softState || source.soft_state || {}
      })
    }
    return rowsByName.get(clean)
  }

  function pushUnique(list, value) {
    const text = typeof value === 'string' ? value : value?.name
    if (!text) return
    if (!list.some(item => (typeof item === 'string' ? item : item?.name) === text)) list.push(value)
  }

  function mergeRows(target, source) {
    if (!target || !source || target === source) return
    for (const alias of source.aliases || []) pushUnique(target.aliases, alias)
    for (const persona of source.personas || []) {
      pushUnique(target.aliases, persona.name)
      pushUnique(target.personas, persona)
    }
    for (const sourceCharacter of source.sourceCharacters || []) pushUnique(target.sourceCharacters, sourceCharacter)
    for (const id of source.sourceCharacterIds || []) pushUnique(target.sourceCharacterIds ||= [], id)
    for (const id of source.sourceEntityIds || []) pushUnique(target.sourceEntityIds ||= [], id)
    for (const claim of source.identityClaims || []) pushUnique(target.identityClaims ||= [], claim)
    for (const mistake of source.mistakenIdentities || []) pushUnique(target.mistakenIdentities ||= [], mistake)
    for (const reveal of source.identityReveals || []) pushUnique(target.identityReveals ||= [], reveal)
  }

  function rowIdentityNames(row) {
    const names = new Set([row.canonicalName, row.name].map(normalizeCharacterName).filter(Boolean))
    for (const alias of row.aliases || []) names.add(normalizeCharacterName(alias))
    for (const persona of row.personas || []) names.add(normalizeCharacterName(persona?.name))
    return [...names].filter(Boolean)
  }

  for (const character of characters || []) {
    const row = ensureRow(character.canonicalName || character.name, character)
    if (!row) continue
    row.sourceCharacters.push(character)
    pushUnique(row.sourceCharacterIds, character.id)
    pushUnique(row.aliases, character.name)
    for (const alias of parseList(character.aliases || character.alias || [])) pushUnique(row.aliases, alias)
  }

  for (const entity of settingEntities || []) {
    const type = entity.entityType || entity.entity_type
    if (type && type !== 'character') continue
    const profile = profileOf(entity)
    const row = ensureRow(profile.canonicalName || entity.canonicalName || entity.name, entity)
    if (!row) continue
    pushUnique(row.sourceEntityIds, entity.id)
    pushUnique(row.aliases, entity.name)
    for (const alias of parseList(entity.aliases || entity.alias || [])) pushUnique(row.aliases, alias)
    for (const persona of personasOf(entity)) {
      pushUnique(row.aliases, persona.name)
      pushUnique(row.personas, persona)
    }
    row.identityClaims = profile.identityClaims || row.identityClaims || []
    row.mistakenIdentities = profile.mistakenIdentities || row.mistakenIdentities || []
    row.identityReveals = profile.identityReveals || row.identityReveals || []
  }

  let merged = true
  while (merged) {
    merged = false
    const rows = [...rowsByName.entries()]
    for (const [name, row] of rows) {
      if (!rowsByName.has(name)) continue
      const targetEntry = rows.find(([targetName, target]) =>
        targetName !== name &&
        rowsByName.has(targetName) &&
        rowIdentityNames(target).some(alias => sameCharacterName(alias, name))
      )
      if (!targetEntry) continue
      mergeRows(targetEntry[1], row)
      rowsByName.delete(name)
      merged = true
      break
    }
  }

  return [...rowsByName.values()].sort((a, b) => String(a.name).localeCompare(String(b.name), 'zh-Hans-CN'))
}

export function factMatchesCharacter(fact = {}, character = {}, aliasIndex = buildCharacterAliasIndex([character])) {
  const canonicalValues = canonicalCharacterValues(fact)
  if (canonicalValues.some(value =>
    sameCharacterName(value, character.canonicalName || character.name) ||
    (character.id && value === character.id) ||
    (character.sourceEntityIds || []).includes(value) ||
    (character.sourceCharacterIds || []).includes(value)
  )) return true
  const related = relatedCharacterValues(fact)
  if (!related.length) return false
  if (character.id && related.includes(character.id)) return true
  const target = character.id || character.name
  return related.some(value => {
    const normalized = normalizeCharacterName(value)
    return aliasIndex.byNormalizedName.get(normalized) === target ||
      sameCharacterName(normalized, character.name)
  })
}

export function characterFactsForChapter(character, chapter, canonFacts = [], aliasIndex) {
  const chapterNum = Number(chapter?.chapterNum || chapter?.chapter_num || 0)
  return (canonFacts || []).filter(fact =>
    Number(fact.chapterNum || fact.chapter_num || 0) === chapterNum &&
    factMatchesCharacter(fact, character, aliasIndex)
  )
}

export function summarizeCharacterFactCoverage({ characters = [], settingEntities = [], canonFacts = [] } = {}) {
  const aliasIndex = buildCharacterAliasIndex(characters, settingEntities)
  let idHitCount = 0
  let nameAliasHitCount = 0
  const characterCoverage = (characters || []).map(character => {
    const chapters = new Set()
    let factCount = 0
    for (const fact of canonFacts || []) {
      const related = relatedCharacterValues(fact)
      const canonical = canonicalCharacterValues(fact)
      const idHit = Boolean(character.id && related.includes(character.id))
      const canonicalHit = canonical.some(value =>
        sameCharacterName(value, character.canonicalName || character.name) ||
        (character.id && value === character.id) ||
        (character.sourceEntityIds || []).includes(value) ||
        (character.sourceCharacterIds || []).includes(value)
      )
      const nameAliasHit = canonicalHit || related.some(value => {
        const normalized = normalizeCharacterName(value)
        return aliasIndex.byNormalizedName.get(normalized) === (character.id || character.name) ||
          aliasIndex.byNormalizedName.get(normalized) === character.id ||
          sameCharacterName(normalized, character.canonicalName || character.name)
      })
      if (idHit) idHitCount += 1
      if (!idHit && nameAliasHit) nameAliasHitCount += 1
      if (idHit || nameAliasHit) {
        factCount += 1
        const chapterNum = Number(fact.chapterNum || fact.chapter_num || 0)
        if (chapterNum) chapters.add(chapterNum)
      }
    }
    return {
      id: character.id,
      name: character.name,
      canonicalName: character.canonicalName || character.name,
      factCount,
      coverageChapterCount: chapters.size,
      chapters: [...chapters].sort((a, b) => a - b)
    }
  })

  return {
    idHitCount,
    nameAliasHitCount,
    characterCoverage
  }
}

export function buildIdentityKnowledgeNote(entity = {}, viewerNames = ['陆沉舟']) {
  const profile = profileOf(entity)
  const canonicalName = profile.canonicalName || entity.canonicalName || entity.name
  const personas = personasOf(entity)
  const notes = []
  for (const persona of personas) {
    const knownBy = parseList(persona.knownBy || persona.known_by)
    const viewerKnown = viewerNames.some(name => knownBy.includes(name))
    if (!viewerKnown && persona.status !== 'false') {
      notes.push(`${persona.name}：系统身份指向 ${canonicalName}，${viewerNames[0] || '主角'}未知；已知者：${knownBy.join('、') || '未标注'}`)
    } else {
      notes.push(`${persona.name}：已揭示为 ${canonicalName}`)
    }
  }
  return notes.join('；')
}
