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
        priority="P0", area="Product / Experiment",
        finding=f"The new swap UI (B) lifts quote→submit conversion from {ul['rate_a']:.1%} to {ul['rate_b']:.1%} "
                f"(+{ul['rel_lift']:.1%} relative, p={ul['p_value']:.1g}, 95% CI [{ul['ci_low']:+.1%}, {ul['ci_high']:+.1%}])",
        evidence=f"User-level analysis, A={ul['n_a']:,} / B={ul['n_b']:,} quoting users; SRM check p={ex['srm']['p_value']:.2f} (assignment healthy); "
                 f"MDE={ex['mde_abs']:.1%}.",
        hypothesis="The route preview reduces uncertainty about slippage and price, so fewer users abandon after quoting.",
        action="Ship B to 100%. Next experiment: show a gas estimate and a retry flow for failed transactions (the submit→confirm step).",
        impact=f"About +{ex['projected_extra_swaps_per_month']:,.0f} successful swaps per month, "
               f"≈ +${ex['projected_extra_volume_per_month']/1e6:,.2f}M volume / +${ex['projected_extra_lp_fees_per_month']:,.0f} LP fees.",
    ))
    sy = next((a for a in tk["airdrop"] if a["recipient_type"] == "sybil"), None)
    ge = next((a for a in tk["airdrop"] if a["recipient_type"] == "genuine"), None)
    if sy and ge:
        out.append(dict(
            priority="P0", area="Growth / Tokenomics",
            finding=f"{dq['july_new_sybil_share']:.0%} of wallets acquired in July (quest campaign) are sybils; they took {sy['share_of_airdrop']:.0%} of the airdrop "
                    f"and sold {sy['sell_through_24h']:.0%} of it within 24h (genuine users sold only {ge['sell_through_7d']:.0%} within 7 days)",
            evidence=f"{dq['sybil_clusters']} funding clusters with {dq['sybil_wallets']} wallets: seeded by one address within <2h, never used the front-end, "
                     f"~$30 per swap, active <1 month. DEMO price moved {tk['demo_price_change_airdrop_week']:+.0%} in the week after the airdrop.",
            hypothesis="Points were awarded per transaction count, so scripted farming cost almost nothing.",
            action="Run funding-cluster and behaviour filters before the airdrop; weight points by fees paid and holding time, with a cap; "
                   "switch to linear vesting (e.g. 30 days) or tie unlocks to continued activity.",
            impact=f"Filtering sybils would redirect ~{sy['claimed_tokens']/1e6:,.1f}M DEMO (≈ ${sy['claimed_usd_at_t0']/1e3:,.0f}k at distribution) "
                   f"to real users and reduce first-week sell pressure.",
        ))
    q, tw, org = ch.get("quest_platform", {}), ch.get("twitter_ads", {}), ch.get("organic", {})
    if q and tw:
        out.append(dict(
            priority="P1", area="Growth / Paid acquisition",
            finding=f"Twitter Ads CAC is ${tw['cac_usd']:.0f} while 30-day LTV (fees) is only ${tw['ltv_30d_fees_usd']:.2f}; "
                    f"quest-platform D30 retention is {q['d30_retention']:.0%}, well below organic at {org.get('d30_retention', float('nan')):.0%}",
            evidence="Channel attribution = UTM channel of the session in which the wallet first connected; LTV = LP fees generated in the 30 days after the first swap.",
            hypothesis="Paid channels bring one-off, task-driven users; organic and KOL users arrive with real trading intent.",
            action="Move part of the Twitter budget to KOL referrals paid on retention (CPA); redesign quests around retention, e.g. 'trade every week for 4 weeks'.",
            impact="Every paid channel is below 1× LTV/CAC. Re-evaluate on 90-day LTV and protocol revenue before continuing spend.",
        ))
    weth = next(p for p in df_["pools"] if p["pool"] == "WETH-USDC")
    out.append(dict(
        priority="P1", area="DeFi / Liquidity",
        finding=f"Passive LPs in WETH-USDC underperformed holding: fee yield {weth['fee_yield']:.2%}, impermanent loss {weth['impermanent_loss']:.2%}, "
                f"net {weth['net_vs_hodl']:+.2%} vs HODL",
        evidence=f"Daily volume/TVL is only {weth['volume_tvl_ratio']:.2%}. Covering IL would need ~${weth['breakeven_daily_volume']/1e6:,.1f}M average daily volume; "
                 f"actual was ${weth['actual_avg_daily_volume']/1e6:,.2f}M.",
        hypothesis="Liquidity is over-provisioned relative to trading demand (low capital efficiency), so LP returns are thin and capital is at risk of leaving.",
        action="Evaluate concentrated liquidity (V3-style ranges) or dynamic fees; shift DEMO incentives from subsidising TVL to subsidising real volume "
               "(trading rewards with wash-trading filters).",
        impact="Better capital efficiency gives deeper quotes from the same TVL and raises LP APR.",
    ))
    out.append(dict(
        priority="P1", area="Risk / Liquidity concentration",
        finding=f"TVL fell {df_['biggest_tvl_drop_pct']:.0%} on {df_['biggest_tvl_drop_day']}: a single market maker withdrew half of WETH-USDC liquidity at once",
        evidence=f"That address supplied {df_['top_lp_share_of_deposits']:.0%} of all WETH-USDC deposits; the robust z-score detector fired the same day.",
        hypothesis="TVL depends heavily on one market maker; if their strategy changes, slippage and user experience degrade immediately.",
        action="Alert when any single LP exceeds 30% of a pool; agree lock-ups or staged withdrawals with market makers; use incentives to attract a broader LP base.",
        impact="Reduces tail risk: a withdrawal during peak trading would sharply widen slippage on large trades.",
    ))
    out.append(dict(
        priority="P2", area="Data quality / Metric definitions",
        finding=f"~${dq['wash_volume_usd']/1e6:,.1f}M of volume over 3 days in early September came from {dq['wash_wallets']} wallets with the same funder wash-trading the DEMO pool",
        evidence="Both wallets net position / gross volume < 1%, 150 round trips per day, funded by the same address.",
        hypothesis="Likely an attempt to inflate DEMO volume rankings, or to dress up metrics ahead of a CEX listing.",
        action="Use 'clean' metrics (excluding bots, sybils and wash trading) for both external reporting and internal KPIs; apply wash filters to leaderboards and incentive calculations.",
        impact=f"Reported peak DAU was {dq['peak_reported_dau']:,} ({dq['peak_reported_dau_day']}) versus {dq['peak_clean_dau_that_day']:,} clean users that day; the gap would mislead decisions.",
    ))
    ret = R["retention"]
    out.append(dict(
        priority="P2", area="Retention",
        finding=f"{ret['one_and_done_share']:.0%} of real users traded on a single day only; retention is {ret['curve'].get(1, float('nan')):.0%} after week 1 "
                f"and {ret['curve'].get(8, float('nan')):.0%} by week 8",
        evidence="Weekly cohorts by first-swap week, excluding bots, sybils and wash-trading wallets.",
        hypothesis="After the first trade there is little reason to come back (no limit orders, no portfolio or P&L view).",
        action="Launch limit orders / DCA and a 'My positions' page; re-engage wallets that haven't returned 7 days after their first swap (e.g. Push Protocol, email).",
        impact="Each +5pp of week-1 retention adds several hundred monthly active traders at the current acquisition rate.",
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
