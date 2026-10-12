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
    L = [f"# DemoSwap 协议日报 · {R['as_of']}", "",
         f"> 观察窗口 {R['window'][0]} → {R['window'][1]};KPI 为近 30 天 vs 前 30 天。「清洗后」= 剔除 MEV 机器人 / 协议地址 / 女巫簇 / 刷量钱包。", "",
         "## 核心指标", "", "| 指标 | 数值 | 环比 |", "|---|---:|---:|",
         f"| TVL | {usd(K['tvl_usd']['value'])} | {delta(K['tvl_usd']['change'])} |",
         f"| 30 日交易量(全部) | {usd(K['volume_usd']['value'])} | {delta(K['volume_usd']['change'])} |",
         f"| 30 日交易量(清洗后) | {usd(K['clean_volume_usd']['value'])} | {delta(K['clean_volume_usd']['change'])} |",
         f"| 30 日 LP 手续费 | {usd(K['fees_usd']['value'])} | {delta(K['fees_usd']['change'])} |",
         f"| 日均活跃交易者(报告口径 / 清洗后) | {K['avg_reported_dau']['value']:,.0f} / {K['avg_clean_dau']['value']:,.0f} | {delta(K['avg_clean_dau']['change'])} |",
         f"| 30 日新增真实用户 | {K['clean_new_traders']['value']:,.0f} | {delta(K['clean_new_traders']['change'])} |",
         f"| Fee APR(近 30 日年化) | {pct(K['fee_apr_30d']['value'], 2)} | |", "",
         "## 关键发现与建议", ""]
    for i, s in enumerate(R["insights"], 1):
        L += [f"### {i}. [{s['priority']}] {s['finding']}", "",
              f"- **领域**:{s['area']}", f"- **证据**:{s['evidence']}", f"- **假设**:{s['hypothesis']}",
              f"- **建议**:{s['action']}", f"- **预期影响**:{s['impact']}", ""]
    L += ["## 异常报警", "", "| 日期 | 指标 | z | 方向 |", "|---|---|---:|---|"]
    for a in R["anomalies"]["flagged"]:
        L.append(f"| {a['day']} | {a['metric']} | {a['zscore']:.1f} | {'激增' if a['direction']=='spike' else '骤降'} |")
    L += ["", "**交易量异常归因**(当日 Top3 地址):", ""]
    for a in R["anomalies"]["volume_attribution"]:
        L.append(f"- {a['day']}:Top3 贡献 {pct(a['top_share'],0)},类型 {' / '.join(a['top_flags'])},主要在 {a['top_pool']}")
    if R["anomalies"]["large_token_transfers"]:
        L += ["", "**大额代币转移**(≥ 0.5% 供应,不含铸造与 CEX / 机器人库存):", ""]
        for t in R["anomalies"]["large_token_transfers"]:
            L.append(f"- {t['block_time'][:16]}  {t['from_label'] or t['from_address'][:10]} → {t['to_label'] or t['to_address'][:10]}:{t['amount']/1e6:,.1f}M DEMO({pct(t['share_of_supply'],2)})")
    L += ["", "## 实验", "",
          f"- 用户级:A {pct(ex['user_level']['rate_a'])} vs B {pct(ex['user_level']['rate_b'])},p={ex['user_level']['p_value']:.1g},"
          f"95% CI [{pct(ex['user_level']['ci_low'])}, {pct(ex['user_level']['ci_high'])}]",
          f"- 会话级(仅供参考,同一用户的会话彼此相关,会低估方差):A {pct(ex['session_level']['rate_a'])} vs B {pct(ex['session_level']['rate_b'])}",
          f"- SRM 检验 p={ex['srm']['p_value']:.2f} → {'⚠ 分流异常' if ex['srm']['srm_detected'] else '分流正常'};当前样本 MDE = {pct(ex['mde_abs'])}", "",
          "## 数据质量", "",
          f"- 识别出 {dq['sybil_clusters']} 个女巫资金簇({dq['sybil_wallets']} 个钱包)和 {dq['wash_wallets']} 个刷量钱包(刷量额 {usd(dq['wash_volume_usd'])})",
          f"- 机器人交易量占比 {pct(dq['bot_volume_share'])};报告口径用户 {dq['reported_users']:,} → 清洗后 {dq['clean_users']:,}"]
    if "validation" in R:
        V = R["validation"]
        L += ["", "## 模型验证(模拟数据的隐藏真值)", "",
              f"- 女巫检测 precision {pct(V['sybil']['precision'])} / recall {pct(V['sybil']['recall'])}",
              f"- 刷量检测 precision {pct(V['wash']['precision'])} / recall {pct(V['wash']['recall'])}",
              f"- 实验:真实单次报价提交率 {pct(V['experiment_truth']['control'])} → {pct(V['experiment_truth']['treatment'])};"
              f"会话级估计提升 {pct(ex['session_level']['abs_lift'])}(CI [{pct(ex['session_level']['ci_low'])}, {pct(ex['session_level']['ci_high'])}])",
              "- 异常检出:" + ",".join(f"{a['date']} {a['type']} {'✓' if a['detected'] else '✗'}" for a in V["anomalies"])]
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
