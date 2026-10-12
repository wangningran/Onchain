-- Day-over-day TVL change should be explained by price moves + net liquidity flows; flag
-- days where the unexplained part is > 25% of TVL (would indicate missing Sync/Mint/Burn).
with d as (
    select pool_address, day, tvl_usd, reserve0, reserve1,
           lag(reserve0) over (partition by pool_address order by day) as prev_r0,
           lag(reserve1) over (partition by pool_address order by day) as prev_r1,
           liquidity_added_usd - liquidity_removed_usd as net_flow
    from {{ ref('fct_pool_daily') }}
)
select d.*
from d
join {{ ref('stg_pools') }} p using (pool_address)
join {{ ref('stg_prices_daily') }} p0 on p0.token_address = p.token0_address and p0.day = d.day
join {{ ref('stg_prices_daily') }} p1 on p1.token_address = p.token1_address and p1.day = d.day
where prev_r0 is not null
  and abs(d.tvl_usd - (prev_r0 * p0.price_usd + prev_r1 * p1.price_usd) - net_flow) > 0.25 * d.tvl_usd
