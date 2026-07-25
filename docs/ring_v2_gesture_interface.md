# SoundClay 戒指四动作接口

版本：`v2.0`  
更新日期：`2026-07-25`  
适用对象：成员 C（后端/AI）和成员 D（前端/视觉）

## 1. 最终动作清单

正式接口只有以下四个动作：

| 事件类型 | 用户动作 | 数据类型 | 数值范围 | 建议视觉效果 |
|---|---|---|---|---|
| `twist` | 左右转腕 | 连续 | `-1～1` | 带惯性的整体三维旋转 |
| `tiltX` | 左右倾斜 | 连续 | `-1～1` | 粒子轮廓左右弯曲或偏移 |
| `burst` | 快速挥动 | 离散 | `strength: 0～1` | 粒子爆散、能量环扩张 |
| `freeze` | 双击戒指实体按钮 | 离散终止 | `active: true` | 降速、晶体闪烁、凝固作品 |

`push` 已正式废弃，后端不会再发送，前端也不应继续保留 `push` 或凹陷逻辑。

前端只消费以上标准结果，不需要读取 `accelX/Y/Z`、`gyroX/Y/Z`，也不要在
浏览器中重复识别 IMU 动作。

### 训练标签与前端接口相互独立

用于重新采集和训练的真实动作标签固定为七类：

| 真实标签 | 中文动作 | 是否进入 IMU 模型训练 | 对应前端输出 |
|---|---|---:|---|
| `tilt_left` | 向左倾斜 | 是 | `tiltX` 负/正方向之一 |
| `tilt_right` | 向右倾斜 | 是 | `tiltX` 另一方向 |
| `twist` | 转腕（不区分左右类别） | 是 | `twist`，方向由数值正负表达 |
| `burst` | 快速挥动 | 是 | `burst` |
| `neutral` | 中立/静止 | 是 | 不发送离散动作，连续值接近 0 |
| `freeze` | 双击凝固 | 否，直接使用按钮事件 | `freeze` |
| `invalid` | 无效/不确定样本 | 否 | 不发送 |

注意：`twist_left` 和 `twist_right` 不再作为训练类别。转腕样本仍保留
`twist`、`gyroZ` 等带符号原始数值，因此不会丢失方向信息。训练模型负责判断
“这是转腕”，前端继续使用 `twist.value` 的正负控制左右旋转。

## 2. 服务地址

本机联调默认地址：

```text
HTTP:      http://127.0.0.1:8000
WebSocket: ws://127.0.0.1:8000/ws/ring
```

前端环境变量：

```env
VITE_API_BASE=http://127.0.0.1:8000
VITE_WS_URL=ws://127.0.0.1:8000/ws/ring
```

如果前后端不在同一台电脑，请将 `127.0.0.1` 换成后端所在电脑的 IP，并确保
端口 `8000` 可访问。

WebSocket 除四种动作外，还会发送 `status`、`error`、`audio_ready` 等系统
事件。前端必须根据 `message.type` 分流。

## 3. 通用消息结构

```json
{
  "type": "twist",
  "timestamp": 1720000000000,
  "payload": {
    "session_id": "backend-session-id",
    "audio_id": "audio-id",
    "revision": 12
  }
}
```

通用字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `type` | string | 事件类型 |
| `timestamp` | integer | 后端 Unix 毫秒时间戳 |
| `payload.session_id` | string | 当前后端作品会话 |
| `payload.audio_id` | string/null | 当前录音标识 |
| `payload.revision` | integer | 当前后端状态版本 |
| `payload.ringSessionId` | string/null | 戒指侧采集会话；Mock 时可能没有 |

前端切换作品或点击“重新开始”后，应忽略旧 `session_id` 或旧 `audio_id` 的
消息。`revision` 可用于诊断，不要用它对连续手势做相邻帧去重。

## 4. `twist`：转腕旋转

`twist` 是连续控制事件，默认最高约 `20Hz`。

