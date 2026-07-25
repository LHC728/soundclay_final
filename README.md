# SoundClay

SoundClay 是一套本地运行的声音交互系统：用户先录下一段声音，再选择“舒缓”或“释放”模式，通过智能戒指或页面模拟动作改变 Three.js 粒子作品，并同步控制 Ableton Live 中的音乐、音色、鼓点和音量。

项目默认离线运行，不依赖云端数据库。录音、作品和模型缓存均保存在本机，并已通过 `.gitignore` 排除。

## 当前体验流程

1. 点击页面中央按钮开始录音，再次点击结束录音。
2. 将模式滑块拖到左侧进入“舒缓”，拖到右侧进入“释放”。
3. 进入“用动作雕刻声音”：
   - 转腕：旋转粒子球，并在 Ableton 中切换三档音色。
   - 快速挥动：第一次爆散，第二次聚合，同时触发鼓点。
   - 手指左右摆动：控制球体和声音的大、中、小三档。
   - 双击或点击“凝固”：冻结作品、停止 Ableton 音乐并保存。
4. 结果页可以分享作品或重新开始。

浏览器不会播放录下的声音；录音只用于驱动和保存作品，现场声音由 Ableton Live 输出。

## 项目结构

```text
soundclay_final/
├─ backend/                 FastAPI、音频分析、STT、情绪、戒指和 Ableton 接口
│  ├─ server.py             HTTP 与 WebSocket 入口
│  ├─ ableton_adapter.py    MIDI/OSC 映射
│  ├─ ring_integration.py   AB RingRuntime 适配
│  ├─ samples/              无戒指联调样本
│  └─ tests/                后端自动测试
├─ frontend_final/          当前正式前端（Vite + Three.js）
├─ frontend/                保留的旧版前端，不是当前启动入口
├─ docs/                    集成说明
└─ works/                   本地生成的作品，不提交 Git
```

## 环境要求

- Windows 10/11
- Python 3.11
- Node.js 20.19+ 或 22.12+
- Ableton Live（需要音乐联动时）
- loopMIDI（需要 MIDI 联动时）
- FFmpeg（真戒指音频解码时）

无戒指模拟、后端测试和前端构建不需要真实硬件，也不需要启动 Ableton。

## 首次安装

在仓库根目录打开 PowerShell：

```powershell
py -3.11 -m venv .venv311
.\.venv311\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
Copy-Item backend\.env.example backend\.env
```

不要复制其他电脑或旧项目中的 `.venv`、`.venv311`、`node_modules`。这些目录包含与本机路径和运行时绑定的文件，应在当前电脑重新创建。

## 启动后端

在仓库根目录执行：

```powershell
.\.venv311\Scripts\Activate.ps1
Set-Location backend
python -m uvicorn server:app --host 127.0.0.1 --port 8000
```

启动后可访问：

- 健康检查：<http://127.0.0.1:8000/health>
- Ableton 状态：<http://127.0.0.1:8000/api/ableton/status>
- Swagger 接口文档：<http://127.0.0.1:8000/docs>
- 戒指 WebSocket：`ws://127.0.0.1:8000/ws/ring`

## 启动正式前端

另开一个 PowerShell 窗口：

```powershell
Set-Location frontend_final
npm ci
Copy-Item .env.example .env.local
npm run dev -- --host 127.0.0.1
```

打开 <http://127.0.0.1:5173>。

Windows 下也可以双击：

```text
frontend_final/start-soundclay.bat
```

麦克风权限需要在 `localhost`、`127.0.0.1` 或 HTTPS 页面中使用。首次打开时请允许浏览器访问麦克风。

## 前端配置

`frontend_final/.env.local`：

```dotenv
VITE_API_BASE=http://127.0.0.1:8000
VITE_WS_URL=ws://127.0.0.1:8000/ws/ring
```

修改环境变量后需要重新启动 Vite。

## Ableton Live 与 loopMIDI

### 1. 创建 MIDI 端口

在 loopMIDI 中创建一个端口，例如：

```text
SoundClay MIDI
```

端口名称必须与 `backend/.env` 中的 `ABLETON_MIDI_PORT` 一致。如果电脑上实际使用的是 `SoundClay Live 2026`，就填写该名称：

