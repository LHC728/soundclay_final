from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import math
import time
from pathlib import Path
from unittest.mock import AsyncMock

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from fastapi import HTTPException

import server
import ableton_adapter
import emotion_adapter
import stt_adapter
from audio_pipeline import analyze_audio
from chinese_text import normalize_transcript
from emotion_analyzer import analyze_emotion_local
from event_bus import EventBus
from recipe_engine import build_recipe
from schemas import AudioFeatures, Emotion, Mode, SessionState
from stt_adapter import STTError


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
    monkeypatch.setenv("EMOTION_PROVIDER", "local")
    monkeypatch.setenv("ABLETON_OSC_ENABLED", "false")
    monkeypatch.setenv("ABLETON_MIDI_ENABLED", "false")
    emotion_adapter._reset_runtime_state()
    server.session = SessionState(session_id="test-session")
    server.bus = EventBus()
    server.audio_lock = asyncio.Lock()
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


@pytest.mark.parametrize(
    ("transcript", "expected"),
    [
        ("我不生气，只是有点担心明天来不及", Emotion.ANXIETY),
        ("虽然有点紧张，但是终于成功了，我真的很开心", Emotion.JOY),
        ("我很开心但后来特别失落，想哭", Emotion.SADNESS),
        ("今天一直出错，我现在真的很烦", Emotion.ANGER),
        ("今天很平静，心情有些复杂", Emotion.NEUTRAL_MIXED),
    ],
)
def test_weighted_local_emotion_handles_context(transcript: str, expected: Emotion) -> None:
    assert analyze_emotion_local(transcript).emotion == expected


def test_local_emotion_classifier_is_fast_enough_for_inline_use() -> None:
    started = time.perf_counter()
    for _ in range(500):
        analyze_emotion_local("虽然有点紧张，但是事情终于成功了，我真的很开心")
    assert time.perf_counter() - started < 2.0


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        (AudioFeatures(volume=0.95, pitch=0.75, brightness=0.30), Emotion.ANGER),
        (AudioFeatures(volume=0.18, pitch=0.18, brightness=0.18), Emotion.SADNESS),
        (AudioFeatures(volume=0.55, pitch=0.90, brightness=0.90), Emotion.ANXIETY),
        (AudioFeatures(volume=0.65, pitch=0.75, brightness=0.90), Emotion.JOY),
    ],
)
def test_local_fusion_uses_all_audio_features(
    features: AudioFeatures,
    expected: Emotion,
) -> None:
    result = analyze_emotion_local("今天的事情已经结束了", features)
    assert result.emotion == expected
    assert "volume=" in result.reason
    assert "pitch=" in result.reason
    assert "brightness=" in result.reason


def test_silence_does_not_invent_acoustic_emotion() -> None:
    result = analyze_emotion_local(
        "今天的事情已经结束了",
        AudioFeatures(volume=0.0, pitch=0.0, brightness=0.0),
    )
    assert result.emotion == Emotion.NEUTRAL_MIXED


def test_glm_adapter_sends_text_and_features_and_validates_json(monkeypatch) -> None:
    emotion_adapter._reset_runtime_state()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "choices": [{
                    "message": {
                        "content": json.dumps({
                            "emotion": "anxiety",
                            "confidence": 0.88,
                            "reason": "文字表达担心，且音高与明亮度偏高。",
                        }, ensure_ascii=False),
                    },
                }],
            }, ensure_ascii=False).encode("utf-8")

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setenv("EMOTION_PROVIDER", "hybrid")
    monkeypatch.setenv("EMOTION_API_KEY", "test-key-not-real")
    monkeypatch.setenv("EMOTION_BASE_URL", "https://aiping.cn/api/v1")
    monkeypatch.setenv("EMOTION_MODEL", "GLM-5.2")
    monkeypatch.setattr(emotion_adapter.urllib.request, "urlopen", fake_urlopen)
    features = AudioFeatures(volume=0.4, pitch=0.8, brightness=0.75)
    decision = asyncio.run(emotion_adapter.analyze_emotion("我担心时间不够", features))

    assert decision.result.emotion == Emotion.ANXIETY
    assert decision.provider == "hybrid:glm:GLM-5.2"
    assert abs(sum(decision.scores.values()) - 1.0) < 1e-9
    assert set(decision.scores) == {emotion.value for emotion in Emotion}
    assert decision.weights["glm"] > 0
    assert captured["url"] == "https://aiping.cn/api/v1/chat/completions"
    assert captured["body"]["model"] == "GLM-5.2"
    user_payload = json.loads(captured["body"]["messages"][1]["content"])
    assert user_payload["normalized_audio_features"] == features.model_dump()
    assert captured["authorization"] == "Bearer test-key-not-real"


