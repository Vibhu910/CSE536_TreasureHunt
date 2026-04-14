from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future

from .base import CommunicationBase

_logger = logging.getLogger(__name__)

_TURN_TIMEOUT = 120.0


class AsyncioComm(CommunicationBase):
    """Communication library backed by asyncio primitives."""

    def __init__(self, player_ids: list[str]):
        super().__init__(player_ids)
        self._closed = False
        self._loop = asyncio.new_event_loop()
        self._loop_ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._loop_ready.wait()
        self._mailboxes = self._sync(self._create_mailboxes(player_ids))
        self._actions: asyncio.Queue[tuple[str, str]] = self._sync(self._create_action_queue())

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._loop_ready.set)
        self._loop.run_forever()

    async def _create_mailboxes(self, player_ids: list[str]):
        return {pid: asyncio.Queue() for pid in player_ids}

    async def _create_action_queue(self):
        return asyncio.Queue()

    def _sync(self, coro):
        if self._closed:
            _logger.warning("_sync called after close(), ignoring")
            return None
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
        q = self._mailboxes.get(player_id)
        if q is None:
            _logger.warning("send_to_player: unknown player_id %s", player_id)
            return
        self._sync_call(self._put, q, msg)

    def broadcast(self, msg: str) -> None:
        async def _broadcast_all():
            await asyncio.gather(
                *(self._put(self._mailboxes[pid], msg) for pid in self.player_ids)
            )

        self._sync(_broadcast_all())

    def multicast(self, player_ids: list[str], msg: str) -> None:
        targets = [pid for pid in player_ids if pid in self._mailboxes]
        if not targets:
            return

        async def _multicast_all():
            await asyncio.gather(
                *(self._put(self._mailboxes[pid], msg) for pid in targets)
            )

        self._sync(_multicast_all())

    def receive(self, player_id: str, timeout: float | None = None) -> str | None:
        q = self._mailboxes.get(player_id)
        if q is None:
            return None
        try:
            return self._sync_call(self._get_timeout, q, timeout)
        except (TimeoutError, asyncio.TimeoutError):
            return None

    def submit_action(self, player_id: str, action: str) -> None:
        self._sync_call(self._put, self._actions, (player_id, action))

    def next_turn(self) -> dict[str, str]:
        actions: dict[str, str] = {}

        async def _collect():
            remaining = set(self.player_ids) - set(actions)
            while remaining:
                try:
                    pid, action = await asyncio.wait_for(
                        self._actions.get(), timeout=_TURN_TIMEOUT
                    )
                    actions[pid] = action
                    remaining.discard(pid)
                except (TimeoutError, asyncio.TimeoutError):
                    for pid in remaining:
                        actions[pid] = "wait"
                        _logger.warning(
                            "next_turn: timed out waiting for %s, defaulting to wait",
                            pid,
                        )
                    break

        self._sync(_collect())
        return actions

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        async def _shutdown():
            tasks = [
                t for t in asyncio.all_tasks(self._loop) if t is not asyncio.current_task()
            ]
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._loop.stop()

        try:
            self._loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(_shutdown(), loop=self._loop)
            )
        except RuntimeError:
            _logger.warning("event loop already closed during shutdown")
        self._thread.join(timeout=3.0)
        if not self._loop.is_closed():
            self._loop.close()
