import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import test from 'node:test'

const requireFromFrontend = createRequire(
  new URL('../../frontend/package.json', import.meta.url),
)
const { parse } = requireFromFrontend('@babel/parser')

const readWorkspaceFile = async relativePath => {
  try {
    return await readFile(new URL(`../../${relativePath}`, import.meta.url), 'utf8')
  } catch (error) {
    if (error?.code === 'ENOENT') return ''
    throw error
  }
}

const FUNCTION_LIKE_TYPES = new Set([
  'ArrowFunctionExpression', 'ClassMethod', 'ClassPrivateMethod',
  'FunctionDeclaration', 'FunctionExpression', 'ObjectMethod',
])

const childNodes = node => Object.values(node).flatMap(value => {
  if (Array.isArray(value)) return value.filter(child => typeof child?.type === 'string')
  return value && typeof value.type === 'string' ? [value] : []
})

const walkAst = (node, visit, skipNestedFunctions = false) => {
  if (!node || typeof node.type !== 'string') return
  if (skipNestedFunctions && FUNCTION_LIKE_TYPES.has(node.type)) return
  visit(node)
  for (const child of childNodes(node)) walkAst(child, visit, skipNestedFunctions)
}

const findNamedAsyncFunction = (source, functionName) => {
  const matches = []
  walkAst(parse(source, { sourceType: 'module' }), node => {
    if (
      node.type === 'FunctionDeclaration'
      && node.id?.name === functionName
    ) matches.push(node)
  })
  assert.equal(matches.length, 1, `expected one named async function: ${functionName}`)
  const [match] = matches
  assert.equal(match.async, true)
  assert.equal(match.generator, false)
  assert.equal(match.params.length, 0)
  return match
}

const directExecutionNodes = functionOrBlock => {
  const nodes = []
  const root = functionOrBlock.type === 'BlockStatement' ? functionOrBlock : functionOrBlock.body
  const walkDirect = node => {
    if (!node || typeof node.type !== 'string' || FUNCTION_LIKE_TYPES.has(node.type)) return
    nodes.push(node)
    if (node.type === 'IfStatement' && node.test.type === 'BooleanLiteral') {
      walkDirect(node.test.value ? node.consequent : node.alternate)
      return
    }
    for (const child of childNodes(node)) walkDirect(child)
  }
  walkDirect(root)
  return nodes
}

const isIdentifier = (node, name) => node?.type === 'Identifier' && node.name === name

const isIdentifierCall = (node, name) => (
  node?.type === 'CallExpression'
  && isIdentifier(node.callee, name)
  && node.arguments.length === 0
)

const isPageCall = (node, method) => (
  isReceiverCall(node, 'page', method)
)

const isReceiverCall = (node, receiver, method) => (
  node?.type === 'CallExpression'
  && node.callee?.type === 'MemberExpression'
  && node.callee.computed === false
  && isIdentifier(node.callee.object, receiver)
  && isIdentifier(node.callee.property, method)
)

const patternBindsIdentifier = (node, name) => {
  if (isIdentifier(node, name)) return true
  if (node?.type === 'ArrayPattern') {
    return node.elements.some(element => patternBindsIdentifier(element, name))
  }
  if (node?.type === 'ObjectPattern') {
    return node.properties.some(property => (
      property?.type === 'RestElement'
        ? patternBindsIdentifier(property.argument, name)
        : patternBindsIdentifier(property?.value, name)
    ))
  }
  if (node?.type === 'RestElement') return patternBindsIdentifier(node.argument, name)
  if (node?.type === 'AssignmentPattern') return patternBindsIdentifier(node.left, name)
  return false
}

const functionOwnsIdentifier = (functionNode, name) => {
  if (functionNode.params.some(parameter => patternBindsIdentifier(parameter, name))) {
    return true
  }
  let ownsIdentifier = false
  const scan = node => {
    if (!node || typeof node.type !== 'string' || ownsIdentifier) return
    if (node !== functionNode.body && FUNCTION_LIKE_TYPES.has(node.type)) return
    if (
      (node.type === 'VariableDeclarator' && patternBindsIdentifier(node.id, name))
      || (node.type === 'CatchClause' && patternBindsIdentifier(node.param, name))
    ) {
      ownsIdentifier = true
      return
    }
    for (const child of childNodes(node)) scan(child)
  }
  scan(functionNode.body)
  return ownsIdentifier
}

