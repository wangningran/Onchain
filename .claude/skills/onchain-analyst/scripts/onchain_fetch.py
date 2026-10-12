#!/usr/bin/env python3
"""Fetch real on-chain data from the common research sources. Only needs `requests`.

Dune (needs DUNE_API_KEY)
  onchain_fetch.py dune run     --query-id 1234567 [--param days=30 --param project=uniswap] [--out x.csv]
  onchain_fetch.py dune latest  --query-id 1234567           # cached last result, costs no credits
  onchain_fetch.py dune sql     --file query.sql [--name "my query"]   # creates a private query, executes it

DefiLlama (no key)
  onchain_fetch.py llama tvl     --protocol uniswap          # daily TVL history
  onchain_fetch.py llama fees    --protocol uniswap          # daily fees
  onchain_fetch.py llama volume  --protocol uniswap          # daily DEX volume
  onchain_fetch.py llama price   --coins ethereum:0xc02a...,coingecko:ethereum [--timestamp 1717200000]
  onchain_fetch.py llama yields  [--project uniswap-v3 --chain Ethereum]

Etherscan V2 multichain (needs ETHERSCAN_API_KEY)
  onchain_fetch.py etherscan txs     --address 0x... [--chainid 1]
  onchain_fetch.py etherscan tokentx --address 0x... [--contract 0x...]
  onchain_fetch.py etherscan logs    --address 0x... --topic0 0x... --from-block N --to-block M
  onchain_fetch.py etherscan abi     --address 0x...

JSON-RPC (any node; RPC_URL env or --rpc)
  onchain_fetch.py rpc block
  onchain_fetch.py rpc logs --address 0x... --topic0 0x... --from-block N --to-block M [--chunk 2000]

All commands print a short summary and write CSV/JSON with --out (default: stdout preview).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests

DUNE = "https://api.dune.com/api/v1"
LLAMA = "https://api.llama.fi"
COINS = "https://coins.llama.fi"
YIELDS = "https://yields.llama.fi"
ETHERSCAN = "https://api.etherscan.io/v2/api"
TIMEOUT = 60


# ----------------------------------------------------------------------------- utils
def die(msg: str, code: int = 2):
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def get(url, **kw):
    r = requests.get(url, timeout=TIMEOUT, **kw)
    if r.status_code >= 400:
        die(f"GET {url} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def post(url, **kw):
    r = requests.post(url, timeout=TIMEOUT, **kw)
    if r.status_code >= 400:
        die(f"POST {url} -> {r.status_code}: {r.text[:300]}")
    return r.json()


def emit(rows: list[dict], out: str | None, label: str):
    print(f"[{label}] {len(rows)} rows", file=sys.stderr)
    if not out:
        for r in rows[:10]:
            print(json.dumps(r, default=str))
        if len(rows) > 10:
            print(f"... ({len(rows) - 10} more; use --out to save)", file=sys.stderr)
        return
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.suffix == ".json":
        p.write_text(json.dumps(rows, indent=2, default=str))
    else:
        cols = list(dict.fromkeys(k for r in rows for k in r))
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
    print(f"[{label}] saved -> {p}", file=sys.stderr)


def need_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        die(f"{name} is not set")
    return v


# ----------------------------------------------------------------------------- Dune
def _dune_headers():
    return {"X-Dune-API-Key": need_env("DUNE_API_KEY")}


def _dune_params(pairs):
    out = {}
    for p in pairs or []:
        k, _, v = p.partition("=")
        out[k] = v
    return out


def dune_execute(query_id: int, params: dict, performance: str = "medium", poll: float = 3.0, max_wait: int = 900):
    ex = post(f"{DUNE}/query/{query_id}/execute", headers=_dune_headers(),
              json={"query_parameters": params, "performance": performance})
    eid = ex["execution_id"]
    print(f"[dune] execution {eid} started", file=sys.stderr)
    t0 = time.time()
    while True:
        st = get(f"{DUNE}/execution/{eid}/status", headers=_dune_headers())
        state = st.get("state")
        if state == "QUERY_STATE_COMPLETED":
            break
        if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"):
            die(f"execution {eid} {state}: {json.dumps(st.get('error', st))[:400]}")
        if time.time() - t0 > max_wait:
            die(f"execution {eid} still {state} after {max_wait}s")
        time.sleep(poll)
    return dune_results(f"{DUNE}/execution/{eid}/results")


def dune_results(url: str, page: int = 25_000):
    rows, offset = [], 0
    while True:
        res = get(url, headers=_dune_headers(), params={"limit": page, "offset": offset})
        batch = res.get("result", {}).get("rows", [])
        rows += batch
        if not res.get("next_offset") or not batch:
            break
        offset = res["next_offset"]
    return rows


def cmd_dune(a):
    if a.action == "run":
        emit(dune_execute(a.query_id, _dune_params(a.param), a.performance), a.out, "dune")
    elif a.action == "latest":
        emit(dune_results(f"{DUNE}/query/{a.query_id}/results"), a.out, "dune")
    elif a.action == "sql":
        sql = Path(a.file).read_text()
        q = post(f"{DUNE}/query", headers=_dune_headers(),
                 json={"name": a.name or Path(a.file).stem, "query_sql": sql, "is_private": True,
                       "parameters": [{"key": k, "value": v, "type": "text"} for k, v in _dune_params(a.param).items()]})
        qid = q["query_id"]
        print(f"[dune] created query {qid} (reuse with: dune run --query-id {qid})", file=sys.stderr)
        emit(dune_execute(qid, _dune_params(a.param), a.performance), a.out, "dune")


# ----------------------------------------------------------------------------- DefiLlama
def cmd_llama(a):
    if a.action == "tvl":
        d = get(f"{LLAMA}/protocol/{a.protocol}")
        rows = [dict(date=time.strftime("%Y-%m-%d", time.gmtime(x["date"])), tvl_usd=x["totalLiquidityUSD"]) for x in d.get("tvl", [])]
        if a.chain:
            ch = d.get("chainTvls", {}).get(a.chain, {}).get("tvl", [])
            rows = [dict(date=time.strftime("%Y-%m-%d", time.gmtime(x["date"])), tvl_usd=x["totalLiquidityUSD"]) for x in ch]
    elif a.action in ("fees", "volume"):
        path = f"summary/fees/{a.protocol}?dataType=dailyFees" if a.action == "fees" else f"summary/dexs/{a.protocol}?dataType=dailyVolume"
        d = get(f"{LLAMA}/{path}")
        rows = [dict(date=time.strftime("%Y-%m-%d", time.gmtime(ts)), value_usd=v) for ts, v in d.get("totalDataChart", [])]
    elif a.action == "price":
        url = f"{COINS}/prices/historical/{a.timestamp}/{a.coins}" if a.timestamp else f"{COINS}/prices/current/{a.coins}"
        d = get(url)
        rows = [dict(coin=k, **v) for k, v in d.get("coins", {}).items()]
    elif a.action == "yields":
        d = get(f"{YIELDS}/pools")
        rows = [p for p in d.get("data", []) if (not a.project or p.get("project") == a.project) and (not a.chain or p.get("chain") == a.chain)]
    emit(rows, a.out, f"llama {a.action}")


# ----------------------------------------------------------------------------- Etherscan
def cmd_etherscan(a):
    key = need_env("ETHERSCAN_API_KEY")
    base = {"chainid": a.chainid, "apikey": key}
    if a.action == "txs":
        q = dict(module="account", action="txlist", address=a.address, sort="asc", startblock=a.from_block or 0, endblock=a.to_block or 99999999)
    elif a.action == "tokentx":
        q = dict(module="account", action="tokentx", address=a.address, sort="asc")
        if a.contract:
            q["contractaddress"] = a.contract
    elif a.action == "logs":
        q = dict(module="logs", action="getLogs", address=a.address, fromBlock=a.from_block, toBlock=a.to_block)
        if a.topic0:
            q["topic0"] = a.topic0
    elif a.action == "abi":
        q = dict(module="contract", action="getabi", address=a.address)
    d = get(ETHERSCAN, params={**base, **q})
    if str(d.get("status")) != "1" and d.get("message") != "No transactions found":
        die(f"etherscan: {d.get('message')} {str(d.get('result'))[:300]}")
    res = d.get("result")
    rows = json.loads(res) if a.action == "abi" else (res or [])
    emit(rows if isinstance(rows, list) else [rows], a.out, f"etherscan {a.action}")


# ----------------------------------------------------------------------------- JSON-RPC
def rpc_call(url, method, params):
    r = requests.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=TIMEOUT)
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(d["error"])
    return d["result"]


def get_logs_chunked(url, address, topic0, start, end, chunk):
    """eth_getLogs with adaptive range splitting (providers cap block range / result size)."""
    logs, lo = [], start
    while lo <= end:
        hi = min(lo + chunk - 1, end)
        flt = {"fromBlock": hex(lo), "toBlock": hex(hi), "address": address}
        if topic0:
            flt["topics"] = [topic0]
        try:
            logs += rpc_call(url, "eth_getLogs", [flt])
            lo = hi + 1
        except Exception as e:  # too many results / range too large -> halve
            if chunk <= 1:
                raise
            chunk = max(1, chunk // 2)
            print(f"[rpc] {str(e)[:80]} -> chunk={chunk}", file=sys.stderr)
    return logs


def cmd_rpc(a):
    url = a.rpc or need_env("RPC_URL")
    if a.action == "block":
        print(int(rpc_call(url, "eth_blockNumber", []), 16))
        return
    logs = get_logs_chunked(url, a.address, a.topic0, a.from_block, a.to_block, a.chunk)
    rows = [dict(block_number=int(l["blockNumber"], 16), tx_hash=l["transactionHash"], log_index=int(l["logIndex"], 16),
                 contract_address=l["address"], **{f"topic{i}": (l["topics"][i] if i < len(l["topics"]) else None) for i in range(4)},
                 data=l["data"]) for l in logs]
    emit(rows, a.out, "rpc logs")


# ----------------------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="source", required=True)

    d = sub.add_parser("dune")
    d.add_argument("action", choices=["run", "latest", "sql"])
    d.add_argument("--query-id", type=int)
    d.add_argument("--file")
    d.add_argument("--name")
    d.add_argument("--param", action="append", help="key=value (repeatable)")
    d.add_argument("--performance", default="medium", choices=["medium", "large"])
    d.add_argument("--out")
    d.set_defaults(fn=cmd_dune)

    l = sub.add_parser("llama")
    l.add_argument("action", choices=["tvl", "fees", "volume", "price", "yields"])
    l.add_argument("--protocol")
    l.add_argument("--chain")
    l.add_argument("--project")
    l.add_argument("--coins")
    l.add_argument("--timestamp", type=int)
    l.add_argument("--out")
    l.set_defaults(fn=cmd_llama)

    e = sub.add_parser("etherscan")
    e.add_argument("action", choices=["txs", "tokentx", "logs", "abi"])
    e.add_argument("--address", required=True)
    e.add_argument("--contract")
    e.add_argument("--topic0")
    e.add_argument("--from-block", type=int)
    e.add_argument("--to-block", type=int)
    e.add_argument("--chainid", type=int, default=1)
    e.add_argument("--out")
    e.set_defaults(fn=cmd_etherscan)

    r = sub.add_parser("rpc")
    r.add_argument("action", choices=["block", "logs"])
    r.add_argument("--rpc")
    r.add_argument("--address")
    r.add_argument("--topic0")
    r.add_argument("--from-block", type=int)
    r.add_argument("--to-block", type=int)
    r.add_argument("--chunk", type=int, default=2000)
    r.add_argument("--out")
    r.set_defaults(fn=cmd_rpc)

    a = ap.parse_args(argv)
    if a.source == "dune" and a.action in ("run", "latest") and not a.query_id:
        die("--query-id is required")
    if a.source == "dune" and a.action == "sql" and not a.file:
        die("--file is required")
    if a.source == "llama" and a.action in ("tvl", "fees", "volume") and not a.protocol:
        die("--protocol is required")
    if a.source == "llama" and a.action == "price" and not a.coins:
        die("--coins is required")
    a.fn(a)


if __name__ == "__main__":
    main()
