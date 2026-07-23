import './style.css'

import {
  STATE_ORDER,
  getCurrentState,
  goToState,
  nextState,
  previousState,
  resetState,
} from './state.js'

import { initSculpture } from './sculpture.js'

const app = document.querySelector('#app')

if (!app) {
  throw new Error('未找到 #app 根节点')
}

let selectedEmotion = 'anger'
let selectedMode = 'express'
let destroySculpture = null

const stateMeta = {
  ready: {
    code: 'S0 / READY',
    title: '准备开始',
    description: '说出感受，让声音成为一种可以触摸和雕刻的材料。',
  },
  recording: {
    code: 'S1 / RECORDING',
    title: '声音输入',
    description: '长按戒指，说出此刻最想表达的一句话。',
  },
  understanding: {
    code: 'S2 / INTERPRETING',
    title: '语义理解',
    description: 'AI 正在理解你主动表达的内容，而不是读取你的内心。',
  },
  review: {
    code: 'S3 / REVIEW',
    title: '情绪确认',
    description: 'AI 只建立作品起点，最终结果由你确认。',
  },
  choice: {
    code: 'S4 / DIRECTION',
    title: '方向选择',
    description: '同一种情绪，可以被放大表达，也可以被温柔安放。',
  },
  materializing: {
    code: 'S5 / MATERIALIZING',
    title: '声音物质化',
    description: '系统正在把情绪、声音和视觉参数组合成创作配方。',
  },
  sculpting: {
    code: 'S6 / SCULPTING',
    title: '具身雕刻',
    description: '转腕改变形态和声音，快挥释放能量，双击完成凝固。',
  },
  saved: {
    code: 'S7 / ARCHIVED',
    title: '作品保存',
    description: '声音、图像和动作参数已经形成一份个人声音肖像。',
  },
}

const emotionNames = {
  joy: '开心 / 兴奋',
  anger: '愤怒 / 烦躁',
  sadness: '难过 / 低落',
  anxiety: '紧张 / 不安',
  neutral_mixed: '中性 / 混合',
}

function emotionName(emotion) {
  return emotionNames[emotion] ?? emotionNames.neutral_mixed
}

function modeName(mode) {
  return mode === 'express' ? '张扬个性' : '安慰舒缓'
}

function createProgress(currentState) {
  const currentIndex = STATE_ORDER.indexOf(currentState)

  return STATE_ORDER.map((state, index) => {
    let status = ''

    if (index < currentIndex) {
      status = 'is-complete'
    } else if (index === currentIndex) {
      status = 'is-active'
    }

    return `
      <div class="progress-node ${status}">
        <span class="progress-index">
          ${String(index + 1).padStart(2, '0')}
        </span>

        <span class="progress-line"></span>
      </div>
    `
  }).join('')
}

function renderReady() {
  return `
    <div class="screen-grid hero-screen">
      <section class="editorial-panel hero-copy">
        <div class="bracket-label">
          [ EMOTION MATERIAL SYSTEM ]
        </div>

        <h1 class="display-title">
          把噪声<br>
          塑造成形
        </h1>

        <p class="lede">
          SoundClay 将你主动说出的感受转化为声音和三维材料。
          AI 建立起点，你决定方向，身体完成最终雕刻。
        </p>

        <div class="action-row">
          <button
            class="primary-button"
            data-action="next"
            type="button"
          >
            开始体验
            <span>↗</span>
          </button>

          <span class="action-code">
            SESSION / 001
          </span>
        </div>

        <div class="micro-note">
          <span>PRIVACY</span>
          录音仅用于本次作品生成，不会自动公开完整转写。
        </div>
      </section>

      <section class="visual-panel">
        <div class="visual-meta visual-meta-top">
          <span>OBJECT / LIVE</span>
          <span>MODE / EXPRESS</span>
        </div>

        <div
          id="sculpture-stage"
          class="hero-sculpture"
        ></div>

        <div class="visual-caption">
          <span>声音不是播放内容</span>
          <strong>它是一种材料</strong>
        </div>

        <div class="coordinate coordinate-left">
          X / 12.04
        </div>

        <div class="coordinate coordinate-right">
          Y / 08.61
        </div>
      </section>
    </div>
  `
}

