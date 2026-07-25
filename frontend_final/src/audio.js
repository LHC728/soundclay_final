const clamp01 = (value) => Math.min(1, Math.max(0, value))
const lerp = (a, b, t) => a + (b - a) * t

function createDistortionCurve(amount = 0) {
  const samples = 2048
  const curve = new Float32Array(samples)
  const k = Math.max(0, amount)

  for (let i = 0; i < samples; i += 1) {
    const x = (i * 2) / samples - 1
    curve[i] = ((3 + k) * x * 20 * (Math.PI / 180)) / (Math.PI + k * Math.abs(x))
  }

  return curve
}

function createImpulse(context, duration = 2.2, decay = 2.8) {
  const length = Math.max(1, Math.floor(context.sampleRate * duration))
  const impulse = context.createBuffer(2, length, context.sampleRate)

  for (let channel = 0; channel < 2; channel += 1) {
    const data = impulse.getChannelData(channel)
    for (let i = 0; i < length; i += 1) {
      const envelope = Math.pow(1 - i / length, decay)
      data[i] = (Math.random() * 2 - 1) * envelope
    }
  }

  return impulse
}

function mergeBuffers(chunks, mimeType) {
  return new Blob(chunks, { type: mimeType || 'audio/webm' })
}

function writeAscii(view, offset, text) {
  for (let i = 0; i < text.length; i += 1) {
    view.setUint8(offset + i, text.charCodeAt(i))
  }
}

function audioBufferToWav(buffer) {
  const channels = Math.min(2, buffer.numberOfChannels)
  const sampleRate = buffer.sampleRate
  const frames = buffer.length
  const bytesPerSample = 2
  const blockAlign = channels * bytesPerSample
  const output = new ArrayBuffer(44 + frames * blockAlign)
  const view = new DataView(output)

  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + frames * blockAlign, true)
  writeAscii(view, 8, 'WAVE')
  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, channels, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * blockAlign, true)
  view.setUint16(32, blockAlign, true)
  view.setUint16(34, 16, true)
  writeAscii(view, 36, 'data')
  view.setUint32(40, frames * blockAlign, true)

  const source = []
  for (let channel = 0; channel < channels; channel += 1) {
    source.push(buffer.getChannelData(channel))
  }

  let offset = 44
  for (let frame = 0; frame < frames; frame += 1) {
    for (let channel = 0; channel < channels; channel += 1) {
      const sample = Math.max(-1, Math.min(1, source[channel][frame]))
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true)
      offset += 2
    }
  }

  return new Blob([output], { type: 'audio/wav' })
}

export class SoundClayAudio {
  constructor({ onLevel = () => {}, onProgress = () => {} } = {}) {
    this.onLevel = onLevel
    this.onProgress = onProgress
    this.context = null
    this.stream = null
    this.recorder = null
    this.recordingChunks = []
    this.recordingMimeType = ''
    this.buffer = null
    this.source = null
    this.graph = null
    this.output = null
    this.monitorFrame = 0
    this.startedAt = 0
    this.startOffset = 0
    this.playing = false
    this.loop = true
    this.mode = 0.5
    this.space = 0.5
    this.energy = 0.5
  }

  get hasRecording() {
    return Boolean(this.buffer)
  }

  get duration() {
    return this.buffer?.duration ?? 0
  }

  async ensureContext() {
    if (!this.context) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext
      if (!AudioContextClass) throw new Error('当前浏览器不支持 Web Audio。')
      this.context = new AudioContextClass()
    }

