# DemoSwap daily protocol report · 2026-09-30

> Window 2026-05-01 → 2026-09-30; KPIs compare the last 30 days with the previous 30. "Clean" = excluding MEV bots, protocol addresses, sybil clusters and wash-trading wallets. Data is simulated (see README).

## Key metrics

| Metric | Value | vs previous 30d |
|---|---:|---:|
| TVL | $35.65M | (▼ 20.7%) |
| 30d volume (all) | $33.13M | (▲ 12.4%) |
| 30d volume (clean) | $17.98M | (▲ 2.8%) |
| 30d LP fees | $99.4k | (▲ 12.4%) |
| Avg daily active traders (reported / clean) | 503 / 502 | (▼ 3.6%) |
| 30d new real users | 4,378 | (▲ 9.3%) |
| Fee APR (30d annualised) | 3.25% | |

## Findings and recommendations

### 1. [P0] The new swap UI (B) lifts quote→submit conversion from 51.3% to 56.5% (+10.3% relative, p=3e-11, 95% CI [+3.7%, +6.8%])

- **Area:** Product / Experiment
- **Evidence:** User-level analysis, A=7,932 / B=7,900 quoting users; SRM check p=0.75 (assignment healthy); MDE=2.2%.
- **Hypothesis:** The route preview reduces uncertainty about slippage and price, so fewer users abandon after quoting.
- **Recommendation:** Ship B to 100%. Next experiment: show a gas estimate and a retry flow for failed transactions (the submit→confirm step).
- **Expected impact:** About +2,000 successful swaps per month, ≈ +$2.62M volume / +$7,848 LP fees.

### 2. [P0] 13% of wallets acquired in July (quest campaign) are sybils; they took 25% of the airdrop and sold 100% of it within 24h (genuine users sold only 32% within 7 days)

- **Area:** Growth / Tokenomics
- **Evidence:** 8 funding clusters with 799 wallets: seeded by one address within <2h, never used the front-end, ~$30 per swap, active <1 month. DEMO price moved -22% in the week after the airdrop.
- **Hypothesis:** Points were awarded per transaction count, so scripted farming cost almost nothing.
- **Recommendation:** Run funding-cluster and behaviour filters before the airdrop; weight points by fees paid and holding time, with a cap; switch to linear vesting (e.g. 30 days) or tie unlocks to continued activity.
- **Expected impact:** Filtering sybils would redirect ~6.5M DEMO (≈ $245k at distribution) to real users and reduce first-week sell pressure.

### 3. [P1] Twitter Ads CAC is $56 while 30-day LTV (fees) is only $5.50; quest-platform D30 retention is 50%, well below organic at 86%

- **Area:** Growth / Paid acquisition
- **Evidence:** Channel attribution = UTM channel of the session in which the wallet first connected; LTV = LP fees generated in the 30 days after the first swap.
- **Hypothesis:** Paid channels bring one-off, task-driven users; organic and KOL users arrive with real trading intent.
- **Recommendation:** Move part of the Twitter budget to KOL referrals paid on retention (CPA); redesign quests around retention, e.g. 'trade every week for 4 weeks'.
- **Expected impact:** Every paid channel is below 1× LTV/CAC. Re-evaluate on 90-day LTV and protocol revenue before continuing spend.

### 4. [P1] Passive LPs in WETH-USDC underperformed holding: fee yield 1.17%, impermanent loss -3.52%, net -2.35% vs HODL

- **Area:** DeFi / Liquidity
- **Evidence:** Daily volume/TVL is only 2.52%. Covering IL would need ~$1.7M average daily volume; actual was $0.57M.
- **Hypothesis:** Liquidity is over-provisioned relative to trading demand (low capital efficiency), so LP returns are thin and capital is at risk of leaving.
- **Recommendation:** Evaluate concentrated liquidity (V3-style ranges) or dynamic fees; shift DEMO incentives from subsidising TVL to subsidising real volume (trading rewards with wash-trading filters).
- **Expected impact:** Better capital efficiency gives deeper quotes from the same TVL and raises LP APR.

### 5. [P1] TVL fell -30% on 2026-09-12: a single market maker withdrew half of WETH-USDC liquidity at once

- **Area:** Risk / Liquidity concentration
- **Evidence:** That address supplied 53% of all WETH-USDC deposits; the robust z-score detector fired the same day.
- **Hypothesis:** TVL depends heavily on one market maker; if their strategy changes, slippage and user experience degrade immediately.
- **Recommendation:** Alert when any single LP exceeds 30% of a pool; agree lock-ups or staged withdrawals with market makers; use incentives to attract a broader LP base.
- **Expected impact:** Reduces tail risk: a withdrawal during peak trading would sharply widen slippage on large trades.

### 6. [P2] ~$4.5M of volume over 3 days in early September came from 2 wallets with the same funder wash-trading the DEMO pool

- **Area:** Data quality / Metric definitions
- **Evidence:** Both wallets net position / gross volume < 1%, 150 round trips per day, funded by the same address.
- **Hypothesis:** Likely an attempt to inflate DEMO volume rankings, or to dress up metrics ahead of a CEX listing.
- **Recommendation:** Use 'clean' metrics (excluding bots, sybils and wash trading) for both external reporting and internal KPIs; apply wash filters to leaderboards and incentive calculations.
- **Expected impact:** Reported peak DAU was 1,260 (2026-08-01) versus 461 clean users that day; the gap would mislead decisions.

