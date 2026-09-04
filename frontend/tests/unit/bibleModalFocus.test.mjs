import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { createModalFocusManager } from '../../src/components/common/modalFocusManager.js'

function element(name, documentRef) {
  return { name, isConnected: true, focus() { documentRef.activeElement = this }, hasAttribute: () => false, getAttribute: () => null, setAttribute() {}, removeAttribute() {} }
}

function appRoot({ inert = false, inertAttribute = null } = {}) {
  const attributes = new Map()
  if (inertAttribute !== null) attributes.set('inert', inertAttribute)
  return {
    inert,
    hasAttribute: name => attributes.has(name),
    getAttribute: name => attributes.get(name) ?? null,
    setAttribute: (name, value) => attributes.set(name, value),
    removeAttribute: name => attributes.delete(name),
  }
}

test('Bible modal focus manager makes app inert, traps both Tab directions, and restores trigger/inert', () => {
  const root = appRoot()
  const documentRef = { activeElement: null, querySelector: selector => selector === '#app' ? root : null }
  const trigger = element('trigger', documentRef); const first = element('first', documentRef); const last = element('last', documentRef)
  const dialog = { querySelectorAll: () => [first, last] }; documentRef.activeElement = trigger
  const manager = createModalFocusManager({ getDocument: () => documentRef, getDialog: () => dialog, getInitialFocus: () => first })
  manager.mount(); assert.equal(root.inert, true); assert.equal(documentRef.activeElement, first)
  documentRef.activeElement = last; manager.trapTab({ key: 'Tab', shiftKey: false, preventDefault() {} }); assert.equal(documentRef.activeElement, first)
  manager.trapTab({ key: 'Tab', shiftKey: true, preventDefault() {} }); assert.equal(documentRef.activeElement, last)
  manager.unmount(); assert.equal(root.inert, false); assert.equal(documentRef.activeElement, trigger)
})

test('nested modal managers keep the app inert and restore focus in LIFO order', () => {
  const root = appRoot(); const documentRef = { activeElement: null, querySelector: selector => selector === '#app' ? root : null }
  const pageTrigger = element('page-trigger', documentRef); const outerInitial = element('outer-initial', documentRef)
  const outerTrigger = element('outer-trigger', documentRef); const innerInitial = element('inner-initial', documentRef)
  const outer = createModalFocusManager({ getDocument: () => documentRef, getInitialFocus: () => outerInitial })
  const inner = createModalFocusManager({ getDocument: () => documentRef, getInitialFocus: () => innerInitial })
  documentRef.activeElement = pageTrigger; outer.mount()
  documentRef.activeElement = outerTrigger; inner.mount()
  inner.unmount()
  assert.equal(root.inert, true); assert.equal(documentRef.activeElement, outerTrigger)
  outer.unmount()
  assert.equal(root.inert, false); assert.equal(root.hasAttribute('inert'), false); assert.equal(documentRef.activeElement, pageTrigger)
})

test('non-LIFO modal close never steals focus or restores inert before the final close', () => {
  const root = appRoot(); const documentRef = { activeElement: null, querySelector: selector => selector === '#app' ? root : null }
  const pageTrigger = element('page-trigger', documentRef); const outerInitial = element('outer-initial', documentRef)
  const outerTrigger = element('outer-trigger', documentRef); const innerInitial = element('inner-initial', documentRef)
  const outer = createModalFocusManager({ getDocument: () => documentRef, getInitialFocus: () => outerInitial })
  const inner = createModalFocusManager({ getDocument: () => documentRef, getInitialFocus: () => innerInitial })
  documentRef.activeElement = pageTrigger; outer.mount()
  documentRef.activeElement = outerTrigger; inner.mount()
  outer.unmount()
  assert.equal(root.inert, true); assert.equal(documentRef.activeElement, innerInitial)
  inner.unmount()
  assert.equal(root.inert, false); assert.equal(documentRef.activeElement, pageTrigger)
})

test('the modal stack preserves pre-existing inert state and skips disconnected final targets', () => {
  const root = appRoot({ inert: true, inertAttribute: 'locked' }); const documentRef = { activeElement: null, querySelector: selector => selector === '#app' ? root : null }
  const disconnected = element('disconnected', documentRef); disconnected.isConnected = false
  const outerInitial = element('outer-initial', documentRef); const connectedFallback = element('connected-fallback', documentRef); const innerInitial = element('inner-initial', documentRef)
  const outer = createModalFocusManager({ getDocument: () => documentRef, getInitialFocus: () => outerInitial })
  const inner = createModalFocusManager({ getDocument: () => documentRef, getInitialFocus: () => innerInitial })
  documentRef.activeElement = disconnected; outer.mount()
  documentRef.activeElement = connectedFallback; inner.mount()
  outer.unmount(); inner.unmount()
  assert.equal(root.inert, true); assert.equal(root.getAttribute('inert'), 'locked'); assert.equal(documentRef.activeElement, connectedFallback)
})

test('a proposal review focus domain restores its author action after an independently scrolled review closes', () => {
  const root = appRoot(); const documentRef = { activeElement: null, querySelector: selector => selector === '#app' ? root : null }
  const proposalTrigger = element('proposal-trigger', documentRef); const reviewAction = element('review-action', documentRef)
  const review = { scrollTop: 360, querySelectorAll: () => [reviewAction] }
  documentRef.activeElement = proposalTrigger
  const manager = createModalFocusManager({ getDocument: () => documentRef, getDialog: () => review, getInitialFocus: () => reviewAction })
  manager.mount(); assert.equal(documentRef.activeElement, reviewAction); assert.equal(review.scrollTop, 360)
  manager.unmount(); assert.equal(documentRef.activeElement, proposalTrigger); assert.equal(root.inert, false)
})

test('foundation-owned modal surfaces explicitly restore the custom page scroller', async () => {
  const sources = await Promise.all([
    '../../src/components/foundation/FoundationConfirmationDialog.vue',
    '../../src/components/bible/BibleHistoryDrawer.vue',
  ].map(path => readFile(new URL(path, import.meta.url), 'utf8')))

  for (const source of sources) {
    assert.match(source, /#main-content/)
    assert.match(source, /scrollTop/)
    assert.match(source, /scrollLeft/)
    assert.match(source, /scrollTo\(\{\s*top:/)
    assert.match(source, /focusManager\.unmount\(\)[\s\S]*restorePageScroll\(\)/)
  }
})

test('the contract history drawer restores its own trigger and custom page scroll', async () => {
  const source = await readFile(new URL('../../src/components/project/contract/ContractHistoryDrawer.vue', import.meta.url), 'utf8')

  assert.match(source, /#main-content/)
  assert.match(source, /restoreTarget/)
  assert.match(source, /focus\?\.\(\{ preventScroll: true \}\)/)
  assert.match(source, /scrollTo\(\{\s*top:/)
})
