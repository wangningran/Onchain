"""Run the Base DEX case-study queries on Dune and save the results as CSV.

    DUNE_API_KEY=... python scripts/run_dune_case.py --project uniswap

Each dune_queries/base_case/*.sql file is executed (with {{project}} substituted),
results land in data/real/base_case/<file>.csv plus a run_meta.json manifest.
Tries Dune's raw-SQL endpoint first, then falls back to create-query + execute.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

API = "https://api.dune.com/api/v1"
ROOT = Path(__file__).resolve().parents[1]


class DuneError(RuntimeError):
    pass


def _req(method, path, key, **kw):
    r = requests.request(method, f"{API}{path}", headers={"X-Dune-API-Key": key}, timeout=60, **kw)
    if r.status_code >= 400:
        raise DuneError(f"{method} {path} -> {r.status_code}: {r.text[:400]}")
    return r.json()


def start_execution(sql: str, name: str, key: str, performance: str) -> tuple[str, str]:
    """Return (execution_id, how). Prefer raw SQL execution; fall back to a saved query."""
    try:
        res = _req("POST", "/sql/execute", key, json={"sql": sql, "performance": performance})
        return res["execution_id"], "sql/execute"
    except DuneError as e:
        print(f"  raw-SQL endpoint unavailable ({str(e)[:120]}); falling back to create-query", flush=True)
    q = _req("POST", "/query", key, json={"name": name, "query_sql": sql, "is_private": False})
    qid = q["query_id"]
    res = _req("POST", f"/query/{qid}/execute", key, json={"performance": performance})
    return res["execution_id"], f"query/{qid}"


def wait_and_fetch(eid: str, key: str, max_wait: int) -> list[dict]:
    t0 = time.time()
    while True:
        st = _req("GET", f"/execution/{eid}/status", key)
        state = st.get("state")
        if state == "QUERY_STATE_COMPLETED":
            break
        if state in ("QUERY_STATE_FAILED", "QUERY_STATE_CANCELLED", "QUERY_STATE_EXPIRED"):
            raise DuneError(f"execution {eid} {state}: {json.dumps(st.get('error', st))[:400]}")
        if time.time() - t0 > max_wait:
            raise DuneError(f"execution {eid} still {state} after {max_wait}s")
        time.sleep(5)
    rows, offset = [], 0
    while True:
        res = _req("GET", f"/execution/{eid}/results", key, params={"limit": 10000, "offset": offset})
        batch = res.get("result", {}).get("rows", [])
        rows += batch
        if not res.get("next_offset") or not batch:
            return rows
        offset = res["next_offset"]


def write_csv(rows: list[dict], path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    cols = list(dict.fromkeys(k for r in rows for k in r)) if rows else []
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="uniswap")
    ap.add_argument("--only", nargs="*", help="query file stems to run (default: all)")
    ap.add_argument("--performance", default="medium", choices=["medium", "large"])
    ap.add_argument("--max-wait", type=int, default=1200)
    args = ap.parse_args()
    key = os.environ.get("DUNE_API_KEY")
    if not key:
        sys.exit("DUNE_API_KEY is not set (add it as a GitHub Actions secret)")

    out_dir = ROOT / "data" / "real" / "base_case"
    meta = {"project": args.project, "blockchain": "base",
            "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "queries": {}}
    failures = 0
    for f in sorted((ROOT / "dune_queries" / "base_case").glob("*.sql")):
        if args.only and f.stem not in args.only:
            continue
        sql = f.read_text().replace("{{project}}", args.project)
        print(f"\n== {f.stem} ==", flush=True)
        t0 = time.time()
        try:
            eid, how = start_execution(sql, f"onchain-portfolio {f.stem} ({args.project})", key, args.performance)
            print(f"  execution {eid} via {how}", flush=True)
            rows = wait_and_fetch(eid, key, args.max_wait)
            write_csv(rows, out_dir / f"{f.stem}.csv")
            meta["queries"][f.stem] = {"status": "ok", "rows": len(rows), "execution_id": eid, "via": how,
                                       "seconds": round(time.time() - t0)}
            print(f"  {len(rows)} rows in {time.time() - t0:.0f}s", flush=True)
            for r in rows[:5]:
                print("   ", json.dumps(r, default=str)[:300])
        except Exception as e:  # keep going so one slow query doesn't lose the rest
            failures += 1
            meta["queries"][f.stem] = {"status": "error", "error": str(e)[:500]}
            print(f"  ERROR: {e}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "run_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"\n{len(meta['queries']) - failures} ok, {failures} failed -> {out_dir}")
    sys.exit(1 if failures == len(meta["queries"]) else 0)


if __name__ == "__main__":
    main()
