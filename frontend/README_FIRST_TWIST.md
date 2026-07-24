# SoundClay 第一阶段：转腕

本版本只完成第一个戒指手势：`twist`。

- 初始形态保持原来的万花筒。
- 第一次明显转腕后，同一批 2100 个粒子平滑展开为横向粒子条带。
- 粒子数量和原有颜色体系不变。
- 持续转腕会让整条粒子带围绕画面中心旋转，并累计立体扭曲。
- 停止转腕后，条带和扭曲结果保留，不回弹为万花筒。
- Three.js 画布已改为全屏，条带长度自动适配屏幕宽高比。

## 本地测试

进入塑形页面后：

- 鼠标按住并左右拖动；或
- 按住键盘 `←` / `→`，也可使用 `A` / `D`。

## 硬件接口

WebSocket：`ws://127.0.0.1:8000/ws/ring`

```json
{
  "type": "twist",
  "payload": {
    "value": -0.42
  }
}
```

`value` 直接使用 `-1 ~ 1`，没有二次映射。

## 运行

```bat
cd /d C:\Users\hhyy\Desktop\soundclay_final\frontend
npm install
npm run dev
```
