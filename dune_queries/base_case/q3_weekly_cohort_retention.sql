-- Weekly cohort retention for traders whose first trade (365d lookback) is within the last 90 days
WITH first_seen AS (
    SELECT tx_from AS trader, DATE_TRUNC('week', MIN(block_date)) AS cohort_week
    FROM dex.trades
    WHERE blockchain = 'base' AND project = '{{project}}'
      AND block_date >= CURRENT_DATE - INTERVAL '365' DAY
    GROUP BY 1
),
cohorts AS (
    SELECT * FROM first_seen
    WHERE cohort_week >= DATE_TRUNC('week', CURRENT_DATE - INTERVAL '90' DAY)
),
activity AS (
    SELECT DISTINCT tx_from AS trader, DATE_TRUNC('week', block_date) AS week
    FROM dex.trades
    WHERE blockchain = 'base' AND project = '{{project}}'
      AND block_date >= CURRENT_DATE - INTERVAL '90' DAY
),
sizes AS (SELECT cohort_week, COUNT(*) AS cohort_size FROM cohorts GROUP BY 1)
SELECT c.cohort_week,
       DATE_DIFF('week', c.cohort_week, a.week)        AS weeks_since_first,
       s.cohort_size,
       COUNT(*)                                        AS active,
       CAST(COUNT(*) AS DOUBLE) / s.cohort_size        AS retention
FROM cohorts c
JOIN activity a ON a.trader = c.trader AND a.week >= c.cohort_week
JOIN sizes s    ON s.cohort_week = c.cohort_week
GROUP BY 1, 2, 3
ORDER BY 1, 2