function renderRecording() {
  const waveform = Array.from({ length: 42 }, (_, index) => {
    const height =
      18 + Math.abs(Math.sin(index * 0.72)) * 72

    return `
      <span
        class="wave-bar"
        style="
          --height:${height}px;
          --delay:${index * -32}ms;
        "
      ></span>
    `
  }).join('')

  return `
    <div class="screen-grid recording-screen">
      <section class="recording-console">
        <div class="console-head">
          <span>[ AUDIO INPUT ]</span>

          <span class="live-status">
            <i></i>
            LIVE
          </span>
        </div>

        <div class="recording-orb">
          <div class="recording-orb-inner"></div>
          <div class="recording-orbit orbit-one"></div>
          <div class="recording-orbit orbit-two"></div>
        </div>

        <div class="waveframe">
          <div class="wave-bars">
            ${waveform}
          </div>

          <div class="wave-baseline"></div>
        </div>
      </section>

      <section class="editorial-panel recording-copy">
        <div class="bracket-label">
          [ SPEAK NOW ]
        </div>

        <h1 class="section-title">
          说出此刻<br>
          最真实的一句话
        </h1>

        <p class="lede compact">
          长按戒指 3–8 秒，说完后松开。
          页面将在音频传输完成后进入语义理解。
        </p>

        <blockquote class="voice-quote">
          “今天事情一直出错，我真的很烦。”
        </blockquote>

        <div class="recording-metrics">
          <div class="metric-card">
            <span>FORMAT</span>
            <strong>16 kHz</strong>
          </div>

          <div class="metric-card">
            <span>CHANNEL</span>
            <strong>MONO</strong>
          </div>

          <div class="metric-card">
            <span>STATE</span>
            <strong>READY</strong>
          </div>
        </div>

        <button
          class="primary-button"
          data-action="next"
          type="button"
        >
          模拟录音完成
          <span>↗</span>
        </button>
      </section>
    </div>
  `
}

function renderUnderstanding() {
  const rays = Array.from({ length: 28 }, (_, index) => {
    return `
      <span
        class="network-ray"
        style="
          --angle:${index * 12.86}deg;
          --length:${110 + (index % 6) * 26}px;
        "
      >
        <i></i>
      </span>
    `
  }).join('')

  return `
    <div class="screen-grid understanding-screen">
      <section class="network-stage">
        <div class="network-label">
          SEMANTIC FIELD / ACTIVE
        </div>

        <div class="network">
          <div class="network-core">AI</div>
          ${rays}
        </div>

        <div class="network-readout">
          <span>TRANSCRIPT SIGNAL</span>
          <strong>86.42%</strong>
        </div>
      </section>

      <section class="editorial-panel analysis-copy">
        <div class="bracket-label">
          [ INTERPRETATION PIPELINE ]
        </div>

        <h1 class="section-title">
          理解表达<br>
          而不是猜测内心
        </h1>

        <p class="lede compact">
          系统只分析用户主动说出的语义。
          情绪结果必须由用户确认或修改。
        </p>

        <div class="analysis-steps">
          <div class="analysis-step is-done">
            <span>01</span>

            <div>
              <strong>语音转文字</strong>
              <small>TRANSCRIPT READY</small>
            </div>
          </div>

          <div class="analysis-step is-active">
            <span>02</span>

            <div>
              <strong>语义情绪分类</strong>
              <small>PROCESSING</small>
            </div>
          </div>

          <div class="analysis-step">
            <span>03</span>

            <div>
              <strong>创作配方准备</strong>
              <small>STANDBY</small>
            </div>
          </div>
        </div>

        <button
          class="primary-button"
          data-action="next"
          type="button"
        >
          显示分析结果
          <span>↗</span>
        </button>
      </section>
    </div>
  `
}

