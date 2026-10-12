"""Token distribution & airdrop effectiveness."""
from __future__ import annotations

import numpy as np
import pandas as pd


def gini(x) -> float:
    x = np.sort(np.asarray(x, dtype=float))
    x = x[x > 0]
    n = len(x)
    if n == 0:
        return float("nan")
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def top_n_share(x, n: int = 10) -> float:
    x = np.sort(np.asarray(x, dtype=float))[::-1]
    return float(x[:n].sum() / x.sum())


def nakamoto_coefficient(x, threshold: float = 0.5) -> int:
    """Smallest number of holders that together control > threshold of supply."""
    x = np.sort(np.asarray(x, dtype=float))[::-1]
    return int(np.searchsorted(np.cumsum(x) / x.sum(), threshold, side="right") + 1)


def concentration_report(balances: pd.DataFrame, exclude_types=("amm_pool", "cex_hot_wallet", "airdrop_distributor")) -> dict:
    """Concentration among *economic* holders (exclude pools, exchanges, undistributed contracts)."""
    b = balances[~balances["holder_type"].isin(exclude_types)]["balance"]
    return dict(holders=int((b > 0).sum()), gini=gini(b), top10_share=top_n_share(b, 10),
                top100_share=top_n_share(b, 100), nakamoto=nakamoto_coefficient(b))


def airdrop_effectiveness(claims: pd.DataFrame, flags: pd.DataFrame, price_usd: float) -> pd.DataFrame:
    c = claims.merge(flags[["wallet", "is_sybil"]], left_on="recipient", right_on="wallet", how="left")
    c["recipient_type"] = np.where(c["is_sybil"].fillna(False), "sybil", "genuine")
    g = c.groupby("recipient_type").agg(
        recipients=("recipient", "count"),
        claimed_tokens=("claimed_amount", "sum"),
        median_minutes_to_claim=("minutes_to_claim", "median"),
        sold_24h_tokens=("sold_24h", "sum"),
        sold_7d_tokens=("sold_7d", "sum"),
        sold_7d_usd=("sold_7d_usd", "sum"),
    )
    g["claimed_usd_at_t0"] = g["claimed_tokens"] * price_usd
    g["sell_through_24h"] = g["sold_24h_tokens"] / g["claimed_tokens"]
    g["sell_through_7d"] = g["sold_7d_tokens"] / g["claimed_tokens"]
    g["share_of_airdrop"] = g["claimed_tokens"] / g["claimed_tokens"].sum()
    return g.reset_index()


def large_transfers(transfers: pd.DataFrame, labels: pd.DataFrame, supply: float, threshold: float = 0.005) -> pd.DataFrame:
    """Transfers >= `threshold` of supply, excluding mints: unlocks, treasury moves, CEX deposits."""
    t = transfers[(transfers["amount"] >= threshold * supply) &
                  (transfers["from_address"] != "0x0000000000000000000000000000000000000000")].copy()
    lab = labels.set_index("address")["label"]
    t["from_label"] = lab.reindex(t["from_address"]).values
    t["to_label"] = lab.reindex(t["to_address"]).values
    t["share_of_supply"] = t["amount"] / supply
    return t.sort_values("block_time")
