import './integration-style.css'

import { API_BASE, WS_URL, getJson, postJson, uploadWav } from './api.js'
import { createRingSocket } from './socket.js'

const EMOTIONS = ['joy', 'anger', 'sadness', 'anxiety', 'neutral-mixed']
const state = {
  backend: 'checking',
  websocket: 'connecting',
  phase: 'ready',
  transcript: '',
  emotion: null,
  confidence: null,
  reason: '',
  confirmedEmotion: null,
  mode: 'express',
  features: { volume: 0, pitch: 0, brightness: 0 },
  recipe: null,
  motion: { twist: 0.65, burstStrength: 0.9, burstCount: 0, frozen: false },
  saved: null,
  busy: new Set(),
  events: [],
}

const app = document.querySelector('#app')
if (!app) throw new Error('Missing #app root element')

app.innerHTML = `
  <header class="masthead">
    <div>
      <p class="eyebrow">LOCAL EMOTION MATERIAL SYSTEM / P0</p>
      <h1>SoundClay <span>Integration Console</span></h1>
      <p class="intro">A lightweight end-to-end workspace for voice, expressed emotion, material recipes, motion and local saving.</p>
    </div>
    <div class="connection-panel" aria-label="Connection status">
      <div class="connection-row"><span id="backend-dot" class="status-dot"></span><span>Backend</span><strong id="backend-status">Checking</strong></div>
      <div class="connection-row"><span id="ws-dot" class="status-dot"></span><span>WebSocket</span><strong id="ws-status">Connecting</strong></div>
      <button id="reconnect-button" class="button button-quiet" type="button">Reconnect</button>
      <small id="endpoint-label"></small>
    </div>
  </header>

  <main class="workspace">
    <section class="panel panel-wide" aria-labelledby="voice-title">
      <div class="panel-heading"><span>01</span><div><p>VOICE INPUT</p><h2 id="voice-title">Upload and understand</h2></div><span id="phase-badge" class="badge">READY</span></div>
      <div class="split-grid">
        <div class="stack">
          <label class="file-drop" for="wav-file">
            <span>Choose a local WAV</span>
            <small id="file-label">PCM WAV recommended · up to 50 MB</small>
            <input id="wav-file" type="file" accept="audio/wav,.wav" />
          </label>
          <div class="button-row">
            <button id="upload-button" class="button" type="button">Upload WAV</button>
            <button id="transcribe-button" class="button button-primary" type="button">Start transcription</button>
          </div>
          <p id="voice-error" class="error-message" role="alert"></p>
        </div>
        <div class="mock-box">
          <label for="mock-transcript">No ring or local model? Run the complete flow with a mock transcript.</label>
          <textarea id="mock-transcript" rows="3">I feel nervous and worried because time is running out.</textarea>
          <button id="mock-transcript-button" class="button button-quiet" type="button">Analyze mock transcript</button>
        </div>
      </div>
      <div class="result-block">
        <p class="result-label">TRANSCRIPT</p>
        <p id="transcript-output" class="transcript empty">No transcript yet.</p>
      </div>
    </section>

    <section class="panel" aria-labelledby="emotion-title">
      <div class="panel-heading"><span>02</span><div><p>EXPRESSED EMOTION</p><h2 id="emotion-title">Review and confirm</h2></div></div>
      <div class="emotion-result">
        <div><small>INITIAL LABEL</small><strong id="emotion-output">—</strong></div>
        <div><small>CONFIDENCE</small><strong id="confidence-output">—</strong></div>
      </div>
      <p id="reason-output" class="muted">The local classifier result will appear here.</p>
      <fieldset id="emotion-options" class="choice-grid" disabled>
        <legend class="sr-only">Correct the emotion</legend>
        ${EMOTIONS.map((emotion) => `<label><input type="radio" name="emotion" value="${emotion}" /><span>${emotion}</span></label>`).join('')}
      </fieldset>
      <button id="confirm-emotion-button" class="button button-primary full" type="button" disabled>Confirm emotion</button>
      <p id="emotion-error" class="error-message" role="alert"></p>
    </section>

    <section class="panel" aria-labelledby="mode-title">
      <div class="panel-heading"><span>03</span><div><p>DIRECTION</p><h2 id="mode-title">Express or soothe</h2></div></div>
      <div class="mode-grid">
        <label><input type="radio" name="mode" value="express" checked /><span><strong>Express</strong><small>Amplify and articulate</small></span></label>
        <label><input type="radio" name="mode" value="soothe" /><span><strong>Soothe</strong><small>Settle and soften</small></span></label>
      </div>
      <button id="select-mode-button" class="button button-primary full" type="button" disabled>Generate material recipe</button>
      <p id="mode-error" class="error-message" role="alert"></p>
    </section>

    <section class="panel panel-wide" aria-labelledby="material-title">
      <div class="panel-heading"><span>04</span><div><p>REAL SIGNAL + RECIPE</p><h2 id="material-title">Material output</h2></div></div>
      <div class="feature-grid">
        ${['volume', 'pitch', 'brightness'].map((name) => `<div class="feature-card"><div><span>${name}</span><strong id="${name}-value">0.000</strong></div><div class="meter"><i id="${name}-meter"></i></div></div>`).join('')}
      </div>
      <div class="recipe-grid">
        <div><p>VOICE FX</p><pre id="voice-recipe">Waiting for mode selection…</pre></div>
        <div><p>AUDIO BED</p><pre id="bed-recipe">Waiting for mode selection…</pre></div>
        <div><p>VISUAL</p><pre id="visual-recipe">Waiting for mode selection…</pre></div>
      </div>
    </section>

    <section class="panel" aria-labelledby="motion-title">
      <div class="panel-heading"><span>05</span><div><p>MOCK RING / WEBSOCKET</p><h2 id="motion-title">Sculpt with motion</h2></div></div>
      <label class="range-row" for="twist-range"><span>Twist</span><output id="twist-output">0.65</output><input id="twist-range" type="range" min="0" max="1" step="0.01" value="0.65" /></label>
      <button id="twist-button" class="button full" type="button">Emit twist</button>
      <label class="range-row" for="burst-range"><span>Burst</span><output id="burst-output">0.90</output><input id="burst-range" type="range" min="0" max="1" step="0.01" value="0.90" /></label>
      <button id="burst-button" class="button full" type="button">Emit burst</button>
      <button id="freeze-button" class="button button-danger full" type="button">Freeze work</button>
      <div id="motion-readout" class="motion-readout">Twist 0.65 · Bursts 0 · Live</div>
      <p id="motion-error" class="error-message" role="alert"></p>
    </section>

    <section class="panel" aria-labelledby="save-title">
      <div class="panel-heading"><span>06</span><div><p>LOCAL ARCHIVE</p><h2 id="save-title">Save the work</h2></div></div>
      <label class="check-row"><input id="placeholder-screenshot" type="checkbox" /><span>Include a small generated placeholder PNG</span></label>
      <p class="muted">Processed audio is optional. The basic path saves metadata and any uploaded original WAV.</p>
      <button id="save-button" class="button button-primary full" type="button" disabled>Save locally</button>
      <div id="save-result" class="save-result empty">No saved work yet.</div>
      <p id="save-error" class="error-message" role="alert"></p>
    </section>

    <section class="panel panel-wide log-panel" aria-labelledby="log-title">
      <div class="panel-heading"><span>07</span><div><p>LIVE PROTOCOL</p><h2 id="log-title">Event log</h2></div><button id="clear-log-button" class="button button-quiet" type="button">Clear</button></div>
      <ol id="event-log" class="event-log"><li class="empty">Waiting for events…</li></ol>
    </section>
  </main>

  <footer><span>Default page: zero Three.js initialization</span><span>Local-first · No cloud dependency</span></footer>
`

