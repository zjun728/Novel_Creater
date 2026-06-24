import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const presets = readFileSync('frontend/src/api/ai/providerPresets.js', 'utf8')

const deepseekPreset = presets.match(/\{\s*name:\s*'deepseek-v4-flash'[\s\S]*?model:\s*'deepseek-v4-flash'[\s\S]*?\}/)

assert.ok(deepseekPreset, 'DeepSeek provider preset should display the current default provider/model deepseek-v4-flash / deepseek-v4-flash')
assert.doesNotMatch(presets, /model:\s*'deepseek-v4-pro'/, 'Provider presets should not default new settings to deepseek-v4-pro')

console.log('provider preset default contract tests passed')
