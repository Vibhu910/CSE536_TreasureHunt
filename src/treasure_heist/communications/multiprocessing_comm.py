from __future__ import annotations

import queue
import time
from multiprocessing import Queue

from .base import CommunicationBase


class MultiprocessingComm(CommunicationBase):
	"""Message-passing communication library using multiprocessing.Queue."""

	def __init__(self, player_ids: list[str]):
		super().__init__(player_ids)
		self._mailboxes: dict[str, Queue] = {pid: Queue() for pid in player_ids}
		self._actions: Queue = Queue()



	def _put(self, q: Queue, msg: str) -> None:
		while True:
			try:
				q.put_nowait(msg)
				return
			except queue.Full:
				pass 

	def send_to_player(self, player_id: str, msg: str) -> None:
		self._put(self._mailboxes[player_id], msg)

	def broadcast(self, msg: str) -> None:
		for pid in self.player_ids:
			self._put(self._mailboxes[pid], msg)

	def multicast(self, player_ids: list[str], msg: str) -> None:
		for pid in player_ids:
			if pid in self._mailboxes:
				self._put(self._mailboxes[pid], msg)

	def receive(self, player_id: str, timeout: float | None = None) -> str | None:
		deadline = None if timeout is None else time.monotonic() + timeout
		while True:
			try:
				return self._mailboxes[player_id].get_nowait()
			except queue.Empty:
				if deadline is not None and time.monotonic() >= deadline:
					return None

	def submit_action(self, player_id: str, action: str) -> None:
		self._put(self._actions, (player_id, action))

	def next_turn(self) -> dict[str, str]:
		actions: dict[str, str] = {}
		while len(actions) < len(self.player_ids):
			pid, action = self._actions.get()
			actions[pid] = action
		return actions
