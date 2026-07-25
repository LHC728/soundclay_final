from __future__ import annotations

import asyncio

import obs_adapter


def test_ensure_soundclay_sources_creates_missing_capture_inputs(monkeypatch) -> None:
    calls: list[tuple[str, dict | None]] = []

    async def fake_request(request_type: str, request_data: dict | None = None) -> dict:
        calls.append((request_type, request_data))
        if request_type == "GetSceneList":
            return {"currentProgramSceneName": "SoundClay"}
        if request_type == "GetInputList":
            return {"inputs": []}
        return {}

    monkeypatch.setattr(obs_adapter, "_request", fake_request)
    result = asyncio.run(obs_adapter.ensure_soundclay_sources())

    assert result["created"] == ["SoundClay 屏幕", "SoundClay 桌面音频"]
    assert result["audioSource"] == "SoundClay 桌面音频"
    create_calls = [data for kind, data in calls if kind == "CreateInput"]
    assert [data["inputKind"] for data in create_calls] == [
        "monitor_capture",
        "wasapi_output_capture",
    ]


def test_ensure_soundclay_sources_reuses_desktop_audio_and_mutes_microphone(
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict | None]] = []

    async def fake_request(request_type: str, request_data: dict | None = None) -> dict:
        calls.append((request_type, request_data))
        if request_type == "GetSceneList":
            return {"currentProgramSceneName": "场景"}
        if request_type == "GetInputList":
            return {
                "inputs": [
                    {
                        "inputName": "桌面音频",
                        "unversionedInputKind": "wasapi_output_capture",
                    },
                    {
                        "inputName": "麦克风/Aux",
                        "unversionedInputKind": "wasapi_input_capture",
                    },
                    {
                        "inputName": "SoundClay 屏幕",
                        "unversionedInputKind": "monitor_capture",
                    },
                    {
                        "inputName": "SoundClay 桌面音频",
                        "unversionedInputKind": "wasapi_output_capture",
                    },
                ]
            }
        return {}

    monkeypatch.setattr(obs_adapter, "_request", fake_request)
    result = asyncio.run(obs_adapter.ensure_soundclay_sources())

    assert result["created"] == []
    assert result["removed"] == ["SoundClay 桌面音频"]
    assert result["audioSource"] == "桌面音频"
    assert result["mutedInputs"] == ["麦克风/Aux"]
    assert ("RemoveInput", {"inputName": "SoundClay 桌面音频"}) in calls
    assert (
        "SetInputMute",
        {"inputName": "麦克风/Aux", "inputMuted": True},
    ) in calls
