import './style.css'
import { createSculpture } from './sculpture.js'
import { SoundClayAudio } from './audio.js'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000/ws/ring'
const app = document.querySelector('#app')

app.innerHTML = `
  <main class="soundclay" data-state="idle">
    <p class="brand">SoundClay</p>
    <div class="connection-status" id="connection-status" data-connection="connecting">正在连接后端</div>

    <section class="stage" aria-live="polite">
      <div class="visual" id="visual" aria-hidden="true"></div>
      <div class="interaction-layer" id="interaction-layer" aria-label="声音塑形区域"></div>

      <div class="copy" id="copy"></div>
      <div class="controls" id="controls"></div>
      <div class="toast" id="toast">已留下</div>

      <div class="progress-dots" aria-hidden="true">
        <span class="progress-dot" data-step="0"></span>
        <span class="progress-dot" data-step="1"></span>
        <span class="progress-dot" data-step="2"></span>
        <span class="progress-dot" data-step="3"></span>
      </div>
    </section>
  </main>
`

const root = document.querySelector('.soundclay')
const visual = document.querySelector('#visual')
const interactionLayer = document.querySelector('#interaction-layer')
const copy = document.querySelector('#copy')
const controls = document.querySelector('#controls')
const toast = document.querySelector('#toast')
const connectionStatus = document.querySelector('#connection-status')
const dots = [...document.querySelectorAll('.progress-dot')]

const sculpture = createSculpture(visual)
const audio = new SoundClayAudio({
  onLevel: (level) => sculpture.setAudioLevel(level),
  onProgress: (progress) => {
    sculpture.setProgress(progress)
    const bar = document.querySelector('.timeline-progress')
    if (bar) bar.style.width = `${Math.round(progress * 1000) / 10}%`
  },
})

const STATE_INDEX = { idle: 0, recording: 0, mode: 1, sculpt: 2, result: 3 }
let state = 'idle'
let mode = 0.5
let modeSelectionCommitted = false
let recordingStartedAt = 0
let recordingTimer = 0
let recordingTimeout = 0
let nodes = []
let toastTimer = 0
let pointer = null
let hintTimer = 0
let completionTimer = 0
let isCompleting = false
let localSizeDemo = 0
let materialRequest = Promise.resolve(null)
let savedWork = null
let finalMotion = {}
const lastAbletonSync = { twist: 0, finger: 0 }
const heldTwistKeys = new Set()
let socket = null
let reconnectTimer = 0
let reconnectDelay = 800
let ringEnabled = false
let ringConnected = false
let ringFrozen = false
let activeRingSessionId = null
const freezeStateBySession = new Map()
const seenDiscreteEvents = new Set()
const discreteEventOrder = []

const icons = {
  play: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10-6.5-10-6.5Z"/></svg>`,
  pause: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 6v12M15.5 6v12"/></svg>`,
  share: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4m0 0L8 8m4-4 4 4M5 13v6h14v-6"/></svg>`,
  restart: `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 9A8 8 0 1 1 4 14m.5-5V4.5M4.5 9H9"/></svg>`,
}

function setActiveDot() {
  const active = STATE_INDEX[state]
  dots.forEach((dot, index) => dot.classList.toggle('is-active', index === active))
}

function setState(nextState) {
  state = nextState
  if (nextState === 'mode') modeSelectionCommitted = false
  root.dataset.state = state
  sculpture.setState(state)
  setActiveDot()
  render()
}

function updateConnectionStatus(message, connection = 'offline') {
  connectionStatus.textContent = message
  connectionStatus.dataset.connection = connection
}

function eventSessionId(payload = {}) {
  return payload.sessionId || payload.session_id || null
}

function resetRingEventState(sessionId = activeRingSessionId) {
  activeRingSessionId = sessionId
  ringFrozen = false
  isCompleting = false
  clearTimeout(completionTimer)
  sculpture.freeze(false)
  sculpture.setTwist(0)
  sculpture.setSize?.(0)
  freezeStateBySession.clear()
  seenDiscreteEvents.clear()
  discreteEventOrder.length = 0
}

function acceptsRingSession(eventType, payload) {
  const sessionId = eventSessionId(payload)
  if (!sessionId) return true
  if (!activeRingSessionId || sessionId === activeRingSessionId) {
    activeRingSessionId = sessionId
    return true
  }

  const phase = String(payload.phase || '').toLowerCase()
  if (eventType === 'audio_ready' || (eventType === 'status' && ['connected', 'ready', 'recording'].includes(phase))) {
    resetRingEventState(sessionId)
    return true
  }
  return false
}

