-- Screen for wash trading (self-offsetting flow) and bots (very high frequency, non-router tx_to).
-- For each trader x pool: gross volume vs |net| volume in USD.  Net ~ 0 with large gross = suspicious.
WITH flows AS (
    SELECT
        tx_from AS trader,
        project_contract_address AS pool,
        token_pair,
        amount_usd,
        -- +usd when buying the pair's "first" token alphabetically, -usd when selling it
        CASE WHEN token_bought_symbol = SPLIT_PART(token_pair, '-', 1) THEN amount_usd ELSE -amount_usd END AS signed_usd,
        block_date,
        tx_to
    FROM dex.trades
    WHERE project = '{{project}}' AND blockchain = '{{blockchain}}'
      AND block_date >= CURRENT_DATE - INTERVAL '{{days}}' DAY
      AND amount_usd IS NOT NULL
)
SELECT
    trader, pool, token_pair,
    COUNT(*)                                     AS trades,
    COUNT(DISTINCT block_date)                   AS active_days,
    SUM(amount_usd)                              AS gross_usd,
    ABS(SUM(signed_usd))                         AS net_usd,
    ABS(SUM(signed_usd)) / SUM(amount_usd)       AS net_ratio,
    COUNT(*) * 1.0 / COUNT(DISTINCT block_date)  AS trades_per_day,
    COUNT(DISTINCT tx_to)                        AS distinct_tx_to,
    CASE
        WHEN ABS(SUM(signed_usd)) / SUM(amount_usd) < 0.05 AND COUNT(*) >= 50 THEN 'wash_suspect'
        WHEN COUNT(*) * 1.0 / COUNT(DISTINCT block_date) > 100            THEN 'bot_suspect'
        ELSE 'ok'
    END                                          AS flag
FROM flows
GROUP BY 1, 2, 3
HAVING SUM(amount_usd) > 100000
ORDER BY gross_usd DESC
LIMIT 500
-- Next step for wash suspects: pull each wallet's first ETH funder from ethereum.traces / ethereum.transactions
-- and look for rings sharing a funder (see query 07).
