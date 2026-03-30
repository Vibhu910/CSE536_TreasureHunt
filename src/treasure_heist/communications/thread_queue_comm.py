from __future__ import annotations

import queue
import threading

from .base import CommunicationBase


class ThreadQueueComm(CommunicationBase):
    """Thread-safe communication library using queue.Queue."""

    def __init__(self, player_ids: list[str]):
        super().__init__(player_ids)
        self._mailboxes: dict[str, queue.Queue[str]] = {pid: queue.Queue() for pid in player_ids}
        self._action_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._pending_actions: dict[str, str] = {}
        self._lock = threading.Lock()

    def send_to_player(self, player_id: str, msg: str) -> None:
        self._mailboxes[player_id].put(msg)

    def broadcast(self, msg: str) -> None:
        for pid in self.player_ids:
            self._mailboxes[pid].put(msg)

    def multicast(self, player_ids: list[str], msg: str) -> None:
        for pid in player_ids:
            if pid in self._mailboxes:
                self._mailboxes[pid].put(msg)

    def receive(self, player_id: str, timeout: float | None = None) -> str | None:
        try:
            return self._mailboxes[player_id].get(timeout=timeout)
        except queue.Empty:
            return None

    def submit_action(self, player_id: str, action: str) -> None:
        self._action_queue.put((player_id, action))

    def next_turn(self) -> dict[str, str]:
        with self._lock:
            self._pending_actions.clear()
            while len(self._pending_actions) < len(self.player_ids):
                pid, action = self._action_queue.get()
                self._pending_actions[pid] = action
            return dict(self._pending_actions)
