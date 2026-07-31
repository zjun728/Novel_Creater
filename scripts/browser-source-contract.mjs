import { createRequire } from 'node:module'
import path from 'node:path'

const requireFrontendDependency = createRequire(new URL('../frontend/package.json', import.meta.url))
const { parse } = requireFrontendDependency('@babel/parser')

const FORBIDDEN_MODULES = new Set([
  'axios',
  'got',
  'http',
  'https',
  'node:http',
  'node:https',
  'undici',
])
const FORBIDDEN_IDENTIFIERS = new Set([
  'XMLHttpRequest',
  'api',
  'axios',
  'fetch',
  'got',
  'http',
  'https',
  'undici',
])
const FORBIDDEN_MEMBER_PROPERTIES = new Map([
  ['globalThis', new Set(['XMLHttpRequest', 'fetch'])],
  ['http', new Set(['createConnection', 'get', 'request'])],
  ['https', new Set(['createConnection', 'get', 'request'])],
  ['page', new Set(['request', 'route'])],
  ['request', new Set(['delete', 'patch', 'post', 'put'])],
  ['route', new Set(['abort', 'continue', 'fallback', 'fulfill'])],
  ['self', new Set(['XMLHttpRequest', 'fetch'])],
  ['window', new Set(['XMLHttpRequest', 'fetch'])],
])
const FORBIDDEN_ANY_MEMBER_ROOTS = new Set(['api', 'axios', 'got', 'undici'])
const ALIAS_PROTECTED_IDENTIFIERS = new Set(['page', 'request', 'route'])
const PRODUCT_API_CLIENT = /(?:^|\/)api\/db\/client(?:\.[cm]?[jt]s)?$/iu

export function assertSafeBrowserSource(source, options = {}) {
  analyzeBrowserSource(source, options.sourceName)
}

export function collectBrowserTestDeclarations(source, sourceName) {
  const program = parseBrowserSourceAst(source, sourceName)
  const declarations = []
  walkAst(program, null, null, node => {
    if (node.type !== 'CallExpression') return
    const testCall = testCallModifiers(node.callee)
    if (testCall === null) return
    const title = getStaticString(node.arguments[0])
    const callback = testDeclarationCallback(node.arguments)
    const requiresDeclaration = testCall.modifiers.length === 0 || testCall.modifiers.includes('only')
    if (requiresDeclaration) {
      if (title === null) throw new Error('browser test declaration requires a static title')
      if (!callback) throw new Error('browser test declaration must have a callback')
    } else if (isRuntimeTestAnnotation(testCall.modifiers, node.arguments, title)) {
      return
    } else {
      if (title === null) throw new Error('browser test declaration requires a static title')
      if (!callback) throw new Error('browser test declaration must have a callback')
    }
    if (testCall.hasDynamicModifier) throw new Error('browser test declaration modifier must be static')
    declarations.push({
      title,
      modifiers: testCall.modifiers,
      bodySource: callback.functionNode ? source.slice(callback.functionNode.body.start, callback.functionNode.body.end) : '',
      calls: callback.functionNode ? collectExecutedCallNames(callback.functionNode.body) : new Set(),
    })
  })
  return declarations
}

export function collectBrowserFunctionGraph(source, sourceName) {
  const program = parseBrowserSourceAst(source, sourceName)
  const functions = new Map()
  walkAst(program, null, null, node => {
    const named = namedFunctionNode(node)
    if (!named) return
    if (functions.has(named.name)) throw new Error('duplicate browser helper function: ' + named.name)
    functions.set(named.name, {
      bodySource: source.slice(named.functionNode.body.start, named.functionNode.body.end),
      calls: collectDirectCallNames(named.functionNode.body),
    })
  })
  return functions
}

function parseBrowserSourceAst(source, sourceName) {
  if (typeof source !== 'string') throw new TypeError('browser source must be a string')
  try {
    return parse(source, {
      allowAwaitOutsideFunction: true,
      createImportExpressions: true,
      plugins: ['dynamicImport', 'importAttributes', 'jsx', 'topLevelAwait', 'typescript'],
      sourceType: 'unambiguous',
    }).program
  } catch (error) {
    const location = sourceName ? ' in ' + sourceName : ''
    throw new Error('invalid browser source' + location + ': ' + error.message)
  }
}

