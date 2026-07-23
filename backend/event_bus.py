from __future__ import annotations

import asyncio
from typing import Any

from fastapi import WebSocket


class EventBus:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(websocket)

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            clients = list(self._clients)

        dead: list[WebSocket] = []
        for client in clients:
            try:
                await client.send_json(message)
            except Exception:
                dead.append(client)

        if dead:
            async with self._lock:
                for client in dead:
                    self._clients.discard(client)
