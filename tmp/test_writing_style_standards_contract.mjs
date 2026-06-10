import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = path => fs.readFileSync(path, 'utf8')

const standardsPath = 'frontend/src/data/writingStyleStandards.js'
assert.ok(fs.existsSync(standardsPath), 'writing style standards data module should exist')

const standardsSource = read(standardsPath)
const ids = [...standardsSource.matchAll(/^\s*id:\s*'([^']+)'/gm)].map(match => match[1])
assert.equal(ids.length, 14, 'standards module should expose 14 style/genre standards')
assert.ok(standardsSource.includes('formatWritingStyleStandardsForPrompt'), 'standards module should format prompt brief')
assert.ok(standardsSource.includes('normalizeWritingProfile'), 'standards module should normalize writingProfile')
assert.ok(standardsSource.includes('getAllWritingStyleStandards'), 'standards module should expose built-in plus custom standards')
assert.ok(standardsSource.includes('主写作标准'), 'standards module should use primary writing standard wording')
assert.ok(standardsSource.includes('辅助风味'), 'standards module should use secondary flavor wording')

const biblePrompt = read('frontend/src/prompts/bibleFromSeed.js')
assert.ok(biblePrompt.includes("'writingProfile'"), 'creative bible normalizer should keep writingProfile')
assert.ok(biblePrompt.includes('normalizeWritingProfilePayload'), 'creative bible normalizer should parse writingProfile')
assert.ok(!biblePrompt.includes('confirmedSettings'), 'creative bible normalizer should not keep legacy confirmedSettings')

const bibleUi = read('frontend/src/components/bible/CreativeBible.vue')
assert.ok(bibleUi.includes('NSelect'), 'creative bible editor should use select controls for standards')
assert.ok(bibleUi.includes('getAllWritingStyleStandards'), 'creative bible editor should list built-in plus confirmed custom standards')
assert.ok(!bibleUi.includes('WRITING_STYLE_STANDARDS.map'), 'creative bible editor should not hardcode built-in-only standards')
assert.ok(bibleUi.includes('主写作标准'), 'creative bible editor should expose primary writing standard')
assert.ok(bibleUi.includes('辅助风味'), 'creative bible editor should expose secondary flavor')
assert.ok(bibleUi.includes('写作策略'), 'creative bible viewer should expose writing strategy as a visible section')
assert.ok(bibleUi.includes('未选择主写作标准'), 'creative bible viewer should make missing writing standard visible')
assert.ok(bibleUi.includes('writingProfile'), 'creative bible editor should store writingProfile')
assert.ok(!bibleUi.includes('confirmedSettings'), 'creative bible editor should not store standards in confirmedSettings')

const writerView = read('frontend/src/views/WriterView.vue')
assert.ok(writerView.includes('chapter-title-line'), 'writer desk should render a dedicated chapter title line')
assert.ok(writerView.includes('currentChapterTitleOnly'), 'writer desk should expose chapter title separately from number and volume')

const projectView = read('frontend/src/views/ProjectView.vue')
assert.ok(projectView.includes('getSelectedWritingStyleStandards'), 'project header should expose selected writing strategy tags')
assert.ok(projectView.includes('project-chapter-title'), 'project chapter list should render full chapter title in a stable title area')

const contextBuilder = read('frontend/src/utils/contextBuilder.js')
assert.ok(contextBuilder.includes('formatWritingStyleStandardsForPrompt'), 'context builder should import style standard formatter')
assert.ok(contextBuilder.includes('styleStandardBrief'), 'writing context should expose selected style standard brief')
assert.ok(contextBuilder.includes('bible?.writingProfile'), 'context builder should read writingProfile')
assert.ok(!contextBuilder.includes('confirmedSettings'), 'context builder should not read legacy confirmedSettings')

const chapterPrompt = read('frontend/src/prompts/chapter.js')
assert.ok(chapterPrompt.includes('题材/风格标准'), 'chapter prompt should include style/genre standard section')

const auditPrompt = read('frontend/src/prompts/audit.js')
assert.ok(auditPrompt.includes('题材/风格标准'), 'audit prompt should include style/genre standard section')

const backendNovel = read('backend/routers/novel.py')
assert.ok(backendNovel.includes('writingProfile: Optional[Any]'), 'backend bible payload should accept object writingProfile')
assert.ok(!backendNovel.includes('confirmedSettings'), 'backend bible payload should not accept legacy confirmedSettings')
assert.ok(backendNovel.includes('isinstance(v, (list, dict))'), 'backend should persist dict/list JSON fields')

const schema = read('backend/schema.sql')
assert.ok(schema.includes('writing_profile JSON DEFAULT NULL'), 'schema should include writing_profile')
assert.ok(!schema.includes('confirmed_settings JSON'), 'schema should not define legacy confirmed_settings')

const helpers = read('backend/routers/helpers.py')
assert.ok(helpers.includes("'writing_profile'"), 'helper should decode writing_profile JSON')
assert.ok(!helpers.includes("'confirmed_settings'"), 'helper should not decode legacy confirmed_settings')
