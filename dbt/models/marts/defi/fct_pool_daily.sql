with vol as (
    select pool_address, block_date as day,
           count(*)                                         as swaps,
           count(distinct trader)                           as traders,
           sum(amount_usd)                                  as volume_usd,
           sum(case when is_user then amount_usd else 0 end) as user_volume_usd,
           sum(lp_fee_usd)                                  as fees_usd
    from {{ ref('fct_swaps') }}
    group by 1, 2
),
liq as (
    select pool_address, block_date as day,
           sum(case when event_type = 'add' then amount_usd else 0 end)    as liquidity_added_usd,
           sum(case when event_type = 'remove' then amount_usd else 0 end) as liquidity_removed_usd
    from {{ ref('int_liquidity_events') }}
    group by 1, 2
)
select
    r.day, r.pool_address, r.pool_name,
    r.reserve0, r.reserve1,
    r.tvl_usd,
    coalesce(v.swaps, 0)                         as swaps,
    coalesce(v.traders, 0)                       as traders,
    coalesce(v.volume_usd, 0)                    as volume_usd,
    coalesce(v.user_volume_usd, 0)               as user_volume_usd,
    coalesce(v.fees_usd, 0)                      as fees_usd,
    coalesce(l.liquidity_added_usd, 0)           as liquidity_added_usd,
    coalesce(l.liquidity_removed_usd, 0)         as liquidity_removed_usd,
    coalesce(v.volume_usd, 0) / nullif(r.tvl_usd, 0)            as volume_tvl_ratio,
    coalesce(v.fees_usd, 0) / nullif(r.tvl_usd, 0) * 365        as fee_apr
from {{ ref('int_pool_reserves_daily') }} r
left join vol v on v.pool_address = r.pool_address and v.day = r.day
left join liq l on l.pool_address = r.pool_address and l.day = r.day
