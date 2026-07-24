from __future__ import annotations

import asyncio
import io
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import emotion_adapter
import server
from event_bus import EventBus
from ring_integration import RingRuntimeManager, resolve_ring_ffmpeg_path
from ring_protocol import RingEventGuard, RingProtocolError, normalize_ring_event
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
                "sequence": 9,
                "twist": -0.72,
                "accelMag": 0.18,
                "gyroZ": -92.4,
            },
        }
    )
    assert message["payload"]["sessionId"] == "SC-001"
    assert message["payload"]["twist"] == pytest.approx(-0.72)
    assert message["payload"]["gyroZ"] == pytest.approx(-92.4)


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


def test_mock_ring_motion_is_session_scoped_signed_and_idempotent(ring_client) -> None:
    test_client, _ = ring_client
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