const byId = (id) => document.getElementById(id)
const controls = {
  upload: byId('upload-button'),
  transcribe: byId('transcribe-button'),
  mockTranscript: byId('mock-transcript-button'),
  confirmEmotion: byId('confirm-emotion-button'),
  selectMode: byId('select-mode-button'),
  twist: byId('twist-button'),
  burst: byId('burst-button'),
  freeze: byId('freeze-button'),
  save: byId('save-button'),
}

function setIndicator(prefix, status, detail = '') {
  const dot = byId(`${prefix}-dot`)
  const label = byId(`${prefix}-status`)
  dot.dataset.status = status
  label.textContent = detail ? `${status} · ${detail}` : status
}

function formatJson(value) {
  return value ? JSON.stringify(value, null, 2) : 'Waiting for mode selection…'
}

function addEvent(type, payload = {}, timestamp = Date.now()) {
  const duplicate = state.events.some((item) => item.type === type && item.timestamp === timestamp)
  if (duplicate) return false
  state.events.unshift({ type, payload, timestamp })
  state.events = state.events.slice(0, 50)
  const log = byId('event-log')
  log.replaceChildren(...state.events.map((item) => {
    const row = document.createElement('li')
    const time = new Date(item.timestamp).toLocaleTimeString([], { hour12: false })
    const summary = JSON.stringify(item.payload)
    row.innerHTML = `<time>${time}</time><strong>${item.type}</strong><span></span>`
    row.querySelector('span').textContent = summary.length > 180 ? `${summary.slice(0, 177)}…` : summary
    return row
  }))
  return true
}