def test_glm_probability_response_is_fused_and_cached(monkeypatch) -> None:
    calls = 0

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "choices": [{"message": {"content": json.dumps({
                    "scores": {
                        "joy": 0.02,
                        "anger": 0.04,
                        "sadness": 0.03,
                        "anxiety": 0.88,
                        "neutral_mixed": 0.03,
                    },
                    "reason": "文字与高音高、高明亮度共同支持焦虑。",
                }, ensure_ascii=False)}}],
            }, ensure_ascii=False).encode("utf-8")

    def fake_urlopen(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse()

    emotion_adapter._reset_runtime_state()
    monkeypatch.setenv("EMOTION_PROVIDER", "hybrid")
    monkeypatch.setenv("EMOTION_API_KEY", "test-key-not-real")
    monkeypatch.setattr(emotion_adapter.urllib.request, "urlopen", fake_urlopen)
    features = AudioFeatures(volume=0.45, pitch=0.85, brightness=0.82)
    first = asyncio.run(emotion_adapter.analyze_emotion("我担心来不及", features))
    second = asyncio.run(emotion_adapter.analyze_emotion("我担心来不及", features))

    assert first.result.emotion == Emotion.ANXIETY
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert second.scores == first.scores
    assert calls == 1


def test_glm_ambiguous_disagreement_becomes_neutral_mixed(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "choices": [{"message": {"content": json.dumps({
                    "scores": {
                        "joy": 0.12,
                        "anger": 0.36,
                        "sadness": 0.08,
                        "anxiety": 0.35,
                        "neutral_mixed": 0.09,
                    },
                    "reason": "证据冲突。",
                }, ensure_ascii=False)}}],
            }, ensure_ascii=False).encode("utf-8")

    emotion_adapter._reset_runtime_state()
    monkeypatch.setenv("EMOTION_PROVIDER", "hybrid")
    monkeypatch.setenv("EMOTION_API_KEY", "test-key-not-real")
    monkeypatch.setattr(emotion_adapter.urllib.request, "urlopen", lambda *_a, **_k: FakeResponse())
    decision = asyncio.run(emotion_adapter.analyze_emotion(
        "今天的事情结束了",
        AudioFeatures(volume=0.5, pitch=0.55, brightness=0.5),
    ))
    assert decision.result.emotion == Emotion.NEUTRAL_MIXED


def test_glm_soft_deadline_returns_local_without_late_mutation(monkeypatch) -> None:
    async def immediate_timeout(awaitable, *, timeout):
        assert timeout == 0.25
        awaitable.close()
        raise TimeoutError

    emotion_adapter._reset_runtime_state()
    monkeypatch.setenv("EMOTION_PROVIDER", "hybrid")
    monkeypatch.setenv("EMOTION_API_KEY", "test-key-not-real")
    monkeypatch.setenv("EMOTION_SOFT_TIMEOUT_SECONDS", "0.25")
    monkeypatch.setenv("EMOTION_TIMEOUT_SECONDS", "3")
    monkeypatch.setattr(emotion_adapter.asyncio, "wait_for", immediate_timeout)
    decision = asyncio.run(emotion_adapter.analyze_emotion(
        "我很生气",
        AudioFeatures(volume=0.9, pitch=0.7, brightness=0.35),
    ))
    assert decision.result.emotion == Emotion.ANGER
    assert decision.provider == "local_fusion"
    assert "decision deadline" in decision.warning


def test_glm_circuit_breaker_opens_after_repeated_failures(monkeypatch) -> None:
    calls = 0

    def fail(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise OSError("offline")

    emotion_adapter._reset_runtime_state()
    monkeypatch.setenv("EMOTION_PROVIDER", "hybrid")
    monkeypatch.setenv("EMOTION_API_KEY", "test-key-not-real")
    monkeypatch.setenv("EMOTION_CIRCUIT_FAILURES", "2")
    monkeypatch.setattr(emotion_adapter.urllib.request, "urlopen", fail)
    features = AudioFeatures(volume=0.9, pitch=0.7, brightness=0.35)
    first = asyncio.run(emotion_adapter.analyze_emotion("我很生气", features))
    second = asyncio.run(emotion_adapter.analyze_emotion("我真的很生气", features))
    third = asyncio.run(emotion_adapter.analyze_emotion("我非常生气", features))

    assert first.provider == second.provider == third.provider == "local_fusion"
    assert "circuit breaker" in third.warning
    assert calls == 2


def test_glm_failure_falls_back_to_local_fusion(monkeypatch) -> None:
    emotion_adapter._reset_runtime_state()
    monkeypatch.setenv("EMOTION_PROVIDER", "hybrid")
    monkeypatch.setenv("EMOTION_API_KEY", "test-key-not-real")
    monkeypatch.setattr(
        emotion_adapter.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("offline")),
    )
    decision = asyncio.run(emotion_adapter.analyze_emotion(
        "我很生气",
        AudioFeatures(volume=0.9, pitch=0.7, brightness=0.4),
    ))
    assert decision.result.emotion == Emotion.ANGER
    assert decision.provider == "local_fusion"
    assert "used local fusion" in decision.warning


