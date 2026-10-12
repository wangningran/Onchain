"""End-to-end pipeline:  generate (or ingest) -> dbt build -> analysis -> report.

    python pipeline.py              # full run on synthetic data
    python pipeline.py --skip-generate   # reuse data/raw (e.g. after ingesting real data)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "reports"))


def sh(cmd: list[str], cwd: Path, env=None):
    print(f"\n$ {' '.join(cmd)}  (in {cwd.relative_to(ROOT) if cwd != ROOT else '.'})", flush=True)
    subprocess.run(cmd, cwd=cwd, check=True, env={**os.environ, **(env or {})})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-generate", action="store_true")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    if not args.skip_generate:
        sh([sys.executable, "data_gen/generate.py", "--seed", str(args.seed)], ROOT)
    env = {"DBT_PROFILES_DIR": str(ROOT / "dbt"), "WAREHOUSE_PATH": str(ROOT / "data" / "warehouse.duckdb"),
           "RAW_DIR": str(ROOT / "data" / "raw")}
    sh(["dbt", "build", "--quiet"], ROOT / "dbt", env)

    from onchain_analytics import db, report
    import build_report

    con = db.connect(ROOT / "data" / "warehouse.duckdb", read_only=False)
    results = report.run_analysis(con, ROOT / "data" / "ground_truth.json")
    con.close()
    out = ROOT / "reports" / "output"
    report.save(results, out / "results.json")
    R = __import__("json").loads((out / "results.json").read_text())
    (out / f"daily_report_{R['as_of']}.md").write_text(build_report.render_markdown(R))
    (out / "latest_report.md").write_text(build_report.render_markdown(R))
    (out / "dashboard.html").write_text(build_report.render_html(R))
    print(f"\nreport    -> {out / 'latest_report.md'}\ndashboard -> {out / 'dashboard.html'}")


if __name__ == "__main__":
    main()
