-- Sybil / ring detection: group wallets by their FIRST inbound ETH funder.  Param: {{wallets_query}} = a query id
-- that returns a `wallet` column (e.g. airdrop recipients); referenced with Dune's query_<id> syntax.
WITH wallets AS (
    SELECT wallet FROM query_{{wallets_query}}
),
first_fund AS (
    SELECT
        t."to"                                        AS wallet,
        MIN_BY(t."from", t.block_time)                AS funder,
        MIN(t.block_time)                             AS funded_at,
        MIN_BY(t.value, t.block_time) / 1e18          AS first_value_eth
    FROM ethereum.transactions t
    JOIN wallets w ON w.wallet = t."to"
    WHERE t.value > 0 AND t.success
    GROUP BY 1
)
SELECT
    f.funder,
    COALESCE(c.cex_name, 'unlabelled')                                AS funder_label,   -- CEX hot wallets fund everyone: not a sybil signal
    COUNT(*)                                                          AS wallets_funded,
    DATE_DIFF('minute', MIN(f.funded_at), MAX(f.funded_at))          AS funding_window_min,
    APPROX_PERCENTILE(f.first_value_eth, 0.5)                         AS median_seed_eth,
    STDDEV(f.first_value_eth) / NULLIF(AVG(f.first_value_eth), 0)    AS seed_cv               -- identical seed amounts = scripted
FROM first_fund f
LEFT JOIN cex.addresses c ON c.address = f.funder AND c.blockchain = 'ethereum'
GROUP BY 1, 2
HAVING COUNT(*) >= 10
ORDER BY wallets_funded DESC