export function assertSafeBrowserGraph(entry, readSource) {
  if (typeof entry !== 'string' || entry.trim() === '') {
    throw new TypeError('browser graph entry must be a non-empty string')
  }
  if (typeof readSource !== 'function') throw new TypeError('readSource must be a function')
  assertRepositoryRelativePath(entry, 'outside browser source root')

  const normalizedEntry = normalizeGraphPath(entry)
  const root = path.posix.dirname(normalizedEntry)
  const visited = new Set()

  function visit(fileName) {
    if (visited.has(fileName)) return
    const source = readSource(fileName)
    if (typeof source !== 'string') throw new Error('missing browser source: ' + fileName)

    visited.add(fileName)
    const imports = analyzeBrowserSource(source, fileName)
    for (const specifier of imports) {
      if (isAbsolutePath(specifier)) {
        throw new Error('outside browser source root: ' + specifier + ' from ' + fileName)
      }
      if (!specifier.startsWith('.')) continue
      const resolved = normalizeGraphPath(path.posix.join(
        path.posix.dirname(fileName),
        specifier,
      ))
      if (!isWithinRoot(resolved, root)) {
        throw new Error('outside browser source root: ' + specifier + ' from ' + fileName)
      }
      visit(resolved)
    }
  }

  visit(normalizedEntry)
}

function analyzeBrowserSource(source, sourceName) {
  const program = parseBrowserSourceAst(source, sourceName)

  const imports = []
  walkAst(program, null, null, (node, parent, key) => {
    if (node.type === 'ImportDeclaration'
      || node.type === 'ExportAllDeclaration'
      || node.type === 'ExportNamedDeclaration') {
      if (node.source) registerModuleSpecifier(node.source.value, imports, sourceName)
    }

    if (node.type === 'ImportExpression') {
      const specifier = getStaticString(node.source)
      if (specifier === null) throwUnsafe('unresolved dynamic import', sourceName)
      registerModuleSpecifier(specifier, imports, sourceName)
    }

    if (node.type === 'CallExpression') {
      if (node.callee?.type === 'Import') {
        const specifier = getStaticString(node.arguments[0])
        if (specifier === null) throwUnsafe('unresolved dynamic import', sourceName)
        registerModuleSpecifier(specifier, imports, sourceName)
      }
      if (node.callee?.type === 'Identifier' && node.callee.name === 'require') {
        const specifier = getStaticString(node.arguments[0])
        if (specifier === null) throwUnsafe('unresolved require', sourceName)
        registerModuleSpecifier(specifier, imports, sourceName)
      }
    }

    if (node.type === 'MemberExpression' || node.type === 'OptionalMemberExpression') {
      assertSafeMember(node, sourceName)
    }
    if (node.type === 'ObjectProperty'
      && parent?.type === 'ObjectPattern'
      && ['request', 'route'].includes(getObjectPropertyName(node))) {
      throwUnsafe('destructured browser network capability', sourceName)
    }
    if (node.type === 'NewExpression'
      && node.callee?.type === 'Identifier'
      && node.callee.name === 'XMLHttpRequest') {
      throwUnsafe('XMLHttpRequest', sourceName)
    }
    if (node.type === 'Identifier'
      && FORBIDDEN_IDENTIFIERS.has(node.name)
      && isReferenceIdentifier(parent, key)) {
      throwUnsafe(node.name, sourceName)
    }
    if ((node.type === 'VariableDeclarator' || node.type === 'AssignmentExpression')
      && isProtectedAlias(node.type === 'VariableDeclarator' ? node.init : node.right)) {
      throwUnsafe('aliased browser network capability', sourceName)
    }
  })
  return imports
}

function testCallModifiers(callee) {
  const modifiers = []
  let hasDynamicModifier = false
  let current = unwrapExpression(callee)
  while (current?.type === 'MemberExpression' || current?.type === 'OptionalMemberExpression') {
    const modifier = getStaticMemberProperty(current)
    if (modifier === null) hasDynamicModifier = true
    else modifiers.unshift(modifier)
    current = unwrapExpression(current.object)
  }
  if (current?.type !== 'Identifier' || current.name !== 'test') return null
  if (modifiers.length > 0 && !modifiers.every(modifier => ['only', 'skip', 'fixme', 'fail', 'slow'].includes(modifier))) return null
  return { modifiers, hasDynamicModifier }
}

function testDeclarationCallback(argumentsList) {
  const callback = unwrapExpression(argumentsList.at(-1))
  if (isFunctionNode(callback)) return { kind: 'function', functionNode: callback }
  if (callback?.type === 'Identifier') return { kind: 'identifier', functionNode: null }
  return null
}

