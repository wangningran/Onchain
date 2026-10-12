-- Airdrop claims and how much each recipient dumped within 7 days (sell-through).
with distributor as (select address from {{ ref('stg_labels') }} where label = 'airdrop_distributor'),
claims as (
    select to_address as recipient, min(block_time) as claimed_at, sum(amount) as claimed_amount
    from {{ ref('int_token_transfers') }}
    where symbol = 'DEMO' and from_address in (select address from distributor)
    group by 1
),
sells as (
    select c.recipient,
           sum(case when s.block_time <= c.claimed_at + interval 1 day then s.amount_sold else 0 end) as sold_24h,
           sum(case when s.block_time <= c.claimed_at + interval 7 day then s.amount_sold else 0 end) as sold_7d,
           sum(case when s.block_time <= c.claimed_at + interval 7 day then s.amount_usd  else 0 end) as sold_7d_usd
    from claims c
    join {{ ref('fct_swaps') }} s on s.trader = c.recipient and s.token_sold_symbol = 'DEMO' and s.block_time >= c.claimed_at
    group by 1
)
select
    c.recipient,
    c.claimed_at,
    datediff('minute', timestamp '{{ var("airdrop_date") }}', c.claimed_at) as minutes_to_claim,
    c.claimed_amount,
    -- cap at the claimed amount: recipients may also sell tokens they held before the airdrop
    least(coalesce(s.sold_24h, 0), c.claimed_amount)                       as sold_24h,
    least(coalesce(s.sold_7d, 0), c.claimed_amount)                        as sold_7d,
    coalesce(s.sold_7d_usd, 0) * least(1, c.claimed_amount / nullif(s.sold_7d, 0)) as sold_7d_usd,
    least(coalesce(s.sold_7d, 0) / c.claimed_amount, 1)                    as sell_through_7d
from claims c
left join sells s using (recipient)
