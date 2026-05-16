import { AnthropicAdapter } from './anthropicAdapter.js'
import { OpenaiCompatibleAdapter } from './openaiCompatibleAdapter.js'

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
  const adapter = createAdapter(providerConfig)
  return adapter.testConnection()
}

export async function chatCompletion(providerConfig, messages, options = {}) {
  const adapter = createAdapter(providerConfig)
  return adapter.chatCompletion(messages, options)
}

/**
 * 流式聊天补全
 * @returns {Promise<{readNext, readAll, cancel}>} 流式读取器
 */
export async function chatCompletionStream(providerConfig, messages, options = {}) {
  const adapter = createAdapter(providerConfig)
  if (!adapter.chatCompletionStream) {
    throw new Error('该适配器不支持流式输出')
  }
  return adapter.chatCompletionStream(messages, options)
}

export { AnthropicAdapter } from './anthropicAdapter.js'
export { OpenaiCompatibleAdapter } from './openaiCompatibleAdapter.js'
export { AdapterBase } from './adapterBase.js'
export { providerTypeOptions, defaultBaseUrls, providerPresets } from './providerPresets.js'