function rememberDiscreteEvent(eventType, timestamp, payload) {
  const sessionId = eventSessionId(payload) || activeRingSessionId || 'unknown'
  const discriminator = payload.sequence ?? payload.deviceTimestampMs ?? timestamp
  if (discriminator == null) return true
  const key = `${sessionId}:${eventType}:${discriminator}`
  if (seenDiscreteEvents.has(key)) return false
  seenDiscreteEvents.add(key)
  discreteEventOrder.push(key)
  while (discreteEventOrder.length > 512) seenDiscreteEvents.delete(discreteEventOrder.shift())
  return true
}

async function loadRingAudio(payload) {
  const audioUrl = payload.audioUrl
  if (!audioUrl) return
  const resolved = new URL(audioUrl, `${API_BASE}/`).href
  try {
    await audio.loadUrl(`${resolved}?audio_id=${encodeURIComponent(payload.audio_id || '')}`)
    setMode(0.5)
    setState('mode')
  } catch (error) {
    showError(error instanceof Error ? error.message : '无法读取戒指录音。')
  }
}

function handleSocketEvent(message) {
  if (!message || typeof message !== 'object' || typeof message.type !== 'string') return
  const payload = message.payload && typeof message.payload === 'object' ? message.payload : {}
  if (!acceptsRingSession(message.type, payload)) return

  switch (message.type) {
    case 'status': {
      if (typeof payload.ringEnabled === 'boolean') ringEnabled = payload.ringEnabled
      if (typeof payload.ringConnected === 'boolean') ringConnected = payload.ringConnected
      if (typeof payload.connected === 'boolean') ringConnected = payload.connected
      if (payload.phase === 'connected') ringConnected = true
      const label = ringConnected ? '戒指已连接' : ringEnabled ? '等待戒指' : '后端已连接 · 模拟模式'
      updateConnectionStatus(label, ringConnected ? 'ring' : 'online')
      break
    }
    case 'recording':
      if (state === 'idle') setState('recording')
      break
    case 'audio_ready':
      void loadRingAudio(payload)
      break
    case 'imu': {
      if (state !== 'sculpt' || ringFrozen) break
      const twist = Math.min(1, Math.max(-1, Number(payload.twist) || 0))
      const energy = Math.min(1, Math.max(0, Number(payload.accelMag) || 0))
      sculpture.setTwist(twist)
      sculpture.setEnergy(energy)

      // 预留完整 IMU 姿态：后端未来可直接发送弧度制 pitch / yaw / roll。
      if ([payload.pitch, payload.yaw, payload.roll].some((value) => Number.isFinite(Number(value)))) {
        sculpture.setOrientation({
          pitch: payload.pitch,
          yaw: payload.yaw,
          roll: payload.roll,
        })
      }

      audio.setMorph({ space: (twist + 1) / 2, energy })

      const fingerValue = payload.fingerX ?? payload.finger ?? payload.size ?? payload.scale
      if (Number.isFinite(Number(fingerValue))) applySizeControl(Number(fingerValue))
      break
    }
    case 'twist': {
      if (state !== 'sculpt' || ringFrozen) break
      // 最终硬件接口的 value 已经是 -1 ~ 1，不能再次从 0 ~ 1 映射。
      const twist = Math.min(1, Math.max(-1, Number(payload.value) || 0))
      sculpture.setTwist(twist)
      audio.setMorph({ space: (twist + 1) / 2 })
      break
    }
    case 'finger':
    case 'finger_move':
    case 'size':
    case 'scale':
    case 'depth': {
      if (state !== 'sculpt' || ringFrozen) break
      const value = Number(payload.value ?? payload.x ?? payload.position ?? payload.size ?? 0)
      applySizeControl(value)
      break
    }
    case 'double_tap':
    case 'doubletap':
    case 'double_click': {
      if (state !== 'sculpt' || ringFrozen || payload.active === false) break
      if (!rememberDiscreteEvent('freeze', message.timestamp, payload)) break
      completeCreation({ message: '作品已凝固' })
      break
    }
    case 'burst': {
      if (state !== 'sculpt' || ringFrozen) break
      if (!rememberDiscreteEvent('burst', message.timestamp, payload)) break
      triggerBurst(payload.strength)
      break
    }
    case 'push': {
      if (state !== 'sculpt' || ringFrozen) break
      if (!rememberDiscreteEvent('push', message.timestamp, payload)) break
      const rawDepth = Number(payload.value ?? payload.depth ?? payload.strength ?? 1)
      const direction = String(payload.direction ?? payload.motion ?? '').toLowerCase()
      if (direction === 'backward' || direction === 'back' || direction === 'pull' || rawDepth < 0) {
        triggerPull(Math.abs(rawDepth) || 1)
      } else {
        triggerPush(Math.abs(rawDepth) || 1)
      }
      break
    }
    case 'pull': {
      if (state !== 'sculpt' || ringFrozen) break
      if (!rememberDiscreteEvent('pull', message.timestamp, payload)) break
      triggerPull(Math.abs(Number(payload.strength ?? payload.depth ?? payload.value ?? 1)) || 1)
      break
    }
    case 'freeze': {
      if (state !== 'sculpt' || ringFrozen || payload.active === false) break
      if (!rememberDiscreteEvent('freeze', message.timestamp, payload)) break
      completeCreation({ message: '作品已凝固' })
      break
    }
    case 'saved':
      savedWork = payload
      if (state === 'result' && payload.id) showToast(`作品已保存 · ${payload.id}`)
      break
    case 'error':
      updateConnectionStatus(payload.message || '戒指连接异常', 'error')
      showToast(payload.recommendedAction || payload.message || '戒指连接异常')
      break
    default:
      break
  }
}

