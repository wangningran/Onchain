"""Render the daily report (Markdown, for Slack/Notion/email) and the HTML dashboard from the
analysis results. Usage:  python reports/build_report.py [--results reports/output/results.json]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def usd(v):
    if v is None:
        return "–"
    a = abs(v)
    return f"${v/1e6:,.2f}M" if a >= 1e6 else f"${v/1e3:,.1f}k" if a >= 1e3 else f"${v:,.2f}"


def pct(v, d=1):
    return "–" if v is None else f"{v*100:.{d}f}%"


def delta(v):
    return "" if v is None else f"({'▲' if v >= 0 else '▼'} {abs(v)*100:.1f}%)"


def render_markdown(R: dict) -> str:
    K, dq, ex = R["kpis"], R["data_quality"], R["experiment"]
    L = [f"# DemoSwap daily protocol report · {R['as_of']}", "",
         f"> Window {R['window'][0]} → {R['window'][1]}; KPIs compare the last 30 days with the previous 30. "
         "\"Clean\" = excluding MEV bots, protocol addresses, sybil clusters and wash-trading wallets. "
         "Data is simulated (see README).", "",
         "## Key metrics", "", "| Metric | Value | vs previous 30d |", "|---|---:|---:|",
         f"| TVL | {usd(K['tvl_usd']['value'])} | {delta(K['tvl_usd']['change'])} |",
         f"| 30d volume (all) | {usd(K['volume_usd']['value'])} | {delta(K['volume_usd']['change'])} |",
         f"| 30d volume (clean) | {usd(K['clean_volume_usd']['value'])} | {delta(K['clean_volume_usd']['change'])} |",
         f"| 30d LP fees | {usd(K['fees_usd']['value'])} | {delta(K['fees_usd']['change'])} |",
         f"| Avg daily active traders (reported / clean) | {K['avg_reported_dau']['value']:,.0f} / {K['avg_clean_dau']['value']:,.0f} | {delta(K['avg_clean_dau']['change'])} |",
         f"| 30d new real users | {K['clean_new_traders']['value']:,.0f} | {delta(K['clean_new_traders']['change'])} |",
         f"| Fee APR (30d annualised) | {pct(K['fee_apr_30d']['value'], 2)} | |", "",
         "## Findings and recommendations", ""]
    for i, s in enumerate(R["insights"], 1):
        L += [f"### {i}. [{s['priority']}] {s['finding']}", "",
              f"- **Area:** {s['area']}", f"- **Evidence:** {s['evidence']}", f"- **Hypothesis:** {s['hypothesis']}",
              f"- **Recommendation:** {s['action']}", f"- **Expected impact:** {s['impact']}", ""]
    L += ["## Anomaly alerts", "", "| Date | Metric | z | Direction |", "|---|---|---:|---|"]
    for a in R["anomalies"]["flagged"]:
        L.append(f"| {a['day']} | {a['metric']} | {a['zscore']:.1f} | {'spike' if a['direction']=='spike' else 'drop'} |")
    L += ["", "**Volume anomaly attribution** (top 3 addresses that day):", ""]
    for a in R["anomalies"]["volume_attribution"]:
        L.append(f"- {a['day']}: top 3 contributed {pct(a['top_share'],0)}, types {' / '.join(a['top_flags'])}, mainly in {a['top_pool']}")
    if R["anomalies"]["large_token_transfers"]:
        L += ["", "**Large token transfers** (≥ 0.5% of supply, excluding mints and CEX / bot inventory):", ""]
        for t in R["anomalies"]["large_token_transfers"]:
            L.append(f"- {t['block_time'][:16]}  {t['from_label'] or t['from_address'][:10]} → {t['to_label'] or t['to_address'][:10]}: "
                     f"{t['amount']/1e6:,.1f}M DEMO ({pct(t['share_of_supply'],2)})")
    L += ["", "## Experiment", "",
          f"- User level: A {pct(ex['user_level']['rate_a'])} vs B {pct(ex['user_level']['rate_b'])}, p={ex['user_level']['p_value']:.1g}, "
          f"95% CI [{pct(ex['user_level']['ci_low'])}, {pct(ex['user_level']['ci_high'])}]",
          f"- Session level (reference only; sessions of the same user are correlated, so variance is understated): "
          f"A {pct(ex['session_level']['rate_a'])} vs B {pct(ex['session_level']['rate_b'])}",
          f"- SRM check p={ex['srm']['p_value']:.2f} → {'⚠ assignment problem' if ex['srm']['srm_detected'] else 'assignment healthy'}; "
          f"MDE at current sample = {pct(ex['mde_abs'])}", "",
          "## Data quality", "",
          f"- Found {dq['sybil_clusters']} sybil funding clusters ({dq['sybil_wallets']} wallets) and {dq['wash_wallets']} wash-trading wallets "
          f"({usd(dq['wash_volume_usd'])} wash volume)",
          f"- Bot share of volume {pct(dq['bot_volume_share'])}; reported users {dq['reported_users']:,} → clean {dq['clean_users']:,}"]
    if "validation" in R:
        V = R["validation"]
        L += ["", "## Model validation (against the simulator's hidden ground truth)", "",
              f"- Sybil detection precision {pct(V['sybil']['precision'])} / recall {pct(V['sybil']['recall'])}",
              f"- Wash-trading detection precision {pct(V['wash']['precision'])} / recall {pct(V['wash']['recall'])}",
              f"- Experiment: true per-quote submit rate {pct(V['experiment_truth']['control'])} → {pct(V['experiment_truth']['treatment'])}; "
              f"estimated session-level lift {pct(ex['session_level']['abs_lift'])} (CI [{pct(ex['session_level']['ci_low'])}, {pct(ex['session_level']['ci_high'])}])",
              "- Anomalies detected: " + ", ".join(f"{a['date']} {a['type']} {'✓' if a['detected'] else '✗'}" for a in V["anomalies"])]
    return "\n".join(L) + "\n"


def render_html(R: dict) -> str:
    tpl = (HERE / "templates" / "dashboard.html").read_text()
    data = json.dumps(R, ensure_ascii=False).replace("</", "<\\/")
    return tpl.replace("__DATA__", data)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(HERE / "output" / "results.json"))
    ap.add_argument("--out", default=str(HERE / "output"))
    args = ap.parse_args()
    R = json.loads(Path(args.results).read_text())
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    md = out / f"daily_report_{R['as_of']}.md"
    md.write_text(render_markdown(R))
    (out / "latest_report.md").write_text(render_markdown(R))
    (out / "dashboard.html").write_text(render_html(R))
    print(f"wrote {md}, {out / 'dashboard.html'}")


if __name__ == "__main__":
    main()