def test_express_and_soothe_recipes_differ() -> None:
    express = build_recipe(Emotion.ANGER, Mode.EXPRESS)
    soothe = build_recipe(Emotion.ANGER, Mode.SOOTHE)
    assert express != soothe
    assert express["voiceFx"]["distortion"] > soothe["voiceFx"]["distortion"]
    assert soothe["visual"]["motion"] == "settling"
    assert express["audioBed"]["emotionStemId"] == "emotion_anger"
    assert soothe["audioBed"]["emotionStemId"] == "emotion_anger"


def test_every_emotion_has_a_stable_audio_stem_mapping() -> None:
    for emotion in Emotion:
        recipe = build_recipe(emotion, Mode.EXPRESS)
        assert recipe["audioBed"]["emotionStemId"] == f"emotion_{emotion.value}"


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
    assert response.json()["emotionProvider"] == "local_fusion"
    assert set(response.json()["emotionScores"]) == {
        emotion.value for emotion in Emotion
    }
    assert abs(sum(response.json()["emotionScores"].values()) - 1.0) < 1e-9
    assert response.json()["emotionWeights"]["acoustic"] > 0.0
    assert "volume=" in response.json()["reason"]
    current = test_client.get("/api/session/current").json()
    assert current["emotion_provider"] == "local_fusion"
    assert current["emotion_scores"] == response.json()["emotionScores"]
    mocked_transcribe.assert_awaited_once()


def test_second_upload_clears_first_audio_derived_state(client, monkeypatch) -> None:
    test_client, audio_dir, _ = client
    first_audio = wav_bytes(frequency=180.0)
    second_audio = wav_bytes(frequency=360.0)
    first_upload = test_client.post(
        "/api/audio/upload",
        content=first_audio,
        headers={"content-type": "audio/wav", "x-soundclay-filename": "first.wav"},
    )
    assert first_upload.status_code == 200
    first_id = first_upload.json()["audio_id"]

    monkeypatch.setattr(
        server, "transcribe_audio", AsyncMock(return_value="I am angry and frustrated")
    )
    assert test_client.post("/api/stt/transcribe").status_code == 200
    assert test_client.post("/api/emotion/confirm", json={"emotion": "anger"}).status_code == 200
    assert test_client.post("/api/mode/select", json={"mode": "express"}).status_code == 200
    assert test_client.post("/api/mock/twist?value=0.8").status_code == 200
    assert test_client.post("/api/save", json={"final_motion": {}}).status_code == 200

    second_upload = test_client.post(
        "/api/audio/upload",
        content=second_audio,
        headers={"content-type": "audio/wav", "x-soundclay-filename": "second.wav"},
    )
    assert second_upload.status_code == 200
    uploaded = second_upload.json()
    assert uploaded["phase"] == "audio_ready"
    assert uploaded["filename"] == "second.wav"
    assert uploaded["bytes"] == len(second_audio)
    assert uploaded["audio_id"] == hashlib.sha256(second_audio).hexdigest()
    assert uploaded["audio_id"] != first_id
    assert (audio_dir / "original.wav").read_bytes() == second_audio

    current = test_client.get("/api/session/current").json()
    assert current["phase"] == "audio_ready"
    assert current["audio_id"] == uploaded["audio_id"]
    assert current["audio_filename"] == "second.wav"
    assert current["audio_bytes"] == len(second_audio)
    assert current["transcript"] is None
    assert current["emotion"] is None
    assert current["confidence"] is None
    assert current["reason"] is None
    assert current["emotion_provider"] is None
    assert current["emotion_warning"] is None
    assert current["emotion_scores"] is None
    assert current["emotion_weights"] is None
    assert current["emotion_cache_hit"] is False
    assert current["mode"] is None
    assert current["recipe"] is None
    assert current["motion"] == {}
    assert current["saved_id"] is None
    assert current["last_error"] is None
    assert all(0.0 <= value <= 1.0 for value in current["features"].values())


