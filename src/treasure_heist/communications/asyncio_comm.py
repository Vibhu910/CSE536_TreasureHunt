from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future

from .base import CommunicationBase


class AsyncioComm(CommunicationBase):
    """Communication library backed by asyncio primitives."""

    def __init__(self, player_ids: list[str]):
        super().__init__(player_ids)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._mailboxes = self._sync(self._create_mailboxes(player_ids))
        self._actions: asyncio.Queue[tuple[str, str]] = self._sync(self._create_action_queue())

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _create_mailboxes(self, player_ids: list[str]):
        return {pid: asyncio.Queue() for pid in player_ids}

    async def _create_action_queue(self):
        return asyncio.Queue()

    def _sync(self, coro):
        fut: Future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return fut.result()

    def _sync_call(self, fn, *args):
        async def _inner():
            return await fn(*args)

        return self._sync(_inner())

    async def _put(self, q: asyncio.Queue, value):
        await q.put(value)

    async def _get(self, q: asyncio.Queue):
        return await q.get()

    async def _get_timeout(self, q: asyncio.Queue, timeout: float | None):
        if timeout is None:
            return await q.get()
        return await asyncio.wait_for(q.get(), timeout=timeout)

    def send_to_player(self, player_id: str, msg: str) -> None:
        self._sync_call(self._put, self._mailboxes[player_id], msg)

    def broadcast(self, msg: str) -> None:
        for pid in self.player_ids:
            self._sync_call(self._put, self._mailboxes[pid], msg)

    def multicast(self, player_ids: list[str], msg: str) -> None:
        for pid in player_ids:
            if pid in self._mailboxes:
                self._sync_call(self._put, self._mailboxes[pid], msg)

    def receive(self, player_id: str, timeout: float | None = None) -> str | None:
        try:
            return self._sync_call(self._get_timeout, self._mailboxes[player_id], timeout)
        except TimeoutError:
            return None

    def submit_action(self, player_id: str, action: str) -> None:
        self._sync_call(self._put, self._actions, (player_id, action))

    def next_turn(self) -> dict[str, str]:
        actions: dict[str, str] = {}
        while len(actions) < len(self.player_ids):
            pid, action = self._sync_call(self._get, self._actions)
            actions[pid] = action
        return actions

    def close(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=1.0)
