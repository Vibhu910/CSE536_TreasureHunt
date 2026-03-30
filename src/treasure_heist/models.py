from dataclasses import dataclass, field


@dataclass
class PlayerState:
    player_id: str
    row: int
    col: int
    score: int = 0
    extracted: bool = False
    action: str = "wait"
    inbox_preview: list[str] = field(default_factory=list)


@dataclass
class GameState:
    width: int
    height: int
    alarm_level: int = 0
    turn: int = 1