```dotenv
ABLETON_MIDI_ENABLED=true
ABLETON_MIDI_PORT=SoundClay Live 2026
ABLETON_MIDI_CHANNEL=0
ABLETON_MIDI_GAIN_FLOOR=0.4
ABLETON_MIDI_MAX_HZ=50
```

`ABLETON_MIDI_CHANNEL=0` 表示 MIDI Channel 1。修改后重启后端。

### 2. 设置 Ableton 输入

打开 Ableton Live：

1. 进入“设置 → Link, Tempo & MIDI”。
2. 找到对应的 loopMIDI 输入端口。
3. 打开该输入端口的“外部控制（Remote）”。
4. 不需要从 Ableton 输出回同一个端口，避免 MIDI 回路。

如果刚创建或改名 MIDI 端口，请完全关闭并重新打开 Ableton Live，让它重新扫描端口。

### 3. 当前 MIDI 映射

所有消息使用 Channel 1：

| SoundClay 动作 | MIDI 消息 | Ableton 目标 |
| --- | --- | --- |
| 转腕 | CC 20，值 16 / 64 / 112 | Instrument Rack `Chain Selector` 三档音色 |
| 手指左/中/右 | CC 21，值 0 / 64 / 127 | Main Utility `Gain` 三档音量 |
| Joy Express / Soothe | Note 60 / 61 | 对应 Scene |
| Anger Express / Soothe | Note 62 / 63 | 对应 Scene |
| Sadness Express / Soothe | Note 64 / 65 | 对应 Scene |
| Anxiety Express / Soothe | Note 66 / 67 | 对应 Scene |
| Mixed Express / Soothe | Note 68 / 69 | 对应 Scene |
| 快速挥动 | Note 70 | Drum Layer；每次挥动发送两次，间隔 100 ms |
| 凝固作品 | Note 71（Ableton 通常显示 B3） | `Stop All Clips` |

进入 Ableton MIDI 映射模式（`Ctrl + M`）后，点击需要控制的目标，再通过网页触发对应按钮或动作完成映射，最后再次按 `Ctrl + M` 退出。

“凝固”停止功能同时发送 Note 71、MIDI Clock Stop 和 OSC `freeze`。当前使用 Remote 输入时，应优先把 Note 71 映射到 `Stop All Clips`。

### 4. 检查连接

访问：

```text
http://127.0.0.1:8000/api/ableton/status
```

重点检查：

- `midi.enabled` 是否为 `true`
- `midi.resolvedPort` 是否是正确的 loopMIDI 端口
- `midi.lastError` 是否为空
- 操作网页时 loopMIDI 数据计数是否增长
- Ableton 右上角 MIDI 输入指示灯是否闪烁

## 可选 OSC

OSC 默认关闭。需要 Max for Live 接收时，在 `backend/.env` 中设置：

```dotenv
ABLETON_OSC_ENABLED=true
ABLETON_OSC_HOST=127.0.0.1
ABLETON_OSC_PORT=11000
```

后端会发送：

- `/soundclay/mode`
- `/soundclay/twist`
- `/soundclay/energy`
- `/soundclay/filter`
- `/soundclay/burst`
- `/soundclay/freeze`
- `/soundclay/color`

## 智能戒指接入

硬件模式默认关闭，因此本地页面和自动测试不要求戒指：

```dotenv
SOUNDCLAY_RING_ENABLED=false
```

连接 AB 的 `RingRuntime` 时，在 `backend/.env` 中填写：

```dotenv
SOUNDCLAY_RING_ENABLED=true
SOUNDCLAY_RING_PATH=C:\path\to\soundclay-ring
SOUNDCLAY_RING_ADDRESS=FA:7E:92:E6:38:6D
SOUNDCLAY_FFMPEG=ffmpeg
```

`SOUNDCLAY_RING_PATH` 应指向直接包含 `ring_runtime.py` 的目录。真机联调前请关闭手机 Zilo APK 和其他 BLE 程序，并确保只运行一个 FastAPI/Python 进程。

### 无戒指事件回放

后端运行后，在仓库根目录执行：

```powershell
.\.venv311\Scripts\python.exe backend\replay_ring_events.py backend\samples\mock_motion.ndjson --speed 10
```

