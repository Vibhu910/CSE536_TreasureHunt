from __future__ import annotations

import logging
import queue
import threading
from xmlrpc.client import ServerProxy
from xmlrpc.server import SimpleXMLRPCServer

from .base import CommunicationBase

_logger = logging.getLogger(__name__)

_TURN_TIMEOUT = 120.0
_RECEIVE_POLL = 0.5

_SENTINEL = "__RPC_NONE__"


class _RpcBackend:
    def __init__(self, player_ids: list[str]):
        self._mailboxes: dict[str, queue.Queue[str]] = {pid: queue.Queue() for pid in player_ids}
        self._actions: queue.Queue[tuple[str, str]] = queue.Queue()
        self._player_ids = player_ids

    def send_to_player(self, player_id: str, msg: str) -> bool:
        q = self._mailboxes.get(player_id)
        if q is None:
            _logger.warning("send_to_player: unknown player_id %s", player_id)
            return False
        q.put(msg)
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
        q = self._mailboxes.get(player_id)
        if q is None:
            return _SENTINEL
        try:
            if timeout is None:
                timeout = _RECEIVE_POLL
            return q.get(timeout=timeout)
        except queue.Empty:
            return _SENTINEL

    def submit_action(self, player_id: str, action: str) -> bool:
        self._actions.put((player_id, action))
        return True

    def next_turn(self) -> dict[str, str]:
        actions: dict[str, str] = {}
        remaining = set(self._player_ids)
        while remaining:
            try:
                pid, action = self._actions.get(timeout=_TURN_TIMEOUT)
                actions[pid] = action
                remaining.discard(pid)
            except queue.Empty:
                for pid in remaining:
                    actions[pid] = "wait"
                    _logger.warning(
                        "next_turn: timed out waiting for %s, defaulting to wait",
                        pid,
                    )
                break
        return actions


class RpcComm(CommunicationBase):
    """RPC communication library using stdlib XML-RPC."""

    def __init__(self, player_ids: list[str], host: str = "127.0.0.1", port: int = 0):
        super().__init__(player_ids)
        self._closed = False
        self._backend = _RpcBackend(player_ids)
        self._server = SimpleXMLRPCServer((host, port), allow_none=True, logRequests=False)
        self._server.register_instance(self._backend)
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        bound_host, bound_port = self._server.server_address
        self._proxy = ServerProxy(f"http://{bound_host}:{bound_port}", allow_none=True)

    def _rpc_call(self, method: str, *args):
        if self._closed:
            _logger.warning("RPC call %s after close(), ignoring", method)
            return None
        try:
            return getattr(self._proxy, method)(*args)
        except Exception:
            _logger.warning("RPC call %s failed", method, exc_info=True)
            return None

    def send_to_player(self, player_id: str, msg: str) -> None:
        self._rpc_call("send_to_player", player_id, msg)

    def broadcast(self, msg: str) -> None:
        self._rpc_call("broadcast", msg)

    def multicast(self, player_ids: list[str], msg: str) -> None:
        self._rpc_call("multicast", player_ids, msg)

    def receive(self, player_id: str, timeout: float | None = None) -> str | None:
        result = self._rpc_call("receive", player_id, timeout)
        if result is None or result == _SENTINEL:
            return None
        return result

    def submit_action(self, player_id: str, action: str) -> None:
        self._rpc_call("submit_action", player_id, action)

    def next_turn(self) -> dict[str, str]:
        result = self._rpc_call("next_turn")
        if result is None:
            return {pid: "wait" for pid in self.player_ids}
        return result

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._server.shutdown()
        self._server.server_close()
        self._server_thread.join(timeout=3.0)
