import assert from 'node:assert/strict'
import test from 'node:test'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as Vue from 'vue'
import * as helpers from '../../src/application/writer/addCanonFact.js'

const prose = '  首😀段。\r\n\r\n中间段。\r\n\r\n末𠮷段。\n'
const hash = value => createHash('sha256').update(value).digest('hex')
const input = () => ({ candidateContent: prose, chapterNumber: 1, value: '人物烧毁旧鞋。', startId: 'p1', endId: 'p3' })

test('source paragraph offsets preserve Unicode scalars, CRLF and absolute final newline', () => {
  assert.deepEqual(helpers.candidateSourceParagraphs(prose), [
    { id: 'p1', text: '首😀段。', startScalar: 2, endScalar: 6 },
    { id: 'p2', text: '中间段。', startScalar: 10, endScalar: 14 },
    { id: 'p3', text: '末𠮷段。\n', startScalar: 18, endScalar: 23 },
  ])
  const selected = helpers.authorFactEvidenceRange(prose, 'p1', 'p3')
  assert.equal(selected.excerpt, prose.slice(2))
  assert.equal(helpers.authorFactEvidenceRange(prose, 'p2', 'p2').excerpt, '中间段。')
  for (const [start, end] of [['p3', 'p1'], ['p0', 'p1'], ['p1', 'p9'], ['', '']]) {
    assert.throws(() => helpers.authorFactEvidenceRange(prose, start, end))
  }
  assert.throws(() => helpers.candidateSourceParagraphs('\ud800'))
})

test('author fact is a complete multi-value event with a hash of the untouched interval', async () => {
  const result = await helpers.buildAuthorCanonFact(input(), { idFactory: () => 'author-fact-1' })
  assert.deepEqual(result, {
    id: 'author-fact-1', entityId: null, factKind: 'dynamic_event', fieldPath: 'author.observation',
    value: '人物烧毁旧鞋。', effectiveStartChapter: 1, effectiveEndChapter: null,
    assertionOperator: 'equals', valueCardinality: 'multi',
    evidence: { startScalar: 2, endScalar: 23, excerptHash: hash(prose.slice(2)), confidence: 1, rationale: '作者对照原文补录' },
  })
  const linked = await helpers.buildAuthorCanonFact({ ...input(), entityId: 'known', entities: [{ id: 'known' }], factKind: 'claim' })
  assert.equal(linked.entityId, 'known'); assert.equal(linked.factKind, 'claim')
  assert.match(linked.id, /^[0-9a-f-]{36}$/u)
})

test('invalid or unauthorized input cannot produce an event', async () => {
  for (const damage of [
    { chapterNumber: 0 }, { chapterNumber: 1.5 }, { candidateContent: '' }, { value: ' ' },
    { value: '文'.repeat(4001) }, { fieldPath: '' }, { fieldPath: 'plot.progress.scene_task.x' },
    { fieldPath: 'x'.repeat(201) }, { factKind: 'unknown' }, { entityId: 'missing' },
    { startId: 'p3', endId: 'p1' },
  ]) await assert.rejects(helpers.buildAuthorCanonFact({ ...input(), ...damage }))
  await assert.rejects(helpers.buildAuthorCanonFact(input(), { hashText: async () => 'invalid' }))
})

async function mountEditor(overrides = {}, build = helpers.buildAuthorCanonFact) {
  const source = await readFile(new URL('../../src/components/writer/AddCanonFactEditor.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  let script = compileScript(descriptor, { id: 'author-fact-test' }).content
  script = script.replace(/import \{([^}]+)\} from 'vue'/u, (_all, names) => `const {${names}} = Vue`)
  script = script.replace(/import \{([^}]+)\} from '[^']+addCanonFact.js'/u, (_all, names) => `const {${names}} = helpers`)
  script = script.replace('export default', 'return')
  const Component = new Function('Vue', 'helpers', script)(Vue, { ...helpers, buildAuthorCanonFact: build })
  Component.render = () => null
  const props = Vue.reactive({ candidateContent: prose, chapterNumber: 1, entities: [], disabled: false, ...overrides })
  const added = []; const dirty = []; let editor
  const renderer = Vue.createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode: () => null, nextSibling: () => null })
  const app = renderer.createApp({ render: () => Vue.h(Component, { ...props, ref: value => { editor = value?.$?.setupState }, onAdd: value => added.push(value), 'onDirty-change': value => dirty.push(value) }) })
  app.mount({})
  await Vue.nextTick()
  return { props, editor, added, dirty, close: () => app.unmount() }
}

test('editor emits complete events, tracks unsaved input and blocks disabled handler calls', async () => {
  const mounted = await mountEditor()
  try {
    mounted.editor.value = '有原文支持的事实'
    await Vue.nextTick()
    assert.equal(mounted.dirty.at(-1), true)
    mounted.props.disabled = true; await Vue.nextTick()
    await mounted.editor.addFact(); assert.equal(mounted.added.length, 0)
    mounted.props.disabled = false; await Vue.nextTick()
    await mounted.editor.addFact()
    assert.equal(mounted.added.length, 1)
    assert.equal(mounted.added[0].value, '有原文支持的事实')
    assert.equal(mounted.dirty.at(-1), false)
  } finally { mounted.close() }
})

test('candidate changes while hashing fence stale add output', async () => {
  let complete
  const waiting = new Promise(resolve => { complete = resolve })
  const mounted = await mountEditor({}, async () => waiting)
  try {
    mounted.editor.value = '旧候选事实'
    const add = mounted.editor.addFact()
    mounted.props.candidateContent = '新的候选原文'; await Vue.nextTick()
    complete({ id: 'stale' }); await add
    assert.deepEqual(mounted.added, [])
    assert.equal(mounted.dirty.at(-1), false)
  } finally { mounted.close() }
})