function isRuntimeTestAnnotation(modifiers, argumentsList, title) {
  if (modifiers.length !== 1) return false
  if (['slow', 'fail', 'fixme'].includes(modifiers[0])) return argumentsList.length === 0
  return modifiers[0] === 'skip'
    && title === null
    && argumentsList.length === 2
    && getStaticString(argumentsList[1]) !== null
}

function isFunctionNode(node) {
  return ['ArrowFunctionExpression', 'FunctionExpression'].includes(unwrapExpression(node)?.type)
}

function namedFunctionNode(node) {
  if (node.type === 'FunctionDeclaration' && node.id?.type === 'Identifier') {
    return { name: node.id.name, functionNode: node }
  }
  if (node.type === 'VariableDeclarator'
    && node.id?.type === 'Identifier'
    && isFunctionNode(node.init)) return { name: node.id.name, functionNode: unwrapExpression(node.init) }
  return null
}

function collectDirectCallNames(root) {
  const calls = new Set()
  walkAstWithoutNestedFunctions(root, root, node => {
    if (node.type === 'CallExpression' && node.callee?.type === 'Identifier') calls.add(node.callee.name)
  })
  return calls
}

function collectExecutedCallNames(root) {
  const calls = new Set()
  visitExecutedNode(root, false)
  return calls

  function visitExecutedNode(node, invokedCallback) {
    const current = unwrapExpression(node)
    if (!current || typeof current !== 'object' || typeof current.type !== 'string') return
    if (isFunctionNode(current)) {
      if (invokedCallback) visitExecutedNode(current.body, false)
      return
    }
    if (isNestedExecutionScope(current)) return
    if (current.type === 'CallExpression' || current.type === 'OptionalCallExpression') {
      if (current.callee?.type === 'Identifier') calls.add(current.callee.name)
      visitExecutedNode(current.callee, isFunctionNode(current.callee))
      for (const argument of current.arguments) visitExecutedNode(argument, isFunctionNode(argument))
      return
    }
    for (const [key, value] of Object.entries(current)) {
      if (['comments', 'errors', 'extra', 'loc', 'tokens'].includes(key)) continue
      if (Array.isArray(value)) {
        for (const child of value) visitExecutedNode(child, false)
      } else visitExecutedNode(value, false)
    }
  }
}

function walkAstWithoutNestedFunctions(node, root, visitor) {
  if (!node || typeof node !== 'object' || typeof node.type !== 'string') return
  if (node !== root && isNestedExecutionScope(node)) return
  visitor(node)
  for (const [key, value] of Object.entries(node)) {
    if (['comments', 'errors', 'extra', 'loc', 'tokens'].includes(key)) continue
    if (Array.isArray(value)) {
      for (const child of value) walkAstWithoutNestedFunctions(child, root, visitor)
    } else walkAstWithoutNestedFunctions(value, root, visitor)
  }
}

function isNestedExecutionScope(node) {
  return isFunctionNode(node)
    || ['FunctionDeclaration', 'ObjectMethod', 'ClassDeclaration', 'ClassExpression', 'ClassMethod', 'ClassPrivateMethod'].includes(node?.type)
}

function assertSafeMember(node, sourceName) {
  const root = getRootIdentifier(node)
  const property = getStaticMemberProperty(node)

  if (root && FORBIDDEN_ANY_MEMBER_ROOTS.has(root)) throwUnsafe(root + ' client', sourceName)
  const forbiddenProperties = FORBIDDEN_MEMBER_PROPERTIES.get(root)
  if (forbiddenProperties) {
    if (node.computed && property === null) throwUnsafe(root + ' computed access', sourceName)
    if (forbiddenProperties.has(property)) throwUnsafe(root + '.' + property, sourceName)
  }

  const chain = getMemberPropertyChain(node)
  for (let index = 0; index < chain.length - 1; index += 1) {
    const current = chain[index]
    const next = chain[index + 1]
    if (current === 'request' && (next === null || ['delete', 'patch', 'post', 'put'].includes(next))) {
      throwUnsafe('request write chain', sourceName)
    }
    if (current === 'route'
      && (next === null || ['abort', 'continue', 'fallback', 'fulfill'].includes(next))) {
      throwUnsafe('route interception chain', sourceName)
    }
  }
}

