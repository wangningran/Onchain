-- Which DEXs are biggest on Base (last 30 days)?
SELECT project, version,
       SUM(amount_usd)          AS volume_usd_30d,
       COUNT(DISTINCT tx_from)  AS traders_30d,
       COUNT(*)                 AS trades_30d
FROM dex.trades
WHERE blockchain = 'base'
  AND block_date >= CURRENT_DATE - INTERVAL '30' DAY
GROUP BY 1, 2
ORDER BY volume_usd_30d DESC
LIMIT 15
