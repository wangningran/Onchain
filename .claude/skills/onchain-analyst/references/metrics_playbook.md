# Metrics playbook: definitions, formulas, pitfalls

Code references are to `src/onchain_analytics/` (repo root).

## DeFi protocol metrics
| metric | definition | pitfall |
|---|---|---|
| TVL | Σ pool token balances × price (V2: last Sync reserves) | price of the protocol's own token inflates TVL reflexively, so report TVL ex-native-token too |
| Volume | Σ swap `amount_usd` (one leg) | multi-hop double count; wash & arb volume |
| Fees | volume × fee tier; protocol revenue = fees × protocol share | LP fees ≠ protocol revenue |
| Fee APR | fees_day / TVL_day × 365 | spiky; use 7d/30d windows |
| Capital efficiency | volume / TVL | low ⇒ LPs underpaid, liquidity over-provisioned |
| LP net vs HODL | Σ daily fee yield + IL(price ratio) | `defi.lp_economics`; IL formula `2√r/(1+r) − 1` |
| Breakeven volume | \|IL\| × TVL / (fee × days) | `defi.breakeven_daily_volume` |
| LP concentration | top LP share of deposits | one market maker = exit risk (TVL cliff) |
| Liquidity depth | price impact for $X swap (V2: X/(R+X)) | quote quality matters more to users than TVL |

## User / product metrics
| metric | definition | pitfall |
|---|---|---|
| Active traders (DAU/WAU) | distinct `tx_from` with ≥1 successful swap | exclude bots/protocol; show reported vs clean |
| New / returning / reactivated | first-ever day = new; active after ≥30d gap = reactivated | first-seen over full history |
| Cohort retention | share of cohort active in week N | censor partial weeks; size-weighted average curve (`cohorts.average_retention_curve`) |
| Churn | active in M, not in M+1 (or no activity for 30d) | `cohorts.monthly_churn`, `dormant_share` |
| Funnel | visit → connect → quote → submit → confirmed on-chain | join on `tx_hash`; failed txs are a real drop-off (gas, slippage) |
| CAC | channel spend / new traders attributed (first touch) | sybils inflate denominators of quest campaigns |
| LTV (proxy) | fees (or protocol revenue) generated in first 30/90 days | compare at the same horizon as CAC payback |

## Experiments (`abtest`)
- Randomise and analyse at the **user** level (`anonymous_id`/wallet), not sessions.
- `two_proportion_test(x_a, n_a, x_b, n_b)` → rates, abs/rel lift, 95% CI, p.
- `srm_check(n_a, n_b)`: p < 0.001 ⇒ assignment broken, results invalid.
- `minimum_detectable_effect(n, p)` before launch; `required_sample_size(p, mde)`.
- Guardrails: confirmed-tx rate, failed-tx rate, median trade size, revenue per user.
- Novelty effects: look at lift by week of exposure.

## Anomaly detection (`anomaly`)
- Trailing robust z: `(x − median₂₈) / (1.4826 · MAD₂₈)`, alert at |z| > 4 (`detect_anomalies`).
- Use `pct_change` for stock metrics (TVL), level for flows (volume, users).
- Then **attribute** (`attribute_volume_day`): top-3 wallet share, labels, pool. Most volume
  alerts on majors are MEV-arb during volatility, not demand.
- Token events: transfers ≥ 0.5% of supply (`tokenomics.large_transfers`) → unlocks, treasury moves, CEX deposits.

## Integrity (`sybil`)
- Sybil cluster: one funder → ≥20 wallets, funded within 24h, ≥90% headless (no front-end), tiny uniform swaps (IQR/median), short lifespan. ≥4 of 5 rules (`funder_clusters`).
- Wash: net/gross < 5% with ≥50 swaps and large gross; pull in wallets sharing the funder (`wash_traders`).
- Bots: labelled MEV, non-router `tx_to`, >100 trades/day, same-block sandwich patterns.

## Segmentation (`segmentation`)
- Value tiers by volume; behaviour (one-and-done / occasional / power / LP); RFM 1–5.
- Always pair segment size with volume/fee share (Pareto).

## Tokenomics (`tokenomics`)
- Concentration among economic holders: exclude pools, CEX, vesting and undistributed contracts.
- Gini, top-10/100 share, Nakamoto coefficient (holders to control >50%).
- Airdrop: recipients, claim delay, sell-through 24h/7d/30d by recipient type (sybil vs genuine), price impact.
- Unlock calendar vs DEX liquidity: unlock size / daily volume = days of sell pressure.
