export function createModalFocusManager({
  getDocument = () => globalThis.document,
  getDialog = () => null,
  getInitialFocus = () => null,
} = {}) {
  let appRoot = null
  let restoreTarget = null
  let previousInert = null

  function mount() {
    const documentRef = getDocument?.()
    if (!documentRef) return
    restoreTarget = documentRef.activeElement
    appRoot = documentRef.querySelector?.('#app') ?? null
    if (appRoot) {
      previousInert = {
        property: appRoot.inert,
        hadAttribute: appRoot.hasAttribute?.('inert') === true,
        attribute: appRoot.getAttribute?.('inert'),
      }
      appRoot.inert = true
      appRoot.setAttribute?.('inert', '')
    }
    getInitialFocus()?.focus?.()
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
    if (appRoot && previousInert) {
      appRoot.inert = previousInert.property
      if (previousInert.hadAttribute) appRoot.setAttribute?.('inert', previousInert.attribute ?? '')
      else appRoot.removeAttribute?.('inert')
    }
    if (restoreTarget?.isConnected !== false) restoreTarget?.focus?.()
    appRoot = null; restoreTarget = null; previousInert = null
  }

  return { mount, trapTab, unmount }
}
