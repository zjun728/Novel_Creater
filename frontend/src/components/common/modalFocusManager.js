const modalStacks = new WeakMap()

function restoreInert(appRoot, snapshot) {
  appRoot.inert = snapshot.property
  if (snapshot.hadAttribute) appRoot.setAttribute?.('inert', snapshot.attribute ?? '')
  else appRoot.removeAttribute?.('inert')
}

function connected(target) {
  return target && target.isConnected !== false
}

export function createModalFocusManager({
  getDocument = () => globalThis.document,
  getDialog = () => null,
  getInitialFocus = () => null,
} = {}) {
  let appRoot = null
  let entry = null
  let standaloneRestoreTarget = null

  function mount() {
    if (entry || standaloneRestoreTarget) return
    const documentRef = getDocument?.()
    if (!documentRef) return
    const restoreTarget = documentRef.activeElement
    appRoot = documentRef.querySelector?.('#app') ?? null
    if (appRoot) {
      let stack = modalStacks.get(appRoot)
      if (!stack) {
        stack = {
          originalInert: {
            property: appRoot.inert,
            hadAttribute: appRoot.hasAttribute?.('inert') === true,
            attribute: appRoot.getAttribute?.('inert'),
          },
          entries: [],
          restoreCandidates: [],
        }
        modalStacks.set(appRoot, stack)
      }
      entry = { restoreTarget, initialTarget: getInitialFocus?.() ?? null }
      stack.entries.push(entry)
      stack.restoreCandidates.push(restoreTarget)
      appRoot.inert = true
      appRoot.setAttribute?.('inert', '')
    } else {
      standaloneRestoreTarget = restoreTarget
    }
    (entry?.initialTarget ?? getInitialFocus?.())?.focus?.()
  }

  function trapTab(event) {
    if (event?.key !== 'Tab') return false
    const focusable = Array.from(getDialog()?.querySelectorAll?.(
      'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    ) ?? [])
    if (!focusable.length) return false
    const first = focusable[0]; const last = focusable[focusable.length - 1]
    const active = getDocument?.()?.activeElement
    let destination = null
    if (event.shiftKey && active === first) destination = last
    else if (!event.shiftKey && active === last) destination = first
    else if (!focusable.includes(active)) destination = event.shiftKey ? last : first
    if (!destination) return false
    event.preventDefault?.(); destination.focus?.()
    return true
  }

  function unmount() {
    if (appRoot && entry) {
      const stack = modalStacks.get(appRoot)
      const index = stack?.entries.indexOf(entry) ?? -1
      const wasTop = stack && index === stack.entries.length - 1
      if (stack && index >= 0) stack.entries.splice(index, 1)
      if (stack?.entries.length) {
        appRoot.inert = true
        appRoot.setAttribute?.('inert', '')
        if (wasTop) {
          const destination = connected(entry.restoreTarget)
            ? entry.restoreTarget
            : stack.entries.at(-1)?.initialTarget
          if (connected(destination)) destination.focus?.()
        }
      } else if (stack) {
        restoreInert(appRoot, stack.originalInert)
        modalStacks.delete(appRoot)
        stack.restoreCandidates.find(connected)?.focus?.()
      }
    } else if (connected(standaloneRestoreTarget)) {
      standaloneRestoreTarget.focus?.()
    }
    appRoot = null; entry = null; standaloneRestoreTarget = null
  }

  return { mount, trapTab, unmount }
}
