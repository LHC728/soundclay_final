# SoundClay 成员 C 后端启动说明

## 你的角色
后端、STT、语义情绪、AudioRecipe 与作品保存。

## 第一阶段目标
先不接戒指和真实 AI，让成员 D 可以用固定文本完成：
`情绪分析 → 用户确认 → 选择 Express/Soothe → 收到 Recipe → 保存作品`

## Windows PowerShell

```powershell
cd backend
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

打开：

- Swagger：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>
- 当前会话：<http://127.0.0.1:8000/api/session/current>

## 第一次测试顺序

1. `POST /api/mock/transcript`

```json
{"transcript":"事情一直出问题，我已经改了很多次，真的特别烦。"}
```

2. `POST /api/emotion/confirm`

```json
{"emotion":"anger"}
```

3. `POST /api/mode/select`

```json
{"mode":"express"}
```

再请求一次，把 mode 改成：

```json
{"mode":"soothe"}
```

确认两次返回的 `recipe` 明显不同。

4. `POST /api/save`

首轮可不传截图：

```json
{"screenshot_data_url":null,"final_motion":{"twist":0.62,"burstCount":1}}
```

## 今天交给队友的接口

- `GET /api/status`
- `GET /api/session/current`
- `POST /api/mock/transcript`
- `POST /api/emotion/confirm`
- `POST /api/mode/select`
- `POST /api/save`
- `POST /api/reset`
- `WS /ws/ring`

## 下一阶段
骨架成功后再接：
1. 真正 STT Provider；
2. 真实 original.wav；
3. 成员 A/B 的事件总线；
4. output.wav 离线导出。
