-- Airdrop sell-through is attributed only up to the amount claimed.
select * from {{ ref('fct_airdrop_claims') }}
where sold_7d > claimed_amount * (1 + 1e-9) or sold_24h > sold_7d * (1 + 1e-9) or sell_through_7d > 1
