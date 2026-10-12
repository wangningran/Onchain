-- Holder count per day via balance state transitions (0 -> >0 = +1, >0 -> 0 = -1).
with deltas as (
    select to_address as holder, block_date as day, amount from {{ ref('int_token_transfers') }} where symbol = 'DEMO'
    union all
    select from_address, block_date, -amount from {{ ref('int_token_transfers') }} where symbol = 'DEMO'
),
daily as (
    select holder, day, sum(amount) as delta from deltas
    where holder <> '0x0000000000000000000000000000000000000000'
    group by 1, 2
),
bal as (
    select holder, day, sum(delta) over (partition by holder order by day) as balance
    from daily
),
transitions as (
    select day,
           case when balance > 1e-9 and coalesce(lag(balance) over (partition by holder order by day), 0) <= 1e-9 then 1
                when balance <= 1e-9 and coalesce(lag(balance) over (partition by holder order by day), 0) > 1e-9 then -1
                else 0 end as change
    from bal
)
select day, sum(sum(change)) over (order by day) as holders, sum(change) as net_new_holders
from transitions
group by day
order by day
