/**
 * MySQL API 客户端
 * 统一通过后端 HTTP API 访问本地 MySQL 数据层。
 */

const BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api').replace(/\/+$/, '')
const DEFAULT_TIMEOUT = 30000

async function request(method, path, body, timeoutMs = DEFAULT_TIMEOUT) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal
    }
    if (body !== undefined) {
      opts.body = JSON.stringify(body)
    }
    const res = await fetch(`${BASE}${path}`, opts)
    if (!res.ok) {
      const err = await res.text().catch(() => res.statusText)
      throw new Error(`API error ${res.status}: ${err}`)
    }
    const text = await res.text()
    if (!text) return null
    try {
      return JSON.parse(text)
    } catch (e) {
      throw new Error(`Invalid JSON response: ${text.slice(0, 200)}`)
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error(`请求超时 (${timeoutMs / 1000}s): ${method} ${path}`)
    }
    throw e
  } finally {
    clearTimeout(timer)
  }
}

const get = (path) => request('GET', path)
const post = (path, body) => request('POST', path, body)
const put = (path, body) => request('PUT', path, body)
const del = (path) => request('DELETE', path)

function queryString(params = {}) {
  const qs = new URLSearchParams()
  Object.entries(params || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') qs.set(key, value)
  })
  const query = qs.toString()
  return query ? `?${query}` : ''
}

