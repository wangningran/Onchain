"""Unit tests for the analysis library (no warehouse needed)."""
import math

import numpy as np
import pandas as pd
import pytest

from onchain_analytics import abtest, anomaly, cohorts, defi, funnel, tokenomics
import evm_tools


# ---------- EVM decoding
@pytest.mark.parametrize("sig,topic", [
    ("Transfer(address,address,uint256)", "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"),
    ("Swap(address,uint256,uint256,uint256,uint256,address)", "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"),
    ("Sync(uint112,uint112)", "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"),
])
def test_keccak_topics(sig, topic):
    assert evm_tools.topic0(sig) == topic


def test_selector_and_decode():
    assert evm_tools.selector("transfer(address,uint256)") == "0xa9059cbb"
    data = "0x" + format(10**18, "064x") + "0" * 24 + "a0b86991c6218b36c1d19d4a2e9eb0ce3606eb48" + format((1 << 256) - 5, "064x")
    assert evm_tools.decode_static(data, ["uint256", "address", "int256"]) == [10**18, "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", -5]


# ---------- A/B
def test_two_proportion_known_values():
    r = abtest.two_proportion_test(200, 1000, 250, 1000)
    assert r.abs_lift == pytest.approx(0.05)
    assert r.z == pytest.approx(2.68, abs=0.01)
    assert r.p_value == pytest.approx(0.0074, abs=0.0005)
    assert r.ci_low < 0.05 < r.ci_high and r.significant


def test_srm():
    assert not abtest.srm_check(5000, 5050)["srm_detected"]
    assert abtest.srm_check(5000, 5600)["srm_detected"]


def test_mde_sample_size_roundtrip():
    n = abtest.required_sample_size(0.36, 0.02)
    assert abtest.minimum_detectable_effect(n, 0.36) == pytest.approx(0.02, rel=0.01)


# ---------- anomaly
def test_robust_z_flags_spike_not_noise():
    rng = np.random.default_rng(0)
    s = pd.Series(100 + rng.normal(0, 5, 120))
    s.iloc[100] = 200
    df = pd.DataFrame({"day": pd.date_range("2026-01-01", periods=120), "m": s})
    a = anomaly.detect_anomalies(df, {"m": "level"})
    assert list(a["day"]) == [pd.Timestamp("2026-01-01") + pd.Timedelta(days=100)]


# ---------- tokenomics
def test_concentration_metrics():
    assert tokenomics.gini([1, 1, 1, 1]) == pytest.approx(0)
    assert tokenomics.gini([0, 0, 0, 10]) == pytest.approx(0)  # zeros dropped: single holder
    assert tokenomics.gini([1, 2, 3, 4]) == pytest.approx(0.25)
    assert tokenomics.nakamoto_coefficient([50, 30, 20]) == 2
    assert tokenomics.nakamoto_coefficient([60, 30, 10]) == 1
    assert tokenomics.top_n_share([5, 3, 2], 1) == pytest.approx(0.5)


# ---------- defi
def test_impermanent_loss():
    assert defi.impermanent_loss(1.0) == 0
    assert defi.impermanent_loss(4.0) == pytest.approx(-0.2)  # classic: 4x price move => -20%
    assert defi.impermanent_loss(0.25) == pytest.approx(-0.2)


# ---------- cohorts & funnel
def test_monthly_churn():
    swaps = pd.DataFrame({"trader": ["a", "b", "a", "c"], "block_date": ["2026-01-05", "2026-01-06", "2026-02-01", "2026-02-02"]})
    c = cohorts.monthly_churn(swaps)
    assert c.iloc[0]["churn_rate"] == pytest.approx(0.5)


def test_funnel_rates():
    df = pd.DataFrame({"sessions": [100], "connected": [50], "quoted": [40], "submitted": [10], "confirmed": [9]})
    t = funnel.funnel_table(df)
    assert t.iloc[0]["quoted_to_submitted"] == pytest.approx(0.25)
    assert funnel.biggest_dropoff(t.iloc[0])[0] == "quoted->submitted"
