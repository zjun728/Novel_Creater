const STATE_KEY = 'manuscriptView'
export const MANUSCRIPT_HISTORY_CONTEXT = Symbol('manuscript-history-context')

function routeKey(route) {
  return String(route?.fullPath || route?.path || '')
}

function routeDocumentKey(value) {
  return String(value || '').split(/[?#]/u, 1)[0]
}

function routeIdentity(route) {
  const projectId = String(route?.params?.projectId || '')
  const chapter = route?.params?.chapterNumber == null
    ? 'index'
    : String(route.params.chapterNumber)
  return `${projectId}:${chapter}`
}

function isManuscriptRoute(route) {
  return ['ProjectManuscript', 'FinalChapterReader'].includes(String(route?.name || ''))
    || /\/projects\/[^/]+\/manuscript(?:\/chapters\/[^/?#]+)?(?:[?#]|$)/u.test(routeKey(route))
}

function safeScrollTop(value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : 0
}

export function createManuscriptHistory({
  router,
  windowRef = globalThis.window,
  documentRef = globalThis.document,
  getScroller,
  schedule = callback => Promise.resolve().then(callback),
} = {}) {
  let mounted = false
  let pendingPopState = null
  let currentRoute = router?.currentRoute?.value || null
  let renderAction = null
  let removeBefore = () => {}
  let removeAfter = () => {}
  let attachedScroller = null
  let historyPosition = windowRef?.history?.state?.position

  function focusId(scroller) {
    const active = documentRef?.activeElement
    return active?.id && scroller?.contains?.(active) ? String(active.id) : ''
  }

  function stateFor(route, scroller) {
    return {
      routeKey: routeKey(route),
      scrollTop: safeScrollTop(scroller?.scrollTop),
      focusId: focusId(scroller),
    }
  }

  function replaceManuscriptState(value) {
    if (!windowRef?.history?.replaceState) return
    windowRef.history.replaceState({
      ...(windowRef.history.state || {}),
      [STATE_KEY]: {
        routeKey: String(value.routeKey || ''),
        scrollTop: safeScrollTop(value.scrollTop),
        focusId: String(value.focusId || ''),
      },
    }, '')
  }

  function recordCurrent() {
    if (!isManuscriptRoute(currentRoute)) return
    replaceManuscriptState(stateFor(currentRoute, getScroller?.()))
  }

  function handlePopState(event) {
    pendingPopState = event?.state?.[STATE_KEY] || {}
  }

  function restoreRecorded(record, route, scroller) {
    if (!record || String(record.routeKey || '') !== routeKey(route)) return false
    const top = safeScrollTop(record.scrollTop)
    if (scroller?.scrollTo) scroller.scrollTo({ top, behavior: 'auto' })
    else if (scroller) scroller.scrollTop = top
    const target = record.focusId ? documentRef?.getElementById?.(String(record.focusId)) : null
    if (target?.isConnected !== false && target && scroller?.contains?.(target)) {
      target.focus?.({ preventScroll: true })
    }
    return true
  }

  function resetForNewManuscriptRoute(scroller) {
    if (scroller?.scrollTo) scroller.scrollTo({ top: 0, behavior: 'auto' })
    else if (scroller) scroller.scrollTop = 0
    scroller?.querySelector?.('h1')?.focus?.({ preventScroll: true })
  }

  function applyRenderAction(action, route, scroller) {
    if (!action || action.routeKey !== routeKey(route)) return false
    if (action.type === 'restore') restoreRecorded(action.record, route, scroller)
    else if (action.type === 'reset') resetForNewManuscriptRoute(scroller)
    replaceManuscriptState(stateFor(route, scroller))
    return true
  }

  async function afterNavigation(to, from) {
    const priorRenderAction = renderAction
    const popRecord = pendingPopState
    const isPop = pendingPopState !== null
    pendingPopState = null
    currentRoute = to
    historyPosition = windowRef?.history?.state?.position
    if (!isManuscriptRoute(to)) {
      renderAction = null
      return
    }

    const carriesPendingAction = !isPop
      && ['reset', 'restore'].includes(priorRenderAction?.type)
      && routeIdentity(to) === routeIdentity(from)
    renderAction = carriesPendingAction
      ? {
          routeKey: routeKey(to),
          type: priorRenderAction.type,
          record: priorRenderAction.type === 'restore'
            ? { ...priorRenderAction.record, routeKey: routeKey(to) }
            : priorRenderAction.record,
        }
      : {
          routeKey: routeKey(to),
          type: isPop
            ? 'restore'
            : (!isManuscriptRoute(from) || routeIdentity(to) !== routeIdentity(from) ? 'reset' : 'preserve'),
          record: popRecord,
        }

  }

  async function viewRendered(route = currentRoute) {
    if (!mounted || !isManuscriptRoute(route)) return false
    const action = renderAction
    await schedule(() => {})
    if (action !== renderAction) return false
    const applied = applyRenderAction(action, route, getScroller?.())
    if (applied) renderAction = null
    return applied
  }

  async function mount() {
    if (mounted) return
    mounted = true
    currentRoute = router?.currentRoute?.value || currentRoute
    attachedScroller = getScroller?.() || null
    attachedScroller?.addEventListener?.('scroll', recordCurrent, { passive: true })
    attachedScroller?.addEventListener?.('focusin', recordCurrent)
    windowRef?.addEventListener?.('popstate', handlePopState)
    removeBefore = router?.beforeEach?.((to, from) => {
      const destinationState = windowRef?.history?.state?.[STATE_KEY]
      const destinationPosition = windowRef?.history?.state?.position
      const browserAlreadyMoved = historyPosition != null
        && destinationPosition != null
        && destinationPosition !== historyPosition
      const historyAlreadyEnteredDestination = Boolean(
        destinationState
        && String(destinationState.routeKey || '') === routeKey(to)
        && routeKey(to) !== routeKey(from),
      )
      if (pendingPopState === null && (browserAlreadyMoved || historyAlreadyEnteredDestination)) {
        pendingPopState = destinationState || {}
      } else if (pendingPopState === null) {
        currentRoute = from
        recordCurrent()
      }
    }) || (() => {})
    removeAfter = router?.afterEach?.((to, from) => afterNavigation(to, from)) || (() => {})
    if (isManuscriptRoute(currentRoute)) {
      const existing = windowRef?.history?.state?.[STATE_KEY]
      const currentKey = routeKey(currentRoute)
      const canRestore = existing
        && routeDocumentKey(existing.routeKey) === routeDocumentKey(currentKey)
      renderAction = {
        routeKey: currentKey,
        type: canRestore ? 'restore' : 'reset',
        record: canRestore ? { ...existing, routeKey: currentKey } : existing,
      }
      await schedule(() => {})
    }
  }

  function dispose() {
    if (!mounted) return
    if (pendingPopState === null) recordCurrent()
    mounted = false
    attachedScroller?.removeEventListener?.('scroll', recordCurrent)
    attachedScroller?.removeEventListener?.('focusin', recordCurrent)
    windowRef?.removeEventListener?.('popstate', handlePopState)
    removeBefore()
    removeAfter()
    removeBefore = () => {}
    removeAfter = () => {}
    attachedScroller = null
    renderAction = null
  }

  return { mount, dispose, recordCurrent, viewRendered }
}
