# SoundClay P0 system integration

SoundClay P0 is a local-first FastAPI and Vite system. The current default page deliberately bypasses recording, transcription, and emotion classification: it opens directly on a horizontal direction choice. Left enters Rhythm and right enters Soothe. Both modes use the shared Three.js particle instrument, local Web Audio loop, mock/ring motion interface, and optional Ableton OSC bridge. Legacy audio/STT/emotion routes remain available for backward-compatible clients but are not called by the default page.

## Startup

Backend, from the repository root in Windows PowerShell:

```powershell
py -3.11 -m venv .venv311
.venv311\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item backend\.env.example backend\.env
cd backend
python -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

Frontend, in a second terminal:

```powershell
cd frontend
npm ci
npm run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`. Swagger is at `http://127.0.0.1:8000/docs`.

The supported integration environment uses Python 3.11 and a root-level `.venv311`. Do not copy or reuse a virtual environment from another checkout. FFmpeg must be available on `PATH` before real ring audio/STT acceptance.

## Environment

Backend variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `STT_PROVIDER` | `mock` | `mock`, `faster_whisper`, or legacy alias `local_whisper` |
| `MOCK_TRANSCRIPT` | local example | Offline transcript fallback |
| `WHISPER_MODEL` | `base` | Local faster-whisper model name or path |
| `WHISPER_DEVICE` | `cpu` | faster-whisper device |
| `WHISPER_COMPUTE_TYPE` | `int8` | faster-whisper compute type |
| `WHISPER_LANGUAGE` | `zh` | Language hint; blank allows auto-detection |
| `WHISPER_BEAM_SIZE` | `1` | Beam size from 1 through 20; `1` is the fast interactive default |
| `STT_TIMEOUT_SECONDS` | `120` | Local STT timeout from 1 through 3600 seconds |
| `EMOTION_PROVIDER` | `hybrid` | `hybrid`/`glm` uses GLM when a key exists; `local` forces offline fusion |
| `EMOTION_BASE_URL` | `https://aiping.cn/api/v1` | User-selected OpenAI-compatible base URL |
| `EMOTION_MODEL` | `GLM-5.2` | Emotion reasoning model ID sent to the compatible API |
| `EMOTION_SOFT_TIMEOUT_SECONDS` | `1.5` | Maximum time the interactive flow waits for GLM before freezing the local result |
| `EMOTION_TIMEOUT_SECONDS` | `3` | Hard HTTP timeout for the background GLM request, 1 through 30 seconds |
| `EMOTION_CIRCUIT_FAILURES` | `3` | Consecutive GLM failures before temporarily bypassing the remote provider |
| `EMOTION_CIRCUIT_SECONDS` | `30` | Circuit-breaker cooldown in seconds |
| `EMOTION_API_KEY` | blank | Bearer token read only from `backend/.env`; blank uses local fusion immediately |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Additional CORS origin |
| `ABLETON_OSC_ENABLED` | `false` | Enables the optional local OSC/UDP bridge |
| `ABLETON_OSC_HOST` | `127.0.0.1` | Ableton/Max for Live OSC receiver host |
| `ABLETON_OSC_PORT` | `11000` | Ableton/Max for Live UDP receive port |
| `ABLETON_MIDI_ENABLED` | `false` | Enables the existing SoundClay MIDI mapping saved in the Ableton Set |
| `ABLETON_MIDI_PORT` | `SoundClay MIDI` | Case-insensitive loopMIDI output name or substring |
| `ABLETON_MIDI_CHANNEL` | `0` | Zero-based Mido channel; `0` is Ableton MIDI channel 1 |
| `ABLETON_MIDI_GAIN_FLOOR` | `0.4` | Lowest Main gain fraction while ring energy is zero |
| `ABLETON_MIDI_MAX_HZ` | `50` | Maximum CC update rate per controller |
| `SOUNDCLAY_RING_ENABLED` | `false` | Enables the single hardware `RingRuntime`; keep false for offline/mock testing |
| `SOUNDCLAY_RING_PATH` | blank | Optional override directory; blank uses the RingRuntime bundled in `backend/` |
| `SOUNDCLAY_RING_ADDRESS` | `FA:7E:92:E6:38:6D` | AB's default Zilo ring BLE address; override for another device |
| `SOUNDCLAY_SESSION_ROOT` | `./runtime/sessions` | RingRuntime audio/event output, ignored by Git |
| `SOUNDCLAY_FFMPEG` | `ffmpeg` | FFmpeg executable name or absolute path used by AB audio decoding |

