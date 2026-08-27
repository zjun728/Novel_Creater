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

test('initial restore waits for the async manuscript content and focus target to render', async () => {
  const { createManuscriptHistory } = await loadHistoryModule()
  const initial = route('/projects/p/manuscript/chapters/3', { chapterNumber: 3, view: 'outline' })
  const env = fakeEnvironment(initial)
  env.entries[0].state.manuscriptView = {
    routeKey: initial.fullPath,
    scrollTop: 620,
    focusId: 'final-reader-view-outline',
  }
  let ready = false
  let scrollCalls = 0
  const target = focusTarget('final-reader-view-outline', { activeElement: null })
  const documentRef = {
    activeElement: null,
    getElementById: id => ready && id === target.id ? target : null,
  }
  target.focus = options => { target.focusOptions = options; documentRef.activeElement = target }
  const scroller = {
    scrollTop: 0,
    contains: value => ready && value === target,
    querySelector: () => ready ? target : null,
    addEventListener() {}, removeEventListener() {},
    scrollTo({ top }) { scrollCalls += 1; this.scrollTop = ready ? top : 0 },
  }
  const manager = createManuscriptHistory({ router: env.router, windowRef: env.windowRef, documentRef, getScroller: () => scroller, schedule: callback => Promise.resolve().then(callback) })

  await manager.viewRendered(initial) // reproduces the old immediate query watcher
  await manager.mount()
  assert.equal(scrollCalls, 0)
  assert.equal(documentRef.activeElement, null)

  ready = true
  await manager.viewRendered(initial)
  assert.equal(scroller.scrollTop, 620)
  assert.equal(documentRef.activeElement, target)
  manager.dispose()
})

test('mount publishes its initial action before an in-flight content render notification', async () => {
  const { createManuscriptHistory } = await loadHistoryModule()
  const initial = route('/projects/p/manuscript/chapters/3', { chapterNumber: 3 })
  const env = fakeEnvironment(initial)
  const scheduled = []
  const title = { id: 'final-reader-title', isConnected: true, focus() {} }
  const scroller = {
    scrollTop: 300,
    contains: value => value === title,
    querySelector: () => title,
    addEventListener() {}, removeEventListener() {},
    scrollTo({ top }) { this.scrollTop = top },
  }
  const manager = createManuscriptHistory({
    router: env.router,
    windowRef: env.windowRef,
    documentRef: { activeElement: null, getElementById: () => null },
    getScroller: () => scroller,
    schedule: callback => new Promise(resolve => {
      scheduled.push(() => { callback(); resolve() })
    }),
  })

  const mounting = manager.mount()
  assert.equal(scheduled.length, 1)
  const rendering = manager.viewRendered(initial)
  assert.equal(scheduled.length, 2)
  scheduled.shift()()
  await Promise.resolve()
  scheduled.shift()()

  assert.equal(await rendering, true, 'the content notification must observe the initial action')
  await mounting
  assert.equal(scroller.scrollTop, 0)
  manager.dispose()
})

test('mount restores a history entry normalized by the child view before the manager mounts', async () => {
  const { createManuscriptHistory } = await loadHistoryModule()
  const bad = route('/projects/p/manuscript/chapters/3', { chapterNumber: 3, view: 'bad' })
  const normalized = route('/projects/p/manuscript/chapters/3', { chapterNumber: 3, view: 'text' })
  const env = fakeEnvironment(bad)
  env.entries[0].state.manuscriptView = {
    routeKey: bad.fullPath,
    scrollTop: 510,
    focusId: 'final-reader-view-text',
  }
  env.router.currentRoute.value = normalized
  env.entries[0].route = normalized
  const target = { id: 'final-reader-view-text', isConnected: true, focus() { documentRef.activeElement = this } }
  const documentRef = { activeElement: null, getElementById: id => id === target.id ? target : null }
  const scroller = { scrollTop: 0, contains: value => value === target, querySelector: () => target, addEventListener() {}, removeEventListener() {}, scrollTo({ top }) { this.scrollTop = top } }
  const manager = createManuscriptHistory({ router: env.router, windowRef: env.windowRef, documentRef, getScroller: () => scroller, schedule: callback => Promise.resolve().then(callback) })

  await manager.mount()
  await manager.viewRendered(normalized)

  assert.equal(scroller.scrollTop, 510)
  assert.equal(documentRef.activeElement, target)
  assert.equal(env.entries[0].state.manuscriptView.routeKey, normalized.fullPath)
  manager.dispose()
})

test('invalid view normalization preserves a pending pop restoration', async () => {
  const { createManuscriptHistory } = await loadHistoryModule()
  const bad = route('/projects/p/manuscript/chapters/3', { chapterNumber: 3, view: 'bad' })
  const normalized = route('/projects/p/manuscript/chapters/3', { chapterNumber: 3, view: 'text' })
  const env = fakeEnvironment(bad)
  env.entries[0].state.manuscriptView = { routeKey: bad.fullPath, scrollTop: 480, focusId: 'final-reader-view-text' }
  const target = { id: 'final-reader-view-text', isConnected: true, focus() { documentRef.activeElement = this } }
  const documentRef = { activeElement: null, getElementById: id => id === target.id ? target : null }
  const scroller = { scrollTop: 0, contains: value => value === target, querySelector: () => target, addEventListener() {}, removeEventListener() {}, scrollTo({ top }) { this.scrollTop = top } }
  const manager = createManuscriptHistory({ router: env.router, windowRef: env.windowRef, documentRef, getScroller: () => scroller, schedule: callback => Promise.resolve().then(callback) })
  await manager.mount()

  await env.navigate(normalized, 'replace')
  await manager.viewRendered(normalized)

  assert.equal(scroller.scrollTop, 480)
  assert.equal(documentRef.activeElement, target)
  assert.equal(env.entries[0].state.manuscriptView.routeKey, normalized.fullPath)
  manager.dispose()
})

test('invalid view normalization preserves a pending new-chapter reset', async () => {
  const { createManuscriptHistory } = await loadHistoryModule()
  const first = route('/projects/p/manuscript/chapters/2', { chapterNumber: 2 })
  const bad = route('/projects/p/manuscript/chapters/3', { chapterNumber: 3, view: 'bad' })
  const normalized = route('/projects/p/manuscript/chapters/3', { chapterNumber: 3, view: 'text' })
  const env = fakeEnvironment(first)
  const firstTitle = { id: 'chapter-2-title', isConnected: true, focus() {} }
  const nextTitle = { id: 'chapter-3-title', isConnected: true, focus() { documentRef.activeElement = this } }
  const documentRef = { activeElement: null, getElementById: () => null }
  const scroller = {
    scrollTop: 0,
    contains: () => true,
    querySelector: () => env.router.currentRoute.value.params.chapterNumber === '3' ? nextTitle : firstTitle,
    addEventListener() {}, removeEventListener() {},
    scrollTo({ top }) { this.scrollTop = top },
  }
  const manager = createManuscriptHistory({ router: env.router, windowRef: env.windowRef, documentRef, getScroller: () => scroller, schedule: callback => Promise.resolve().then(callback) })
  await manager.mount()
  await manager.viewRendered(first)
  scroller.scrollTop = 360

  await env.navigate(bad, 'push')
  await env.navigate(normalized, 'replace')
  await manager.viewRendered(normalized)

  assert.equal(scroller.scrollTop, 0)
  assert.equal(documentRef.activeElement, nextTitle)
  manager.dispose()
})
