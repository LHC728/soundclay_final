export const API_BASE = (
  import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'
).replace(/\/$/, '')

export const WS_URL =
  import.meta.env.VITE_WS_URL ?? 'ws://127.0.0.1:8000/ws/ring'

export class ApiError extends Error {
  constructor(message, status = 0, body = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

async function decodeResponse(response) {
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) {
    try {
      return await response.json()
    } catch {
      throw new ApiError('Backend returned malformed JSON.', response.status)
    }
  }
  const text = await response.text()
  return text ? { message: text } : {}
}

export async function apiRequest(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE}${path}`, options)
  } catch (error) {
    throw new ApiError(`Backend is unavailable at ${API_BASE}.`, 0, error)
  }

  const body = await decodeResponse(response)
  if (!response.ok) {
    const detail = typeof body?.detail === 'string' ? body.detail : body?.message
    throw new ApiError(detail || `Request failed (${response.status}).`, response.status, body)
  }
  return body
}

export function getJson(path) {
  return apiRequest(path)
}

export function postJson(path, body = undefined) {
  return apiRequest(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function uploadWav(file) {
  return apiRequest('/api/audio/upload', {
    method: 'POST',
    headers: { 'content-type': 'audio/wav' },
    body: file,
  })
}