function renderReview() {
  return `
    <div class="screen-grid review-screen">
      <section class="transcript-panel">
        <div class="panel-heading">
          <span>[ TRANSCRIPT ]</span>
          <span>00:04.82</span>
        </div>

        <div class="transcript-text">
          今天事情<br>
          一直出错，<br>
          我真的很烦。
        </div>

        <div class="transcript-footer">
          <span>LANGUAGE / ZH-CN</span>
          <span>SOURCE / RING AUDIO</span>
        </div>
      </section>

      <section class="review-panel">
        <div class="bracket-label">
          [ AI SUGGESTION ]
        </div>

        <div class="suggestion-heading">
          <div>
            <span>检测结果</span>
            <h2>愤怒 / 烦躁</h2>
          </div>

          <div class="confidence-box">
            <small>CONFIDENCE</small>
            <strong>86%</strong>
          </div>
        </div>

        <p class="reason-text">
          文本中出现“很烦”“一直出错”等明确受阻表达，
          因此系统将作品起点判断为愤怒或烦躁。
        </p>

        <label
          class="field-label"
          for="emotion-select"
        >
          修改情绪标签
        </label>

        <div class="select-wrap">
          <select id="emotion-select">
            <option value="joy">
              开心 / 兴奋
            </option>

            <option
              value="anger"
              selected
            >
              愤怒 / 烦躁
            </option>

            <option value="sadness">
              难过 / 低落
            </option>

            <option value="anxiety">
              紧张 / 不安
            </option>

            <option value="neutral_mixed">
              中性 / 混合
            </option>
          </select>
        </div>

        <div class="review-actions">
          <button
            class="primary-button"
            data-action="confirm-emotion"
            type="button"
          >
            确认这份感受
            <span>↗</span>
          </button>

          <span class="review-notice">
            最终判断权属于用户
          </span>
        </div>
      </section>
    </div>
  `
}

function renderChoice() {
  return `
    <div class="choice-screen">
      <section class="choice-intro">
        <div class="bracket-label">
          [ SELECT DIRECTION ]
        </div>

        <h1 class="display-title choice-title">
          同一种情绪<br>
          两种作品方向
        </h1>

        <p class="lede">
          情绪决定作品从哪里开始，
          但只有你能决定它最终要去哪里。
        </p>
      </section>

      <section class="mode-grid">
        <button
          class="mode-card mode-card-express"
          data-mode="express"
          type="button"
        >
          <div class="mode-card-head">
            <span>01 / EXPRESS</span>
            <span class="mode-arrow">↗</span>
          </div>

          <div class="mode-graphic express-graphic">
            <span></span>
            <span></span>
            <span></span>
          </div>

          <div class="mode-card-content">
            <h2>张扬个性</h2>

            <p>
              我想先把它完整、直接而有力量地表达出来。
            </p>

            <div class="mode-tags">
              <span>高对比</span>
              <span>强脉冲</span>
              <span>爆散</span>
            </div>
          </div>
        </button>

        <button
          class="mode-card mode-card-soothe"
          data-mode="soothe"
          type="button"
        >
          <div class="mode-card-head">
            <span>02 / SOOTHE</span>
            <span class="mode-arrow">↗</span>
          </div>

          <div class="mode-graphic soothe-graphic">
            <span></span>
            <span></span>
            <span></span>
          </div>

          <div class="mode-card-content">
            <h2>安慰舒缓</h2>

            <p>
              我不否认它，但想让它逐渐稳定并被温柔安放。
            </p>

            <div class="mode-tags">
              <span>低通</span>
              <span>呼吸</span>
              <span>沉降</span>
            </div>
          </div>
        </button>
      </section>
    </div>
  `
}

