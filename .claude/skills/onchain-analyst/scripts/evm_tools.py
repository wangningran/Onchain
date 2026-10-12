#!/usr/bin/env python3
"""Zero-dependency EVM helpers for on-chain research.

  python evm_tools.py topic0 "Transfer(address,address,uint256)"
  python evm_tools.py selector "transfer(address,uint256)"
  python evm_tools.py decode-data 0x000...  --types uint256,uint256,address
  python evm_tools.py topic-to-address 0x000000000000000000000000a0b8...

keccak256 is implemented in pure Python (Ethereum uses the original Keccak padding 0x01,
not NIST SHA3's 0x06, so hashlib.sha3_256 gives the WRONG answer).
"""
from __future__ import annotations

import argparse
import sys

_RC = [0x0000000000000001, 0x0000000000008082, 0x800000000000808A, 0x8000000080008000, 0x000000000000808B,
       0x0000000080000001, 0x8000000080008081, 0x8000000000008009, 0x000000000000008A, 0x0000000000000088,
       0x0000000080008009, 0x000000008000000A, 0x000000008000808B, 0x800000000000008B, 0x8000000000008089,
       0x8000000000008003, 0x8000000000008002, 0x8000000000000080, 0x000000000000800A, 0x800000008000000A,
       0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008]
_ROT = [[0, 36, 3, 41, 18], [1, 44, 10, 45, 2], [62, 6, 43, 15, 61], [28, 55, 25, 21, 56], [27, 20, 39, 8, 14]]
_M = (1 << 64) - 1


def _rol(x, n):
    return ((x << n) | (x >> (64 - n))) & _M if n else x


def _keccak_f(a):
    for rc in _RC:
        c = [a[x][0] ^ a[x][1] ^ a[x][2] ^ a[x][3] ^ a[x][4] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [[a[x][y] ^ d[x] for y in range(5)] for x in range(5)]
        b = [[0] * 5 for _ in range(5)]
        for x in range(5):
            for y in range(5):
                b[y][(2 * x + 3 * y) % 5] = _rol(a[x][y], _ROT[x][y])
        a = [[b[x][y] ^ ((~b[(x + 1) % 5][y]) & b[(x + 2) % 5][y]) for y in range(5)] for x in range(5)]
        a[0][0] ^= rc
    return a


def keccak256(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * ((-len(msg)) % rate)
    msg[-1] |= 0x80
    a = [[0] * 5 for _ in range(5)]
    for off in range(0, len(msg), rate):
        block = msg[off:off + rate]
        for i in range(rate // 8):
            x, y = i % 5, i // 5
            a[x][y] ^= int.from_bytes(block[8 * i:8 * i + 8], "little")
        a = _keccak_f(a)
    out = b"".join(a[i % 5][i // 5].to_bytes(8, "little") for i in range(4))
    return out[:32]


def topic0(signature: str) -> str:
    """Event signature -> topic0. Use canonical types: uint256 not uint, no spaces, no arg names."""
    return "0x" + keccak256(signature.replace(" ", "").encode()).hex()


def selector(signature: str) -> str:
    return topic0(signature)[:10]


def topic_to_address(topic: str) -> str:
    return "0x" + topic.lower().removeprefix("0x")[-40:]


def decode_static(data: str, types: list[str]) -> list:
    """Decode static ABI types (uintN/intN/address/bool/bytes32) from log `data`."""
    h = data.lower().removeprefix("0x")
    out = []
    for i, t in enumerate(types):
        w = h[64 * i:64 * (i + 1)]
        if len(w) < 64:
            raise ValueError(f"data too short for {len(types)} words")
        if t == "address":
            out.append("0x" + w[-40:])
        elif t == "bool":
            out.append(int(w, 16) != 0)
        elif t.startswith("uint"):
            out.append(int(w, 16))
        elif t.startswith("int"):
            v = int(w, 16)
            out.append(v - (1 << 256) if v >= 1 << 255 else v)
        elif t == "bytes32":
            out.append("0x" + w)
        else:
            raise ValueError(f"dynamic/unsupported type {t}: decode with eth_abi or Dune's decoded tables")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("topic0").add_argument("signature")
    sub.add_parser("selector").add_argument("signature")
    p = sub.add_parser("decode-data")
    p.add_argument("data")
    p.add_argument("--types", required=True)
    sub.add_parser("topic-to-address").add_argument("topic")
    a = ap.parse_args(argv)
    if a.cmd == "topic0":
        print(topic0(a.signature))
    elif a.cmd == "selector":
        print(selector(a.signature))
    elif a.cmd == "decode-data":
        for t, v in zip(a.types.split(","), decode_static(a.data, a.types.split(","))):
            print(f"{t}\t{v}")
    else:
        print(topic_to_address(a.topic))


if __name__ == "__main__":
    sys.exit(main())