const observerPageMutations = observer => {
  const mutations = []
  const visit = node => {
    if (!node || typeof node.type !== 'string') return
    if (FUNCTION_LIKE_TYPES.has(node.type) && functionOwnsIdentifier(node, 'page')) {
      return
    }
    if (
      (node.type === 'AssignmentExpression' && patternBindsIdentifier(node.left, 'page'))
      || (node.type === 'UpdateExpression' && patternBindsIdentifier(node.argument, 'page'))
      || (node.type === 'VariableDeclarator' && patternBindsIdentifier(node.id, 'page'))
      || (
        ['ForInStatement', 'ForOfStatement'].includes(node.type)
        && node.left?.type !== 'VariableDeclaration'
        && patternBindsIdentifier(node.left, 'page')
      )
    ) mutations.push(node)
    for (const child of childNodes(node)) visit(child)
  }
  for (const statement of observer.body.body) visit(statement)
  return mutations
}

const drainKind = node => {
  const call = node?.type === 'AwaitExpression' ? node.argument : null
  if (
    call?.type !== 'CallExpression'
    || !isIdentifier(call.callee, 'readBeforeDeadline')
    || call.arguments.length !== 3
    || !isIdentifier(call.arguments[1], 'deadline')
    || !isIdentifier(call.arguments[2], 'settleTimeoutMessage')
  ) return null
  const callback = call.arguments[0]
  if (
    callback?.type !== 'ArrowFunctionExpression'
    || callback.async
    || callback.params.length !== 0
    || callback.body?.type !== 'CallExpression'
    || callback.body.arguments.length !== 0
  ) return null
  if (isIdentifier(callback.body.callee, 'drainPendingRequests')) return 'Requests'
  if (isIdentifier(callback.body.callee, 'drainPendingApiBodies')) return 'ApiBodies'
  return null
}

const assertSettleContract = source => {
  const settle = findNamedAsyncFunction(source, 'settle')
  const calls = directExecutionNodes(settle)
    .flatMap(node => {
      const kind = drainKind(node)
      return kind ? [[node.start, kind]] : []
    })
    .sort((left, right) => left[0] - right[0])
    .map(([, kind]) => kind)
  assert.deepEqual(calls, ['Requests', 'ApiBodies', 'Requests', 'ApiBodies'])
}

const assertFinishContract = source => {
  const finish = findNamedAsyncFunction(source, 'finish')
  const finalizingTryStatements = finish.body.body.filter(
    statement => statement.type === 'TryStatement' && statement.finalizer,
  )
  assert.equal(finalizingTryStatements.length, 1)
  const [{ block, finalizer }] = finalizingTryStatements
  const coreOperations = []
  for (const statement of block.body) {
    if (
      ['ReturnStatement', 'ThrowStatement'].includes(statement.type)
      && coreOperations.length < 3
    ) assert.fail('finish core is unreachable after an abrupt statement')
    const node = statement.type === 'ExpressionStatement' ? statement.expression : null
    if (node?.type === 'AwaitExpression' && isIdentifierCall(node.argument, 'settle')) {
      coreOperations.push([node.start, 'settle'])
    } else if (
      node?.type === 'AssignmentExpression' && node.operator === '='
      && isIdentifier(node.left, 'pageContent') && node.right?.type === 'AwaitExpression'
      && isPageCall(node.right.argument, 'content') && node.right.argument.arguments.length === 0
    ) coreOperations.push([node.start, 'pageContent'])
  }
  const orderedCoreOperations = coreOperations
    .sort((left, right) => left[0] - right[0])
    .map(([, kind]) => kind)
  assert.deepEqual(orderedCoreOperations, ['settle', 'pageContent', 'settle'])

  assert.equal(finalizer.type, 'BlockStatement')
  const detachments = finalizer.body.map(statement => {
    const node = statement.type === 'ExpressionStatement' ? statement.expression : null
    if (
      node?.type !== 'CallExpression'
      || node.callee?.type !== 'MemberExpression'
      || node.callee.computed !== false
      || !['page', 'context'].includes(node.callee.object?.name)
      || !isIdentifier(node.callee.property, 'off')
      || node.arguments.length !== 2
      || node.arguments[0]?.type !== 'StringLiteral'
      || node.arguments[1]?.type !== 'Identifier'
    ) return null
    return [node.callee.object.name, node.arguments[0].value, node.arguments[1].name]
  })
  assert.deepEqual(detachments, [
    ['context', 'request', 'onRequest'],
    ['context', 'requestfinished', 'onRequestFinished'],
    ['context', 'response', 'onResponse'],
    ['page', 'console', 'onConsole'],
    ['page', 'pageerror', 'onPageError'],
    ['context', 'requestfailed', 'onRequestFailed'],
  ])
}