```json
{
  "type": "twist",
  "timestamp": 1720000000000,
  "payload": {
    "session_id": "backend-session-id",
    "audio_id": "audio-id",
    "revision": 12,
    "value": -0.42,
    "normalizedValue": 0.29,
    "rawTwist": -0.42,
    "accelMag": 0.18,
    "sequence": 420,
    "deviceTimestampMs": 186532,
    "ringSessionId": "SC-1720000000000"
  }
}
```

正式控制字段：

- `payload.value`：`-1～1`，正负表示相反的转腕方向，`0` 表示没有明显转腕。

可选诊断字段：

- `normalizedValue`：兼容值，范围 `0～1`；新代码优先使用 `value`。
- `rawTwist`：进入后端前的标准化值。
- `accelMag`：动态加速度强度。
- `sequence`：IMU 序号。
- `deviceTimestampMs`：戒指设备时间戳。

建议：

- `value` 控制旋转速度或旋转力，而不是直接覆盖绝对角度。
- 前端可继续保留少量旋转惯性。
- `abs(value)` 很小时应逐渐停止加速。
- 不要把 `twist` 和 `tiltX` 同时写进同一个旋转变量。

## 5. `tiltX`：左右倾斜

`tiltX` 是连续姿态事件，默认最高约 `20Hz`。

```json
{
  "type": "tiltX",
  "timestamp": 1720000000050,
  "payload": {
    "session_id": "backend-session-id",
    "audio_id": "audio-id",
    "revision": 13,
    "value": 0.38,
    "sequence": 425,
    "deviceTimestampMs": 186582,
    "ringSessionId": "SC-1720000000000"
  }
}
```

正式控制字段：

- `payload.value`：`-1～1`。
- 正负表示相反的左右倾斜方向。
- `0` 表示接近进入 IMU 模式时记录的中立姿态。

戒指侧正式实时链路已经使用
`neutral → active_left/active_right → returning → neutral_dwell`
状态机过滤复位动作：

- 首次稳定离开中立约 `8°` 后锁定本轮左右方向。
- 回手阶段只允许 `tiltX` 平滑回到 `0`，越过零点的反向过冲不会输出成
  另一方向。
- 回到约 `±5°` 中立区并稳定 `300ms` 后，才允许识别下一次左右倾斜。
- 该逻辑位于正式 `MotionMapper`，真机 WebSocket、动作日志和前端收到的
  `tiltX` 都使用同一结果；前端不需要自行实现复位过滤。

进入 IMU 后，用户需要保持自然中立姿态约 `1.5 秒`，戒指后端会自动建立
`tiltX=0` 的零点。换手、换手指或改变戒指佩戴朝向后，应重新进入 IMU
完成标定。

建议：

- 控制局部弯曲、左右偏移、色彩流向或声像移动。
- 前端可以再做轻量插值，但不要增加很大的死区。
- 快速挥动期间后端会保持可信的上一姿态，避免 `burst` 造成倾斜跳变。
- 当前正负对应的实际左右方向以最终真机标定为准；如需反向，由后端配置
  `SOUNDCLAY_TILT_X_SIGN`，前端不要各自写死反向规则。

## 6. `burst`：快速挥动爆散

`burst` 是离散事件，一次有效挥动只发送一次。

```json
{
  "type": "burst",
  "timestamp": 1720000000100,
  "payload": {
    "session_id": "backend-session-id",
    "audio_id": "audio-id",
    "revision": 14,
    "strength": 0.84,
    "ringSessionId": "SC-1720000000000"
  }
}
```

正式控制字段：

- `payload.strength`：`0～1`，表示爆散强度。

建议：

- 每收到一条事件，只触发一次爆散动画。
- 不要根据 `strength` 连续重复触发。
- 可以让粒子爆散、能量环同步扩张，并保留部分形态变化。
- 戒指侧使用 `armed → outward_active → wait_return → returning → armed`
  状态机；挥出只发送一次事件，收回动作会在戒指侧被吸收。
