import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createSSRApp, reactive, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const sourceRoot = fileURLToPath(new URL('../../src', import.meta.url))
const source = path => new URL(`../../src/${path}`, import.meta.url)
const HASH = 'a'.repeat(64)

async function createVite() {
  return createServer({
    configFile: false,
    root: frontendRoot,
    resolve: { alias: { '@': sourceRoot } },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin()],
    optimizeDeps: { noDiscovery: true },
  })
}

function outlineContent() {
  return {
    schemaVersion: 'chapter-outline-draft-v1',
    volumeRef: { id: 'volume-1', revision: 2, contentHash: HASH },
    storyBlockRef: { id: 'block-1', revision: 3, contentHash: HASH },
    stageRefs: [{ id: 'stage-1', revision: 4, contentHash: HASH }],
    sceneTaskRefs: [{ id: 'task-1', revision: 5, contentHash: HASH }],
    chapterGoal: '取得残卷',
    expectedCharacters: ['沈砚'],
    continuation: ['承接追兵'],
    plannedTasks: ['潜入县衙'],
    scenes: ['城门盘查'],
    forbiddenEarlyEvents: ['不揭示残卷来源'],
  }
}

function storeFixture() {
  const content = outlineContent()
  return reactive({
    outlineState: {
      projectId: 'project-1',
      lifecycle: 'active',
      authoritativeChapterNumber: 3,
      targetPath: '/projects/project-1/planning/story-blocks',
      planningAuthority: {
        planningRevisionId: 'planning-4',
        revision: 4,
        contentHash: HASH,
        content: {
          activeStoryBlockId: 'block-1',
          volumes: [
            {
              id: 'volume-1',
              revision: 2,
              contentHash: HASH,
              lifecycle: 'active',
              title: '第一卷',
            },
            {
              id: 'volume-retired',
              revision: 8,
              contentHash: HASH,
              lifecycle: 'retired',
              title: '旧卷',
            },
          ],
          plots: [],
          storyBlocks: [{
            id: 'block-1',
            revision: 3,
            contentHash: HASH,
            lifecycle: 'active',
            title: '夜入县衙',
            volumeId: 'volume-1',
            plotIds: [],
            stages: [
              {
                id: 'stage-1',
                revision: 4,
                contentHash: HASH,
                lifecycle: 'active',
                title: '潜入',
                sceneTasks: [{
                  id: 'task-1',
                  revision: 5,
                  contentHash: HASH,
                  lifecycle: 'active',
                  task: '取得残卷',
                }],
              },
              {
                id: 'stage-retired',
                revision: 9,
                contentHash: HASH,
                lifecycle: 'retired',
                title: '旧阶段',
                sceneTasks: [],
              },
            ],
          }],
        },
      },
      canonProjectionAuthority: {
        canonRevision: 2,
        projectionRevision: 2,
        contentHash: HASH,
        synchronized: true,
      },
      confirmedOutline: null,
      draft: {
        projectId: 'project-1',
        chapterNumber: 3,
        draftId: 'outline-draft-1',
        baseHeadRevision: 0,
        draftRevision: 1,
        contentHash: HASH,
        content,
        basis: {},
        status: 'current',
      },
      activeSession: null,
      capabilities: {
        view: true,
        createDraft: false,
        editDraft: true,
        generate: false,
        confirm: true,
        startSession: false,
      },
      reasons: [],
    },
    outlineHistory: [],
    outlineLocalContent: content,
    outlineDirty: false,
    outlineLoading: false,
    outlineSaving: false,
    outlineConfirming: false,
    outlineGenerating: false,
    outlineReconciling: false,
    outlineOperation: null,
    outlineOutcomeUnknown: false,
    outlineAwaitingAuthority: false,
    outlineError: null,
    error: null,
  })
}

function controllerFixture() {
  return {
    historyOpen: ref(false),
    authorInstructions: ref(''),
    notice: ref(''),
    busy: ref(false),
    editorLocked: ref(false),
    localOverlay: ref(false),
    hasCriticalRecovery: ref(false),
    readOnly: ref(false),
    editable: ref(true),
    canAdjustOutline: ref(false),
    canCreateDraft: ref(false),
    canSave: ref(false),
    canGenerate: ref(false),
    canConfirm: ref(true),
    generationDisabledReason: ref('小纲模型尚未就绪；手工编辑仍可继续。'),
    recovery: ref(null),
    recoveryActions: ref([]),
    hydrate() {},
    editLocal() {},
    createManualDraft() {},
    save() {},
    generate() {},
    reconcile() {},
    confirm() {},
    openHistory() {},
    closeHistory() {},
  }
}