function showError(section, error) {
  byId(`${section}-error`).textContent = error?.message || String(error)
  addEvent('error', { section, message: error?.message || String(error) })
}

function clearError(section) {
  byId(`${section}-error`).textContent = ''
}

function setBusy(name, busy) {
  if (busy) state.busy.add(name)
  else state.busy.delete(name)
  const button = controls[name]
  if (button) {
    button.disabled = busy || (name === 'confirmEmotion' && !state.emotion) || (name === 'selectMode' && !state.confirmedEmotion) || (name === 'save' && !state.recipe)
    button.classList.toggle('is-loading', busy)
  }
}

async function runAction(name, section, action) {
  clearError(section)
  setBusy(name, true)
  try {
    return await action()
  } catch (error) {
    showError(section, error)
    return null
  } finally {
    setBusy(name, false)
  }
}

function renderFeatures(features = {}) {
  for (const name of ['volume', 'pitch', 'brightness']) {
    const numeric = Number(features[name])
    const value = Number.isFinite(numeric) ? Math.max(0, Math.min(1, numeric)) : 0
    state.features[name] = value
    byId(`${name}-value`).textContent = value.toFixed(3)
    byId(`${name}-meter`).style.width = `${value * 100}%`
  }
}

function renderEmotion(data) {
  if (!data?.emotion || !EMOTIONS.includes(data.emotion)) return
  state.emotion = data.emotion
  state.confidence = Number(data.confidence)
  state.reason = data.reason || ''
  byId('emotion-output').textContent = state.emotion
  byId('confidence-output').textContent = Number.isFinite(state.confidence) ? `${Math.round(state.confidence * 100)}%` : '—'
  byId('reason-output').textContent = state.reason || 'No explanation supplied.'
  const option = document.querySelector(`input[name="emotion"][value="${state.emotion}"]`)
  if (option) option.checked = true
  byId('emotion-options').disabled = false
  controls.confirmEmotion.disabled = false
}

function renderTranscript(transcript) {
  state.transcript = typeof transcript === 'string' ? transcript : ''
  byId('transcript-output').textContent = state.transcript || 'No transcript yet.'
  byId('transcript-output').classList.toggle('empty', !state.transcript)
}

function renderRecipe(recipe) {
  state.recipe = recipe || null
  byId('voice-recipe').textContent = formatJson(recipe?.voiceFx)
  byId('bed-recipe').textContent = formatJson(recipe?.soundscape)
  byId('visual-recipe').textContent = formatJson(recipe?.visual)
  controls.save.disabled = !state.recipe
}

function renderMotion() {
  const status = state.motion.frozen ? 'Frozen' : 'Live'
  byId('motion-readout').textContent = `Twist ${Number(state.motion.twist).toFixed(2)} · Bursts ${state.motion.burstCount} · ${status}`
}

