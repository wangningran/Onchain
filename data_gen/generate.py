"""
Synthetic on-chain + off-chain data generator for "DemoSwap", a Uniswap-V2-style DEX on Ethereum.

Why synthetic?  The pipeline must run offline / in CI, and every analysis needs *ground truth*
to be validated against (planted sybil clusters, wash trading, a TVL shock, an A/B effect).
The raw tables deliberately mimic Dune's raw schemas so the dbt models are a realistic
decode-from-logs exercise rather than a toy:

  raw_transactions   ~ ethereum.transactions   (hash, block_time, "from", "to", value, gas, success)
  raw_logs           ~ ethereum.logs           (contract_address, topic0..3, data as hex)
  raw_prices_daily   ~ prices.day
  raw_tokens/pools   ~ tokens.erc20 / Factory_evt_PairCreated
  raw_app_sessions   off-chain product analytics (Segment/Amplitude-like)
  raw_app_events
  raw_marketing_spend

Run:  python data_gen/generate.py --out data/raw
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------
START = datetime(2026, 5, 1, tzinfo=timezone.utc)
N_DAYS = 153  # 2026-05-01 .. 2026-09-30
BASE_BLOCK = 24_800_000

# Canonical event signatures -> topic0 (keccak256 of the signature)
TOPIC_SWAP = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822"  # Swap(address,uint256,uint256,uint256,uint256,address)
TOPIC_MINT = "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f"  # Mint(address,uint256,uint256)
TOPIC_BURN = "0xdccd412f0b1252819cb1fd330b93224ca42612892bb3f4f789976e6d81936496"  # Burn(address,uint256,uint256,address)
TOPIC_SYNC = "0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1"  # Sync(uint112,uint112)
TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"  # Transfer(address,address,uint256)

ZERO = "0x" + "0" * 40


def fake_address(label: str) -> str:
    return "0x" + hashlib.sha256(label.encode()).hexdigest()[:40]


TOKENS = {
    "USDC": {"address": "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", "decimals": 6},
    "USDT": {"address": "0xdac17f958d2ee523a2206206994597c13d831ec7", "decimals": 6},
    "WETH": {"address": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "decimals": 18},
    "DEMO": {"address": fake_address("DEMO governance token"), "decimals": 18},
}
ROUTER = fake_address("DemoSwap Router02")
FACTORY = fake_address("DemoSwap Factory")
AIRDROP_DISTRIBUTOR = fake_address("DEMO airdrop merkle distributor")
TEAM_VESTING = fake_address("DEMO team vesting")
TREASURY = fake_address("DemoSwap treasury")
INVESTORS = fake_address("DEMO investor custody")
ECOSYSTEM = fake_address("DEMO ecosystem fund")
MARKET_MAKER = fake_address("Genesis market maker / seed LP")
CEX_HOT_WALLET = fake_address("CEX hot wallet (arb bot inventory source)")

# Story calendar (ground truth)
QUEST_START, QUEST_END = datetime(2026, 7, 1, tzinfo=timezone.utc), datetime(2026, 7, 31, tzinfo=timezone.utc)
AIRDROP_DAY = datetime(2026, 8, 1, tzinfo=timezone.utc)
EXP_START, EXP_END = datetime(2026, 8, 1, tzinfo=timezone.utc), datetime(2026, 8, 31, tzinfo=timezone.utc)
TEAM_UNLOCK_DAY = datetime(2026, 9, 1, tzinfo=timezone.utc)
WASH_DAYS = [datetime(2026, 9, d, tzinfo=timezone.utc) for d in (5, 6, 7)]
LP_EXIT_DAY = datetime(2026, 9, 12, tzinfo=timezone.utc)

SUBMIT_RATE = {"A": 0.36, "B": 0.42, None: 0.36}  # quote -> submit; variant B = new route-preview UI
CHANNELS = {
    # mix share, retention tau (days), retention floor, daily spend usd
    "organic": (0.40, 60, 0.020, 0),
    "twitter_ads": (0.25, 25, 0.008, 1500),
    "kol_referral": (0.15, 35, 0.012, 800),
    "quest_platform": (0.20, 8, 0.003, 500),
}
FEE = 0.003


def topic_addr(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:]


def word(n: int) -> str:
    return format(int(n), "064x")


# --------------------------------------------------------------------------------------
# AMM pool
# --------------------------------------------------------------------------------------
@dataclass
class Pool:
    name: str
    address: str
    token0: str  # symbol
    token1: str
    r0: float = 0.0  # reserves in token units
    r1: float = 0.0

    @property
    def price1_in_0(self) -> float:  # how many token0 per token1
        return self.r0 / self.r1


@dataclass
class World:
    rng: np.random.Generator
    txs: list = field(default_factory=list)
    logs: list = field(default_factory=list)
    sessions: list = field(default_factory=list)
    events: list = field(default_factory=list)
    demo_bal: dict = field(default_factory=lambda: defaultdict(float))

    def new_address(self) -> str:
        return "0x" + self.rng.bytes(20).hex()

    def new_hash(self) -> str:
        return "0x" + self.rng.bytes(32).hex()


def make_pools() -> dict[str, Pool]:
    def ordered(a: str, b: str):
        return (a, b) if TOKENS[a]["address"] < TOKENS[b]["address"] else (b, a)

    pools = {}
    for name, (a, b) in {"WETH-USDC": ("WETH", "USDC"), "DEMO-WETH": ("DEMO", "WETH"), "USDC-USDT": ("USDC", "USDT")}.items():
        t0, t1 = ordered(a, b)
        pools[name] = Pool(name, fake_address(f"DemoSwap pair {name}"), t0, t1)
    return pools


# --------------------------------------------------------------------------------------
# Prices (exogenous "CEX" prices; arbitrage bots keep pools aligned)
# --------------------------------------------------------------------------------------
def make_prices(rng) -> pd.DataFrame:
    days = [START + timedelta(days=i) for i in range(N_DAYS + 1)]
    weth = [3200.0]
    demo = [0.060]
    for i in range(1, N_DAYS + 1):
        d = days[i]
        weth.append(weth[-1] * math.exp(rng.normal(0.0004, 0.03)))
        drift = 0.004 if d < QUEST_END else 0.0
        if AIRDROP_DAY <= d < AIRDROP_DAY + timedelta(days=8):
            drift = -0.045  # airdrop sell pressure
        if TEAM_UNLOCK_DAY <= d < TEAM_UNLOCK_DAY + timedelta(days=4):
            drift = -0.02
        demo.append(demo[-1] * math.exp(rng.normal(drift, 0.05)))
    rows = []
    for i, d in enumerate(days):
        rows += [
            (d.date(), "WETH", weth[i]),
            (d.date(), "DEMO", demo[i]),
            (d.date(), "USDC", 1.0 + rng.normal(0, 0.0003)),
            (d.date(), "USDT", 1.0 + rng.normal(0, 0.0005)),
        ]
    return pd.DataFrame(rows, columns=["day", "symbol", "price_usd"])


class PriceOracle:
    def __init__(self, prices: pd.DataFrame):
        self.p = {(r.day, r.symbol): r.price_usd for r in prices.itertuples()}

    def usd(self, symbol: str, ts: datetime) -> float:
        d0 = ts.date()
        d1 = (ts + timedelta(days=1)).date()
        frac = (ts - datetime(d0.year, d0.month, d0.day, tzinfo=timezone.utc)).total_seconds() / 86400
        a, b = self.p[(d0, symbol)], self.p.get((d1, symbol), self.p[(d0, symbol)])
        return a + (b - a) * frac


# --------------------------------------------------------------------------------------
# Tx / log emission
# --------------------------------------------------------------------------------------
def block_of(ts: datetime) -> int:
    return BASE_BLOCK + int((ts - START).total_seconds() // 12)


def emit_tx(w: World, ts, frm, to, value_eth=0.0, gas_used=130_000, success=True) -> str:
    h = w.new_hash()
    base_fee = 8 + 6 * math.sin((ts - START).total_seconds() / 86400 / 7) + w.rng.gamma(2, 2)
    w.txs.append(
        dict(
            block_number=block_of(ts), block_time=ts, hash=h, from_address=frm, to_address=to,
            value_wei=str(int(value_eth * 1e18)), gas_used=gas_used if success else int(gas_used * 0.4),
            gas_price_gwei=round(base_fee, 3), success=success,
        )
    )
    w._log_index = 0
    return h


def emit_log(w: World, ts, tx_hash, contract, topics, data_words):
    topics = list(topics) + [None] * (4 - len(topics))
    w.logs.append(
        dict(
            block_number=block_of(ts), block_time=ts, tx_hash=tx_hash, log_index=w._log_index,
            contract_address=contract, topic0=topics[0], topic1=topics[1], topic2=topics[2], topic3=topics[3],
            data="0x" + "".join(word(x) for x in data_words),
        )
    )
    w._log_index += 1


def raw(symbol: str, amount: float) -> int:
    return int(round(amount * 10 ** TOKENS[symbol]["decimals"]))


def demo_transfer(w: World, ts, tx_hash, frm, to, amount):
    if amount <= 0:
        return
    w.demo_bal[frm] -= amount
    w.demo_bal[to] += amount
    emit_log(w, ts, tx_hash, TOKENS["DEMO"]["address"], [TOPIC_TRANSFER, topic_addr(frm), topic_addr(to)], [raw("DEMO", amount)])


def sync(w, ts, h, pool: Pool):
    emit_log(w, ts, h, pool.address, [TOPIC_SYNC], [raw(pool.token0, pool.r0), raw(pool.token1, pool.r1)])


def do_swap(w: World, ts, trader, pool: Pool, token_in: str, amount_in: float, via=ROUTER, success=True) -> str | None:
    """Execute a constant-product swap with 0.3% fee and emit Swap + Sync (+ DEMO Transfer) logs."""
    if amount_in <= 0:
        return None
    h = emit_tx(w, ts, trader, via, gas_used=int(w.rng.normal(125_000, 8_000)), success=success)
    if not success:
        return h
    zero_for_one = token_in == pool.token0
    r_in, r_out = (pool.r0, pool.r1) if zero_for_one else (pool.r1, pool.r0)
    amount_out = amount_in * (1 - FEE) * r_out / (r_in + amount_in * (1 - FEE))
    token_out = pool.token1 if zero_for_one else pool.token0
    if zero_for_one:
        pool.r0 += amount_in
        pool.r1 -= amount_out
    else:
        pool.r1 += amount_in
        pool.r0 -= amount_out
    if token_in == "DEMO":
        demo_transfer(w, ts, h, trader, pool.address, amount_in)
    if token_out == "DEMO":
        demo_transfer(w, ts, h, pool.address, trader, amount_out)
    a0in, a1in = (raw(pool.token0, amount_in), 0) if zero_for_one else (0, raw(pool.token1, amount_in))
    a0out, a1out = (0, raw(pool.token1, amount_out)) if zero_for_one else (raw(pool.token0, amount_out), 0)
    sync(w, ts, h, pool)
    # Swap(sender indexed = router/bot contract, ..., to indexed = recipient)
    emit_log(w, ts, h, pool.address, [TOPIC_SWAP, topic_addr(via), topic_addr(trader if via == ROUTER else via)], [a0in, a1in, a0out, a1out])
    return h


def do_mint(w: World, ts, lp, pool: Pool, usd: float, oracle: PriceOracle):
    p0 = oracle.usd(pool.token0, ts)
    a0 = usd / 2 / p0
    a1 = a0 * pool.r1 / pool.r0 if pool.r0 > 0 else usd / 2 / oracle.usd(pool.token1, ts)
    h = emit_tx(w, ts, lp, ROUTER, gas_used=180_000)
    for sym, amt in ((pool.token0, a0), (pool.token1, a1)):
        if sym == "DEMO":
            demo_transfer(w, ts, h, lp, pool.address, amt)
    pool.r0 += a0
    pool.r1 += a1
    sync(w, ts, h, pool)
    emit_log(w, ts, h, pool.address, [TOPIC_MINT, topic_addr(ROUTER)], [raw(pool.token0, a0), raw(pool.token1, a1)])


def do_burn(w: World, ts, lp, pool: Pool, share: float):
    a0, a1 = pool.r0 * share, pool.r1 * share
    h = emit_tx(w, ts, lp, ROUTER, gas_used=170_000)
    pool.r0 -= a0
    pool.r1 -= a1
    for sym, amt in ((pool.token0, a0), (pool.token1, a1)):
        if sym == "DEMO":
            demo_transfer(w, ts, h, pool.address, lp, amt)
    sync(w, ts, h, pool)
    emit_log(w, ts, h, pool.address, [TOPIC_BURN, topic_addr(ROUTER), topic_addr(lp)], [raw(pool.token0, a0), raw(pool.token1, a1)])


# --------------------------------------------------------------------------------------
# Main simulation
# --------------------------------------------------------------------------------------
@dataclass
class User:
    wallet: str
    anon_id: str
    channel: str
    persona: str
    acq_day: int | None = None
    tau: float = 30
    floor: float = 0.01
    july_swaps: int = 0


def variant_for(anon_id: str, ts: datetime):
    if EXP_START <= ts < EXP_END + timedelta(days=1):
        return "B" if int(hashlib.md5(anon_id.encode()).hexdigest(), 16) % 2 else "A"
    return None


def simulate(seed: int = 7):
    rng = np.random.default_rng(seed)
    w = World(rng)
    w._log_index = 0
    prices = make_prices(rng)
    oracle = PriceOracle(prices)
    pools = make_pools()
    truth = defaultdict(list)

    # --- Genesis: DEMO supply + seed liquidity ---------------------------------------
    t0 = START + timedelta(minutes=1)
    h = emit_tx(w, t0, TREASURY, TOKENS["DEMO"]["address"], gas_used=900_000)
    for holder, amt in [(TREASURY, 250e6), (TEAM_VESTING, 200e6), (INVESTORS, 150e6), (AIRDROP_DISTRIBUTOR, 30e6),
                        (MARKET_MAKER, 50e6), (ECOSYSTEM, 70e6), (CEX_HOT_WALLET, 250e6)]:
        w.demo_bal[ZERO] += amt  # so ZERO nets to -supply, like a real mint
        demo_transfer(w, t0, h, ZERO, holder, amt)
    seed_tvl = {"WETH-USDC": 20e6, "DEMO-WETH": 4e6, "USDC-USDT": 8e6}
    for name, tvl in seed_tvl.items():
        p = pools[name]
        p.r0 = tvl / 2 / oracle.usd(p.token0, t0)
        p.r1 = tvl / 2 / oracle.usd(p.token1, t0)
        h = emit_tx(w, t0 + timedelta(minutes=5), MARKET_MAKER, ROUTER, gas_used=200_000)
        if "DEMO" in (p.token0, p.token1):
            demo_transfer(w, t0, h, MARKET_MAKER, p.address, p.r0 if p.token0 == "DEMO" else p.r1)
        sync(w, t0, h, p)
        emit_log(w, t0, h, p.address, [TOPIC_MINT, topic_addr(ROUTER)], [raw(p.token0, p.r0), raw(p.token1, p.r1)])

    # --- Populations -------------------------------------------------------------------
    users: list[User] = []
    pending: list[tuple[int, User]] = []  # connected but not yet converted prospects (retry day)
    whales = [User(w.new_address(), f"anon_{w.new_hash()[2:14]}", "organic", "whale", acq_day=int(rng.integers(0, 40)), tau=1e9, floor=0.35)
              for _ in range(40)]
    lps = [w.new_address() for _ in range(120)]
    bots = [(w.new_address(), fake_address(f"arb bot contract {i}")) for i in range(4)]
    truth["arb_bots"] = [b for b, _ in bots]

    sybil_funders = [w.new_address() for _ in range(8)]
    sybils: list[tuple[str, str, datetime]] = []  # wallet, funder, funded_at
    for f in sybil_funders:
        fund_day = QUEST_START + timedelta(days=int(rng.integers(0, 10)), hours=int(rng.integers(0, 20)))
        for _ in range(int(rng.integers(70, 130))):
            sybils.append((w.new_address(), f, fund_day + timedelta(seconds=int(rng.integers(0, 7200)))))
    truth["sybil_wallets"] = [s for s, _, _ in sybils]
    truth["sybil_funders"] = sybil_funders
    wash_funder = w.new_address()
    wash_wallets = [w.new_address(), w.new_address()]
    truth["wash_wallets"] = wash_wallets
    team_wallets = [w.new_address() for _ in range(4)]
    truth["team_wallets"] = team_wallets

    channel_names = list(CHANNELS)
    channel_mix = np.array([CHANNELS[c][0] for c in channel_names])

    def swap_intent(ts, user_wallet, kind):
        """Pick a pool/direction/size for a genuine user swap."""
        pool = pools[rng.choice(["WETH-USDC", "DEMO-WETH", "USDC-USDT"], p=[0.65, 0.2, 0.15])]
        usd = float(rng.lognormal(math.log(400 if kind != "whale" else 30_000), 1.1))
        if pool.name == "DEMO-WETH":
            usd = min(usd, 60_000)
            bal = w.demo_bal.get(user_wallet, 0)
            if bal > 0 and rng.random() < 0.6:
                token_in = "DEMO"
                amt = min(bal, usd / oracle.usd("DEMO", ts))
                return pool, token_in, amt
            token_in = "WETH"
        else:
            token_in = pool.token0 if rng.random() < 0.5 else pool.token1
        return pool, token_in, usd / oracle.usd(token_in, ts)

    def run_session(day_idx, ts, u: User | None, anon, channel, returning: bool):
        """Product funnel. Returns list of (ts, wallet, pool, token_in, amount, success) swap intents."""
        sid = f"s_{w.new_hash()[2:18]}"
        variant = variant_for(anon, ts)
        wallet = u.wallet if u else None
        w.sessions.append(dict(session_id=sid, anonymous_id=anon, session_start=ts, channel=channel,
                               utm_campaign=f"{channel}_{ts:%Y%m}" if channel != "organic" else None,
                               experiment_variant=variant, is_returning=returning))
        w.events.append(dict(session_id=sid, event_time=ts, event_name="page_view", wallet_address=None, tx_hash=None, quote_usd=None))
        p_connect, p_quote, p_confirm = (0.92, 0.80, 0.95) if returning else (0.45, 0.70, 0.93)
        t = ts + timedelta(seconds=int(rng.integers(5, 90)))
        if rng.random() > p_connect:
            return None, []
        if wallet is None:
            wallet = w.new_address()
        w.events.append(dict(session_id=sid, event_time=t, event_name="wallet_connected", wallet_address=wallet, tx_hash=None, quote_usd=None))
        intents = []
        for _ in range(1 if not returning else int(rng.integers(1, 3))):
            t += timedelta(seconds=int(rng.integers(10, 240)))
            if rng.random() > p_quote:
                break
            pool, token_in, amt = swap_intent(t, wallet, u.persona if u else "retail")
            quote_usd = amt * oracle.usd(token_in, t)
            w.events.append(dict(session_id=sid, event_time=t, event_name="quote_requested", wallet_address=wallet, tx_hash=None, quote_usd=round(quote_usd, 2)))
            if rng.random() > SUBMIT_RATE[variant]:
                continue
            t += timedelta(seconds=int(rng.integers(5, 60)))
            ok = rng.random() < p_confirm
            intents.append((t, wallet, pool, token_in, amt, ok, sid))
        return wallet, intents

    lp_days = {lp: int(rng.integers(0, N_DAYS)) for lp in lps}
    july_counts: dict[str, int] = {}  # points snapshot for the airdrop
    airdrop_alloc: dict[str, float] = {}
    claim_sched: list = []

    for d in range(N_DAYS):
        day = START + timedelta(days=d)
        rand_ts = lambda: day + timedelta(seconds=int(rng.integers(0, 86400)))
        acts = []  # (ts, callable)
        swaps = []  # (ts, wallet, pool, token_in, amount, success, session_id, via)

        # 1) new prospects
        growth = 1 + 0.012 * d
        for ci, ch in enumerate(channel_names):
            lam = 400 * growth * channel_mix[ci]
            if ch == "quest_platform" and QUEST_START <= day <= QUEST_END:
                lam *= 4
            for _ in range(rng.poisson(lam)):
                ts = rand_ts()
                anon = f"anon_{w.new_hash()[2:14]}"
                tmp = User("", anon, ch, "retail", tau=CHANNELS[ch][1], floor=CHANNELS[ch][2])
                wallet, intents = run_session(d, ts, None, anon, ch, returning=False)
                if wallet:
                    tmp.wallet = wallet
                    if any(i[5] for i in intents):
                        tmp.acq_day = d
                        users.append(tmp)
                    elif rng.random() < 0.3:
                        pending.append((d + int(rng.integers(1, 8)), tmp))
                swaps += [(*i, ROUTER) for i in intents]

        # 2) retrying prospects
        still = []
        for retry_day, u in pending:
            if retry_day > d:
                still.append((retry_day, u))
                continue
            _, intents = run_session(d, rand_ts(), u, u.anon_id, u.channel, returning=True)
            if any(i[5] for i in intents):
                u.acq_day = d
                users.append(u)
            swaps += [(*i, ROUTER) for i in intents]
        pending = still

        # 3) returning users + whales
        for u in users + whales:
            if u.acq_day is None or u.acq_day >= d:
                continue
            age = d - u.acq_day
            p = (0.22 * math.exp(-age / u.tau) + u.floor) if u.persona != "whale" else u.floor
            if rng.random() < p:
                _, intents = run_session(d, rand_ts(), u, u.anon_id, u.channel, returning=True)
                swaps += [(*i, ROUTER) for i in intents]
        for u in whales:
            if u.acq_day == d:
                pool, tin, amt = swap_intent(rand_ts(), u.wallet, "whale")
                swaps.append((rand_ts(), u.wallet, pool, tin, amt, True, None, ROUTER))

        # 4) sybil farming in July: direct contract calls, tiny sizes, no front-end sessions
        if QUEST_START <= day <= QUEST_END:
            for wal, funder, funded_at in sybils:
                if funded_at.date() == day.date():
                    acts.append((funded_at, ("fund", funder, wal, 0.02)))
                if funded_at < day and rng.random() < 0.18:
                    ts = rand_ts()
                    pool = pools["WETH-USDC"] if rng.random() < 0.7 else pools["USDC-USDT"]
                    tin = pool.token0 if rng.random() < 0.5 else pool.token1
                    swaps.append((ts, wal, pool, tin, float(rng.uniform(15, 40)) / oracle.usd(tin, ts), True, None, ROUTER))

        # 5) airdrop: snapshot July activity, claims from Aug 1
        if day == AIRDROP_DAY:
            pts = {}
            for wal, cnt in july_counts.items():
                pts[wal] = min(cnt, 10)
            total = sum(pts.values())
            sybil_set = set(truth["sybil_wallets"])
            for wal, pt in pts.items():
                airdrop_alloc[wal] = 30e6 * pt / total
                if wal in sybil_set:
                    claim_sched.append((day + timedelta(minutes=int(rng.integers(5, 240))), wal, True))
                elif rng.random() < 0.85:
                    claim_sched.append((day + timedelta(hours=float(rng.uniform(1, 24 * 10))), wal, False))
            truth["airdrop_recipients"] = len(airdrop_alloc)
        for ts, wal, is_sybil in claim_sched:
            if ts.date() == day.date():
                acts.append((ts, ("claim", wal, airdrop_alloc[wal])))
                if is_sybil:
                    swaps.append((ts + timedelta(minutes=int(rng.integers(3, 300))), wal, pools["DEMO-WETH"], "DEMO", None, True, None, ROUTER))
                elif rng.random() < 0.35:
                    lag = timedelta(hours=float(rng.uniform(2, 24 * 7)))
                    swaps.append((ts + lag, wal, pools["DEMO-WETH"], "DEMO", -float(rng.uniform(0.5, 1.0)), True, None, ROUTER))

        # 6) team unlock + partial sells
        if day == TEAM_UNLOCK_DAY:
            for tw in team_wallets:
                acts.append((day + timedelta(hours=1), ("vest", tw, 10e6)))
        if TEAM_UNLOCK_DAY < day <= TEAM_UNLOCK_DAY + timedelta(days=3):
            for _ in range(6):
                swaps.append((rand_ts(), team_wallets[0], pools["DEMO-WETH"], "DEMO", 500_000.0, True, None, ROUTER))

        # 7) wash trading: two wallets ping-pong DEMO
        if any(day.date() == wd.date() for wd in WASH_DAYS):
            if day.date() == WASH_DAYS[0].date():
                for ww in wash_wallets:
                    acts.append((day + timedelta(minutes=2), ("fund", wash_funder, ww, 5.0)))
            for k in range(150):
                ts = day + timedelta(minutes=10 + k * 9)
                usd = float(rng.uniform(4000, 6000))
                swaps.append((ts, wash_wallets[k % 2], pools["DEMO-WETH"], "WETH", usd / oracle.usd("WETH", ts), True, None, ROUTER))
                swaps.append((ts + timedelta(minutes=4), wash_wallets[k % 2], pools["DEMO-WETH"], "DEMO", None, True, None, ROUTER))

        # 8) liquidity provision
        for lp in lps:
            if lp_days[lp] == d or (lp_days[lp] < d and rng.random() < 0.01):
                pool = pools["WETH-USDC"] if rng.random() < 0.7 else pools["USDC-USDT"]
                acts.append((rand_ts(), ("mint", lp, pool, float(rng.lognormal(math.log(80_000), 0.9)))))
            elif lp_days[lp] < d and rng.random() < 0.003:
                acts.append((rand_ts(), ("burn", lp, pools["WETH-USDC"], 0.002)))
        if day.date() == LP_EXIT_DAY.date():
            acts.append((day + timedelta(hours=14, minutes=7), ("burn", MARKET_MAKER, pools["WETH-USDC"], 0.5)))

        # 9) arbitrage every 2h per pool (MEV bots, own contracts)
        for hh in range(0, 24, 2):
            for name in pools:
                acts.append((day + timedelta(hours=hh, minutes=int(rng.integers(0, 110))), ("arb", name)))

        # ---- execute chronologically
        timeline = [(a[0], 0, a[1]) for a in acts] + [(s[0], 1, s) for s in swaps]
        timeline.sort(key=lambda x: (x[0], x[1]))
        for ts, kind, payload in timeline:
            if ts >= START + timedelta(days=N_DAYS):  # spill-over past the window
                continue
            if kind == 1:
                _, wallet, pool, tin, amt, ok, sid, via = payload
                if tin == "DEMO":
                    bal = w.demo_bal.get(wallet, 0)
                    if amt is None:
                        amt = bal * 0.999
                    elif amt < 0:
                        amt = bal * -amt
                    amt = min(amt, bal)
                h = do_swap(w, ts, wallet, pool, tin, amt, via=via, success=ok)
                if h and sid:
                    w.events.append(dict(session_id=sid, event_time=ts, event_name="swap_submitted", wallet_address=wallet, tx_hash=h, quote_usd=None))
                if h and ok and QUEST_START <= ts <= QUEST_END + timedelta(days=1):
                    july_counts[wallet] = july_counts.get(wallet, 0) + 1
                continue
            op = payload[0]
            if op == "fund":
                _, funder, wal, eth = payload
                emit_tx(w, ts, funder, wal, value_eth=eth, gas_used=21_000)
            elif op == "claim":
                _, wal, amt = payload
                h = emit_tx(w, ts, wal, AIRDROP_DISTRIBUTOR, gas_used=85_000)
                demo_transfer(w, ts, h, AIRDROP_DISTRIBUTOR, wal, amt)
            elif op == "vest":
                _, tw, amt = payload
                h = emit_tx(w, ts, tw, TEAM_VESTING, gas_used=70_000)
                demo_transfer(w, ts, h, TEAM_VESTING, tw, amt)
            elif op == "mint":
                _, lp, pool, usd = payload
                do_mint(w, ts, lp, pool, usd, oracle)
            elif op == "burn":
                _, lp, pool, share = payload
                do_burn(w, ts, lp, pool, share)
            elif op == "arb":
                pool = pools[payload[1]]
                target = oracle.usd(pool.token1, ts) / oracle.usd(pool.token0, ts)  # token0 per token1
                k = pool.r0 * pool.r1
                new_r0 = math.sqrt(k * target)
                bot, contract = bots[int(rng.integers(0, len(bots)))]
                if abs(new_r0 / pool.r0 - 1) < 0.0015:  # not profitable after fees
                    continue
                if new_r0 > pool.r0:
                    tin, amt = pool.token0, (new_r0 - pool.r0) / (1 - FEE)
                else:
                    tin, amt = pool.token1, (k / new_r0 - pool.r1) / (1 - FEE)
                # bots source / park DEMO inventory on a CEX (the other leg of the arb)
                if tin == "DEMO" and w.demo_bal[bot] < amt:
                    h = emit_tx(w, ts - timedelta(seconds=30), CEX_HOT_WALLET, TOKENS["DEMO"]["address"], gas_used=52_000)
                    demo_transfer(w, ts, h, CEX_HOT_WALLET, bot, amt - w.demo_bal[bot] + 1e6)
                do_swap(w, ts, bot, pool, tin, amt, via=contract)
                if w.demo_bal[bot] > 10e6:
                    h = emit_tx(w, ts + timedelta(seconds=30), bot, TOKENS["DEMO"]["address"], gas_used=52_000)
                    demo_transfer(w, ts, h, bot, CEX_HOT_WALLET, w.demo_bal[bot] - 2e6)

    # ---- tables
    days = [START.date() + timedelta(days=i) for i in range(N_DAYS)]
    spend = []
    for dd in days:
        dt = datetime(dd.year, dd.month, dd.day, tzinfo=timezone.utc)
        for ch, (_, _, _, s) in CHANNELS.items():
            amt = s * (12 if ch == "quest_platform" and QUEST_START <= dt <= QUEST_END else 1)
            if ch == "kol_referral":
                amt *= 2 if dd.day <= 14 else 0  # KOL bursts in first half of month
            if amt:
                spend.append((dd, ch, float(amt * rng.uniform(0.85, 1.15))))

    out = {
        "raw_transactions": pd.DataFrame(w.txs),
        "raw_logs": pd.DataFrame(w.logs),
        "raw_prices_daily": prices,
        "raw_tokens": pd.DataFrame([dict(symbol=s, contract_address=t["address"], decimals=t["decimals"],
                                         is_stable=s in ("USDC", "USDT"),
                                         pricing_priority={"USDC": 1, "USDT": 2, "WETH": 3, "DEMO": 4}[s]) for s, t in TOKENS.items()]),
        "raw_pools": pd.DataFrame([dict(pool_name=p.name, pool_address=p.address, token0_address=TOKENS[p.token0]["address"],
                                        token1_address=TOKENS[p.token1]["address"], fee_bps=30, created_at=START) for p in pools.values()]),
        "raw_app_sessions": pd.DataFrame(w.sessions),
        "raw_app_events": pd.DataFrame(w.events),
        "raw_marketing_spend": pd.DataFrame(spend, columns=["day", "channel", "spend_usd"]),
        "raw_labels": pd.DataFrame(
            [dict(address=a, label=l) for l, a in [("router", ROUTER), ("factory", FACTORY), ("airdrop_distributor", AIRDROP_DISTRIBUTOR),
                                                     ("team_vesting", TEAM_VESTING), ("treasury", TREASURY), ("investor_custody", INVESTORS),
                                                     ("ecosystem_fund", ECOSYSTEM), ("market_maker", MARKET_MAKER), ("cex_hot_wallet", CEX_HOT_WALLET)]]
            + [dict(address=b, label="mev_bot") for b, _ in bots]
            + [dict(address=c, label="mev_bot_contract") for _, c in bots]
        ),
    }
    truth.update(
        quest_window=[str(QUEST_START.date()), str(QUEST_END.date())],
        experiment=dict(window=[str(EXP_START.date()), str(EXP_END.date())], metric="quote_to_submit", control=SUBMIT_RATE["A"], treatment=SUBMIT_RATE["B"]),
        anomalies=[
            dict(date=str(AIRDROP_DAY.date()), type="airdrop_claim_and_dump"),
            dict(date=str(TEAM_UNLOCK_DAY.date()), type="team_token_unlock"),
            *[dict(date=str(d.date()), type="wash_trading_volume_spike") for d in WASH_DAYS],
            dict(date=str(LP_EXIT_DAY.date()), type="whale_lp_exit_tvl_drop"),
        ],
        channel_retention_tau={c: v[1] for c, v in CHANNELS.items()},
        genuine_users=len(users),
    )
    negative = {a: b for a, b in w.demo_bal.items() if a != ZERO and b < -1e-6}
    assert not negative, f"negative DEMO balances: {list(negative.items())[:3]}"
    
    return out, dict(truth)



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[1] / "data" / "raw"))
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    tables, truth = simulate(args.seed)
    for name, df in tables.items():
        df.to_parquet(out_dir / f"{name}.parquet", index=False)
        print(f"{name:22s} {len(df):>9,d} rows")
    (out_dir.parent / "ground_truth.json").write_text(json.dumps(truth, indent=2, default=str))
    print(f"ground truth -> {out_dir.parent / 'ground_truth.json'}")


if __name__ == "__main__":
    main()
