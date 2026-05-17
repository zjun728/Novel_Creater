import { AdapterBase } from './adapterBase.js'

export class OpenaiCompatibleAdapter extends AdapterBase {
  getDefaultBaseURL() {
    return 'https://api.openai.com/v1'
  }

  getHeaders() {
    const headers = {
      'Content-Type': 'application/json'
    }
    if (this.config.apiKey) {
      headers['Authorization'] = `Bearer ${this.config.apiKey}`
    }
    return headers
  }

  buildRequestBody(messages, options = {}) {
    const body = {
      model: this.config.model,
      messages,
      max_tokens: options.maxTokens || this.config.maxOutputTokens || 4096,
      temperature: options.temperature ?? this.config.temperature ?? 0.8,
      top_p: options.topP ?? this.config.topP ?? 0.9,
      stream: options.stream ?? this.config.stream ?? false
    }

    // DeepSeek V4 thinking 参数
    const thinking = options.thinking || this.config.thinking
    if (thinking) {
      body.thinking = thinking
    }

    // JSON 输出模式
    if (options.responseFormat === 'json') {
      body.response_format = { type: 'json_object' }
    }

    // stream_options
    if (body.stream && options.includeUsage !== false) {
      body.stream_options = { include_usage: true }
    }

    return body
  }

  // === 非流式请求 ===
  async chatCompletion(messages, options = {}) {
    this.validate()

    const baseURL = this.getBaseURL().replace(/\/+$/, '')
    const url = baseURL.includes('/chat/completions')
      ? baseURL
      : `${baseURL}/chat/completions`

    const response = await fetch(url, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(this.buildRequestBody(messages, { ...options, stream: false }))
    })

    if (!response.ok) {
      const errorBody = await response.text().catch(() => '')
      throw new Error(`API 错误 (${response.status}): ${errorBody}`)
    }

    const data = await response.json()
    return data.choices?.[0]?.message?.content || ''
  }

  // === 流式请求（SSE） ===
  async chatCompletionStream(messages, options = {}) {
    this.validate()

    const baseURL = this.getBaseURL().replace(/\/+$/, '')
    const url = baseURL.includes('/chat/completions')
      ? baseURL
      : `${baseURL}/chat/completions`

    const response = await fetch(url, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify(this.buildRequestBody(messages, { ...options, stream: true }))
    })

    if (!response.ok) {
      const errorBody = await response.text().catch(() => '')
      throw new Error(`API 错误 (${response.status}): ${errorBody}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let fullContent = ''
    let buffer = ''

    // 返回一个可迭代对象，让调用方逐步消费
    return {
      response,
      reader,
      decoder,
      buffer,
      fullContent,

      /**
       * 读取下一个 SSE chunk
       * @returns {Promise<{done: boolean, content: string, delta: string, finishReason: string|null}>}
       */
      async readNext() {
        while (true) {
          const readResult = await reader.read()
          const reachedEnd = readResult.done
          if (reachedEnd) {
            const tail = decoder.decode()
            if (tail) this.buffer += tail
            if (!this.buffer.trim()) break
          } else {
            this.buffer += decoder.decode(readResult.value, { stream: true })
          }

          const lines = this.buffer.split('\n')
          this.buffer = reachedEnd ? '' : (lines.pop() || '')
          let batchDelta = ''
          let finishReason = null
          let streamFinished = false

          for (const line of lines) {
            const trimmed = line.trim()
            if (!trimmed || !trimmed.startsWith('data:')) continue

            const dataStr = trimmed.replace(/^data:\s*/, '')
            if (dataStr === '[DONE]') {
              streamFinished = true
              finishReason = finishReason || 'stop'
              break
            }

            try {
              const chunk = JSON.parse(dataStr)
              const delta = chunk.choices?.[0]?.delta?.content || ''
              const chunkFinishReason = chunk.choices?.[0]?.finish_reason || null
              if (delta) {
                this.fullContent += delta
                batchDelta += delta
              }
              if (chunkFinishReason) {
                finishReason = chunkFinishReason
                streamFinished = true
              }
            } catch (e) {
              // 跳过解析失败的行，等待后续 chunk 补齐。
            }
          }

          if (batchDelta || streamFinished || finishReason) {
            return {
              done: streamFinished || Boolean(finishReason),
              content: this.fullContent,
              delta: batchDelta,
              finishReason
            }
          }
        }
        return { done: true, content: this.fullContent, delta: '', finishReason: 'stop' }
      },

      /**
       * 读取所有流式内容，返回完整文本
       */
      async readAll() {
        while (true) {
          const result = await this.readNext()
          if (result.done) return result.content
        }
      },

      /**
       * 取消流式请求
       */
      cancel() {
        reader.cancel()
      }
    }
  }
}