def test_second_transcription_uses_latest_audio_and_replaces_transcript(client, monkeypatch) -> None:
    test_client, _, _ = client
    first_audio = wav_bytes(frequency=200.0)
    second_audio = wav_bytes(frequency=420.0)
    transcript_by_id = {
        hashlib.sha256(first_audio).hexdigest(): "first transcript is sad",
        hashlib.sha256(second_audio).hexdigest(): "second transcript is happy",
    }

    async def transcribe_current(path: Path) -> str:
        current_id = hashlib.sha256(path.read_bytes()).hexdigest()
        return transcript_by_id[current_id]

    mocked_transcribe = AsyncMock(side_effect=transcribe_current)
    monkeypatch.setattr(server, "transcribe_audio", mocked_transcribe)

    first_upload = test_client.post(
        "/api/audio/upload", content=first_audio, headers={"content-type": "audio/wav"}
    ).json()
    first_result = test_client.post("/api/stt/transcribe")
    assert first_result.status_code == 200
    assert first_result.json()["transcript"] == "first transcript is sad"
    assert first_result.json()["audio_id"] == first_upload["audio_id"]

    second_upload = test_client.post(
        "/api/audio/upload", content=second_audio, headers={"content-type": "audio/wav"}
    ).json()
    assert test_client.get("/api/session/current").json()["transcript"] is None
    second_result = test_client.post("/api/stt/transcribe")
    assert second_result.status_code == 200
    assert second_result.json()["transcript"] == "second transcript is happy"
    assert second_result.json()["audio_id"] == second_upload["audio_id"]
    assert second_result.json()["audio_id"] != first_result.json()["audio_id"]

    current = test_client.get("/api/session/current").json()
    assert current["phase"] == "emotion_review"
    assert current["transcript"] == "second transcript is happy"
    assert current["audio_id"] == second_upload["audio_id"]
    assert current["features"] == second_result.json()["features"]
    assert mocked_transcribe.await_count == 2


def test_auto_confirm_transcription_skips_review_and_reuses_upload_features(client, monkeypatch) -> None:
    test_client, _, _ = client
    upload = test_client.post(
        "/api/audio/upload", content=wav_bytes(), headers={"content-type": "audio/wav"}
    ).json()
    assert server.session.features_audio_id == upload["audio_id"]
    monkeypatch.setattr(
        server, "transcribe_audio", AsyncMock(return_value="我很担心明天来不及")
    )
    repeated_analysis = AsyncMock()
    monkeypatch.setattr(server, "_analyze_current_audio", repeated_analysis)

    response = test_client.post("/api/stt/transcribe?auto_confirm=true")
    assert response.status_code == 200
    assert response.json()["phase"] == "mode_choice"
    assert response.json()["emotion"] == "anxiety"
    assert test_client.get("/api/session/current").json()["phase"] == "mode_choice"
    repeated_analysis.assert_not_awaited()


def test_auto_confirm_mock_transcript_goes_directly_to_mode_choice(client) -> None:
    test_client, _, _ = client
    response = test_client.post(
        "/api/mock/transcript?auto_confirm=true",
        json={"transcript": "终于成功了，我真的很开心"},
    )
    assert response.status_code == 200
    assert response.json()["emotion"] == "joy"
    assert response.json()["phase"] == "mode_choice"


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


def test_failed_transcription_returns_session_to_audio_ready(client, monkeypatch) -> None:
    test_client, _, _ = client
    upload = test_client.post(
        "/api/audio/upload", content=wav_bytes(), headers={"content-type": "audio/wav"}
    ).json()
    monkeypatch.setattr(
        server, "transcribe_audio", AsyncMock(side_effect=STTError("mock failure"))
    )

    response = test_client.post("/api/stt/transcribe")
    assert response.status_code == 502
    current = test_client.get("/api/session/current").json()
    assert current["phase"] == "audio_ready"
    assert current["audio_id"] == upload["audio_id"]
    assert current["transcript"] is None
    assert current["last_error"] == "mock failure"


def test_mock_motion_routes_clamp_broadcast_and_update_session(client) -> None:
    test_client, _, _ = client
    with test_client.websocket_connect("/ws/ring") as websocket:
        assert websocket.receive_json()["type"] == "status"
        twist = test_client.post("/api/mock/twist?value=3").json()
        assert twist["payload"]["value"] == 1.0
        assert twist["payload"]["session_id"] == "test-session"
        assert websocket.receive_json() == twist

        finger = test_client.post("/api/mock/finger?value=-3").json()
        assert finger["payload"]["value"] == -1.0
        assert finger["payload"]["gain"] == 0.0
        assert websocket.receive_json() == finger

        burst = test_client.post("/api/mock/burst?strength=-2").json()
        assert burst["payload"]["strength"] == 0.0
        assert websocket.receive_json() == burst

        freeze = test_client.post("/api/mock/freeze").json()
        assert freeze["type"] == "freeze"
        assert websocket.receive_json() == freeze
    assert server.session.motion["frozen"] is True
    assert server.session.motion["burstCount"] == 1
    assert [item["type"] for item in server.session.motion["trace"]] == [
        "twist",
        "finger",
        "burst",
        "freeze",
    ]


