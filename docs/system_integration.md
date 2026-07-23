# SoundClay P0 system integration

SoundClay P0 is a local-first FastAPI and Vite system. The default page is a lightweight integration console and does not import or initialize Three.js. A real ring is not required: a mock transcript and HTTP motion controls exercise the complete workflow.

## Backend startup

From the repository root on Windows PowerShell:

```powershell
cd backend
python -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

The API is available at `http://127.0.0.1:8000`; Swagger is at `http://127.0.0.1:8000/docs`.

The default `.env.example` uses `STT_PROVIDER=mock`, so the no-hardware demo does not load or download a model. For real local transcription, set `STT_PROVIDER=faster_whisper`. The configured `WHISPER_MODEL` must already be present in the local faster-whisper cache when the machine has no internet access.

Backend environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `STT_PROVIDER` | `mock` | `mock`, `faster_whisper`, or `local_whisper` |
| `MOCK_TRANSCRIPT` | example Chinese sentence | Transcript returned by the mock STT adapter |
| `WHISPER_MODEL` | `base` | Local faster-whisper model name or path |
| `WHISPER_DEVICE` | `cpu` | faster-whisper device |
| `WHISPER_COMPUTE_TYPE` | `int8` | faster-whisper compute type |
| `WHISPER_LANGUAGE` | `zh` | Transcription language hint |
| `EMOTION_PROVIDER` | `local` | Reserved provider selector; the working path remains local |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Additional allowed frontend origin |

No API key, authentication service, database, cloud API, or ring driver is needed for P0.

