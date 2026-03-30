from __future__ import annotations

import json


def encode_message(payload: dict) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


def decode_message(line: str) -> dict:
    return json.loads(line)