function renderMaterializing() {
  const isSoothe = selectedMode === 'soothe'

  return `
    <div class="screen-grid materializing-screen">
      <section class="editorial-panel material-copy">
        <div class="bracket-label">
          ${
            isSoothe
              ? '[ SOOTHING MATERIAL ]'
              : '[ GENERATING MATERIAL ]'
          }
        </div>

        <h1 class="display-title">
          ${
            isSoothe
              ? `
                Breathe.<br>
                Settle.<br>
                Become.
              `
              : `
                Feeling<br>
                becomes<br>
                matter.
              `
          }
        </h1>

        <p class="lede compact">
          ${
            isSoothe
              ? `
                系统正在把情绪、声音与呼吸节奏组合成柔和的创作配方。
                万花筒粒子保持原有结构，界面进入安静、明亮的舒缓环境。
              `
              : `
                AI 正在根据情绪、模式和声音特征生成结构化创作配方。
                实时执行将在本地完成。
              `
          }
        </p>

        <div class="recipe-grid">
          <div>
            <span>EMOTION</span>
            <strong>
              ${emotionName(selectedEmotion)}
            </strong>
          </div>

          <div>
            <span>DIRECTION</span>
            <strong>
              ${modeName(selectedMode)}
            </strong>
          </div>

          <div>
            <span>ENGINE</span>
            <strong>LOCAL / REALTIME</strong>
          </div>

          <div>
            <span>RECIPE</span>
            <strong>READY</strong>
          </div>
        </div>

        <button
          class="primary-button"
          data-action="next"
          type="button"
        >
          ${
            isSoothe
              ? '进入舒缓雕刻'
              : '进入雕刻'
          }

          <span>↗</span>
        </button>
      </section>

      <section class="material-visual">
        <div class="visual-meta visual-meta-top">
          <span>
            ${
              isSoothe
                ? 'OBJECT / BREATHING'
                : 'OBJECT / FORMING'
            }
          </span>

          <span>SEED / 0317</span>
        </div>

        <div
          id="sculpture-stage"
          class="material-sculpture"
        ></div>

        <div class="material-progress">
          <span>STRUCTURE</span>

          <div>
            <i></i>
          </div>

          <strong>100%</strong>
        </div>
      </section>
    </div>
  `
}

function renderSculpting() {
  const isSoothe = selectedMode === 'soothe'

  return `
    <div class="sculpt-screen">
      <section class="sculpt-stage-panel">
        <div class="panel-heading">
          <span>[ LIVE SCULPTURE ]</span>
          <span>25 HZ / IMU</span>
        </div>

        <div
          id="sculpture-stage"
          class="sculpture-stage"
        ></div>

        <div class="sculpt-readout">
          <div>
            <span>ROTATION</span>
            <strong>+ 12.8°</strong>
          </div>

          <div>
            <span>ENERGY</span>
            <strong>
              ${isSoothe ? '0.31' : '0.74'}
            </strong>
          </div>

          <div>
            <span>FILTER</span>
            <strong>
              ${isSoothe ? '1.6 kHz' : '3.8 kHz'}
            </strong>
          </div>
        </div>
      </section>

      <section class="control-panel">
        <div class="bracket-label">
          [ PHYSICAL CONTROL ]
        </div>

        <h1 class="section-title">
          ${
            isSoothe
              ? `
                让动作<br>
                慢下来
              `
              : `
                用动作<br>
                塑造声音
              `
          }
        </h1>

        <p class="lede compact">
          ${
            isSoothe
              ? '用缓慢的动作梳理形态，让情绪逐渐沉降。'
              : '戒指不是遥控器，而是作品的一部分。'
          }
        </p>

        <div class="gesture-list">
          <div class="gesture-row">
            <span class="gesture-index">01</span>

            <div>
              <strong>转腕</strong>

              <small>
                ${
                  isSoothe
                    ? '缓慢调整形态与声音'
                    : '扭曲形态与滤波器'
                }
              </small>
            </div>

            <span class="gesture-symbol">↻</span>
          </div>

          <div class="gesture-row">
            <span class="gesture-index">02</span>

            <div>
              <strong>
                ${isSoothe ? '平缓挥动' : '快速挥动'}
              </strong>

              <small>
                ${
                  isSoothe
                    ? '让粒子逐渐扩散'
                    : '释放一次声音爆散'
                }
              </small>
            </div>

            <span class="gesture-symbol">
              ${isSoothe ? '≈' : '↯'}
            </span>
          </div>

          <div class="gesture-row">
            <span class="gesture-index">03</span>

            <div>
              <strong>双击</strong>
              <small>凝固并保存作品</small>
            </div>

            <span class="gesture-symbol">×2</span>
          </div>
        </div>

        <button
          class="primary-button danger-button"
          data-action="freeze"
          type="button"
        >
          模拟双击凝固
          <span>◆</span>
        </button>
      </section>
    </div>
  `
}

