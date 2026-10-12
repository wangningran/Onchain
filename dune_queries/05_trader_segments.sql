-- Value tiers & Pareto: who generates the volume (and fees)?
WITH t AS (
    SELECT tx_from AS trader, SUM(amount_usd) AS volume_usd, COUNT(*) AS trades, COUNT(DISTINCT block_date) AS active_days
    FROM dex.trades
    WHERE project = '{{project}}' AND blockchain = '{{blockchain}}'
      AND block_date >= CURRENT_DATE - INTERVAL '{{days}}' DAY
      AND amount_usd IS NOT NULL
    GROUP BY 1
),
tiered AS (
    SELECT *,
        CASE WHEN volume_usd < 1e3 THEN '1 shrimp <1k'
             WHEN volume_usd < 1e4 THEN '2 fish 1k-10k'
             WHEN volume_usd < 1e5 THEN '3 dolphin 10k-100k'
             WHEN volume_usd < 1e6 THEN '4 whale 100k-1m'
             ELSE '5 leviathan >1m (check: bot?)' END AS tier
    FROM t
)
SELECT
    tier,
    COUNT(*)                                                 AS traders,
    CAST(COUNT(*) AS DOUBLE) / SUM(COUNT(*)) OVER ()         AS trader_share,
    SUM(volume_usd)                                          AS volume_usd,
    SUM(volume_usd) / SUM(SUM(volume_usd)) OVER ()           AS volume_share,
    APPROX_PERCENTILE(active_days, 0.5)                      AS median_active_days,
    APPROX_PERCENTILE(trades * 1.0 / active_days, 0.9)       AS p90_trades_per_active_day   -- bots trade 100s/day
FROM tiered
GROUP BY 1
ORDER BY 1
