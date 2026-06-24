import { AnthropicAdapter } from './anthropicAdapter.js'
import { createOpenAIStreamReader, OpenaiCompatibleAdapter } from './openaiCompatibleAdapter.js'

const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api').replace(/\/+$/, '')
const AI_PROXY_TIMEOUT_MS = 20 * 60 * 1000
const MAX_AI_PROXY_RETRIES = 2
const AI_PROXY_RETRY_BASE_DELAY_MS = 800

class AiProxyError extends Error {
  constructor(message, options = {}) {
    super(message)
    this.name = 'AiProxyError'
    this.status = options.status || 0
    this.detail = options.detail || {}
    this.upstreamStatus = this.detail.upstreamStatus ?? this.detail.httpStatus ?? null
    this.providerId = this.detail.providerId || ''
    this.providerName = this.detail.providerName || ''
    this.modelName = this.detail.modelName || ''
    this.taskName = this.detail.taskName || ''
    this.taskId = this.detail.taskId || ''
    this.taskKey = this.detail.taskKey || ''
    this.requestId = this.detail.requestId || ''
    this.retryable = Boolean(this.detail.retryable) || [502, 503, 504].includes(Number(this.status)) || [502, 503, 504].includes(Number(this.upstreamStatus))
    this.retriesAttempted = options.retriesAttempted || 0
    this.retrySucceeded = Boolean(options.retrySucceeded)
  }
}

export function directProviderEnabled() {
  return import.meta.env?.VITE_AI_DIRECT_PROVIDER === 'true'
}

export function createAdapter(providerConfig) {
  switch (providerConfig.providerType) {
    case 'anthropic':
      return new AnthropicAdapter(providerConfig)
    case 'openai-compatible':
      return new OpenaiCompatibleAdapter(providerConfig)
    default:
      return new OpenaiCompatibleAdapter(providerConfig)
  }
}

export async function testConnection(providerConfig) {
  if (!directProviderEnabled()) {
    try {
      const data = await requestAiProxy('/ai/chat-completions', buildProxyPayload(
        providerConfig,
        [{ role: 'user', content: '请回复"连接成功"四个字。' }],
        { maxTokens: 50, temperature: 0, taskName: 'provider_test' },
        false
      ))
      return { ok: true, data: data.choices?.[0]?.message?.content || '' }
    } catch (e) {
      return { ok: false, error: e.message, detail: e.detail || null, retriesAttempted: e.retriesAttempted || 0 }
    }
  }
  const adapter = createAdapter(providerConfig)
  return adapter.testConnection()
}

export async function chatCompletion(providerConfig, messages, options = {}) {
  if (!directProviderEnabled()) {
    const data = await requestAiProxy('/ai/chat-completions', buildProxyPayload(providerConfig, messages, options, false))
    if (options.returnRaw) return data
    return data.choices?.[0]?.message?.content || ''
  }
  const adapter = createAdapter(providerConfig)
  return adapter.chatCompletion(messages, options)
}

/**
 * 流式聊天补全
 * @returns {Promise<{readNext, readAll, cancel}>} 流式读取器
 */
export async function chatCompletionStream(providerConfig, messages, options = {}) {
  if (!directProviderEnabled()) {
    const response = await requestAiProxyResponse('/ai/chat-completions/stream', buildProxyPayload(providerConfig, messages, options, true))
    return createOpenAIStreamReader(response)
  }
  const adapter = createAdapter(providerConfig)
  if (!adapter.chatCompletionStream) {
    throw new Error('该适配器不支持流式输出')
  }
  return adapter.chatCompletionStream(messages, options)
}

function assignIfPresent(target, key, value) {
  if (value !== undefined && value !== null && value !== '') target[key] = value
}

function normalizeProxyResponseFormat(options = {}) {
  const format = options.response_format ?? options.responseFormat
  if (format === 'json') return { type: 'json_object' }
  return format
}

function buildProxyPayload(providerConfig = {}, messages = [], options = {}, stream = false) {
  const payload = {
    messages,
    stream,
    providerId: providerConfig.id || providerConfig.providerId || null,
    model: options.model || providerConfig.model || null,
    taskName: options.taskName || providerConfig.taskName || 'AI 任务'
  }

  assignIfPresent(payload, 'projectId', options.projectId || providerConfig.projectId)
  assignIfPresent(payload, 'temperature', options.temperature)
  assignIfPresent(payload, 'maxTokens', options.maxTokens ?? options.max_tokens)
  assignIfPresent(payload, 'top_p', options.top_p ?? options.topP)
  assignIfPresent(payload, 'response_format', normalizeProxyResponseFormat(options))
  assignIfPresent(payload, 'thinking', options.thinking)
  assignIfPresent(payload, 'includeUsage', options.includeUsage)

  return payload
}

