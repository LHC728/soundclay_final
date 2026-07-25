"""Small local-only OBS WebSocket v5 client for SoundClay recordings."""

from __future__ import annotations

import asyncio
import ctypes
import json
import os
import uuid
from pathlib import Path

import websockets


class OBSControlError(RuntimeError):
    """OBS is unavailable or rejected a local recording request."""


def _ableton_window_selector(executable: str) -> str:
    """Return the complete OBS selector for the active Ableton main window."""

    override = os.getenv("OBS_ABLETON_WINDOW_SELECTOR", "").strip()
    if override:
        return override
    if os.name != "nt":
        return f"::{executable}"

    candidates: list[tuple[str, str]] = []
    user32 = ctypes.windll.user32
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def collect_window(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        user32.GetClassNameW(hwnd, class_buffer, len(class_buffer))
        title = title_buffer.value.strip()
        class_name = class_buffer.value.strip()
        if title and class_name == "Ableton Live Window Class":
            candidates.append((title, class_name))
        return True

    try:
        user32.EnumWindows(callback_type(collect_window), 0)
    except (AttributeError, OSError):
        return f"::{executable}"
    if not candidates:
        return f"::{executable}"

    title, class_name = candidates[0]
    return f"{title}:{class_name}:{executable}"


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
    ableton_selector = _ableton_window_selector(ableton_executable)
    ableton_settings = {
        # OBS silently keeps the previous application when it receives an
        # incomplete selector. Resolve the live title and window class so the
        # application-audio source cannot remain attached to Chrome.
        "window": ableton_selector,
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
        "audioWindowSelector": ableton_selector,
        "mutedInputs": muted,
    }