样本使用 AB 的 NDJSON 事件格式，可验证 `imu`、`burst`、`freeze`、会话隔离和重复事件去重。

## 页面模拟操作

没有戒指时，可使用页面按钮、鼠标和键盘：

| 操作 | 效果 |
| --- | --- |
| 左右拖动 | 模拟转腕和球体旋转 |
| `Shift` + 左右拖动 | 调整球体/声音三档大小 |
| 快速甩动鼠标或按 `B` | 爆散/聚合并触发鼓点 |
| `←` / `A`、`→` / `D` | 模拟转腕 |
| `P` / `Z` | 小球、小声 |
| `L` / `X` | 大球、大声 |
| 双击或按 `F` | 凝固、保存并停止 Ableton |
| `R` | 撤回最近一个时间节点 |

页面底部的“转腕”“挥动”“大小”“凝固”按钮使用相同接口，可用于联调。

## 主要接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 后端健康检查 |
| `GET` | `/api/status` | 当前会话状态 |
| `GET` | `/api/ableton/status` | MIDI/OSC 状态和映射 |
| `POST` | `/api/ableton/stop` | 停止 Ableton |
| `POST` | `/api/mode/select` | 选择 Express/Soothe 并触发 Scene |
| `POST` | `/api/ableton/motion/{type}` | 前端动作转发 |
| `POST` | `/api/ring/session/start` | 启动戒指录音会话 |
| `POST` | `/api/mock/ring-event` | 无戒指注入 AB 格式事件 |
| `POST` | `/api/save` | 保存本地作品 |
| `POST` | `/api/reset` | 重置当前会话 |
| `WS` | `/ws/ring` | 戒指状态和动作事件 |

旧版 STT、情绪分析、音频上传和 recipe 接口继续保留，可在 Swagger 中查看。

## 本地作品

完成作品后，后端将内容保存在：

```text
works/<work-id>/
```

根据当前数据可能包含：

- `original.wav`
- `output.wav`
- `sculpture.png`
- `portrait.json`
- `metadata.json`

`works/`、录音文件、环境变量、虚拟环境、`node_modules` 和构建输出都不会提交到 Git。

## 测试与构建

在仓库根目录运行后端检查：

```powershell
.\.venv311\Scripts\python.exe -m compileall backend
.\.venv311\Scripts\python.exe -m pytest -q
```

运行正式前端构建：

```powershell
Set-Location frontend_final
npm run build
```

测试不会下载 Whisper 模型，不需要网络、Ableton 或真实戒指。

## 常见问题

### 页面显示 `Failed to fetch`

确认后端正在运行，并访问 <http://127.0.0.1:8000/health>。如果健康检查失败，重新启动 FastAPI。

### loopMIDI 有数据，但 Ableton 没反应

依次检查：

1. Ableton 选择的输入端口是否与 `midi.resolvedPort` 一致。
2. 对应输入端口的 Remote 是否打开。
3. Ableton 是否处于 MIDI 映射模式；正常演奏时应退出 `Ctrl + M`。
4. 映射使用的 CC/Note 是否与上表一致。
5. 新建端口后是否重启过 Ableton。

### 点击凝固但音乐没有停止

确认 Note 71 已映射到 Ableton 的 `Stop All Clips`。仅打开 Remote 不会自动建立具体控件映射。

### 后端虚拟环境无法启动

删除并重新创建本机 `.venv311`。不要复用从其他目录复制来的虚拟环境。

### 真实录音无法转写

默认 `STT_PROVIDER=mock`。需要本地 Whisper 时改为：

```dotenv
STT_PROVIDER=faster_whisper
WHISPER_MODEL=base
WHISPER_DEVICE=cpu
WHISPER_COMPUTE_TYPE=int8
```

模型必须已经缓存或使用本地模型路径；完全离线环境不会自动下载模型。

## 数据与隐私

- 默认服务只监听 `127.0.0.1`。
- 作品、录音和会话数据保存在本机。
- `.env` 不提交 Git。
- `EMOTION_PROVIDER=local` 或留空远程密钥时，不会把文本发送给外部情绪服务。
- 启用远程情绪 Provider 前，请确认数据使用要求。
