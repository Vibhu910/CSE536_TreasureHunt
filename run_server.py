import argparse
import random

from src.treasure_heist.comm_factory import build_comm
from src.treasure_heist.network_server import NetworkTreasureHeistServer


def main():
    parser = argparse.ArgumentParser(description="Treasure Heist multi-client server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--comm", choices=["thread", "asyncio", "mp", "rpc"], default="thread")
    parser.add_argument("--players", type=int, default=3, help="Number of players (2-6)")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--max-turns", type=int, default=25)
    args = parser.parse_args()

    if not 2 <= args.players <= 6:
        raise ValueError("players must be between 2 and 6")

    if args.seed is not None:
        random.seed(args.seed)

    player_ids = [f"P{i+1}" for i in range(args.players)]
    comm = build_comm(args.comm, player_ids)
    server = NetworkTreasureHeistServer(
        host=args.host,
        port=args.port,
        player_ids=player_ids,
        comm=comm,
        max_turns=args.max_turns,
    )
    server.run()


if __name__ == "__main__":
    main()
