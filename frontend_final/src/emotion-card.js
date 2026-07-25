import QRCode from 'qrcode'
import joyNebula from './assets/card-nebulas/joy.png'
import angerNebula from './assets/card-nebulas/anger.png'
import sadnessNebula from './assets/card-nebulas/sadness.png'
import anxietyNebula from './assets/card-nebulas/anxiety.png'
import neutralNebula from './assets/card-nebulas/neutral-mixed.png'

export const THEMES = {
  joy: { label: '喜悦', primary: '#37e9ce', accent: '#f5c45c', ink: '#071917' },
  anger: { label: '愤怒', primary: '#ef4b4f', accent: '#ff952f', ink: '#26080b' },
  sadness: { label: '悲伤', primary: '#426ee8', accent: '#d8e6ff', ink: '#091025' },
  anxiety: { label: '焦虑', primary: '#9d62ff', accent: '#e6ed47', ink: '#180b2b' },
  neutral_mixed: { label: '中性 / 混合', primary: '#8daab2', accent: '#f0f1e7', ink: '#101719' },
}

const CARD_NEBULAS = {
  joy: joyNebula,
  anger: angerNebula,
  sadness: sadnessNebula,
  anxiety: anxietyNebula,
  neutral_mixed: neutralNebula,
}

export function cardNebula(emotion) {
  return CARD_NEBULAS[emotion] || neutralNebula
}

const CAPTIONS = {
  joy: ['光从声音里醒来，向所有方向生长。', '这一刻轻得像星尘，也亮得像答案。', '我把雀跃藏进宇宙，等它慢慢发光。'],
  anger: ['炽热没有消失，它只是换了一种形状。', '风暴穿过胸口，留下仍在燃烧的星。', '我让失序的火焰，成为一片有方向的光。'],
  sadness: ['夜色很轻，刚好接住我的沉默。', '有些低落不必说完，它会在星云里停靠。', '我把未说出口的风，留在这片星云里。'],
  anxiety: ['尚未抵达的答案，在暗处练习发光。', '摇晃的念头，也能找到自己的轨道。', '我把散落的呼吸，慢慢收拢成一颗星。'],
  neutral_mixed: ['心事没有名字，仍然值得被看见。', '所有模糊的感受，都在此刻拥有形状。', '平静与复杂之间，漂着一片自己的星云。'],
}

export function emotionTheme(emotion) {
  return THEMES[emotion] || THEMES.neutral_mixed
}

export function pickCaption(emotion) {
  const captions = CAPTIONS[emotion] || CAPTIONS.neutral_mixed
  const index = crypto.getRandomValues(new Uint32Array(1))[0] % captions.length
  return captions[index]
}

function loadImage(source) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error('无法加载作品封面。'))
    image.src = source
  })
}

function drawCover(ctx, image, width, height) {
  const scale = Math.max(width / image.width, height / image.height)
  const drawWidth = image.width * scale
  const drawHeight = image.height * scale
  ctx.drawImage(image, (width - drawWidth) / 2, (height - drawHeight) / 2, drawWidth, drawHeight)
}

function lineWrap(ctx, text, maxWidth) {
  const lines = []
  let line = ''
  for (const character of text) {
    const candidate = line + character
    if (line && ctx.measureText(candidate).width > maxWidth) {
      lines.push(line)
      line = character
    } else {
      line = candidate
    }
  }
  if (line) lines.push(line)
  return lines.slice(0, 2)
}

function techFrame(ctx, x, y, width, height, color, cut = 24) {
  ctx.beginPath()
  ctx.moveTo(x + cut, y)
  ctx.lineTo(x + width - cut, y)
  ctx.lineTo(x + width, y + cut)
  ctx.lineTo(x + width, y + height - cut)
  ctx.lineTo(x + width - cut, y + height)
  ctx.lineTo(x + cut, y + height)
  ctx.lineTo(x, y + height - cut)
  ctx.lineTo(x, y + cut)
  ctx.closePath()
  ctx.strokeStyle = color
  ctx.stroke()
}

function pill(ctx, x, y, width, height, color) {
  ctx.beginPath()
  ctx.roundRect(x, y, width, height, height / 2)
  ctx.strokeStyle = color
  ctx.stroke()
}

function colorChannels(hex) {
  const value = Number.parseInt(hex.slice(1), 16)
  return { r: (value >> 16) & 255, g: (value >> 8) & 255, b: value & 255 }
}

function seededRandom(seed) {
  let value = seed >>> 0
  return () => {
    value += 0x6d2b79f5
    let result = value
    result = Math.imul(result ^ (result >>> 15), result | 1)
    result ^= result + Math.imul(result ^ (result >>> 7), result | 61)
    return ((result ^ (result >>> 14)) >>> 0) / 4294967296
  }
}

