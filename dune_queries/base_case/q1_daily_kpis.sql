-- Daily volume / trades / traders, last 90 days
SELECT block_date                          AS day,
       SUM(amount_usd)                     AS volume_usd,
       COUNT(*)                            AS trades,
       COUNT(DISTINCT tx_from)             AS traders,
       APPROX_PERCENTILE(amount_usd, 0.5)  AS median_trade_usd
FROM dex.trades
WHERE blockchain = 'base' AND project = '{{project}}'
  AND block_date >= CURRENT_DATE - INTERVAL '90' DAY
  AND amount_usd IS NOT NULL AND amount_usd < 1e8
GROUP BY 1
ORDER BY 1
