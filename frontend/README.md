# SoundClay 前端：戒指粒子雕刻版

一个基于 Vite、Three.js 与 Web Audio 的全屏声音粒子创作页面。前端不直接连接 BLE，而是通过后端 WebSocket 接收戒指标准事件。

## 本次交互

- **转腕**：读取 `imu.payload.twist`（`-1～1`）。正负控制旋转方向，幅度控制转速与形体扭曲强度。
- **快速挥动**：读取一次性的 `burst.payload.strength`，触发由中心向外的粒子爆散。
- **双击实体按键**：读取 `freeze`，立即锁定当前粒子、停止音频并进入作品结果页。
- 所有粒子通过同一个 `THREE.Points` 对象旋转，共用一个旋转相位，严格围绕画面中心运动。
- `burst` 与 `freeze` 按 `sessionId` 隔离；重复 `freeze` 不会再次执行。

## WebSocket 事件

默认连接：

```text
ws://127.0.0.1:8000/ws/ring
```

标准 IMU 示例：

```json
{
  "type": "imu",
  "timestamp": 1720000000000,
  "payload": {
    "sessionId": "SC-DEMO-001",
    "sequence": 100,
    "twist": 0.42,
    "accelMag": 0.18
  }
}
```

爆散：

```json
{
  "type": "burst",
  "timestamp": 1720000000100,
  "payload": {
    "sessionId": "SC-DEMO-001",
    "sequence": 101,
    "strength": 0.9
  }
}
```

凝固：

```json
{
  "type": "freeze",
  "timestamp": 1720000000200,
  "payload": {
    "sessionId": "SC-DEMO-001",
    "sequence": 102,
    "source": "key_double_press",
    "active": true
  }
}
```

## 无戒指模拟

进入塑形页后：

- `←` / `A`：向左转腕
- `→` / `D`：向右转腕
- `B`：爆散
- `F`：模拟双击并凝固作品
- 鼠标左右拖动：模拟连续转腕
- 鼠标上下拖动：改变力量
- 双击粒子区域：凝固作品
- `Space`：播放或暂停
- `R`：撤回最后一个节点

## 环境变量

复制 `.env.example` 为 `.env.local`，按需要修改：

```env
VITE_API_BASE=http://127.0.0.1:8000
VITE_WS_URL=ws://127.0.0.1:8000/ws/ring
```

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

## 构建

```bash
npm run build
npm run preview -- --host 0.0.0.0
```
