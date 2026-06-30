import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const presets = readFileSync('frontend/src/api/ai/providerPresets.js', 'utf8')

const deepseekPreset = presets.match(/\{\s*name:\s*'联通云-DeepSeek-V4-Flash'[\s\S]*?model:\s*'DeepSeek-V4-Flash'[\s\S]*?\}/)

assert.ok(deepseekPreset, 'DeepSeek provider preset should display the current default provider/model 联通云-DeepSeek-V4-Flash / DeepSeek-V4-Flash')
assert.doesNotMatch(presets, /model:\s*'deepseek-v4-pro'/, 'Provider presets should not default new settings to deepseek-v4-pro')

console.log('provider preset default contract tests passed')
