-- Holder distribution of an ERC20 from the full transfer history.  Param: {{token}}
WITH flows AS (
    SELECT "to" AS holder, amount FROM tokens.transfers WHERE blockchain = 'ethereum' AND contract_address = {{token}}
    UNION ALL
    SELECT "from", -amount FROM tokens.transfers WHERE blockchain = 'ethereum' AND contract_address = {{token}}
),
bal AS (
    SELECT holder, SUM(amount) AS balance
    FROM flows
    WHERE holder <> 0x0000000000000000000000000000000000000000
    GROUP BY 1
    HAVING SUM(amount) > 1e-9
),
ranked AS (
    SELECT holder, balance,
           ROW_NUMBER() OVER (ORDER BY balance DESC)              AS rnk,
           balance / SUM(balance) OVER ()                         AS share,
           SUM(balance) OVER (ORDER BY balance DESC ROWS UNBOUNDED PRECEDING) / SUM(balance) OVER () AS cum_share
    FROM bal
)
SELECT
    COUNT(*)                                      AS holders,
    SUM(CASE WHEN rnk <= 10  THEN share END)      AS top10_share,
    SUM(CASE WHEN rnk <= 100 THEN share END)      AS top100_share,
    MIN(CASE WHEN cum_share > 0.5 THEN rnk END)   AS nakamoto_coefficient
FROM ranked
-- Exclude contracts (pools, vesting, bridges, CEX) before drawing conclusions: join labels / ethereum.contracts.
