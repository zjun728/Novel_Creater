import { AdapterBase } from './adapterBase.js'

export class AnthropicAdapter extends AdapterBase {
  getDefaultBaseURL() {
    return 'https://api.anthropic.com'
  }

  getHeaders() {
    return {
      'Content-Type': 'application/json',
      'x-api-key': this.config.apiKey,
      'anthropic-version': '2023-06-01'
    }
  }

  normalizeMessages(messages) {
    const systemMessages = []
    const normalized = []

    for (const message of messages || []) {
      if (message.role === 'system') {
        if (message.content) systemMessages.push(message.content)
        continue
      }

      normalized.push({
        role: message.role === 'assistant' ? 'assistant' : 'user',
        content: message.content || ''
      })
    }

    return {
      system: systemMessages.join('\n\n'),
      messages: normalized.length
        ? normalized
        : [{ role: 'user', content: '' }]
    }
  }

  buildRequestBody(messages, options = {}) {
    const normalized = this.normalizeMessages(messages)
    const body = {
      model: this.config.model,
      messages: normalized.messages,
      max_tokens: options.maxTokens || this.config.maxOutputTokens || 4096,
      temperature: options.temperature ?? this.config.temperature ?? 0.8,
      top_p: options.topP ?? this.config.topP ?? 0.9,
      stream: options.stream ?? false
    }

    if (normalized.system) {
      body.system = normalized.system
    }

    return body
  }

  async chatCompletion(messages, options = {}) {
    this.validateDirectProviderAccess()

    const baseURL = this.getBaseURL().replace(/\/+$/, '')
    const url = baseURL.endsWith('/v1/messages')
      ? baseURL
      : `${baseURL}/v1/messages`

    const response = await fetch(url, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(this.buildRequestBody(messages, { ...options, stream: false }))
    })

    if (!response.ok) {
      const errorBody = await response.text().catch(() => '')
      throw new Error(`Claude API 错误 (${response.status}): ${errorBody}`)
    }

    const data = await response.json()
    return data.content?.[0]?.text || ''
  }
}
