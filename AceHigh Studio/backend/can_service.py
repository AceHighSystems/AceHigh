from __future__ import annotations

import asyncio
from typing import Any


class CanService:
    """
    Single serialized access point to AceLight.

    The browser never talks to python-can or AceLight directly.
    Every read/write goes through this object so CAN transactions cannot
    accidentally overlap from multiple WebSocket handlers/tasks.
    """

    def __init__(self, ace_backend: Any | None):
        self.ace = ace_backend
        # Create the lock on first use inside Uvicorn's running loop.
        # Python 3.9 can bind a lock created here to the pre-server loop.
        self._lock: asyncio.Lock | None = None

    @property
    def connected(self) -> bool:
        return self.ace is not None

    def _require_backend(self):
        if self.ace is None:
            raise RuntimeError(
                "AceLight backend is not loaded. Copy your existing AceLight "
                "library into AceHigh-gui/acelight/ and expose the object/module "
                "that provides ace.read(...) and ace.write(...)."
            )

    async def read(self, node_id: int, parameter: str):
        self._require_backend()
        return await self._transaction(self.ace.read, node_id, parameter)

    async def write(self, node_id: int, parameter: str, data):
        self._require_backend()

        return await self._transaction(self.ace.write, node_id, parameter, data)

    async def _transaction(self, function, *args):
        if self._lock is None:
            self._lock = asyncio.Lock()

        async with self._lock:
            worker = asyncio.create_task(asyncio.to_thread(function, *args))
            try:
                return await asyncio.shield(worker)
            except asyncio.CancelledError:
                # Cancelling the waiter cannot stop a python-can worker thread.
                # Keep ownership until it finishes consuming its CAN response.
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not worker.cancelled():
                    worker.exception()
                raise
