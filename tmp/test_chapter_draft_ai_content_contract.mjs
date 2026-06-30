import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const repoRoot = process.cwd()
const modulePath = path.join(repoRoot, 'frontend/src/domain/chapter-draft/ai-content.js')
const writerStorePath = path.join(repoRoot, 'frontend/src/stores/writerStore.js')
const { extractAiContent } = await import(pathToFileURL(modulePath).href)

assert.equal(extractAiContent('正文'), '正文')
assert.equal(extractAiContent({ content: '对象正文' }), '对象正文')
assert.equal(extractAiContent({ content: '' }), '')
assert.equal(extractAiContent({ choices: [{ message: { content: 'message 正文' } }] }), 'message 正文')
assert.equal(extractAiContent({ choices: [{ text: 'choice text 正文' }] }), 'choice text 正文')
assert.equal(extractAiContent({ foo: 'bar' }), '{"foo":"bar"}')
assert.equal(extractAiContent(null), '')
assert.equal(extractAiContent(undefined), '')
assert.equal(
  extractAiContent({ content: '', choices: [{ message: { content: 'fallback choice' } }] }),
  '',
)
assert.equal(
  extractAiContent(
    { content: '', choices: [{ message: { content: 'fallback choice' } }] },
    { preferOwnContent: false },
  ),
  'fallback choice',
)
const unknownPayload = { unexpected: true }
assert.equal(extractAiContent(unknownPayload, { stringifyUnknown: false }), unknownPayload)
assert.equal(extractAiContent(unknownPayload, { unknownFallback: '' }), '')

const moduleSource = fs.readFileSync(modulePath, 'utf8')
const forbidden = [
  /from ['"]vue['"]/,
  /pinia/,
  /stores\//,
  /api\//,
  /router/,
  /naive/i,
  /prompts\//,
  /chatCompletion/,
  /localStorage|sessionStorage/,
  /\bwindow\b|\bdocument\b/,
]
for (const pattern of forbidden) {
  assert.equal(pattern.test(moduleSource), false, `ai-content helper must stay pure: ${pattern}`)
}

const writerStoreSource = fs.readFileSync(writerStorePath, 'utf8')
assert.match(writerStoreSource, /@\/domain\/chapter-draft\/ai-content/)
assert.doesNotMatch(
  writerStoreSource,
  /function extractAiContent\s*\(/,
  'writerStore should import extractAiContent instead of defining it inline',
)
assert.doesNotMatch(
  writerStoreSource,
  /if \(typeof result === 'string'\)/,
  'writerStore should use extractAiContent instead of local result string branches',
)
assert.doesNotMatch(
  writerStoreSource,
  /result\?\.content\) (?:content = result\.content|return result\.content)/,
  'writerStore should use extractAiContent instead of local result.content branches',
)

console.log('chapter draft ai content contract passed')
