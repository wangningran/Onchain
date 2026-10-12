-- North-star daily metrics. "user" metrics exclude labelled bots / protocol wallets and
-- contract callers; sybil filtering happens downstream in Python (needs clustering).
with pools as (
    select day,
           sum(tvl_usd)                 as tvl_usd,
           sum(volume_usd)              as volume_usd,
           sum(user_volume_usd)         as user_volume_usd,
           sum(fees_usd)                as fees_usd,
           sum(swaps)                   as swaps,
           sum(liquidity_added_usd)     as liquidity_added_usd,
           sum(liquidity_removed_usd)   as liquidity_removed_usd
    from {{ ref('fct_pool_daily') }}
    group by 1
),
users as (
    select block_date as day,
           count(distinct trader)                                                as active_traders,
           count(distinct case when is_first_swap_day then trader end)          as new_traders,
           count(*)                                                              as user_swaps,
           median(amount_usd)                                                    as median_trade_usd
    from {{ ref('fct_swaps') }}
    where is_user
    group by 1
)
select
    p.day,
    p.tvl_usd,
    p.volume_usd,
    p.user_volume_usd,
    p.volume_usd - p.user_volume_usd                         as non_user_volume_usd,
    p.fees_usd,
    p.fees_usd / nullif(p.tvl_usd, 0) * 365                  as fee_apr,
    p.swaps,
    p.liquidity_added_usd - p.liquidity_removed_usd          as net_liquidity_flow_usd,
    coalesce(u.active_traders, 0)                            as active_traders,
    coalesce(u.new_traders, 0)                               as new_traders,
    coalesce(u.active_traders, 0) - coalesce(u.new_traders, 0) as returning_traders,
    u.user_swaps,
    u.median_trade_usd,
    avg(p.volume_usd) over (order by p.day rows between 6 preceding and current row)               as volume_usd_7d_avg,
    avg(coalesce(u.active_traders,0)) over (order by p.day rows between 6 preceding and current row) as active_traders_7d_avg
from pools p
left join users u using (day)
order by p.day
