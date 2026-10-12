"""User segmentation: value tiers, behavioural segments and RFM."""
from __future__ import annotations

import numpy as np
import pandas as pd

TIERS = [(0, 1_000, "shrimp (<$1k)"), (1_000, 10_000, "fish ($1k-10k)"),
         (10_000, 100_000, "dolphin ($10k-100k)"), (100_000, np.inf, "whale (>$100k)")]


def value_tier(volume_usd: pd.Series) -> pd.Series:
    bins = [t[0] for t in TIERS] + [np.inf]
    return pd.cut(volume_usd, bins=bins, labels=[t[2] for t in TIERS], right=False)


def behaviour_segment(w: pd.DataFrame) -> pd.Series:
    return np.select(
        [w["lp_added_usd"] > 0, w["n_active_days"] >= 8, w["n_active_days"] >= 2],
        ["liquidity provider", "power trader", "occasional trader"],
        default="one-and-done",
    )


def rfm(w: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Recency (days since last swap), Frequency (active days), Monetary (fees generated) scored 1-5."""
    out = w[["wallet"]].copy()
    out["recency_days"] = (as_of - pd.to_datetime(w["last_swap_at"])).dt.days
    out["frequency"] = w["n_active_days"]
    out["monetary"] = w["volume_usd"] * 0.003
    score = lambda s, asc: pd.qcut(s.rank(method="first", ascending=asc), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    out["r"] = score(out["recency_days"], False)  # recent = high
    out["f"] = score(out["frequency"], True)
    out["m"] = score(out["monetary"], True)
    out["rfm_segment"] = np.select(
        [(out.r >= 4) & (out.f >= 4) & (out.m >= 4), (out.r >= 4) & (out.f <= 2), (out.r <= 2) & (out.f >= 4) & (out.m >= 3),
         (out.r <= 2) & (out.f <= 2)],
        ["champions", "new / promising", "at risk (was valuable)", "hibernating"],
        default="needs attention",
    )
    return out


def segment_summary(w: pd.DataFrame, col: str) -> pd.DataFrame:
    g = w.groupby(col, observed=True).agg(wallets=("wallet", "count"), volume_usd=("volume_usd", "sum"),
                                          median_active_days=("n_active_days", "median"))
    g["wallet_share"] = g["wallets"] / g["wallets"].sum()
    g["volume_share"] = g["volume_usd"] / g["volume_usd"].sum()
    return g.reset_index().sort_values("volume_usd", ascending=False)