The faster-whisper model must already be cached or supplied as a local path for offline use. Model instances are cached in memory by model/device/compute configuration. Tests replace provider/model calls and never download a model.

Frontend variables:

```dotenv
VITE_API_BASE=http://127.0.0.1:8000
VITE_WS_URL=ws://127.0.0.1:8000/ws/ring
VITE_EMOTION_AUDIO_BASE=/audio/emotions
VITE_RHYTHM_AUDIO_URL=/audio/modes/rhythm.wav
VITE_SOOTHE_AUDIO_URL=/audio/modes/soothe.wav
```

## Public values and phases

Canonical emotion values are `joy`, `anger`, `sadness`, `anxiety`, and `neutral_mixed`. The legacy request spelling `neutral-mixed` remains accepted and is serialized as `neutral_mixed`. This is an expressed-emotion classification of the user's words, not a diagnosis or claim about a hidden internal state.

Modes are `express` and `soothe`. Stable ring controls are signed `twist`, signed `tiltX`, discrete `burst`, and idempotent `freeze`; legacy `finger` remains an input alias for `tiltX`, and the default UI also keeps the backward-compatible `color` interaction.

The eight taskbook phases remain available to legacy clients: `ready`, `recording`, `understanding`, `emotion_review`, `mode_choice`, `materializing`, `sculpting`, and `saved`. `audio_ready` is an explicit recoverable handoff between Recording and Understanding. The current product page skips this chain and starts with direct direction selection; `emotion_review` remains only for backward compatibility.

## HTTP and WebSocket API

| Method | Route | Behavior |
| --- | --- | --- |
| `GET` | `/health` | Process health |
| `GET` | `/api/status` | Phase, session/audio ownership, revision, ring/mock hint, and last error |
| `GET` | `/api/ableton/status` | Optional OSC transport configuration and address map |
| `GET` | `/api/session/current` | Authoritative complete in-memory session |
| `POST` | `/api/audio/upload` | Atomically stores and analyzes a raw RIFF/WAVE body |
| `POST` | `/api/audio/analyze` | Re-analyzes the current WAV outside the event loop |
| `POST` | `/api/stt/transcribe` | Transcribes the current owned WAV and classifies expressed emotion; `?auto_confirm=true` proceeds directly to Mode Choice |
| `POST` | `/api/mock/recording` | Enters Recording and clears temporary input/derived state |
| `POST` | `/api/mock/transcript` | Offline/manual transcript and local emotion fallback; supports `?auto_confirm=true` |
| `POST` | `/api/emotion/confirm` | Confirms or corrects an emotion |
| `POST` | `/api/recipe/preview` | Builds an Express/Soothe preview without advancing or mutating the session |
| `POST` | `/api/mode/select` | Selects Express/Soothe and generates a validated recipe |
| `POST` | `/api/mock/twist?value=0.65` | Clamps, traces, broadcasts, and returns twist |
| `POST` | `/api/mock/tilt-x?value=0.65` | Simulates signed ring tilt and drives the existing three-level size/gain mapping |
| `POST` | `/api/mock/burst?strength=0.9` | Clamps, traces, broadcasts, and returns burst |
| `POST` | `/api/mock/freeze?active=true` | Freezes or releases, traces, broadcasts, and returns freeze; omitting `active` preserves the original freeze behavior |
| `POST` | `/api/mock/color?hue=210` | Normalizes hue, traces/broadcasts the random color change, and forwards it to OSC |
| `GET` | `/api/ring/status` | RingRuntime enablement, connection, current AB session, and recoverable error state |
| `POST` | `/api/ring/session/start` | Arms audio capture and starts the single RingRuntime session when hardware mode is enabled |
| `POST` | `/api/mock/ring-event` | Accepts one AB-contract event while hardware mode is disabled |
| `POST` | `/api/save` | Backward-compatible local bundle save |
| `POST` | `/api/reset` | Clears temporary audio/session data without deleting saved works |
| `GET` | `/audio/original.wav` | Current temporary input when present |
| `GET` | `/audio/output.wav` | Optional backend-produced temporary output when present |
| `WS` | `/ws/ring` | Status plus P0 event broadcast and validated inbound motion adapter |