test('drafting Session renders outline adoption labels from confirmed authority', async () => {
  const vite = await createVite()
  try {
    const Workspace = await vite.ssrLoadModule(
      '/src/components/planning/ChapterOutlineWorkspace.vue',
    )
    for (const [confirmedOutline, label] of [
      [null, '采用小纲'],
      [{ content: outlineContent() }, '更新当前小纲'],
    ]) {
      const store = storeFixture()
      store.outlineState.activeSession = { status: 'drafting' }
      store.outlineState.capabilities = {
        ...store.outlineState.capabilities,
        createDraft: true,
        editDraft: false,
      }
      store.outlineState.confirmedOutline = confirmedOutline
      const controller = controllerFixture()
      controller.canAdjustOutline.value = true
      const html = await renderToString(createSSRApp(Workspace.default, {
        store,
        controller,
      }))

      assert.match(html, /调整本章小纲/)
      assert.match(html, /采用后作为当前写作依据；正文定稿前仍可调整。/)
      assert.match(html, new RegExp(`>\\s*${label}\\s*<`))
      assert.doesNotMatch(html, /Session 已创建，小纲只读/)
    }
  } finally {
    await vite.close()
  }
})

test('outline workspace keeps server authority read-only and closes editing to the approved fields', async () => {
  const vite = await createVite()
  try {
    const Workspace = await vite.ssrLoadModule(
      '/src/components/planning/ChapterOutlineWorkspace.vue',
    )
    const html = await renderToString(createSSRApp(Workspace.default, {
      store: storeFixture(),
      controller: controllerFixture(),
    }))

    assert.match(html, /第 3 章/)
    assert.match(
      html,
      /<p class="authority-strip" aria-label="章节小纲状态"[^>]*>章节小纲依据已同步<\/p>/,
    )
    assert.doesNotMatch(
      html,
      /Planning|Canon|Projection|planning-4|R(?:2|4)\b/,
    )
    for (const label of [
      '所属分卷',
      '当前故事块',
      '关联阶段',
      '关联场景任务',
      '本章目标',
      '预计出场人物',
      '承接的未完成情节',
      '计划推进的任务',
      '主要场景',
      '不应提前发生',
    ]) {
      assert.match(html, new RegExp(label))
    }
    for (const canonicalOption of [
      'value="volume-1"',
      '第一卷',
      'value="block-1"',
      '夜入县衙',
      '潜入',
      '取得残卷',
    ]) {
      assert.match(html, new RegExp(canonicalOption))
    }
    assert.doesNotMatch(html, /旧卷|旧阶段/)
    assert.doesNotMatch(html, /编辑章节号|编辑 Planning|编辑 Canon|编辑 Projection/)
    assert.match(html, /小纲模型尚未就绪；手工编辑仍可继续/)
  } finally {
    await vite.close()
  }
})

test('real unavailable authority reason exposes both fixed upstream recovery links', async () => {
  const vite = await createVite()
  try {
    const Workspace = await vite.ssrLoadModule(
      '/src/components/planning/ChapterOutlineWorkspace.vue',
    )
    const store = storeFixture()
    store.outlineState.reasons = ['planningOrProjectionUnavailable']
    const controller = controllerFixture()
    controller.recoveryActions.value = [
      {
        label: '去确认创作圣经',
        path: '/projects/project-1/bible',
      },
      {
        label: '去补齐故事规划',
        path: '/projects/project-1/planning/story-blocks',
      },
    ]
    const html = await renderToString(createSSRApp(Workspace.default, {
      store,
      controller,
    }))

    assert.match(html, /href="\/projects\/project-1\/bible"/)
    assert.match(html, /去确认创作圣经/)
    assert.match(
      html,
      /href="\/projects\/project-1\/planning\/story-blocks"/,
    )
    assert.match(html, /去补齐故事规划/)
  } finally {
    await vite.close()
  }
})

test('backend create capability always exposes one explicit new-draft action', async () => {
  const vite = await createVite()
  try {
    const Workspace = await vite.ssrLoadModule(
      '/src/components/planning/ChapterOutlineWorkspace.vue',
    )
    for (const mode of ['confirmed-only', 'superseded']) {
      const store = storeFixture()
      const controller = controllerFixture()
      controller.canCreateDraft.value = true
      store.outlineState.capabilities.createDraft = true
      if (mode === 'confirmed-only') {
        store.outlineState.confirmedOutline = {
          outlineRevisionId: 'confirmed-1',
          content: outlineContent(),
        }
        store.outlineState.draft = null
        controller.editable.value = false
      } else {
        store.outlineState.draft.status = 'superseded'
        controller.readOnly.value = true
        controller.editable.value = false
      }

      const html = await renderToString(createSSRApp(Workspace.default, {
        store,
        controller,
      }))

      assert.match(html, /建立新工作稿/, mode)
      assert.match(html, /readonly/, mode)
      assert.equal(
        (
          html.match(
            /<button[^>]*>\s*建立新工作稿\s*<\/button>/g,
          ) || []
        ).length,
        1,
        mode,
      )
      assert.doesNotMatch(
        html,
        /href="\/projects\/project-1\/planning\/story-blocks"/,
        mode,
      )
    }
  } finally {
    await vite.close()
  }
})

