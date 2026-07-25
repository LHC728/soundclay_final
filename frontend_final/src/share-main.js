import './share.css'
import { getPublicWork } from './api.js'
import { cardNebula, emotionTheme } from './emotion-card.js'

const app = document.querySelector('#app')
const workId = new URLSearchParams(window.location.search).get('id')

function renderMessage(title, detail) {
  app.replaceChildren()
  const panel = document.createElement('section')
  panel.className = 'share-message'
  panel.innerHTML = `<p class="share-message__brand">SOUNDCLAY</p><h1>${title}</h1><p>${detail}</p>`
  app.append(panel)
}

function renderWork(work) {
  const theme = emotionTheme(work.emotion)
  document.documentElement.style.setProperty('--theme-primary', theme.primary)
  document.documentElement.style.setProperty('--theme-accent', theme.accent)
  document.title = 'SoundClay'

  app.replaceChildren()
  const screening = document.createElement('article')
  screening.className = 'screening'
  screening.style.setProperty('--nebula-image', `url("${cardNebula(work.emotion)}")`)
  const canScreen = Boolean(work.videoUrl)
  screening.innerHTML = `
    <div class="screening__aura" aria-hidden="true"></div>
    <header class="screening__header">
      <p>SOUNDCLAY</p><span>VOICE ARCHIVE</span>
    </header>
    <section class="screening__portal" aria-label="声音档案放映">
      <img class="screening__cover" src="${work.coverUrl}" alt="这件作品最终形成的星云" />
      ${canScreen ? `<video class="screening__film" preload="metadata" playsinline poster="${work.coverUrl}" src="${work.videoUrl}"></video>` : ''}
      <div class="screening__shade" aria-hidden="true"></div>
      <button class="screening__trigger" type="button">
        <span class="screening__ring" aria-hidden="true"></span>
        <span class="screening__trigger-copy">${canScreen ? '触碰星云' : '聆听这件作品'}</span>
      </button>
      <p class="screening__status">${canScreen ? '一段由声音塑成的过程，等待被重新唤醒。' : '这份早期档案未保存过程影像。'}</p>
      <div class="screening__timeline" aria-hidden="true"><i></i></div>
    </section>
    <section class="screening__caption">
      <p class="screening__index">ARCHIVE ${new Date(work.saved_at).toLocaleDateString('zh-CN').replace(/\//g, '.')}</p>
      <h1></h1>
      <p class="screening__ending">星云已经抵达它最终的形状。</p>
    </section>
  `
  app.append(screening)

  screening.querySelector('.screening__caption h1').textContent = work.caption

  const trigger = screening.querySelector('.screening__trigger')
  const film = screening.querySelector('.screening__film')
  const timeline = screening.querySelector('.screening__timeline i')
  const ending = screening.querySelector('.screening__ending')
  let fallbackAudio = null
  let hasFilm = canScreen
  const filmHasAudio = work.process_video_has_audio !== false

  const enterFinalState = () => {
    screening.classList.remove('is-playing')
    screening.classList.add('is-finished')
    trigger.querySelector('.screening__trigger-copy').textContent = '再次进入'
    ending.textContent = '星云已经抵达它最终的形状。'
  }

  const play = async () => {
    screening.classList.remove('is-finished')
    screening.classList.add('is-playing')
    trigger.querySelector('.screening__trigger-copy').textContent = '正在放映'
    try {
      if (hasFilm && film) {
        film.currentTime = 0
        if (!filmHasAudio) {
          fallbackAudio ??= new Audio(work.audioUrl)
          fallbackAudio.currentTime = 0
          await Promise.all([fallbackAudio.play(), film.play()])
        } else {
          await film.play()
        }
      } else {
        fallbackAudio ??= new Audio(work.audioUrl)
        fallbackAudio.currentTime = 0
        await fallbackAudio.play()
        window.setTimeout(enterFinalState, 1400)
      }
    } catch {
      screening.classList.remove('is-playing')
      trigger.querySelector('.screening__trigger-copy').textContent = '轻触后重试'
    }
  }

  trigger.addEventListener('click', play)
  film?.addEventListener('timeupdate', () => {
    const ratio = film.duration ? film.currentTime / film.duration : 0
    timeline.style.transform = `scaleX(${Math.min(1, Math.max(0, ratio))})`
  })
  film?.addEventListener('ended', enterFinalState)
  film?.addEventListener('ended', () => fallbackAudio?.pause())
  film?.addEventListener('error', () => {
    hasFilm = false
    film.pause()
    screening.classList.remove('is-playing')
    trigger.querySelector('.screening__trigger-copy').textContent = '聆听这件作品'
    screening.querySelector('.screening__status').textContent = '此设备暂不支持过程影像，可聆听这件作品。'
  })
}

if (!workId) {
  renderMessage('没有找到这件作品', '请使用作品卡片上的完整二维码重新打开。')
} else {
  renderMessage('正在唤醒星云', '声音档案正从本地空间抵达。')
  getPublicWork(workId)
    .then(renderWork)
    .catch(() => renderMessage('作品暂时无法打开', '请确认电脑仍在运行，且手机与电脑连接同一 Wi‑Fi。'))
}