def test_freeze_release_is_backward_compatible(client) -> None:
    test_client, _, _ = client
    assert test_client.post("/api/mock/freeze").json()["payload"]["active"] is True
    released = test_client.post("/api/mock/freeze?active=false").json()
    assert released["type"] == "freeze"
    assert released["payload"]["active"] is False
    assert server.session.motion["frozen"] is False


def test_color_motion_is_broadcast_traced_and_ready_for_ableton(client, monkeypatch) -> None:
    test_client, _, _ = client
    sent = []
    monkeypatch.setattr(server, "send_ableton_motion", lambda kind, payload: sent.append((kind, payload)))
    with test_client.websocket_connect("/ws/ring") as websocket:
        websocket.receive_json()
        color = test_client.post("/api/mock/color?hue=725").json()
        assert websocket.receive_json() == color
    assert color["type"] == "color"
    assert color["payload"]["hue"] == 5.0
    assert server.session.motion["colorHue"] == 5.0
    assert server.session.motion["colorChanges"] == 1
    assert server.session.motion["trace"][-1]["type"] == "color"
    assert sent == [("color", {"hue": 5.0})]


def test_ableton_osc_adapter_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.setenv("ABLETON_OSC_ENABLED", "false")
    monkeypatch.setenv("ABLETON_MIDI_ENABLED", "false")
    monkeypatch.setattr(
        ableton_adapter.socket,
        "socket",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("socket should stay closed")),
    )
    assert ableton_adapter.send_control("twist", 0.5) is False
    assert ableton_adapter.status()["enabled"] is False


def test_ableton_osc_adapter_encodes_local_udp_controls(monkeypatch) -> None:
    packets = []

    class FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def settimeout(self, value):
            assert value == 0.05

        def sendto(self, packet, target):
            packets.append((packet, target))

    monkeypatch.setenv("ABLETON_OSC_ENABLED", "true")
    monkeypatch.setenv("ABLETON_MIDI_ENABLED", "false")
    monkeypatch.setenv("ABLETON_OSC_HOST", "127.0.0.1")
    monkeypatch.setenv("ABLETON_OSC_PORT", "11000")
    monkeypatch.setattr(ableton_adapter.socket, "socket", lambda *_a, **_k: FakeSocket())
    ableton_adapter.send_motion("twist", {"value": 0.75})

    assert len(packets) == 2
    assert packets[0][0].startswith(b"/soundclay/twist\0")
    assert packets[1][0].startswith(b"/soundclay/filter\0")
    assert packets[0][1] == ("127.0.0.1", 11000)


def test_status_exposes_backward_compatible_ableton_mapping(client) -> None:
    test_client, _, _ = client
    status = test_client.get("/api/ableton/status")
    assert status.status_code == 200
    assert status.json()["transport"] == "osc-udp"
    assert status.json()["addresses"]["color"] == "/soundclay/color"
    assert status.json()["midi"]["controls"]["timbreWheel"]["number"] == 20
    assert status.json()["midi"]["controls"]["mainGain"]["number"] == 21
    assert status.json()["midi"]["controls"]["burstClip"]["number"] == 70
    assert status.json()["midi"]["scenes"]["joy:express"] == 60
    assert status.json()["midi"]["scenes"]["neutral_mixed:soothe"] == 69


def test_ableton_midi_reuses_saved_live_set_mapping(monkeypatch) -> None:
    messages = []

    class FakePort:
        closed = False

        def send(self, message):
            messages.append(message)

        def close(self):
            self.closed = True

    port = FakePort()
    monkeypatch.setenv("ABLETON_OSC_ENABLED", "false")
    monkeypatch.setenv("ABLETON_MIDI_ENABLED", "true")
    monkeypatch.setenv("ABLETON_MIDI_PORT", "SoundClay MIDI")
    monkeypatch.setenv("ABLETON_MIDI_CHANNEL", "0")
    monkeypatch.setenv("ABLETON_MIDI_GAIN_FLOOR", "0.4")
    monkeypatch.setattr(
        ableton_adapter.mido,
        "get_output_names",
        lambda: ["GesturePort 1", "SoundClay MIDI 2"],
    )
    monkeypatch.setattr(ableton_adapter.mido, "open_output", lambda name: port)
    ableton_adapter.close_midi_output()

    assert ableton_adapter.send_scene("joy", "express") is True
    ableton_adapter.send_motion("twist", {"value": 0.5})
    ableton_adapter.send_motion("finger", {"value": -0.5})
    ableton_adapter.send_motion("burst", {"strength": 0.8})

    assert [(message.type, getattr(message, "note", None)) for message in messages[:2]] == [
        ("note_on", 60),
        ("note_off", 60),
    ]
    cc_messages = [message for message in messages if message.type == "control_change"]
    assert [(message.control, message.value) for message in cc_messages] == [(20, 64), (21, 70)]
    assert [(message.type, getattr(message, "note", None)) for message in messages[-2:]] == [
        ("note_on", 70),
        ("note_off", 70),
    ]
    assert all(message.channel == 0 for message in messages)
    ableton_adapter.close_midi_output()


