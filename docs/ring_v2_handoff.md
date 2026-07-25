# SoundClay 成员 C/D 联调交付说明

本文档面向成员 C（STT、情绪分析、后端事件总线）和成员 D
（Three.js、Web Audio、交互页面）。戒指侧角色 A/B 已完成真机验收。

## 1. 联调架构

```text
Zilo 戒指
  │ BLE（只能由一个 Python 进程持有）
  ▼
RingRuntime（成员 A/B，本仓库）
  │ async event_sink(event)
  ▼
成员 C 后端事件总线 / WebSocket
  ├── WAV → STT → 情绪分析
  └── 标准事件 → 成员 D 页面
```

- 戒指必须连接运行 Python 的 Windows 电脑，不能直接连接云服务器。
- 成员 C 将后端和 `RingRuntime` 放在同一个 Python 3.11 进程中。
- 成员 D 不连接 BLE，只消费成员 C 转发的标准 JSON 事件。
- 手机 Zilo APK 和手机蓝牙在真机联调期间必须关闭。

## 2. 拉取和安装

```powershell
git clone https://github.com/Leonce12138/soundclay-ring.git
cd soundclay-ring
py -3.11 -m venv .venv311
.\.venv311\Scripts\python.exe -m pip install -r requirements.txt
```

还需要安装 FFmpeg，并确保下面命令能输出版本：

```powershell
ffmpeg -version
```

默认配置可以直接运行。需要覆盖 MAC 或阈值时，参考 `.env.example`
在启动进程前设置对应的系统环境变量，例如：

```powershell
$env:SOUNDCLAY_RING_ADDRESS = "FA:7E:92:E6:38:6D"
```

项目不会自动读取 `.env` 文件；`.env`、`runtime/`、真实录音和验收
日志均不会提交到 Git。

## 3. 成员 C：接入 RingRuntime

成员 C 必须创建一个长期存活的 `RingRuntime`，不能为录音和 IMU 分别
创建连接，也不要通过多个子进程调用戒指。

```python
import asyncio

from ring_runtime import RingRuntime


event_queue: asyncio.Queue[dict] = asyncio.Queue()


async def event_sink(event: dict) -> None:
    await event_queue.put(event)


runtime = RingRuntime(event_sink=event_sink)


async def start_ring() -> None:
    await runtime.connect()
    await runtime.get_status()


async def run_session(session_id: str) -> None:
    audio = await runtime.arm_recording(session_id)
    # audio.wav_path 是本机绝对路径，可直接交给 STT。
    await runtime.enter_motion_mode(session_id)
    await runtime.sculpt_until_freeze(session_id)


async def stop_ring() -> None:
    await runtime.close()
```

应用退出时必须 `await runtime.close()`，让 SDK 正常关闭实时上报和 BLE。
不要杀死进程来代替正常关闭。

### C 需要处理的事件

| 事件 | C 的处理 |
| --- | --- |
| `status` | 保存连接、阶段、模式提示、电量和固件状态 |
| `audio_ready` | 读取 `wavPath`，启动 STT；不要修改或移动文件 |
| `imu` | 原样转发给 D；高频事件应使用 WebSocket |
| `burst` | 原样转发给 D |
| `freeze` | 原样转发给 D，并确保同一 session 只处理一次 |
| `error` | 展示 `message` 和 `recommendedAction`；根据 `recoverable` 决定是否重试 |

STT 和情绪分析完成后，C 可用同一事件结构发布：

- `transcript_ready`
- `emotion_ready`
- `material_ready`
- `saved`

这些事件类型已经被 `event_contract.py` 接受。

## 4. 成员 D：消费交互事件

D 推荐通过成员 C 提供的 WebSocket 接收每行一个 JSON 对象：

```json
{
  "type": "imu",
  "timestamp": 1720000000000,
  "payload": {
    "sessionId": "SC-DEMO-001",
    "sequence": 100,
    "deviceTimestampMs": 123456,
    "twist": 0.42,
    "tiltX": -0.35,
    "accelMag": 0.18,
    "gyroZ": 92.4
  }
}
```

| 事件/字段 | D 的用途 |
| --- | --- |
| `imu.payload.twist` | `-1～1` 连续雕刻，正负表示转腕方向 |
| `imu.payload.tiltX` | `-1～1` 连续左右倾斜，驱动局部弯曲或横向偏移 |
| `imu.payload.accelMag` | `0～1` 动态加速度强度，可用于辅助形变 |
| `burst.payload.strength` | 快速挥动的一次性爆散触发 |
| `freeze.payload.source` | 固定为 `key_double_press`；停止编辑并凝固 |
| `status.payload.phase` | 页面步骤、连接提示和恢复提示 |

D 必须按 `sessionId` 隔离作品，并将 `burst`、`freeze` 作为离散事件处理。
`freeze` 要做幂等保护，重复收到时不能再次凝固。

## 5. 无戒指联调

成员 C/D 可以先使用仓库内的标准 mock：

```powershell
.\.venv311\Scripts\python.exe replay_events.py samples\mock_motion.ndjson
```

加速回放：

```powershell
.\.venv311\Scripts\python.exe replay_events.py samples\mock_motion.ndjson --speed 10
```

`samples/mock_motion.ndjson` 与真机采用相同事件结构。成员 C 可以把回放
输出接入事件总线，成员 D 不应为 mock 和真机编写两套处理逻辑。
mock 中的 `audio_ready.wavPath` 是接口占位路径；成员 C 真正测试 STT
时应替换为自己的 16kHz、16-bit、单声道 WAV，或使用真机生成的文件。

## 6. 真机联调顺序

首次联调必须在连接戒指的 Windows 电脑上完成：

1. 成员 C 启动后端和唯一的 `RingRuntime`。
2. 确认收到 `status.phase=connected`。
3. 用户长按戒指说话 3–8 秒。
4. C 收到 `audio_ready`，读取 `wavPath` 并完成 STT。
5. 用户根据页面提示单击戒指进入手势模式。
6. D 使用 `imu.twist` 驱动整体旋转，使用 `imu.tiltX` 驱动左右弯曲。
7. 用户快速挥动，D 收到一次 `burst`；收手动作由状态机吸收。
8. 用户双击实体按键，D 收到一次 `freeze`。
9. C/D 保存作品后发布 `saved`。
10. 下一轮录音前，页面提示用户单击返回录音模式。

真机调试前可以单独运行：

```powershell
.\.venv311\Scripts\python.exe hardware_smoke.py flow
```

## 7. 已验收基线

可提交的脱敏摘要位于
[`samples/hardware_acceptance_summary.json`](samples/hardware_acceptance_summary.json)。
完整真机日志保留在测试电脑的 `runtime/` 中，不上传 GitHub。

当前基线包括：

- 10 条严格合格 WAV；
- 10 分钟连续 IMU，无序号缺口；
- 普通转腕零误触；
- 快速挥动 20/20，且支持不同挥动方向；
- 双击凝固单次触发；
- 5/5 次连接在 60 秒内成功；
- 断线恢复均在 2 分钟内完成；
- 录音→手势→凝固连续 3 次成功。

## 8. 联调边界

- A/B 不负责 STT、情绪分析、Three.js、Web Audio 或作品存储。
- C/D 不得直接调用 `ring_sound.py` 的底层读写函数抢占 `0x0505` 或
  `0x0605`。
- 不得让手机 APK、另一个 Python 进程或另一台电脑同时连接戒指。
- 公共事件字段冻结后，新增字段应保持向后兼容，不能重命名现有字段。


