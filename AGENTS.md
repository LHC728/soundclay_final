# AGENTS.md — SoundClay Integration Rules

## Goal
Build a complete, stable SoundClay P0 system first. Use a simple frontend for integration. Preserve the existing Three.js/kaleidoscope work for later visual redesign.

## Current architecture
- Backend: FastAPI, local faster-whisper, local emotion analysis, recipe generation, WebSocket, local saving.
- Frontend: Vite. Existing Three.js visual work may be incomplete or slow.
- Hardware: Zilo Whisper ring recording and IMU integration will be connected later.

## Allowed scope
You MAY modify:
- `backend/**`
- `frontend/**`
- `docs/**`
- root configuration files required for tests or startup

You MUST:
- preserve existing Three.js and kaleidoscope source files where practical
- avoid deleting Member D's visual work
- create a lightweight default integration UI without Three.js
- keep backend routes backward compatible
- keep the project runnable offline

## P0 user flow
1. Check backend connection.
2. Trigger or upload a WAV recording.
3. Transcribe with local faster-whisper.
4. Show transcript.
5. Show initial expressed-emotion classification.
6. Let the user confirm or correct the emotion.
7. Select `express` or `soothe`.
8. Show real audio features and generated recipe.
9. Receive or simulate `twist`, `burst`, and `freeze`.
10. Save the work and show the saved work ID/path.

## Stable values
Emotions:
- `joy`
- `anger`
- `sadness`
- `anxiety`
- `neutral-mixed`

Modes:
- `express`
- `soothe`

Motion events:
- `twist`
- `burst`
- `freeze`

WebSocket/backend event types:
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

## Frontend rules
- Default UI must be lightweight and work without Three.js.
- Use plain HTML/CSS/JavaScript within the existing Vite project.
- Do not add React/Vue/Svelte.
- Do not add heavy UI libraries.
- Do not remove existing visual modules; isolate or leave them available for later use.
- Provide clear loading, success, error, and disabled states.
- Provide a visible event log.
- Use `http://127.0.0.1:8000` as the default API base and `ws://127.0.0.1:8000/ws/ring` as the default WebSocket endpoint, configurable through Vite environment variables.
- The frontend must still work with mock routes when no ring is connected.

## Backend rules
- Keep local `faster-whisper`.
- Do not require OpenAI or unknown sponsor APIs.
- Run long audio work through `asyncio.to_thread`.
- Keep local emotion analysis as the working fallback.
- No auth, database, or cloud dependency.
- Never call model inference inside the live motion loop.
- Validate all data URLs and numeric inputs.
- Do not break existing endpoints.

## Safety and repository hygiene
Never commit:
- `.env`
- API keys
- `.venv`
- `node_modules`
- model caches
- generated WAV files
- generated `works/`
- build output such as `dist/`

## Testing
Backend:
- `python -m compileall backend`
- `python -m pytest -q`

Frontend:
- `npm run build`
- run any existing frontend checks

Tests must not:
- download Whisper models
- require internet
- require a real ring

## Finish requirements
- Run all tests and builds.
- Fix failures.
- Report exact files changed, routes changed, commands run, outputs, and remaining hardware dependencies.
- Commit changes with a clear message.
- Leave the worktree clean.
