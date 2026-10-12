"""Integration tests: the detectors must recover what the simulator planted.
Requires `python pipeline.py` to have been run (skipped otherwise)."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "reports" / "output" / "results.json"
pytestmark = pytest.mark.skipif(not RESULTS.exists(), reason="run `python pipeline.py` first")


@pytest.fixture(scope="module")
def R():
    return json.loads(RESULTS.read_text())


def test_sybil_detection(R):
    v = R["validation"]["sybil"]
    assert v["precision"] >= 0.95 and v["recall"] >= 0.95


def test_wash_detection(R):
    v = R["validation"]["wash"]
    assert v["precision"] == 1.0 and v["recall"] == 1.0


@pytest.mark.parametrize("kind", ["whale_lp_exit_tvl_drop", "airdrop_claim_and_dump", "team_token_unlock"])
def test_key_anomalies_detected(R, kind):
    assert all(a["detected"] for a in R["validation"]["anomalies"] if a["type"] == kind)


def test_wash_days_majority_detected(R):
    w = [a["detected"] for a in R["validation"]["anomalies"] if a["type"] == "wash_trading_volume_spike"]
    assert sum(w) >= 2


def test_experiment_ci_covers_truth(R):
    t = R["validation"]["experiment_truth"]
    s = R["experiment"]["session_level"]
    assert s["ci_low"] <= t["treatment"] - t["control"] <= s["ci_high"]
    assert not R["experiment"]["srm"]["srm_detected"]


def test_tvl_drop_found(R):
    assert R["defi"]["biggest_tvl_drop_day"] == "2026-09-12"
    assert R["defi"]["biggest_tvl_drop_pct"] < -0.2