function seedFrom(value) {
  return Array.from(String(value)).reduce((seed, character) => ((seed * 31) + character.codePointAt(0)) >>> 0, 2166136261)
}

function drawNebula(ctx, width, height, theme, seed) {
  const random = seededRandom(seed)
  const primary = colorChannels(theme.primary)
  const accent = colorChannels(theme.accent)
  const centerX = width * (0.47 + (random() - 0.5) * 0.12)
  const centerY = height * (0.52 + (random() - 0.5) * 0.14)
  const angle = -0.55 + (random() - 0.5) * 1.2

  ctx.fillStyle = '#030507'
  ctx.fillRect(0, 0, width, height)
  const glow = ctx.createRadialGradient(centerX, centerY, 0, centerX, centerY, width * 0.68)
  glow.addColorStop(0, `rgba(${primary.r}, ${primary.g}, ${primary.b}, .25)`)
  glow.addColorStop(0.42, `rgba(${primary.r}, ${primary.g}, ${primary.b}, .07)`)
  glow.addColorStop(1, 'rgba(0, 0, 0, 0)')
  ctx.fillStyle = glow
  ctx.fillRect(0, 0, width, height)

  ctx.strokeStyle = `rgba(${primary.r}, ${primary.g}, ${primary.b}, .10)`
  ctx.lineWidth = 1
  for (let x = 36; x < width; x += 36) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, height); ctx.stroke() }
  for (let y = 36; y < height; y += 36) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(width, y); ctx.stroke() }

  for (let index = 0; index < 700; index += 1) {
    const size = random() < 0.035 ? 3 + random() * 4 : 0.6 + random() * 1.7
    const alpha = 0.18 + random() * 0.72
    ctx.fillStyle = random() < 0.16 ? `rgba(${accent.r}, ${accent.g}, ${accent.b}, ${alpha})` : `rgba(${primary.r}, ${primary.g}, ${primary.b}, ${alpha})`
    ctx.beginPath(); ctx.arc(random() * width, random() * height, size, 0, Math.PI * 2); ctx.fill()
  }

  ctx.save(); ctx.translate(centerX, centerY); ctx.rotate(angle)
  for (let index = 0; index < 2100; index += 1) {
    const progress = random() * 2 - 1
    const x = progress * width * 0.7 + Math.sin(progress * 4.8 + seed * 0.00001) * 64
    const y = (random() - 0.5) * (92 + 235 * Math.abs(progress)) + Math.sin(progress * 7.2) * 32
    const size = 0.9 + random() * (random() < 0.055 ? 6 : 2.2)
    const alpha = 0.16 + random() * 0.75
    ctx.fillStyle = random() < 0.14 ? `rgba(${accent.r}, ${accent.g}, ${accent.b}, ${alpha})` : `rgba(${primary.r}, ${primary.g}, ${primary.b}, ${alpha})`
    ctx.beginPath(); ctx.arc(x, y, size, 0, Math.PI * 2); ctx.fill()
  }
  ctx.restore()
  ctx.strokeStyle = `rgba(${accent.r}, ${accent.g}, ${accent.b}, .22)`
  ctx.lineWidth = 1.5
  ctx.beginPath(); ctx.arc(centerX, centerY, width * 0.31, 0, Math.PI * 2); ctx.stroke()
  ctx.beginPath(); ctx.arc(centerX, centerY, width * 0.48, Math.PI * 0.12, Math.PI * 1.36); ctx.stroke()
}

