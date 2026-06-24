export const providerTypeOptions = [
  { label: 'Anthropic Claude（原生）', value: 'anthropic' },
  { label: 'OpenAI-compatible（通用）', value: 'openai-compatible' }
]

export const defaultBaseUrls = {
  anthropic: 'https://api.anthropic.com',
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
    name: 'Anthropic Claude',
    providerType: 'anthropic',
    baseURL: 'https://api.anthropic.com',
    model: 'claude-sonnet-4-20250514',
    maxContextTokens: 200000
  },
  {
    name: 'deepseek-v4-flash',
    providerType: 'openai-compatible',
    baseURL: 'https://api.deepseek.com',
    model: 'deepseek-v4-flash',
    maxContextTokens: 128000,
    maxOutputTokens: 8192,
    temperature: 0.8,
    thinking: { type: 'enabled', reasoning_effort: 'high' }
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
