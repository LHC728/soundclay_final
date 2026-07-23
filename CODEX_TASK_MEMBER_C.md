# CODEX TASK — Finish SoundClay Member C Backend

## Current completed work
Member C has already completed:
- FastAPI backend foundation and `GET /health`
- session state and schemas
- local keyword emotion classification
- user emotion confirmation/editing
- `express` and `soothe` recipe generation
- WebSocket event bus foundation
- local work saving
- saving `original.wav` and `portrait.json`
- local `faster-whisper`
- `POST /api/stt/transcribe`
- real WAV transcription returning HTTP 200
- runtime files excluded through `.gitignore`

Current flow:
`original.wav → faster-whisper → local emotion result → user confirmation → mode recipe → save`

Do not modify `frontend/**`.

## Goal
Finish remaining Member C P0 backend work:
`real WAV → transcript → real audio features → emotion review → express/soothe recipe → stable mock/WebSocket events → saved Voice Portrait`

## 1. Real audio features
Inspect existing `backend/audio_pipeline.py`, `backend/server.py`, and `backend/schemas.py`.

Implement robust extraction of:
- `volume`
- `pitch`
- `brightness`

Requirements:
- all outputs finite floats in `[0,1]`
- stereo converted to mono
- safe defaults for silence, malformed, or very short input
- avoid O(n²) autocorrelation on long audio
- prefer NumPy + soundfile
- use `asyncio.to_thread`

Add or preserve:
`POST /api/audio/analyze`

Integrate into `POST /api/stt/transcribe`:
- store in `session.features`
- emit `audio_features_ready`
- expose through `GET /api/session/current`
- include in `POST /api/mode/select`

Feature failure must not destroy a valid transcript.

## 2. Stable event contract
Keep `WS /ws/ring`.

Support:
- `status`
- `transcript_ready`
- `audio_features_ready`
- `emotion_ready`
- `material_ready`
- `twist`
- `burst`
- `freeze`
- `saved`
- `error`

Public motion schema:
```json
{"type":"twist","timestamp":1720000000000,"payload":{"value":0.65}}
{"type":"burst","timestamp":1720000000000,"payload":{"strength":0.9}}
{"type":"freeze","timestamp":1720000000000,"payload":{}}
```

Add mock routes, for example:
- `POST /api/mock/twist?value=0.65`
- `POST /api/mock/burst?strength=0.9`
- `POST /api/mock/freeze`

Clamp values, broadcast events, update phase on freeze, and return emitted JSON.

## 3. Complete P0 saving
Keep current support for:
- `original.wav`
- `portrait.json`
- optional PNG data URL

Extend `POST /api/save` with an optional backward-compatible field:
```json
{
  "screenshot_data_url": "data:image/png;base64,...",
  "processed_audio_data_url": "data:audio/wav;base64,...",
  "final_motion": {"twist":0.62,"burstCount":1}
}
```

Save:
```text
works/<work-id>/
├─ original.wav
├─ output.wav
├─ sculpture.png
└─ portrait.json
```

Requirements:
- null processed audio still works
- validate data URL prefixes and payload size
- never overwrite earlier works
- persist emotion, mode, recipe, features, and motion
- no database

## 4. Emotion provider boundary
Do not invent sponsor APIs.

- `local` remains the working default
- unavailable external provider falls back safely to `local`
- keys/URLs only from environment variables
- update `.env.example`, never real secrets
- preserve five emotions and confirmation step
- no diagnosis claims
- no network provider is required for acceptance

## 5. Tests
Add offline tests under `backend/tests/`.

Tests must not download Whisper, need internet, or need a ring.

Cover:
1. `GET /health`
2. local emotion analysis
3. express vs soothe recipes differ
4. feature values finite and `[0,1]`
5. silence fallback
6. `POST /api/audio/analyze`
7. mock twist/burst/freeze
8. save metadata only
9. save valid small PNG/audio data URLs
10. reject invalid data URLs

Mock STT/model loading in API tests.

## 6. Documentation
Create/update `docs/backend_api.md` with:
- startup commands
- environment variables
- routes
- request/response examples
- WebSocket schema
- offline fallbacks
- work folder structure
- frontend notes

Member D mapping:
- `volume` → particle scale/breathing
- `pitch` → stretch/sector density
- `brightness` → brightness/sharpness
- `recipe.visual` → initial visual style
- `recipe.voiceFx` → Web Audio parameters
- `twist/burst/freeze` → live gesture events

## Non-goals
Do not:
- edit `frontend/**`
- redesign UI
- add auth/database/deployment
- add real sponsor APIs or OpenAI dependency
- replace faster-whisper
- change emotion list
- rewrite ring protocol
- train models
- make medical claims

## Acceptance criteria
Complete only when:
- existing routes still work
- STT stores real features
- `/api/audio/analyze` returns valid values
- mode select returns features + recipe
- mock motion events broadcast
- save supports metadata, original WAV, optional processed WAV and PNG
- offline tests pass
- syntax checks pass
- docs updated
- no secrets/runtime files committed
- `frontend/**` untouched
- changes committed
- worktree clean

## Finish report
Return:
1. summary
2. files changed
3. routes added/changed
4. commands/tests run
5. outputs
6. commit hash
7. remaining dependencies on A/B/D
