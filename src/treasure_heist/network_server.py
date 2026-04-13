from __future__ import annotations

import logging
import random
import socket
import threading
from dataclasses import dataclass, field

from .communications.base import CommunicationBase
from .models import GameState, PlayerState
from .network_protocol import decode_message, encode_message

_logger = logging.getLogger(__name__)

_INBOX_MAX = 200


@dataclass
class ClientConn:
    sock: socket.socket
    file_in: any
    file_out: any
    lock: threading.Lock
    player_id: str
    disconnected: bool = field(default=False, init=False)

    def send(self, payload: dict) -> bool:
        if self.disconnected:
            return False
        data = encode_message(payload)
        try:
            with self.lock:
                self.file_out.write(data)
                self.file_out.flush()
            return True
        except OSError:
            self.disconnected = True
            _logger.warning("send failed for %s, marking disconnected", self.player_id)
            return False


class NetworkTreasureHeistServer:
    def __init__(
        self,
        host: str,
        port: int,
        player_ids: list[str],
        comm: CommunicationBase,
        max_turns: int = 25,
    ):
        self.host = host
        self.port = port
        self.player_ids = player_ids
        self.comm = comm
        self.max_turns = max_turns
        self.state = GameState(width=8, height=8)
        self.players = self._init_players(player_ids)
        self.extraction_point = (self.state.height - 1, self.state.width - 1)
        self.artifacts = self._init_artifacts(count=4)
        self.traps = self._init_traps(count=5)
        self.discovered_artifacts: set[tuple[int, int]] = set()

        self._server_sock: socket.socket | None = None
        self._clients: dict[str, ClientConn] = {}
        self._clients_lock = threading.Lock()
        self._running = False
        self._log_lock = threading.Lock()
        self._drain_lock = threading.Lock()
        self._action_submitted: set[str] = set()
        self._action_lock = threading.Lock()

    def _log(self, message: str) -> None:
        with self._log_lock:
            print(message, flush=True)

    def _init_players(self, player_ids: list[str]) -> dict[str, PlayerState]:
        h = self.state.height
        w = self.state.width
        starts = [
            (0, 0),
            (0, w - 1),
            (h - 1, 0),
            (h // 2, 0),
            (0, w // 2),
            (h // 2, w - 1),
        ]
        players: dict[str, PlayerState] = {}
        for idx, pid in enumerate(player_ids):
            row, col = starts[idx]
            players[pid] = PlayerState(player_id=pid, row=row, col=col)
        return players

    def _init_artifacts(self, count: int) -> set[tuple[int, int]]:
        blocked = {(p.row, p.col) for p in self.players.values()}
        blocked.add(self.extraction_point)
        # Reserve a little space near starts by leaving them allowed (simpler),
        # but never place on a start cell or extraction.
        all_cells = [
            (r, c)
            for r in range(self.state.height)
            for c in range(self.state.width)
            if (r, c) not in blocked
        ]
        return set(random.sample(all_cells, k=count))

    def _init_traps(self, count: int) -> set[tuple[int, int]]:
        blocked = {(p.row, p.col) for p in self.players.values()}
        blocked.add(self.extraction_point)
        blocked |= self.artifacts
        all_cells = [
            (r, c)
            for r in range(self.state.height)
            for c in range(self.state.width)
            if (r, c) not in blocked
        ]
        count = min(count, len(all_cells))
        return set(random.sample(all_cells, k=count))

    def _render_map(self, artifact_mode: str = "all") -> str:
        grid = [["." for _ in range(self.state.width)] for _ in range(self.state.height)]
        if artifact_mode == "all":
            for r, c in self.artifacts:
                grid[r][c] = "A"
        elif artifact_mode == "discovered":
            for r, c in self.artifacts:
                if (r, c) in self.discovered_artifacts:
                    grid[r][c] = "A"
        er, ec = self.extraction_point
        grid[er][ec] = "E"
        if artifact_mode == "all":
            for r, c in self.traps:
                grid[r][c] = "T"
        for p in self.players.values():
            grid[p.row][p.col] = p.player_id[-1]
        return "\n".join(" ".join(row) for row in grid)

    def _send_to_player(self, player_id: str, payload: dict) -> None:
        with self._clients_lock:
            conn = self._clients.get(player_id)
        if conn is not None:
            conn.send(payload)
            text = payload.get("text", "")
            if text:
                self._log(f"[server -> {player_id}] {text}")

    def _broadcast(self, payload: dict) -> None:
        with self._clients_lock:
            conns = list(self._clients.values())
        for conn in conns:
            conn.send(payload)  # individual failures handled inside send()
        text = payload.get("text", "")
        if text:
            self._log(f"[server -> ALL] {text}")

    def _handle_client(self, conn: ClientConn) -> None:
        try:
            while self._running:
                line = conn.file_in.readline()
                if not line:
                    break
                payload = decode_message(line.decode("utf-8").strip())
                msg_type = payload.get("type")
                self._log(f"[{conn.player_id} -> server] {payload}")
                if msg_type == "action":
                    with self._action_lock:
                        already = conn.player_id in self._action_submitted
                    if already:
                        conn.send({"type": "error", "text": "action already submitted this turn"})
                        continue
                    action = str(payload.get("action", "")).strip() or "wait"
                    self.comm.submit_action(conn.player_id, action)
                    with self._action_lock:
                        self._action_submitted.add(conn.player_id)
                    conn.send({"type": "info", "text": f"[client] submitted action: {action}"})
                elif msg_type == "chat":
                    text = str(payload.get("text", "")).strip()
                    if not text:
                        conn.send({"type": "error", "text": "empty chat"})
                    else:
                        self._log(f"[chat] {conn.player_id}: {text}")
                        self._process_chat_line(conn.player_id, text)
                        with self._drain_lock:
                            self._drain_messages()
                        conn.send({"type": "info", "text": "[chat delivered — does not use your turn]"})
                elif msg_type == "ping":
                    conn.send({"type": "pong"})
                else:
                    conn.send({"type": "error", "text": "unknown message type"})
        finally:
            with self._clients_lock:
                if conn.player_id in self._clients:
                    del self._clients[conn.player_id]
            self._log(f"[server] {conn.player_id} disconnected")

    def _accept_clients(self) -> None:
        assert self._server_sock is not None
        while len(self._clients) < len(self.player_ids):
            sock, _addr = self._server_sock.accept()
            self._log("[server] incoming client connection")
            file_in = sock.makefile("rb")
            file_out = sock.makefile("wb")
            first_line = file_in.readline()
            if not first_line:
                sock.close()
                continue
            payload = decode_message(first_line.decode("utf-8").strip())
            if payload.get("type") != "join":
                file_out.write(encode_message({"type": "error", "text": "first message must be join"}))
                file_out.flush()
                sock.close()
                continue

            player_id = str(payload.get("player_id", ""))
            if player_id not in self.player_ids:
                file_out.write(encode_message({"type": "error", "text": "invalid player id"}))
                file_out.flush()
                sock.close()
                continue

            with self._clients_lock:
                if player_id in self._clients:
                    file_out.write(encode_message({"type": "error", "text": "player id already connected"}))
                    file_out.flush()
                    sock.close()
                    continue
                conn = ClientConn(
                    sock=sock,
                    file_in=file_in,
                    file_out=file_out,
                    lock=threading.Lock(),
                    player_id=player_id,
                )
                self._clients[player_id] = conn

            conn.send({"type": "welcome", "text": f"joined as {player_id}"})
            thread = threading.Thread(target=self._handle_client, args=(conn,), daemon=True)
            thread.start()
            self._log(f"[server] accepted player {player_id}")

            self._broadcast(
                {
                    "type": "info",
                    "text": f"[server] {player_id} connected ({len(self._clients)}/{len(self.player_ids)})",
                }
            )

    def _apply_move(self, player: PlayerState, direction: str, pid: str) -> None:
        dr_dc = {"N": (-1, 0), "S": (1, 0), "E": (0, 1), "W": (0, -1)}
        dr, dc = dr_dc.get(direction, (0, 0))
        player.row = max(0, min(self.state.height - 1, player.row + dr))
        player.col = max(0, min(self.state.width - 1, player.col + dc))
        pos = (player.row, player.col)
        if pos in self.traps:
            self.traps.discard(pos)
            self.state.alarm_level += 1
            self.comm.send_to_player(pid, "[private] you triggered a trap! alarm +1")
            self.comm.broadcast(f"[broadcast] {pid} triggered a trap. Alarm increased.")

    def _adjacent_players(self, source_id: str) -> list[str]:
        src = self.players[source_id]
        near: list[str] = []
        for pid, p in self.players.items():
            if pid == source_id:
                continue
            if abs(p.row - src.row) + abs(p.col - src.col) <= 1:
                near.append(pid)
        return near

    def _process_chat_line(self, pid: str, line: str) -> None:
        """say / share — uses comm layer only; does not consume a turn."""
        parts = line.split()
        cmd = parts[0].lower() if parts else ""
        if cmd == "say" and len(parts) >= 2:
            message = " ".join(parts[1:])
            text = f"[broadcast from {pid}] {message}"
            self.comm.broadcast(text)
            self.comm.send_to_player(pid, "[private] your message was sent to everyone")
            return
        if cmd == "share" and len(parts) >= 3:
            target = parts[1]
            message = " ".join(parts[2:])
            if target.lower() == "all":
                text = f"[broadcast from {pid}] {message}"
                self.comm.broadcast(text)
                self.comm.send_to_player(pid, "[private] your message was sent to everyone")
            elif target in self.players:
                self.comm.send_to_player(target, f"[private from {pid}] {message}")
                self.comm.send_to_player(pid, f"[private] sent message to {target}")
            else:
                self.comm.send_to_player(pid, "[private] invalid target player id")
            return
        self.comm.send_to_player(pid, "[private] chat must be: say <msg> or share <player>|all <msg>")

    def _resolve_action(self, pid: str, action: str) -> None:
        player = self.players[pid]
        parts = action.split()
        cmd = parts[0].lower() if parts else "wait"
        one_key_dirs = {"n": "N", "s": "S", "e": "E", "w": "W"}
        self._log(f"[turn {self.state.turn}] resolving {pid}: {action}")

        if cmd in one_key_dirs and len(parts) == 1:
            parts = ["move", one_key_dirs[cmd]]
            cmd = "move"

        if cmd == "move" and len(parts) == 2:
            self._apply_move(player, parts[1].upper(), pid)
            self.comm.send_to_player(pid, f"[private] moved to ({player.row},{player.col})")
            nearby = self._adjacent_players(pid)
            if nearby:
                self.comm.multicast(nearby, f"[room] footsteps near {player.player_id}")
        elif cmd == "scout":
            around = []
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1), (0, 0)]:
                rr, cc = player.row + dr, player.col + dc
                if 0 <= rr < self.state.height and 0 <= cc < self.state.width and (rr, cc) in self.artifacts:
                    around.append((rr, cc))
            msg = f"[private] scout sees artifacts at: {around}" if around else "[private] scout found nothing"
            self.comm.send_to_player(pid, msg)
        elif cmd == "steal":
            pos = (player.row, player.col)
            if pos in self.artifacts:
                self.discovered_artifacts.add(pos)
                self.artifacts.remove(pos)
                player.score += 1
                self.comm.send_to_player(pid, "[private] steal successful (+1 score)")
                self.comm.broadcast(f"[broadcast] {pid} stole an artifact. Remaining: {len(self.artifacts)}")
            else:
                self.state.alarm_level += 1
                self.comm.send_to_player(pid, "[private] no artifact here; alarm increased")
        else:
            self.comm.send_to_player(pid, "[private] waiting")

    def _drain_messages(self) -> None:
        for pid in self.players:
            while True:
                msg = self.comm.receive(pid, timeout=0.01)
                if msg is None:
                    break
                inbox = self.players[pid].inbox_preview
                if len(inbox) >= _INBOX_MAX:
                    inbox.pop(0)
                inbox.append(msg)
                self._log(f"[comm -> {pid}] {msg}")
                self._send_to_player(pid, {"type": "info", "text": msg})

    def _check_extractions(self) -> None:
        for p in self.players.values():
            if (p.row, p.col) == self.extraction_point and p.score > 0:
                p.extracted = True

    def _is_game_over(self) -> tuple[bool, str]:
        if self.state.alarm_level >= 6:
            return True, "Alarm reached critical level. Guards win."
        if all(p.extracted or p.score == 0 for p in self.players.values()) and not self.artifacts:
            return True, "All artifacts resolved and carriers extracted."
        if self.state.turn > self.max_turns:
            return True, "Reached max turns."
        return False, ""

    def _turn_summary_text(self, artifact_mode: str = "all") -> str:
        lines = [
            "=== Turn Summary ===",
            f"Turn: {self.state.turn}",
            f"Alarm: {self.state.alarm_level}/6",
            f"Artifacts remaining: {len(self.artifacts)}",
            "Map:",
            self._render_map(artifact_mode=artifact_mode),
        ]
        for pid, p in self.players.items():
            extracted = " (extracted)" if p.extracted else ""
            lines.append(f"- {pid}: score={p.score}, pos=({p.row},{p.col}){extracted}")
        return "\n".join(lines)

    def _artifact_intro_text(self) -> str:
        ordered = sorted(self.artifacts)
        traps_ordered = sorted(self.traps)
        return f"[server] artifact locations: {ordered} | trap locations: {traps_ordered}"

    def _send_prompt_to_all(self) -> None:
        for pid, p in self.players.items():
            self._send_to_player(
                pid,
                {
                    "type": "prompt",
                    "text": (
                        f"[{pid}] Turn {self.state.turn} | score={p.score} | pos=({p.row},{p.col})\n"
                        "Actions: move N|S|E|W | scout | steal | wait\n"
                        "Free chat (any number per turn, no turn cost): say <msg> | share <player>|all <msg>\n"
                        "Enter chat or your one turn action:"
                    ),
                },
            )
        self._log(f"[turn {self.state.turn}] prompts sent to all players")

    def run(self) -> None:
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(len(self.player_ids))
        bound_host, bound_port = self._server_sock.getsockname()
        self._running = True
        self._log(f"Server listening on {bound_host}:{bound_port}")
        self._log(f"Waiting for players: {', '.join(self.player_ids)}")

        try:
            self._accept_clients()
            self._broadcast({"type": "info", "text": "All players connected. Starting game."})
            self._log(self._artifact_intro_text())
            while True:
                over, reason = self._is_game_over()
                if over:
                    break

                self._log(f"[turn {self.state.turn}] starting")
                with self._action_lock:
                    self._action_submitted.clear()
                self.comm.broadcast(f"[broadcast] starting turn {self.state.turn}")
                self._send_prompt_to_all()
                actions = self.comm.next_turn()
                self._log(f"[turn {self.state.turn}] received actions: {actions}")
                for pid in self.player_ids:
                    action = actions.get(pid, "wait")
                    self._resolve_action(pid, action)

                if random.random() < 0.20:
                    self.state.alarm_level += 1
                    self.comm.broadcast("[broadcast] random security sweep increased alarm")

                self._check_extractions()
                with self._drain_lock:
                    self._drain_messages()
                server_summary = self._turn_summary_text(artifact_mode="all")
                client_summary = self._turn_summary_text(artifact_mode="discovered")
                self._log(server_summary)
                self._broadcast({"type": "summary", "text": client_summary})
                self.state.turn += 1

            self._log(f"[server] game over reason: {reason}")
            self._broadcast({"type": "game_over", "text": reason})
            score_lines = ["=== Final Scores ==="]
            for pid, p in self.players.items():
                bonus = 1 if p.extracted else 0
                score_lines.append(f"{pid}: {p.score + bonus} (artifacts={p.score}, extracted_bonus={bonus})")
            self._log("\n".join(score_lines))
            self._broadcast({"type": "game_over", "text": "\n".join(score_lines)})
        finally:
            self._running = False
            self.comm.close()
            with self._clients_lock:
                conns = list(self._clients.values())
                self._clients.clear()
            for conn in conns:
                try:
                    conn.sock.close()
                except OSError:
                    pass
            if self._server_sock is not None:
                self._server_sock.close()