def test_frontend_ableton_motion_route_maps_signed_controls(client, monkeypatch) -> None:
    test_client, _, _ = client
    sent = []
    monkeypatch.setattr(server, "send_ableton_motion", lambda kind, payload: sent.append((kind, payload)))

    twist = test_client.post("/api/ableton/motion/twist?value=-1").json()
    finger = test_client.post("/api/ableton/motion/finger?value=0.6").json()
    burst = test_client.post("/api/ableton/motion/burst?value=2").json()
    unsupported = test_client.post("/api/ableton/motion/unknown?value=0")

    assert twist == {"ok": True, "type": "twist", "value": 0.0}
    assert finger == {"ok": True, "type": "finger", "value": 0.6}
    assert burst == {"ok": True, "type": "burst", "value": 1.0}
    assert unsupported.status_code == 422
    assert sent == [
        ("twist", {"value": 0.0}),
        ("finger", {"value": 0.6}),
        ("burst", {"strength": 1.0}),
    ]


def test_ableton_stop_sends_midi_clock_stop(monkeypatch) -> None:
    messages = []

    class FakePort:
        closed = False

        def send(self, message):
            messages.append(message)

        def close(self):
            self.closed = True

    monkeypatch.setenv("ABLETON_OSC_ENABLED", "false")
    monkeypatch.setenv("ABLETON_MIDI_ENABLED", "true")
    monkeypatch.setattr(ableton_adapter.mido, "get_output_names", lambda: ["SoundClay MIDI 2"])
    monkeypatch.setattr(ableton_adapter.mido, "open_output", lambda _name: FakePort())
    ableton_adapter.close_midi_output()

    assert ableton_adapter.send_stop() is True
    assert [message.type for message in messages] == ["stop"]
    ableton_adapter.close_midi_output()


def test_ableton_stop_route(client, monkeypatch) -> None:
    test_client, _, _ = client
    monkeypatch.setattr(server, "stop_ableton_playback", lambda: True)

    response = test_client.post("/api/ableton/stop")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_mode_selection_sends_existing_emotion_scene_note(client, monkeypatch) -> None:
    test_client, _, _ = client
    sent = []
    monkeypatch.setattr(
        server,
        "send_ableton_scene",
        lambda emotion, mode: sent.append((emotion, mode)) or True,
    )
    assert test_client.post(
        "/api/mock/transcript", json={"transcript": "我真的很生气"}
    ).status_code == 200
    assert test_client.post(
        "/api/emotion/confirm", json={"emotion": "anger"}
    ).status_code == 200
    assert test_client.post(
        "/api/mode/select", json={"mode": "soothe"}
    ).status_code == 200
    assert sent == [("anger", "soothe")]


def test_recipe_preview_does_not_advance_the_mode_choice(client) -> None:
    test_client, _, _ = client
    assert test_client.post(
        "/api/mock/transcript", json={"transcript": "I feel nervous and worried"}
    ).status_code == 200
    confirmed = test_client.post(
        "/api/emotion/confirm", json={"emotion": "anxiety"}
    ).json()
    assert confirmed["phase"] == "mode_choice"

    express = test_client.post("/api/recipe/preview", json={"mode": "express"})
    soothe = test_client.post("/api/recipe/preview", json={"mode": "soothe"})
    assert express.status_code == 200
    assert soothe.status_code == 200
    assert express.json()["recipe"] != soothe.json()["recipe"]
    current = test_client.get("/api/session/current").json()
    assert current["phase"] == "mode_choice"
    assert current["mode"] is None
    assert current["recipe"] is None


def test_direct_mode_selection_requires_no_emotion_analysis(client, monkeypatch) -> None:
    test_client, _, _ = client
    analyzer = AsyncMock()
    monkeypatch.setattr(server, "analyze_emotion", analyzer)

    express_preview = test_client.post("/api/recipe/preview", json={"mode": "express"})
    soothe_preview = test_client.post("/api/recipe/preview", json={"mode": "soothe"})
    selected = test_client.post("/api/mode/select", json={"mode": "soothe"})

    assert express_preview.status_code == 200
    assert soothe_preview.status_code == 200
    assert express_preview.json()["recipe"] != soothe_preview.json()["recipe"]
    assert selected.status_code == 200
    assert selected.json()["phase"] == "sculpting"
    current = test_client.get("/api/session/current").json()
    assert current["emotion"] == "neutral_mixed"
    assert current["emotion_provider"] == "direct_mode"
    assert current["reason"].startswith("Direct mode selection")
    analyzer.assert_not_awaited()


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


