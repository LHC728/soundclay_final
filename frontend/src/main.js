import './style.css'
import { createSculpture } from './sculpture.js'
import { SoundClayAudio } from './audio.js'

const app = document.querySelector('#app')

app.innerHTML = `
  <main class="soundclay" data-state="idle">
    <p class="brand">SoundClay</p>

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
let recordingStartedAt = 0
let recordingTimer = 0
let recordingTimeout = 0
let nodes = []
let toastTimer = 0
let pointer = null
let holdTimer = 0
let isHolding = false
let hintTimer = 0

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
  root.dataset.state = state
  sculpture.setState(state)
  setActiveDot()
  render()
}

function modeName() {
  if (mode < 0.38) return '释放'
  if (mode > 0.62) return '舒缓'
  return '混合'
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
    controls.innerHTML = `
      <button class="icon-button record-button" id="stop-button" aria-label="结束录音" data-recording="true">
        <span class="record-dot"></span>
      </button>
      <div class="tiny-label" id="record-time">00:00</div>
    `
    document.querySelector('#stop-button').addEventListener('click', stopRecording)
    updateRecordingTime()
    recordingTimer = window.setInterval(updateRecordingTime, 250)
    return
  }

  if (state === 'mode') {
    copy.innerHTML = `
      <h1 class="title">选择声音的方向</h1>
      <p class="subtitle">拖动粒子或滑轨，实时试听。</p>
    `
    controls.innerHTML = `
      <div class="mode-control">
        <div class="mode-labels"><span>释放</span><span>${modeName()}</span><span>舒缓</span></div>
        <input class="mode-slider" id="mode-slider" type="range" min="0" max="100" value="${Math.round(mode * 100)}" aria-label="选择释放或舒缓程度" />
      </div>
      <button class="primary-button" id="enter-sculpt">进入塑形</button>
    `

    const slider = document.querySelector('#mode-slider')
    slider.addEventListener('input', () => setMode(Number(slider.value) / 100))
    document.querySelector('#enter-sculpt').addEventListener('click', enterSculpt)
    return
  }

  if (state === 'sculpt') {
    copy.innerHTML = `
      <h1 class="title">用动作塑造它</h1>
      <p class="subtitle">左右展开 · 上下改变力量 · 轻点留下节点</p>
    `
    controls.innerHTML = `
      <div class="sculpt-hud">
        <div class="timeline" aria-label="作品播放进度">
          <div class="timeline-track"><div class="timeline-progress"></div></div>
          ${nodes.map((node) => `<span class="timeline-node" style="left:${node.progress * 100}%"></span>`).join('')}
        </div>
        <div class="hint" id="sculpt-hint">移动 · 旋转 · 点击</div>
        <div class="sculpt-actions">
          <button class="finish-button" id="finish-button">完成</button>
        </div>
      </div>
    `
    document.querySelector('#finish-button').addEventListener('click', finishCreation)
    clearTimeout(hintTimer)
    hintTimer = window.setTimeout(() => {
      const hint = document.querySelector('#sculpt-hint')
      if (hint) hint.style.opacity = '0'
    }, 3400)
    return
  }

  copy.innerHTML = `
    <h1 class="result-title">${resultName()}</h1>
    <p class="subtitle">你的声音已经成形</p>
  `
  controls.innerHTML = `
    <div class="result-actions">
      <button class="icon-button" id="play-button" aria-label="播放或暂停">${audio.playing ? icons.pause : icons.play}</button>
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
    audio.playLoop()
    setState('mode')
  } catch (error) {
    showError(error instanceof Error ? error.message : '无法完成录音。')
  }
}

function setMode(value) {
  mode = Math.min(1, Math.max(0, value))
  sculpture.setMode(mode)
  audio.setMode(mode)

  const labels = document.querySelector('.mode-labels')
  if (labels) labels.children[1].textContent = modeName()
  const slider = document.querySelector('#mode-slider')
  if (slider && Number(slider.value) !== Math.round(mode * 100)) slider.value = String(Math.round(mode * 100))
}

function enterSculpt() {
  nodes = []
  audio.setMode(mode)
  audio.playLoop()
  setState('sculpt')
}

