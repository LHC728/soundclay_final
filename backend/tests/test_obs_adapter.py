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
    monkeypatch.setattr(
        obs_adapter,
        "_ableton_window_selector",
        lambda _executable: "soundclay - Ableton Live:Ableton Live Window Class:Ableton Live 12 Suite.exe",
    )
    result = asyncio.run(obs_adapter.ensure_soundclay_sources())

    assert result["created"] == ["SoundClay 屏幕", "SoundClay Ableton 音频"]
    assert result["audioSource"] == "SoundClay Ableton 音频"
    create_calls = [data for kind, data in calls if kind == "CreateInput"]
    assert [data["inputKind"] for data in create_calls] == [
        "monitor_capture",
        "wasapi_process_output_capture",
    ]
    assert create_calls[1]["inputSettings"]["window"] == (
        "soundclay - Ableton Live:Ableton Live Window Class:Ableton Live 12 Suite.exe"
    )


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
                    {"inputName": "窗口采集", "unversionedInputKind": "window_capture"},
                    {
                        "inputName": "SoundClay 桌面音频",
                        "unversionedInputKind": "wasapi_output_capture",
                    },
                ]
            }
        return {}

    monkeypatch.setattr(obs_adapter, "_request", fake_request)
    monkeypatch.setattr(
        obs_adapter,
        "_ableton_window_selector",
        lambda _executable: "soundclay - Ableton Live:Ableton Live Window Class:Ableton Live 12 Suite.exe",
    )
    result = asyncio.run(obs_adapter.ensure_soundclay_sources())

    assert result["created"] == ["SoundClay Ableton 音频"]
    assert result["removed"] == ["SoundClay 桌面音频"]
    assert result["videoSource"] == "窗口采集"
    assert result["audioSource"] == "SoundClay Ableton 音频"
    assert result["mutedInputs"] == ["桌面音频", "麦克风/Aux"]
    assert ("RemoveInput", {"inputName": "SoundClay 桌面音频"}) in calls
    assert (
        "SetInputSettings",
        {
            "inputName": "窗口采集",
            "inputSettings": {"capture_audio": False},
            "overlay": True,
        },
    ) in calls
    assert (
        "SetInputMute",
        {"inputName": "麦克风/Aux", "inputMuted": True},
    ) in calls


def test_ableton_window_selector_allows_explicit_override(monkeypatch) -> None:
    selector = "My Live Set:Custom Ableton Class:Ableton Live 12 Suite.exe"
    monkeypatch.setenv("OBS_ABLETON_WINDOW_SELECTOR", selector)

    assert obs_adapter._ableton_window_selector("Ableton Live 12 Suite.exe") == selector