The upload body content type may be `audio/wav`, `audio/x-wav`, or `application/octet-stream`; maximum size is 50 MiB. The backend writes a same-directory temporary file, validates it through libsndfile, flushes it, and uses `os.replace`. A successful response includes `session_id`, filename, byte size, SHA-256 `audio_id`, sample rate, channels, subtype, and `expectedFormat`. The ring target is 16 kHz, mono, PCM-16; valid alternatives remain accepted so stereo-to-mono and decoded ring compatibility work.

Every successful new upload clears transcript, emotion, confidence, reason, mode, recipe, motion, saved ID, output URL, and old error before feature analysis. The resulting features are tagged with their SHA-256 audio owner and reused during transcription instead of running the same analysis twice. `POST /api/stt/transcribe` accepts an optional `X-SoundClay-Audio-Id` header; a mismatch returns `409` before provider invocation. Its response includes transcript, emotion, confidence, reason, features, phase, provider, timing, and ownership metadata.

The local fusion classifier uses weighted Mandarin/English phrases, phrase specificity, negation, intensifiers/diminishers, contrast-clause emphasis, recency, mixed-evidence detection, and the current normalized `volume`, `pitch`, and `brightness`. Text remains the stronger signal; acoustic evidence helps when words are short or ambiguous. Silence does not create an acoustic label. It classifies only the emotion expressed by speech and is not a diagnosis.

With `EMOTION_PROVIDER=hybrid` and a non-empty `EMOTION_API_KEY`, the adapter sends the transcript, all three normalized features, and local evidence to `GLM-5.2` through `${EMOTION_BASE_URL}/chat/completions`. GLM must return probabilities for all five public emotions rather than only a winning label. The server validates and normalizes those probabilities, then deterministically fuses text, acoustic, and GLM evidence. The base weighting is 45% text, 20% acoustics, and 35% GLM; weak or silent acoustic evidence automatically receives less weight, and weak text gives GLM slightly more weight. Close scores or unresolved local/GLM disagreement resolve to `neutral_mixed` instead of an unstable forced label.

The interactive decision deadline defaults to 1.5 seconds. If GLM is not ready by then, the already-computed local result is returned and cannot later overwrite the session. Successful remote decisions are cached in memory by transcript, features, endpoint, model, and fusion version. Three consecutive remote failures open a 30-second circuit breaker, keeping subsequent requests fast while the provider is unavailable. Malformed JSON, missing scores, invalid numbers, HTTP errors, and timeouts all fall back locally without breaking the flow. `emotion_provider`, `emotion_warning`, `emotion_scores`, `emotion_weights`, and `emotion_cache_hit` are additive session diagnostics. No key is logged or returned. Enabling GLM transmits the transcript and three feature numbers to the configured provider; use `EMOTION_PROVIDER=local` when fully offline/private operation is required.

All WebSocket events use this additive, backward-compatible envelope:

```json
{
  "type": "twist",
  "timestamp": 1720000000000,
  "payload": {
    "session_id": "session-uuid",
    "audio_id": "sha256-or-null",
    "revision": 12,
    "value": 0.65
  }
}
```

Supported event types are `status`, `recording`, `audio_ready`, `transcript_ready`, `audio_features_ready`, `emotion_ready`, `material_ready`, `twist`, `tiltX`, `burst`, `freeze`, `color`, `saved`, and `error`. Inbound `imu/twist`, `imu/tiltX`, `imu/burst`, and `imu/freeze` are accepted as Member B aliases; legacy `finger` remains accepted as a size-control alias and `ui/color` remains accepted for color clients. Inbound JSON, identifiers, timestamps, and numbers are validated; normalized events are stored in a bounded 500-item trace and rebroadcast. No decoding or model inference occurs in the motion loop.

