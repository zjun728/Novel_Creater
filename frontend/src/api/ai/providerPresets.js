export const providerTypeOptions = [
  { label: 'OpenAI-compatible（通用）', value: 'openai-compatible' }
]

export const defaultBaseUrls = {
  'openai-compatible': 'https://api.openai.com/v1'
}

export const providerPresets = [
  {
    name: 'OpenAI',
    providerType: 'openai-compatible',
    baseURL: 'https://api.openai.com/v1',
    model: 'gpt-4o',
    maxContextTokens: 128000
  },
  {
    name: '联通云-DeepSeek-V4-Flash',
    providerType: 'openai-compatible',
    baseURL: 'https://aigw-gzgy2.cucloud.cn:8443/v1',
    model: 'DeepSeek-V4-Flash',
    maxContextTokens: 1000000,
    maxOutputTokens: 380000,
    temperature: 0.8,
    topP: 0.9
  },
  {
    name: '通义千问 / Qwen',
    providerType: 'openai-compatible',
    baseURL: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    model: 'qwen-plus',
    maxContextTokens: 128000
  },
  {
    name: 'Kimi / Moonshot',
    providerType: 'openai-compatible',
    baseURL: 'https://api.moonshot.cn/v1',
    model: 'moonshot-v1-8k',
    maxContextTokens: 8000
  }
]

// createAdapter 位于 index.js，使用 ESM import
