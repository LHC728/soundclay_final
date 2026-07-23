export const GESTURE_THEME_MAP = {
  spread: 'prism',   // 张开：彩窗万花筒
  rotate: 'neon',    // 旋转：科技霓虹
  pinch: 'lattice',  // 捏合：白网空间
  swipe: 'ember',    // 滑动：爆发红橙
  hold: 'bloom',     // 停留：花窗宝石
  tap: 'prism',      // 轻点：回到默认彩窗
}

export function applyKaleidoTheme(gesture) {
  const theme = GESTURE_THEME_MAP[gesture] || 'prism'
  document.documentElement.dataset.kaleidoTheme = theme
  return theme
}