function connectRingSocket() {
  if (socket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(socket.readyState)) return
  updateConnectionStatus('正在连接后端', 'connecting')
  socket = new WebSocket(WS_URL)
  socket.addEventListener('open', () => {
    reconnectDelay = 800
    updateConnectionStatus('后端已连接 · 模拟模式', 'online')
  })
  socket.addEventListener('message', (event) => {
    try {
      handleSocketEvent(JSON.parse(event.data))
    } catch {
      updateConnectionStatus('收到无效事件', 'error')
    }
  })
  socket.addEventListener('close', () => {
    socket = null
    ringConnected = false
    updateConnectionStatus('后端离线 · 本地模式', 'offline')
    clearTimeout(reconnectTimer)
    reconnectTimer = window.setTimeout(connectRingSocket, reconnectDelay)
    reconnectDelay = Math.min(8000, reconnectDelay * 1.7)
  })
  socket.addEventListener('error', () => socket?.close())
}

function modeName() {
  if (mode < 0.38) return '释放'
  if (mode > 0.62) return '舒缓'
  return '混合'
}

// mode 的语义是：1 = 舒缓（滑块左侧），0 = 释放（滑块右侧）。
// 预览旋转使用：-1 = 向左旋转，0 = 停止，1 = 向右旋转。
function modePreviewDirection() {
  return (1 - mode) * 2 - 1
}

function resultName() {
  if (mode < 0.38) return '声音向外生长'
  if (mode > 0.62) return '声音慢慢落下'
  return '声音在两端之间'
}