function registerModuleSpecifier(specifier, imports, sourceName) {
  if (typeof specifier !== 'string' || specifier.length === 0) {
    throwUnsafe('empty module specifier', sourceName)
  }
  const normalized = specifier.replaceAll('\\', '/')
  if (FORBIDDEN_MODULES.has(normalized) || PRODUCT_API_CLIENT.test(normalized)) {
    throwUnsafe('forbidden module ' + normalized, sourceName)
  }
  imports.push(specifier)
}

function walkAst(node, parent, key, visitor) {
  if (!node || typeof node !== 'object' || typeof node.type !== 'string') return
  visitor(node, parent, key)
  for (const [childKey, value] of Object.entries(node)) {
    if (childKey === 'comments'
      || childKey === 'errors'
      || childKey === 'extra'
      || childKey === 'loc'
      || childKey === 'tokens') continue
    if (Array.isArray(value)) {
      for (const child of value) walkAst(child, node, childKey, visitor)
    } else {
      walkAst(value, node, childKey, visitor)
    }
  }
}

function getRootIdentifier(node) {
  let current = unwrapExpression(node)
  while (current?.type === 'MemberExpression' || current?.type === 'OptionalMemberExpression') {
    current = unwrapExpression(current.object)
  }
  return current?.type === 'Identifier' ? current.name : null
}

function getStaticMemberProperty(node) {
  if (!node.computed && node.property?.type === 'Identifier') return node.property.name
  return getStaticString(node.property)
}

function getMemberPropertyChain(node) {
  const chain = []
  let current = unwrapExpression(node)
  while (current?.type === 'MemberExpression' || current?.type === 'OptionalMemberExpression') {
    chain.unshift(getStaticMemberProperty(current))
    current = unwrapExpression(current.object)
  }
  return chain
}

function getObjectPropertyName(node) {
  if (!node.computed && node.key?.type === 'Identifier') return node.key.name
  return getStaticString(node.key)
}

function getStaticString(node) {
  const current = unwrapExpression(node)
  if (current?.type === 'StringLiteral') return current.value
  if (current?.type === 'TemplateLiteral' && current.expressions.length === 0) {
    return current.quasis[0]?.value?.cooked ?? current.quasis[0]?.value?.raw ?? ''
  }
  return null
}

function unwrapExpression(node) {
  let current = node
  while (current && [
    'ChainExpression',
    'TSAsExpression',
    'TSInstantiationExpression',
    'TSNonNullExpression',
    'TSSatisfiesExpression',
    'TSTypeAssertion',
    'ParenthesizedExpression',
  ].includes(current.type)) current = current.expression
  return current
}

function isReferenceIdentifier(parent, key) {
  if (!parent) return true
  if ((parent.type === 'MemberExpression' || parent.type === 'OptionalMemberExpression')
    && key === 'property'
    && !parent.computed) return false
  if ((parent.type === 'ObjectMethod' || parent.type === 'ObjectProperty')
    && key === 'key'
    && !parent.computed) return false
  if ((parent.type === 'ClassMethod' || parent.type === 'ClassProperty')
    && key === 'key'
    && !parent.computed) return false
  return true
}

function isProtectedAlias(node) {
  const current = unwrapExpression(node)
  if (current?.type === 'Identifier') return ALIAS_PROTECTED_IDENTIFIERS.has(current.name)
  if (current?.type === 'MemberExpression' || current?.type === 'OptionalMemberExpression') {
    return ['request', 'route'].includes(getStaticMemberProperty(current))
  }
  return false
}

function throwUnsafe(label, sourceName) {
  const location = sourceName ? ' in ' + sourceName : ''
  throw new Error('shadow browser write' + location + ': ' + label)
}

function assertRepositoryRelativePath(value, label) {
  if (isAbsolutePath(value)) throw new Error(label + ': ' + value)
  const normalized = normalizeGraphPath(value)
  if (normalized === '..' || normalized.startsWith('../')) throw new Error(label + ': ' + value)
}

function isAbsolutePath(value) {
  return path.posix.isAbsolute(value.replaceAll('\\', '/'))
    || path.win32.isAbsolute(value)
    || /^[A-Za-z]:/u.test(value)
}

function isWithinRoot(candidate, root) {
  if (isAbsolutePath(candidate) || candidate === '..' || candidate.startsWith('../')) return false
  if (root === '.') return true
  return candidate === root || candidate.startsWith(root + '/')
}

function normalizeGraphPath(value) {
  const normalized = path.posix.normalize(value.replaceAll('\\', '/'))
  return normalized.startsWith('./') ? normalized.slice(2) : normalized
}
