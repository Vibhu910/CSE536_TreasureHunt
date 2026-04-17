import argparse
import socket
import sys
import threading

from src.treasure_heist.network_protocol import decode_message, encode_message


def is_chat_line(line: str) -> bool:
    """Lines that are sent as chat (free, no turn) instead of turn action."""
    parts = line.strip().split(None, 2)
    if not parts:
        return False
    cmd = parts[0].lower()
    if cmd == "say" and len(parts) >= 2:
        return True
    if cmd == "share" and len(parts) >= 3:
        return True
    return False


def send_payload(file_out, lock: threading.Lock, payload: dict) -> None:
    with lock:
        file_out.write(encode_message(payload))
        file_out.flush()


def receiver_loop(file_in, stop_event: threading.Event, prompt_event: threading.Event) -> None:
    while not stop_event.is_set():
        line = file_in.readline()
        if not line:
            print("[client] server disconnected")
            stop_event.set()
            prompt_event.set()
            return
        payload = decode_message(line.decode("utf-8").strip())
        msg_type = payload.get("type")
        text = payload.get("text", "")

        if msg_type == "prompt":
            print(f"\n{text}", flush=True)
            prompt_event.set()
        elif msg_type in {"info", "summary", "welcome", "error", "game_over"}:
            print(f"\n{text}", flush=True)
            if msg_type == "game_over":
                stop_event.set()
                prompt_event.set()
                return
        elif msg_type == "pong":
            continue
        else:
            print(f"\n[client] unknown message: {payload}")


def main():
    parser = argparse.ArgumentParser(description="Treasure Heist player client")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--player-id", required=True, help="Player id (e.g., P1)")
    args = parser.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((args.host, args.port))
    except OSError as exc:
        print(f"Could not connect to server: {exc}")
        sys.exit(1)

    file_in = sock.makefile("rb")
    file_out = sock.makefile("wb")
    out_lock = threading.Lock()
    stop_event = threading.Event()
    prompt_event = threading.Event()

    send_payload(file_out, out_lock, {"type": "join", "player_id": args.player_id})

    reader = threading.Thread(
        target=receiver_loop,
        args=(file_in, stop_event, prompt_event),
        daemon=True,
    )
    reader.start()

    try:
        while not stop_event.is_set():
            prompt_event.wait(timeout=0.1)
            if not prompt_event.is_set():
                continue
            if stop_event.is_set():
                break
            while True:
                line = input(f"[{args.player_id}] > ").strip() or "wait"
                if is_chat_line(line):
                    send_payload(file_out, out_lock, {"type": "chat", "text": line})
                else:
                    send_payload(file_out, out_lock, {"type": "action", "action": line})
                    prompt_event.clear()
                    break
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
        try:
            sock.close()
        except OSError:
            pass


if __name__ == "__main__":
    main()