function renderSaved() {
  const isSoothe = selectedMode === 'soothe'

  const portraitTitle = isSoothe
    ? `
      Quiet<br>
      After<br>
      Noise
    `
    : `
      Noise<br>
      Without<br>
      Apology
    `

  const portraitDescription = isSoothe
    ? `
      一段烦躁的情绪被选择为舒缓安放，
      并通过呼吸、旋转与沉降形成这件声音作品。
    `
    : `
      一段烦躁的情绪被选择为张扬表达，
      并通过转腕、爆散与凝固形成这件声音作品。
    `

  return `
    <div class="screen-grid saved-screen">
      <section class="saved-visual">
        <div class="panel-heading">
          <span>[ VOICE PORTRAIT ]</span>
          <span>VP-20260723-001</span>
        </div>

        <div
          id="sculpture-stage"
          class="portrait-sculpture"
        ></div>

        <div class="portrait-stamp">
          ARCHIVED<br>
          2026 / 07 / 23
        </div>
      </section>

      <section class="saved-details">
        <div class="bracket-label">
          [ OUTPUT COMPLETE ]
        </div>

        <h1 class="portrait-title">
          ${portraitTitle}
        </h1>

        <p class="lede compact">
          ${portraitDescription}
        </p>

        <div class="portrait-properties">
          <div>
            <span>EMOTION</span>

            <strong>
              ${emotionName(selectedEmotion)}
            </strong>
          </div>

          <div>
            <span>DIRECTION</span>

            <strong>
              ${modeName(selectedMode)}
            </strong>
          </div>

          <div>
            <span>OBJECT ID</span>
            <strong>VP-20260723-001</strong>
          </div>
        </div>

        <div class="output-grid">
          <div class="output-item">
            <span>01</span>
            <strong>original.wav</strong>
            <small>原始声音</small>
          </div>

          <div class="output-item">
            <span>02</span>
            <strong>output.wav</strong>
            <small>输出声音</small>
          </div>

          <div class="output-item">
            <span>03</span>
            <strong>sculpture.png</strong>
            <small>作品图像</small>
          </div>

          <div class="output-item">
            <span>04</span>
            <strong>metadata.json</strong>
            <small>动作与配方</small>
          </div>
        </div>

        <div class="saved-actions">
          <button
            class="primary-button"
            data-action="download"
            type="button"
          >
            下载作品包
            <span>↓</span>
          </button>

          <button
            class="outline-button"
            data-action="reset"
            type="button"
          >
            重新开始
          </button>
        </div>
      </section>
    </div>
  `
}

function renderStateContent(state) {
  const renderers = {
    ready: renderReady,
    recording: renderRecording,
    understanding: renderUnderstanding,
    review: renderReview,
    choice: renderChoice,
    materializing: renderMaterializing,
    sculpting: renderSculpting,
    saved: renderSaved,
  }

  const renderer = renderers[state]

  if (!renderer) {
    return '<p>未知状态</p>'
  }

  return renderer()
}

function render() {
  if (destroySculpture) {
    destroySculpture()
    destroySculpture = null
  }

  const currentState = getCurrentState()
  const currentMeta = stateMeta[currentState]

  /*
   * 关键修改：
   * 把当前模式写入 html 标签。
   *
   * 张扬模式：
   * <html data-mode="express">
   *
   * 舒缓模式：
   * <html data-mode="soothe">
   *
   * style.css 可以通过这个属性切换整套配色。
   */
  document.documentElement.dataset.mode = selectedMode
  document.body.dataset.mode = selectedMode

  app.innerHTML = `
    <main
      class="
        app-shell
        mode-${selectedMode}
        state-${currentState}
      "
    >
      <header class="topbar">
        <a
          href="#"
          class="brand"
          data-action="reset"
        >
          <span class="brand-symbol">
            SC
          </span>

          <span class="brand-copy">
            <strong>SOUNDCLAY</strong>
            <small>EMOTION MATERIAL SYSTEM</small>
          </span>
        </a>

        <nav
          class="nav-links"
          aria-label="主导航"
        >
          <span>INPUT</span>
          <span>INTERPRET</span>
          <span>SHAPE</span>
          <span>ARCHIVE</span>
        </nav>

        <div class="system-status">
          <i></i>
          RING MOCK CONNECTED
        </div>
      </header>

      <div class="progress-rail">
        <div class="progress-state">
          <span>${currentMeta.code}</span>
          <strong>${currentMeta.title}</strong>
        </div>

        <div class="progress-track">
          ${createProgress(currentState)}
        </div>

        <div class="progress-count">
          ${String(
            STATE_ORDER.indexOf(currentState) + 1,
          ).padStart(2, '0')}
          /
          ${String(
            STATE_ORDER.length,
          ).padStart(2, '0')}
        </div>
      </div>

      <section class="experience">
        <div class="state-description">
          ${currentMeta.description}
        </div>

        <div class="screen-wrap">
          ${renderStateContent(currentState)}
        </div>

        ${
          currentState !== 'ready' &&
          currentState !== 'saved'
            ? `
              <button
                class="back-button"
                data-action="back"
                type="button"
              >
                <span>←</span>
                返回上一步
              </button>
            `
            : ''
        }
      </section>

      <footer class="site-footer">
        <span>SOUNDCLAY / 2026</span>

        <div>
          <span>YOUR FEELING.</span>
          <span>YOUR CHOICE.</span>
          <span>YOUR FORM.</span>
        </div>
      </footer>
    </main>
  `

  bindEvents()

  const statesWithSculpture = [
    'ready',
    'materializing',
    'sculpting',
    'saved',
  ]

  if (statesWithSculpture.includes(currentState)) {
    requestAnimationFrame(() => {
      const container = document.querySelector(
        '#sculpture-stage',
      )

      if (!container) {
        return
      }

      /*
       * 关键修改：
       * 两种模式固定使用同一套万花筒粒子。
       *
       * 不把 selectedMode 传入 sculpture.js，
       * 防止舒缓模式改变粒子配色、速度和结构。
       */
      destroySculpture = initSculpture(
        container,
        'express',
      )
    })
  }
}