const assertListenerOwnershipContract = source => {
  const observer = findNamedFunction(source, 'observeRuntime')
  const expectedAttachments = [
    ['context', 'request', 'onRequest'],
    ['context', 'requestfinished', 'onRequestFinished'],
    ['context', 'response', 'onResponse'],
    ['page', 'console', 'onConsole'],
    ['page', 'pageerror', 'onPageError'],
    ['context', 'requestfailed', 'onRequestFailed'],
  ]
  const controlledEvents = new Set(expectedAttachments.map(([, event]) => event))
  const listenerSignature = node => {
    if (
      node?.type !== 'CallExpression'
      || node.callee?.type !== 'MemberExpression'
      || node.callee.computed !== false
      || !isIdentifier(node.callee.property, 'on')
      || node.arguments[0]?.type !== 'StringLiteral'
      || !controlledEvents.has(node.arguments[0].value)
    ) return null
    return [
      node.callee.object?.name,
      node.arguments[0].value,
      node.arguments[1]?.name,
    ]
  }
  assert.equal(
    isIdentifier(observer.params[0], 'page'),
    true,
    'observeRuntime must receive page as its first parameter',
  )
  const contextBindings = []
  walkAst(observer.body, node => {
    if (node.type === 'VariableDeclarator' && isIdentifier(node.id, 'context')) {
      contextBindings.push(node)
    }
  })
  assert.equal(contextBindings.length, 1, 'context must be bound exactly once')
  const topLevelContextBindings = observer.body.body.flatMap(statement => (
    statement.type === 'VariableDeclaration' && statement.kind === 'const'
      ? statement.declarations.filter(declaration => (
        isIdentifier(declaration.id, 'context')
        && isPageCall(declaration.init, 'context')
        && declaration.init.arguments.length === 0
      ))
      : []
  ))
  assert.deepEqual(
    topLevelContextBindings,
    contextBindings,
    'context must be the top-level const binding from page.context()',
  )
  const topLevelAttachmentRecords = observer.body.body.flatMap(statement => (
    statement.type === 'ExpressionStatement'
      ? [listenerSignature(statement.expression)]
        .filter(Boolean)
        .map(signature => [statement.start, signature])
      : []
  ))
  const topLevelAttachments = topLevelAttachmentRecords.map(([, signature]) => signature)
  assert.deepEqual(topLevelAttachments, expectedAttachments)
  assert.equal(
    contextBindings[0].start < topLevelAttachmentRecords[0][0],
    true,
    'context must be bound before listener registration',
  )
  const listenerSetupEnd = topLevelAttachmentRecords.at(-1)[0]
  assert.equal(
    directExecutionNodes(observer).some(node => (
      ['ReturnStatement', 'ThrowStatement'].includes(node.type)
      && node.start < listenerSetupEnd
    )),
    false,
    'listener setup must not be preceded by an abrupt statement',
  )
  const pageMutations = observerPageMutations(observer)
  assert.equal(pageMutations.length, 0, 'page must not be reassigned or updated')
  const allAttachments = []
  walkAst(observer.body, node => {
    const signature = listenerSignature(node)
    if (signature) allAttachments.push(signature)
  })
  assert.deepEqual(allAttachments, expectedAttachments)
}

