export class ApiError extends Error {
  constructor({ status, code = 'request_failed', message = '请求失败', correlationId = '' } = {}) {
    super(String(message || '请求失败'))
    this.name = 'ApiError'
    this.status = Number(status || 0)
    this.code = String(code || 'request_failed')
    this.correlationId = String(correlationId || '')
  }

  toJSON() {
    return {
      name: this.name,
      status: this.status,
      code: this.code,
      message: this.message,
      correlationId: this.correlationId,
    }
  }
}

export async function parseApiError(response) {
  let body = {}
  try {
    const parsed = await response.json()
    body = parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    body = {}
  }

  const detail = body.detail && typeof body.detail === 'object' && !Array.isArray(body.detail)
    ? body.detail
    : {}
  return new ApiError({
    status: response.status,
    code: body.code || detail.code,
    message: body.message || detail.message || `请求失败 (${response.status})`,
    correlationId: body.correlationId || detail.correlationId,
  })
}