async function buildLegacyEmotionCard({ coverBlob, emotion, caption, url, savedAt }) {
  const width = 1240
  const height = 1748
  const coverHeight = 1048
  const theme = emotionTheme(emotion)
  const margin = 38
  const contentLeft = 88
  const contentRight = width - contentLeft
  const panelTop = coverHeight
  const qrSize = 296
  const qrFrameSize = qrSize + 30
  const qrX = contentRight - qrFrameSize
  const qrY = panelTop + 156
  const copyRight = qrX - 66
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  const coverUrl = URL.createObjectURL(coverBlob)

  try {
    const cover = await loadImage(coverUrl)
    ctx.fillStyle = '#06090d'
    ctx.fillRect(0, 0, width, height)
    drawCover(ctx, cover, width, coverHeight)
    const fade = ctx.createLinearGradient(0, coverHeight - 170, 0, coverHeight)
    fade.addColorStop(0, 'rgba(6,9,13,0)')
    fade.addColorStop(1, theme.ink)
    ctx.fillStyle = fade
    ctx.fillRect(0, coverHeight - 170, width, 170)
  } finally {
    URL.revokeObjectURL(coverUrl)
  }

  ctx.fillStyle = theme.ink
  ctx.fillRect(0, coverHeight, width, height - coverHeight)

  // One shared grid keeps the picture frame, information panel, copy and QR aligned.
  ctx.lineWidth = 3
  ctx.globalAlpha = 0.88
  techFrame(ctx, margin, margin, width - margin * 2, height - margin * 2, theme.primary, 30)
  ctx.globalAlpha = 0.6
  techFrame(ctx, margin + 16, margin + 16, width - (margin + 16) * 2, coverHeight - margin - 16, theme.accent, 20)
  ctx.globalAlpha = 1

  ctx.strokeStyle = theme.primary
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(margin, panelTop)
  ctx.lineTo(width - margin, panelTop)
  ctx.stroke()
  ctx.fillStyle = theme.primary
  ctx.fillRect(width / 2 - 18, panelTop - 3, 36, 6)

  ctx.fillStyle = theme.accent
  ctx.font = '600 24px "SFMono-Regular", Consolas, monospace'
  ctx.fillText('SOUNDCLAY / VOICE ARCHIVE', contentLeft, panelTop + 72)

  ctx.fillStyle = '#f7f7f0'
  ctx.font = '400 42px "Noto Sans SC", "Microsoft YaHei", sans-serif'
  const lines = lineWrap(ctx, caption, copyRight - contentLeft)
  lines.forEach((line, index) => ctx.fillText(line, contentLeft, panelTop + 232 + index * 58))
  ctx.strokeStyle = theme.primary
  ctx.globalAlpha = 0.72
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(contentLeft, panelTop + 368)
  ctx.lineTo(copyRight, panelTop + 368)
  ctx.stroke()
  ctx.globalAlpha = 1

  const qrUrl = await QRCode.toDataURL(url, {
    width: qrSize,
    margin: 1,
    errorCorrectionLevel: 'M',
    color: { dark: '#050607', light: '#ffffff' },
  })
  const qr = await loadImage(qrUrl)
  ctx.fillStyle = '#fff'
  ctx.fillRect(qrX + 15, qrY + 15, qrSize, qrSize)
  ctx.drawImage(qr, qrX + 15, qrY + 15, qrSize, qrSize)
  ctx.strokeStyle = theme.primary
  ctx.lineWidth = 4
  techFrame(ctx, qrX, qrY, qrFrameSize, qrFrameSize, theme.primary, 22)
  ctx.strokeStyle = theme.accent
  ctx.globalAlpha = 0.65
  ctx.lineWidth = 2
  techFrame(ctx, qrX + 9, qrY + 9, qrFrameSize - 18, qrFrameSize - 18, theme.accent, 16)
  ctx.globalAlpha = 1

  ctx.fillStyle = theme.primary
  ctx.font = '600 21px "SFMono-Regular", Consolas, monospace'
  ctx.textAlign = 'center'
  ctx.fillText('SCAN TO ENTER SCREENING', qrX + qrFrameSize / 2, qrY + qrFrameSize + 38)
  ctx.textAlign = 'left'

  const footerY = height - 126
  ctx.strokeStyle = theme.primary
  ctx.globalAlpha = 0.65
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(contentLeft, footerY - 34)
  ctx.lineTo(contentRight, footerY - 34)
  ctx.stroke()
  ctx.globalAlpha = 1
  ctx.fillStyle = theme.accent
  ctx.font = '500 23px "Noto Sans SC", "Microsoft YaHei", sans-serif'
  ctx.fillText('扫码进入这片星云的放映', contentLeft, footerY + 10)
  ctx.globalAlpha = 0.62
  ctx.font = '400 20px "SFMono-Regular", Consolas, monospace'
  const date = new Date(savedAt).toLocaleDateString('zh-CN').replace(/\//g, '.')
  ctx.textAlign = 'right'
  ctx.fillText(`SOUNDCLAY  /  ${date}`, contentRight, footerY + 10)
  ctx.textAlign = 'left'
  ctx.globalAlpha = 1

  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob((value) => value ? resolve(value) : reject(new Error('无法生成作品卡片。')), 'image/png')
  })
  return { blob, theme }
}

