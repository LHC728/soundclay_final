# AGENTS.md — SoundClay Repository Rules

## Project
SoundClay is a Zilo Whisper ring + FastAPI + Three.js project.

Core flow:
1. Record a short spoken emotional statement with the ring.
2. Read `backend/audio/original.wav`.
3. Transcribe with local faster-whisper.
4. Classify the expressed emotion.
5. Let the user confirm or edit the emotion.
6. Let the user select `express` or `soothe`.
7. Return a stable audio/visual recipe.
8. Sculpt through ring gestures.
9. Save the final Voice Portrait.

## Team ownership
- Member A: ring recording and audio capture.
- Member B: ring motion, IMU and gesture mapping.
- Member C: backend, STT, emotion analysis, recipes and saving.
- Member D: `frontend/`, Three.js, Web Audio and UI.

## Member C scope
- MAY modify `backend/**`, backend tests, backend docs, and root config required by backend.
- MUST NOT modify `frontend/**`.
- MUST NOT overwrite hardware files owned by Members A/B.
- Preserve existing public routes and backward compatibility.
- Public motion events are `twist`, `burst`, `freeze`.

## Required routes
- `GET /health`
- `GET /api/status`
- `GET /api/session/current`
- `POST /api/mock/transcript`
- `POST /api/stt/transcribe`
- `POST /api/emotion/confirm`
- `POST /api/mode/select`
- `POST /api/save`
- `POST /api/reset`
- `WS /ws/ring`

## Stable values
Emotions: `joy`, `anger`, `sadness`, `anxiety`, `neutral-mixed`.
Modes: `express`, `soothe`.

Event types:
`status`, `transcript_ready`, `audio_features_ready`, `emotion_ready`,
`material_ready`, `twist`, `burst`, `freeze`, `saved`, `error`.

## Security and runtime rules
- Never commit `.env`, API keys, `.venv`, model caches, generated WAV files, or `works/`.
- Keep local/offline fallbacks.
- Do not require OpenAI or an unknown sponsor API for P0.
- `faster-whisper` is the default STT provider.
- Do not add auth, a database, accounts, or unrelated frameworks.
- Do not call models inside the WebSocket motion loop.
- Run long audio work through `asyncio.to_thread`.
- Tests must not download models or need internet.

## Engineering rules
- Read existing code before editing.
- Preserve current working behavior.
- Add tests for completed features.
- Run:
  - `python -m compileall backend`
  - `python -m pytest -q`
- Commit changes with a clear message.
- Leave the worktree clean.
- Report files changed, routes changed, tests run, results, and remaining dependencies.
