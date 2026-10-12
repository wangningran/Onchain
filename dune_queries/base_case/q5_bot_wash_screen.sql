-- Bot / wash-trading screen, last 30 days: share of volume by behavioural flag
WITH t AS (
    SELECT tx_from AS trader, project_contract_address AS pool,
           COUNT(*)                                   AS trades,
           COUNT(DISTINCT block_date)                 AS active_days,
           SUM(amount_usd)                            AS gross_usd,
           ABS(SUM(CASE WHEN token_bought_symbol = SPLIT_PART(token_pair, '-', 1)
                        THEN amount_usd ELSE -amount_usd END)) AS net_usd
    FROM dex.trades
    WHERE blockchain = 'base' AND project = '{{project}}'
      AND block_date >= CURRENT_DATE - INTERVAL '30' DAY
      AND amount_usd IS NOT NULL AND amount_usd < 1e8
    GROUP BY 1, 2
),
flagged AS (
    SELECT *,
           CASE WHEN trades * 1.0 / active_days > 100           THEN 'bot_suspect (>100 trades/day)'
                WHEN trades >= 50 AND net_usd / gross_usd < 0.05 THEN 'wash_suspect (net~0)'
                ELSE 'normal' END AS flag
    FROM t
)
SELECT flag,
       COUNT(DISTINCT trader)                            AS traders,
       SUM(gross_usd)                                    AS volume_usd,
       SUM(gross_usd) / SUM(SUM(gross_usd)) OVER ()      AS volume_share
FROM flagged
GROUP BY 1
ORDER BY volume_usd DESC