function showToast(message = '已留下') {
  clearTimeout(toastTimer)
  toast.textContent = message
  toast.classList.add('is-visible')
  toastTimer = window.setTimeout(() => toast.classList.remove('is-visible'), 900)
}

function addNode() {
  const progress = audio.duration > 0 && audio.context
    ? ((audio.context.currentTime - audio.startedAt) % audio.duration) / audio.duration
    : 0
  nodes.push({ progress, mode, space: audio.space, energy: audio.energy })
  sculpture.burst(0.74)
  showToast('已留下')
  render()
}

function finishCreation() {
  sculpture.burst(1)
  setState('result')
}

function togglePlayback() {
  audio.togglePlayback()
  render()
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
  audio.reset()
  nodes = []
  mode = 0.5
  sculpture.setMode(mode)
  sculpture.setInteraction(0, 0)
  sculpture.setProgress(0)
  setState('idle')
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
  if (!['mode', 'sculpt'].includes(state)) return
  interactionLayer.setPointerCapture(event.pointerId)
  const point = normalizedPointer(event)
  pointer = { id: event.pointerId, startX: event.clientX, startY: event.clientY, moved: false, point }

  if (state === 'mode') {
    setMode((point.x + 1) / 2)
    return
  }

  isHolding = false
  holdTimer = window.setTimeout(() => {
    isHolding = true
    sculpture.freeze(true)
    showToast('凝固')
  }, 520)
})

interactionLayer.addEventListener('pointermove', (event) => {
  if (!pointer || pointer.id !== event.pointerId) return
  const point = normalizedPointer(event)
  const movedDistance = Math.hypot(event.clientX - pointer.startX, event.clientY - pointer.startY)
  if (movedDistance > 7) pointer.moved = true

  if (state === 'mode') {
    setMode((point.x + 1) / 2)
    sculpture.setInteraction(point.x, point.y)
    return
  }

  if (state === 'sculpt') {
    sculpture.setInteraction(point.x, point.y)
    audio.setMorph({
      space: (point.x + 1) / 2,
      energy: (1 - point.y) / 2,
    })
  }
})

function finishPointer(event) {
  if (!pointer || pointer.id !== event.pointerId) return
  clearTimeout(holdTimer)

  if (state === 'sculpt') {
    if (isHolding) {
      sculpture.freeze(false)
      showToast('继续流动')
    } else if (!pointer.moved) {
      addNode()
    }
  }

  pointer = null
  isHolding = false
}

interactionLayer.addEventListener('pointerup', finishPointer)
interactionLayer.addEventListener('pointercancel', finishPointer)

window.addEventListener('keydown', (event) => {
  if (event.code === 'Space' && ['sculpt', 'result'].includes(state)) {
    event.preventDefault()
    togglePlayback()
  }

  if (event.key.toLowerCase() === 'r' && state === 'sculpt') {
    nodes.pop()
    sculpture.burst(0.35)
    showToast('已撤回')
    render()
  }
})

window.addEventListener('soundclay:gesture', (event) => {
  const detail = event.detail ?? {}
  const strength = Math.min(1.5, Math.max(0, Number(detail.strength ?? 1)))

  if (state === 'mode' && typeof detail.x === 'number') {
    setMode((Math.min(1, Math.max(-1, detail.x)) + 1) / 2)
    return
  }

  if (state !== 'sculpt') return

  switch (detail.type) {
    case 'rotate': {
      const x = Math.min(1, Math.max(-1, Number(detail.x ?? detail.value ?? 0)))
      sculpture.setInteraction(x, 0)
      audio.setMorph({ space: (x + 1) / 2 })
      break
    }
    case 'lift': {
      const energy = Math.min(1, Math.max(0, Number(detail.value ?? strength)))
      sculpture.setInteraction(0, 1 - energy * 2)
      audio.setMorph({ energy })
      break
    }
    case 'press': {
      const energy = 1 - Math.min(1, strength)
      sculpture.setInteraction(0, 1 - energy * 2)
      audio.setMorph({ energy })
      break
    }
    case 'tap':
      addNode()
      break
    case 'hold':
      sculpture.freeze(Boolean(detail.active ?? true))
      break
    case 'swipe':
      sculpture.burst(strength)
      break
    default:
      break
  }
})

setState('idle')