export async function buildEmotionCard({ emotion, caption, url, savedAt }) {
  const width = 1240
  const height = 1748
  const nebulaHeight = Math.round(height * 0.6)
  const theme = emotionTheme(emotion)
  const margin = 28
  const contentLeft = 92
  const contentRight = width - contentLeft
  const qrSize = 274
  const qrFrameSize = qrSize + 46
  const qrX = (width - qrFrameSize) / 2
  const qrY = nebulaHeight + 282
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')
  const date = new Date(savedAt).toLocaleDateString('zh-CN').replace(/\//g, '.')

  const nebula = await loadImage(CARD_NEBULAS[emotion] || neutralNebula)
  // Each approved visual contains a finished card.  Only its upper star-cloud area
  // is used here; the lower archive area is drawn live so its QR code always works.
  ctx.drawImage(nebula, 0, 0, nebula.width, nebula.height * 0.61, 0, 0, width, nebulaHeight)
  ctx.fillStyle = '#f0efea'
  ctx.fillRect(0, nebulaHeight, width, height - nebulaHeight)

  ctx.lineWidth = 3
  ctx.globalAlpha = 0.9
  techFrame(ctx, margin, margin, width - margin * 2, height - margin * 2, '#c8c7c1', 30)
  ctx.globalAlpha = 1
  ctx.strokeStyle = theme.primary
  ctx.lineWidth = 2
  ctx.beginPath(); ctx.moveTo(margin, nebulaHeight); ctx.lineTo(width - margin, nebulaHeight); ctx.stroke()
  ctx.fillStyle = theme.primary
  ctx.fillRect(width / 2 - 18, nebulaHeight - 3, 36, 6)

  ctx.fillStyle = '#16191d'
  ctx.font = '600 22px "SFMono-Regular", Consolas, monospace'
  ctx.fillText('SOUNDCLAY / VOICE ARCHIVE', contentLeft, nebulaHeight + 70)

  ctx.fillStyle = '#242629'
  ctx.font = '400 39px "Noto Serif SC", "STSong", "Microsoft YaHei", serif'
  ctx.textAlign = 'center'
  const lines = lineWrap(ctx, caption, width - 260)
  lines.forEach((line, index) => ctx.fillText(line, width / 2, nebulaHeight + 154 + index * 52))
  ctx.textAlign = 'left'

  const qrUrl = await QRCode.toDataURL(url, {
    width: qrSize,
    margin: 1,
    errorCorrectionLevel: 'M',
    color: { dark: '#050607', light: '#ffffff' },
  })
  const qr = await loadImage(qrUrl)
  ctx.fillStyle = '#fff'
  ctx.fillRect(qrX + 23, qrY + 23, qrSize, qrSize)
  ctx.drawImage(qr, qrX + 23, qrY + 23, qrSize, qrSize)
  ctx.strokeStyle = theme.primary
  ctx.lineWidth = 3
  techFrame(ctx, qrX, qrY, qrFrameSize, qrFrameSize, theme.primary, 20)
  ctx.strokeStyle = '#747474'
  ctx.globalAlpha = 0.55
  ctx.lineWidth = 2
  techFrame(ctx, qrX + 11, qrY + 11, qrFrameSize - 22, qrFrameSize - 22, '#747474', 14)
  ctx.globalAlpha = 1

  ctx.fillStyle = '#33363b'
  ctx.font = '500 22px "Noto Sans SC", "Microsoft YaHei", sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText('扫码聆听星云', width / 2, qrY + qrFrameSize + 48)
  ctx.textAlign = 'left'

  const footerY = height - 91
  ctx.strokeStyle = '#b8b7b1'
  ctx.lineWidth = 1
  ctx.beginPath(); ctx.moveTo(contentLeft, footerY - 32); ctx.lineTo(contentRight, footerY - 32); ctx.stroke()
  ctx.fillStyle = '#51545a'
  ctx.font = '400 20px "SFMono-Regular", Consolas, monospace'
  ctx.fillText(`ARCHIVE  /  ${date}`, contentLeft, footerY + 6)
  ctx.textAlign = 'right'; ctx.fillText('POINT CLOUD / LIVE', contentRight, footerY + 6)
  ctx.textAlign = 'left'

  const blob = await new Promise((resolve, reject) => {
    canvas.toBlob((value) => value ? resolve(value) : reject(new Error('无法生成作品卡片。')), 'image/png')
  })
  return { blob, theme }
}

export function printCard(blob) {
  const printUrl = URL.createObjectURL(blob)
  const printWindow = window.open('', '_blank')
  if (!printWindow) {
    URL.revokeObjectURL(printUrl)
    throw new Error('浏览器阻止了打印窗口，请允许弹窗后重试。')
  }
  printWindow.opener = null
  printWindow.document.write(`<!doctype html><html><head><title>SoundClay 作品卡片</title><style>@page{size:A6 portrait;margin:0}html,body{margin:0;width:105mm;height:148mm;background:#fff}img{display:block;width:105mm;height:148mm;object-fit:contain}</style></head><body><img src="${printUrl}" onload="window.print()"></body></html>`)
  printWindow.document.close()
  window.setTimeout(() => URL.revokeObjectURL(printUrl), 60000)
}
