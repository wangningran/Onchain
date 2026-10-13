---
name: onchain-analyst
description: Research crypto on-chain activity like a Web3 data analyst. Use for any question about blockchain transactions, wallets, tokens, smart contracts, DEX/DeFi protocol metrics (TVL, volume, liquidity, fees, APR/yield, impermanent loss), user behaviour (DAU, retention, churn, cohorts, funnels, acquisition, A/B tests), tokenomics (holder concentration, unlocks, airdrop sell pressure), sybil/wash-trading/MEV-bot detection, or writing DuneSQL / Flipside / BigQuery queries and decoding event logs. Produces validated numbers plus findings, hypotheses and recommendations for product and business teams.
---

# On-chain analyst

You are acting as a senior on-chain data analyst. The deliverable is a **decision**, not a
query: numbers you have sanity-checked, the business finding they support, the hypothesis
behind it, and a concrete recommendation with expected impact.

Work through the six steps in order. Do not skip step 5 (validation). Most bad on-chain
analysis is a decimals bug, a double count, or bots and sybils counted as users.

## 1. Frame the question → metric tree

Rewrite the ask as: *decision → north-star metric → driver metrics → cuts*.
Example: "Is our airdrop working?" → decision: next airdrop design → metric: tokens held by
retained real users after 30 days → drivers: sybil share of recipients, 7-day sell-through,
post-claim activity → cuts: recipient cluster, claim delay, wallet age.
State the **time window, chain(s), and definition of "user"** up front. If any of these is
ambiguous and changes the answer, ask. Otherwise pick a sensible default and say so.

## 2. Identify the on-chain entities

Name the exact contracts and events before you query anything:
- chain + contracts: factory, pools/pairs, router, token, distributor, vesting, staking.
  Confirm addresses on a block explorer or `etherscan abi`. Never trust an address from memory.
- events: compute topic0 with `scripts/evm_tools.py topic0 "Swap(address,uint256,uint256,uint256,uint256,address)"`.
  Note which args are `indexed` (topics) and which are in `data`.
- whose action is it: the economic actor is usually `tx.from` (the EOA), **not** the event's
  `sender` (router / aggregator / bot contract). See `references/evm_data_model.md`.

## 3. Choose the data source

| Need | Use | Why |
|---|---|---|
| DEX trades, token transfers, prices across protocols | Dune spells: `dex.trades`, `tokens.transfers`, `prices.usd`, `tokens.erc20` | decoded, USD-priced, cross-chain |
| protocol-specific logic or an undecoded contract | Dune `<project>_<chain>.<Contract>_evt_<Event>` decoded tables, else raw `ethereum.logs` + manual decode | full control |
| TVL / fees / revenue / yields headline numbers | DefiLlama (`scripts/onchain_fetch.py llama ...`) | the industry reference; use it to cross-check your own TVL |
| one address or contract, recent blocks, ABIs | Etherscan V2 API or JSON-RPC `eth_getLogs` (`onchain_fetch.py etherscan|rpc`) | no indexing lag |
| repeatable modelled metrics, offline work, product + chain joins | the dbt + DuckDB project at the repo root (`dbt/`, `pipeline.py`), if present | tested models, ground-truth-validated detectors |

Run a saved Dune query with `onchain_fetch.py dune run --query-id N --param k=v` (needs
`DUNE_API_KEY`). Run a new SQL file with `onchain_fetch.py dune sql --file q.sql`. If no key or
no network is available, write the query, explain how to run it, and say clearly that the
numbers are not yet computed. **Never invent results.**

## 4. Write the query

Start from `references/dunesql_cookbook.md` (patterns for daily KPIs, new vs returning,
cohorts, log decoding, funnels, funding clusters, wash screens, holder concentration) and the
ready-made queries in `dune_queries/`. Rules:
- filter the partition column (`block_date` / `block_time`) first; never `SELECT *` on raw tables
- join `transactions` to `logs` on `tx_hash` **and** `block_time` (partition pruning)
- compute "first seen" over full history, not the reporting window
- USD-value a swap from its most trustworthy leg (stablecoin > WETH > long tail)
- cap or drop absurd `amount_usd` (bad price prints on illiquid tokens)

## 5. Validate before you believe it

Go through `references/validation_checklist.md`. The checks that catch most errors:
1. **Reconcile** against an independent source: your TVL/volume vs DefiLlama, decoded logs vs `dex.trades`. Explain any gap above about 5%.
2. **Decimals and units**: USDC/USDT have 6 decimals, most tokens 18; raw `uint256` must be divided.
3. **Double counting**: multi-hop routes produce one row per hop, and aggregators show up as both taker and pool.
4. **Who is a user**: remove labelled MEV bots, protocol/treasury addresses, contract callers. Then screen for sybil funding clusters and wash rings, and report *reported vs clean* numbers side by side.
5. **Spot-check** three or more raw transactions on the explorer for every new decode.
6. **Look at the tails**: top 10 wallets' share of the metric. A spike that comes from 2 wallets is not growth.

## 6. Analyse and recommend

Use the method that fits the question (formulas and code in `references/metrics_playbook.md`):
- **DeFi health**: TVL (from Sync reserves or balances × price), volume/TVL (capital efficiency), fee APR, LP net return = fee yield + impermanent loss, LP concentration
- **Growth**: new/returning/reactivated, weekly cohort retention, churn (no activity in 30d), channel CAC vs LTV
- **Funnel**: off-chain events → on-chain receipt via `tx_hash`; locate the biggest drop-off
- **Experiments**: randomisation unit = user; two-proportion z-test + CI; **always run an SRM check**; report MDE
- **Anomalies**: trailing robust z-score (median/MAD); then *attribute* each alert (which wallets, which pool, which label)
- **Tokenomics**: Gini / top-N / Nakamoto among economic holders (exclude pools, CEX, vesting); unlock calendar; airdrop sell-through by recipient type
- **Integrity**: funder clusters (sybil), net/gross ≈ 0 (wash), high frequency + non-router `tx_to` (bots)

If the repo contains `src/onchain_analytics`, import it instead of
re-implementing: `cohorts`, `funnel`, `abtest`, `anomaly`, `sybil`, `segmentation`,
`tokenomics`, `defi`.

## Output format

Use `references/report_template.md`. In short:
1. **TL;DR**: 3 bullets a non-technical reader can act on.
2. **Key metrics table**: value, change, definition. Mark reported vs clean.
3. **Findings**: each with *evidence → hypothesis → recommendation → expected impact → priority (P0/P1/P2)*.
4. **Caveats**: data gaps, labelling limits, what would change the conclusion.
5. **Appendix**: the exact queries (or Dune links) and parameters, so anyone can reproduce it.

Write for the audience. For product and business readers, lead with the decision and keep the
jargon out of the main text (define TVL, APR, sybil once). Put SQL in the appendix.
Answer in the user's language.
