"""Sybil-cluster and wash-trading detection.

No labels are used. Sybil farms are found as *funding clusters*: many wallets seeded by the
same address in a short window that then behave identically (tiny, uniform swaps straight
to the contract with no front-end session, then claim-and-dump). Wash traders are wallets whose
trading nets out to ~0 while generating large gross volume.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

SYBIL_RULES = {
    "big_cluster": "cluster size >= 20 wallets with one funder",
    "fast_funding": "all wallets funded within 24h",
    "headless": ">= 90% of wallets never used the front-end",
    "uniform_tiny_swaps": "median swap < $100 and robust dispersion (IQR/median) < 0.8",
    "low_activity_span": "median wallet active < 40 days",
}


def funder_clusters(wallets: pd.DataFrame, swaps: pd.DataFrame) -> pd.DataFrame:
    """One row per funder with cluster-level behavioural features + rule hits."""
    w = wallets.dropna(subset=["funder"]).copy()
    if w.empty:
        return pd.DataFrame()
    w["span_days"] = (pd.to_datetime(w["last_swap_at"]) - pd.to_datetime(w["first_swap_at"])).dt.days
    s = swaps[swaps["trader"].isin(w["wallet"])].merge(w[["wallet", "funder"]], left_on="trader", right_on="wallet")
    # IQR/median rather than CV: one claim-and-dump sell per wallet would blow up a std-based CV
    swap_feats = s.groupby("funder")["amount_usd"].agg(
        median_swap_usd="median",
        swap_dispersion=lambda x: (x.quantile(0.75) - x.quantile(0.25)) / x.median() if x.median() else np.nan)
    c = w.groupby("funder").agg(
        n_wallets=("wallet", "count"),
        funding_window_h=("funded_at", lambda x: (pd.to_datetime(x).max() - pd.to_datetime(x).min()).total_seconds() / 3600),
        headless_share=("has_web_session", lambda x: 1 - x.mean()),
        median_span_days=("span_days", "median"),
        total_volume_usd=("volume_usd", "sum"),
    ).join(swap_feats)
    c["big_cluster"] = c["n_wallets"] >= 20
    c["fast_funding"] = c["funding_window_h"] <= 24
    c["headless"] = c["headless_share"] >= 0.9
    c["uniform_tiny_swaps"] = (c["median_swap_usd"] < 100) & (c["swap_dispersion"] < 0.8)
    c["low_activity_span"] = c["median_span_days"] < 40
    c["rules_hit"] = c[list(SYBIL_RULES)].sum(axis=1)
    c["is_sybil_cluster"] = c["big_cluster"] & (c["rules_hit"] >= 4)
    return c.reset_index().sort_values("n_wallets", ascending=False)


def wash_traders(swaps: pd.DataFrame, wallets: pd.DataFrame, min_swaps: int = 50,
                 min_volume_usd: float = 100_000, max_net_ratio: float = 0.05) -> pd.DataFrame:
    """Wallets whose USD buys and sells per pool almost cancel out while gross volume is large.
    Wallets sharing a funder with a flagged wallet are pulled in (wash rings use >1 address)."""
    s = swaps[swaps["is_user"]].copy()
    # direction w.r.t. the pool's non-quote token: +usd when buying the risk token, - when selling
    quote = {"USDC", "USDT", "WETH"}
    risk_bought = ~s["token_bought_symbol"].isin(quote) | ((s["token_bought_symbol"] == "WETH") & s["token_sold_symbol"].isin({"USDC", "USDT"}))
    s["signed_usd"] = np.where(risk_bought, s["amount_usd"], -s["amount_usd"])
    g = s.groupby(["trader", "pool_name"]).agg(n_swaps=("amount_usd", "size"), gross_usd=("amount_usd", "sum"),
                                               net_usd=("signed_usd", "sum"),
                                               active_days=("block_date", "nunique")).reset_index()
    g["net_ratio"] = g["net_usd"].abs() / g["gross_usd"]
    g["swaps_per_active_day"] = g["n_swaps"] / g["active_days"]
    flagged = g[(g["n_swaps"] >= min_swaps) & (g["gross_usd"] >= min_volume_usd) & (g["net_ratio"] <= max_net_ratio)]
    funders = wallets.set_index("wallet")["funder"]
    ring_funders = set(funders.reindex(flagged["trader"]).dropna())
    ring = set(wallets.loc[wallets["funder"].isin(ring_funders), "wallet"]) | set(flagged["trader"])
    out = g[g["trader"].isin(ring)].copy()
    out["funder"] = funders.reindex(out["trader"]).values
    return out.sort_values("gross_usd", ascending=False)


def flag_wallets(wallets: pd.DataFrame, swaps: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    clusters = funder_clusters(wallets, swaps)
    sybil_funders = set(clusters.loc[clusters["is_sybil_cluster"], "funder"]) if not clusters.empty else set()
    wash = wash_traders(swaps, wallets)
    flags = wallets[["wallet", "wallet_type", "funder"]].copy()
    flags["is_sybil"] = flags["funder"].isin(sybil_funders)
    flags["is_wash"] = flags["wallet"].isin(set(wash["trader"]))
    flags["is_clean_user"] = (flags["wallet_type"] == "user") & ~flags["is_sybil"] & ~flags["is_wash"]
    return flags, clusters, wash


def precision_recall(flagged: set, truth: set) -> dict:
    tp = len(flagged & truth)
    return dict(tp=tp, fp=len(flagged - truth), fn=len(truth - flagged),
                precision=tp / len(flagged) if flagged else float("nan"),
                recall=tp / len(truth) if truth else float("nan"))
