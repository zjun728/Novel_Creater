import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(liveScript, /const EXPECTED_PROVIDER_NAME = 'deepseek-v4-flash'/)
assert.match(liveScript, /const EXPECTED_MODEL_NAME = 'deepseek-v4-flash'/)
assert.match(liveScript, /expectedProviderName:\s*EXPECTED_PROVIDER_NAME/)
assert.match(liveScript, /expectedModelName:\s*EXPECTED_MODEL_NAME/)
assert.match(liveScript, /actualProviderModelMatched/)
assert.match(liveScript, /providerId/)
assert.match(liveScript, /modelName/)
assert.doesNotMatch(liveScript, /继承模型不是期望的联通云-DeepSeek-V4-Flash/)
assert.doesNotMatch(liveScript, /expectedProviderName:\s*'联通云-DeepSeek-V4-Flash'/)

console.log('live model expectation contract tests passed')