## AB RingRuntime integration

FastAPI owns exactly one optional `RingRuntime` for the process lifetime. Startup calls `connect()` and `get_status()`. A ring session calls `arm_recording(session_id)`, `enter_motion_mode(session_id)`, then `sculpt_until_freeze(session_id)` in sequence. Shutdown cancels an unfinished session before calling `runtime.close()`.

The adapter accepts AB's `status`, `audio_ready`, `imu`, `burst`, `freeze`, and `error` events. Both `sessionId` and legacy `session_id` are accepted at ingress, then normalized to AB's 1-80 character identifier contract. Real status fields including `ringConnected`, `firmwareVersion`, `batteryPercent`, sensor ranges, reconnect attempts, and phase messages are preserved. Motion is isolated to the active AB session. `imu.twist` and `imu.tiltX` remain signed in `[-1, 1]`; only the Ableton adapter converts them to the existing timbre and three-level gain mappings. Repeated or out-of-order IMU sequences, repeated bursts, and repeated freezes are idempotently ignored.

`audio_ready.wavPath` must be an absolute existing local WAV path below the 50 MiB limit. The backend reads and validates it without moving or deleting AB's source file, atomically stores its own current WAV, computes real features, and launches local STT/emotion work outside the live motion loop. On Windows, the manager also resolves `%LOCALAPPDATA%\Programs\ffmpeg\bin\ffmpeg.exe` when the current process has not yet inherited an updated user `PATH`.

Hardware mode is deliberately disabled by default. To run the no-ring acceptance test, start FastAPI and replay the checked-in AB-shaped sample:

```powershell
.venv311\Scripts\python backend\replay_ring_events.py backend\samples\mock_motion.ndjson --speed 10
```

The sample contains signed IMU input plus duplicate `burst` and `freeze` records. The first discrete event is accepted and its duplicate returns `duplicate_or_out_of_order`. The frontend connects to `ws://127.0.0.1:8000/ws/ring`, shows connection/phase status, maps signed twist to particle/audio sculpting, triggers burst once, and makes freeze stop further editing.

Only after mock acceptance should hardware mode be enabled in `backend/.env`:

```dotenv
SOUNDCLAY_RING_ENABLED=true
```

Before real-ring acceptance, close the phone Zilo APK, phone Bluetooth, and any other BLE program, then start exactly one FastAPI/Python process. The A/B runtime is bundled in this repository; only the physical ring and Windows BLE stack remain external hardware dependencies.

## Audio analysis and recipe contracts

`volume`, `pitch`, and `brightness` are finite floats in `[0,1]`. Volume is normalized RMS across the mono signal. Pitch uses a bounded center window and FFT autocorrelation, avoiding quadratic work on long files. Brightness uses spectral centroid on the bounded window. Stereo channels are averaged; empty, silent, non-finite, and very short audio has safe zero fallbacks. Blocking soundfile/NumPy work and the optional GLM HTTP request run outside the async event loop.

Recipes contain:

```json
{
  "voiceFx": {
    "playbackRate": 1.0,
    "lowpassHz": 4200,
    "distortion": 0.1,
    "reverb": 0.4,
    "gain": 1.0
  },
  "soundscape": {
    "stemId": "neutral_air_01",
    "emotionStemId": "emotion_neutral_mixed",
    "pulseRate": 0.45,
    "stemGain": 0.26
  },
  "audioBed": {
    "stemId": "neutral_air_01",
    "emotionStemId": "emotion_neutral_mixed",
    "pulseRate": 0.45,
    "stemGain": 0.26
  },
  "visual": {
    "sharpness": 0.35,
    "density": 0.5,
    "breathing": 0.48,
    "motion": "floating"
  }
}
```

`soundscape` is preserved; `audioBed` is the taskbook-compatible additive alias. Pydantic validates finite bounded values. Express and Soothe use the same deterministic emotion matrix but produce different audio and visual parameters.

