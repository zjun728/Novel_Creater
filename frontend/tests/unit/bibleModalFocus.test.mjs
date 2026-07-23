import assert from 'node:assert/strict'
import test from 'node:test'

import { createModalFocusManager } from '../../src/components/common/modalFocusManager.js'

function element(name, documentRef) {
  return { name, isConnected: true, focus() { documentRef.activeElement = this }, hasAttribute: () => false, getAttribute: () => null, setAttribute() {}, removeAttribute() {} }
}

test('Bible modal focus manager makes app inert, traps both Tab directions, and restores trigger/inert', () => {
  const documentRef = { activeElement: null, querySelector: selector => selector === '#app' ? appRoot : null }
  const appRoot = { inert: false, hasAttribute: () => false, getAttribute: () => null, setAttribute() {}, removeAttribute() {} }
  const trigger = element('trigger', documentRef); const first = element('first', documentRef); const last = element('last', documentRef)
  const dialog = { querySelectorAll: () => [first, last] }; documentRef.activeElement = trigger
  const manager = createModalFocusManager({ getDocument: () => documentRef, getDialog: () => dialog, getInitialFocus: () => first })
  manager.mount(); assert.equal(appRoot.inert, true); assert.equal(documentRef.activeElement, first)
  documentRef.activeElement = last; manager.trapTab({ key: 'Tab', shiftKey: false, preventDefault() {} }); assert.equal(documentRef.activeElement, first)
  manager.trapTab({ key: 'Tab', shiftKey: true, preventDefault() {} }); assert.equal(documentRef.activeElement, last)
  manager.unmount(); assert.equal(appRoot.inert, false); assert.equal(documentRef.activeElement, trigger)
})