test('authority refresh failure exposes a GET-only retry action with state present', async () => {
  const vite = await createVite()
  try {
    const Workspace = await vite.ssrLoadModule(
      '/src/components/planning/ChapterOutlineWorkspace.vue',
    )
    const store = storeFixture()
    store.outlineError = {
      code: 'ChapterOutlineRefreshFailed',
      message: '章节小纲工作稿已保存，但刷新失败',
    }
    store.outlineSaving = true
    const controller = controllerFixture()
    controller.busy.value = true
    const html = await renderToString(createSSRApp(Workspace.default, {
      store,
      controller,
    }))
    const contents = await readFile(
      source('components/planning/ChapterOutlineWorkspace.vue'),
      'utf8',
    )

    assert.match(html, /重新读取权威状态/)
    assert.match(
      html,
      /<button[^>]*disabled[^>]*>\s*重新读取权威状态\s*<\/button>/,
    )
    assert.match(
      contents,
      /@click="run\(\(\) => controller\.hydrate\(\{ force: true \}\)\)"/,
    )
  } finally {
    await vite.close()
  }
})

test('outline authority and actions remain shrinkable at the narrow breakpoint', async () => {
  const contents = await readFile(
    source('components/planning/ChapterOutlineWorkspace.vue'),
    'utf8',
  )
  const narrow = contents.match(/@media\s*\(max-width:760px\)\s*\{([\s\S]*)\}\s*<\/style>/)?.[1] || ''

  assert.match(narrow, /\.authority-strip\s*\{[^}]*width:\s*100%/)
  assert.match(
    contents,
    /<p class="authority-strip" aria-label="章节小纲状态">章节小纲依据已同步<\/p>/,
  )
  assert.doesNotMatch(contents, /<dl class="authority-strip"|\.authority-strip div/)
  assert.match(narrow, /\.outline-actions\s*\{[^}]*flex-wrap:\s*wrap/)
  assert.match(narrow, /\.outline-actions button\s*\{[^}]*width:\s*100%/)
})

test('outline selectors and save transport use exact server-returned node refs', async () => {
  const contents = await readFile(
    source('components/planning/ChapterOutlineWorkspace.vue'),
    'utf8',
  )
  assert.match(contents, /planningAuthority/)
  assert.match(contents, /node\.id/)
  assert.match(contents, /node\.revision/)
  assert.match(contents, /node\.contentHash/)
  assert.match(contents, /lifecycle === 'active'/)
  for (const field of [
    'volumeRef',
    'storyBlockRef',
    'stageRefs',
    'sceneTaskRefs',
    'chapterGoal',
    'expectedCharacters',
    'continuation',
    'plannedTasks',
    'scenes',
    'forbiddenEarlyEvents',
  ]) {
    assert.match(contents, new RegExp(field))
  }
  for (const forbidden of [
    'targetChapterCount',
    'completed',
    'actualProgress',
    'providerId',
    'rawOutput',
  ]) {
    assert.doesNotMatch(contents, new RegExp(forbidden))
  }
})

test('history drawer is immutable, status-aware, and has no authoring actions', async () => {
  const vite = await createVite()
  try {
    const Drawer = await vite.ssrLoadModule(
      '/src/components/planning/ChapterOutlineHistoryDrawer.vue',
    )
    const context = {}
    await renderToString(createSSRApp(Drawer.default, {
      open: true,
      history: [{
        projectId: 'project-1',
        chapterNumber: 3,
        outlineRevisionId: 'outline-1',
        revision: 1,
        parentRevision: 0,
        contentHash: HASH,
        content: outlineContent(),
        basis: {},
        status: 'session_pinned',
        reason: 'activeOrHistoricalSession',
      }],
    }), context)
    const html = context.teleports?.body || ''

    assert.match(html, /章节小纲历史/)
    assert.match(html, /第 3 章/)
    assert.match(html, /已钉住写作会话/)
    assert.match(html, /取得残卷/)
    assert.doesNotMatch(html, /保存|确认|生成|编辑|克隆/)
  } finally {
    await vite.close()
  }
})

test('embedded outline workspace is mounted only beneath the story-block editor', async () => {
  const contents = await readFile(
    source('components/planning/PlanningWorkspace.vue'),
    'utf8',
  )
  const storyBlockPosition = contents.indexOf('<story-block-editor')
  const outlinePosition = contents.indexOf('<chapter-outline-workspace')
  assert.ok(storyBlockPosition >= 0)
  assert.ok(outlinePosition > storyBlockPosition)
  assert.match(
    contents.slice(storyBlockPosition, outlinePosition + 100),
    /activeTab === 'story-blocks'/,
  )
})
