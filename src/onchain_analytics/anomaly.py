"""Metric anomaly detection with a trailing robust z-score (median / MAD), resistant to the very
outliers it's trying to find and to the heavy tails typical of on-chain metrics."""
from __future__ import annotations

import numpy as np
import pandas as pd


def robust_zscore(s: pd.Series, window: int = 28, min_periods: int = 14) -> pd.Series:
    hist = s.shift(1)  # trailing window, excludes the current point
    med = hist.rolling(window, min_periods=min_periods).median()
    mad = (hist - med).abs().rolling(window, min_periods=min_periods).median()
    scale = 1.4826 * mad.replace(0, np.nan)
    return (s - med) / scale


def detect_anomalies(daily: pd.DataFrame, metrics: dict[str, str], threshold: float = 4.0,
                     date_col: str = "day", window: int = 28) -> pd.DataFrame:
    """`metrics` maps column -> transform ('level' or 'pct_change'). Returns flagged rows."""
    d = daily.sort_values(date_col).reset_index(drop=True)
    out = []
    for col, transform in metrics.items():
        series = d[col].pct_change() if transform == "pct_change" else d[col]
        z = robust_zscore(series, window=window)
        hits = d.loc[z.abs() > threshold, [date_col]].copy()
        if hits.empty:
            continue
        hits["metric"] = col
        hits["transform"] = transform
        hits["value"] = d.loc[hits.index, col]
        hits["observed"] = series[hits.index]
        hits["zscore"] = z[hits.index]
        hits["direction"] = np.where(hits["zscore"] > 0, "spike", "drop")
        out.append(hits)
    if not out:
        return pd.DataFrame(columns=[date_col, "metric", "transform", "value", "observed", "zscore", "direction"])
    return pd.concat(out).sort_values([date_col, "metric"]).reset_index(drop=True)


def attribute_volume_day(swaps: pd.DataFrame, day, flags: pd.DataFrame | None = None, top: int = 3) -> dict:
    """Root-cause hint for a volume anomaly: how concentrated was that day's volume, and in whom?"""
    d = swaps[pd.to_datetime(swaps["block_date"]) == pd.Timestamp(day)]
    by = d.groupby("trader")["amount_usd"].sum().sort_values(ascending=False)
    total = by.sum()
    top_w = by.head(top)
    info = dict(day=str(pd.Timestamp(day).date()), volume_usd=float(total), top_traders=list(top_w.index),
                top_share=float(top_w.sum() / total) if total else float("nan"),
                top_pool=d.groupby("pool_name")["amount_usd"].sum().idxmax() if len(d) else None)
    if flags is not None:
        f = flags.set_index("wallet").reindex(top_w.index)
        info["top_flags"] = [("wash" if r.is_wash else "sybil" if r.is_sybil else r.wallet_type) for r in f.itertuples()]
    return info
