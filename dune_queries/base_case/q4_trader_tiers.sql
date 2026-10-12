-- Who generates the volume? Value tiers, last 30 days
WITH t AS (
    SELECT tx_from AS trader, SUM(amount_usd) AS volume_usd,
           COUNT(*) AS trades, COUNT(DISTINCT block_date) AS active_days
    FROM dex.trades
    WHERE blockchain = 'base' AND project = '{{project}}'
      AND block_date >= CURRENT_DATE - INTERVAL '30' DAY
      AND amount_usd IS NOT NULL AND amount_usd < 1e8
    GROUP BY 1
)
SELECT CASE WHEN volume_usd < 1e3 THEN '1 <1k'
            WHEN volume_usd < 1e4 THEN '2 1k-10k'
            WHEN volume_usd < 1e5 THEN '3 10k-100k'
            WHEN volume_usd < 1e6 THEN '4 100k-1m'
            ELSE '5 >1m' END                                   AS tier,
       COUNT(*)                                                AS traders,
       CAST(COUNT(*) AS DOUBLE) / SUM(COUNT(*)) OVER ()        AS trader_share,
       SUM(volume_usd)                                         AS volume_usd,
       SUM(volume_usd) / SUM(SUM(volume_usd)) OVER ()          AS volume_share,
       APPROX_PERCENTILE(trades * 1.0 / active_days, 0.9)      AS p90_trades_per_day
FROM t
GROUP BY 1
ORDER BY 1