function renderSession(session) {
  if (!session || typeof session !== 'object') return
  state.phase = session.phase || state.phase
  byId('phase-badge').textContent = state.phase.replaceAll('_', ' ').toUpperCase()
  renderTranscript(session.transcript)
  renderFeatures(session.features)
  renderEmotion(session)
  if (session.emotion && ['mode_choice', 'materializing', 'sculpting', 'saved'].includes(session.phase)) {
    state.confirmedEmotion = session.emotion
    controls.selectMode.disabled = false
  }
  if (session.mode) {
    state.mode = session.mode
    const mode = document.querySelector(`input[name="mode"][value="${session.mode}"]`)
    if (mode) mode.checked = true
  }
  renderRecipe(session.recipe)
  if (session.motion) state.motion = { ...state.motion, ...session.motion }
  renderMotion()
}

function handleEvent(message) {
  const { type, payload = {}, timestamp = Date.now() } = message
  if (!addEvent(type, payload, timestamp)) return
  if (type === 'status' && payload.phase) {
    state.phase = payload.phase
    byId('phase-badge').textContent = String(payload.phase).replaceAll('_', ' ').toUpperCase()
  } else if (type === 'transcript_ready') {
    renderTranscript(payload.transcript)
  } else if (type === 'audio_features_ready') {
    renderFeatures(payload)
  } else if (type === 'emotion_ready') {
    renderEmotion(payload)
  } else if (type === 'material_ready') {
    renderFeatures(payload.features)
    renderRecipe(payload.recipe)
  } else if (type === 'twist') {
    state.motion.twist = payload.value
    renderMotion()
  } else if (type === 'burst') {
    state.motion.burstStrength = payload.strength
    state.motion.burstCount += 1
    renderMotion()
  } else if (type === 'freeze') {
    state.motion.frozen = true
    state.motion.frozenAt = timestamp
    renderMotion()
  } else if (type === 'saved') {
    renderSaved(payload)
  }
}

function logWhenSocketOffline(type, payload) {
  if (state.websocket !== 'online') addEvent(type, payload)
}

function renderSaved(result) {
  state.saved = result
  const target = byId('save-result')
  target.classList.remove('empty')
  target.replaceChildren()
  const id = document.createElement('strong')
  id.textContent = result?.id || 'Saved'
  const path = document.createElement('code')
  path.textContent = result?.path || result?.files?.metadata || 'Local work directory'
  target.append(id, path)
}

function placeholderPngDataUrl() {
  const canvas = document.createElement('canvas')
  canvas.width = 320
  canvas.height = 180
  const context = canvas.getContext('2d')
  context.fillStyle = '#15141a'
  context.fillRect(0, 0, canvas.width, canvas.height)
  const gradient = context.createLinearGradient(0, 0, canvas.width, canvas.height)
  gradient.addColorStop(0, '#ff6f61')
  gradient.addColorStop(1, '#8d82ff')
  context.fillStyle = gradient
  context.beginPath()
  context.arc(160, 90, 54, 0, Math.PI * 2)
  context.fill()
  context.fillStyle = '#ffffff'
  context.font = '16px sans-serif'
  context.fillText('SoundClay P0', 18, 30)
  return canvas.toDataURL('image/png')
}

const ringSocket = createRingSocket({
  url: WS_URL,
  onEvent: handleEvent,
  onStatus: ({ status, detail }) => {
    state.websocket = status
    setIndicator('ws', status, detail)
  },
})

async function checkBackend() {
  state.backend = 'checking'
  setIndicator('backend', 'checking')
  try {
    const health = await getJson('/health')
    if (health?.ok !== true) throw new Error('Unexpected health response')
    state.backend = 'online'
    setIndicator('backend', 'online')
    addEvent('status', { backend: 'online' })
    renderSession(await getJson('/api/session/current'))
  } catch (error) {
    state.backend = 'offline'
    setIndicator('backend', 'offline')
    showError('voice', error)
  }
}