async function requestAiProxy(path, payload) {
  const response = await requestAiProxyResponse(path, payload)
  const text = await response.text()
  if (!text) return null
  try {
    const data = JSON.parse(text)
    if (response.aiProxyRetryDiagnostics && data && typeof data === 'object') {
      data.proxyDiagnostics = {
        ...(data.proxyDiagnostics || {}),
        aiProxyRetry: response.aiProxyRetryDiagnostics
      }
    }
    return data
  } catch (e) {
    throw new Error(`后端 AI 代理请求失败：Invalid JSON response: ${text.slice(0, 200)}`)
  }
}

async function requestAiProxyResponse(path, payload) {
  let lastError = null
  let retriesAttempted = 0
  for (let attempt = 0; attempt <= MAX_AI_PROXY_RETRIES; attempt += 1) {
    try {
      const response = await fetchAiProxyResponseOnce(path, payload)
      if (attempt > 0) {
        response.aiProxyRetryDiagnostics = {
          retriesAttempted: attempt,
          retrySucceeded: true
        }
      }
      return response
    } catch (error) {
      lastError = error
      if (!isRetryableAiProxyError(error) || attempt >= MAX_AI_PROXY_RETRIES) break
      retriesAttempted = attempt + 1
      await wait(resolveAiProxyRetryDelayMs(attempt + 1))
    }
  }
  if (lastError instanceof AiProxyError) {
    lastError.retriesAttempted = retriesAttempted
    lastError.retrySucceeded = false
  }
  throw lastError
}

async function fetchAiProxyResponseOnce(path, payload) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), AI_PROXY_TIMEOUT_MS)

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
      body: JSON.stringify(payload)
    })

    if (!response.ok) {
      const errorText = await response.text().catch(() => response.statusText)
      const detail = parseAiProxyErrorDetail(errorText)
      throw new AiProxyError(formatAiProxyError(response.status, errorText), { status: response.status, detail })
    }

    return response
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new AiProxyError(`后端 AI 代理请求失败：请求超时 (${Math.round(AI_PROXY_TIMEOUT_MS / 1000)}s): ${path}`, {
        status: 0,
        detail: {
          message: '后端 AI 代理请求超时',
          taskName: payload?.taskName || '',
          retryable: true
        }
      })
    }
    if (/后端 AI 代理请求失败|供应商返回失败/.test(e.message)) throw e
    throw new Error(`后端 AI 代理请求失败：${e.message}`)
  } finally {
    clearTimeout(timer)
  }
}

function isRetryableAiProxyError(error) {
  return Boolean(error?.retryable) &&
    ([502, 503, 504].includes(Number(error.status)) ||
      [502, 503, 504].includes(Number(error.upstreamStatus)) ||
      /timeout|超时/i.test(error.message || ''))
}

function resolveAiProxyRetryDelayMs(attempt) {
  return AI_PROXY_RETRY_BASE_DELAY_MS * Math.pow(2, Math.max(0, Number(attempt || 1) - 1))
}

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function formatAiProxyError(status, errorText) {
  const detail = parseAiProxyErrorDetail(errorText)
  const message = detail.message || '后端 AI 代理请求失败'
  const prefix = message.includes('供应商返回失败') ? '供应商返回失败' : '后端 AI 代理请求失败'
  const provider = [detail.providerName, detail.modelName].filter(Boolean).join(' / ')
  const task = detail.taskName ? ` task=${detail.taskName}` : ''
  const upstreamStatus = detail.upstreamStatus ?? detail.httpStatus
  const upstream = upstreamStatus ? ` upstream=${upstreamStatus}` : ''
  const retryable = detail.retryable ? ' retryable=true' : ''
  const requestId = detail.requestId ? ` requestId=${detail.requestId}` : ''
  const raw = detail.upstreamBodyHead || detail.rawHead ? ` raw=${String(detail.upstreamBodyHead || detail.rawHead).slice(0, 240)}` : ''
  return `${prefix} (${status}${upstream})${provider ? ` ${provider}` : ''}${task}${retryable}${requestId}: ${message}${raw}`
}

function parseAiProxyErrorDetail(errorText) {
  try {
    const parsed = JSON.parse(errorText)
    return parsed.detail && typeof parsed.detail === 'object' ? parsed.detail : parsed
  } catch (e) {
    return { message: errorText || '' }
  }
}

export { AnthropicAdapter } from './anthropicAdapter.js'
export { OpenaiCompatibleAdapter } from './openaiCompatibleAdapter.js'
export { AdapterBase } from './adapterBase.js'
export { providerTypeOptions, defaultBaseUrls, providerPresets } from './providerPresets.js'
