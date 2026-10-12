-- Current DEMO balance per holder from the full Transfer history (zero address = mint/burn).
with flows as (
    select to_address as holder, symbol, amount from {{ ref('int_token_transfers') }} where symbol = 'DEMO'
    union all
    select from_address, symbol, -amount from {{ ref('int_token_transfers') }} where symbol = 'DEMO'
)
select
    f.holder,
    sum(f.amount)                                             as balance,
    coalesce(lb.label, case when p.pool_address is not null then 'amm_pool' end, 'wallet') as holder_type
from flows f
left join {{ ref('stg_labels') }} lb on lb.address = f.holder
left join {{ ref('stg_pools') }} p on p.pool_address = f.holder
where f.holder <> '0x0000000000000000000000000000000000000000'
group by f.holder, lb.label, p.pool_address
having sum(f.amount) > 1e-9
