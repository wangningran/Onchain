"""Orchestrates every analysis on top of the dbt marts and returns one JSON-able results dict
that the Markdown report and the HTML dashboard are rendered from. Also writes the wallet flags
back to the warehouse (analysis_* tables) so BI tools see the same "clean" definitions."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import abtest, anomaly, cohorts, db, defi, funnel, segmentation, sybil, tokenomics

DEMO_SUPPLY = 1_000_000_000


def _f(x):
    """numpy/pandas scalars -> plain python for JSON."""
    if isinstance(x, (np.floating, float)):
        return None if np.isnan(x) else float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (pd.Timestamp,)):
        return str(x.date())
    return x


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: _f(v) for k, v in r.items()} for r in df.to_dict("records")]


def pct_change(a, b):
    return (a - b) / b if b else float("nan")


def run_analysis(con, ground_truth_path: Path | None = None) -> dict:
    R: dict = {}
    wallets = db.query(con, "select * from dim_wallets")
    swaps = db.query(con, "select * from fct_swaps")
    daily = db.query(con, "select * from fct_protocol_daily order by day")
    pool_daily = db.query(con, "select * from fct_pool_daily order by day")
    funnel_daily = db.query(con, "select * from fct_funnel_daily")
    exp_users = db.query(con, "select * from fct_experiment_users")
    channels = db.query(con, "select * from fct_channel_performance")
    claims = db.query(con, "select * from fct_airdrop_claims")
    balances = db.query(con, "select * from fct_token_balances")
    holders_daily = db.query(con, "select * from fct_token_holders_daily order by day")
    transfers = db.query(con, "select * from int_token_transfers where symbol = 'DEMO'")
    labels = db.query(con, "select * from stg_labels")
    prices = db.query(con, "select * from stg_prices_daily")

    daily["day"] = pd.to_datetime(daily["day"])
    swaps["block_date"] = pd.to_datetime(swaps["block_date"])
    as_of = daily["day"].max()
    R["as_of"] = str(as_of.date())
    R["window"] = [str(daily["day"].min().date()), str(as_of.date())]

    # ---------------- 1. data quality: sybil / wash / bot flags ----------------
    flags, clusters, wash = sybil.flag_wallets(wallets, swaps)
    db.write_table(con, "analysis_wallet_flags", flags)
    db.write_table(con, "analysis_sybil_clusters", clusters)
    fl = flags.set_index("wallet")
    swaps["is_sybil"] = fl["is_sybil"].reindex(swaps["trader"]).fillna(False).values
    swaps["is_wash"] = fl["is_wash"].reindex(swaps["trader"]).fillna(False).values
    swaps["segment"] = np.select([~swaps["is_user"], swaps["is_wash"] | swaps["is_sybil"]],
                                 ["bots & contracts", "sybil & wash"], default="clean users")
    clean = swaps[swaps["segment"] == "clean users"]

    comp = (swaps.pivot_table(index="block_date", columns="segment", values="amount_usd", aggfunc="sum")
            .reindex(columns=["clean users", "sybil & wash", "bots & contracts"]).fillna(0))
    clean_dau = clean.groupby("block_date")["trader"].nunique()
    first_clean = clean.groupby("trader")["block_date"].min()
    clean_new = first_clean.value_counts().sort_index()
    u = swaps[swaps["is_user"]]
    demo_sell = (u.loc[u["token_sold_symbol"] == "DEMO"].groupby("block_date")["amount_usd"].sum()
                 .sub(u.loc[u["token_bought_symbol"] == "DEMO"].groupby("block_date")["amount_usd"].sum(), fill_value=0))
    daily = daily.set_index("day")
    daily["demo_net_sell_usd"] = demo_sell.reindex(daily.index).fillna(0)
    daily["clean_active_traders"] = clean_dau.reindex(daily.index).fillna(0)
    daily["clean_new_traders"] = clean_new.reindex(daily.index).fillna(0)
    daily["clean_volume_usd"] = comp["clean users"].reindex(daily.index).fillna(0)
    daily = daily.reset_index()

    sybil_wallets = set(flags.loc[flags["is_sybil"], "wallet"])
    july = wallets[pd.to_datetime(wallets["first_swap_date"]).dt.month == 7]
    R["data_quality"] = dict(
        sybil_clusters=int(clusters["is_sybil_cluster"].sum()) if len(clusters) else 0,
        sybil_wallets=len(sybil_wallets),
        wash_wallets=int(flags["is_wash"].sum()),
        wash_volume_usd=float(swaps.loc[swaps["is_wash"], "amount_usd"].sum()),
        sybil_volume_usd=float(swaps.loc[swaps["is_sybil"], "amount_usd"].sum()),
        bot_volume_share=float(swaps.loc[~swaps["is_user"], "amount_usd"].sum() / swaps["amount_usd"].sum()),
        reported_users=int((wallets["wallet_type"] == "user").sum()),
        clean_users=int(flags["is_clean_user"].sum()),
        july_new_wallets=int(len(july)),
        july_new_sybil_share=float(july["wallet"].isin(sybil_wallets).mean()),
        peak_reported_dau=int(daily["active_traders"].max()),
        peak_reported_dau_day=str(daily.loc[daily["active_traders"].idxmax(), "day"].date()),
        peak_clean_dau_that_day=int(daily.loc[daily["active_traders"].idxmax(), "clean_active_traders"]),
        clusters=_records(clusters.head(10)[["funder", "n_wallets", "funding_window_h", "headless_share",
                                              "median_swap_usd", "median_span_days", "rules_hit", "is_sybil_cluster"]]) if len(clusters) else [],
        wash=_records(wash.head(5)[["trader", "pool_name", "n_swaps", "gross_usd", "net_usd", "net_ratio", "funder"]]),
    )

    # ---------------- 2. KPIs: last 30d vs previous 30d ----------------
    last = daily[daily["day"] > as_of - pd.Timedelta(days=30)]
    prev = daily[(daily["day"] <= as_of - pd.Timedelta(days=30)) & (daily["day"] > as_of - pd.Timedelta(days=60))]
    k = {}
    for name, col, agg in [("volume_usd", "volume_usd", "sum"), ("clean_volume_usd", "clean_volume_usd", "sum"),
                           ("fees_usd", "fees_usd", "sum"), ("avg_clean_dau", "clean_active_traders", "mean"),
                           ("avg_reported_dau", "active_traders", "mean"), ("clean_new_traders", "clean_new_traders", "sum")]:
        a, b = getattr(last[col], agg)(), getattr(prev[col], agg)()
        k[name] = dict(value=float(a), prev=float(b), change=pct_change(a, b))
    k["tvl_usd"] = dict(value=float(daily["tvl_usd"].iloc[-1]), prev=float(daily["tvl_usd"].iloc[-31]),
                        change=pct_change(daily["tvl_usd"].iloc[-1], daily["tvl_usd"].iloc[-31]))
    k["fee_apr_30d"] = dict(value=float(last["fees_usd"].sum() / last["tvl_usd"].mean() * 365 / len(last)))
    R["kpis"] = k

    # ---------------- 3. anomalies + attribution ----------------
    anoms = anomaly.detect_anomalies(daily, {"volume_usd": "level", "clean_volume_usd": "level", "tvl_usd": "pct_change",
                                             "demo_net_sell_usd": "level",
                                             "clean_active_traders": "level", "active_traders": "level",
                                             "new_traders": "level", "net_liquidity_flow_usd": "level"})
    attributions = []
    for d in sorted(set(anoms.loc[anoms["metric"] == "volume_usd", "day"])):
        attributions.append(anomaly.attribute_volume_day(swaps, d, flags))
    big = tokenomics.large_transfers(transfers, labels, DEMO_SUPPLY)
    pool_addrs = set(pool_daily["pool_address"])
    big = big[~big["from_label"].isin(["cex_hot_wallet", "mev_bot"]) & ~big["to_label"].isin(["cex_hot_wallet", "mev_bot"])
              & ~big["to_address"].isin(pool_addrs) & ~big["from_address"].isin(pool_addrs)]
    R["anomalies"] = dict(
        flagged=_records(anoms.assign(day=anoms["day"].astype(str))),
        volume_attribution=attributions,
        large_token_transfers=_records(big.assign(block_time=big["block_time"].astype(str))[
            ["block_time", "from_address", "from_label", "to_address", "to_label", "amount", "share_of_supply"]]),
    )

    # ---------------- 4. retention & churn (clean users) ----------------
    first_week = clean.groupby("trader")["block_date"].min().dt.to_period("W-SUN").dt.start_time
    act = clean[["trader", "block_date"]].drop_duplicates().copy()
    act["week"] = act["block_date"].dt.to_period("W-SUN").dt.start_time
    act = act.drop_duplicates(["trader", "week"])
    act["cohort_week"] = first_week.reindex(act["trader"]).values
    act["weeks_since_first"] = ((act["week"] - act["cohort_week"]).dt.days // 7).astype(int)
    long = act.groupby(["cohort_week", "weeks_since_first"])["trader"].nunique().rename("active_wallets").reset_index()
    sizes = long[long["weeks_since_first"] == 0].set_index("cohort_week")["active_wallets"]
    long["cohort_size"] = sizes.reindex(long["cohort_week"]).values
    long["retention_rate"] = long["active_wallets"] / long["cohort_size"]
    # drop the partial last week from the curve
    long = long[long["cohort_week"] + pd.to_timedelta(long["weeks_since_first"] * 7 + 6, unit="D") <= as_of]
    mat = cohorts.retention_matrix(long, max_weeks=12)
    curve = cohorts.average_retention_curve(long, max_weeks=12)
    churn = cohorts.monthly_churn(clean)
    clean_w = wallets[wallets["wallet"].isin(flags.loc[flags["is_clean_user"], "wallet"])]
    R["retention"] = dict(
        curve={int(i): float(v) for i, v in curve.items()},
        matrix=[dict(cohort_week=str(i.date()), cohort_size=int(r["cohort_size"]),
                     **{f"w{int(c)}": (None if pd.isna(r[c]) else float(r[c])) for c in mat.columns if c != "cohort_size"})
                for i, r in mat.iterrows()],
        monthly_churn=_records(churn),
        dormant_share_30d=cohorts.dormant_share(clean_w, as_of),
        one_and_done_share=float((clean_w["n_active_days"] == 1).mean()),
    )

    # ---------------- 5. acquisition channels ----------------
    ch = channels.copy()
    ch["w_d30"] = ch["d30_retention"] * ch["new_traders"]
    ch["w_ltv"] = ch["ltv_30d_fees_usd"] * ch["new_traders"]
    ch["has_full_window"] = ch["d30_retention"].notna()
    g = ch.groupby("channel").agg(new_traders=("new_traders", "sum"), spend_usd=("spend_usd", "sum"))
    full = ch[ch["has_full_window"]].groupby("channel").agg(n=("new_traders", "sum"), w_d30=("w_d30", "sum"), w_ltv=("w_ltv", "sum"))
    g["cac_usd"] = g["spend_usd"] / g["new_traders"]
    g["d30_retention"] = full["w_d30"] / full["n"]
    g["ltv_30d_fees_usd"] = full["w_ltv"] / full["n"]
    g["ltv_cac"] = np.where(g["cac_usd"] > 0, g["ltv_30d_fees_usd"] / g["cac_usd"], np.nan)
    R["channels"] = _records(g.reset_index().sort_values("new_traders", ascending=False))

    # ---------------- 6. funnel & experiment ----------------
    ft = funnel.funnel_table(funnel_daily)
    step, rate = funnel.biggest_dropoff(ft.iloc[0])
    ft_ret = funnel.funnel_table(funnel_daily, by=["is_returning"])
    quoted = exp_users[exp_users["quoted"] == 1]
    a, b = quoted[quoted["variant"] == "A"], quoted[quoted["variant"] == "B"]
    res = abtest.two_proportion_test(int(a["submitted"].sum()), len(a), int(b["submitted"].sum()), len(b))
    srm = abtest.srm_check(int((exp_users["variant"] == "A").sum()), int((exp_users["variant"] == "B").sum()))
    mde = abtest.minimum_detectable_effect(min(len(a), len(b)), res.rate_a)
    # session-level (for comparison; overstates precision because sessions are clustered by user)
    fd = funnel_daily[funnel_daily["experiment_variant"].isin(["A", "B"])].groupby("experiment_variant")[["quoted", "submitted"]].sum()
    sess = abtest.two_proportion_test(int(fd.loc["A", "submitted"]), int(fd.loc["A", "quoted"]),
                                      int(fd.loc["B", "submitted"]), int(fd.loc["B", "quoted"]))
    monthly_quotes = float(last.shape[0] and funnel_daily[pd.to_datetime(funnel_daily["day"]) > as_of - pd.Timedelta(days=30)]["quoted"].sum())
    conf_rate = ft.iloc[0]["submitted_to_confirmed"]
    avg_fee = float(clean["lp_fee_usd"].mean())
    extra_swaps = monthly_quotes * sess.abs_lift * conf_rate
    R["funnel"] = dict(overall=_records(ft)[0], by_returning=_records(ft_ret), biggest_dropoff=dict(step=step, rate=rate))
    R["experiment"] = dict(user_level=res.as_dict(), session_level=sess.as_dict(), srm=srm, mde_abs=mde,
                           projected_extra_swaps_per_month=extra_swaps,
                           projected_extra_lp_fees_per_month=extra_swaps * avg_fee,
                           projected_extra_volume_per_month=extra_swaps * float(clean["amount_usd"].mean()))

    # ---------------- 7. segmentation ----------------
    cw = clean_w.copy()
    cw["tier"] = segmentation.value_tier(cw["volume_usd"]).astype(str)
    cw["behaviour"] = segmentation.behaviour_segment(cw)
    rfm = segmentation.rfm(cw, as_of)
    tiers = segmentation.segment_summary(cw, "tier")
    beh = segmentation.segment_summary(cw, "behaviour")
    R["segments"] = dict(tiers=_records(tiers), behaviour=_records(beh),
                         rfm=_records(rfm["rfm_segment"].value_counts().rename_axis("segment").reset_index(name="wallets")))
    db.write_table(con, "analysis_user_segments", cw[["wallet", "tier", "behaviour"]].merge(rfm, on="wallet"))

    # ---------------- 8. tokenomics ----------------
    demo_px = prices[prices["symbol"] == "DEMO"].assign(day=lambda x: pd.to_datetime(x["day"])).set_index("day")["price_usd"]
    airdrop_day = pd.Timestamp("2026-08-01")
    ae = tokenomics.airdrop_effectiveness(claims, flags, float(demo_px.get(airdrop_day, np.nan)))
    R["tokenomics"] = dict(
        concentration=tokenomics.concentration_report(balances),
        holders_start=int(holders_daily["holders"].iloc[0]), holders_end=int(holders_daily["holders"].iloc[-1]),
        holders_series=[dict(day=str(r.day), holders=int(r.holders)) for r in holders_daily.itertuples()],
        airdrop=_records(ae),
        demo_price_change_airdrop_week=float(demo_px[airdrop_day + pd.Timedelta(days=7)] / demo_px[airdrop_day - pd.Timedelta(days=1)] - 1),
        balances_by_type=_records(balances.groupby("holder_type")["balance"].sum().sort_values(ascending=False)
                                  .div(DEMO_SUPPLY).rename("share").reset_index()),
    )

    # ---------------- 9. DeFi: TVL, fees, LP economics ----------------
    pools = []
    for p in pool_daily["pool_name"].unique():
        e = defi.lp_economics(pool_daily, p)
        e["breakeven_daily_volume"] = defi.breakeven_daily_volume(e["avg_tvl_usd"], e["impermanent_loss"], e["days"])
        e["actual_avg_daily_volume"] = float(pool_daily.loc[pool_daily["pool_name"] == p, "volume_usd"].mean())
        pools.append(e)
    liq = db.query(con, "select provider, sum(case when event_type='add' then amount_usd else -amount_usd end) net "
                        "from int_liquidity_events where pool_name='WETH-USDC' group by 1 order by 2 desc")
    adds = db.query(con, "select provider, sum(amount_usd) a from int_liquidity_events where pool_name='WETH-USDC' "
                         "and event_type='add' group by 1 order by 2 desc")
    tvl_drop = daily.set_index("day")["tvl_usd"].pct_change().idxmin()
    R["defi"] = dict(
        pools=pools,
        top_lp_share_of_deposits=float(adds["a"].iloc[0] / adds["a"].sum()),
        biggest_tvl_drop_day=str(tvl_drop.date()),
        biggest_tvl_drop_pct=float(daily.set_index("day")["tvl_usd"].pct_change().min()),
        lp_count=int((liq["net"] > 0).sum()),
    )

    # ---------------- 10. chart series for the dashboard ----------------
    comp_r = comp.reindex(pd.to_datetime(daily["day"])).fillna(0)
    R["series"] = dict(
        day=[str(d.date()) for d in daily["day"]],
        tvl_usd=daily["tvl_usd"].round(0).tolist(),
        fee_apr=daily["fee_apr"].round(5).tolist(),
        volume_clean=comp_r["clean users"].round(0).tolist(),
        volume_suspicious=comp_r["sybil & wash"].round(0).tolist(),
        volume_bots=comp_r["bots & contracts"].round(0).tolist(),
        dau_reported=daily["active_traders"].astype(int).tolist(),
        dau_clean=daily["clean_active_traders"].astype(int).tolist(),
    )

    # ---------------- 11. validation against ground truth (synthetic data only) ----------------
    if ground_truth_path and Path(ground_truth_path).exists():
        t = json.loads(Path(ground_truth_path).read_text())
        flagged_days = set(anoms["day"].astype(str))
        R["validation"] = dict(
            sybil=sybil.precision_recall(sybil_wallets, set(t["sybil_wallets"])),
            wash=sybil.precision_recall(set(flags.loc[flags["is_wash"], "wallet"]), set(t["wash_wallets"])),
            anomalies=[dict(**a, detected=a["date"] in flagged_days
                            or (a["type"] == "team_token_unlock" and any(str(x["block_time"]).startswith(a["date"]) for x in R["anomalies"]["large_token_transfers"])))
                       for a in t["anomalies"]],
            experiment_truth=t["experiment"],
        )

    R["insights"] = build_insights(R)
    return R


def build_insights(R: dict) -> list[dict]:
    """Turn numbers into hypotheses + actions. Each insight: finding, evidence, hypothesis, action, impact."""
    dq, ex, tk, df_ = R["data_quality"], R["experiment"], R["tokenomics"], R["defi"]
    ch = {c["channel"]: c for c in R["channels"]}
    out = []
    ul = ex["user_level"]
    out.append(dict(
        priority="P0", area="产品 / 实验",
        finding=f"新版 Swap 界面(B)将「报价→提交」转化率从 {ul['rate_a']:.1%} 提升到 {ul['rate_b']:.1%}"
                f"(相对 +{ul['rel_lift']:.1%},p={ul['p_value']:.1g},95% CI [{ul['ci_low']:+.1%}, {ul['ci_high']:+.1%}])",
        evidence=f"用户级分析,A={ul['n_a']:,} / B={ul['n_b']:,} 名报价用户;SRM 检验 p={ex['srm']['p_value']:.2f}(分流正常);"
                 f"MDE={ex['mde_abs']:.1%}",
        hypothesis="路由预览降低了用户对滑点/价格的不确定性,从而减少报价后的放弃。",
        action="全量上线 B;下一步实验:在报价页展示 gas 预估 + 失败重试引导(提交→确认环节)。",
        impact=f"预计每月 +{ex['projected_extra_swaps_per_month']:,.0f} 笔成功交易,"
               f"约 +${ex['projected_extra_volume_per_month']/1e6:,.2f}M 交易量 / +${ex['projected_extra_lp_fees_per_month']:,.0f} LP 手续费。",
    ))
    sy = next((a for a in tk["airdrop"] if a["recipient_type"] == "sybil"), None)
    ge = next((a for a in tk["airdrop"] if a["recipient_type"] == "genuine"), None)
    if sy and ge:
        out.append(dict(
            priority="P0", area="增长 / 代币经济",
            finding=f"7 月(Quest 活动期)新增钱包中 {dq['july_new_sybil_share']:.0%} 是女巫;女巫拿走了 {sy['share_of_airdrop']:.0%} 的空投,"
                    f"24 小时内抛售 {sy['sell_through_24h']:.0%}(真实用户 7 天仅卖出 {ge['sell_through_7d']:.0%})",
            evidence=f"{dq['sybil_clusters']} 个资金簇共 {dq['sybil_wallets']} 个钱包:同一地址在 <2h 内注资、从未使用前端、"
                     f"单笔 ~$30、活跃 <1 个月;空投后一周 DEMO 价格 {tk['demo_price_change_airdrop_week']:+.0%}。",
            hypothesis="积分规则只按交易笔数计分,脚本批量刷量的边际成本几乎为零。",
            action="空投前跑资金簇 + 行为规则过滤;积分按手续费/持有时长加权并设上限;空投改为线性解锁(如 30 天),或与后续活跃挂钩。",
            impact=f"若剔除女巫,可把 ~{sy['claimed_tokens']/1e6:,.1f}M DEMO(按发放时价格约 ${sy['claimed_usd_at_t0']/1e3:,.0f}k)留给真实用户,并降低上线首周抛压。",
        ))
    q, tw, org = ch.get("quest_platform", {}), ch.get("twitter_ads", {}), ch.get("organic", {})
    if q and tw:
        out.append(dict(
            priority="P1", area="增长 / 投放",
            finding=f"Twitter Ads 的 CAC ${tw['cac_usd']:.0f} 而 30 日 LTV(手续费)仅 ${tw['ltv_30d_fees_usd']:.2f};"
                    f"Quest 平台 D30 留存 {q['d30_retention']:.0%},明显低于自然流量的 {org.get('d30_retention', float('nan')):.0%}",
            evidence="渠道归因 = 钱包首次连接时所属会话的 UTM 渠道;LTV = 首笔交易后 30 天内产生的 LP 手续费。",
            hypothesis="付费渠道带来的是一次性的「任务型」用户;自然流量与 KOL 用户本身有交易需求。",
            action="把 Twitter 预算的一部分转给 KOL 推荐(按留存后付费 / CPA 计价);Quest 任务改成「连续 4 周每周交易」这类留存型任务。",
            impact="以 LTV/CAC 衡量,当前所有付费渠道都 < 1:应把 30 日 LTV 换成 90 日 + 协议收入口径后重新评估,再决定是否继续投放。",
        ))
    weth = next(p for p in df_["pools"] if p["pool"] == "WETH-USDC")
    out.append(dict(
        priority="P1", area="DeFi / 流动性",
        finding=f"WETH-USDC 池的被动 LP 在观察期内跑输持币:手续费收益 {weth['fee_yield']:.2%},无常损失 {weth['impermanent_loss']:.2%},"
                f"净收益 {weth['net_vs_hodl']:+.2%}",
        evidence=f"池子日均成交/TVL 仅 {weth['volume_tvl_ratio']:.2%};要覆盖无常损失,日均成交需要 ~${weth['breakeven_daily_volume']/1e6:,.1f}M,"
                 f"实际只有 ${weth['actual_avg_daily_volume']/1e6:,.2f}M。",
        hypothesis="流动性相对交易需求过剩(资本效率低),LP 收益不足,资金存在持续流出的风险。",
        action="评估集中流动性(V3 式区间)或动态费率;DEMO 激励应从「补贴 TVL」改为「补贴真实成交量」(如交易挖矿 + 反刷量过滤)。",
        impact="资本效率提高后,同样的 TVL 可以给出更好的报价深度,LP APR 也会上升。",
    ))
    out.append(dict(
        priority="P1", area="风险 / 流动性集中度",
        finding=f"{df_['biggest_tvl_drop_day']} 单日 TVL {df_['biggest_tvl_drop_pct']:.0%}:单一做市商一次撤出了一半的 WETH-USDC 流动性",
        evidence=f"该地址提供了 WETH-USDC 累计存入流动性的 {df_['top_lp_share_of_deposits']:.0%};异常检测(稳健 z 分数)在当日报警。",
        hypothesis="TVL 高度依赖单一做市商,对方策略一变,滑点和用户体验就会立刻恶化。",
        action="设置「单一 LP 占比 > 30%」监控与告警;与做市商签锁定期 / 分批撤出协议;用激励吸引更分散的长尾 LP。",
        impact="降低尾部风险:撤出发生在交易高峰时,大额交易的滑点会显著扩大。",
    ))
    out.append(dict(
        priority="P2", area="数据质量 / 指标口径",
        finding=f"约 ${dq['wash_volume_usd']/1e6:,.1f}M 交易量(9 月初 3 天)来自同一资金源的 {dq['wash_wallets']} 个钱包在 DEMO 池里对倒刷量",
        evidence="两个钱包净头寸 / 总成交 < 1%,每天 150 笔往返交易,同一地址注资。",
        hypothesis="可能是为了刷 DEMO 的成交量排名,或做 CEX 上币前的数据包装。",
        action="对外报告与内部 KPI 统一采用「清洗后」口径(剔除机器人、女巫和刷量);在交易排行榜 / 激励计算中接入刷量过滤。",
        impact=f"报告口径的峰值 DAU 为 {dq['peak_reported_dau']:,}({dq['peak_reported_dau_day']}),同日清洗后只有 {dq['peak_clean_dau_that_day']:,}:口径差异会直接误导决策。",
    ))
    ret = R["retention"]
    out.append(dict(
        priority="P2", area="留存",
        finding=f"{ret['one_and_done_share']:.0%} 的真实用户只在一天内交易过;首周后留存 {ret['curve'].get(1, float('nan')):.0%},第 8 周 {ret['curve'].get(8, float('nan')):.0%}",
        evidence="周同期群(按首笔交易周),已剔除机器人 / 女巫 / 刷量钱包。",
        hypothesis="首单之后缺少触发回访的理由(没有限价单、没有持仓 / 收益看板)。",
        action="上线限价单 / DCA 和「我的持仓」页;对首单后 7 天没回来的钱包做定向推送(如 Push Protocol、邮件订阅)。",
        impact="第 1 周留存每提高 5 个百分点,按当前新增速度,每月多出数百个活跃交易者。",
    ))
    return out


def _json_default(x):
    if isinstance(x, np.generic):
        return x.item()
    if isinstance(x, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(x).date())
    if isinstance(x, set):
        return sorted(x)
    return str(x)


def _clean_nan(o):
    if isinstance(o, dict):
        return {k: _clean_nan(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean_nan(v) for v in o]
    if isinstance(o, float) and np.isnan(o):
        return None
    return o


def save(results: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean_nan(results), indent=2, ensure_ascii=False, default=_json_default))
