export class AdapterBase {
  constructor(providerConfig) {
    this.config = providerConfig
  }

  directProviderEnabled() {
    return import.meta.env?.VITE_AI_DIRECT_PROVIDER === 'true'
  }

  validateDirectProviderAccess() {
    if (!this.directProviderEnabled()) {
      throw new Error('浏览器直连 AI 供应商已默认关闭。需要调试直连时，请显式设置 VITE_AI_DIRECT_PROVIDER=true。')
    }
    this.validate()
  }

  validate() {
    if (!this.config.apiKey) throw new Error('API Key 未配置')
    if (!this.config.model) throw new Error('模型 ID 未配置')
  }

  getBaseURL() {
    return this.config.baseURL || this.getDefaultBaseURL()
  }

  getDefaultBaseURL() {
    throw new Error('子类必须实现 getDefaultBaseURL()')
  }

  getHeaders() {
    throw new Error('子类必须实现 getHeaders()')
  }

  async chatCompletion(messages, options = {}) {
    throw new Error('子类必须实现 chatCompletion()')
  }

  async testConnection() {
    try {
      const result = await this.chatCompletion(
        [{ role: 'user', content: '请回复"连接成功"四个字。' }],
        { maxTokens: 50, temperature: 0 }
      )
      return { ok: true, data: result }
    } catch (e) {
      return { ok: false, error: e.message }
    }
  }
}
