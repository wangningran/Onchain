"""Cohort retention and churn."""
from __future__ import annotations

import pandas as pd


def retention_matrix(cohort_long: pd.DataFrame, max_weeks: int = 12) -> pd.DataFrame:
    """fct_cohort_retention_weekly (long) -> cohort x weeks-since matrix of retention rates."""
    df = cohort_long[cohort_long["weeks_since_first"] <= max_weeks]
    m = df.pivot(index="cohort_week", columns="weeks_since_first", values="retention_rate").sort_index()
    m.insert(0, "cohort_size", df.groupby("cohort_week")["cohort_size"].first())
    return m


def average_retention_curve(cohort_long: pd.DataFrame, max_weeks: int = 12) -> pd.Series:
    """Cohort-size-weighted retention by week, only using cohorts old enough to observe each week."""
    df = cohort_long[cohort_long["weeks_since_first"] <= max_weeks]
    g = df.groupby("weeks_since_first").agg(active=("active_wallets", "sum"), size=("cohort_size", "sum"))
    return g["active"] / g["size"]


def monthly_churn(swaps: pd.DataFrame, wallet_col: str = "trader", date_col: str = "block_date") -> pd.DataFrame:
    """Share of wallets active in month M that are NOT active in M+1 (last month dropped: not observable)."""
    s = swaps[[wallet_col, date_col]].copy()
    s["month"] = pd.to_datetime(s[date_col]).dt.to_period("M")
    active = s.drop_duplicates([wallet_col, "month"]).groupby("month")[wallet_col].apply(set)
    rows = []
    months = list(active.index)
    for m, nxt in zip(months[:-1], months[1:]):
        base = active[m]
        retained = len(base & active[nxt])
        rows.append(dict(month=str(m), active=len(base), retained_next_month=retained,
                         churn_rate=1 - retained / len(base) if base else float("nan")))
    return pd.DataFrame(rows)


def dormant_share(wallets: pd.DataFrame, as_of: pd.Timestamp, churn_days: int = 30) -> float:
    """Share of wallets whose last swap is older than `churn_days` as of `as_of`."""
    last = pd.to_datetime(wallets["last_swap_at"])
    return float((last < as_of - pd.Timedelta(days=churn_days)).mean())