## Direct-mode frontend workflow

1. The entry screen immediately accepts a left/right swipe, pointer drag, button click, or keyboard arrow. It performs no audio upload, STT, or emotion call.
2. Left/Rhythm and Right/Soothe both call the backward-compatible `POST /api/mode/select`. Rhythm maps internally to the stable `express` value; Soothe uses `soothe`. They display the same particle instrument and try to loop `frontend/public/audio/modes/rhythm.wav` or `soothe.wav`. Browser audio unlock occurs inside the selection gesture. If a file is missing, visuals and Ableton controls remain usable and a non-blocking status explains where to add it.
3. One click arms/disarms pointer-based wrist simulation in either mode. Horizontal rotation updates particle twist, Web Audio low-pass cutoff, distortion, and playback rate together. Real `twist` WebSocket events use the same adapter.
4. A fast fling emits `burst`; particles expand and decay, audio receives a short gain/filter/distortion impulse, and both return to the current stable recipe after 620 ms.
5. Returning to direction selection stops the current loop. Entering the other mode resets twist state, loads that mode's distinct recipe and loop, and ignores a late audio response from the previous selection.

## Completion cover and sharing

The editing page exposes one primary `完成` action. It stores the current mode title, audio buffer reference, duration, direction rotation, twist, visual mode, space, and energy in the local `currentWork` object, then transitions `editing → finishing → completed`. The existing Three.js instance is retained throughout.

`setPresentationMode()` changes targets inside the existing particle render loop. Finishing/completed states interpolate motion to `0.08`, audio response to `0`, distortion to `0.12`, breathing to `0.08`, and swing to `0.03`; playback restores them to `1`. No particle geometry, render loop, or AudioContext is recreated.

After the cover settles, one 1.1-second timer attempts a single non-looping playback if the user has not selected an action. Browser autoplay rejection is silent. The playback button uses the same decoded buffer and audio graph, prevents parallel sources, starts manual playback from the beginning, and preserves position when paused. Natural completion returns to the quiet cover state.

The completed page displays only the work title and play/share/continue-editing icons. Share opens one bottom sheet containing Video, Audio, Share Link, and Cancel. Video export remains an explicit placeholder. Audio uses a real processed WAV with system file sharing when supported and a user-triggered download fallback otherwise. A link is shared only when a real `currentWork.shareUrl` exists; no localhost or fake link is generated. Continue Editing restores the saved particle parameters and loop without reloading the page or creating new renderer/audio instances.

## Ableton Live bridge

`backend/ableton_adapter.py` preserves the optional dependency-free OSC/UDP bridge and also drives the MIDI mappings already saved in `C:\Users\19662\Desktop\SoundClay_Final.als\soundclay.als`. Both transports are disabled by default, so Ableton being closed can never break the browser flow.

For the existing Ableton Set, start loopMIDI with the `SoundClay MIDI` port, open the Set, and enable **Remote** for its input in Live's Link, Tempo & MIDI settings. Then put this in `backend/.env` and restart FastAPI:

```dotenv
ABLETON_MIDI_ENABLED=true
ABLETON_MIDI_PORT=SoundClay MIDI
ABLETON_MIDI_CHANNEL=0
ABLETON_MIDI_GAIN_FLOOR=0.4
ABLETON_MIDI_MAX_HZ=50
```

The checked Ableton Set contains these mappings; the backend reuses them exactly:

| Ring/product event | MIDI message (channel 1) | Existing Ableton target |
| --- | --- | --- |
| signed `twist` mapped to `0..127` | CC 20 | `Timbre Wheel` Chain Selector |
| `accelMag`, with a safe 40% floor | CC 21 | Main Gain |
| Joy Express / Soothe | Note 60 / 61 | Scene launch |
| Anger Express / Soothe | Note 62 / 63 | Scene launch |
| Sadness Express / Soothe | Note 64 / 65 | Scene launch |
| Anxiety Express / Soothe | Note 66 / 67 | Scene launch |
| Mixed Express / Soothe | Note 68 / 69 | Scene launch |
| `burst` with strength as velocity | Note 70 | `10_Drum_Layer` clip |

