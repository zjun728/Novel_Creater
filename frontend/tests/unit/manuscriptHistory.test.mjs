import assert from 'node:assert/strict'
import test from 'node:test'

async function loadHistoryModule() {
  try {
    return await import('../../src/application/manuscript/manuscriptHistory.js')
  } catch (error) {
    assert.fail(`manuscript history module is missing: ${error.message}`)
  }
}

function route(path, { projectId = 'p', chapterNumber, view } = {}) {
  const query = view ? { view } : {}
  return {
    fullPath: `${path}${view ? `?view=${view}` : ''}`,
    name: chapterNumber == null ? 'ProjectManuscript' : 'FinalChapterReader',
    params: { projectId, ...(chapterNumber == null ? {} : { chapterNumber: String(chapterNumber) }) },
    query,
  }
}

function fakeEnvironment(initialRoute) {
  const listeners = new Map()
  const entries = [{ state: { position: 0 }, route: initialRoute }]
  let index = 0
  const before = []
  const after = []
  const currentRoute = { value: initialRoute }
  const history = {
    get state() { return entries[index].state },
    replaceState(state) { entries[index].state = { ...structuredClone(state), position: index } },
    pushState(state, _title, _url) {
      entries.splice(index + 1)
      entries.push({ state: { ...structuredClone(state), position: index + 1 }, route: null })
      index += 1
    },
  }
  const windowRef = {
    history,
    addEventListener(type, listener) { listeners.set(type, listener) },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) listeners.delete(type)
    },
  }
  const router = {
    currentRoute,
    beforeEach(handler) { before.push(handler); return () => before.splice(before.indexOf(handler), 1) },
    afterEach(handler) { after.push(handler); return () => after.splice(after.indexOf(handler), 1) },
  }
  async function navigate(next, kind = 'push') {
    const from = currentRoute.value
    if (kind === 'popstate' || kind === 'popstate-late') {
      index -= 1
      if (kind === 'popstate') listeners.get('popstate')?.({ state: entries[index].state })
    }
    for (const handler of [...before]) await handler(next, from)
    if (kind === 'popstate-late') listeners.get('popstate')?.({ state: entries[index].state })
    if (kind === 'push') history.pushState({}, '', next.fullPath)
    if (kind === 'replace') history.replaceState({}, '', next.fullPath)
    currentRoute.value = next
    entries[index].route = next
    for (const handler of [...after]) await handler(next, from)
  }
  return { router, windowRef, entries, navigate, get index() { return index } }
}

function focusTarget(id, documentRef) {
  return {
    id,
    isConnected: true,
    focusOptions: null,
    focus(options) { this.focusOptions = options; documentRef.activeElement = this },
  }
}

test('history entries retain independent chapter scroll and focus on push and popstate', async () => {
  const { createManuscriptHistory } = await loadHistoryModule()
  const first = route('/projects/p/manuscript/chapters/1', { chapterNumber: 1 })
  const second = route('/projects/p/manuscript/chapters/2', { chapterNumber: 2 })
  const env = fakeEnvironment(first)
  const listeners = new Map()
  const documentRef = { activeElement: null, getElementById: id => targets.get(id) || null }
  const title1 = focusTarget('chapter-1-title', documentRef)
  const title2 = focusTarget('chapter-2-title', documentRef)
  const targets = new Map([[title1.id, title1], [title2.id, title2]])
  const scroller = {
    scrollTop: 0,
    contains: target => targets.has(target?.id),
    querySelector: () => env.router.currentRoute.value === first ? title1 : title2,
    addEventListener(type, listener) { listeners.set(type, listener) },
    removeEventListener(type, listener) { if (listeners.get(type) === listener) listeners.delete(type) },
    scrollTo({ top }) { this.scrollTop = top },
  }
  const manager = createManuscriptHistory({
    router: env.router,
    windowRef: env.windowRef,
    documentRef,
    getScroller: () => scroller,
    schedule: callback => Promise.resolve().then(callback),
  })
  await manager.mount()
  await manager.viewRendered(first)
  assert.equal(scroller.scrollTop, 0)
  assert.equal(documentRef.activeElement, title1)
  assert.deepEqual(title1.focusOptions, { preventScroll: true })
  scroller.scrollTop = 140
  documentRef.activeElement = title1
  listeners.get('scroll')()
  listeners.get('focusin')()

  await env.navigate(second, 'push')
  await manager.viewRendered(second)
  assert.equal(scroller.scrollTop, 0)
  assert.deepEqual(title2.focusOptions, { preventScroll: true })
  scroller.scrollTop = 280
  documentRef.activeElement = title2
  listeners.get('scroll')()
  listeners.get('focusin')()

  await env.navigate(first, 'popstate-late')
  scroller.scrollTop = 0
  await manager.viewRendered(first)
  assert.equal(scroller.scrollTop, 140)
  assert.equal(documentRef.activeElement, title1)
  scroller.scrollTop = 155
  await manager.viewRendered(first)
  assert.equal(scroller.scrollTop, 155, 'a consumed restoration must not replay on retry')
  assert.deepEqual(env.entries.map(entry => entry.state.manuscriptView?.scrollTop), [140, 280])
  assert.deepEqual(Object.keys(env.entries[0].state.manuscriptView).sort(), ['focusId', 'routeKey', 'scrollTop'])
  manager.dispose()
})

