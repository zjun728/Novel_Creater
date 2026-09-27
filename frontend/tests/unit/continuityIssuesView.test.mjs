import { projectOverviewPath, planningPlotsPath } from '../../src/router/projectRoutes.js'
import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { createServer } from 'vite'
import vuePlugin from '@vitejs/plugin-vue'
import { api } from '../../src/api/db/client.js'
import { createContinuityIssuesController, ISSUE_CATEGORIES, ISSUE_SEVERITIES, ISSUE_STATUSES } from '../../src/application/continuity/continuityIssuesController.js'

const issue = (overrides = {}) => ({ id: '11111111-1111-4111-8111-111111111111', projectId: 'p', category: 'time', severity: 'medium', status: 'pending', description: '抵达时间前后不一致。', suggestion: null, futureTarget: null, sourceChapterNumber: null, sourceFinalizationId: null, sourceCanonRevision: null, resolutionNote: null, createdAt: 100, updatedAt: 100, ...overrides })
const page = (items = [], overrides = {}) => ({ projectId: 'p', lifecycle: 'active', items, nextOffset: null, ...overrides })
const deferred = () => { let resolve; let reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const make = (methods = {}) => createContinuityIssuesController({ api: { continuityIssues: { list: async () => page(), get: async () => issue(), create: async (_id, payload) => issue(payload), update: async (_id, id, payload) => issue({ id, ...payload, updatedAt: 101 }), ...methods } }, makeId: () => issue().id })
async function begin(controller, source = null) { await controller.load('p'); controller.beginCreate(source); controller.form.description = issue().description }

test('creation sends only issue fields and a stable request UUID with an optional source chapter', async () => {
  const calls = []; const controller = make({ create: async (...args) => { calls.push(args); return issue({ ...args[1], sourceFinalizationId: 'final-2', sourceCanonRevision: 2 }) } })
  await begin(controller, 2); controller.form.futureTarget = '下一章解释误报来源'
  assert.equal(await controller.save(), true)
  assert.deepEqual(calls[0], ['p', { id: issue().id, category: 'fact', severity: 'medium', description: issue().description, suggestion: null, futureTarget: '下一章解释误报来源', sourceChapterNumber: 2 }])
  assert.equal(controller.dirty.value, false)
})

test('uncertain creation locks fields and retries the identical UUID and original payload', async () => {
  const calls = []; const controller = make({ create: async (_id, payload) => { calls.push(structuredClone(payload)); if (calls.length === 1) throw { code: 'request_timeout' }; return issue({ ...payload, status: 'resolved', resolutionNote: '已在后文解释', updatedAt: 200 }) } })
  await begin(controller); await controller.save()
  assert.equal(controller.operation.value, 'uncertain')
  assert.equal(controller.formLocked.value, true)
  assert.equal(controller.cancel(), false)
  controller.form.description = '不应发送的新内容'
  assert.equal(await controller.save(), true)
  assert.deepEqual(calls[1], calls[0])
  assert.equal(controller.selected.value.status, 'resolved')
})

test('definite creation validation failure keeps editable author content and hides backend diagnostics', async () => {
  const controller = make({ create: async () => { throw { code: 'ContinuityIssueSourceInvalid', status: 422, message: 'SECRET SQL' } } })
  await begin(controller, 2); await controller.save()
  assert.equal(controller.formLocked.value, false)
  assert.equal(controller.form.description, issue().description)
  assert.match(controller.message.value, /来源章节/)
  assert.doesNotMatch(controller.message.value, /SECRET SQL/)
})

test('invalid author inputs never make a write request', async () => {
  let calls = 0; const controller = make({ create: async () => { calls++; return issue() } })
  await begin(controller)
  for (const values of [{ description: ' ' }, { description: '文'.repeat(4001) }, { description: '问题', sourceChapterNumber: '0' }, { sourceChapterNumber: '1.5' }, { sourceChapterNumber: '01' }, { sourceChapterNumber: '', category: 'unknown' }]) {
    Object.assign(controller.form, values); assert.equal(await controller.save(), false)
  }
  assert.equal(calls, 0)
})

test('resolved and ignored require a note, while returning to pending accepts an empty note', async () => {
  const calls = []; const controller = make({ update: async (_p, _id, payload) => { calls.push(payload); return issue({ ...payload, updatedAt: 200 }) } })
  await controller.load('p'); await controller.open(issue().id)
  for (const status of ['resolved', 'ignored']) { controller.form.status = status; assert.equal(await controller.save(), false) }
  assert.equal(calls.length, 0)
  controller.form.status = 'pending'; assert.equal(await controller.save(), true)
  assert.deepEqual(calls[0], { status: 'pending', resolutionNote: null, expectedUpdatedAt: 100 })
})

test('update conflict preserves author note and cannot save again until an explicit fresh GET', async () => {
  let writes = 0; let reads = 0; const calls = []
  const controller = make({ get: async () => issue({ updatedAt: ++reads === 1 ? 100 : 150, status: reads === 1 ? 'pending' : 'ignored', resolutionNote: reads === 1 ? null : '其他作者已说明' }), update: async (_p, _id, payload) => { calls.push(payload); if (++writes === 1) throw { code: 'ContinuityIssueConflict', status: 409 }; return issue({ ...payload, updatedAt: 200 }) } })
  await controller.load('p'); await controller.open(issue().id)
  controller.form.status = 'resolved'; controller.form.resolutionNote = '我的处理说明'
  await controller.save(); assert.equal(controller.operation.value, 'conflict')
  assert.equal(await controller.save(), false); assert.equal(writes, 1)
  assert.equal(controller.form.resolutionNote, '我的处理说明')
  assert.equal(await controller.reloadSelected(), true)
  assert.equal(controller.selected.value.status, 'ignored')
  assert.equal(controller.form.resolutionNote, '我的处理说明')
  await controller.save(); assert.equal(calls[1].expectedUpdatedAt, 150)
})

test('failed conflict refresh keeps the save barrier and the unsaved note', async () => {
  let reads = 0; const controller = make({ get: async () => { if (++reads > 1) throw { code: 'ContinuityIssueUnavailable' }; return issue() }, update: async () => { throw { code: 'ContinuityIssueConflict' } } })
  await controller.load('p'); await controller.open(issue().id)
  controller.form.status = 'resolved'; controller.form.resolutionNote = '待确认说明'; await controller.save()
  assert.equal(await controller.reloadSelected(), false)
  assert.equal(controller.operation.value, 'conflict')
  assert.equal(controller.form.resolutionNote, '待确认说明')
})

test('an invalid create receipt stays uncertain and an unchanged update receipt requires a fresh read', async () => {
  const creation = make({ create: async () => issue({ description: '错误的其他内容' }) })
  await begin(creation); assert.equal(await creation.save(), false)
  assert.equal(creation.operation.value, 'uncertain'); assert.equal(creation.formLocked.value, true)
  const update = make({ update: async () => issue({ status: 'resolved', resolutionNote: '说明', updatedAt: 100 }) })
  await update.load('p'); await update.open(issue().id); update.form.status = 'resolved'; update.form.resolutionNote = '说明'
  assert.equal(await update.save(), false); assert.equal(update.operation.value, 'conflict')
  assert.equal(update.form.resolutionNote, '说明')
})

test('a completed write for the previous project cannot refresh or replace the current page', async () => {
  const pending = deferred(); const calls = []
  const controller = make({ list: async id => { calls.push(id); return page([], { projectId: id }) }, create: async () => pending.promise })
  await begin(controller); const saving = controller.save(); await controller.load('next')
  pending.resolve(issue({ category: 'fact' })); await saving
  assert.deepEqual(calls, ['p', 'next']); assert.equal(controller.state.value.data.projectId, 'next'); assert.equal(controller.selected.value, null)
})

test('archived list and mid-save archive rejection prevent any further writes', async () => {
  let calls = 0; const archived = make({ list: async () => page([], { lifecycle: 'archived' }), create: async () => { calls++; return issue() } })
  await archived.load('p'); assert.equal(archived.beginCreate(), false); assert.equal(await archived.save(), false)
  const active = make({ create: async () => { calls++; throw { code: 'ProjectArchived', status: 409 } } })
  await begin(active); await active.save(); assert.equal(active.readOnly.value, true)
  await active.save(); assert.equal(calls, 1)
})

test('filtering and a failed list refresh preserve the active editable draft', async () => {
  const request = deferred(); let first = true
  const controller = make({ list: async () => { if (first) { first = false; return page() }; return request.promise } })
  await controller.load('p'); await controller.open(issue().id)
  controller.form.status = 'resolved'; controller.form.resolutionNote = '尚未保存的处理说明'
  const refresh = controller.load('p', { status: 'pending', offset: 50 })
  assert.equal(controller.readOnly.value, false)
  assert.equal(controller.form.resolutionNote, '尚未保存的处理说明')
  request.reject({ code: 'ContinuityIssueUnavailable' }); await refresh
  assert.equal(controller.state.value.status, 'error'); assert.equal(controller.readOnly.value, false)
  assert.equal(controller.dirty.value, true); assert.equal(controller.form.resolutionNote, '尚未保存的处理说明')
})

for (const code of ['ProjectArchived', 'ProjectNotFound']) {
  test(`a delayed active list cannot reverse ${code} from a later save`, async () => {
    const pending = deferred(); let reads = 0; let writes = 0
    const controller = make({
      list: async () => ++reads === 2 ? pending.promise : page(),
      update: async () => { writes++; throw { code } },
    })
    await controller.load('p'); await controller.open(issue().id)
    controller.form.resolutionNote = '保留处理说明'
    const refreshing = controller.load('p')
    await controller.save()
    pending.resolve(page()); await refreshing
    assert.equal(controller.readOnly.value, true)
    assert.equal(controller.formLocked.value, true)
    assert.equal(controller.form.resolutionNote, '保留处理说明')
    assert.equal(await controller.save(), false); assert.equal(writes, 1)
    await controller.load('p')
    assert.equal(controller.readOnly.value, false)
  })
}

test('a delayed active detail cannot undo an archive learned by the list', async () => {
  const pending = deferred(); let reads = 0
  const controller = make({ list: async () => page([], { lifecycle: ++reads === 1 ? 'active' : 'archived' }), get: async () => pending.promise })
  await controller.load('p')
  const opening = controller.open(issue().id)
  await controller.load('p')
  pending.resolve(issue({ lifecycle: 'active' })); await opening
  assert.equal(controller.selected.value.id, issue().id)
  assert.equal(controller.readOnly.value, true)
})

test('a confirmed archive preserves the unsaved note and blocks writing', async () => {
  let archived = false; let writes = 0
  const controller = make({ list: async () => page([], { lifecycle: archived ? 'archived' : 'active' }), update: async () => { writes++; return issue() } })
  await controller.load('p'); await controller.open(issue().id)
  controller.form.status = 'ignored'; controller.form.resolutionNote = '尚未提交的忽略理由'
  archived = true; await controller.load('p')
  assert.equal(controller.readOnly.value, true); assert.equal(controller.dirty.value, true)
  assert.equal(controller.form.resolutionNote, '尚未提交的忽略理由')
  assert.equal(await controller.save(), false); assert.equal(writes, 0)
})

test('only explicit confirmation can close an archived uncertain creation and recover read-only browsing', async () => {
  let archived = false; let writes = 0; let confirmations = 0
  const controller = make({ list: async () => page([], { lifecycle: archived ? 'archived' : 'active' }), get: async () => issue({ lifecycle: 'archived' }), create: async () => { writes++; throw { code: 'request_timeout' } } })
  await begin(controller); await controller.save()
  assert.equal(await controller.closeArchivedUncertain(() => { confirmations++; return true }), false)
  assert.equal(confirmations, 0)
  archived = true; await controller.load('p')
  assert.equal(controller.canCloseArchivedUncertain.value, true)
  assert.equal(controller.cancel(), false); assert.equal(controller.beginCreate(), false)
  assert.equal(await controller.closeArchivedUncertain(() => { confirmations++; return false }), false)
  assert.equal(controller.operation.value, 'uncertain'); assert.equal(controller.form.description, issue().description)
  assert.equal(await controller.closeArchivedUncertain(() => { confirmations++; return true }), true)
  assert.equal(confirmations, 2); assert.equal(controller.mode.value, '')
  assert.match(controller.message.value, /可能已经保存/)
  assert.equal(controller.beginCreate(), false); assert.equal(await controller.save(), false)
  assert.equal(await controller.open(issue().id), true); assert.equal(controller.readOnly.value, true)
  assert.equal(writes, 1)
})

test('a delayed uncertain-close confirmation cannot discard a new project draft', async () => {
  let archived = false; const confirmation = deferred()
  const controller = make({ list: async id => page([], { projectId: id, lifecycle: archived && id === 'p' ? 'archived' : 'active' }), create: async () => { throw { code: 'request_timeout' } } })
  await begin(controller); await controller.save(); archived = true; await controller.load('p')
  const closing = controller.closeArchivedUncertain(() => confirmation.promise)
  await controller.load('next'); controller.beginCreate(); controller.form.description = '新项目草稿'
  confirmation.resolve(true)
  assert.equal(await closing, false); assert.equal(controller.form.description, '新项目草稿')
})

test('list filtering omits all status and caps pagination at 50', async () => {
  const calls = []; const controller = make({ list: async (id, filters) => { calls.push([id, filters]); return page() } })
  await controller.load('p'); await controller.load('p', { status: 'resolved', offset: 50 })
  assert.deepEqual(calls, [['p', { offset: 0, limit: 50 }], ['p', { status: 'resolved', offset: 50, limit: 50 }]])
})

test('a stale project list or detail cannot populate the current project', async () => {
  const slow = deferred(); const detail = deferred()
  const controller = make({ list: async id => id === 'old' ? slow.promise : page([], { projectId: id }), get: async () => detail.promise })
  const old = controller.load('old'); await controller.load('p'); slow.resolve(page([], { projectId: 'old' })); await old
  assert.equal(controller.state.value.data.projectId, 'p')
  const opening = controller.open(issue().id); await controller.load('new'); detail.resolve(issue()); await opening
  assert.equal(controller.selected.value, null)
})

test('invalid lifecycle, cross-project records and backward pagination are rejected', async () => {
  for (const result of [page([], { lifecycle: 'maybe' }), page([issue({ projectId: 'other' })]), page([], { nextOffset: 0 }), page([issue({ status: 'resolved', resolutionNote: null })])]) {
    const controller = make({ list: async () => result }); await controller.load('p')
    assert.equal(controller.state.value.status, 'error'); assert.equal(controller.state.value.data, null)
  }
})

test('dirty navigation confirms discard and saving blocks departure', async () => {
  const pending = deferred(); const controller = make({ create: async () => pending.promise })
  await begin(controller)
  let confirmations = 0
  assert.equal(await controller.confirmLeave(() => { confirmations++; return false }), false)
  const saving = controller.save(); assert.equal(await controller.confirmLeave(() => { confirmations++; return true }), false)
  assert.equal(confirmations, 1)
  const event = { preventDefault() { this.prevented = true } }; controller.beforeUnload(event)
  assert.equal(event.prevented, true); assert.equal(event.returnValue, '')
  pending.resolve(issue({ category: 'fact' })); await saving
  assert.equal(await controller.confirmLeave(() => false), true)
})

test('API client uses only the independent issues endpoints and preserves CAS and request fields', async () => {
  const previous = global.fetch; const calls = []
  global.fetch = async (url, options) => { calls.push({ url: String(url), method: options.method, body: options.body && JSON.parse(options.body) }); return new Response('{}', { status: 200 }) }
  try {
    await api.continuityIssues.list('p/a', { status: 'pending', offset: 50, limit: 50 })
    await api.continuityIssues.get('p/a', 'issue/a')
    await api.continuityIssues.create('p/a', { id: issue().id, description: '问题' })
    await api.continuityIssues.update('p/a', 'issue/a', { status: 'ignored', resolutionNote: '已核实无需处理', expectedUpdatedAt: 100 })
    assert.deepEqual(calls.map(call => [call.method, call.url.replace('http://127.0.0.1:8000/api', '')]), [
      ['GET', '/projects/p%2Fa/continuity/issues?status=pending&offset=50&limit=50'], ['GET', '/projects/p%2Fa/continuity/issues/issue%2Fa'], ['POST', '/projects/p%2Fa/continuity/issues'], ['PATCH', '/projects/p%2Fa/continuity/issues/issue%2Fa'],
    ])
    assert.equal(calls[2].body.id, issue().id); assert.equal(calls[3].body.expectedUpdatedAt, 100)
  } finally { global.fetch = previous }
})

let vite; let IssuesView
test.before(async () => {
  vite = await createServer({ configFile: false, root: fileURLToPath(new URL('../..', import.meta.url)), plugins: [vuePlugin()], server: { middlewareMode: true, hmr: false, ws: false }, optimizeDeps: { noDiscovery: true }, logLevel: 'error' })
  IssuesView = (await vite.ssrLoadModule('/src/views/ContinuityIssuesView.vue')).default
})
test.after(async () => { await vite?.close() })
async function renderPage(response, query = '', status = 200) {
  const previous = global.fetch
  global.fetch = async () => new Response(JSON.stringify(response), { status, headers: { 'content-type': 'application/json' } })
  try {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/continuity/issues', name: 'ContinuityIssues', component: IssuesView }] })
    await router.push(`/projects/p/continuity/issues${query}`); await router.isReady()
    const app = createSSRApp({ render: () => h(RouterView) }); app.use(router)
    return await renderToString(app)
  } finally { global.fetch = previous }
}

async function renderControllerState(controller) {
  const Snapshot = {
    ...IssuesView,
    setup: () => ({ ...controller, controller, projectId: 'p', filter: '', offset: 0, sourcePath: '', projectOverviewPath, planningPlotsPath, ISSUE_CATEGORIES, ISSUE_SEVERITIES, ISSUE_STATUSES, dateLabel: value => String(value) }),
  }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/continuity/issues', component: Snapshot }] })
  await router.push('/projects/p/continuity/issues'); await router.isReady()
  const app = createSSRApp({ render: () => h(RouterView) }); app.use(router)
  return renderToString(app)
}

test('the actual template keeps an unsaved resolution visible and editable after a list failure', async () => {
  let failure = false
  const controller = make({ list: async () => { if (failure) throw { code: 'ContinuityIssueUnavailable' }; return page() } })
  await controller.load('p'); await controller.open(issue().id)
  controller.form.status = 'resolved'; controller.form.resolutionNote = '刷新失败仍应保留的说明'
  failure = true; await controller.load('p')
  const html = await renderControllerState(controller)
  assert.match(html, /<textarea[^>]*>刷新失败仍应保留的说明<\/textarea>/)
  assert.match(html, /保存处理结论/)
  assert.doesNotMatch(html, /当前仅可查看问题及处理结论/)
})

test('the actual archived template shows unsaved resolution text without write controls', async () => {
  let archived = false
  const controller = make({ list: async () => page([], { lifecycle: archived ? 'archived' : 'active' }) })
  await controller.load('p'); await controller.open(issue().id)
  controller.form.status = 'ignored'; controller.form.resolutionNote = '归档后仍可复制的未保存说明'
  archived = true; await controller.load('p')
  const html = await renderControllerState(controller)
  assert.match(html, /aria-label="未保存的处理说明"/)
  assert.match(html, /归档后仍可复制的未保存说明/)
  assert.match(html, /处理状态：已忽略/)
  assert.doesNotMatch(html, /<textarea|保存处理结论|>记录问题</)
})

test('the archived uncertain template offers an enabled explicit close with all writes blocked', async () => {
  let archived = false
  const controller = make({ list: async () => page([], { lifecycle: archived ? 'archived' : 'active' }), create: async () => { throw { code: 'request_timeout' } } })
  await begin(controller); await controller.save(); archived = true; await controller.load('p')
  const html = await renderControllerState(controller)
  assert.match(html, /<button(?![^>]*disabled)[^>]*>关闭未确认表单<\/button>/)
  assert.match(html, /<button[^>]*disabled[^>]*>重试确认创建结果<\/button>/)
  assert.doesNotMatch(html, />记录问题</)
})

test('actual issues page renders independent states, source labels and the historical fact boundary', async () => {
  const html = await renderPage(page([issue({ description: '<b>时间矛盾</b>', sourceChapterNumber: 2, sourceFinalizationId: 'final-2', sourceCanonRevision: 2 })]))
  for (const text of ['连续性问题', '全部状态', '待处理', '已解决', '已忽略', '来源：第 2 章定稿', '不代表历史正文或已发生事实被改写', '未来处理目标仅保存说明']) assert.ok(html.includes(text), text)
  assert.match(html, /&lt;b&gt;时间矛盾&lt;\/b&gt;/)
  assert.doesNotMatch(html, /<b>时间矛盾|<main/)
})

test('actual source-entry page opens an editable creation form with the source chapter prefilled', async () => {
  const html = await renderPage(page(), '?sourceChapterNumber=2')
  assert.match(html, /记录连续性问题/)
  assert.match(html, /<input[^>]*value="2"/)
  assert.match(html, /<textarea[^>]*required/)
  assert.match(html, /保存问题记录/)
})

test('actual archived source-entry page stays read-only without creation or handling controls', async () => {
  const html = await renderPage(page([issue()], { lifecycle: 'archived' }), '?sourceChapterNumber=2')
  assert.match(html, /项目已归档，连续性问题仅可查看/)
  assert.doesNotMatch(html, /<textarea|保存问题记录|保存处理结论|>记录问题</)
})

test('actual empty and failed pages give distinct honest recovery paths', async () => {
  const empty = await renderPage(page())
  assert.match(empty, /尚无连续性问题记录/)
  const failed = await renderPage({ code: 'ContinuityIssueUnavailable', message: 'SECRET' }, '', 503)
  assert.match(failed, /重新读取/); assert.doesNotMatch(failed, /尚无连续性问题记录|SECRET/)
})