`freeze` and `color` have no saved MIDI assignment in this Set, so they continue through OSC only. This avoids silently inventing a second mapping.

`POST /api/ableton/stop` sends a MIDI Clock Stop message (and the existing OSC freeze signal). The frontend calls it when **凝固作品** is selected. In Live's Link, Tempo & MIDI settings, enable **Sync** for the `SoundClay MIDI` input so Live accepts the incoming transport stop; keep Sync disabled on the matching output to avoid a feedback loop.

To enable the optional OSC path as well, use:

```dotenv
ABLETON_OSC_ENABLED=true
ABLETON_OSC_HOST=127.0.0.1
ABLETON_OSC_PORT=11000
```

In Max for Live, use this receiving chain:

```text
[udpreceive 11000]
        |
    [oscparse]
        |
[route soundclay]
        |
[route twist filter burst freeze color mode]
```

The bridge sends:

| OSC address | Value | Suggested Ableton mapping |
| --- | --- | --- |
| `/soundclay/mode` | `soothe` or `express` string (`express` = product-facing Rhythm) | Rack/scene selection |
| `/soundclay/twist` | normalized float `0..1` | Macro control |
| `/soundclay/filter` | cutoff in Hz `700..16000` | Auto Filter frequency |
| `/soundclay/burst` | normalized float `0..1` | Envelope/transient trigger |
| `/soundclay/freeze` | integer `0/1` | Freeze/hold device |
| `/soundclay/color` | normalized hue `0..1` | Timbre, send, or spectral macro |

`GET /api/ableton/status` exposes the OSC addresses plus resolved MIDI port, channel, saved CC/Note map, connection state, available outputs, and last error. Mode selection launches the matching emotion/mode scene; real ring IMU drives CC20/CC21; burst triggers Note 70. Existing twist/burst/freeze mock and ring events continue to forward to OSC when enabled.

## Legacy single-screen workflow

The previous product experience followed `网页产品设计.docx`: one full-screen particle stage, four continuous phases, no page navigation, and only the currently relevant control visible. It remains documented here only for backward-compatible testing.

1. **声音** — tap the central microphone to record. `BrowserWavRecorder` captures mono samples, resamples to 16 kHz, encodes PCM-16 RIFF/WAVE, uploads, and starts local transcription automatically. WAV upload and a Chinese mock transcript remain available as quiet fallbacks.
2. **理解** — Understanding always exits in `finally`. The transcript response is applied first and then completely replaced by `GET /api/session/current`. Local expressed-emotion classification is automatically accepted for this product flow, so no emotion-review page appears; the detected value and rationale remain visible in diagnostics.
3. **方向** — the `律动 ↔ 舒缓` rail fetches two non-mutating preview recipes and continuously interpolates their numeric Web Audio and visual parameters. One second of rest or a tap on the clay confirms the nearest canonical backend mode.
4. **塑形** — the voice loops automatically when audio exists. Canvas drag gives immediate local space/energy/twist feedback while sampled twist events are traced by the backend. A tap creates a burst/timeline marker; press-and-hold freezes audio and particles, and release resumes them. Visible fallback controls keep the flow usable without a ring.
5. **完成** — Done captures the live canvas, tries an offline processed WAV export, and saves the local Voice Portrait bundle. The final cover exposes only play, share, and restart. The share icon opens local/native sharing choices rather than permanently showing download controls.

Backend/WebSocket status, transcript, emotion rationale, normalized features, recipe, motion trace, save result, endpoints, recovery actions, and event log remain available in the top-right diagnostics drawer without competing with the default instrument interface.

API and WebSocket URLs are centralized in `frontend/src/api.js`. Each input operation has a generation and current audio identifier. Late HTTP responses and WebSocket events with an older generation, session ID, audio ID, or revision are ignored. Duplicate transcription clicks are blocked. Successful health/upload/transcription clears stale errors. Request timeouts show executable retry guidance.