function render() {
  clearInterval(recordingTimer)

  if (state === 'idle') {
    copy.innerHTML = `
      <h1 class="title">发出一段声音</h1>
      <p class="subtitle">说话、唱歌，或发出任何声音。</p>
    `
    controls.innerHTML = `
      <button class="icon-button record-button" id="record-button" aria-label="开始录音" data-recording="false">
        <span class="record-dot"></span>
      </button>
      <div class="tiny-label">点击开始</div>
    `
    document.querySelector('#record-button').addEventListener('click', startRecording)
    return
  }

  if (state === 'recording') {
    copy.innerHTML = `
      <h1 class="title">正在聆听</h1>
      <p class="subtitle">声音越自由，材料越丰富。</p>
    `
    controls.innerHTML = ringConnected
      ? `<div class="ring-listening"><span class="ring-pulse"></span><span>请长按戒指说话</span></div>`
      : `
        <button class="icon-button record-button" id="stop-button" aria-label="结束录音" data-recording="true">
          <span class="record-dot"></span>
        </button>
        <div class="tiny-label" id="record-time">00:00</div>
      `
    document.querySelector('#stop-button')?.addEventListener('click', stopRecording)
    updateRecordingTime()
    recordingTimer = window.setInterval(updateRecordingTime, 250)
    return
  }

  if (state === 'mode') {
    copy.innerHTML = `
      <h1 class="title">选择声音的方向</h1>
      <p class="subtitle">向左滑动进入舒缓模式，向右滑动进入释放模式。</p>
    `
    controls.innerHTML = `
      <div class="mode-control">
        <div class="mode-labels"><span>舒缓</span><span>${modeName()}</span><span>释放</span></div>
        <input class="mode-slider" id="mode-slider" type="range" min="0" max="100" value="${Math.round((1 - mode) * 100)}" aria-label="向左选择舒缓模式，向右选择释放模式" />
      </div>
    `

    const slider = document.querySelector('#mode-slider')
    const commitSliderSelection = () => {
      const sliderPosition = Number(slider.value) / 100
      // 松手时吸附到左右模式，确保一次明确的滑动只触发一次场景音符。
      setMode(sliderPosition < 0.5 ? 1 : 0)
      enterSculpt()
    }
    slider.addEventListener('input', () => {
      const sliderPosition = Number(slider.value) / 100
      setMode(1 - sliderPosition)

      if (sliderPosition <= 0.01 || sliderPosition >= 0.99) enterSculpt()
    })
    slider.addEventListener('change', commitSliderSelection)
    slider.addEventListener('pointerup', commitSliderSelection)
    return
  }

  if (state === 'sculpt') {
    copy.innerHTML = `
      <h1 class="title">用动作雕刻万花筒</h1>
      <p class="subtitle">转腕旋转 · 挥动爆散 · 左小右大 · 双击凝固</p>
    `
    const interactionHint = ringConnected
      ? '转腕旋转 · 快挥爆散 · 手指左小右大 · 双击凝固'
      : '拖动旋转 · 快甩爆散 · Shift＋横拖大小 · 双击凝固'

    controls.innerHTML = `
      <div class="sculpt-hud">
        <div class="timeline" aria-label="作品播放进度">
          <div class="timeline-track"><div class="timeline-progress"></div></div>
          ${nodes.map((node) => `<span class="timeline-node" style="left:${node.progress * 100}%"></span>`).join('')}
        </div>
        <div class="hint" id="sculpt-hint">${interactionHint}</div>
        <div class="demo-actions" aria-label="交互动作测试">
          <button class="gesture-button" id="demo-sphere" type="button">转腕</button>
          <button class="gesture-button" id="demo-burst" type="button">挥动</button>
          <button class="gesture-button" id="demo-size" type="button">大小</button>
          <button class="gesture-button gesture-button--primary" id="finish-button" type="button">凝固</button>
        </div>
      </div>
    `
    document.querySelector('#demo-sphere')?.addEventListener('click', demoSphere)
    document.querySelector('#demo-burst')?.addEventListener('click', () => triggerBurst(1, { syncAbleton: true }))
    document.querySelector('#demo-size')?.addEventListener('click', demoSize)
    document.querySelector('#finish-button')?.addEventListener('click', finishCreation)
    clearTimeout(hintTimer)
    hintTimer = window.setTimeout(() => {
      const hint = document.querySelector('#sculpt-hint')
      if (hint) hint.style.opacity = '0'
    }, 4300)
    return
  }

  copy.innerHTML = `
    <h1 class="result-title">${resultName()}</h1>
    <p class="subtitle">你的声音已经成形</p>
  `
  controls.innerHTML = `
    <div class="result-actions">
      <button class="icon-button" id="play-button" aria-label="在 Ableton Live 中播放">${icons.play}</button>
      <button class="icon-button" id="share-button" aria-label="分享作品">${icons.share}</button>
      <button class="icon-button" id="restart-button" aria-label="重新开始">${icons.restart}</button>
    </div>
    <div class="tiny-label">播放 · 分享 · 重来</div>
  `
  document.querySelector('#play-button').addEventListener('click', togglePlayback)
  document.querySelector('#share-button').addEventListener('click', shareWork)
  document.querySelector('#restart-button').addEventListener('click', restart)
}

async function startRecording() {
  try {
    if (ringConnected) {
      const response = await fetch(`${API_BASE}/api/ring/session/start`, { method: 'POST' })
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}))
        throw new Error(detail.detail || `无法启动戒指录音（HTTP ${response.status}）。`)
      }
      recordingStartedAt = performance.now()
      setState('recording')
      return
    }
    await audio.startRecording()
    recordingStartedAt = performance.now()
    setState('recording')
    recordingTimeout = window.setTimeout(stopRecording, 30000)
  } catch (error) {
    showError(error instanceof Error ? error.message : '无法开始录音。')
  }
}

function updateRecordingTime() {
  const target = document.querySelector('#record-time')
  if (!target) return
  const seconds = Math.max(0, Math.floor((performance.now() - recordingStartedAt) / 1000))
  target.textContent = `00:${String(seconds).padStart(2, '0')}`
}

async function stopRecording() {
  clearTimeout(recordingTimeout)
  clearInterval(recordingTimer)

  try {
    await audio.stopRecording()
    setMode(0.5)
    setState('mode')
  } catch (error) {
    showError(error instanceof Error ? error.message : '无法完成录音。')
  }
}