## Frontend startup

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`.

Optional `frontend/.env` values:

```dotenv
VITE_API_BASE=http://127.0.0.1:8000
VITE_WS_URL=ws://127.0.0.1:8000/ws/ring
```

The checked-in `frontend/.env.example` contains the defaults. Do not commit a real `.env`.

## HTTP API

| Method | Route | Behavior |
| --- | --- | --- |
| `GET` | `/health` | Process health, returns `{"ok":true}` |
| `GET` | `/api/status` | Ring availability, phase, mock hint, and last feature/STT error |
| `GET` | `/api/session/current` | Complete in-memory session including transcript, emotion, features, recipe, and motion |
| `POST` | `/api/audio/upload` | Stores a raw RIFF/WAVE request body as `backend/audio/original.wav`, validates it, analyzes it, and emits `audio_features_ready` |
| `POST` | `/api/audio/analyze` | Analyzes the current `original.wav` with work dispatched through `asyncio.to_thread` |
| `POST` | `/api/stt/transcribe` | Transcribes the current WAV, analyzes real features, classifies expressed emotion, and emits progress/results |
| `POST` | `/api/mock/transcript` | Accepts `{"transcript":"..."}` for an offline/no-ring flow |
| `POST` | `/api/emotion/confirm` | Accepts one stable emotion value and advances the session |
| `POST` | `/api/mode/select` | Accepts `express` or `soothe`; returns features and the material recipe |
| `POST` | `/api/mock/twist?value=0.65` | Clamps to `[0,1]`, updates session motion, broadcasts and returns the event |
| `POST` | `/api/mock/burst?strength=0.9` | Clamps to `[0,1]`, increments burst count, broadcasts and returns the event |
| `POST` | `/api/mock/freeze` | Marks the session frozen, broadcasts and returns the event |
| `POST` | `/api/save` | Backward-compatible metadata save with optional screenshot, processed WAV, and final motion |
| `POST` | `/api/reset` | Creates a fresh in-memory session |
| `WS` | `/ws/ring` | Sends status on connection and broadcasts all P0 events |

The audio upload uses the raw request body rather than multipart form data, keeping the backend free of an additional multipart dependency. Accepted content types are `audio/wav`, `audio/x-wav`, and `application/octet-stream`; the maximum upload is 50 MiB.

## Audio features

`volume`, `pitch`, and `brightness` are finite normalized floats in `[0,1]`:

- volume is normalized RMS across the complete mono signal;
- pitch uses a bounded center window and FFT autocorrelation, avoiding quadratic work on long files;
- brightness uses the spectral centroid of the bounded window;
- stereo is averaged to mono;
- empty, silent, non-finite, and very short signals return safe values instead of NaN or infinity.

If feature extraction fails after a successful transcription, the transcript remains stored and is still classified. An `error` event with code `AUDIO_FEATURES_FAILED` reports the degraded feature step.

## WebSocket schema

Every event uses the same envelope:

```json
{
  "type": "twist",
  "timestamp": 1720000000000,
  "payload": { "value": 0.65 }
}
```

Stable event types are `status`, `transcript_ready`, `audio_features_ready`, `emotion_ready`, `material_ready`, `twist`, `burst`, `freeze`, `saved`, and `error`.

Motion payloads are:

```json
{"type":"twist","timestamp":1720000000000,"payload":{"value":0.65}}
{"type":"burst","timestamp":1720000000000,"payload":{"strength":0.9}}
{"type":"freeze","timestamp":1720000000000,"payload":{}}
```

The frontend reconnects with bounded exponential delay and offers a manual reconnect button. HTTP mock routes remain usable when the socket or real ring is unavailable.

## Lightweight UI flow

1. Confirm the backend and WebSocket indicators are online.
2. Choose a WAV and click **Upload WAV**, or skip audio and use **Analyze mock transcript**.
3. For a real/local STT run, click **Start transcription**.
4. Review the transcript, initial expressed-emotion label, confidence, and reason.
5. Select any of the five stable emotions and click **Confirm emotion**.
6. Choose **Express** or **Soothe**, then generate the recipe.
7. Inspect normalized features and the voice FX, audio-bed, and visual recipe cards.
8. Adjust and emit twist/burst, then freeze. The mock HTTP response and WebSocket event appear in the log.
9. Optionally include the generated placeholder PNG and click **Save locally**.
10. Read the returned work ID and absolute work path in the save panel.

All request buttons show disabled/loading states. Section-specific errors remain visible, malformed responses are rejected, and the event log retains the latest 50 events.

## Fast no-hardware demo

With both servers running and the backend using `STT_PROVIDER=mock`:

1. Click **Analyze mock transcript**.
2. Confirm or correct the emotion.
3. Select Express or Soothe and generate the recipe.
4. Emit twist and burst; click freeze.
5. Save without a screenshot for the minimal metadata-only path, or check the placeholder option to exercise image saving.

This path requires no Whisper model, internet access, microphone, ring, or IMU.

## Save request and output

The request remains compatible with the earlier shape. Every field is optional at schema level, while the session must already have a confirmed emotion and selected mode:

```json
{
  "screenshot_data_url": "data:image/png;base64,...",
  "processed_audio_data_url": "data:audio/wav;base64,...",
  "final_motion": {"twist": 0.65, "burstCount": 1, "frozen": true}
}
```

PNG screenshots are limited to 5 MiB decoded. Processed RIFF/WAVE audio is limited to 25 MiB decoded. MIME prefixes, strict base64, file signatures, finite motion numbers, and upload sizes are validated before a work directory is allocated. Unique timestamp-plus-random IDs prevent an earlier work from being overwritten.

```text
works/<work-id>/
├── original.wav    # when an uploaded/current original exists
├── output.wav      # when processed audio data or backend output exists
├── sculpture.png   # when a screenshot is supplied
└── portrait.json   # always
```

`portrait.json` contains session ID/phase, transcript, emotion, confidence, reason, mode, normalized features, recipe, audio URLs, and merged final motion.

## Advanced Three.js visual handoff

Member D's visual implementation remains in `frontend/src/main.js`, `frontend/src/style.css`, `frontend/src/sculpture.js`, and `frontend/src/kaleido-theme.js`. The default `index.html` now imports `integration-main.js`, whose dependency graph does not include Three.js and has no animation loop.

For a temporary legacy visual run, change the `index.html` module source back to `/src/main.js`. For the final integration, keep the centralized endpoints from `api.js`, consume the same session and WebSocket event envelopes, and map `material_ready`, `twist`, `burst`, and `freeze` into Member D's renderer. The visual should export a PNG data URL only when saving; it should not run model inference or alter backend event types.

## Remaining member dependencies

- **Member A:** provide the Zilo Whisper ring audio capture/transfer contract and decide whether the device posts raw WAV to `/api/audio/upload` or deposits a compatible local file. Confirm sample rate, channel count, session timing, and reconnect behavior.
- **Member B:** provide the real IMU-to-event adapter and calibrated mapping for twist value, burst strength, and freeze detection. It must emit the stable event envelope without invoking model inference in the live loop.
- **Member D:** connect the preserved Three.js/kaleidoscope renderer to the P0 session/event contract, apply the visual recipe and motion events, and provide the final screenshot plus any processed `output.wav` data at save time. Final performance and visual redesign remain outside P0 integration.

## Validation

From the repository root:

```powershell
python -m compileall backend
python -m pytest -q
cd frontend
npm run build
```

Tests generate temporary WAV/work data only, mock the transcription adapter, require no internet, and never load a Whisper model or real ring.