def test_status_current_and_reset_clear_temporary_audio_but_keep_works(client) -> None:
    test_client, audio_dir, works_dir = client
    (audio_dir / "original.wav").write_bytes(wav_bytes())
    preserved = works_dir / "existing-work"
    preserved.mkdir()
    (preserved / "metadata.json").write_text("{}", encoding="utf-8")

    status = test_client.get("/api/status")
    assert status.status_code == 200
    assert status.json()["sessionId"] == "test-session"
    assert test_client.get("/api/session/current").json()["phase"] == "ready"

    reset = test_client.post("/api/reset")
    assert reset.status_code == 200
    assert reset.json()["session_id"] != "test-session"
    assert reset.json()["transcript"] is None
    assert not (audio_dir / "original.wav").exists()
    assert preserved.exists()


def test_upload_rejects_non_riff_and_reports_expected_format(client) -> None:
    test_client, _, _ = client
    invalid = test_client.post(
        "/api/audio/upload",
        content=b"not a wave file",
        headers={"content-type": "audio/wav"},
    )
    assert invalid.status_code == 422
    assert "RIFF/WAVE" in invalid.json()["detail"]

    valid = test_client.post(
        "/api/audio/upload",
        content=wav_bytes(),
        headers={"content-type": "audio/wav"},
    )
    assert valid.status_code == 200
    metadata = valid.json()
    assert metadata["sampleRate"] == 16_000
    assert metadata["channels"] == 1
    assert metadata["subtype"] == "PCM_16"
    assert metadata["expectedFormat"] is True
    assert metadata["session_id"] == "test-session"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("I feel happy and delighted", "joy"),
        ("I am furious and angry", "anger"),
        ("I feel sad and lonely", "sadness"),
        ("I am nervous and worried", "anxiety"),
        ("This is a factual sentence", "neutral_mixed"),
    ],
)
def test_all_local_emotion_categories_use_public_contract(text, expected) -> None:
    assert analyze_emotion_local(text).model_dump(mode="json")["emotion"] == expected


def test_legacy_neutral_emotion_input_is_accepted_and_normalized(client) -> None:
    test_client, _, _ = client
    assert test_client.post(
        "/api/mock/transcript", json={"transcript": "A factual sentence"}
    ).status_code == 200
    response = test_client.post(
        "/api/emotion/confirm", json={"emotion": "neutral-mixed"}
    )
    assert response.status_code == 200
    assert response.json()["emotion"] == "neutral_mixed"
    assert response.json()["reason"] == "Confirmed or corrected by the user."


def test_every_recipe_value_is_finite_bounded_and_has_audio_bed_alias() -> None:
    for emotion in Emotion:
        for mode in Mode:
            recipe = build_recipe(emotion, mode)
            assert recipe["audioBed"] == recipe["soundscape"]
            for section in ("voiceFx", "soundscape", "audioBed", "visual"):
                for value in recipe[section].values():
                    if isinstance(value, (int, float)):
                        assert math.isfinite(value)
            assert 0.5 <= recipe["voiceFx"]["playbackRate"] <= 2.0
            assert 20 <= recipe["voiceFx"]["lowpassHz"] <= 20_000
            assert 0 <= recipe["visual"]["density"] <= 1


def test_transcription_rejects_an_explicit_stale_audio_identifier(client, monkeypatch) -> None:
    test_client, _, _ = client
    upload = test_client.post(
        "/api/audio/upload", content=wav_bytes(), headers={"content-type": "audio/wav"}
    ).json()
    mocked = AsyncMock(return_value="this must not run")
    monkeypatch.setattr(server, "transcribe_audio", mocked)
    response = test_client.post(
        "/api/stt/transcribe", headers={"x-soundclay-audio-id": "older-audio"}
    )
    assert response.status_code == 409
    assert test_client.get("/api/session/current").json()["audio_id"] == upload["audio_id"]
    mocked.assert_not_awaited()


def test_mock_recording_clears_old_audio_and_emits_recording(client) -> None:
    test_client, audio_dir, _ = client
    assert test_client.post(
        "/api/audio/upload", content=wav_bytes(), headers={"content-type": "audio/wav"}
    ).status_code == 200
    with test_client.websocket_connect("/ws/ring") as websocket:
        websocket.receive_json()
        response = test_client.post("/api/mock/recording")
        assert response.status_code == 200
        assert response.json()["type"] == "recording"
        assert websocket.receive_json()["type"] == "recording"
    current = test_client.get("/api/session/current").json()
    assert current["phase"] == "recording"
    assert current["audio_id"] is None
    assert not (audio_dir / "original.wav").exists()