`frontend/src/audio.js` supplies non-artistic Web Audio plumbing: user-interaction unlock, WAV decode, filter/distortion/reverb/gain recipe application, loop-safe one-source lifecycle, live recipe parameter updates, suspend/resume freeze, emotion-first stem lookup, and offline PCM-16 export. Put the five final loops in `frontend/public/audio/emotions/` as `joy.wav`, `anger.wav`, `sadness.wav`, `anxiety.wav`, and `neutral_mixed.wav`. `VITE_EMOTION_AUDIO_BASE` can relocate that directory. Missing artistic stems do not stop original-voice playback.

`frontend/src/clay-visual.js` is the lightweight default renderer. It maps recipe sharpness/density/breathing, real volume/pitch/brightness, the continuous direction, twist, burst, freeze, pointer speed, and x/y movement to the central particle clay. `frontend/src/visual-adapter.js` still emits the stable material/motion events and legacy rotate/swipe/hold mappings, so the preserved Three.js/kaleidoscope renderer can be substituted later without changing the API flow.

## Save and privacy

The request remains backward compatible:

```json
{
  "screenshot_data_url": "data:image/png;base64,...",
  "processed_audio_data_url": "data:audio/wav;base64,...",
  "final_motion": {"twist": 0.65, "burstCount": 1, "frozen": true}
}
```

PNG is limited to 5 MiB decoded; processed RIFF/WAVE is limited to 25 MiB. MIME prefixes, strict base64, signatures, finite motion numbers, and sizes are validated before allocating the final work directory. IDs combine UTC time and random data; directory creation is exclusive.

```text
works/<unique-work-id>/
|-- original.wav     # when current input exists
|-- output.wav       # when processed/backend output exists
|-- sculpture.png    # when a screenshot exists
|-- portrait.json    # private local backward-compatible full metadata
`-- metadata.json    # public-card projection without transcript
```

`portrait.json` stores the local transcript, session/audio IDs, timestamps, confirmed emotion, mode, features, recipe, and motion trace. `metadata.json` deliberately omits transcript and reason. There is no account, database, gallery, or community upload.

## Mock smoke flow

With `STT_PROVIDER=mock`:

1. Start both servers and verify `/health` plus WebSocket status.
2. Upload any valid short WAV and transcribe, or submit a mock transcript.
3. Confirm/correct the emotion.
4. Generate Express, then Soothe, and verify the recipes differ.
5. Emit twist, burst, and freeze.
6. Save and verify a unique work directory.
7. Reset and verify temporary audio/session fields clear while the work remains.

Newest-audio regression: upload A, transcribe A, upload B, verify A's transcript/recipe/motion disappear, transcribe B, and verify the UI exits Understanding and `/api/session/current.audio_id` equals B's upload SHA-256.

## Preserved advanced renderer and remaining dependencies

The approved Member D page structure, typography, interaction hierarchy, responsive layout, Canvas particle behavior, state transitions, screenshot composition, local audio loop, direction morphing, share menu, and recovery/diagnostics flow are implemented in the default `integration-main.js` experience. The prior experimental renderer remains preserved in `frontend/src/main.js`, `frontend/src/style.css`, `frontend/src/sculpture.js`, `frontend/src/kaleido-theme.js`, and visual assets; none is imported by the default lightweight page.

- Member A: provide Zilo ring audio capture/transfer, exact decoded audio contract, sample/channel timing, and reconnect behavior.
- Member B: provide real IMU calibration/gesture recognition and feed the validated twist/burst/freeze envelope. The adapter and mocks are ready; no gesture model is implemented here.
- Member D: optional future artistic work is limited to supplying final stem assets/mixes or deliberately replacing the lightweight Canvas renderer with the preserved Three.js renderer. These assets are not required for the complete P0 mock/WAV flow.

## Validation

From the repository root:

```powershell
python -m compileall backend
python -m pytest -q -p no:cacheprovider --basetemp=.pytest-tmp
cd frontend
npm.cmd test
npm.cmd run build
node --check src/integration-main.js
```

Also run `node --check` for every changed frontend JavaScript file and `git diff --check`. Tests use a repository-local base temp, write no permanent work data, use no ring or internet, and mock all model calls.
