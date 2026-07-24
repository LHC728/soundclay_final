# SoundClay Frontend Upgrade

一个极简、全屏、以 Three.js 粒子为中心的声音二次创作界面。

## 流程

1. 录下一段声音
2. 在“释放—舒缓”之间选择方向
3. 用鼠标、触控或戒指动作塑造声音
4. 导出 WAV 音频和 PNG 封面

不展示情绪标签，不要求用户理解音频参数。

## 本地运行

```bash
npm install
npm run dev -- --host 0.0.0.0
```

浏览器打开终端显示的地址，通常是：

```text
http://localhost:5173/
```

麦克风需要在 `localhost` 或 HTTPS 环境下使用。

## 生产构建

```bash
npm run build
npm run preview -- --host 0.0.0.0
```

## 交互

- 录音页：点击圆形按钮开始/结束录音
- 模式页：拖动粒子或滑轨，在释放与舒缓间连续变化
- 塑形页：
  - 左右拖动：空间感
  - 上下拖动：力量/柔和程度
  - 轻点粒子：留下创作节点
  - 长按粒子：凝固/恢复视觉
  - 空格：播放/暂停
  - R：撤回最后一个节点
- 完成页：播放、分享/下载、重新开始

## 戒指事件接口

通过浏览器自定义事件接入戒指 SDK：

```js
window.dispatchEvent(
  new CustomEvent('soundclay:gesture', {
    detail: {
      type: 'rotate',
      x: 0.6,
      strength: 1,
    },
  }),
)
```

支持的 `type`：

- `rotate`
- `lift`
- `press`
- `tap`
- `hold`
- `swipe`

## 合并进现有仓库

将本项目的 `src`、`index.html` 与 `package.json` 覆盖到现有 `frontend` 目录，然后执行：

```bash
npm install
npm run dev
```
