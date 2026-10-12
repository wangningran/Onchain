# Validation checklist: run it before reporting any number

## Correctness
- [ ] Contract addresses verified on an explorer; filtering by `contract_address`, not only `topic0`
- [ ] Decimals applied per token (6 vs 18!); raw uint256 not compared to USD
- [ ] Failed transactions excluded from activity counts (no logs, but still in `transactions`)
- [ ] Multi-hop / aggregator routes not double counted (one row per hop in `dex.trades`)
- [ ] Time zone = UTC; partial current day/week excluded from trends
- [ ] First-seen computed over full history; cohort left-censoring handled

## Reconciliation
- [ ] TVL / volume within ~5% of DefiLlama (or the gap explained: chains, versions, pricing)
- [ ] Decoded raw logs ↔ curated spell row counts match for a sample window
- [ ] Token balances sum to total supply (mint/burn via zero address included)
- [ ] Funnel steps monotonic (confirmed ≤ submitted ≤ quoted ≤ connected ≤ sessions)
- [ ] 3+ transactions spot-checked by hand on the explorer

## Who counts
- [ ] MEV bots / protocol / treasury / CEX addresses labelled and excluded from "users"
- [ ] Sybil funding clusters and wash rings screened; *reported vs clean* shown side by side
- [ ] Top-10 wallets' share of the metric reported (concentration hides in averages)

## Statistics
- [ ] Experiments: user-level unit, SRM check, CI not just p-value, MDE stated
- [ ] Comparisons over equal-length windows; seasonality (weekday, token events) considered
- [ ] Anomaly alerts attributed to wallets/pools before being called "growth" or "incident"

## Communication
- [ ] Every number has a definition and a window
- [ ] Each finding has evidence → hypothesis → action → impact
- [ ] Caveats state what would change the conclusion
- [ ] Queries / parameters in the appendix for reproducibility
