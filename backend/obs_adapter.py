"""Small local-only OBS WebSocket v5 client for SoundClay recordings."""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import websockets


class OBSControlError(RuntimeError):
    """OBS is unavailable or rejected a local recording request."""


async def _request(request_type: str) -> dict:
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
            await socket.send(json.dumps({"op": 6, "d": {"requestType": request_type, "requestId": request_id}}))
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