function bindEvents() {
  document
    .querySelectorAll('[data-action="next"]')
    .forEach((button) => {
      button.addEventListener('click', () => {
        nextState()
        render()
      })
    })

  document
    .querySelectorAll('[data-action="back"]')
    .forEach((button) => {
      button.addEventListener('click', () => {
        previousState()
        render()
      })
    })

  document
    .querySelectorAll('[data-action="reset"]')
    .forEach((button) => {
      button.addEventListener('click', (event) => {
        event.preventDefault()

        resetState()

        selectedEmotion = 'anger'
        selectedMode = 'express'

        document.documentElement.dataset.mode =
          'express'

        document.body.dataset.mode =
          'express'

        render()
      })
    })

  const confirmEmotionButton =
    document.querySelector(
      '[data-action="confirm-emotion"]',
    )

  confirmEmotionButton?.addEventListener(
    'click',
    () => {
      const emotionSelect =
        document.querySelector(
          '#emotion-select',
        )

      selectedEmotion =
        emotionSelect?.value ?? 'anger'

      goToState('choice')
      render()
    },
  )

  document
    .querySelectorAll('[data-mode]')
    .forEach((button) => {
      button.addEventListener('click', () => {
        const mode = button.dataset.mode

        selectedMode =
          mode === 'soothe'
            ? 'soothe'
            : 'express'

        /*
         * 点击模式卡片时立即修改页面主题。
         */
        document.documentElement.dataset.mode =
          selectedMode

        document.body.dataset.mode =
          selectedMode

        goToState('materializing')
        render()
      })
    })

  const freezeButton =
    document.querySelector(
      '[data-action="freeze"]',
    )

  freezeButton?.addEventListener(
    'click',
    () => {
      goToState('saved')
      render()
    },
  )

  const downloadButton =
    document.querySelector(
      '[data-action="download"]',
    )

  downloadButton?.addEventListener(
    'click',
    () => {
      const metadata = {
        id: 'VP-20260723-001',
        emotion: selectedEmotion,
        emotionLabel:
          emotionName(selectedEmotion),
        mode: selectedMode,
        modeLabel:
          modeName(selectedMode),
        createdAt:
          new Date().toISOString(),
        files: [
          'original.wav',
          'output.wav',
          'sculpture.png',
          'metadata.json',
        ],
      }

      const blob = new Blob(
        [
          JSON.stringify(
            metadata,
            null,
            2,
          ),
        ],
        {
          type: 'application/json',
        },
      )

      const url =
        URL.createObjectURL(blob)

      const anchor =
        document.createElement('a')

      anchor.href = url
      anchor.download =
        'soundclay-metadata.json'

      document.body.appendChild(anchor)

      anchor.click()
      anchor.remove()

      URL.revokeObjectURL(url)
    },
  )
}

render()