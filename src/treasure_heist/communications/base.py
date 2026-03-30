from __future__ import annotations

from abc import ABC, abstractmethod


class CommunicationBase(ABC):
    def __init__(self, player_ids: list[str]):
        self.player_ids = player_ids

    @abstractmethod
    def send_to_player(self, player_id: str, msg: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def broadcast(self, msg: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def multicast(self, player_ids: list[str], msg: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def receive(self, player_id: str, timeout: float | None = None) -> str | None:
        raise NotImplementedError

    @abstractmethod
    def submit_action(self, player_id: str, action: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def next_turn(self) -> dict[str, str]:
        raise NotImplementedError

    def close(self) -> None:
        return