    if (this.context.state === 'suspended') await this.context.resume()
    return this.context
  }

  async startRecording() {
    const context = await this.ensureContext()
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('当前环境无法访问麦克风。请使用 localhost 或 HTTPS。')
    }

    this.stopPlayback()
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: false,
      },
    })

    const preferredTypes = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
    ]
    this.recordingMimeType = preferredTypes.find((type) => MediaRecorder.isTypeSupported(type)) || ''
    this.recorder = this.recordingMimeType
      ? new MediaRecorder(this.stream, { mimeType: this.recordingMimeType })
      : new MediaRecorder(this.stream)

    this.recordingChunks = []
    this.recorder.addEventListener('dataavailable', (event) => {
      if (event.data.size > 0) this.recordingChunks.push(event.data)
    })

    const micSource = context.createMediaStreamSource(this.stream)
    const analyser = context.createAnalyser()
    analyser.fftSize = 512
    analyser.smoothingTimeConstant = 0.72
    micSource.connect(analyser)
    this.startMonitor(analyser, false)
    this.recorder.start(120)
  }

  async stopRecording() {
    if (!this.recorder || this.recorder.state === 'inactive') {
      throw new Error('当前没有正在进行的录音。')
    }

    const blob = await new Promise((resolve, reject) => {
      const recorder = this.recorder
      recorder.addEventListener(
        'stop',
        () => resolve(mergeBuffers(this.recordingChunks, recorder.mimeType || this.recordingMimeType)),
        { once: true },
      )
      recorder.addEventListener('error', () => reject(new Error('录音失败。')), { once: true })
      recorder.stop()
    })

    this.stream?.getTracks().forEach((track) => track.stop())
    this.stream = null
    this.recorder = null
    cancelAnimationFrame(this.monitorFrame)

    const context = await this.ensureContext()
    const data = await blob.arrayBuffer()
    this.buffer = await context.decodeAudioData(data.slice(0))
    this.onLevel(0)
    return blob
  }

  async loadUrl(url) {
    const context = await this.ensureContext()
    this.stopPlayback()
    const response = await fetch(url, { cache: 'no-store' })
    if (!response.ok) throw new Error(`无法读取戒指录音（HTTP ${response.status}）。`)
    const data = await response.arrayBuffer()
    this.buffer = await context.decodeAudioData(data.slice(0))
    this.startOffset = 0
    this.onLevel(0)
    this.onProgress(0)
    return this.buffer
  }

  buildGraph(context, destination) {
    const input = context.createGain()
    const filter = context.createBiquadFilter()
    const distortion = context.createWaveShaper()
    const dry = context.createGain()
    const convolver = context.createConvolver()
    const wet = context.createGain()
    const delay = context.createDelay(1.5)
    const feedback = context.createGain()
    const delayWet = context.createGain()
    const panner = context.createStereoPanner ? context.createStereoPanner() : context.createGain()
    const master = context.createGain()
    const analyser = context.createAnalyser()

    filter.type = 'lowpass'
    convolver.buffer = createImpulse(context)
    distortion.oversample = '2x'
    analyser.fftSize = 512
    analyser.smoothingTimeConstant = 0.78

    input.connect(filter)
    filter.connect(distortion)
    distortion.connect(dry)
    dry.connect(panner)

    distortion.connect(convolver)
    convolver.connect(wet)
    wet.connect(panner)

    distortion.connect(delay)
    delay.connect(feedback)
    feedback.connect(delay)
    delay.connect(delayWet)
    delayWet.connect(panner)

    panner.connect(master)
    master.connect(analyser)
    analyser.connect(destination)

    return {
      input,
      filter,
      distortion,
      dry,
      wet,
      delay,
      feedback,
      delayWet,
      panner,
      master,
      analyser,
    }
  }

  applyParameters(graph, context = this.context) {
    const mode = clamp01(this.mode)
    const space = clamp01(this.space)
    const energy = clamp01(this.energy)
    const now = context.currentTime
    const set = (param, value, smoothing = 0.04) => {
      if (typeof param.cancelScheduledValues === 'function') param.cancelScheduledValues(now)
      param.setTargetAtTime(value, now, smoothing)
    }

    const cutoff = lerp(1800, 14500, energy) * lerp(1.0, 0.72, mode)
    graph.filter.frequency.setValueAtTime(Math.max(500, cutoff), now)
    graph.filter.Q.setValueAtTime(lerp(1.4, 0.45, mode), now)
    graph.distortion.curve = createDistortionCurve(lerp(76, 2, mode) * (0.35 + energy * 0.65))

    set(graph.dry.gain, lerp(0.82, 0.70, space))
    set(graph.wet.gain, lerp(0.08, 0.54, space) * lerp(0.72, 1.24, mode))
    set(graph.delay.delayTime, lerp(0.035, 0.42, space))
    set(graph.feedback.gain, lerp(0.07, 0.48, space) * lerp(1.0, 0.72, mode))
    set(graph.delayWet.gain, lerp(0.02, 0.28, space))
    set(graph.master.gain, lerp(0.64, 0.94, energy))

    if ('pan' in graph.panner) set(graph.panner.pan, (space - 0.5) * 0.28)
    if (this.source) this.source.playbackRate.setTargetAtTime(lerp(1.04, 0.90, mode) + (energy - 0.5) * 0.08, now, 0.05)
  }

  setMode(value) {
    this.mode = clamp01(Number(value) || 0)
    if (this.graph) this.applyParameters(this.graph)
  }

  setMorph({ space = this.space, energy = this.energy } = {}) {
    this.space = clamp01(Number(space) || 0)
    this.energy = clamp01(Number(energy) || 0)
    if (this.graph) this.applyParameters(this.graph)
  }

  playLoop({ muted = false } = {}) {
    if (!this.buffer) return false
    if (this.playing) return true

    const context = this.context
    this.output = context.createGain()
    this.output.gain.value = muted ? 0 : 1
    this.output.connect(context.destination)
    this.graph = this.buildGraph(context, this.output)
    this.source = context.createBufferSource()
    this.source.buffer = this.buffer
    this.source.loop = this.loop
    this.source.connect(this.graph.input)
    this.applyParameters(this.graph)

    const offset = this.duration > 0 ? this.startOffset % this.duration : 0
    this.startedAt = context.currentTime - offset
    this.source.start(0, offset)
    this.source.addEventListener('ended', () => {
      if (!this.loop) this.stopPlayback()
    })
    this.playing = true
    this.startMonitor(this.graph.analyser, true)
    return true
  }

  stopPlayback() {
    if (this.source) {
      try {
        if (this.playing && this.duration > 0) {
          this.startOffset = (this.context.currentTime - this.startedAt) % this.duration
        }
        this.source.stop()
      } catch {
        // Source may already have ended.
      }
      this.source.disconnect()
    }

    this.source = null
    this.graph = null
    this.output?.disconnect()
    this.output = null
    this.playing = false
    cancelAnimationFrame(this.monitorFrame)
    this.onLevel(0)
  }

  togglePlayback() {
    if (this.playing) {
      this.stopPlayback()
      return false
    }
    this.playLoop()
    return true
  }

  startMonitor(analyser, includeProgress) {
    cancelAnimationFrame(this.monitorFrame)
    const data = new Uint8Array(analyser.fftSize)

    const tick = () => {
      analyser.getByteTimeDomainData(data)
      let sum = 0
      for (let i = 0; i < data.length; i += 1) {
        const value = (data[i] - 128) / 128
        sum += value * value
      }
      const rms = Math.sqrt(sum / data.length)
      this.onLevel(clamp01(rms * 4.4))

      if (includeProgress && this.playing && this.duration > 0) {
        const elapsed = this.context.currentTime - this.startedAt
        this.onProgress((elapsed % this.duration) / this.duration)
      }
      this.monitorFrame = requestAnimationFrame(tick)
    }

    this.monitorFrame = requestAnimationFrame(tick)
  }

  async exportProcessedWav() {
    if (!this.buffer) throw new Error('没有可以导出的录音。')

    const sourceBuffer = this.buffer
    const tailSeconds = 2.4
    const outputLength = Math.ceil((sourceBuffer.duration + tailSeconds) * sourceBuffer.sampleRate)
    const offline = new OfflineAudioContext(2, outputLength, sourceBuffer.sampleRate)
    const graph = this.buildGraph(offline, offline.destination)
    const source = offline.createBufferSource()
    source.buffer = sourceBuffer
    source.connect(graph.input)

    const previousSource = this.source
    this.source = source
    this.applyParameters(graph, offline)
    this.source = previousSource
    source.start(0)

    const rendered = await offline.startRendering()
    return audioBufferToWav(rendered)
  }

  exportOriginalWav() {
    if (!this.buffer) throw new Error('没有可供识别的录音。')
    return audioBufferToWav(this.buffer)
  }

  reset() {
    this.stopPlayback()
    this.buffer = null
    this.startOffset = 0
    this.mode = 0.5
    this.space = 0.5
    this.energy = 0.5
    this.onProgress(0)
    this.onLevel(0)
  }
}
