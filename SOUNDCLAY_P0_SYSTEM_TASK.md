# SOUNDCLAY P0 SYSTEM INTEGRATION TASK

## Objective
Complete a working end-to-end SoundClay P0 system using a lightweight integration frontend. Do not spend time redesigning the final visual experience. Preserve the existing Three.js/kaleidoscope code for later.

## Read first
Read:
- `AGENTS.md`
- all existing backend files
- all existing frontend files
- existing README/docs
- current git status and branch history

Do not assume file locations or schemas before inspecting them.

## Current known completed backend work
- FastAPI foundation
- health/session/status foundations
- local emotion classifier
- emotion confirmation
- express/soothe recipe engine
- event bus/WebSocket foundation
- local save foundation
- local faster-whisper adapter
- real WAV transcription through `POST /api/stt/transcribe`
- saving `original.wav` and `portrait.json`

## Current known frontend work
- Vite project
- Three.js/kaleidoscope experiments
- modules such as state, socket, audio, save, sculpture and themes
- current visual may be slow or incomplete

## Phase 1 — Inspect and create a plan
Before editing:
1. Inspect current routes and schemas.
2. Inspect frontend entry point and package scripts.
3. Identify which existing components can be reused.
4. Produce a concise implementation plan.
Then execute the plan without waiting for approval unless a destructive conflict is found.

## Phase 2 — Finish backend P0

### A. Real audio features
Implement robust normalized:
- `volume`
- `pitch`
- `brightness`

Requirements:
- finite floats in `[0,1]`
- stereo to mono
- safe silence/short-file fallback
- no O(n²) work on long files
- prefer NumPy + soundfile
- use `asyncio.to_thread`

Add/preserve:
- `POST /api/audio/analyze`

Integrate features into:
- `POST /api/stt/transcribe`
- `GET /api/session/current`
- `POST /api/mode/select`
- `audio_features_ready` WebSocket event

A feature error must not erase a valid transcript.

### B. Stable mock and WebSocket motion protocol
Keep:
- `WS /ws/ring`

Add/preserve mock routes:
- `POST /api/mock/twist?value=0.65`
- `POST /api/mock/burst?strength=0.9`
- `POST /api/mock/freeze`

Event format:
```json
{"type":"twist","timestamp":1720000000000,"payload":{"value":0.65}}
```

Clamp values, broadcast events, return emitted JSON, and make freeze update the session safely.

### C. Complete saving
Extend the existing save request backward-compatibly with optional:
- `screenshot_data_url`
- `processed_audio_data_url`
- `final_motion`

Save when provided:
```text
works/<work-id>/
├─ original.wav
├─ output.wav
├─ sculpture.png
└─ portrait.json
```

Requirements:
- metadata-only save still works
- validate MIME prefixes and payload sizes
- never overwrite an earlier work
- store transcript, emotion, confidence, mode, features, recipe and motion
- no database

### D. Provider fallback
Keep local emotion analysis as default.
Do not invent external APIs.
External provider configuration may exist only as optional environment-variable-based infrastructure with safe fallback to local.

## Phase 3 — Build a lightweight frontend

Create a simple default integration page that does not initialize Three.js.

The page must include:

### Connection
- backend health indicator
- WebSocket connection indicator
- reconnect button

### Recording/transcription section
- show the expected audio file or provide a simple WAV file picker/upload path if the backend supports it
- `Start transcription` button
- loading state
- transcript display
- readable error display

### Emotion section
- initial emotion
- confidence
- reason
- selectable correction controls for all five emotions
- `Confirm emotion` button

### Mode section
- `Express`
- `Soothe`
- selected state
- submit/select button

### Feature and recipe section
Show:
- volume
- pitch
- brightness
- voice FX recipe
- audio-bed recipe
- visual recipe
Use readable formatted JSON or cards.

### Motion section
Buttons/sliders:
- twist value
- burst strength
- freeze
Display incoming WebSocket events.

### Save section
- optional small generated placeholder screenshot data URL only if needed for testing
- save button
- saved work ID/path
- do not require processed audio for the basic success path

### Event log
Show recent events with timestamps:
- status
- transcript
- features
- emotion
- material/recipe
- motion
- save
- error

## Phase 4 — Frontend integration behavior
- Centralize API base URL.
- Centralize WebSocket URL.
- Do not duplicate state across unrelated modules.
- Disable buttons while requests are running.
- Handle backend being offline.
- Handle malformed responses.
- Handle WebSocket reconnect.
- Use mock motion endpoints when no ring is connected.
- Avoid continuous animation loops in the lightweight page.
- Do not delete existing visual modules.
- Document how the final visual page can later consume the same state/events.

## Phase 5 — Offline tests and validation

Backend tests must cover:
1. health
2. local emotion analysis
3. express/soothe difference
4. audio features in range
5. silence fallback
6. audio analyze endpoint
7. mock motion endpoints
8. save metadata only
9. valid small image/audio data URLs
10. invalid data URL rejection

Mock Whisper model loading in API tests.

Frontend validation:
- install dependencies
- `npm run build`
- no missing imports
- no runtime dependency on Three.js for the lightweight page

End-to-end smoke test:
1. start backend
2. start frontend
3. verify health
4. transcribe/mock transcript
5. confirm emotion
6. select mode
7. trigger twist/burst/freeze
8. save
9. verify work metadata

## Required documentation
Create/update `docs/system_integration.md` with:
- exact backend startup commands
- exact frontend startup commands
- environment variables
- API route list
- WebSocket schema
- lightweight UI flow
- mock demo flow
- work output structure
- how to restore/connect the advanced Three.js visual later
- dependencies still waiting on Members A/B/D

## Non-goals
Do not:
- redesign final visuals
- optimize the existing kaleidoscope now
- add a framework
- add auth/database/cloud deployment
- add an OpenAI dependency
- invent sponsor APIs
- train models
- make therapeutic or diagnostic claims
- delete Member D's visual source code

## Acceptance criteria
Complete only when:
- simple frontend launches and is responsive
- backend launches
- frontend can complete the entire P0 flow
- no real ring is required for the mock demo
- real WAV STT remains available
- real features are stored and displayed
- emotion correction works
- express/soothe recipes display
- twist/burst/freeze work through mock + WebSocket
- save completes
- backend tests pass offline
- frontend build passes
- docs match implementation
- no secrets/runtime artifacts are tracked
- changes are committed
- worktree is clean

## Required final report
Return:
1. implementation summary
2. exact files changed
3. routes added/changed
4. frontend flow
5. tests/build commands
6. exact outputs
7. commit hash
8. remaining dependencies on Members A, B and D
