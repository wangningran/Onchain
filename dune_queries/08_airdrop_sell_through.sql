-- Airdrop effectiveness: how much of the claimed token was sold within 1 / 7 / 30 days?
-- Params: {{token}} (0x token address), {{distributor}} (0x airdrop / merkle distributor address)
WITH claims AS (
    SELECT "to" AS recipient, MIN(block_time) AS claimed_at, SUM(amount) AS claimed
    FROM tokens.transfers
    WHERE blockchain = 'ethereum' AND contract_address = {{token}} AND "from" = {{distributor}}
    GROUP BY 1
),
sells AS (
    SELECT c.recipient,
           SUM(CASE WHEN d.block_time <= c.claimed_at + INTERVAL '1' DAY  THEN d.token_sold_amount ELSE 0 END) AS sold_1d,
           SUM(CASE WHEN d.block_time <= c.claimed_at + INTERVAL '7' DAY  THEN d.token_sold_amount ELSE 0 END) AS sold_7d,
           SUM(CASE WHEN d.block_time <= c.claimed_at + INTERVAL '30' DAY THEN d.token_sold_amount ELSE 0 END) AS sold_30d
    FROM claims c
    JOIN dex.trades d ON d.blockchain = 'ethereum' AND d.token_sold_address = {{token}}
                     AND d.tx_from = c.recipient AND d.block_time >= c.claimed_at
    GROUP BY 1
)
SELECT
    COUNT(*)                                                    AS recipients,
    SUM(c.claimed)                                              AS claimed_tokens,
    SUM(COALESCE(s.sold_1d, 0))  / SUM(c.claimed)               AS sell_through_1d,
    SUM(COALESCE(s.sold_7d, 0))  / SUM(c.claimed)               AS sell_through_7d,
    SUM(COALESCE(s.sold_30d, 0)) / SUM(c.claimed)               AS sell_through_30d,
    COUNT_IF(COALESCE(s.sold_7d, 0) >= 0.9 * c.claimed) * 1.0 / COUNT(*) AS share_full_dumpers_7d
FROM claims c
LEFT JOIN sells s ON s.recipient = c.recipient
-- Caveat: sells routed via CEX deposits or bridges are invisible here; add tokens.transfers to cex.addresses.
