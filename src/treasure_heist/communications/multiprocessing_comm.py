from __future__ import annotations

import queue
from multiprocessing import Queue

from .base import CommunicationBase


class MultiprocessingComm(CommunicationBase):
    """Message-passing communication library using multiprocessing.Queue."""

    def __init__(self, player_ids: list[str]):
        super().__init__(player_ids)
        self._mailboxes: dict[str, Queue] = {pid: Queue() for pid in player_ids}
        self._actions: Queue = Queue()

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
        self._actions.put((player_id, action))

    def next_turn(self) -> dict[str, str]:
        actions: dict[str, str] = {}
        while len(actions) < len(self.player_ids):
            pid, action = self._actions.get()
            actions[pid] = action
        return actions