def test_inbound_websocket_motion_alias_is_validated_and_traced(client) -> None:
    test_client, _, _ = client
    with test_client.websocket_connect("/ws/ring") as websocket:
        websocket.receive_json()
        websocket.send_json(
            {
                "type": "imu/twist",
                "timestamp": 1234,
                "payload": {"value": 0.42, "session_id": "test-session"},
            }
        )
        emitted = websocket.receive_json()
        assert emitted["type"] == "twist"
        assert emitted["timestamp"] == 1234
        assert emitted["payload"]["value"] == 0.42

        websocket.send_json({"type": "unknown", "payload": {}})
        error = websocket.receive_json()
        assert error["type"] == "error"
        assert error["payload"]["code"] == "INVALID_RING_EVENT"
    assert server.session.motion["trace"][-1]["type"] == "twist"


def test_five_saves_are_unique_and_public_metadata_is_private(client) -> None:
    test_client, _, works_dir = client
    complete_mock_flow(test_client)
    ids = []
    for _ in range(5):
        response = test_client.post("/api/save", json={"final_motion": {}})
        assert response.status_code == 200
        ids.append(response.json()["id"])
    assert len(set(ids)) == 5

    first = works_dir / ids[0]
    private = json.loads((first / "portrait.json").read_text(encoding="utf-8"))
    public = json.loads((first / "metadata.json").read_text(encoding="utf-8"))
    assert private["transcript"] == "I am frustrated and angry"
    assert "transcript" not in public
    assert public["privateTranscriptStoredLocally"] is True


def test_stt_adapter_configuration_is_offline(monkeypatch, tmp_path) -> None:
    calls = []

    class Segment:
        text = " cached local transcript "

    class FakeModel:
        def transcribe(self, path, **kwargs):
            calls.append((path, kwargs))
            return [Segment()], object()

    stt_adapter._get_whisper_model.cache_clear()
    monkeypatch.setenv("WHISPER_MODEL", "local-model-path")
    monkeypatch.setenv("WHISPER_DEVICE", "cpu")
    monkeypatch.setenv("WHISPER_COMPUTE_TYPE", "int8")
    monkeypatch.setenv("WHISPER_LANGUAGE", "en")
    monkeypatch.setenv("WHISPER_BEAM_SIZE", "2")
    monkeypatch.setattr(
        stt_adapter,
        "_get_whisper_model",
        lambda model, device, compute: FakeModel(),
    )
    audio = tmp_path / "offline.wav"
    audio.write_bytes(wav_bytes())
    assert stt_adapter._transcribe_faster_whisper(audio) == "cached local transcript"
    assert calls[0][1]["beam_size"] == 2
    assert calls[0][1]["language"] == "en"


def test_traditional_chinese_transcript_is_normalized_to_simplified() -> None:
    assert normalize_transcript("第一段錄音，我現在真的很煩。這裡還有聲音。") == (
        "第一段录音，我现在真的很烦。这里还有声音。"
    )


def test_mock_transcript_route_stores_and_returns_simplified_chinese(client) -> None:
    test_client, _, _ = client
    response = test_client.post(
        "/api/mock/transcript",
        json={"transcript": "第一段錄音，我現在真的很煩。"},
    )
    assert response.status_code == 200
    assert response.json()["transcript"] == "第一段录音，我现在真的很烦。"
    assert test_client.get("/api/session/current").json()["transcript"] == (
        "第一段录音，我现在真的很烦。"
    )


def test_real_transcription_response_normalizes_adapter_output(client, monkeypatch) -> None:
    test_client, _, _ = client
    assert test_client.post(
        "/api/audio/upload", content=wav_bytes(), headers={"content-type": "audio/wav"}
    ).status_code == 200
    monkeypatch.setattr(
        server,
        "transcribe_audio",
        AsyncMock(return_value="第一段錄音，我現在真的很煩。"),
    )
    response = test_client.post("/api/stt/transcribe")
    assert response.status_code == 200
    assert response.json()["transcript"] == "第一段录音，我现在真的很烦。"


def test_stt_timeout_has_readable_recovery_message(monkeypatch, tmp_path) -> None:
    audio = tmp_path / "timeout.wav"
    audio.write_bytes(wav_bytes())
    monkeypatch.setenv("STT_TIMEOUT_SECONDS", "1")

    async def immediate_timeout(awaitable, *, timeout):
        assert timeout == 1
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(stt_adapter.asyncio, "wait_for", immediate_timeout)
    with pytest.raises(STTError, match="shorter WAV"):
        asyncio.run(stt_adapter.FasterWhisperAdapter().transcribe(audio))
