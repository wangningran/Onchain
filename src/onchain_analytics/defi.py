"""DeFi LP economics: impermanent loss vs fee income for constant-product (x*y=k) pools."""
from __future__ import annotations

import math

import pandas as pd


def impermanent_loss(price_ratio: float) -> float:
    """IL of a 50/50 V2 position vs. holding, when relative price moves by `price_ratio` (p1/p0). <= 0."""
    return 2 * math.sqrt(price_ratio) / (1 + price_ratio) - 1


def lp_economics(pool_daily: pd.DataFrame, pool_name: str) -> dict:
    """Passive-LP outcome over the whole window: cumulative fee yield vs IL from the reserve-implied price."""
    p = pool_daily[pool_daily["pool_name"] == pool_name].sort_values("day")
    price = p["reserve0"] / p["reserve1"]  # token0 per token1
    ratio = float(price.iloc[-1] / price.iloc[0])
    fee_yield = float((p["fees_usd"] / p["tvl_usd"]).sum())  # sum of daily fee returns
    days = len(p)
    il = impermanent_loss(ratio)
    return dict(pool=pool_name, days=days, price_ratio=ratio, impermanent_loss=il, fee_yield=fee_yield,
                fee_apr=fee_yield * 365 / days, net_vs_hodl=fee_yield + il,
                avg_tvl_usd=float(p["tvl_usd"].mean()), volume_tvl_ratio=float(p["volume_usd"].sum() / p["tvl_usd"].mean() / days))


def breakeven_daily_volume(tvl_usd: float, il: float, days: int, fee_rate: float = 0.003) -> float:
    """Average daily volume at which fees would have offset the observed IL."""
    return abs(il) * tvl_usd / (fee_rate * days)