test('query push and replace preserve position while still keeping route-keyed entries', async () => {
  const { createManuscriptHistory } = await loadHistoryModule()
  const text = route('/projects/p/manuscript/chapters/1', { chapterNumber: 1, view: 'text' })
  const outline = route('/projects/p/manuscript/chapters/1', { chapterNumber: 1, view: 'outline' })
  const normalized = route('/projects/p/manuscript/chapters/1', { chapterNumber: 1, view: 'text' })
  const env = fakeEnvironment(text)
  let focusCount = 0
  let resetCount = 0
  const title = { id: 'reader-title', isConnected: true, focus() { focusCount += 1 } }
  const scroller = {
    scrollTop: 360,
    contains: () => true,
    querySelector: () => title,
    addEventListener() {}, removeEventListener() {},
    scrollTo({ top }) { resetCount += 1; this.scrollTop = top },
  }
  const manager = createManuscriptHistory({
    router: env.router,
    windowRef: env.windowRef,
    documentRef: { activeElement: title, getElementById: () => title },
    getScroller: () => scroller,
    schedule: callback => Promise.resolve().then(callback),
  })
  await manager.mount()
  await manager.viewRendered(text)
  assert.equal(focusCount, 1)
  assert.equal(resetCount, 1)
  scroller.scrollTop = 360
  await env.navigate(outline, 'push')
  await manager.viewRendered(outline)
  assert.equal(env.entries.length, 2)
  assert.equal(scroller.scrollTop, 360)
  assert.equal(focusCount, 1)
  assert.equal(resetCount, 1)
  const beforeReplace = env.entries.length
  await env.navigate(normalized, 'replace')
  await manager.viewRendered(normalized)
  assert.equal(env.entries.length, beforeReplace)
  assert.equal(scroller.scrollTop, 360)
  assert.equal(env.entries[env.index].state.manuscriptView.routeKey, normalized.fullPath)
  manager.dispose()
})

test('a late pop listener cannot write manuscript state into a non-manuscript destination', async () => {
  const { createManuscriptHistory } = await loadHistoryModule()
  const overview = { fullPath: '/projects/p/overview', name: 'ProjectOverview', params: { projectId: 'p' }, query: {} }
  const chapter = route('/projects/p/manuscript/chapters/1', { chapterNumber: 1 })
  const env = fakeEnvironment(overview)
  const scroller = {
    scrollTop: 0,
    contains: () => false,
    querySelector: () => ({ id: 'reader-title', focus() {} }),
    addEventListener() {}, removeEventListener() {}, scrollTo({ top }) { this.scrollTop = top },
  }
  const manager = createManuscriptHistory({
    router: env.router,
    windowRef: env.windowRef,
    documentRef: { activeElement: null, getElementById: () => null },
    getScroller: () => scroller,
    schedule: callback => Promise.resolve().then(callback),
  })
  await manager.mount()
  await env.navigate(chapter, 'push')
  await manager.viewRendered(chapter)
  scroller.scrollTop = 410
  manager.recordCurrent()

  await env.navigate(overview, 'popstate-late')

  assert.equal(env.entries[0].state.manuscriptView, undefined)
  assert.equal(env.entries[1].state.manuscriptView.scrollTop, 410)
  manager.dispose()
})