function setMode(value) {
  mode = Math.min(1, Math.max(0, value))
  sculpture.setMode(mode)
  sculpture.setPreviewRotation(modePreviewDirection())
  audio.setMode(mode)

  const labels = document.querySelector('.mode-labels')
  if (labels) labels.children[1].textContent = modeName()
  const slider = document.querySelector('#mode-slider')
  const sliderValue = Math.round((1 - mode) * 100)
  if (slider && Number(slider.value) !== sliderValue) slider.value = String(sliderValue)
}

function enterSculpt() {
  if (modeSelectionCommitted) return materialRequest
  modeSelectionCommitted = true
  nodes = []
  savedWork = null
  finalMotion = { burstCount: 0, frozen: false, size: 0, twist: 0 }
  ringFrozen = false
  isCompleting = false
  clearTimeout(completionTimer)
  sculpture.freeze(false)
  sculpture.setPreviewRotation(0)
  sculpture.setTwist(0)
  sculpture.setSize?.(0)
  localSizeDemo = 0
  audio.setMode(mode)
  // 浏览器仅静音分析录音并驱动粒子，观众听到的声音只来自 Ableton Live。
  audio.playLoop({ muted: true })
  setState('sculpt')
  materialRequest = triggerAbletonScene().catch((error) => {
    showToast(error instanceof Error ? error.message : '无法触发 Ableton Live')
    return null
  })
  return materialRequest
}

async function triggerAbletonScene() {
  const response = await fetch(`${API_BASE}/api/mode/select`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ mode: mode < 0.5 ? 'express' : 'soothe' }),
  })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail || `无法触发 Ableton Live（HTTP ${response.status}）`)
  }
  return response.json()
}

function syncAbletonMotion(type, value, throttleMs = 0) {
  const now = performance.now()
  if (throttleMs > 0 && now - (lastAbletonSync[type] || 0) < throttleMs) return
  lastAbletonSync[type] = now
  const query = new URLSearchParams({ value: String(value) })
  void fetch(`${API_BASE}/api/ableton/motion/${type}?${query}`, { method: 'POST' }).catch(() => {})
}

function showToast(message = '已留下') {
  clearTimeout(toastTimer)
  toast.textContent = message
  toast.classList.add('is-visible')
  toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 900)
}

function addNode() {
  if (ringFrozen) return
  const progress = audio.duration > 0 && audio.context
    ? ((audio.context.currentTime - audio.startedAt) % audio.duration) / audio.duration
    : 0
  nodes.push({ progress, mode, space: audio.space, energy: audio.energy })
  showToast('已留下')
  render()
}

function demoSphere() {
  if (state !== 'sculpt' || ringFrozen) return
  sculpture.setTwist(0.9, true)
  finalMotion.twist = 0.9
  syncAbletonMotion('twist', 0.9)
  audio.setMorph({ space: 0.95 })
  showToast('万花筒正在球化')
  window.setTimeout(() => {
    sculpture.setTwist(0)
    finalMotion.twist = 0
    syncAbletonMotion('twist', 0)
  }, 520)
}

function triggerBurst(strength = 1, { syncAbleton = false } = {}) {
  if (state !== 'sculpt' || ringFrozen) return
  const normalized = Math.min(1.35, Math.max(0.16, Number(strength) || 1))
  sculpture.burst(normalized)
  finalMotion.burstCount = Number(finalMotion.burstCount || 0) + 1
  finalMotion.lastBurstStrength = normalized
  if (syncAbleton) syncAbletonMotion('burst', Math.min(1, normalized))
  audio.setMorph({ energy: Math.min(1, 0.72 + normalized * 0.2) })
  showToast('粒子爆散已保留')
}

function applySizeControl(value, { notify = false, syncAbleton = false } = {}) {
  if (state !== 'sculpt' || ringFrozen) return 0
  const normalized = Math.min(1, Math.max(-1, Number(value) || 0))
  localSizeDemo = normalized
  finalMotion.size = normalized
  sculpture.setSize(normalized)

  // 左侧声音更小、球体更远更小；右侧声音更大、球体更近更大。
  const loudness = (normalized + 1) * 0.5
  audio.setMorph({ energy: 0.08 + loudness * 0.92 })
  if (syncAbleton) syncAbletonMotion('finger', normalized, 35)

  if (notify) {
    if (normalized < -0.34) showToast('小球 · 小声')
    else if (normalized > 0.34) showToast('大球 · 大声')
    else showToast('标准大小')
  }
  return normalized
}

function demoSize() {
  const next = localSizeDemo > 0.45 ? -1 : 1
  applySizeControl(next, { notify: true, syncAbleton: true })
}

function triggerPush(strength = 1) {
  if (state !== 'sculpt' || ringFrozen) return
  const normalized = Math.min(1.35, Math.max(0.12, Number(strength) || 1))
  const next = sculpture.nudgeSize(-normalized * 0.52)
  applySizeControl(next, { notify: true, syncAbleton: true })
}

