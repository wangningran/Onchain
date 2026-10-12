-- Weekly cohort retention (triangle). Cohort = week of first trade on the protocol.
WITH activity AS (
    SELECT DISTINCT tx_from AS trader, DATE_TRUNC('week', block_date) AS week
    FROM dex.trades
    WHERE project = '{{project}}' AND blockchain = '{{blockchain}}'
      AND block_date >= CURRENT_DATE - INTERVAL '{{days}}' DAY
),
cohorts AS (
    SELECT trader, MIN(week) AS cohort_week FROM activity GROUP BY 1
),
sizes AS (
    SELECT cohort_week, COUNT(*) AS cohort_size FROM cohorts GROUP BY 1
)
SELECT
    c.cohort_week,
    DATE_DIFF('week', c.cohort_week, a.week)                      AS weeks_since_first,
    s.cohort_size,
    COUNT(DISTINCT a.trader)                                      AS active,
    CAST(COUNT(DISTINCT a.trader) AS DOUBLE) / s.cohort_size     AS retention
FROM cohorts c
JOIN activity a ON a.trader = c.trader
JOIN sizes s ON s.cohort_week = c.cohort_week
GROUP BY 1, 2, 3
ORDER BY 1, 2
-- NB: wallets first seen in the first week of the window are left-censored (may be old users);
-- extend {{days}} beyond the analysis window or drop the first cohort.