- 用户必须完成收回并稳定后，下一次挥出才会重新触发。
- 状态机不依赖固定 5 秒 cooldown，也不会为了重新武装而启停 IMU。
- 原始 IMU 诊断字段 `burstState` 和 `burstArmed` 仅用于调试，前端视觉
  不需要处理它们。

## 7. `freeze`：双击凝固

`freeze` 来源于戒指实体按钮双击，是本轮雕刻的终止事件。

```json
{
  "type": "freeze",
  "timestamp": 1720000000300,
  "payload": {
    "session_id": "backend-session-id",
    "audio_id": "audio-id",
    "revision": 15,
    "active": true,
    "source": "key_double_press",
    "ringSessionId": "SC-1720000000000"
  }
}
```

正式控制字段：

- `payload.active`：正式真机事件为 `true`。
- `payload.source`：真机为 `key_double_press`。

前端处理顺序：

1. 判断当前页面仍处于雕刻阶段。
2. 将本地 `frozen` 标志设为 `true`，保证幂等。
3. 忽略后续 `twist`、`tiltX` 和 `burst`。
4. 降低粒子运动速度并进入晶体闪烁状态。
5. 固化当前视觉参数。
6. 执行保存流程并进入结果页。

## 8. 前端参考实现

```javascript
const API_BASE = import.meta.env.VITE_API_BASE || 'http://127.0.0.1:8000'
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://127.0.0.1:8000/ws/ring'

let socket
let reconnectTimer
let frozen = false
let currentSessionId = null
let currentAudioId = null

function connectRingEvents() {
  socket = new WebSocket(WS_URL)

  socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data)
    const payload = message.payload || {}

    // WebSocket 还包含 status/error/audio_ready，不属于四动作时直接跳过。
    if (!['twist', 'tiltX', 'burst', 'freeze'].includes(message.type)) return

    // 有当前会话时，拒绝上一轮残留事件。
    if (currentSessionId && payload.session_id !== currentSessionId) return
    if (currentAudioId && payload.audio_id !== currentAudioId) return

    if (frozen) return

    switch (message.type) {
      case 'twist':
        sculpture.setTwist(clamp(payload.value, -1, 1))
        break

      case 'tiltX':
        sculpture.setTiltX(clamp(payload.value, -1, 1))
        break

      case 'burst':
        sculpture.burst(clamp(payload.strength, 0, 1))
        break

      case 'freeze':
        if (payload.active !== false) {
          frozen = true
          sculpture.freeze(true)
          saveWork()
        }
        break
    }
  })

  socket.addEventListener('close', () => {
    clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(connectRingEvents, 1000)
  })
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number(value) || 0))
}
```

项目已经提供可直接使用的客户端：

```text
frontend/src/ring-client.js
```

它包含 WebSocket 自动重连逻辑，建议在现有项目中继续复用。

## 9. 戒指流程 HTTP 接口

| 方法 | 地址 | 说明 |
|---|---|---|
| `GET` | `/api/ring/status` | 查询戒指连接和操作状态 |
| `POST` | `/api/ring/connect` | 连接戒指 |
| `POST` | `/api/ring/recording/start` | 等待戒指录音并生成 WAV |
| `POST` | `/api/ring/motion/start` | 进入 IMU 雕刻流程 |
| `POST` | `/api/ring/operation/stop` | 停止当前戒指操作 |
| `POST` | `/api/ring/disconnect` | 主动断开戒指 |

前端不要创建第二条 BLE 连接。所有页面操作都通过同一个后端进程调用这些
HTTP 接口。

## 10. 无戒指 Mock

保持后端和前端运行，在 PowerShell 中执行：

```powershell
# 转腕：-1～1
Invoke-RestMethod -Method Post `
  "http://127.0.0.1:8000/api/mock/twist?value=-0.65"

