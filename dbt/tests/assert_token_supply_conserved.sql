-- Sum of all non-zero-address balances must equal minted supply (Transfer accounting is complete).
with minted as (
    select sum(amount) as supply from {{ ref('int_token_transfers') }}
    where symbol = 'DEMO' and from_address = '0x0000000000000000000000000000000000000000'
)
select b.total, m.supply
from (select sum(balance) as total from {{ ref('fct_token_balances') }}) b, minted m
where abs(b.total - m.supply) / m.supply > 1e-6
