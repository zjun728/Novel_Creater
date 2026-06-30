import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const chapterJs = readFileSync('frontend/src/prompts/chapter.js', 'utf8')

const forbiddenLocalHelpers = [
  'normalizeCatalogTitleText',
  'normalizeCatalogTitleCandidate',
  'stripTitleFragmentEdgePunctuation',
  'parseChapterTitleCandidates',
  'titleCharLength',
  'isCompleteSentenceLikeTitle',
  'countChapterTitleChars',
  'detectIllegalChapterTitleFragment',
  'normalizeChapterTitleKey',
  'collectExistingChapterTitleKeys',
  'isHardDialogueFragmentTitle',
  'isHardDirectionFragmentTitle',
  'inferChapterTitleType',
  'isAbstractStateLikeTitle',
  'isLabelPairLikeTitle',
  'isLikelyOralFragmentTitle',
  'isOralStateFragmentTitle',
  'isWeakDialogueQuestionTitle',
  'isWeakDirectionOrActionFragmentTitle',
  'isConcreteStateTitle',
  'isPlainSceneOrPersonPhrase',
  'isConcreteCatalogLabelTitle',
  'firstOccurrenceBonus',
  'scoreChapterTitleCandidate',
  'collectChapterTitleSource',
  'uniqueCatalogCandidates',
  'cleanExtractedTitleTerm',
  'collectQuotedTitleCandidates',
  'collectSimpleFallbackTitleCandidates',
  'inferPositiveChapterTitleType',
  'collectPositiveChapterTitleKeySet',
  'deriveSimpleFallbackChapterTitle'
]

for (const helper of forbiddenLocalHelpers) {
  assert.doesNotMatch(
    chapterJs,
    new RegExp(`function\\s+${helper}\\s*\\(`),
    `chapter.js must not keep local chapter-title helper ${helper}; delegate to frontend/src/domain/chapter-title`
  )
}

const forbiddenLocalConstants = [
  'TITLE_MOJIBAKE_PATTERN',
  'TITLE_INTERNAL_FIELD_PATTERN',
  'TITLE_LATIN_FRAGMENT_PATTERN',
  'TITLE_KEY_VALUE_FRAGMENT_PATTERN',
  'TITLE_JSON_OR_CODE_FRAGMENT_PATTERN',
  'HARD_DIALOGUE_FRAGMENT_TITLES',
  'HARD_DIRECTION_FRAGMENT_TITLES',
  'ROUTE_DISTANCE_QUESTION_PATTERN',
  'DIRECTION_PATH_QUESTION_PATTERN',
  'LOCATION_POINTER_FRAGMENT_PATTERN',
  'ORAL_JUDGMENT_FRAGMENT_TITLES',
  'SINGLE_ACTION_FRAGMENT_TITLES',
  'CHAPTER_TITLE_TYPE_PRIORITY',
  'SIMPLE_EVENT_TITLE_WORDS',
  'TITLE_STATE_TAILS',
  'ABSTRACT_TITLE_SUBJECT_PARTS',
  'PLACE_TITLE_TAILS',
  'ITEM_TITLE_TAILS',
  'SHORT_TITLE_PROPER_NOUNS',
  'ORAL_FRAGMENT_TITLES',
  'ORAL_STATE_FRAGMENT_TITLES'
]

for (const constant of forbiddenLocalConstants) {
  assert.doesNotMatch(
    chapterJs,
    new RegExp(`const\\s+${constant}\\b`),
    `chapter.js must not keep local chapter-title constant ${constant}; policy/ranking constants belong in the domain module`
  )
}

const allowedWrappers = [
  'isDefaultChapterTitle',
  'isChapterTitleDuplicate',
  'evaluateChapterTitlePolicy',
  'getChapterTitleQuality',
  'cleanGeneratedChapterTitle',
  'collectPositiveChapterTitleCandidates',
  'deriveFallbackChapterTitle'
]

for (const wrapper of allowedWrappers) {
  assert.match(
    chapterJs,
    new RegExp(`export\\s+function\\s+${wrapper}\\s*\\(`),
    `chapter.js should retain compatibility wrapper ${wrapper}`
  )
}

assert.match(
  chapterJs,
  /export\s+function\s+buildChapterTitleSystemPrompt\s*\(/,
  'chapter.js should retain the chapter-title system prompt builder'
)
assert.match(
  chapterJs,
  /export\s+function\s+buildChapterTitlePrompt\s*\(/,
  'chapter.js should retain the chapter-title user prompt builder'
)
assert.match(
  chapterJs,
  /export\s+function\s+formatChapterDisplayTitle\s*\(/,
  'chapter.js should retain display title formatting'
)

assert.match(
  chapterJs,
  /export\s+function\s+isChapterTitleDuplicate\s*\([^)]*\)\s*\{\s*return\s+isDomainChapterTitleDuplicate\s*\(/s,
  'isChapterTitleDuplicate wrapper must delegate directly to the domain module'
)
assert.match(
  chapterJs,
  /export\s+function\s+deriveFallbackChapterTitle\s*\([^)]*\)\s*\{\s*return\s+deriveDomainFallbackChapterTitle\s*\(/s,
  'deriveFallbackChapterTitle wrapper must delegate directly to the domain module'
)
assert.match(
  chapterJs,
  /export\s+function\s+cleanGeneratedChapterTitle\s*\([^)]*\)\s*\{\s*return\s+selectDomainGeneratedChapterTitle\s*\(/s,
  'cleanGeneratedChapterTitle wrapper must delegate directly to the domain module'
)
assert.match(
  chapterJs,
  /export\s+function\s+collectPositiveChapterTitleCandidates\s*\([^)]*\)\s*\{\s*return\s+collectChapterTitleMaterials\s*\(/s,
  'collectPositiveChapterTitleCandidates wrapper must delegate directly to the domain source extractor'
)

assert.doesNotMatch(
  chapterJs,
  /const\s+directTerms\s*=|PREFERRED_(?:PLACE|ITEM|PERSON_OR_ORG)_TITLES/,
  'chapter.js must not keep legacy hardcoded title fallback lists'
)

console.log('chapter title entrypoint cleanup contract passed')
