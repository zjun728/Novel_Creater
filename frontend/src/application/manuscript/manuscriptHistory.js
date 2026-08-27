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
  let restoreBaseline = null
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
    if (
      !isManuscriptRoute(currentRoute)
      || pendingPopState !== null
      || ['reset', 'restore'].includes(renderAction?.type)
    ) return
    replaceManuscriptState(stateFor(currentRoute, getScroller?.()))
  }

  function handlePopState(event) {
    pendingPopState = event?.state?.[STATE_KEY] || {}
  }

  function captureRestoreBaseline(action, route, scroller) {
    if (
      restoreBaseline?.action === action
      && restoreBaseline.routeKey === routeKey(route)
    ) return
    const active = documentRef?.activeElement || null
    restoreBaseline = {
      action,
      routeKey: routeKey(route),
      scrollTop: safeScrollTop(scroller?.scrollTop),
      activeElement: active,
      activeId: String(active?.id || ''),
      activeWasInScroller: Boolean(
        active
        && active.isConnected !== false
        && scroller?.contains?.(active),
      ),
      overrideLatched: false,
    }
  }

  function restoreWasOverridden(action, route) {
    const baseline = restoreBaseline
    if (!baseline || baseline.action !== action || baseline.routeKey !== routeKey(route)) return false
    return baseline.overrideLatched === true
  }

  function handleScrollerInteraction() {
    if (
      restoreBaseline
      && restoreBaseline.action === renderAction
      && restoreBaseline.routeKey === routeKey(currentRoute)
    ) restoreBaseline.overrideLatched = true
    recordCurrent()
  }

  function restoreRecorded(record, route, scroller, { settled = false } = {}) {
    if (!record || String(record.routeKey || '') !== routeKey(route)) return false
    const top = safeScrollTop(record.scrollTop)
    const requestedTarget = record.focusId ? documentRef?.getElementById?.(String(record.focusId)) : null
    const targetIsUsable = target => Boolean(
      target
      && target.isConnected !== false
      && (!scroller?.contains || scroller.contains(target)),
    )
    const exactTarget = targetIsUsable(requestedTarget) ? requestedTarget : null
    if (record.focusId && !exactTarget && !settled) return false
    const fallbackTarget = settled && !exactTarget
      ? scroller?.querySelector?.('h1')
      : null
    const focusTarget = exactTarget || (targetIsUsable(fallbackTarget) ? fallbackTarget : null)
    const scrollHeight = Number(scroller?.scrollHeight)
    const clientHeight = Number(scroller?.clientHeight)
    const hasScrollRange = Number.isFinite(scrollHeight) && Number.isFinite(clientHeight)
    const maxScroll = hasScrollRange ? Math.max(0, scrollHeight - clientHeight) : top
    if (
      top > 0
      && hasScrollRange
      && maxScroll < top
      && !settled
    ) return false
    const restoredTop = settled ? Math.min(top, maxScroll) : top
    if (scroller?.scrollTo) scroller.scrollTo({ top: restoredTop, behavior: 'auto' })
    else if (scroller) scroller.scrollTop = restoredTop
    focusTarget?.focus?.({ preventScroll: true })
    return true
  }

  function resetForNewManuscriptRoute(scroller) {
    if (scroller?.scrollTo) scroller.scrollTo({ top: 0, behavior: 'auto' })
    else if (scroller) scroller.scrollTop = 0
    scroller?.querySelector?.('h1')?.focus?.({ preventScroll: true })
  }

  function applyRenderAction(action, route, scroller, options) {
    if (!action || action.routeKey !== routeKey(route)) return false
    if (action.type === 'restore' && options?.settled && restoreWasOverridden(action, route)) {
      replaceManuscriptState(stateFor(route, scroller))
      restoreBaseline = null
      return true
    }
    if (action.type === 'restore' && !restoreRecorded(action.record, route, scroller, options)) {
      if (!options?.settled) captureRestoreBaseline(action, route, scroller)
      return false
    }
    else if (action.type === 'reset') resetForNewManuscriptRoute(scroller)
    replaceManuscriptState(stateFor(route, scroller))
    restoreBaseline = null
    return true
  }

  async function afterNavigation(to, from) {
    const priorRenderAction = renderAction
    const priorRestoreBaseline = restoreBaseline
    const popRecord = pendingPopState
    const isPop = pendingPopState !== null
    pendingPopState = null
    currentRoute = to
    historyPosition = windowRef?.history?.state?.position
    if (!isManuscriptRoute(to)) {
      renderAction = null
      restoreBaseline = null
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
    restoreBaseline = carriesPendingAction
      && priorRestoreBaseline?.action === priorRenderAction
      && priorRestoreBaseline.routeKey === priorRenderAction.routeKey
      ? {
          ...priorRestoreBaseline,
          action: renderAction,
          routeKey: routeKey(to),
        }
      : null

  }

  async function viewRendered(route = currentRoute, { settled = false } = {}) {
    if (!mounted || !isManuscriptRoute(route)) return false
    const renderedRouteKey = routeKey(route)
    const action = renderAction
    const renderedIsSettled = settled === true
    await schedule(() => {})
    if (action !== renderAction || renderedRouteKey !== routeKey(currentRoute)) return false
    const applied = applyRenderAction(action, { fullPath: renderedRouteKey }, getScroller?.(), { settled: renderedIsSettled })
    if (applied) renderAction = null
    return applied
  }

  async function mount() {
    if (mounted) return
    mounted = true
    currentRoute = router?.currentRoute?.value || currentRoute
    attachedScroller = getScroller?.() || null
    attachedScroller?.addEventListener?.('scroll', handleScrollerInteraction, { passive: true })
    attachedScroller?.addEventListener?.('focusin', handleScrollerInteraction)
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
      restoreBaseline = null
      await schedule(() => {})
    }
  }

  function dispose() {
    if (!mounted) return
    if (pendingPopState === null) recordCurrent()
    mounted = false
    attachedScroller?.removeEventListener?.('scroll', handleScrollerInteraction)
    attachedScroller?.removeEventListener?.('focusin', handleScrollerInteraction)
    windowRef?.removeEventListener?.('popstate', handlePopState)
    removeBefore()
    removeAfter()
    removeBefore = () => {}
    removeAfter = () => {}
    attachedScroller = null
    renderAction = null
    restoreBaseline = null
  }

  return { mount, dispose, recordCurrent, viewRendered }
}
