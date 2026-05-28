import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const settingsRouter = readFileSync('backend/routers/settings_library.py', 'utf8')

assert.match(settingsRouter, /SYSTEM_ENTITY_STATUSES/, 'backend should define allowed system entity statuses')
assert.match(settingsRouter, /STORY_STATE_PROFILE_PATH/, 'backend should redirect narrative status text into profile current state')
assert.match(settingsRouter, /field_path == "status"/, 'backend should special-case status field path')
assert.match(settingsRouter, /profile\[STORY_STATE_PROFILE_PATH\]/, 'narrative status changes should update profile current state')

console.log('setting event status field contract OK')