# 左右倾斜：-1～1
Invoke-RestMethod -Method Post `
  "http://127.0.0.1:8000/api/mock/tilt-x?value=0.65"

# 快速挥动：0～1
Invoke-RestMethod -Method Post `
  "http://127.0.0.1:8000/api/mock/burst?strength=0.9"

# 双击凝固
Invoke-RestMethod -Method Post `
  "http://127.0.0.1:8000/api/mock/freeze?active=true"
```

Mock 与真机使用相同的核心控制字段：

- `twist.payload.value`
- `tiltX.payload.value`
- `burst.payload.strength`
- `freeze.payload.active`

`ringSessionId`、`sequence`、`deviceTimestampMs` 等硬件诊断字段在 Mock 中
可能不存在，前端不能依赖这些字段生成视觉效果。

## 11. 优先级与冲突规则

优先级：

```text
freeze > burst > tiltX / twist
```

- `freeze` 优先级最高，处理一次后锁定本轮作品。
- `burst` 是瞬时事件；爆散动画期间可继续接收连续值，但不要重复爆散。
- `twist` 和 `tiltX` 可以同时存在，但必须驱动不同的视觉参数。
- 前端只根据四个标准事件控制效果，不得再次使用原始 XYZ 分类。
- 同一作品的 `freeze` 处理必须幂等。
- WebSocket 断线后可以重连，但不能因此重置当前作品或重复执行旧事件。

## 12. 后端默认参数

```env
SOUNDCLAY_RING_EVENT_HZ=20

SOUNDCLAY_TWIST_SIGN=1
SOUNDCLAY_TWIST_DEADZONE_DPS=15
SOUNDCLAY_TWIST_FULL_SCALE_DPS=360
SOUNDCLAY_TWIST_EMA_ALPHA=0.25

SOUNDCLAY_TILT_X_SIGN=-1
SOUNDCLAY_TILT_X_DEADZONE_DEG=4
SOUNDCLAY_TILT_X_ENTER_DEG=8
SOUNDCLAY_TILT_X_RETURN_DEG=5
SOUNDCLAY_TILT_X_NEUTRAL_DWELL_MS=300
SOUNDCLAY_TILT_X_FULL_SCALE_DEG=40
SOUNDCLAY_TILT_X_EMA_ALPHA=0.18
SOUNDCLAY_TILT_X_CALIBRATION_DELAY_S=1.0
SOUNDCLAY_TILT_X_CALIBRATION_S=1.5

SOUNDCLAY_BURST_THRESHOLD=0.7
SOUNDCLAY_BURST_WINDOW_SAMPLES=30
SOUNDCLAY_BURST_MIN_ACTIVE_SAMPLES=20
SOUNDCLAY_BURST_QUIET_ACCEL_G=0.10
SOUNDCLAY_BURST_QUIET_GYRO_DPS=80
SOUNDCLAY_BURST_QUIET_DWELL_MS=400
SOUNDCLAY_BURST_RETURN_ACCEL_G=0.20
SOUNDCLAY_BURST_RETURN_MIN_ACTIVE_SAMPLES=3
```

参数由戒指后端统一管理。前端同事如果感觉方向、灵敏度或平滑度不合适，应
提供真机表现和事件值，由戒指侧统一标定，不要在多个前端页面分别改阈值。

## 13. 联调验收清单

- [ ] 前端能连接 `/ws/ring`，断线后能自动重连。
- [ ] `twist.value` 正负方向产生相反的整体旋转。
- [ ] `tiltX.value` 正负方向产生相反的局部弯曲。
- [ ] 收到一条 `burst` 只爆散一次。
- [ ] 收到 `freeze.active=true` 只凝固一次。
- [ ] 凝固后不再处理 `twist`、`tiltX`、`burst`。
- [ ] 点击重新开始后清空上一轮 `frozen` 和视觉状态。
- [ ] `push` 不再出现在代码、事件或 UI 文案中。
- [ ] 缺少硬件诊断字段时，Mock 仍能正常驱动全部视觉效果。


