from __future__ import annotations

import asyncio
import io
import time
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import emotion_adapter
import server
from event_bus import EventBus
from event_contract import EventPublisher
from ring_integration import RingRuntimeManager, resolve_ring_ffmpeg_path
from ring_protocol import RingEventGuard, RingProtocolError, normalize_ring_event
from ring_config import RingConfig
from ring_recording_service import AudioReady, RingRecordingService
from ring_runtime import RingRuntime
from schemas import SessionState


def _wav_bytes() -> bytes:
    sample_rate = 16_000
    times = np.arange(sample_rate // 4, dtype=np.float32) / sample_rate
    audio = 0.18 * np.sin(2 * np.pi * 220 * times)
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@pytest.fixture
def ring_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    audio_dir = tmp_path / "audio"
    works_dir = tmp_path / "works"
    audio_dir.mkdir()
    works_dir.mkdir()
    monkeypatch.setattr(server, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(server, "WORKS_DIR", works_dir)
    monkeypatch.setattr(server, "ORIGINAL_AUDIO", audio_dir / "original.wav")
    monkeypatch.setattr(server, "OUTPUT_AUDIO", audio_dir / "output.wav")
    monkeypatch.setenv("SOUNDCLAY_RING_ENABLED", "false")
    monkeypatch.setenv("EMOTION_PROVIDER", "local")
    monkeypatch.setenv("STT_PROVIDER", "mock")
    monkeypatch.setenv("MOCK_TRANSCRIPT", "今天我很开心")
    emotion_adapter._reset_runtime_state()
    server.session = SessionState(session_id="backend-test-session")
    server.bus = EventBus()
    server.audio_lock = asyncio.Lock()
    server.active_ring_session_id = None
    server.ring_event_guard.reset()
    server.ring_status.clear()
    server.ring_status.update(
        {
            "enabled": False,
            "connected": False,
            "phase": "disabled",
            "modeHint": "mock-controls-available",
            "lastError": None,
        }
    )
    with TestClient(server.app) as test_client:
        yield test_client, tmp_path


def test_protocol_preserves_signed_twist_and_accepts_session_alias() -> None:
    message = normalize_ring_event(
        {
            "type": "imu",
            "timestamp": 1720000000000,
            "payload": {
                "session_id": "SC-001",
                "sequence": 0,
                "twist": -0.72,
                "tiltX": 0.63,
                "accelMag": 0.18,
                "gyroZ": -92.4,
                "linearAccelX": 0.21,
                "burstState": "armed",
                "burstArmed": True,
            },
        }
    )
    assert message["payload"]["sessionId"] == "SC-001"
    assert message["payload"]["twist"] == pytest.approx(-0.72)
    assert message["payload"]["tiltX"] == pytest.approx(0.63)
    assert message["payload"]["gyroZ"] == pytest.approx(-92.4)
    assert message["payload"]["linearAccelX"] == pytest.approx(0.21)
    assert message["payload"]["burstState"] == "armed"
    assert message["payload"]["burstArmed"] is True


def test_protocol_accepts_real_ab_status_and_preserves_diagnostics() -> None:
    message = normalize_ring_event(
        {
            "type": "status",
            "timestamp": 1720000000000,
            "payload": {
                "sessionId": "SC-001",
                "ringConnected": True,
                "phase": "sculpting",
                "modeHint": "gesture_verified",
                "firmwareVersion": "0.3.4",
                "batteryPercent": 82,
                "batteryCharging": False,
                "sampleRateHz": 100,
                "accelRangeG": 16,
                "gyroRangeDps": 2000,
            },
        }
    )
    payload = message["payload"]
    assert payload["ringConnected"] is True
    assert payload["connected"] is True
    assert payload["firmwareVersion"] == "0.3.4"
    assert payload["batteryPercent"] == pytest.approx(82)
    assert payload["sampleRateHz"] == 100


def test_protocol_rejects_session_ids_outside_ab_contract() -> None:
    with pytest.raises(RingProtocolError, match="1-80 characters"):
        normalize_ring_event(
            {
                "type": "imu",
                "timestamp": 1,
                "payload": {"sessionId": "SC invalid", "twist": 0.1},
            }
        )


def test_protocol_rejects_nonfinite_motion() -> None:
    with pytest.raises(RingProtocolError, match="finite"):
        normalize_ring_event(
            {
                "type": "imu",
                "timestamp": 1,
                "payload": {"sessionId": "SC-001", "twist": float("nan")},
            }
        )


def test_protocol_accepts_signed_finger_motion_and_session_alias() -> None:
    message = normalize_ring_event(
        {
            "type": "finger",
            "timestamp": 2,
            "payload": {"session_id": "SC-001", "sequence": 10, "value": -1.8},
        }
    )
    assert message["payload"] == {
        "sessionId": "SC-001",
        "value": -1.0,
        "sequence": 10,
    }

    tilt = normalize_ring_event(
        {
            "type": "tiltX",
            "timestamp": 3,
            "payload": {"sessionId": "SC-001", "sequence": 11, "value": 1.8},
        }
    )
    assert tilt["payload"]["value"] == 1.0


def test_runtime_manager_can_load_bundled_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOUNDCLAY_RING_PATH", raising=False)
    manager = RingRuntimeManager(lambda event: asyncio.sleep(0), enabled=False)
    factory = manager._load_runtime_factory()
    assert factory.__name__ == "RingRuntime"
    assert factory.__module__ == "ring_runtime"


def test_event_guard_deduplicates_sequences_bursts_and_freezes() -> None:
    guard = RingEventGuard()
    imu = normalize_ring_event(
        {
            "type": "imu",
            "timestamp": 1,
            "payload": {"sessionId": "SC-001", "sequence": 10, "twist": 0.2},
        }
    )
    assert guard.accept(imu) is True
    assert guard.accept(imu) is False

    burst = normalize_ring_event(
        {
            "type": "burst",
            "timestamp": 2,
            "payload": {"sessionId": "SC-001", "sequence": 11, "strength": 0.8},
        }
    )
    assert guard.accept(burst) is True
    assert guard.accept(burst) is False

    freeze = normalize_ring_event(
        {"type": "freeze", "timestamp": 3, "payload": {"sessionId": "SC-001"}}
    )
    assert guard.accept(freeze) is True
    assert guard.accept(freeze) is False


def test_runtime_manager_owns_one_runtime_and_closes_cleanly() -> None:
    calls: list[object] = []

    class FakeRuntime:
        def __init__(self, event_sink):
            self.event_sink = event_sink
            calls.append("init")

        async def connect(self):
            calls.append("connect")

        async def get_status(self):
            calls.append("status")

        async def arm_recording(self, session_id):
            calls.append(("arm", session_id))

        async def enter_motion_mode(self, session_id):
            calls.append(("motion", session_id))

        async def sculpt_until_freeze(self, session_id):
            calls.append(("freeze", session_id))

        async def close(self):
            calls.append("close")

    async def scenario() -> None:
        manager = RingRuntimeManager(
            lambda event: asyncio.sleep(0), enabled=True, runtime_factory=FakeRuntime
        )
        await manager.start()
        await manager.begin_session("SC-001")
        assert manager.session_task is not None
        await manager.session_task
        await manager.close()

    asyncio.run(scenario())
    assert calls == [
        "init",
        "connect",
        "status",
        ("arm", "SC-001"),
        ("motion", "SC-001"),
        ("freeze", "SC-001"),
        "close",
    ]


def test_runtime_monitor_reconnects_when_ring_returns_to_advertising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DisconnectedClient:
        is_connected = False

    runtime = object.__new__(RingRuntime)
    runtime._closing = False
    runtime.client = DisconnectedClient()
    runtime.phase = "connected"
    runtime.mode_hint = "unknown"
    runtime.publisher = AsyncMock()
    runtime.reconnect = AsyncMock()
    monkeypatch.setattr("ring_runtime.asyncio.sleep", AsyncMock())

    asyncio.run(runtime._monitor_connection())

    runtime.reconnect.assert_awaited_once()
    assert runtime.publisher.emit.await_args_list[0].args[0] == "error"
    assert runtime.publisher.emit.await_args_list[0].args[1]["code"] == "BLE_DISCONNECTED"


def test_recording_ignores_auto_audio_queued_before_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ConnectedClient:
        is_connected = True

    async def scenario() -> None:
        publisher = EventPublisher(tmp_path)
        service = RingRecordingService(
            ConnectedClient(),
            RingConfig(session_root=tmp_path, recording_timeout_s=5),
            publisher,
            asyncio.Lock(),
        )
        monkeypatch.setattr(
            "ring_recording_service.sdk.get_audio_file_count",
            AsyncMock(return_value=91),
        )
        receive = AsyncMock(side_effect=[(90, b"stale"), (91, b"new")])
        monkeypatch.setattr(
            "ring_recording_service.sdk.receive_auto_audio_file", receive
        )
        ready = AudioReady(
            session_id="fresh-session",
            file_index=91,
            raw_path=tmp_path / "ring_raw.bin",
            wav_path=tmp_path / "original.wav",
            duration_ms=3200,
            record_time=1,
            recovered=False,
        )
        save = AsyncMock(return_value=ready)
        monkeypatch.setattr(service, "_save_and_validate", save)

        try:
            result = await service.arm_recording("fresh-session")
        finally:
            await publisher.close()

        assert result == ready
        assert receive.await_count == 2
        assert save.await_args.kwargs["file_index"] == 91
        assert save.await_args.kwargs["raw_audio"] == b"new"

    asyncio.run(scenario())


def test_ffmpeg_resolution_handles_stale_windows_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ffmpeg = tmp_path / "Programs" / "ffmpeg" / "bin" / "ffmpeg.exe"
    ffmpeg.parent.mkdir(parents=True)
    ffmpeg.write_bytes(b"stub")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("SOUNDCLAY_FFMPEG", "ffmpeg")
    monkeypatch.setattr("ring_integration.shutil.which", lambda _: None)
    assert resolve_ring_ffmpeg_path() == str(ffmpeg.resolve())


def test_mock_ring_motion_is_session_scoped_signed_and_idempotent(
    ring_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_client, _ = ring_client
    ableton_events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        server,
        "send_ableton_motion",
        lambda kind, payload: ableton_events.append((kind, payload)),
    )
    status = {
        "type": "status",
        "timestamp": 1000,
        "payload": {"sessionId": "SC-001", "phase": "connected", "connected": True},
    }
    assert test_client.post("/api/mock/ring-event", json=status).json()["accepted"] is True

    imu = {
        "type": "imu",
        "timestamp": 1100,
        "payload": {
            "sessionId": "SC-001",
            "sequence": 1,
            "twist": -0.8,
            "tiltX": 0.76,
            "accelMag": 0.3,
            "gyroZ": -40,
        },
    }
    assert test_client.post("/api/mock/ring-event", json=imu).json()["accepted"] is True
    duplicate = test_client.post("/api/mock/ring-event", json=imu).json()
    assert duplicate == {
        "accepted": False,
        "reason": "duplicate_or_out_of_order",
        "event": normalize_ring_event(imu),
    }
    assert server.session.motion["twist"] == pytest.approx(-0.8)
    assert server.session.motion["tiltX"] == pytest.approx(0.76)
    assert server.session.motion["size"] == pytest.approx(0.76)
    assert ableton_events[:2] == [
        ("twist", {"value": pytest.approx(0.1)}),
        ("finger", {"value": pytest.approx(0.76)}),
    ]

    freeze = {
        "type": "freeze",
        "timestamp": 1200,
        "payload": {"sessionId": "SC-001", "sequence": 2, "source": "key_double_press"},
    }
    assert test_client.post("/api/mock/ring-event", json=freeze).json()["accepted"] is True
    assert test_client.post("/api/mock/ring-event", json=freeze).json()["accepted"] is False

    wrong_session = {**imu, "timestamp": 1300, "payload": {**imu["payload"], "sessionId": "SC-OLD", "sequence": 2}}
    response = test_client.post("/api/mock/ring-event", json=wrong_session)
    assert response.status_code == 422
    assert "different active session" in response.json()["detail"]


def test_ring_audio_ready_reads_without_moving_and_starts_local_pipeline(ring_client) -> None:
    test_client, tmp_path = ring_client
    source = tmp_path / "ring-runtime" / "capture.wav"
    source.parent.mkdir()
    original_bytes = _wav_bytes()
    source.write_bytes(original_bytes)
    event = {
        "type": "audio_ready",
        "timestamp": 2000,
        "payload": {"sessionId": "SC-AUDIO", "wavPath": str(source.resolve())},
    }
    response = test_client.post("/api/mock/ring-event", json=event)
    assert response.status_code == 200
    assert response.json()["accepted"] is True
    assert source.read_bytes() == original_bytes
    assert server.ORIGINAL_AUDIO.read_bytes() == original_bytes

    deadline = time.monotonic() + 2
    while server.session.transcript is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.session.transcript == "今天我很开心"
    assert server.session.emotion is not None


def test_real_ring_waits_for_local_pipeline_before_motion_can_start(
    ring_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, tmp_path = ring_client
    source = tmp_path / "ring-runtime" / "capture.wav"
    source.parent.mkdir()
    source.write_bytes(_wav_bytes())
    pipeline = AsyncMock()
    monkeypatch.setattr(server, "_run_ring_audio_pipeline", pipeline)

    result = asyncio.run(
        server._ingest_ring_event(
            {
                "type": "audio_ready",
                "timestamp": 2100,
                "payload": {
                    "sessionId": "SC-REAL-AUDIO",
                    "wavPath": str(source.resolve()),
                },
            },
            source="ring_runtime",
        )
    )

    assert result["accepted"] is True
    pipeline.assert_awaited_once_with(server.session.audio_id)


def test_ring_status_is_disabled_by_default_and_session_route_is_recoverable(ring_client) -> None:
    test_client, _ = ring_client
    status = test_client.get("/api/ring/status")
    assert status.status_code == 200
    assert status.json()["enabled"] is False
    start = test_client.post("/api/ring/session/start")
    assert start.status_code == 409
    assert "disabled" in start.json()["detail"]


def test_real_runtime_status_updates_manager_connection_state(ring_client) -> None:
    _, _ = ring_client
    manager = server.ring_manager
    assert manager is not None
    asyncio.run(
        server._ingest_ring_event(
            {
                "type": "status",
                "timestamp": 3000,
                "payload": {
                    "ringConnected": True,
                    "phase": "sculpting",
                    "modeHint": "gesture_verified",
                },
            },
            source="ring_runtime",
        )
    )
    assert manager.connected is True

    asyncio.run(
        server._ingest_ring_event(
            {
                "type": "error",
                "timestamp": 3100,
                "payload": {
                    "code": "BLE_DISCONNECTED",
                    "phase": "connection",
                    "message": "ring disconnected",
                    "recoverable": True,
                },
            },
            source="ring_runtime",
        )
    )
    assert manager.connected is False
    assert server.ring_status["ringConnected"] is False
