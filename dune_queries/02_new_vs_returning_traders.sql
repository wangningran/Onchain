-- New vs returning traders per week. First-seen date must be computed over FULL history,
-- not just the reporting window, otherwise every old user looks "new" on day 1.
WITH first_seen AS (
    SELECT tx_from AS trader, MIN(block_date) AS first_day
    FROM dex.trades
    WHERE project = '{{project}}' AND blockchain = '{{blockchain}}'
    GROUP BY 1
),
weekly AS (
    SELECT DISTINCT DATE_TRUNC('week', block_date) AS week, tx_from AS trader
    FROM dex.trades
    WHERE project = '{{project}}' AND blockchain = '{{blockchain}}'
      AND block_date >= CURRENT_DATE - INTERVAL '{{days}}' DAY
)
SELECT
    w.week,
    COUNT(*)                                                                    AS active_traders,
    COUNT_IF(DATE_TRUNC('week', f.first_day) = w.week)                          AS new_traders,
    COUNT_IF(DATE_TRUNC('week', f.first_day) < w.week)                          AS returning_traders,
    CAST(COUNT_IF(DATE_TRUNC('week', f.first_day) < w.week) AS DOUBLE) / COUNT(*) AS returning_share
FROM weekly w
JOIN first_seen f ON f.trader = w.trader
GROUP BY 1
ORDER BY 1