function triggerPull(strength = 1) {
  if (state !== 'sculpt' || ringFrozen) return
  const normalized = Math.min(1.35, Math.max(0.12, Number(strength) || 1))
  const next = sculpture.nudgeSize(normalized * 0.52)
  applySizeControl(next, { notify: true, syncAbleton: true })
}

function completeCreation({ message = '作品已凝固', burst = false } = {}) {
  if (state !== 'sculpt' || ringFrozen || isCompleting) return
  isCompleting = true

  if (burst) {
    sculpture.burst(0.72)
    showToast('正在凝固')
  }

  const finalize = () => {
    completionTimer = 0
    ringFrozen = true
    finalMotion.frozen = true
    finalMotion.frozenAt = Date.now()
    sculpture.setTwist(0)
    sculpture.freeze(true)
    audio.stopPlayback()
    setState('result')
    showToast(message)
    isCompleting = false
    void stopAbletonPlayback().catch((error) => {
      showToast(error instanceof Error ? error.message : '无法停止 Ableton Live')
    })
    void saveCurrentWork()
  }

  if (burst) completionTimer = window.setTimeout(finalize, 260)
  else finalize()
}

function finishCreation() {
  completeCreation({ message: '作品已完成', burst: false })
}

async function stopAbletonPlayback() {
  const response = await fetch(`${API_BASE}/api/ableton/stop`, { method: 'POST' })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.detail || `无法停止 Ableton Live（HTTP ${response.status}）`)
  }
  const result = await response.json()
  if (!result.ok) throw new Error('Ableton Live 未连接，停止指令未发送')
  return result
}

async function togglePlayback() {
  try {
    await triggerAbletonScene()
    showToast('已在 Ableton Live 中播放')
  } catch (error) {
    showToast(error instanceof Error ? error.message : '无法触发 Ableton Live')
  }
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.addEventListener('load', () => resolve(reader.result), { once: true })
    reader.addEventListener('error', () => reject(new Error('无法编码本地作品')), { once: true })
    reader.readAsDataURL(blob)
  })
}

async function saveCurrentWork() {
  try {
    await materialRequest
    const screenshotBlob = await sculpture.captureBlob()
    const processedAudioBlob = audio.hasRecording ? await audio.exportProcessedWav() : null
    const [screenshotDataUrl, processedAudioDataUrl] = await Promise.all([
      blobToDataUrl(screenshotBlob),
      processedAudioBlob ? blobToDataUrl(processedAudioBlob) : Promise.resolve(null),
    ])
    const response = await fetch(`${API_BASE}/api/save`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        screenshot_data_url: screenshotDataUrl,
        processed_audio_data_url: processedAudioDataUrl,
        final_motion: finalMotion,
      }),
    })
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}))
      throw new Error(detail.detail || `本地保存失败（HTTP ${response.status}）`)
    }
    savedWork = await response.json()
    if (savedWork.id) showToast(`作品已保存 · ${savedWork.id}`)
  } catch (error) {
    showToast(error instanceof Error ? error.message : '本地保存失败')
  }
}

async function shareWork() {
  const shareButton = document.querySelector('#share-button')
  if (shareButton) shareButton.disabled = true
  showToast('正在生成')

  try {
    const [audioBlob, coverBlob] = await Promise.all([
      audio.exportProcessedWav(),
      sculpture.captureBlob(),
    ])

    const safeName = `SoundClay-${Date.now()}`
    const audioFile = new File([audioBlob], `${safeName}.wav`, { type: 'audio/wav' })
    const coverFile = new File([coverBlob], `${safeName}.png`, { type: 'image/png' })
    const shareData = {
      title: resultName(),
      text: '我把一段声音，塑造成了另一种形状。',
      files: [audioFile, coverFile],
    }

    if (navigator.share && navigator.canShare?.(shareData)) {
      await navigator.share(shareData)
      showToast('分享完成')
    } else {
      downloadBlob(audioBlob, audioFile.name)
      window.setTimeout(() => downloadBlob(coverBlob, coverFile.name), 180)
      showToast('作品已下载')
    }
  } catch (error) {
    if (error?.name !== 'AbortError') showError(error instanceof Error ? error.message : '作品生成失败。')
  } finally {
    if (shareButton) shareButton.disabled = false
  }
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1500)
}

