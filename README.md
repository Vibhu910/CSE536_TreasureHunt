# Treasure Heist (CSE 536 Group Project Template)

Treasure Heist is a text-based multiplayer game built to satisfy the CSE 536 semester project requirements:

- Non-trivial communication (unicast, multicast, broadcast)
- Concurrency-aware design
- Pluggable communication API
- Multiple communication-library implementations using different primitives

## Project Layout

- `run_server.py` - Entry point for multi-client game server.
- `run_client.py` - Entry point for per-player client.
- `src/treasure_heist/network_server.py` - Server-side game engine for separate clients.
- `src/treasure_heist/network_protocol.py` - JSON line protocol helpers.
- `src/treasure_heist/models.py` - Dataclasses and core game models.
- `src/treasure_heist/comm_factory.py` - Shared communication backend selector.
- `src/treasure_heist/communications/base.py` - Shared communication API contract.
- `src/treasure_heist/communications/thread_queue_comm.py` - Threads + `queue.Queue`.
- `src/treasure_heist/communications/asyncio_comm.py` - Async I/O + `asyncio.Queue`.
- `src/treasure_heist/communications/multiprocessing_comm.py` - Message passing via `multiprocessing.Queue`.
- `src/treasure_heist/communications/rpc_comm.py` - RPC via XML-RPC server/client.

## Communication API

All implementations expose a compatible API:

- `send_to_player(player_id: str, msg: str) -> None`
- `broadcast(msg: str) -> None`
- `multicast(player_ids: list[str], msg: str) -> None`
- `receive(player_id: str, timeout: float | None = None) -> str | None`
- `submit_action(player_id: str, action: str) -> None`
- `next_turn() -> dict[str, str]`

## Quick Start (one terminal per player)

1. Start server:

```bash
python3 run_server.py --comm thread --players 3 --port 5000
```

2. In three separate terminals (or screen windows), start clients:

```bash
python3 run_client.py --host 127.0.0.1 --port 5000 --player-id P1
python3 run_client.py --host 127.0.0.1 --port 5000 --player-id P2
python3 run_client.py --host 127.0.0.1 --port 5000 --player-id P3
```

3. Each client submits its own action when prompted.

This mode preserves the same actions and messaging features while enabling true one-player-per-terminal input.

## Gameplay

- Goal: steal artifacts and escape through the extraction point before alarm reaches critical level.
- Turn actions:
  - `move N|S|E|W`
  - `scout`
  - `steal`
  - `say <message>` — broadcast to everyone (**free**: any number per turn, does not use your turn)
  - `share <player_id> <message>` — private to one player (**free**)
  - `share all <message>` — broadcast to everyone (**free**)
  - After the turn prompt, type as many chat lines as you want, then one **turn action** (`move`, `scout`, `steal`, `wait`, etc.).
  - `wait`
- Non-trivial communication:
  - Unicast: private clue or direct share
  - Multicast: room-based alerts to nearby players
  - Broadcast: turn and alarm announcements

## How Group Members Can Use This

- Keep the game files identical across all group submissions.
- Each member chooses exactly one communication implementation file as their individual library.
- Optionally, each member can rename/copy their chosen implementation to a personal filename for submission clarity.
- In your PDF and README, clearly state:
  - which primitive you implemented
  - which file is your communication library
  - your API

## Suggested Individual Ownership Notes in README

Add a section like:

- Student A: `thread_queue_comm.py` (threads + queue)
- Student B: `asyncio_comm.py` (async I/O)
- Student C: `multiprocessing_comm.py` (message passing)
- Student D: `rpc_comm.py` (RPC)

## Notes

- This template is self-contained and uses only Python standard library modules.
- For screenshots, run multiple sessions and capture turn progression, private messages, and broadcasts.
