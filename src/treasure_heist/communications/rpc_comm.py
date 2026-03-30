from __future__ import annotations

import queue
import threading
from collections import defaultdict
from xmlrpc.client import ServerProxy
from xmlrpc.server import SimpleXMLRPCServer

from .base import CommunicationBase


class _RpcBackend:
    def __init__(self, player_ids: list[str]):
        self._mailboxes: dict[str, queue.Queue[str]] = {pid: queue.Queue() for pid in player_ids}
        self._actions: queue.Queue[tuple[str, str]] = queue.Queue()
        self._player_ids = player_ids
        self._lock = threading.Lock()

    def send_to_player(self, player_id: str, msg: str) -> bool:
        self._mailboxes[player_id].put(msg)
        return True

    def broadcast(self, msg: str) -> bool:
        for pid in self._player_ids:
            self._mailboxes[pid].put(msg)
        return True

    def multicast(self, player_ids: list[str], msg: str) -> bool:
        for pid in player_ids:
            if pid in self._mailboxes:
                self._mailboxes[pid].put(msg)
        return True

    def receive(self, player_id: str, timeout: float | None) -> str:
        try:
            if timeout is None:
                return self._mailboxes[player_id].get()
            return self._mailboxes[player_id].get(timeout=timeout)
        except queue.Empty:
            return ""

    def submit_action(self, player_id: str, action: str) -> bool:
        self._actions.put((player_id, action))
        return True

    def next_turn(self) -> dict[str, str]:
        with self._lock:
            actions: dict[str, str] = defaultdict(str)
            while len(actions) < len(self._player_ids):
                pid, action = self._actions.get()
                actions[pid] = action
            return dict(actions)


class RpcComm(CommunicationBase):
    """RPC communication library using stdlib XML-RPC."""

    def __init__(self, player_ids: list[str], host: str = "127.0.0.1", port: int = 0):
        super().__init__(player_ids)
        self._backend = _RpcBackend(player_ids)
        self._server = SimpleXMLRPCServer((host, port), allow_none=True, logRequests=False)
        self._server.register_instance(self._backend)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        bound_host, bound_port = self._server.server_address
        self._proxy = ServerProxy(f"http://{bound_host}:{bound_port}", allow_none=True)

    def send_to_player(self, player_id: str, msg: str) -> None:
        self._proxy.send_to_player(player_id, msg)

    def broadcast(self, msg: str) -> None:
        self._proxy.broadcast(msg)

    def multicast(self, player_ids: list[str], msg: str) -> None:
        self._proxy.multicast(player_ids, msg)

    def receive(self, player_id: str, timeout: float | None = None) -> str | None:
        msg = self._proxy.receive(player_id, timeout)
        return msg or None

    def submit_action(self, player_id: str, action: str) -> None:
        self._proxy.submit_action(player_id, action)

    def next_turn(self) -> dict[str, str]:
        return self._proxy.next_turn()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._server_thread.join(timeout=1.0)
