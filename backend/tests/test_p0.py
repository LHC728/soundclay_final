from __future__ import annotations

import base64
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from fastapi import HTTPException

import server
from audio_pipeline import analyze_audio
from emotion_analyzer import analyze_emotion_local
from event_bus import EventBus
from recipe_engine import build_recipe
from schemas import Emotion, Mode, SessionState


def wav_bytes(*, frequency: float = 220.0, amplitude: float = 0.25, stereo: bool = False) -> bytes:
    sample_rate = 16_000
    times = np.arange(sample_rate, dtype=np.float32) / sample_rate
    audio = amplitude * np.sin(2 * np.pi * frequency * times)
    if stereo:
        audio = np.column_stack((audio, audio * 0.5))
    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    audio_dir = tmp_path / "audio"
    works_dir = tmp_path / "works"
    audio_dir.mkdir()
    works_dir.mkdir()
    monkeypatch.setattr(server, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(server, "WORKS_DIR", works_dir)
    monkeypatch.setattr(server, "ORIGINAL_AUDIO", audio_dir / "original.wav")
    monkeypatch.setattr(server, "OUTPUT_AUDIO", audio_dir / "output.wav")
    server.session = SessionState(session_id="test-session")
    server.bus = EventBus()
    with TestClient(server.app) as test_client:
        yield test_client, audio_dir, works_dir


def complete_mock_flow(test_client: TestClient) -> None:
    response = test_client.post(
        "/api/mock/transcript", json={"transcript": "I am frustrated and angry"}
    )
    assert response.status_code == 200
    assert test_client.post("/api/emotion/confirm", json={"emotion": "anger"}).status_code == 200
    assert test_client.post("/api/mode/select", json={"mode": "express"}).status_code == 200


def test_health(client) -> None:
    test_client, _, _ = client
    assert test_client.get("/health").json() == {"ok": True}


def test_local_emotion_analysis() -> None:
    result = analyze_emotion_local("I feel nervous and worried about tomorrow")
    assert result.emotion == Emotion.ANXIETY
    assert 0.0 <= result.confidence <= 1.0
    assert analyze_emotion_local("A plain factual sentence").emotion == Emotion.NEUTRAL_MIXED


def test_express_and_soothe_recipes_differ() -> None:
    express = build_recipe(Emotion.ANGER, Mode.EXPRESS)
    soothe = build_recipe(Emotion.ANGER, Mode.SOOTHE)
    assert express != soothe
    assert express["voiceFx"]["distortion"] > soothe["voiceFx"]["distortion"]
    assert soothe["visual"]["motion"] == "settling"


def test_audio_features_are_finite_and_normalized(tmp_path: Path) -> None:
    path = tmp_path / "tone.wav"
    path.write_bytes(wav_bytes(stereo=True))
    features = analyze_audio(path)
    values = features.model_dump().values()
    assert all(np.isfinite(value) and 0.0 <= value <= 1.0 for value in values)
    assert features.volume > 0
    assert features.pitch > 0
    assert features.brightness > 0


def test_silence_audio_fallback(tmp_path: Path) -> None:
    path = tmp_path / "silence.wav"
    sf.write(path, np.zeros(80, dtype=np.float32), 16_000)
    assert analyze_audio(path).model_dump() == {
        "volume": 0.0,
        "pitch": 0.0,
        "brightness": 0.0,
    }


def test_upload_analyze_and_transcribe_without_loading_whisper(client, monkeypatch) -> None:
    test_client, _, _ = client
    upload = test_client.post(
        "/api/audio/upload", content=wav_bytes(), headers={"content-type": "audio/wav"}
    )
    assert upload.status_code == 200
    assert all(0.0 <= value <= 1.0 for value in upload.json()["features"].values())
    assert test_client.post("/api/audio/analyze").status_code == 200

    mocked_transcribe = AsyncMock(return_value="I am happy and excited")
    monkeypatch.setattr(server, "transcribe_audio", mocked_transcribe)
    response = test_client.post("/api/stt/transcribe")
    assert response.status_code == 200
    assert response.json()["transcript"] == "I am happy and excited"
    assert response.json()["emotion"] == "joy"
    mocked_transcribe.assert_awaited_once()


def test_feature_failure_preserves_valid_transcript(client, monkeypatch) -> None:
    test_client, audio_dir, _ = client
    (audio_dir / "original.wav").write_bytes(wav_bytes())
    monkeypatch.setattr(
        server, "transcribe_audio", AsyncMock(return_value="I am happy today")
    )
    monkeypatch.setattr(
        server,
        "_analyze_current_audio",
        AsyncMock(side_effect=HTTPException(status_code=422, detail="bad features")),
    )

    response = test_client.post("/api/stt/transcribe")
    assert response.status_code == 200
    assert response.json()["transcript"] == "I am happy today"
    assert response.json()["featureError"] == "bad features"
    assert server.session.transcript == "I am happy today"
    assert server.session.emotion == Emotion.JOY


def test_mock_motion_routes_clamp_broadcast_and_update_session(client) -> None:
    test_client, _, _ = client
    with test_client.websocket_connect("/ws/ring") as websocket:
        assert websocket.receive_json()["type"] == "status"
        twist = test_client.post("/api/mock/twist?value=3").json()
        assert twist["payload"] == {"value": 1.0}
        assert websocket.receive_json() == twist

        burst = test_client.post("/api/mock/burst?strength=-2").json()
        assert burst["payload"] == {"strength": 0.0}
        assert websocket.receive_json() == burst

        freeze = test_client.post("/api/mock/freeze").json()
        assert freeze["type"] == "freeze"
        assert websocket.receive_json() == freeze
    assert server.session.motion["frozen"] is True
    assert server.session.motion["burstCount"] == 1


def test_save_metadata_only_is_backward_compatible(client) -> None:
    test_client, _, works_dir = client
    complete_mock_flow(test_client)
    response = test_client.post("/api/save", json={"final_motion": {"twist": 0.4}})
    assert response.status_code == 200
    result = response.json()
    target = works_dir / result["id"]
    metadata = json.loads((target / "portrait.json").read_text(encoding="utf-8"))
    assert metadata["transcript"] == "I am frustrated and angry"
    assert metadata["features"] == {"volume": 0.0, "pitch": 0.0, "brightness": 0.0}
    assert metadata["recipe"]["mode"] == "express"
    assert metadata["finalMotion"]["twist"] == 0.4


def test_save_valid_small_image_and_processed_audio_data_urls(client) -> None:
    test_client, _, works_dir = client
    complete_mock_flow(test_client)
    png = b"\x89PNG\r\n\x1a\n" + b"small-test-payload"
    screenshot = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    processed = "data:audio/wav;base64," + base64.b64encode(wav_bytes()).decode("ascii")
    response = test_client.post(
        "/api/save",
        json={
            "screenshot_data_url": screenshot,
            "processed_audio_data_url": processed,
            "final_motion": {"frozen": True},
        },
    )
    assert response.status_code == 200
    target = works_dir / response.json()["id"]
    assert (target / "sculpture.png").read_bytes() == png
    assert (target / "output.wav").read_bytes().startswith(b"RIFF")


@pytest.mark.parametrize(
    "payload",
    [
        {"screenshot_data_url": "data:image/jpeg;base64,AAAA"},
        {"screenshot_data_url": "data:image/png;base64,not-base64!"},
        {"processed_audio_data_url": "data:audio/wav;base64,AAAA"},
    ],
)
def test_invalid_data_urls_are_rejected_without_creating_work(client, payload) -> None:
    test_client, _, works_dir = client
    complete_mock_flow(test_client)
    response = test_client.post("/api/save", json=payload)
    assert response.status_code == 422
    assert list(works_dir.iterdir()) == []
