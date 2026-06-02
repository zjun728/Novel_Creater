import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const root = process.cwd()
const read = file => fs.readFileSync(path.join(root, file), 'utf8')
const exists = file => fs.existsSync(path.join(root, file))

const database = read('backend/database.py')
const novelRouter = read('backend/routers/novel.py')
const outlinePrompt = read('frontend/src/prompts/outline.js')
const novelStore = read('frontend/src/stores/novelStore.js')
const contextBuilder = read('frontend/src/utils/contextBuilder.js')
const volumePlanner = read('frontend/src/components/chapter/VolumePlanner.vue')

assert.match(
  database,
  /CREATE TABLE IF NOT EXISTS rolling_outlines/,
  'ensure_schema must create rolling_outlines for older local databases'
)

assert.match(
  novelRouter,
  /async def save_outline[\s\S]*await touch_project\(pid\)/,
  'saving rolling outline should refresh project updatedAt'
)

assert.match(
  outlinePrompt,
  /nearChapters/,
  'outline prompt should require near-term rolling planning'
)
assert.match(
  outlinePrompt,
  /farVision/,
  'outline prompt should require a longline blueprint payload'
)
assert.match(
  outlinePrompt,
  /3-5/,
  'outline prompt should constrain nearChapters to the next 3-5 chapters'
)
assert.match(
  outlinePrompt,
  /futureVolumes/,
  'longline blueprint should stay coarse and not become detailed chapter planning'
)

assert.match(
  novelStore,
  /async function generateOutline/,
  'novelStore should expose an AI generation method for rolling planning'
)
assert.match(
  novelStore,
  /generateOutline,/,
  'generateOutline should be returned from novelStore'
)

assert.match(
  contextBuilder,
  /builder\.add\('nearOutline'/,
  'near-term rolling plan must be injected into writing context'
)
assert.doesNotMatch(
  contextBuilder,
  /builder\.add\('farVision'/,
  'longline blueprint should not be injected into every chapter generation context'
)

assert.ok(
  exists('frontend/src/components/chapter/RollingPlanningPanel.vue'),
  'chapter planning UI should include RollingPlanningPanel.vue'
)
assert.match(
  volumePlanner,
  /RollingPlanningPanel/,
  'VolumePlanner should render the rolling planning panel'
)

console.log('rolling planning contract checks passed')
