"""Small local-only OBS WebSocket v5 client for SoundClay recordings."""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path

import websockets


class OBSControlError(RuntimeError):
    """OBS is unavailable or rejected a local recording request."""


async def _request(request_type: str, request_data: dict | None = None) -> dict:
    try:
        async with websockets.connect("ws://127.0.0.1:4455", open_timeout=2, close_timeout=1) as socket:
            hello = json.loads(await asyncio.wait_for(socket.recv(), timeout=2))
            if hello.get("op") != 0:
                raise OBSControlError("OBS returned an invalid handshake")
            if hello.get("d", {}).get("authentication"):
                raise OBSControlError("OBS WebSocket authentication must be disabled for local SoundClay control")
            await socket.send(json.dumps({"op": 1, "d": {"rpcVersion": 1}}))
            identified = json.loads(await asyncio.wait_for(socket.recv(), timeout=2))
            if identified.get("op") != 2:
                raise OBSControlError("OBS WebSocket connection was not accepted")
            request_id = uuid.uuid4().hex
            request_payload = {"requestType": request_type, "requestId": request_id}
            if request_data is not None:
                request_payload["requestData"] = request_data
            await socket.send(json.dumps({"op": 6, "d": request_payload}))
            while True:
                response = json.loads(await asyncio.wait_for(socket.recv(), timeout=3))
                if response.get("op") != 7 or response.get("d", {}).get("requestId") != request_id:
                    continue
                data = response["d"]
                status = data.get("requestStatus", {})
                if not status.get("result"):
                    raise OBSControlError(status.get("comment") or f"OBS rejected {request_type}")
                return data.get("responseData", {})
    except OBSControlError:
        raise
    except Exception as exc:
        raise OBSControlError("Cannot connect to OBS on 127.0.0.1:4455") from exc


async def start_recording() -> dict:
    status = await _request("GetRecordStatus")
    if status.get("outputActive"):
        raise OBSControlError("OBS is already recording")
    await _request("StartRecord")
    return {"provider": "obs"}


async def stop_recording() -> Path:
    status = await _request("GetRecordStatus")
    if not status.get("outputActive"):
        raise OBSControlError("OBS is not recording")
    result = await _request("StopRecord")
    output_path = result.get("outputPath")
    if not isinstance(output_path, str) or not output_path:
        raise OBSControlError("OBS did not return the recording path")
    return Path(output_path)


async def ensure_soundclay_sources() -> dict:
    """Ensure the active OBS scene captures the display and desktop audio.

    Existing sources and scenes are preserved. The default Windows display and
    output devices are used so the setup remains valid when hardware changes.
    """
    scenes = await _request("GetSceneList")
    scene_name = scenes.get("currentProgramSceneName")
    if not isinstance(scene_name, str) or not scene_name:
        raise OBSControlError("OBS has no active scene")

    inputs = await _request("GetInputList")
    input_items = [item for item in inputs.get("inputs", []) if isinstance(item, dict)]
    existing = {item.get("inputName") for item in input_items}
    created: list[str] = []
    removed: list[str] = []

    video_inputs = [
        item
        for item in input_items
        if item.get("unversionedInputKind") in {"monitor_capture", "window_capture"}
    ]
    if video_inputs:
        video_name = str(video_inputs[0]["inputName"])
        for item in video_inputs:
            if item.get("unversionedInputKind") != "window_capture":
                continue
            input_name = item.get("inputName")
            if not isinstance(input_name, str) or not input_name:
                continue
            # Window Capture can create a hidden per-window audio source.
            # Disable it so Chrome and microphone recordings cannot leak into
            # the final process film.
            await _request(
                "SetInputSettings",
                {
                    "inputName": input_name,
                    "inputSettings": {"capture_audio": False},
                    "overlay": True,
                },
            )
    else:
        video_name = "SoundClay 屏幕"
        await _request(
            "CreateInput",
            {
                "sceneName": scene_name,
                "inputName": video_name,
                "inputKind": "monitor_capture",
                "inputSettings": {},
                "sceneItemEnabled": True,
            },
        )
        created.append(video_name)

    if "SoundClay 桌面音频" in existing:
        # Remove only the legacy source created by this helper. All remaining
        # output captures are muted below so system/browser audio cannot leak.
        await _request("RemoveInput", {"inputName": "SoundClay 桌面音频"})
        removed.append("SoundClay 桌面音频")

    muted: list[str] = []
    for item in input_items:
        if item.get("unversionedInputKind") not in {
            "wasapi_input_capture",
            "wasapi_output_capture",
        }:
            continue
        input_name = item.get("inputName")
        if not isinstance(input_name, str) or not input_name:
            continue
        if input_name == "SoundClay 桌面音频":
            continue
        await _request("SetInputMute", {"inputName": input_name, "inputMuted": True})
        muted.append(input_name)

    ableton_name = "SoundClay Ableton 音频"
    ableton_executable = (
        os.getenv("OBS_ABLETON_EXECUTABLE", "Ableton Live 12 Suite.exe").strip()
        or "Ableton Live 12 Suite.exe"
    )
    ableton_settings = {
        # OBS window selectors use title:class:executable. Matching priority 2
        # selects by executable, which remains stable when Live Set titles vary.
        "window": f"::{ableton_executable}",
        "priority": 2,
    }
    if ableton_name in existing:
        await _request(
            "SetInputSettings",
            {
                "inputName": ableton_name,
                "inputSettings": ableton_settings,
                "overlay": True,
            },
        )
    else:
        await _request(
            "CreateInput",
            {
                "sceneName": scene_name,
                "inputName": ableton_name,
                "inputKind": "wasapi_process_output_capture",
                "inputSettings": ableton_settings,
                "sceneItemEnabled": True,
            },
        )
        created.append(ableton_name)
    await _request("SetInputMute", {"inputName": ableton_name, "inputMuted": False})

    return {
        "scene": scene_name,
        "created": created,
        "removed": removed,
        "videoSource": video_name,
        "audioSource": ableton_name,
        "audioExecutable": ableton_executable,
        "mutedInputs": muted,
    }
