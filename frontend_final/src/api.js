// The creator page may call the backend directly. The phone share page always
// uses the Vite same-origin /api proxy so a configured 127.0.0.1 never points
// back to the phone itself.
const isSharePage = window.location.pathname.endsWith('/share.html')
const configuredBase = (isSharePage ? '' : import.meta.env.VITE_API_BASE || '').replace(/\/$/, '')

function apiUrl(path) {
  return `${configuredBase}${path}`
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(apiUrl(path), options)
  } catch {
    throw new Error('无法连接本地识别服务，请确认后端正在运行后重试。')
  }
  if (response.ok) return response

  let message = `请求失败（${response.status}）`
  try {
    const body = await response.json()
    message = body.detail || message
  } catch {
    // Keep the status fallback when a proxy/network error has no JSON body.
  }
  throw new Error(message)
}

export async function analyzeRecording(wavBlob) {
  const upload = await request('/api/audio/upload', {
    method: 'POST',
    headers: {
      'Content-Type': 'audio/wav',
      'X-SoundClay-Filename': 'soundclay-recording.wav',
    },
    body: wavBlob,
  })
  const uploaded = await upload.json()
  const transcribed = await request('/api/stt/transcribe', {
    method: 'POST',
    headers: { 'X-SoundClay-Audio-Id': uploaded.audio_id },
  })
  return transcribed.json()
}

export async function confirmEmotion(emotion) {
  const response = await request('/api/emotion/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ emotion }),
  })
  return response.json()
}

export async function createPublicWork(payload) {
  const response = await request('/api/public/works', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  return response.json()
}

export async function startObsRecording() {
  await request('/api/obs/recording/start', { method: 'POST' })
}

export async function stopObsRecording() {
  await request('/api/obs/recording/stop', { method: 'POST' })
}

export async function getPublicWork(workId) {
  const response = await request(`/api/public/works/${encodeURIComponent(workId)}`)
  return response.json()
}

export function publicOrigin() {
  return (import.meta.env.VITE_PUBLIC_ORIGIN || window.location.origin).replace(/\/$/, '')
}

export function shareUrl(workId) {
  return `${publicOrigin()}/share.html?id=${encodeURIComponent(workId)}`
}

export function isLocalhostShareOrigin() {
  try {
    const host = new URL(publicOrigin()).hostname
    return host === 'localhost' || host === '127.0.0.1'
  } catch {
    return true
  }
}

export function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener('load', () => resolve(reader.result))
    reader.addEventListener('error', () => reject(new Error('无法读取作品文件。')))
    reader.readAsDataURL(blob)
  })
}
