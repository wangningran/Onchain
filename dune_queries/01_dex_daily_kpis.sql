-- DEX daily KPIs on Dune (DuneSQL / Trino).  Params: {{project}} e.g. uniswap, {{blockchain}} e.g. ethereum, {{days}} e.g. 90
-- dex.trades is the curated spell: one row per trade, already decoded, USD-priced, multi-version.
-- Always filter the partition column (block_date / block_time) first: it decides scan cost.
SELECT
    block_date                                         AS day,
    SUM(amount_usd)                                    AS volume_usd,
    COUNT(*)                                           AS trades,
    COUNT(DISTINCT tx_from)                            AS traders,           -- tx_from = EOA that signed; `taker` can be a router/aggregator
    SUM(amount_usd) / NULLIF(COUNT(DISTINCT tx_from), 0) AS volume_per_trader,
    APPROX_PERCENTILE(amount_usd, 0.5)                 AS median_trade_usd,
    SUM(CASE WHEN amount_usd >= 100000 THEN amount_usd ELSE 0 END) / NULLIF(SUM(amount_usd), 0) AS whale_trade_share
FROM dex.trades
WHERE project = '{{project}}'
  AND blockchain = '{{blockchain}}'
  AND block_date >= CURRENT_DATE - INTERVAL '{{days}}' DAY
  AND amount_usd IS NOT NULL
  AND amount_usd < 1e8                                 -- drop pricing outliers (bad oracle prints on long-tail tokens)
GROUP BY 1
ORDER BY 1