export const api = {
  // === 健康检查 ===
  health: () => get('/health'),

  // === 项目状态门禁 ===
  projectState: {
    finalizationMarkers: {
      list: (projectId) => get(`/projects/${projectId}/finalization-markers`),
      save: (projectId, chapterNum, marker) => put(`/projects/${projectId}/finalization-markers/${chapterNum}`, marker),
    },
    healthChecks: {
      list: (projectId) => get(`/projects/${projectId}/health-checks`),
      save: (projectId, chapterNum, result) => put(`/projects/${projectId}/health-checks/${chapterNum}`, result),
    },
  },

  // === 项目 ===
  projects: {
    list: () => get('/projects'),
    create: (data) => post('/projects', data),
    get: (id) => get(`/projects/${id}`),
    contentState: (id) => get(`/projects/${id}/content-state`),
    update: (id, data) => put(`/projects/${id}`, data),
    delete: (id) => del(`/projects/${id}`),
  },

  // === Provider 配置 ===
  providers: {
    list: () => get('/providers'),
    create: (data) => post('/providers', data),
    update: (id, data) => put(`/providers/${id}`, data),
    delete: (id) => del(`/providers/${id}`),
  },

  // === 任务模型绑定 ===
  bindings: {
    get: (projectId) => get(`/projects/${projectId}/bindings`),
    status: (projectId) => get(`/projects/${projectId}/bindings/status`),
    save: (projectId, data) => put(`/projects/${projectId}/bindings`, data),
  },

  // === 章节 ===
  chapters: {
    list: (projectId) => get(`/projects/${projectId}/chapters`),
    create: (projectId, data) => post(`/projects/${projectId}/chapters`, data),
    update: (projectId, chapterId, data) => put(`/projects/${projectId}/chapters/${chapterId}`, data),
    updateTitle: (projectId, chapterId, data) => put(`/projects/${projectId}/chapters/${chapterId}/title`, data),
    updateSummary: (projectId, chapterId, data) => put(`/projects/${projectId}/chapters/${chapterId}/summary`, data),
    delete: (projectId, chapterId) => del(`/projects/${projectId}/chapters/${chapterId}`),
  },

  // === 章节版本 ===
  versions: {
    list: (projectId, chapterId) => get(`/projects/${projectId}/chapters/${chapterId}/versions`),
    create: (projectId, chapterId, data) => post(`/projects/${projectId}/chapters/${chapterId}/versions`, data),
    update: (projectId, chapterId, versionId, data) => put(`/projects/${projectId}/chapters/${chapterId}/versions/${versionId}`, data),
    finalize: (projectId, chapterId, versionId, data = {}) => post(`/projects/${projectId}/chapters/${chapterId}/versions/${versionId}/finalize`, data),
    delete: (projectId, chapterId, versionId) => del(`/projects/${projectId}/chapters/${chapterId}/versions/${versionId}`),
  },

  // === 临时草稿 ===
  tempDrafts: {
    get: (projectId, chapterNum) => get(`/projects/${projectId}/temp-draft/${chapterNum}`),
    save: (projectId, chapterNum, content) => put(`/projects/${projectId}/temp-draft/${chapterNum}`, { content }),
    delete: (projectId, chapterNum) => del(`/projects/${projectId}/temp-draft/${chapterNum}`),
  },

  // === 章节小纲 ===
  beatPlans: {
    get: (projectId, chapterNum) => get(`/projects/${projectId}/chapter-beat-plan/${chapterNum}`),
    save: (projectId, chapterNum, content, metadata = {}) => put(`/projects/${projectId}/chapter-beat-plan/${chapterNum}`, { content, ...metadata }),
    delete: (projectId, chapterNum) => del(`/projects/${projectId}/chapter-beat-plan/${chapterNum}`),
  },

  // === 故事块 ===
  storyBlocks: {
    list: (projectId) => get(`/projects/${projectId}/story-blocks`),
    active: (projectId) => get(`/projects/${projectId}/story-blocks/active`),
    create: (projectId, data) => post(`/projects/${projectId}/story-blocks`, data),
    updateRemainingStages: (projectId, blockId, data) => put(`/projects/${projectId}/story-blocks/${blockId}/remaining-stages`, data),
    close: (projectId, blockId, data = {}) => post(`/projects/${projectId}/story-blocks/${blockId}/close`, data),
    complete: (projectId, blockId, data = {}) => post(`/projects/${projectId}/story-blocks/${blockId}/complete`, data),
    confirmReview: (projectId, blockId, data = {}) => post(`/projects/${projectId}/story-blocks/${blockId}/confirm-review`, data),
    createReview: (projectId, blockId, data) => post(`/projects/${projectId}/story-blocks/${blockId}/reviews`, data),
  },

  // === 创作种子 ===
  seeds: {
    list: (projectId) => get(`/projects/${projectId}/seeds`),
    create: (projectId, data) => post(`/projects/${projectId}/seeds`, data),
    update: (projectId, seedId, data) => put(`/projects/${projectId}/seeds/${seedId}`, data),
    delete: (projectId, seedId) => del(`/projects/${projectId}/seeds/${seedId}`),
    clear: (projectId) => del(`/projects/${projectId}/seeds`),
  },

  // === 创作圣经 ===
  bible: {
    get: (projectId) => get(`/projects/${projectId}/bible`),
    save: (projectId, data) => put(`/projects/${projectId}/bible`, data),
    delete: (projectId) => del(`/projects/${projectId}/bible`),
  },

  // === 项目级审稿 ===
  globalAudits: {
    list: (projectId) => get(`/projects/${projectId}/global-audits`),
    create: (projectId, data) => post(`/projects/${projectId}/global-audits`, data),
    delete: (projectId, reportId) => del(`/projects/${projectId}/global-audits/${reportId}`),
  },

  // === 审稿纠偏任务 ===
  correctionTasks: {
    list: (projectId, params = {}) => {
      const qs = new URLSearchParams()
      if (params.status) qs.set('status', params.status)
      const query = qs.toString()
      return get(`/projects/${projectId}/correction-tasks${query ? `?${query}` : ''}`)
    },
    create: (projectId, data) => post(`/projects/${projectId}/correction-tasks`, data),
    bulkCreate: (projectId, data) => post(`/projects/${projectId}/correction-tasks/bulk`, data),
    update: (projectId, taskId, data) => put(`/projects/${projectId}/correction-tasks/${taskId}`, data),
    delete: (projectId, taskId) => del(`/projects/${projectId}/correction-tasks/${taskId}`),
  },

  // === 滚动大纲 ===
  outline: {
    get: (projectId) => get(`/projects/${projectId}/outline`),
    save: (projectId, data) => put(`/projects/${projectId}/outline`, data),
  },

  // === 分卷规划 ===
  volumes: {
    list: (projectId) => get(`/projects/${projectId}/volumes`),
    context: (projectId, volumeId) => get(`/projects/${projectId}/volumes/${volumeId}/context`),
    create: (projectId, data) => post(`/projects/${projectId}/volumes`, data),
    update: (projectId, volumeId, data) => put(`/projects/${projectId}/volumes/${volumeId}`, data),
    saveAudit: (projectId, volumeId, report) => put(`/projects/${projectId}/volumes/${volumeId}/audit`, { report }),
    saveSummary: (projectId, volumeId, report) => put(`/projects/${projectId}/volumes/${volumeId}/summary-report`, { report }),
    delete: (projectId, volumeId) => del(`/projects/${projectId}/volumes/${volumeId}`),
  },

  // === 角色 ===
  characters: {
    list: (projectId) => get(`/projects/${projectId}/characters`),
    create: (projectId, data) => post(`/projects/${projectId}/characters`, data),
    update: (projectId, charId, data) => put(`/projects/${projectId}/characters/${charId}`, data),
    delete: (projectId, charId) => del(`/projects/${projectId}/characters/${charId}`),
  },

  // === 伏笔 ===
  plotThreads: {
    list: (projectId) => get(`/projects/${projectId}/plot-threads`),
    syncFromCanonFacts: (projectId) => post(`/projects/${projectId}/plot-threads/sync-canon-facts`),
    create: (projectId, data) => post(`/projects/${projectId}/plot-threads`, data),
    update: (projectId, threadId, data) => put(`/projects/${projectId}/plot-threads/${threadId}`, data),
    delete: (projectId, threadId) => del(`/projects/${projectId}/plot-threads/${threadId}`),
  },

  // === Canon 事实 ===
  canonFacts: {
    list: (projectId) => get(`/projects/${projectId}/canon-facts`),
    create: (projectId, data) => post(`/projects/${projectId}/canon-facts`, data),
    update: (projectId, factId, data) => put(`/projects/${projectId}/canon-facts/${factId}`, data),
  },

  // === 可能性池 ===
  possibilityCards: {
    list: (projectId) => get(`/projects/${projectId}/possibility-cards`),
    create: (projectId, data) => post(`/projects/${projectId}/possibility-cards`, data),
    delete: (projectId, cardId) => del(`/projects/${projectId}/possibility-cards/${cardId}`),
  },

  // === 设定库 ===
  settings: {
    entities: {
      list: (projectId, params = {}) => {
        const qs = new URLSearchParams()
        if (params.type) qs.set('type', params.type)
        if (params.q) qs.set('q', params.q)
        const query = qs.toString()
        return get(`/projects/${projectId}/settings/entities${query ? `?${query}` : ''}`)
      },
      get: (projectId, entityId) => get(`/projects/${projectId}/settings/entities/${entityId}`),
      create: (projectId, data) => post(`/projects/${projectId}/settings/entities`, data),
      update: (projectId, entityId, data) => put(`/projects/${projectId}/settings/entities/${entityId}`, data),
      delete: (projectId, entityId) => del(`/projects/${projectId}/settings/entities/${entityId}`),
    },
    relations: {
      list: (projectId, entityId = '') => {
        const query = entityId ? `?entityId=${encodeURIComponent(entityId)}` : ''
        return get(`/projects/${projectId}/settings/relations${query}`)
      },
      create: (projectId, data) => post(`/projects/${projectId}/settings/relations`, data),
      update: (projectId, relationId, data) => put(`/projects/${projectId}/settings/relations/${relationId}`, data),
      delete: (projectId, relationId) => del(`/projects/${projectId}/settings/relations/${relationId}`),
    },
    changeEvents: {
      list: (projectId, params = {}) => {
        const qs = new URLSearchParams()
        if (params.status) qs.set('status', params.status)
        if (params.chapterNum != null) qs.set('chapterNum', params.chapterNum)
        const query = qs.toString()
        return get(`/projects/${projectId}/settings/change-events${query ? `?${query}` : ''}`)
      },
      create: (projectId, data) => post(`/projects/${projectId}/settings/change-events`, data),
      update: (projectId, eventId, data) => put(`/projects/${projectId}/settings/change-events/${eventId}`, data),
      accept: (projectId, eventId, data) => post(`/projects/${projectId}/settings/change-events/${eventId}/accept`, data),
      reject: (projectId, eventId) => post(`/projects/${projectId}/settings/change-events/${eventId}/reject`),
      delete: (projectId, eventId) => del(`/projects/${projectId}/settings/change-events/${eventId}`),
    },
    clear: (projectId) => del(`/projects/${projectId}/settings`),
  },

  // === 创作经验卡 / 样本库 ===
  experienceCards: {
    seedLocalReport: () => post('/experience-cards/seed-local-report'),
    seedPromptInjectableCards: () => post('/experience-cards/seed-prompt-injectable-cards'),
    sources: {
      list: (params = {}) => get(`/experience-cards/sources${queryString(params)}`),
    },
    cards: {
      list: (params = {}) => get(`/experience-cards/cards${queryString(params)}`),
      productList: (params = {}) => get(`/experience-cards/product/cards${queryString(params)}`),
      create: (data) => post('/experience-cards/cards', data),
      update: (cardId, data = {}) => put(`/experience-cards/cards/${cardId}`, data),
      delete: (cardId) => del(`/experience-cards/cards/${cardId}`),
      toggleActive: (cardId, data = {}) => post(`/experience-cards/cards/${cardId}/toggle-active`, data),
      copy: (cardId, data = {}) => post(`/experience-cards/cards/${cardId}/copy`, data),
      review: (cardId, data = {}) => post(`/experience-cards/cards/${cardId}/review`, data),
      reject: (cardId, data = {}) => post(`/experience-cards/cards/${cardId}/reject`, data),
      archive: (cardId, data = {}) => post(`/experience-cards/cards/${cardId}/archive`, data),
    },
    candidates: {
      list: (params = {}) => get(`/experience-cards/candidates${queryString(params)}`),
      create: (data) => post('/experience-cards/candidates', data),
      update: (candidateId, data = {}) => put(`/experience-cards/candidates/${candidateId}`, data),
      delete: (candidateId) => del(`/experience-cards/candidates/${candidateId}`),
      addCards: (candidateId, data = {}) => post(`/experience-cards/candidates/${candidateId}/cards`, data),
      removeCard: (candidateId, cardId) => del(`/experience-cards/candidates/${candidateId}/cards/${cardId}`),
      generateStandard: (candidateId, data = {}) => post(`/experience-cards/candidates/${candidateId}/generate-standard`, data),
      approve: (candidateId, data = {}) => post(`/experience-cards/candidates/${candidateId}/approve`, data),
      reject: (candidateId, data = {}) => post(`/experience-cards/candidates/${candidateId}/reject`, data),
      promote: (candidateId, data = {}) => post(`/experience-cards/candidates/${candidateId}/promote`, data),
    },
    standards: {
      list: (params = {}) => get(`/experience-cards/standards${queryString(params)}`),
      update: (standardId, data = {}) => put(`/experience-cards/standards/${standardId}`, data),
      delete: (standardId) => del(`/experience-cards/standards/${standardId}`),
      toggleActive: (standardId, data = {}) => post(`/experience-cards/standards/${standardId}/toggle-active`, data),
      copy: (standardId, data = {}) => post(`/experience-cards/standards/${standardId}/copy`, data),
    },
  },

  // === 导入导出 ===
  exportFull: (projectId = '', includeApiKeys = false) => {
    const params = new URLSearchParams()
    if (projectId) params.set('projectId', projectId)
    if (includeApiKeys) params.set('includeApiKeys', 'true')
    const query = params.toString()
    return post(`/export/full${query ? `?${query}` : ''}`)
  },
  importFull: (data) => post('/import/full', data),

  // === 选题雷达 ===
  market: {
    scrape: (data) => post('/market/scrape', data),
    list: (projectId) => get(`/market/items?projectId=${encodeURIComponent(projectId)}`),
    create: (data) => post('/market/items', data),
    update: (id, data) => put(`/market/items/${id}`, data),
    delete: (id) => del(`/market/items/${id}`),
    chat: {
      list: (projectId) => get(`/market/chat?projectId=${encodeURIComponent(projectId)}`),
      create: (data) => post('/market/chat', data),
      clear: (projectId) => del(`/market/chat?projectId=${encodeURIComponent(projectId)}`),
    },
    directions: {
      list: (projectId) => get(`/market/directions?projectId=${encodeURIComponent(projectId)}`),
      create: (data) => post('/market/directions', data),
    },
  },
}
