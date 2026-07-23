import assert from 'node:assert/strict'
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
