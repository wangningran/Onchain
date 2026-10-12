-- Weekly new vs returning traders (first-seen looks back 365 days)
WITH first_seen AS (
    SELECT tx_from AS trader, MIN(block_date) AS first_day
    FROM dex.trades
    WHERE blockchain = 'base' AND project = '{{project}}'
      AND block_date >= CURRENT_DATE - INTERVAL '365' DAY
    GROUP BY 1
),
weekly AS (
    SELECT DISTINCT DATE_TRUNC('week', block_date) AS week, tx_from AS trader
    FROM dex.trades
    WHERE blockchain = 'base' AND project = '{{project}}'
      AND block_date >= CURRENT_DATE - INTERVAL '90' DAY
)
SELECT w.week,
       COUNT(*)                                              AS active_traders,
       COUNT_IF(DATE_TRUNC('week', f.first_day) = w.week)    AS new_traders,
       COUNT_IF(DATE_TRUNC('week', f.first_day) < w.week)    AS returning_traders
FROM weekly w
JOIN first_seen f ON f.trader = w.trader
GROUP BY 1
ORDER BY 1
