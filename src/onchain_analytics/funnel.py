"""Conversion funnel (off-chain events joined to on-chain receipts)."""
from __future__ import annotations

import pandas as pd

STEPS = ["sessions", "connected", "quoted", "submitted", "confirmed"]


def funnel_table(funnel_daily: pd.DataFrame, by: list[str] | None = None) -> pd.DataFrame:
    by = by or []
    g = funnel_daily.groupby(by)[STEPS].sum() if by else funnel_daily[STEPS].sum().to_frame().T
    out = g.copy()
    for prev, cur in zip(STEPS[:-1], STEPS[1:]):
        out[f"{prev}_to_{cur}"] = g[cur] / g[prev]
    out["overall"] = g["confirmed"] / g["sessions"]
    return out.reset_index() if by else out.reset_index(drop=True)


def biggest_dropoff(funnel_row: pd.Series) -> tuple[str, float]:
    rates = {f"{a}->{b}": funnel_row[f"{a}_to_{b}"] for a, b in zip(STEPS[:-1], STEPS[1:])}
    step = min(rates, key=rates.get)
    return step, float(rates[step])
