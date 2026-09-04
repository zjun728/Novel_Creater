import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'

import { createProjectBibleViteServer } from '../support/projectBibleViteServer.mjs'

const source = new URL('../../src/components/bible/BibleProposalReview.vue', import.meta.url)
const bible = suffix => ({
  premiseAndPromise: `promise ${suffix}`,
  powerOrProgressionSystem: `power ${suffix}`,
  protagonist: `hero ${suffix}`,
  toneAndNarrativeBoundaries: `tone ${suffix}`,
  worldRules: [{ id: 'world-1', text: `world ${suffix}` }],
  coreCast: [{ id: 'cast-1', text: `cast ${suffix}` }],
  factions: [{ id: 'faction-1', text: `faction ${suffix}` }],
  longTermConflicts: [{ id: 'conflict-1', text: `conflict ${suffix}` }],
  relationshipDynamics: [{ id: 'relationship-1', text: `relationship ${suffix}` }],
  continuityGuardrails: [{ id: 'guardrail-1', text: `guardrail ${suffix}` }],
  openDesignQuestions: [{ id: 'question-1', text: `question ${suffix}` }],
})

test('whole Bible proposal renders a compact ten-section before/after review with explicit decisions', async () => {
  const vite = await createProjectBibleViteServer()
  try {
    const Review = (await vite.ssrLoadModule('/src/components/bible/BibleProposalReview.vue')).default
    const html = await renderToString(createSSRApp({ render: () => h(Review, {
      open: true,
      snapshot: { scope: 'whole', scopeLabel: '完整创作圣经', authorInstructions: '增强因果', current: bible('修改前'), proposal: bible('建议后') },
    }) }))
    for (const label of ['作品承诺', '世界规则', '力量／成长体系', '主角与核心人物', '势力', '长期冲突', '关系动力', '基调与叙事边界', '连贯性护栏', '开放设计问题']) assert.match(html, new RegExp(label))
    assert.match(html, /修改前/); assert.match(html, /建议后/); assert.match(html, /作者要求/); assert.match(html, /增强因果/)
    assert.match(html, /采纳建议/); assert.match(html, /取消/); assert.doesNotMatch(html, /\{&quot;premiseAndPromise&quot;/)
  } finally { await vite.close() }
})

test('section Bible proposal renders only its mapped fields', async () => {
  const vite = await createProjectBibleViteServer()
  try {
    const Review = (await vite.ssrLoadModule('/src/components/bible/BibleProposalReview.vue')).default
    const html = await renderToString(createSSRApp({ render: () => h(Review, {
      open: true,
      snapshot: { scope: 'core_characters', scopeLabel: '主角与核心人物', authorInstructions: '', current: bible('修改前'), proposal: bible('建议后') },
    }) }))
    assert.match(html, /主角/); assert.match(html, /核心人物/); assert.match(html, /hero 修改前/); assert.match(html, /cast 建议后/)
    assert.doesNotMatch(html, /world 修改前|faction 建议后|question 建议后/)
  } finally { await vite.close() }
})

test('proposal review owns scrolling and restores page position and focus on close', async () => {
  const contents = await readFile(source, 'utf8')
  assert.match(contents, /createModalFocusManager/)
  assert.match(contents, /#main-content/)
  assert.match(contents, /scrollTop/)
  assert.match(contents, /scrollTo/)
  assert.match(contents, /preventScroll/)
  assert.match(contents, /overflow\s*:\s*auto/u)
})
