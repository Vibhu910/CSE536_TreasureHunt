from .communications.asyncio_comm import AsyncioComm
from .communications.multiprocessing_comm import MultiprocessingComm
from .communications.rpc_comm import RpcComm
from .communications.thread_queue_comm import ThreadQueueComm


def build_comm(comm_name: str, player_ids: list[str]):
    if comm_name == "thread":
        return ThreadQueueComm(player_ids)
    if comm_name == "asyncio":
        return AsyncioComm(player_ids)
    if comm_name == "mp":
        return MultiprocessingComm(player_ids)
    if comm_name == "rpc":
        return RpcComm(player_ids)
    raise ValueError(f"Unknown communication mode: {comm_name}")
