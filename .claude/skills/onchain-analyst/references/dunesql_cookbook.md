# DuneSQL cookbook (Trino dialect)

Syntax reminders: varbinary literals are bare `0xabc…` (no quotes), double-quote reserved
columns (`"from"`, `"to"`), `INTERVAL '30' DAY`, `DATE_TRUNC('week', ts)`, `DATE_DIFF('day', a, b)`,
`COUNT_IF(cond)`, `APPROX_DISTINCT`, `APPROX_PERCENTILE(x, 0.5)`, `MIN_BY(x, ts)`, `TRY_CAST`.
Parameters: `{{name}}`. Reuse another query: `FROM query_1234567`.

Full, ready-to-run versions live in `dune_queries/01…09_*.sql` (repo root).

## Daily protocol KPIs
```sql
SELECT block_date, SUM(amount_usd) volume_usd, COUNT(*) trades, COUNT(DISTINCT tx_from) traders
FROM dex.trades
WHERE project = 'uniswap' AND blockchain = 'ethereum' AND block_date >= CURRENT_DATE - INTERVAL '90' DAY
GROUP BY 1 ORDER BY 1
```

## First-seen / new vs returning (full-history first date!)
```sql
WITH first_seen AS (SELECT tx_from, MIN(block_date) d0 FROM dex.trades WHERE project='uniswap' GROUP BY 1)
SELECT t.block_date, COUNT_IF(f.d0 = t.block_date) new_traders, COUNT_IF(f.d0 < t.block_date) returning
FROM (SELECT DISTINCT block_date, tx_from FROM dex.trades WHERE project='uniswap' AND block_date >= CURRENT_DATE - INTERVAL '30' DAY) t
JOIN first_seen f USING (tx_from) GROUP BY 1
```

## Cohort triangle
`activity(trader, week)` → `cohort = MIN(week)` → `DATE_DIFF('week', cohort, week)` → count / cohort size. See `03_weekly_cohort_retention.sql`.

## Decode raw logs (contract not decoded on Dune)
```sql
SELECT block_time, tx_hash,
       bytearray_substring(topic1, 13, 20)                     AS from_addr,
       bytearray_substring(topic2, 13, 20)                     AS to_addr,
       bytearray_to_uint256(bytearray_substring(data, 1, 32)) / 1e18 AS amount
FROM ethereum.logs
WHERE contract_address = 0x... AND topic0 = 0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef
  AND block_time >= NOW() - INTERVAL '7' DAY
```
Prefer the decoded tables when they exist: `<project>_<chain>.<Contract>_evt_<Event>` (e.g. `uniswap_v3_ethereum.Pair_evt_Swap`). Submit the contract for decoding if it's missing.

## TVL of a V2 pair from Sync
```sql
SELECT DATE_TRUNC('day', block_time) d,
       MAX_BY(bytearray_to_uint256(bytearray_substring(data, 1, 32)), block_number * 1e6 + index) r0,
       MAX_BY(bytearray_to_uint256(bytearray_substring(data, 33, 32)), block_number * 1e6 + index) r1
FROM ethereum.logs WHERE contract_address = {{pair}} AND topic0 = 0x1c411e9a96e071241c2f21f7726b17ae89e3cab4c78be50e062b03a9fffbbad1
GROUP BY 1
```
Then forward-fill missing days and multiply by `prices.usd` (or `prices.day`) / decimals.

## Prices
`prices.usd (minute, blockchain, contract_address, symbol, decimals, price)`. For daily use
`DATE_TRUNC('day', minute)` + `AVG(price)` or the `prices.day` spell. Long-tail tokens may have no price, so value the swap from the other leg.

## Funnel join (off-chain → on-chain)
Upload app events as a Dune dataset (`dune.<team>.dataset_app_events`), then
`JOIN ethereum.transactions t ON t.hash = e.tx_hash AND t.success`. Confirmation = receipt success.

## Funding clusters (sybil)
First inbound ETH per wallet: `MIN_BY("from", block_time)` over `ethereum.transactions WHERE value > 0`
(+ `ethereum.traces` for contract senders). Group by funder; exclude `cex.addresses`. Clusters
of 20+ wallets funded within hours with identical seed amounts are scripted. See `07_funding_clusters.sql`.

## Cost / performance
- Filter `block_date`/`block_time` first; for `ethereum.logs` also `contract_address` and `topic0`.
- Pre-aggregate in a CTE before joining big tables; `APPROX_DISTINCT` for large cardinalities.
- Materialize heavy intermediate results as their own query and reference `query_<id>`.
- Use Flipside (`ez_dex_swaps`, `fact_event_logs`) or BigQuery (`bigquery-public-data.crypto_ethereum.logs`, hex strings like this repo's DuckDB) when Dune credits run out; the patterns are the same.