byId('endpoint-label').textContent = `${API_BASE} · ${WS_URL}`
byId('reconnect-button').addEventListener('click', () => {
  checkBackend()
  ringSocket.connect({ manual: true })
})
byId('wav-file').addEventListener('change', (event) => {
  const file = event.target.files?.[0]
  byId('file-label').textContent = file ? `${file.name} · ${(file.size / 1024).toFixed(1)} KB` : 'PCM WAV recommended · up to 50 MB'
})
controls.upload.addEventListener('click', () => runAction('upload', 'voice', async () => {
  const file = byId('wav-file').files?.[0]
  if (!file) throw new Error('Choose a WAV file first.')
  if (!file.name.toLowerCase().endsWith('.wav')) throw new Error('Only WAV files are accepted.')
  const result = await uploadWav(file)
  renderFeatures(result.features)
  logWhenSocketOffline('audio_features_ready', result.features)
  return result
}))
controls.transcribe.addEventListener('click', () => runAction('transcribe', 'voice', async () => {
  const result = await postJson('/api/stt/transcribe')
  renderTranscript(result.transcript)
  renderEmotion(result)
  renderFeatures(result.features)
  logWhenSocketOffline('transcript_ready', { transcript: result.transcript })
  logWhenSocketOffline('emotion_ready', { emotion: result.emotion, confidence: result.confidence })
  return result
}))
controls.mockTranscript.addEventListener('click', () => runAction('mockTranscript', 'voice', async () => {
  const transcript = byId('mock-transcript').value.trim()
  if (!transcript) throw new Error('Enter a mock transcript.')
  const result = await postJson('/api/mock/transcript', { transcript })
  renderTranscript(result.transcript)
  renderEmotion(result)
  renderFeatures(result.features)
  logWhenSocketOffline('transcript_ready', { transcript: result.transcript })
  logWhenSocketOffline('emotion_ready', { emotion: result.emotion, confidence: result.confidence })
  return result
}))
controls.confirmEmotion.addEventListener('click', () => runAction('confirmEmotion', 'emotion', async () => {
  const emotion = document.querySelector('input[name="emotion"]:checked')?.value
  if (!emotion) throw new Error('Select an emotion.')
  const result = await postJson('/api/emotion/confirm', { emotion })
  state.confirmedEmotion = emotion
  renderSession(result)
  controls.selectMode.disabled = false
  logWhenSocketOffline('status', { phase: result.phase })
  return result
}))
controls.selectMode.addEventListener('click', () => runAction('selectMode', 'mode', async () => {
  const mode = document.querySelector('input[name="mode"]:checked')?.value
  const result = await postJson('/api/mode/select', { mode })
  state.mode = mode
  renderFeatures(result.features)
  renderRecipe(result.recipe)
  logWhenSocketOffline('material_ready', result)
  return result
}))

for (const name of ['twist', 'burst']) {
  byId(`${name}-range`).addEventListener('input', (event) => {
    byId(`${name}-output`).value = Number(event.target.value).toFixed(2)
  })
}
controls.twist.addEventListener('click', () => runAction('twist', 'motion', async () => {
  const value = Number(byId('twist-range').value)
  const result = await postJson(`/api/mock/twist?value=${encodeURIComponent(value)}`)
  handleEvent(result)
  return result
}))
controls.burst.addEventListener('click', () => runAction('burst', 'motion', async () => {
  const strength = Number(byId('burst-range').value)
  const result = await postJson(`/api/mock/burst?strength=${encodeURIComponent(strength)}`)
  handleEvent(result)
  return result
}))
controls.freeze.addEventListener('click', () => runAction('freeze', 'motion', async () => {
  const result = await postJson('/api/mock/freeze')
  handleEvent(result)
  return result
}))
controls.save.addEventListener('click', () => runAction('save', 'save', async () => {
  const includePlaceholder = byId('placeholder-screenshot').checked
  const result = await postJson('/api/save', {
    screenshot_data_url: includePlaceholder ? placeholderPngDataUrl() : null,
    final_motion: state.motion,
  })
  renderSaved(result)
  logWhenSocketOffline('saved', result)
  return result
}))
byId('clear-log-button').addEventListener('click', () => {
  state.events = []
  byId('event-log').innerHTML = '<li class="empty">Waiting for events…</li>'
})

renderFeatures(state.features)
renderMotion()
checkBackend()
ringSocket.connect()

window.addEventListener('beforeunload', () => ringSocket.close())