function restart() {
  clearTimeout(recordingTimeout)
  clearInterval(recordingTimer)
  clearTimeout(completionTimer)
  audio.reset()
  nodes = []
  savedWork = null
  finalMotion = {}
  materialRequest = Promise.resolve(null)
  resetRingEventState(null)
  mode = 0.5
  localSizeDemo = 0
  sculpture.reset()
  sculpture.setMode(mode)
  sculpture.setProgress(0)
  setState('idle')
  void fetch(`${API_BASE}/api/reset`, { method: 'POST' }).catch(() => {})
}

function showError(message) {
  copy.innerHTML = `<h1 class="title">暂时无法继续</h1>`
  controls.innerHTML = `
    <p class="error-message">${message}</p>
    <button class="primary-button" id="error-back">返回</button>
  `
  document.querySelector('#error-back').addEventListener('click', restart)
}

function normalizedPointer(event) {
  const rect = interactionLayer.getBoundingClientRect()
  return {
    x: Math.min(1, Math.max(-1, ((event.clientX - rect.left) / rect.width) * 2 - 1)),
    y: Math.min(1, Math.max(-1, ((event.clientY - rect.top) / rect.height) * 2 - 1)),
  }
}

interactionLayer.addEventListener('pointerdown', (event) => {
  if (!['mode', 'sculpt'].includes(state) || (state === 'sculpt' && ringFrozen)) return
  interactionLayer.setPointerCapture(event.pointerId)
  const point = normalizedPointer(event)
  const now = performance.now()
  pointer = {
    id: event.pointerId,
    startX: event.clientX,
    startY: event.clientY,
    lastX: event.clientX,
    lastY: event.clientY,
    startedAt: now,
    lastAt: now,
    moved: false,
    peakSpeed: 0,
    totalDx: 0,
    totalDy: 0,
    point,
    sizeMode: event.shiftKey,
  }

  if (state === 'mode') {
    // 屏幕左侧 = 舒缓，屏幕右侧 = 释放。
    const sliderPosition = (point.x + 1) / 2
    setMode(1 - sliderPosition)
    return
  }

})

interactionLayer.addEventListener('pointermove', (event) => {
  if (!pointer || pointer.id !== event.pointerId) return
  if (state === 'sculpt' && ringFrozen) return
  const point = normalizedPointer(event)
  const now = performance.now()
  const dt = Math.max(1, now - pointer.lastAt)
  const dx = event.clientX - pointer.lastX
  const dy = event.clientY - pointer.lastY
  const speed = Math.hypot(dx, dy) / dt
  pointer.peakSpeed = Math.max(pointer.peakSpeed, speed)
  pointer.totalDx = event.clientX - pointer.startX
  pointer.totalDy = event.clientY - pointer.startY
  pointer.lastX = event.clientX
  pointer.lastY = event.clientY
  pointer.lastAt = now

  const movedDistance = Math.hypot(pointer.totalDx, pointer.totalDy)
  if (movedDistance > 7) pointer.moved = true

  if (state === 'mode') {
    // 选择模式只旋转完整万花筒，不触发横向条带。
    const sliderPosition = (point.x + 1) / 2
    setMode(1 - sliderPosition)
    return
  }

  if (state === 'sculpt') {
    if (pointer.sizeMode || event.shiftKey) {
      applySizeControl(point.x, { syncAbleton: true })
    } else {
      sculpture.setInteraction(point.x, point.y)
      finalMotion.twist = point.x
      syncAbletonMotion('twist', point.x, 35)
      audio.setMorph({ space: (point.x + 1) / 2 })
    }
  }
})

function finishPointer(event) {
  if (!pointer || pointer.id !== event.pointerId) return

  if (state === 'mode') {
    // 页面级拖动和原生 range 滑块使用同一条提交路径。
    setMode(mode >= 0.5 ? 1 : 0)
    enterSculpt()
    pointer = null
    return
  }

  if (state === 'sculpt') {
    sculpture.setTwist(0)
    finalMotion.twist = 0
    if (!pointer.sizeMode) syncAbletonMotion('twist', 0)
    const duration = Math.max(1, performance.now() - pointer.startedAt)
    const distance = Math.hypot(pointer.totalDx, pointer.totalDy)
    const isFastSwipe = pointer.peakSpeed > 1.15 && distance > 64

    if (isFastSwipe && !pointer.sizeMode) {
      triggerBurst(Math.min(1.35, 0.55 + pointer.peakSpeed * 0.42), { syncAbleton: true })
    } else if (!pointer.moved) {
      addNode()
    }
  }

  pointer = null
}

interactionLayer.addEventListener('pointerup', finishPointer)
interactionLayer.addEventListener('pointercancel', finishPointer)