### 7. [P2] 27% of real users traded on a single day only; retention is 33% after week 1 and 11% by week 8

- **Area:** Retention
- **Evidence:** Weekly cohorts by first-swap week, excluding bots, sybils and wash-trading wallets.
- **Hypothesis:** After the first trade there is little reason to come back (no limit orders, no portfolio or P&L view).
- **Recommendation:** Launch limit orders / DCA and a 'My positions' page; re-engage wallets that haven't returned 7 days after their first swap (e.g. Push Protocol, email).
- **Expected impact:** Each +5pp of week-1 retention adds several hundred monthly active traders at the current acquisition rate.

## Anomaly alerts

| Date | Metric | z | Direction |
|---|---|---:|---|
| 2026-05-31 | net_liquidity_flow_usd | 5.9 | spike |
| 2026-05-31 | tvl_usd | 4.5 | spike |
| 2026-06-10 | clean_volume_usd | 12.4 | spike |
| 2026-06-10 | volume_usd | 12.4 | spike |
| 2026-06-12 | demo_net_sell_usd | -4.2 | drop |
| 2026-07-04 | net_liquidity_flow_usd | 4.3 | spike |
| 2026-07-04 | new_traders | 5.6 | spike |
| 2026-07-05 | new_traders | 4.5 | spike |
| 2026-07-06 | new_traders | 6.6 | spike |
| 2026-07-07 | new_traders | 6.4 | spike |
| 2026-07-07 | volume_usd | 4.6 | spike |
| 2026-07-08 | new_traders | 7.7 | spike |
| 2026-07-09 | new_traders | 6.2 | spike |
| 2026-07-09 | volume_usd | 4.0 | spike |
| 2026-07-10 | net_liquidity_flow_usd | 4.5 | spike |
| 2026-07-10 | new_traders | 4.6 | spike |
| 2026-07-11 | new_traders | 5.3 | spike |
| 2026-07-12 | new_traders | 5.3 | spike |
| 2026-07-13 | new_traders | 5.4 | spike |
| 2026-07-22 | demo_net_sell_usd | -5.4 | drop |
| 2026-08-01 | demo_net_sell_usd | 9.3 | spike |
| 2026-08-08 | net_liquidity_flow_usd | 5.0 | spike |
| 2026-08-19 | demo_net_sell_usd | -4.4 | drop |
| 2026-08-22 | volume_usd | 4.7 | spike |
| 2026-08-25 | clean_volume_usd | 5.5 | spike |
| 2026-08-25 | volume_usd | 5.7 | spike |
| 2026-09-05 | volume_usd | 5.0 | spike |
| 2026-09-06 | volume_usd | 5.9 | spike |
| 2026-09-12 | net_liquidity_flow_usd | -80.9 | drop |
| 2026-09-12 | tvl_usd | -32.7 | drop |
| 2026-09-26 | clean_volume_usd | 4.8 | spike |

**Volume anomaly attribution** (top 3 addresses that day):

- 2026-06-10: top 3 contributed 72%, types mev_bot / user / mev_bot, mainly in WETH-USDC
- 2026-07-07: top 3 contributed 66%, types mev_bot / user / user, mainly in WETH-USDC
- 2026-07-09: top 3 contributed 68%, types mev_bot / user / user, mainly in WETH-USDC
- 2026-08-22: top 3 contributed 47%, types mev_bot / mev_bot / user, mainly in WETH-USDC
- 2026-08-25: top 3 contributed 58%, types mev_bot / user / mev_bot, mainly in WETH-USDC
- 2026-09-05: top 3 contributed 68%, types wash / wash / mev_bot, mainly in DEMO-WETH
- 2026-09-06: top 3 contributed 60%, types wash / wash / mev_bot, mainly in DEMO-WETH

**Large token transfers** (≥ 0.5% of supply, excluding mints and CEX / bot inventory):

- 2026-09-01 01:00  team_vesting → 0xfc812658: 10.0M DEMO (1.00%)
- 2026-09-01 01:00  team_vesting → 0x2d69d625: 10.0M DEMO (1.00%)
- 2026-09-01 01:00  team_vesting → 0xfd86d996: 10.0M DEMO (1.00%)
- 2026-09-01 01:00  team_vesting → 0xac66dca4: 10.0M DEMO (1.00%)

## Experiment

- User level: A 51.3% vs B 56.5%, p=3e-11, 95% CI [3.7%, 6.8%]
- Session level (reference only; sessions of the same user are correlated, so variance is understated): A 42.5% vs B 48.2%
- SRM check p=0.75 → assignment healthy; MDE at current sample = 2.2%

## Data quality

- Found 8 sybil funding clusters (799 wallets) and 2 wash-trading wallets ($4.48M wash volume)
- Bot share of volume 40.6%; reported users 19,156 → clean 18,355

## Model validation (against the simulator's hidden ground truth)

- Sybil detection precision 100.0% / recall 99.0%
- Wash-trading detection precision 100.0% / recall 100.0%
- Experiment: true per-quote submit rate 36.0% → 42.0%; estimated session-level lift 5.7% (CI [4.6%, 6.8%])
- Anomalies detected: 2026-08-01 airdrop_claim_and_dump ✓, 2026-09-01 team_token_unlock ✓, 2026-09-05 wash_trading_volume_spike ✓, 2026-09-06 wash_trading_volume_spike ✓, 2026-09-07 wash_trading_volume_spike ✗, 2026-09-12 whale_lp_exit_tvl_drop ✓