const findNamedFunction = (source, functionName) => {
  const matches = []
  walkAst(parse(source, { sourceType: 'module' }), node => {
    if (node.type === 'FunctionDeclaration' && node.id?.name === functionName) {
      matches.push(node)
    }
  })
  assert.equal(matches.length, 1, `expected one named function: ${functionName}`)
  return matches[0]
}

test('Playwright config owns two isolated loopback servers and repository artifacts', async () => {
  const source = await readWorkspaceFile('frontend/playwright.config.ts')

  assert.match(source, /defineConfig/)
  assert.match(source, /baseURL:\s*['"]http:\/\/127\.0\.0\.1:5173['"]/)
  assert.match(source, /127\.0\.0\.1.*8000/)
  assert.match(source, /127\.0\.0\.1.*5173/)
  assert.equal((source.match(/reuseExistingServer:\s*false/g) || []).length, 2)
  assert.match(source, /outputDir:\s*['"]\.\.\/output\/playwright\/test-results['"]/)
  assert.match(source, /trace:\s*['"]retain-on-failure['"]/)
  assert.match(source, /screenshot:\s*['"]only-on-failure['"]/)
  assert.match(source, /process\.env\.PYTHON\s*\|\|\s*['"]python['"]/)
  assert.match(source, /shellQuoteExecutable/)
  assert.match(source, /command:\s*`\$\{pythonExecutable\}\s+-m\s+uvicorn/)
})

test('M1 browser spec defines exactly two real-page goals with no direct API writes', async () => {
  const source = await readWorkspaceFile('frontend/e2e/milestone1.spec.ts')

  assert.equal((source.match(/\btest\s*\(/g) || []).length, 2)
  assert.match(source, /page\.goto\(['"]\/['"]\)/)
  assert.match(source, /page\.goto\(['"]\/writer\/project-1\/1['"]\)/)
  assert.doesNotMatch(source, /page\.request|request\.(?:post|put|patch|delete)\s*\(|fetch\s*\(|route\.(?:fulfill|continue)\s*\(/)
})

test('M1 browser spec awaits every API body and rejects runtime failures and leaks', async () => {
  const [source, observer] = await Promise.all([
    readWorkspaceFile('frontend/e2e/milestone1.spec.ts'),
    readWorkspaceFile('frontend/e2e/runtime-observer.mjs'),
  ])
  const combined = `${source}\n${observer}`
  const drainCalls = ['Requests', 'ApiBodies', 'Requests', 'ApiBodies']
    .map(kind => `await readBeforeDeadline(() => drainPending${kind}(), deadline, settleTimeoutMessage)`)
    .join('\n')
  const finishFlow = `
    try {
      await settle()
      pageContent = await page.content()
      await settle()
    } finally {
      context.off('request', onRequest)
      context.off('requestfinished', onRequestFinished)
      context.off('response', onResponse)
      page.off('console', onConsole)
      page.off('pageerror', onPageError)
      context.off('requestfailed', onRequestFailed)
    }
  `
  const listenerAttachmentFlow = `
    context.on('request', onRequest)
    context.on('requestfinished', onRequestFinished)
    context.on('response', onResponse)
    page.on('console', onConsole)
    page.on('pageerror', onPageError)
    context.on('requestfailed', onRequestFailed)
  `
  const listenerOwnerPreamble = `
    const context = page.context()
  `
  const equivalentListenerFormatting = `
    function observeRuntime ( page ) {
      const context = page . context ( )
      ${listenerAttachmentFlow.replaceAll('.', ' . ')}
    }
  `
  const crossFunctionDecoy = `
    async function finish() {}
    async function unrelated() { ${finishFlow} }
  `
  const stringDeclarationDecoy = `const decoy = ${JSON.stringify(
    `async function settle() { ${drainCalls} }`,
  )}`
  const commentDeclarationDecoy = `/* async function finish() { ${finishFlow} } */`
  const nestedSettleDecoy = `
    async function settle() { async function neverCalled() { ${drainCalls} } }
  `
  const conciseNestedSettleDecoy = `
    async function settle() {
      const neverCalled = async () => (${drainCalls.replaceAll('\n', ',\n')})
    }
  `
  const objectMethodSettleDecoy = `
    async function settle() {
      const neverCalled = { async collect() { ${drainCalls} } }
    }
  `
  const conditionalSettleDecoy = `
    async function settle() { if (false) { ${drainCalls} } }
  `
  const nestedFinishDecoy = `
    async function finish() { const neverCalled = async () => { ${finishFlow} } }
  `
  const splitFinishDecoy = `
    async function finish() {
      await settle()
      pageContent = await page.content()
      await settle()
      try {} finally {
        context.off('request', onRequest)
        context.off('requestfinished', onRequestFinished)
        context.off('response', onResponse)
        page.off('console', onConsole)
        page.off('pageerror', onPageError)
        context.off('requestfailed', onRequestFailed)
      }
    }
  `
  const conditionalFinishDecoy = `
    async function finish() { if (false) { ${finishFlow} } }
  `
  const returnBeforeCoreFinishDecoy = `
    async function finish() { ${finishFlow.replace('try {', 'try { return;')} }
  `
  const throwBeforeCoreFinishDecoy = `
    async function finish() { ${finishFlow.replace('try {', 'try { throw new Error();')} }
  `
  const wrongListenerReceiverDecoy = `
    function observeRuntime(page) {
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow.replace("context.on('response'", "page.on('response'")}
    }
  `
  const nestedListenerDecoy = `
    function observeRuntime(page) {
      ${listenerOwnerPreamble}
      const neverCalled = () => { ${listenerAttachmentFlow} }
    }
  `
  const foreignContextListenerDecoy = `
    function observeRuntime(page) {
      const context = unrelated.context()
      ${listenerAttachmentFlow}
    }
  `
  const unboundPageListenerDecoy = `
    function observeRuntime() {
      const context = page.context()
      ${listenerAttachmentFlow}
    }
  `
  const wrongFirstParameterDecoy = `
    function observeRuntime(options, page) {
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
    }
  `
  const earlyReturnListenerDecoy = `
    function observeRuntime(page) {
      return
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
    }
  `
  const earlyThrowListenerDecoy = `
    function observeRuntime(page) {
      throw new Error('unreachable listener setup')
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
    }
  `
  const pageReassignmentListenerDecoy = `
    function observeRuntime(page) {
      page = unrelated.page()
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
    }
  `
  const pageUpdateListenerDecoy = `
    function observeRuntime(page) {
      page++
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
    }
  `
  const arrayPageAssignmentDecoy = `
    function observeRuntime(page) {
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
      [page] = [unrelated.page()]
    }
  `
  const variablePageBindingDecoy = `
    function observeRuntime(page) {
      var page = unrelated.page()
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
    }
  `
  const forOfPageAssignmentDecoy = `
    function observeRuntime(page) {
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
      for (page of [unrelated.page()]) {}
    }
  `
  const nestedShadowedPageFormatting = `
    function observeRuntime(page) {
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
      const unrelated = page => { page = unrelatedPage() }
    }
  `
  const nestedFakeContextDecoy = `
    function observeRuntime(page) {
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
      const neverCalled = () => {
        const context = unrelated.context()
        context.on('response', onResponse)
      }
    }
  `
  const shadowedPageListenerDecoy = `
    function observeRuntime(page) {
      ${listenerOwnerPreamble}
      ${listenerAttachmentFlow}
      const neverCalled = () => {
        const page = unrelated.page()
        page.on('console', onConsole)
      }
    }
  `
  const equivalentFormatting = `
    async  function settle ( ) {
      const ignoredBrace = "}"
      // await readBeforeDeadline(() => drainPendingApiBodies())
      await readBeforeDeadline ( ( ) => drainPendingRequests ( ), deadline, settleTimeoutMessage )
      await readBeforeDeadline ( ( ) => drainPendingApiBodies ( ), deadline, settleTimeoutMessage )
      await readBeforeDeadline ( ( ) => drainPendingRequests ( ), deadline, settleTimeoutMessage )
      await readBeforeDeadline ( ( ) => drainPendingApiBodies ( ), deadline, settleTimeoutMessage )
    }
    async  function finish ( ) {
      let pageContent = ''
      try {
        await settle ( )
        pageContent = await page.content ( )
        await settle ( )
      } finally {
        context.off ( "request", onRequest )
        context.off ( "requestfinished", onRequestFinished )
        context.off ( "response", onResponse )
        page.off ( "console", onConsole )
        page.off ( "pageerror", onPageError )
        context.off ( "requestfailed", onRequestFailed )
      }
    }
  `

  for (const required of [
    'pendingApiBodies.add', 'response.text()',
    'Promise.all(batch)', 'response.status()', 'consoleErrors',
    'response.request().method()', 'consoleMessages', 'pageErrors',
    'requestFailures', 'responseFailures', 'apiFailures', 'apiWriteMethods',
    'apiBodyReadFailures', 'apiHeaderReadFailures', 'bodyReadError',
    'headersReadError', 'response.allHeaders()', 'page.content()',
    'requiredTestEnvironment',
    'BROWSER_SECRET_SENTINEL', 'BROWSER_PRIVATE_PROVIDER_URL',
    'BROWSER_TEST_DATABASE', 'api[_-]?key',
  ]) {
    assert.equal(combined.includes(required), true, `missing browser diagnostic contract: ${required}`)
  }
  assert.match(observer, /new Set\(\)/)
  assert.match(observer, /while\s*\(pendingApiBodies\.size\)/)
  assert.doesNotThrow(() => assertListenerOwnershipContract(equivalentListenerFormatting))
  assert.doesNotThrow(() => assertListenerOwnershipContract(nestedShadowedPageFormatting))
  assert.doesNotThrow(() => assertListenerOwnershipContract(observer))
  assert.doesNotThrow(() => assertSettleContract(equivalentFormatting))
  assert.doesNotThrow(() => assertFinishContract(equivalentFormatting))
  const acceptedDecoys = [
    ['string declaration', () => assertSettleContract(stringDeclarationDecoy)],
    ['comment declaration', () => assertFinishContract(commentDeclarationDecoy)],
    ['nested settle function', () => assertSettleContract(nestedSettleDecoy)],
    ['nested settle concise arrow', () => assertSettleContract(conciseNestedSettleDecoy)],
    ['nested settle object method', () => assertSettleContract(objectMethodSettleDecoy)],
    ['conditional settle drains', () => assertSettleContract(conditionalSettleDecoy)],
    ['nested finish arrow', () => assertFinishContract(nestedFinishDecoy)],
    ['split finish try', () => assertFinishContract(splitFinishDecoy)],
    ['conditional finish try', () => assertFinishContract(conditionalFinishDecoy)],
    ['return before finish core', () => assertFinishContract(returnBeforeCoreFinishDecoy)],
    ['throw before finish core', () => assertFinishContract(throwBeforeCoreFinishDecoy)],
    ['wrong listener receiver', () => assertListenerOwnershipContract(wrongListenerReceiverDecoy)],
    ['nested listener attachment', () => assertListenerOwnershipContract(nestedListenerDecoy)],
    ['foreign context listener owner', () => assertListenerOwnershipContract(foreignContextListenerDecoy)],
    ['unbound page listener owner', () => assertListenerOwnershipContract(unboundPageListenerDecoy)],
    ['wrong first observer parameter', () => assertListenerOwnershipContract(wrongFirstParameterDecoy)],
    ['return before listener setup', () => assertListenerOwnershipContract(earlyReturnListenerDecoy)],
    ['throw before listener setup', () => assertListenerOwnershipContract(earlyThrowListenerDecoy)],
    ['page reassignment before listener setup', () => assertListenerOwnershipContract(pageReassignmentListenerDecoy)],
    ['page update before listener setup', () => assertListenerOwnershipContract(pageUpdateListenerDecoy)],
    ['array page assignment', () => assertListenerOwnershipContract(arrayPageAssignmentDecoy)],
    ['variable page binding', () => assertListenerOwnershipContract(variablePageBindingDecoy)],
    ['for-of page assignment', () => assertListenerOwnershipContract(forOfPageAssignmentDecoy)],
    ['nested fake context listener', () => assertListenerOwnershipContract(nestedFakeContextDecoy)],
    ['shadowed page listener', () => assertListenerOwnershipContract(shadowedPageListenerDecoy)],
  ].flatMap(([label, verify]) => {
    try {
      verify()
      return [label]
    } catch {
      return []
    }
  })
  assert.deepEqual(acceptedDecoys, [])
  assert.doesNotThrow(() => assertSettleContract(observer))
  assert.throws(() => assertFinishContract(crossFunctionDecoy))
  assert.doesNotThrow(() => assertFinishContract(observer))
  assert.match(source, /READ_METHODS\.has\(response\.method\)/)
  assert.match(source, /expect\(apiWriteMethods[^]*?\.toEqual\(\[\]\)/)
  assert.match(source, /expect\(apiBodyReadFailures[^]*?\.toEqual\(\[\]\)/)
  assert.match(source, /expect\(apiHeaderReadFailures[^]*?\.toEqual\(\[\]\)/)
  assert.match(source, /expect\(responseFailures[^]*?\.toEqual\(\[\]\)/)
  assert.match(source, /pageContent/)
  assert.doesNotMatch(source, /browser-secret-must-not-leak|private-provider\.example/)
})

test('M1 browser goals cover foundation state, disabled writer, settings read and old URL return', async () => {
  const source = await readWorkspaceFile('frontend/e2e/milestone1.spec.ts')

  for (const required of [
    '永乐大典', '永乐长明', '文渊山海', '典镇山河', '已选定',
    'writer-core-v1.0.0', 'Canon 0', 'Projection 0', '状态同步',
    '进入写作台', 'toBeDisabled', '设置', '写作内核尚未开放',
    '旧章节、临时草稿和版本定稿链已停用', '返回项目',
    'toHaveURL',
  ]) {
    assert.equal(source.includes(required), true, `missing M1 browser assertion: ${required}`)
  }
  assert.match(
    source,
    /getByRole\(['"]menuitem['"],\s*\{\s*name:\s*['"]项目库['"]\s*\}\)\.click\(\)[^]*?getByRole\(['"]heading['"],\s*\{\s*name:\s*['"]永乐大典['"]/,
  )
  assert.doesNotMatch(
    source,
    /getByRole\(['"]menuitem['"],\s*\{\s*name:\s*['"]永乐大典['"]/,
  )
})

test('frontend retains guarded M1 and Phase 2C gates while defaulting e2e to full Phase 2', async () => {
  const packageJson = JSON.parse(await readWorkspaceFile('frontend/package.json'))

  assert.equal(packageJson.scripts?.['test:e2e:m1'], 'node e2e/run-milestone1.mjs')
  assert.equal(packageJson.scripts?.['test:e2e:phase2c'], 'node e2e/run-phase2c.mjs')
  assert.equal(packageJson.scripts?.['test:e2e'], 'node e2e/run-phase2.mjs')
})

test('runner injects fixture leak sentinels while the spec contains no literal values', async () => {
  const [runner, prepare, spec] = await Promise.all([
    readWorkspaceFile('frontend/e2e/run-milestone1.mjs'),
    readWorkspaceFile('backend/scripts/prepare_milestone1_browser_db.py'),
    readWorkspaceFile('frontend/e2e/milestone1.spec.ts'),
  ])
  const fixtures = [
    ['BROWSER_SECRET_SENTINEL', 'browser-secret-must-not-leak'],
    ['BROWSER_PRIVATE_PROVIDER_URL', 'https://private-provider.example/v1'],
  ]
  for (const [environmentName, value] of fixtures) {
    assert.equal(runner.includes(environmentName), true)
    assert.equal(runner.includes(value), true)
    assert.equal(prepare.includes(value), true)
    assert.equal(spec.includes(value), false)
  }
  assert.match(runner, /BROWSER_TEST_DATABASE:\s*databaseName/)
})
