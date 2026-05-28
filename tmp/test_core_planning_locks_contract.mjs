import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const seedsRouter = readFileSync('backend/routers/seeds.py', 'utf8')
const novelRouter = readFileSync('backend/routers/novel.py', 'utf8')
const settingsRouter = readFileSync('backend/routers/settings_library.py', 'utf8')
const marketStore = readFileSync('frontend/src/stores/marketStore.js', 'utf8')
const creativeBible = readFileSync('frontend/src/components/bible/CreativeBible.vue', 'utf8')

for (const fnName of ['create_seed', 'update_seed', 'delete_seed', 'clear_seeds']) {
  const match = seedsRouter.match(new RegExp(`async def ${fnName}\\([\\s\\S]*?(?:\\n\\n|$)`))
  assert.ok(match, `missing ${fnName}`)
  assert.match(match[0], /ensure_project_without_chapter_content\(pid/, `${fnName} must block after chapter content exists`)
}

const deleteBible = novelRouter.match(/async def delete_bible\([\s\S]*?(?:\n\n|$)/)?.[0] || ''
assert.match(deleteBible, /ensure_project_without_chapter_content\(pid/, 'delete_bible must block after chapter content exists')

for (const fnName of ['delete_setting_entity', 'clear_setting_library', 'delete_setting_relation']) {
  const match = settingsRouter.match(new RegExp(`async def ${fnName}\\([\\s\\S]*?(?:\\n\\n|$)`))
  assert.ok(match, `missing ${fnName}`)
  assert.match(match[0], /ensure_project_without_chapter_content\(pid/, `${fnName} must block destructive deletion after chapter content exists`)
}

assert.match(marketStore, /ensureSeedPlanningMutableForChat/)
assert.match(marketStore, /api\.projects\.contentState\(projectId\)/)
assert.match(marketStore, /seedMutationAllowed/)

const initializeBlock = creativeBible.match(/async function handleInitializeSettings\(\) \{[\s\S]*?\n\}/)?.[0] || ''
assert.match(initializeBlock, /api\.projects\.contentState\(props\.projectId\)/)
assert.match(initializeBlock, /state\.hasChapterContent/)

console.log('core planning locks contract tests passed')