function applyKeyboardTwist() {
  if (state !== 'sculpt' || ringFrozen) return
  const left = heldTwistKeys.has('ArrowLeft') || heldTwistKeys.has('KeyA')
  const right = heldTwistKeys.has('ArrowRight') || heldTwistKeys.has('KeyD')
  const twist = left === right ? 0 : left ? -0.88 : 0.88
  sculpture.setTwist(twist, true)
  finalMotion.twist = twist
  syncAbletonMotion('twist', twist, 35)
}

window.addEventListener('keydown', (event) => {
  if (event.code === 'Space' && ['sculpt', 'result'].includes(state)) {
    event.preventDefault()
    togglePlayback()
    return
  }

  if (['ArrowLeft', 'ArrowRight', 'KeyA', 'KeyD'].includes(event.code) && state === 'sculpt') {
    event.preventDefault()
    heldTwistKeys.add(event.code)
    applyKeyboardTwist()
    return
  }

  if (!event.repeat && event.code === 'KeyB' && state === 'sculpt') {
    event.preventDefault()
    triggerBurst(1, { syncAbleton: true })
    return
  }

  if (!event.repeat && ['KeyP', 'KeyZ'].includes(event.code) && state === 'sculpt') {
    event.preventDefault()
    applySizeControl(-1, { notify: true, syncAbleton: true })
    return
  }

  if (!event.repeat && ['KeyL', 'KeyX'].includes(event.code) && state === 'sculpt') {
    event.preventDefault()
    applySizeControl(1, { notify: true, syncAbleton: true })
    return
  }

  if (!event.repeat && event.code === 'KeyF' && state === 'sculpt') {
    event.preventDefault()
    completeCreation({ message: '作品已凝固' })
    return
  }

  if (event.key.toLowerCase() === 'r' && state === 'sculpt') {
    nodes.pop()
    showToast('已撤回')
    render()
  }
})

window.addEventListener('keyup', (event) => {
  if (!['ArrowLeft', 'ArrowRight', 'KeyA', 'KeyD'].includes(event.code)) return
  heldTwistKeys.delete(event.code)
  applyKeyboardTwist()
})

interactionLayer.addEventListener('dblclick', (event) => {
  if (state !== 'sculpt' || ringFrozen) return
  event.preventDefault()
  completeCreation({ message: '作品已凝固' })
})

window.addEventListener('soundclay:gesture', (event) => {
  const detail = event.detail ?? {}
  const strength = Math.min(1.5, Math.max(0, Number(detail.strength ?? 1)))

  if (state === 'mode' && typeof detail.x === 'number') {
    const sliderPosition = (Math.min(1, Math.max(-1, detail.x)) + 1) / 2
    setMode(1 - sliderPosition)
    return
  }

  if (state !== 'sculpt') return

  switch (detail.type) {
    case 'rotate': {
      const x = Math.min(1, Math.max(-1, Number(detail.x ?? detail.value ?? 0)))
      sculpture.setTwist(x)
      finalMotion.twist = x
      syncAbletonMotion('twist', x, 35)
      if ([detail.pitch, detail.yaw, detail.roll].some((value) => Number.isFinite(Number(value)))) {
        sculpture.setOrientation(detail)
      }
      audio.setMorph({ space: (x + 1) / 2 })
      break
    }
    case 'swipe':
    case 'burst':
      triggerBurst(strength, { syncAbleton: true })
      break
    case 'press':
    case 'push': {
      const direction = String(detail.direction ?? detail.motion ?? '').toLowerCase()
      const signedDepth = Number(detail.depth ?? detail.value ?? strength)
      if (direction === 'backward' || direction === 'back' || direction === 'pull' || signedDepth < 0) {
        triggerPull(Math.abs(signedDepth) || strength)
      } else {
        triggerPush(Math.abs(signedDepth) || strength)
      }
      break
    }
    case 'pull':
      triggerPull(strength)
      break
    case 'finger':
    case 'finger_move':
    case 'size':
    case 'scale':
    case 'depth': {
      const sizeValue = Math.min(1, Math.max(-1, Number(detail.value ?? detail.x ?? detail.depth ?? 0)))
      applySizeControl(sizeValue, { syncAbleton: true })
      break
    }
    case 'tap':
      if (detail.count >= 2 || detail.double === true) completeCreation({ message: '作品已凝固' })
      break
    case 'double_tap':
    case 'doubletap':
    case 'double_click':
    case 'freeze':
      completeCreation({ message: '作品已凝固' })
      break
    case 'lift':
    case 'hold':
      break
    default:
      break
  }
})

setState('idle')
connectRingSocket()

window.addEventListener('beforeunload', () => {
  clearTimeout(reconnectTimer)
  clearTimeout(completionTimer)
  socket?.close()
})
