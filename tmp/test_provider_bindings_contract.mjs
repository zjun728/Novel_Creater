import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const providersRouter = readFileSync('backend/routers/providers.py', 'utf8')

const saveBlock = providersRouter.match(/async def save_bindings\([\s\S]*?return await get_bindings\(pid\)/)?.[0] || ''

assert.match(saveBlock, /data\.dict\(\)/, 'save_bindings should preserve explicit null values so mappings can be cleared')
assert.doesNotMatch(saveBlock, /exclude_none=True/, 'save_bindings must not drop null values')
assert.match(saveBlock, /if sets:/, 'save_bindings should avoid malformed UPDATE when there are no fields')

console.log('provider bindings contract tests passed')
